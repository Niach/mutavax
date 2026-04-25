"""Open MHC-II predictor research toolkit.

This package is intentionally separate from the production neoantigen service.
It gives cancerstudio a reproducible place to curate public MHC-II ligand data,
train an in-house model, and benchmark it against external tools without
changing the shipped pVACseq/NetMHCIIpan path.
"""

from app.research.mhc2.alleles import MHC2Allele, normalize_mhc2_allele
from app.research.mhc2.data import MHC2Record
from app.research.mhc2.metrics import (
    average_precision,
    f1_at_threshold,
    roc_auc,
    spearmanr,
)

__all__ = [
    "MHC2Allele",
    "MHC2Record",
    "average_precision",
    "f1_at_threshold",
    "normalize_mhc2_allele",
    "roc_auc",
    "spearmanr",
]

