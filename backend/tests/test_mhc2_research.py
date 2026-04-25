from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.research.mhc2.alleles import normalize_mhc2_allele
from app.research.mhc2.data import MHC2Record, iter_hlaiipred_positive_csv
from app.research.mhc2.decoys import positive_9mer_index, sample_length_matched_decoys
from app.research.mhc2.metrics import average_precision, f1_at_threshold, roc_auc, spearmanr
from app.research.mhc2.splits import assign_cluster_splits, leakage_report


def test_normalize_dr_and_dq_alleles() -> None:
    dr = normalize_mhc2_allele("HLA-DRB1*15:01")
    assert dr.normalized == "HLA-DRB1*15:01"
    assert dr.locus == "DR"

    dr_dimer = normalize_mhc2_allele("DRA*01:01-DRB1*15:01")
    assert dr_dimer.normalized == "HLA-DRB1*15:01"
    assert dr_dimer.alpha == "HLA-DRA*01:01"

    dq = normalize_mhc2_allele("DQA1*03:01-DQB1*04:01")
    assert dq.normalized == "HLA-DQA1*03:01-DQB1*04:01"
    assert dq.locus == "DQ"
    assert dq.alpha == "HLA-DQA1*03:01"
    assert dq.beta == "HLA-DQB1*04:01"


def test_normalize_netmhciipan_dtu_concat_form() -> None:
    """NetMHCIIpan-4.3 pseudosequence file uses underscore + concat-digit form."""
    assert normalize_mhc2_allele("DRB1_1501").normalized == "HLA-DRB1*15:01"
    assert normalize_mhc2_allele("DRB1_0101").normalized == "HLA-DRB1*01:01"

    dp = normalize_mhc2_allele("HLA-DPA10103-DPB10101")
    assert dp.normalized == "HLA-DPA1*01:03-DPB1*01:01"
    assert dp.locus == "DP"

    dq = normalize_mhc2_allele("HLA-DQA10101-DQB10201")
    assert dq.normalized == "HLA-DQA1*01:01-DQB1*02:01"


def test_normalize_three_digit_family_with_ipd_lookup(monkeypatch) -> None:
    """5+ digit fields are ambiguous; IPD lookup picks the registered split.

    Without lookup, 'HLA-DPA10103-DPB110401' could be DPB1*10:401 or
    DPB1*104:01. With the IPD allele list, DPB1*104:01 is registered while
    DPB1*10:401 is not, so the lookup must prefer 104:01.
    """
    from app.research.mhc2 import alleles as alleles_mod
    from app.research.mhc2 import ipd as ipd_mod

    monkeypatch.setattr(alleles_mod, "known_two_field", lambda gene: {"104:01"} if gene == "DPB1" else set())
    ipd_mod.reset_cache()

    assert (
        normalize_mhc2_allele("HLA-DPA10103-DPB110401").normalized
        == "HLA-DPA1*01:03-DPB1*104:01"
    )


def test_parse_hlaiipred_positive_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "train_positive.csv"
    csv_path.write_text(
        "peptide,presented,allele1,allele2,allele3\n"
        "AAAVRHVL,1,DRB1*07:01,DPA1*02:01-DPB1*17:01,0\n"
        "IRVTYCGLUS,1,DRB1*07:01,0,0\n"
        "BROKEN,0,DRB1*07:01,0,0\n",
        encoding="utf-8",
    )

    records = list(iter_hlaiipred_positive_csv(csv_path))

    assert records == [
        MHC2Record(
            peptide="AAAVRHVL",
            alleles=("HLA-DRB1*07:01", "HLA-DPA1*02:01-DPB1*17:01"),
            target=1.0,
            source="hlaiipred_zenodo",
            split="train",
        )
    ]


def test_cluster_split_keeps_shared_9mers_together() -> None:
    records = [
        MHC2Record("ACDEFGHIKLM", ("HLA-DRB1*01:01",)),
        MHC2Record("AACDEFGHIK", ("HLA-DRB1*01:01",)),
        MHC2Record("VVVVVVVVVVV", ("HLA-DRB1*01:01",)),
    ]

    assigned = assign_cluster_splits(records, seed="test")
    assert assigned[0].split == assigned[1].split

    train = [record for record in assigned if record.split == assigned[0].split]
    held_out = [record for record in assigned if record.split != assigned[0].split]
    report = leakage_report(train, held_out)
    assert report.overlapping_records == 0


def test_decoys_match_length_and_exclude_positive_9mers() -> None:
    positives = [
        MHC2Record("ACDEFGHIKLM", ("HLA-DRB1*01:01",), split="train"),
    ]
    decoys, stats = sample_length_matched_decoys(
        positives,
        ["VVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"],
        positive_9mers=positive_9mer_index(positives),
        seed=1,
    )

    assert stats.generated == 1
    assert len(decoys[0].peptide) == len(positives[0].peptide)
    assert not (set(decoys[0].peptide[i : i + 9] for i in range(len(decoys[0].peptide) - 8)) & positive_9mer_index(positives))
    assert decoys[0].target == 0.0
    assert decoys[0].alleles == positives[0].alleles


def test_metrics_known_values() -> None:
    labels = [0, 0, 1, 1]
    scores = [0.1, 0.4, 0.35, 0.8]

    assert roc_auc(labels, scores) == pytest.approx(0.75)
    assert average_precision(labels, scores) == pytest.approx((1.0 + 2 / 3) / 2)
    assert f1_at_threshold(labels, scores, threshold=0.5)["f1"] == pytest.approx(2 / 3)
    assert spearmanr([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert math.isnan(roc_auc([1, 1], [0.2, 0.3]))
