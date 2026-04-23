"""Tests for the Stage 9 AI Review service.

Full workspace fixtures (all upstream stages completed) are heavy, so we
patch ``_build_case_brief``, ``_blocking_reason``, and the lazy LiteLLM
import. The DB round-trip for config storage uses the real SQLite schema.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable

import pytest

from app.db import init_db, session_scope
from app.models.records import (
    IngestionBatchRecord,
    PipelineArtifactRecord,
    PipelineRunRecord,
    WorkspaceFileRecord,
    WorkspaceRecord,
)
from app.models.schemas import (
    AiReviewAction,
    AiReviewBriefConstruct,
    AiReviewBriefCoverage,
    AiReviewBriefPeptide,
    AiReviewBriefVariants,
    AiReviewCaseBrief,
    AiReviewStageStatus,
)
from app.services import ai_review
from app.services.workspace_store import utc_now

WORKSPACE_ID = "ws-ai-review"


@pytest.fixture(autouse=True)
def _clean_database():
    init_db()
    _wipe()
    yield
    _wipe()


def _wipe() -> None:
    with session_scope() as session:
        for model in (
            PipelineArtifactRecord,
            PipelineRunRecord,
            WorkspaceFileRecord,
            IngestionBatchRecord,
            WorkspaceRecord,
        ):
            session.query(model).delete()


def _create_workspace() -> None:
    now = utc_now()
    with session_scope() as session:
        session.add(
            WorkspaceRecord(
                id=WORKSPACE_ID,
                display_name="Rosie",
                species="dog",
                reference_preset="CanFam4",
                active_stage="ai-review",
                created_at=now,
                updated_at=now,
            )
        )


def _fake_brief() -> AiReviewCaseBrief:
    return AiReviewCaseBrief(
        patient_id=WORKSPACE_ID,
        patient_name="Rosie",
        species="dog",
        reference="CanFam4",
        variants=AiReviewBriefVariants.model_validate(
            {"total": 347, "pass": 312, "snv": 280, "indel": 32, "median_vaf": 0.27}
        ),
        shortlist=[
            AiReviewBriefPeptide(
                seq="KITYASNII", gene="KIT", mut="p.N816I", cls="I",
                allele="DLA-88*034:01", ic50_nM=14.0, vaf=0.47,
                cancer_gene=True, driver=True,
            )
        ],
        coverage=AiReviewBriefCoverage.model_validate(
            {"alleles": ["DLA-88*034:01"], "classI": 1, "classII": 0, "uniqueGenes": ["KIT"]}
        ),
        construct=AiReviewBriefConstruct.model_validate(
            {"id": "ROSIE-MCT-001", "version": "v1", "checksum": "abc123",
             "aaLen": 89, "ntLen": 267, "cai": 0.85, "gc": 58.0}
        ),
    )


CANNED_JSON = {
    "verdict": "approve_with_notes",
    "confidence": 82,
    "headline": "Approve with notes.",
    "letter": "Solid cassette for Rosie.",
    "categories": [
        {
            "id": "validity",
            "grade": "A",
            "verdict": "pass",
            "summary": "Good drivers.",
            "findings": [
                {"severity": "info", "title": "KIT anchor", "detail": "Canonical MCT driver."}
            ],
        }
    ],
    "topRisks": ["Allele concentration on DLA-88*034:01"],
    "nextActions": ["Send to Twist"],
}


def _canned_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _canned_completion(contents: Iterable[str]):
    it = iter(list(contents))

    def _fn(*, model, messages, **kwargs):
        return _canned_response(next(it))

    return _fn


@pytest.fixture
def patched_service(monkeypatch):
    """Short-circuit brief + blocking checks; tests inject their own LiteLLM."""

    _create_workspace()
    monkeypatch.setattr(ai_review, "_build_case_brief", lambda wid: _fake_brief())
    monkeypatch.setattr(ai_review, "_blocking_reason", lambda wid, model: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("CANCERSTUDIO_REVIEW_MODEL", raising=False)
    yield


# ── blocking ──────────────────────────────────────────────────────────────


def test_summary_blocked_when_upstream_not_released(monkeypatch):
    _create_workspace()
    blocked = ai_review._Blocked(
        AiReviewStageStatus.BLOCKED,
        "Release the construct output before requesting the AI review.",
    )
    monkeypatch.setattr(ai_review, "_blocking_reason", lambda wid, model: blocked)

    summary = ai_review.load_ai_review_summary(WORKSPACE_ID)

    assert summary.status == AiReviewStageStatus.BLOCKED
    assert "Release the construct output" in (summary.blocking_reason or "")


def test_summary_scaffolded_when_provider_key_missing_for_default_model(monkeypatch):
    _create_workspace()
    # Upstream released — simulate by patching the construct output loader.
    output_summary = SimpleNamespace(status="released")
    monkeypatch.setattr(
        ai_review, "load_construct_output_summary", lambda wid: output_summary
    )
    # ensure we're using the anthropic default
    monkeypatch.delenv("CANCERSTUDIO_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Import the real enum used in _blocking_reason comparison.
    from app.models.schemas import ConstructOutputStatus

    output_summary.status = ConstructOutputStatus.RELEASED

    summary = ai_review.load_ai_review_summary(WORKSPACE_ID)

    assert summary.status == AiReviewStageStatus.SCAFFOLDED
    assert "ANTHROPIC_API_KEY" in (summary.blocking_reason or "")


def test_summary_scaffolded_names_openai_key_when_model_overridden(monkeypatch):
    _create_workspace()
    from app.models.schemas import ConstructOutputStatus

    output_summary = SimpleNamespace(status=ConstructOutputStatus.RELEASED)
    monkeypatch.setattr(
        ai_review, "load_construct_output_summary", lambda wid: output_summary
    )
    monkeypatch.setenv("CANCERSTUDIO_REVIEW_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    summary = ai_review.load_ai_review_summary(WORKSPACE_ID)

    assert summary.status == AiReviewStageStatus.SCAFFOLDED
    assert "OPENAI_API_KEY" in (summary.blocking_reason or "")
    assert "openai/gpt-4o" in (summary.blocking_reason or "")


# ── run / retry ───────────────────────────────────────────────────────────


def test_run_success_persists_result(monkeypatch, patched_service):
    import json

    fake = _canned_completion([json.dumps(CANNED_JSON)])
    import litellm  # import lazily to shadow

    monkeypatch.setattr(litellm, "completion", fake, raising=False)

    summary = ai_review.update_ai_review(
        WORKSPACE_ID, AiReviewAction(action="run")
    )

    assert summary.status == AiReviewStageStatus.COMPLETED
    assert summary.result is not None
    assert summary.result.verdict == "approve_with_notes"
    assert summary.result.confidence == 82
    assert summary.result.categories[0].findings[0].title == "KIT anchor"
    assert summary.brief is not None  # brief echoed for client rendering


def test_run_retries_on_malformed_then_succeeds(monkeypatch, patched_service):
    import json

    fake = _canned_completion(
        [
            "I cannot emit JSON sorry",  # first pass — unparseable
            "```json\n" + json.dumps(CANNED_JSON) + "\n```",  # retry, fenced but parseable
        ]
    )
    import litellm

    monkeypatch.setattr(litellm, "completion", fake, raising=False)

    summary = ai_review.update_ai_review(
        WORKSPACE_ID, AiReviewAction(action="run")
    )

    assert summary.result is not None
    assert summary.result.verdict == "approve_with_notes"


def test_run_raises_call_error_after_retry(monkeypatch, patched_service):
    fake = _canned_completion(["not json", "still not json"])
    import litellm

    monkeypatch.setattr(litellm, "completion", fake, raising=False)

    with pytest.raises(ai_review.AiReviewCallError):
        ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="run"))


# ── decision flow ─────────────────────────────────────────────────────────


def test_accept_records_decision(monkeypatch, patched_service):
    import json

    fake = _canned_completion([json.dumps(CANNED_JSON)])
    import litellm

    monkeypatch.setattr(litellm, "completion", fake, raising=False)
    ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="run"))

    summary = ai_review.update_ai_review(
        WORKSPACE_ID, AiReviewAction(action="accept")
    )

    assert summary.decision is not None
    assert summary.decision.kind == "accept"
    assert summary.decision.reason is None


def test_override_requires_reason(monkeypatch, patched_service):
    import json

    fake = _canned_completion([json.dumps(CANNED_JSON)])
    import litellm

    monkeypatch.setattr(litellm, "completion", fake, raising=False)
    ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="run"))

    with pytest.raises(ValueError):
        ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="override"))

    summary = ai_review.update_ai_review(
        WORKSPACE_ID,
        AiReviewAction(action="override", reason="Clinically justified, vet on record."),
    )

    assert summary.decision is not None
    assert summary.decision.kind == "override"
    assert summary.decision.reason == "Clinically justified, vet on record."


def test_reset_clears_result_and_decision(monkeypatch, patched_service):
    import json

    fake = _canned_completion([json.dumps(CANNED_JSON)])
    import litellm

    monkeypatch.setattr(litellm, "completion", fake, raising=False)
    ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="run"))
    ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="accept"))

    summary = ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="reset"))

    assert summary.status == AiReviewStageStatus.IDLE
    assert summary.result is None
    assert summary.decision is None


def test_accept_before_run_is_rejected(monkeypatch, patched_service):
    with pytest.raises(ValueError):
        ai_review.update_ai_review(WORKSPACE_ID, AiReviewAction(action="accept"))


# ── helpers ───────────────────────────────────────────────────────────────


def test_extract_review_json_handles_fenced_and_prose():
    assert ai_review._extract_review_json('```json\n{"a":1}\n```') == {"a": 1}
    assert ai_review._extract_review_json('Sure! {"a":1} done.') == {"a": 1}
    assert ai_review._extract_review_json("no json here") is None
    assert ai_review._extract_review_json("") is None


def test_expected_provider_key_lookup():
    assert ai_review._expected_provider_key("anthropic/claude-opus-4-7") == "ANTHROPIC_API_KEY"
    assert ai_review._expected_provider_key("openai/gpt-4o") == "OPENAI_API_KEY"
    assert ai_review._expected_provider_key("gemini/pro") == "GEMINI_API_KEY"
    assert ai_review._expected_provider_key("unknown-provider/foo") is None
    assert ai_review._expected_provider_key("no-slash-model") is None
