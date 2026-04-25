"""Benchmark file evaluation for MHC-II predictor outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.research.mhc2.metrics import (
    average_precision,
    f1_at_threshold,
    roc_auc,
    spearmanr,
    topk_recall_by_group,
)


def evaluate_prediction_file(path: Path, threshold: float = 0.5) -> dict:
    """Evaluate a CSV/TSV with ``label`` and ``score`` columns.

    Optional columns: ``group`` for top-k recall and ``rank_target`` for
    Spearman correlation against binding-affinity/rank labels.
    """
    rows = _read_rows(path)
    labels = [float(row.get("label") or row.get("target") or row.get("presented")) for row in rows]
    scores = [float(row.get("score") or row.get("prediction")) for row in rows]
    result = {
        "rows": len(rows),
        "roc_auc": roc_auc(labels, scores),
        "pr_auc": average_precision(labels, scores),
        "threshold": f1_at_threshold(labels, scores, threshold=threshold),
    }
    if all(row.get("group") for row in rows):
        result["top10_recall_by_group"] = topk_recall_by_group(
            labels, scores, [row["group"] for row in rows], k=10
        )
    if all(row.get("rank_target") for row in rows):
        result["spearman"] = spearmanr([float(row["rank_target"]) for row in rows], scores)
    return result


def write_metrics_json(metrics: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_rows(path: Path) -> list[dict[str, str]]:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(
            (line for line in handle if not line.startswith("#")),
            delimiter=delimiter,
        )
        return list(reader)
