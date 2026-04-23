"""Stage 9 — AI Review service (Claude Opus 4.7 via LiteLLM).

An independent second-pass reviewer reads the whole workspace after the
construct is released and signs a structured letter: verdict, per-category
grades, findings, top risks, next actions. The operator accepts or
overrides; that decision is stamped into the stage-8 audit trail via the
shared workspace config.

Provider-agnostic by design — we pass whatever model string is in
``CANCERSTUDIO_REVIEW_MODEL`` (default ``anthropic/claude-opus-4-7``) to
LiteLLM and let it resolve the provider key from env (``ANTHROPIC_API_KEY``,
``OPENAI_API_KEY``, etc.) per LiteLLM convention.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from app.db import session_scope
from app.models.schemas import (
    AiReviewAction,
    AiReviewBriefConstruct,
    AiReviewBriefCoverage,
    AiReviewBriefPeptide,
    AiReviewBriefVariants,
    AiReviewCaseBrief,
    AiReviewCategory,
    AiReviewDecision,
    AiReviewFinding,
    AiReviewResult,
    AiReviewStageStatus,
    AiReviewStageSummaryResponse,
    ConstructOutputStatus,
)
from app.services.construct_design import load_construct_stage_summary
from app.services.construct_output import load_construct_output_summary
from app.services.epitope_selection import load_epitope_stage_summary
from app.services.variant_calling import load_variant_calling_stage_summary
from app.services.workspace_store import (
    get_workspace_record,
    load_workspace_ai_review_config,
    store_workspace_ai_review_config,
    utc_now,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-opus-4-7"

# LiteLLM resolves provider keys by convention. This table only powers the
# blocked-summary message — we never hand any key to LiteLLM ourselves. If a
# prefix is missing from the table we don't pre-check and let LiteLLM raise
# on the first call.
PROVIDER_KEY_BY_PREFIX: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "vertex_ai": "GOOGLE_APPLICATION_CREDENTIALS",
}


class AiReviewCallError(RuntimeError):
    """Raised when the LiteLLM call or JSON extraction fails."""


# ── Public API ────────────────────────────────────────────────────────────


def load_ai_review_summary(workspace_id: str) -> AiReviewStageSummaryResponse:
    """Return the current review status for a workspace."""

    model = _configured_model()
    blocked = _blocking_reason(workspace_id, model)
    if blocked is not None:
        return _summary(
            workspace_id=workspace_id,
            status=blocked.status,
            blocking_reason=blocked.reason,
            model=model,
            brief=None,
            result=None,
            decision=None,
            last_error=None,
        )

    brief = _build_case_brief(workspace_id)
    config = _read_config(workspace_id)
    result = _result_from_config(config)
    decision = _decision_from_config(config)

    status = (
        AiReviewStageStatus.COMPLETED if result is not None else AiReviewStageStatus.IDLE
    )
    return _summary(
        workspace_id=workspace_id,
        status=status,
        blocking_reason=None,
        model=model,
        brief=brief,
        result=result,
        decision=decision,
        last_error=config.get("last_error"),
    )


def update_ai_review(
    workspace_id: str, payload: AiReviewAction
) -> AiReviewStageSummaryResponse:
    """Dispatch a review action: run / accept / override / reset."""

    model = _configured_model()
    blocked = _blocking_reason(workspace_id, model)
    if blocked is not None:
        raise AiReviewCallError(blocked.reason)

    if payload.action == "run":
        return _run_review(workspace_id, model)
    if payload.action == "reset":
        return _reset(workspace_id)
    if payload.action == "accept":
        return _record_decision(workspace_id, kind="accept", reason=None)
    if payload.action == "override":
        reason = (payload.reason or "").strip()
        if not reason:
            raise ValueError("Override requires a reason.")
        return _record_decision(workspace_id, kind="override", reason=reason)

    raise ValueError(f"Unknown action: {payload.action}")  # pragma: no cover


# ── Blocking / config helpers ─────────────────────────────────────────────


class _Blocked:
    __slots__ = ("status", "reason")

    def __init__(self, status: AiReviewStageStatus, reason: str) -> None:
        self.status = status
        self.reason = reason


def _configured_model() -> str:
    return os.environ.get("CANCERSTUDIO_REVIEW_MODEL", DEFAULT_MODEL)


def _expected_provider_key(model: str) -> Optional[str]:
    prefix = model.split("/", 1)[0] if "/" in model else ""
    return PROVIDER_KEY_BY_PREFIX.get(prefix)


def _blocking_reason(workspace_id: str, model: str) -> Optional[_Blocked]:
    try:
        output_summary = load_construct_output_summary(workspace_id)
    except Exception as exc:  # pragma: no cover — only if upstream explodes
        logger.warning("ai-review: could not load construct output: %s", exc)
        return _Blocked(
            AiReviewStageStatus.BLOCKED,
            "Release the construct output before requesting the AI review.",
        )

    if output_summary.status != ConstructOutputStatus.RELEASED:
        return _Blocked(
            AiReviewStageStatus.BLOCKED,
            "Release the construct output before requesting the AI review.",
        )

    key_name = _expected_provider_key(model)
    if key_name and not os.environ.get(key_name):
        return _Blocked(
            AiReviewStageStatus.SCAFFOLDED,
            f"Set {key_name} on the backend to enable Stage 9 (model={model}).",
        )

    return None


def _read_config(workspace_id: str) -> dict:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        return load_workspace_ai_review_config(workspace)


def _write_config(workspace_id: str, mutator) -> dict:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        existing = load_workspace_ai_review_config(workspace)
        if not isinstance(existing, dict):
            existing = {}
        updated = mutator(existing) or existing
        store_workspace_ai_review_config(workspace, updated)
        workspace.updated_at = utc_now()
        session.add(workspace)
        return updated


# ── Brief assembly ────────────────────────────────────────────────────────


def _build_case_brief(workspace_id: str) -> AiReviewCaseBrief:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        patient_name = workspace.display_name
        species = workspace.species
        reference = workspace.reference_preset or ""

    variant_summary = load_variant_calling_stage_summary(workspace_id)
    vm = variant_summary.metrics

    epitope_summary = load_epitope_stage_summary(workspace_id)
    candidate_by_id = {c.id: c for c in epitope_summary.candidates}
    selection_ids = (
        list(epitope_summary.selection)
        or list(epitope_summary.default_picks)
    )
    picked = [candidate_by_id[i] for i in selection_ids if i in candidate_by_id]

    shortlist = [
        AiReviewBriefPeptide(
            seq=p.seq,
            gene=p.gene,
            mut=p.mutation,
            cls=p.mhc_class.value if hasattr(p.mhc_class, "value") else str(p.mhc_class),
            allele=p.allele_id,
            ic50_nM=p.ic50_nm,
            vaf=p.vaf,
            cancer_gene=p.cancer_gene,
            driver=bool(p.driver_context),
        )
        for p in picked
    ]

    coverage = AiReviewBriefCoverage(
        alleles=sorted({p.allele for p in shortlist if p.allele}),
        classI=sum(1 for p in shortlist if p.cls == "I"),
        classII=sum(1 for p in shortlist if p.cls == "II"),
        uniqueGenes=sorted({p.gene for p in shortlist if p.gene}),
    )

    construct_summary = load_construct_stage_summary(workspace_id)
    output_summary = load_construct_output_summary(workspace_id)

    construct_block = AiReviewBriefConstruct(
        id=output_summary.construct_id,
        version=output_summary.version,
        checksum=output_summary.checksum,
        aaLen=construct_summary.metrics.aa_len,
        ntLen=construct_summary.metrics.nt_len,
        cai=construct_summary.metrics.cai,
        gc=construct_summary.metrics.gc,
        mfe=float(construct_summary.metrics.mfe),
    )

    variants = AiReviewBriefVariants.model_validate(
        {
            "total": vm.total_variants,
            "pass": vm.pass_count,
            "snv": vm.snv_count,
            "indel": vm.indel_count,
            "median_vaf": vm.median_vaf,
            "tumor_depth": vm.tumor_mean_depth,
            "normal_depth": vm.normal_mean_depth,
        }
    )

    return AiReviewCaseBrief(
        patient_id=workspace_id,
        patient_name=patient_name,
        species=species,
        reference=reference,
        variants=variants,
        shortlist=shortlist,
        coverage=coverage,
        construct=construct_block,
    )


# ── LiteLLM call ──────────────────────────────────────────────────────────


def _build_prompt(brief: AiReviewCaseBrief) -> tuple[str, str]:
    system = (
        "You are Claude Opus 4.7 acting as an independent reviewer of a "
        "personalized cancer mRNA vaccine construct. You have complete "
        "oversight of the full workspace.\n\n"
        "Your job: review the workspace for validity and recommend "
        "go / hold / block for release.\n\n"
        "Return ONLY a single valid JSON object, no prose before or after, "
        "matching this exact schema:\n\n"
        "{\n"
        '  "verdict": "approve" | "approve_with_notes" | "hold" | "block",\n'
        '  "confidence": 0-100,\n'
        '  "headline": "one sentence verdict",\n'
        '  "letter": "2-3 short paragraphs, plain English, speaking directly '
        "to the designer. Be concrete and specific to THIS case.\",\n"
        '  "categories": [\n'
        '    { "id": "validity" | "safety" | "coverage" | "manufact",\n'
        '      "grade": "A" | "B" | "C" | "D",\n'
        '      "verdict": "pass" | "watch" | "concern",\n'
        '      "summary": "one sentence",\n'
        '      "findings": [\n'
        '        { "severity": "info" | "note" | "watch" | "concern",\n'
        '          "title": "short title (~6 words)",\n'
        '          "detail": "1-2 sentence detail referring to specific '
        "peptides / genes / numbers from the brief\" }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "topRisks": ["short phrase", "short phrase", "short phrase"],\n'
        '  "nextActions": ["short phrase", "short phrase"]\n'
        "}\n\n"
        "Be direct. Cite specific peptides by gene and mutation. Call out "
        "weak spots. If everything looks good, say so plainly.\n\n"
        "CRITICAL: Output ONLY the JSON object. No markdown fences, no prose "
        "before or after. Start with { and end with }."
    )

    brief_json = json.dumps(
        brief.model_dump(by_alias=True, exclude_none=True),
        indent=2,
        default=str,
    )
    user = (
        f"Here is the full case brief for {brief.patient_name}:\n\n"
        f"{brief_json}\n\n"
        "Review this. Return the JSON object only."
    )
    return system, user


def _call_llm(model: str, system: str, user: str) -> AiReviewResult:
    from litellm import completion  # imported lazily so tests can patch

    messages = [{"role": "user", "content": f"{system}\n\n{user}"}]
    raw = _complete(completion, model, messages)
    parsed = _extract_review_json(raw)
    if parsed is None:
        messages.append({"role": "assistant", "content": str(raw)[:3000]})
        messages.append(
            {
                "role": "user",
                "content": (
                    "That response could not be parsed as JSON. Return ONLY "
                    "the JSON object, no prose, no markdown fences."
                ),
            }
        )
        raw = _complete(completion, model, messages)
        parsed = _extract_review_json(raw)

    if parsed is None:
        raise AiReviewCallError("Model response was not valid JSON after one retry.")

    return _validate_result(parsed, model=model)


def _complete(completion, model: str, messages: list[dict]) -> str:
    try:
        resp = completion(model=model, messages=messages, max_tokens=4096)
    except Exception as exc:
        raise AiReviewCallError(f"LiteLLM call failed: {exc}") from exc
    try:
        return resp.choices[0].message.content or ""
    except Exception as exc:  # pragma: no cover — unexpected shape
        raise AiReviewCallError(f"Unexpected LiteLLM response shape: {exc}") from exc


def _extract_review_json(raw: str) -> Optional[dict]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"```\s*$", "", s)
    first = s.find("{")
    last = s.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    try:
        return json.loads(s[first : last + 1])
    except json.JSONDecodeError:
        return None


def _validate_result(parsed: dict, *, model: str) -> AiReviewResult:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "verdict": parsed.get("verdict"),
        "confidence": int(parsed.get("confidence", 0)),
        "headline": str(parsed.get("headline", "")).strip(),
        "letter": str(parsed.get("letter", "")).strip(),
        "categories": [
            AiReviewCategory(
                id=c.get("id"),
                grade=c.get("grade", "B"),
                verdict=c.get("verdict", "watch"),
                summary=str(c.get("summary", "")),
                findings=[
                    AiReviewFinding(
                        severity=f.get("severity", "info"),
                        title=str(f.get("title", "")),
                        detail=str(f.get("detail", "")),
                    )
                    for f in c.get("findings", [])
                ],
            )
            for c in parsed.get("categories", [])
        ],
        "top_risks": [str(r) for r in parsed.get("topRisks", parsed.get("top_risks", []))],
        "next_actions": [
            str(a) for a in parsed.get("nextActions", parsed.get("next_actions", []))
        ],
        "reviewed_at": now,
        "model": model,
    }
    return AiReviewResult.model_validate(payload)


# ── Actions ───────────────────────────────────────────────────────────────


def _run_review(workspace_id: str, model: str) -> AiReviewStageSummaryResponse:
    brief = _build_case_brief(workspace_id)
    system, user = _build_prompt(brief)
    try:
        result = _call_llm(model, system, user)
    except AiReviewCallError as exc:
        _write_config(
            workspace_id,
            lambda cfg: {**cfg, "last_error": str(exc)},
        )
        raise

    def _store(cfg: dict) -> dict:
        cfg["result"] = result.model_dump()
        cfg.pop("decision", None)
        cfg.pop("last_error", None)
        return cfg

    _write_config(workspace_id, _store)
    return load_ai_review_summary(workspace_id)


def _record_decision(
    workspace_id: str, *, kind: str, reason: Optional[str]
) -> AiReviewStageSummaryResponse:
    config = _read_config(workspace_id)
    if "result" not in config:
        raise ValueError("Run a review before accepting or overriding.")

    decision = {
        "kind": kind,
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }

    def _store(cfg: dict) -> dict:
        cfg["decision"] = decision
        return cfg

    _write_config(workspace_id, _store)
    return load_ai_review_summary(workspace_id)


def _reset(workspace_id: str) -> AiReviewStageSummaryResponse:
    def _store(cfg: dict) -> dict:
        cfg.pop("result", None)
        cfg.pop("decision", None)
        cfg.pop("last_error", None)
        return cfg

    _write_config(workspace_id, _store)
    return load_ai_review_summary(workspace_id)


# ── Config → schema adapters ──────────────────────────────────────────────


def _result_from_config(config: dict) -> Optional[AiReviewResult]:
    raw = config.get("result")
    if not isinstance(raw, dict):
        return None
    try:
        return AiReviewResult.model_validate(raw)
    except Exception as exc:  # pragma: no cover
        logger.warning("ai-review: stored result failed validation: %s", exc)
        return None


def _decision_from_config(config: dict) -> Optional[AiReviewDecision]:
    raw = config.get("decision")
    if not isinstance(raw, dict):
        return None
    try:
        return AiReviewDecision.model_validate(raw)
    except Exception as exc:  # pragma: no cover
        logger.warning("ai-review: stored decision failed validation: %s", exc)
        return None


def _summary(
    *,
    workspace_id: str,
    status: AiReviewStageStatus,
    blocking_reason: Optional[str],
    model: str,
    brief: Optional[AiReviewCaseBrief],
    result: Optional[AiReviewResult],
    decision: Optional[AiReviewDecision],
    last_error: Optional[str],
) -> AiReviewStageSummaryResponse:
    return AiReviewStageSummaryResponse(
        workspace_id=workspace_id,
        status=status,
        blocking_reason=blocking_reason,
        model=model,
        brief=brief,
        result=result,
        decision=decision,
        last_error=last_error,
    )
