#!/usr/bin/env python3
"""Source-protein FRANK benchmark on NetMHCIIpan_eval.fa.

Parses each entry of NetMHCIIpan-4.3's evaluation FASTA — 842 published
CD4+ epitopes from CEDAR — and computes the FRANK metric:

    Each entry has (epitope, source_protein, allele). We slide a window
    of length len(epitope) through source_protein, score every window
    plus the epitope itself, and report the rank of the epitope among
    all candidates. FRANK = (rank - 1) / num_candidates so 0 = perfect
    and 0.5 = random.

This is the standard CD4+ epitope benchmark. None of these epitopes
overlap HLAIIPred / NetMHCIIpan / MixMHC2pred / our training data
(they are explicitly the held-out eval set), so this is the cleanest
fair-generalization benchmark we have.

Output: a JSON with median / p95 / mean FRANK + per-allele + per-length
breakdown + ROC-style "fraction of epitopes ranked top-1 / top-5 / top-10".
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.baselines.base import BaselineModel
from app.research.mhc2.baselines.hlaiipred import HLAIIPredAdapter
from app.research.mhc2.baselines.mixmhc2pred import MixMHC2predAdapter
from app.research.mhc2.baselines.netmhciipan import NetMHCIIpanAdapter
from app.research.mhc2.metrics import locus_for_allele


def parse_eval_fa(path: Path) -> list[dict]:
    """Parse NetMHCIIpan_eval.fa.

    Each entry is two lines:
      >protein_id  epitope_peptide  allele_name
      <full source protein sequence>

    Returns a list of dicts {protein_id, epitope, allele_raw, protein}.
    """
    entries: list[dict] = []
    header: str | None = None
    seq: list[str] = []
    with path.open("r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None and seq:
                    entries.append(_finalize(header, "".join(seq)))
                header = line[1:]
                seq = []
            else:
                seq.append(line)
        if header is not None and seq:
            entries.append(_finalize(header, "".join(seq)))
    return entries


def _finalize(header: str, sequence: str) -> dict:
    parts = header.split()
    if len(parts) < 3:
        raise ValueError(f"unexpected eval.fa header: {header!r}")
    protein_id = parts[0]
    epitope = parts[1].upper()
    allele_raw = parts[2]
    return {
        "protein_id": protein_id,
        "epitope": epitope,
        "allele_raw": allele_raw,
        "protein": sequence.upper(),
    }


def normalize_eval_allele(raw: str) -> str | None:
    """Map NetMHCIIpan eval-style allele names to our HLA-DRB1*04:01 form.

    Examples seen in eval.fa:
      DRB1_0401             -> HLA-DRB1*04:01
      DRB5_0101             -> HLA-DRB5*01:01
      HLA-DQA10501-DQB10301 -> HLA-DQA1*05:01-DQB1*03:01
      H-2-IAb               -> H-2-IAb (mouse, may not be in our pseudoseq table)
    """
    s = raw.strip()
    # Mouse / non-human alleles — leave as-is and let pseudoseq lookup fail
    if not s.startswith(("DR", "DP", "DQ", "HLA-")):
        return s
    s_no_prefix = s.removeprefix("HLA-")
    # Heterodimer: e.g. DPA10103-DPB10401, or HLA-DQA10501-DQB10301
    if "-" in s_no_prefix:
        parts = s_no_prefix.split("-")
        out_parts = []
        for part in parts:
            out_parts.append(_format_chain(part))
        return "HLA-" + "-".join(out_parts)
    # Single chain like DRB1_0401
    return "HLA-" + _format_chain(s_no_prefix)


def _format_chain(chain: str) -> str:
    """e.g. DRB1_0401 -> DRB1*04:01; DPB10401 -> DPB1*04:01."""
    chain = chain.replace("_", "")
    m = re.match(r"^([A-Z]+\d?)(\d{2})(\d{2,3})$", chain)
    if not m:
        return chain
    locus, field1, field2 = m.groups()
    return f"{locus}*{field1}:{field2}"


def make_pairs_for_entry(entry: dict) -> list[tuple[str, str, bool]]:
    """For one (epitope, protein, allele) entry, return a list of
    (peptide, allele_norm, is_epitope) for: each unique window of
    epitope-length in the source protein, plus the epitope itself.

    is_epitope=True only on the actual epitope peptide string (note:
    if the epitope happens to also appear as a window in the protein,
    that window is collapsed into the same peptide and tagged as
    epitope so we don't penalize-rank-ties artificially).
    """
    peptide = entry["epitope"]
    protein = entry["protein"]
    allele_norm = normalize_eval_allele(entry["allele_raw"])
    if allele_norm is None:
        return []
    L = len(peptide)
    if L < 9 or len(protein) < L:
        return []
    candidates: dict[str, bool] = {}  # peptide -> is_epitope
    for i in range(len(protein) - L + 1):
        win = protein[i : i + L]
        # Skip windows with non-standard residues
        if not all(c in "ACDEFGHIKLMNPQRSTVWY" for c in win):
            continue
        candidates[win] = candidates.get(win, False)
    candidates[peptide] = True  # epitope, overrides if same string
    return [(pep, allele_norm, is_ep) for pep, is_ep in candidates.items()]


_NAN_FRANK = {"pessimistic": float("nan"), "random": float("nan"), "optimistic": float("nan")}


def compute_frank(scores: dict[str, float], epitope: str) -> dict[str, float]:
    """FRANK = (rank - 1) / N_candidates_excluding_epitope.

    Returns a dict with all three tie-breaking policies:
      pessimistic — epitope ranks below every tie (worst case; what we used
                    to report exclusively).
      optimistic  — epitope ranks above every tie (best case).
      random      — expected FRANK under uniform random tie-breaking
                    (deterministic closed form: midpoint of pessimistic
                    and optimistic). This is the convention NetMHCIIpan
                    and HLAIIPred publish under.

    0.0 = epitope is the highest-scoring window.
    """
    if not scores or epitope not in scores:
        return dict(_NAN_FRANK)
    ep_score = scores[epitope]
    if math.isnan(ep_score):
        return dict(_NAN_FRANK)
    others = [s for p, s in scores.items() if p != epitope and not math.isnan(s)]
    if not others:
        return {"pessimistic": 0.0, "random": 0.0, "optimistic": 0.0}
    better = sum(1 for s in others if s > ep_score)
    ties = sum(1 for s in others if s == ep_score)
    n = len(others)
    pess = (better + ties) / n
    opt = better / n
    # Expected rank under random tie-breaking: epitope is uniformly
    # placed among the (ties + 1) tied items, so E[rank-1] = better + ties/2.
    rand = (better + ties / 2) / n
    return {"pessimistic": pess, "random": rand, "optimistic": opt}


_TIE_POLICIES = ("pessimistic", "random", "optimistic")


def _length_bucket(l: int) -> str:
    if l <= 11:
        return "<=11"
    if l <= 15:
        return "12-15"
    if l <= 19:
        return "16-19"
    return ">=20"


def _slice_summary(valid: list[float]) -> dict:
    n = len(valid)
    if n == 0:
        return {"n_evaluated": 0}
    sorted_franks = sorted(valid)
    return {
        "n_evaluated": n,
        "median_frank": sorted_franks[n // 2],
        "mean_frank": sum(valid) / n,
        "p95_frank": sorted_franks[min(int(0.95 * n), n - 1)],
        "frac_top1_pct": sum(1 for f in valid if f <= 0.01) / n,
        "frac_top5_pct": sum(1 for f in valid if f <= 0.05) / n,
        "frac_top10_pct": sum(1 for f in valid if f <= 0.10) / n,
    }


def aggregate(
    franks_by_policy: dict[str, list[float]],
    alleles: list[str],
    lengths: list[int],
) -> dict:
    """Aggregate FRANK lists for every tie policy.

    The legacy top-level keys (``median_frank`` etc.) mirror ``pessimistic``
    so old downstream tooling keeps working; the new ``by_tie_policy`` block
    holds the full pessimistic/random/optimistic readings, with per-locus
    and per-length slices for each.
    """
    n_entries = len(next(iter(franks_by_policy.values())))
    out: dict = {"n_entries": n_entries}

    by_policy: dict[str, dict] = {}
    for policy, franks in franks_by_policy.items():
        valid = [f for f in franks if not math.isnan(f)]
        slice_out = _slice_summary(valid)
        slice_out["n_skipped"] = n_entries - slice_out["n_evaluated"]

        by_locus: dict[str, list[float]] = {"DR": [], "DP": [], "DQ": [], "other": []}
        for f, a in zip(franks, alleles):
            if math.isnan(f):
                continue
            by_locus[locus_for_allele(a)].append(f)
        slice_out["by_locus"] = {
            loc: {"n": len(fs), "median": (sorted(fs)[len(fs) // 2] if fs else None)}
            for loc, fs in by_locus.items()
        }

        buckets: dict[str, list[float]] = {}
        for f, l in zip(franks, lengths):
            if math.isnan(f):
                continue
            buckets.setdefault(_length_bucket(l), []).append(f)
        slice_out["by_length"] = {
            k: {"n": len(fs), "median": sorted(fs)[len(fs) // 2]}
            for k, fs in buckets.items()
        }
        by_policy[policy] = slice_out

    out["by_tie_policy"] = by_policy
    # Mirror the pessimistic slice at the top level so older readers keep working.
    pess = by_policy.get("pessimistic", {})
    for k in ("n_evaluated", "n_skipped", "median_frank", "mean_frank", "p95_frank",
              "frac_top1_pct", "frac_top5_pct", "frac_top10_pct", "by_locus", "by_length"):
        if k in pess:
            out[k] = pess[k]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-fa", type=Path, required=True,
                        help="Path to NetMHCIIpan_eval.fa")
    parser.add_argument("--tool",
                        choices=["our", "netmhciipan", "mixmhc2pred", "hlaiipred"],
                        default="our",
                        help="Predictor to score with the same source-protein FRANK harness.")
    parser.add_argument("--checkpoint", type=Path,
                        help="Our model checkpoint (.best.pt)")
    parser.add_argument("--pseudosequences", type=Path)
    parser.add_argument("--esm-cache-dir", type=Path,
                        help="Required for ESM (Phase B) checkpoints.")
    parser.add_argument("--netmhciipan-bin",
                        help="Optional path to the NetMHCIIpan wrapper or inner binary.")
    parser.add_argument("--mixmhc2pred-bin",
                        help="Optional path to the MixMHC2pred binary.")
    parser.add_argument("--hlaiipred-root",
                        help="Optional HLAIIPred repo path; otherwise use $HLAIIPRED_ROOT.")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--out", type=Path, required=True,
                        help="Output JSON path.")
    args = parser.parse_args()

    print(f"[eval-fa] parsing {args.eval_fa}", flush=True)
    entries = parse_eval_fa(args.eval_fa)
    print(f"[eval-fa] {len(entries)} entries parsed", flush=True)

    scorer = _build_scorer(args)
    print(f"[eval-fa] scoring tool={scorer.name}", flush=True)

    franks_by_policy: dict[str, list[float]] = {p: [] for p in _TIE_POLICIES}
    alleles: list[str] = []
    lengths: list[int] = []
    skipped_no_pseudoseq = 0
    skipped_too_short = 0

    def _record_skip(allele: str, length: int) -> None:
        for p in _TIE_POLICIES:
            franks_by_policy[p].append(float("nan"))
        alleles.append(allele)
        lengths.append(length)

    for i, entry in enumerate(entries):
        pairs = make_pairs_for_entry(entry)
        if not pairs:
            skipped_too_short += 1
            _record_skip("?", len(entry["epitope"]))
            continue
        allele_norm = pairs[0][1]
        if scorer.supported_alleles is not None and allele_norm not in scorer.supported_alleles:
            skipped_no_pseudoseq += 1
            _record_skip(allele_norm, len(entry["epitope"]))
            continue
        score_pairs = [(pep, all_) for pep, all_, _ in pairs]
        try:
            scores = scorer.score(score_pairs)
        except (KeyError, ValueError) as exc:
            _record_skip(allele_norm, len(entry["epitope"]))
            continue
        f = compute_frank(scores, entry["epitope"])
        for p in _TIE_POLICIES:
            franks_by_policy[p].append(f[p])
        alleles.append(allele_norm)
        lengths.append(len(entry["epitope"]))
        if (i + 1) % 25 == 0 or i < 5:
            running = {
                p: sorted([x for x in franks_by_policy[p] if not math.isnan(x)])
                for p in _TIE_POLICIES
            }
            def _med(xs: list[float]) -> float:
                return xs[len(xs) // 2] if xs else float("nan")
            print(
                f"[eval-fa] {i+1}/{len(entries)} entries, "
                f"len(score_pairs)={len(score_pairs)}, "
                f"med_frank pess={_med(running['pessimistic']):.4f} "
                f"rand={_med(running['random']):.4f} "
                f"opt={_med(running['optimistic']):.4f}",
                flush=True,
            )

    summary = aggregate(franks_by_policy, alleles, lengths)
    summary["skipped_no_pseudoseq"] = skipped_no_pseudoseq
    summary["skipped_too_short"] = skipped_too_short
    summary["tool"] = scorer.name
    summary["model"] = str(args.checkpoint) if args.checkpoint else scorer.name
    summary["per_entry"] = [
        {
            "epitope": e["epitope"],
            "allele": a,
            "length": l,
            "frank_pessimistic": franks_by_policy["pessimistic"][i],
            "frank_random": franks_by_policy["random"][i],
            "frank_optimistic": franks_by_policy["optimistic"][i],
        }
        for i, (e, a, l) in enumerate(zip(entries, alleles, lengths))
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"[eval-fa] wrote {args.out}", flush=True)
    print(f"[eval-fa] median FRANK = {summary.get('median_frank', 'n/a')}", flush=True)
    print(f"[eval-fa] frac top-5%  = {summary.get('frac_top5_pct', 'n/a')}", flush=True)


class _EvalFaScorer:
    def __init__(self, name: str, supported_alleles: set[str] | None = None) -> None:
        self.name = name
        self.supported_alleles = supported_alleles

    def score(self, pairs: list[tuple[str, str]]) -> dict[str, float]:
        raise NotImplementedError


class _OurModelScorer(_EvalFaScorer):
    def __init__(self, args: argparse.Namespace) -> None:
        if args.checkpoint is None or args.pseudosequences is None:
            raise SystemExit("--checkpoint and --pseudosequences are required with --tool our")
        from app.research.mhc2.predict import MHC2Predictor

        self.predictor = MHC2Predictor(
            checkpoint_path=args.checkpoint,
            pseudosequence_path=args.pseudosequences,
            device=args.device,
            esm_cache_dir=args.esm_cache_dir,
        )
        self.batch_size = args.batch_size
        super().__init__(
            name=f"our:{args.checkpoint.name}",
            supported_alleles=set(self.predictor.pseudosequences),
        )

    def score(self, pairs: list[tuple[str, str]]) -> dict[str, float]:
        preds = self.predictor.predict_many(pairs, batch_size=self.batch_size)
        return {p.peptide: float(p.score) for p in preds}


class _BaselineScorer(_EvalFaScorer):
    def __init__(self, adapter: BaselineModel) -> None:
        ok, msg = adapter.is_available()
        if not ok:
            raise SystemExit(f"{adapter.name} unavailable: {msg}")
        self.adapter = adapter
        super().__init__(name=adapter.name)
        print(f"[eval-fa] {adapter.name}: {msg}", flush=True)

    def score(self, pairs: list[tuple[str, str]]) -> dict[str, float]:
        preds = self.adapter.predict(pairs)
        if len(preds) != len(pairs):
            raise RuntimeError(
                f"{self.adapter.name} returned {len(preds)} of {len(pairs)} predictions"
            )
        return {pred.peptide: float(pred.score) for pred in preds}


def _build_scorer(args: argparse.Namespace) -> _EvalFaScorer:
    if args.tool == "our":
        return _OurModelScorer(args)
    if args.tool == "netmhciipan":
        return _BaselineScorer(NetMHCIIpanAdapter(binary=args.netmhciipan_bin))
    if args.tool == "mixmhc2pred":
        return _BaselineScorer(MixMHC2predAdapter(binary=args.mixmhc2pred_bin))
    if args.tool == "hlaiipred":
        return _BaselineScorer(
            HLAIIPredAdapter(
                repo_root=args.hlaiipred_root,
                device=args.device,
                batch_size=args.batch_size,
            )
        )
    raise SystemExit(f"unknown tool: {args.tool}")


if __name__ == "__main__":
    main()
