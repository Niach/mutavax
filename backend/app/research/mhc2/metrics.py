"""Benchmark metrics used by the open MHC-II predictor track."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Sequence

import numpy as np


def roc_auc(labels: Sequence[float], scores: Sequence[float]) -> float:
    y = np.asarray(labels, dtype=float)
    s = np.asarray(scores, dtype=float)
    pos = y > 0.5
    n_pos = int(pos.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return math.nan
    ranks = _rankdata(s)
    rank_sum_pos = ranks[pos].sum()
    return float((rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def average_precision(labels: Sequence[float], scores: Sequence[float]) -> float:
    pairs = sorted(zip(scores, labels), reverse=True)
    positives = sum(1 for _, label in pairs if label > 0.5)
    if positives == 0:
        return math.nan
    hits = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(pairs, start=1):
        if label > 0.5:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / positives


def f1_at_threshold(
    labels: Sequence[float], scores: Sequence[float], threshold: float = 0.5
) -> dict[str, float]:
    tp = fp = tn = fn = 0
    for label, score in zip(labels, scores):
        predicted = score >= threshold
        actual = label > 0.5
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "tp": float(tp),
        "fp": float(fp),
        "tn": float(tn),
        "fn": float(fn),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def spearmanr(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")
    if len(x) < 2:
        return math.nan
    rx = _rankdata(np.asarray(x, dtype=float))
    ry = _rankdata(np.asarray(y, dtype=float))
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = math.sqrt(float((rx**2).sum() * (ry**2).sum()))
    return float((rx * ry).sum() / denom) if denom else math.nan


def topk_recall_by_group(
    labels: Sequence[float],
    scores: Sequence[float],
    groups: Sequence[str],
    k: int = 10,
) -> float:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for label, score, group in zip(labels, scores, groups):
        grouped[group].append((score, label))
    recalls: list[float] = []
    for values in grouped.values():
        positives = sum(1 for _, label in values if label > 0.5)
        if positives == 0:
            continue
        top = sorted(values, reverse=True)[:k]
        found = sum(1 for _, label in top if label > 0.5)
        recalls.append(found / positives)
    return float(np.mean(recalls)) if recalls else math.nan


def frank(epitope_score: float, candidate_scores: Iterable[float]) -> float:
    scores = list(candidate_scores)
    if not scores:
        return math.nan
    return sum(1 for score in scores if score > epitope_score) / len(scores)


def motif_kl_distance(observed: Sequence[Sequence[float]], expected: Sequence[Sequence[float]]) -> float:
    obs = np.asarray(observed, dtype=float)
    exp = np.asarray(expected, dtype=float)
    if obs.shape != exp.shape:
        raise ValueError("motif matrices must have the same shape")
    eps = 1e-9
    obs = (obs + eps) / (obs + eps).sum(axis=1, keepdims=True)
    exp = (exp + eps) / (exp + eps).sum(axis=1, keepdims=True)
    return float((obs * np.log(obs / exp)).sum(axis=1).mean())


def _rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        average_rank = (start + 1 + end) / 2
        ranks[order[start:end]] = average_rank
        start = end
    return ranks

