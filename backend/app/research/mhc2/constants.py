"""Static metadata for the cancerstudio MHC-II research track."""

from __future__ import annotations

from dataclasses import dataclass

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
PAD_TOKEN = "X"
UNKNOWN_TOKEN = "X"
MODEL_AMINO_ACIDS = AMINO_ACIDS + UNKNOWN_TOKEN
MIN_PEPTIDE_LENGTH = 8
MAX_PEPTIDE_LENGTH = 30


@dataclass(frozen=True)
class DataSource:
    key: str
    title: str
    url: str
    role: str
    license_note: str
    expected_files: tuple[str, ...] = ()
    size_bytes: int | None = None
    notes: str = ""


DATA_SOURCES: dict[str, DataSource] = {
    "hlaiipred_zenodo": DataSource(
        key="hlaiipred_zenodo",
        title="HLAIIPred Zenodo positive MS ligand splits",
        url="https://zenodo.org/records/15299217",
        role="primary_public_reproduce",
        license_note="Public Zenodo record; verify terms in downloaded metadata before redistributing derived weights.",
        expected_files=("train_positive.csv", "valid_positive.csv", "test_positive.csv"),
        size_bytes=242_764_573,
        notes="Reported scale: 597,508 unique peptides, 341 samples, 172 unique alleles, 1,856,146 peptide-sample pairs.",
    ),
    "netmhciipan_43": DataSource(
        key="netmhciipan_43",
        title="NetMHCIIpan-4.3 training and evaluation data",
        url="https://services.healthtech.dtu.dk/services/NetMHCIIpan-4.3/",
        role="partition_scaffold_and_benchmark",
        license_note="DTU service data; do not redistribute DTU binaries. Keep downloaded data provenance.",
        expected_files=("NetMHCIIpan_train.tar.gz", "NetMHCIIpan_eval.fa"),
        size_bytes=396_748_800,
        notes="Use the published 5-fold partitions and pseudosequences for leakage-aware benchmarking.",
    ),
    "racle_2023": DataSource(
        key="racle_2023",
        title="Racle et al. 2023 MixMHC2pred ligand corpus",
        url="https://github.com/GfellerLab/MixMHC2pred",
        role="research_sota_training_and_motif_benchmark",
        license_note="Research-use data and academic-only external tool; benchmark users obtain MixMHC2pred separately.",
        expected_files=(),
        notes="Associated PRIDE accession PXD034773; paper reports 627,013 unique MHC-II ligands and 88 allele motifs.",
    ),
    "strazar_captan": DataSource(
        key="strazar_captan",
        title="Strazar/CAPTAn monoallelic HLA-II corpus",
        url="https://doi.org/10.1016/j.immuni.2023.05.009",
        role="rare_dp_dq_training_and_benchmark",
        license_note="Publication supplement/data portal terms must be captured with raw files.",
        expected_files=(),
        notes="Reported scale: 358,024 allele-restricted ligands, 203,022 unique peptides, 42 heterodimers.",
    ),
    "hla_ligand_atlas": DataSource(
        key="hla_ligand_atlas",
        title="HLA Ligand Atlas",
        url="https://hla-ligand-atlas.org/data",
        role="benign_tissue_auxiliary_training",
        license_note="Portal states CC-BY 4.0 for downloadable data.",
        expected_files=(),
        notes="Reported class-II scale: 142,625 peptides across benign tissues.",
    ),
    "systemhc_v2": DataSource(
        key="systemhc_v2",
        title="SysteMHC Atlas v2.0",
        url="https://systemhc.sjtu.edu.cn/",
        role="weak_augmented_optional",
        license_note="Use only as weak auxiliary data; some labels are predictor-derived.",
        expected_files=(),
        notes="Reported scale: 1,123,828 class-II unique peptides and 342,478 predicted binders across 149 allotypes.",
    ),
    "graph_pmhc_zenodo": DataSource(
        key="graph_pmhc_zenodo",
        title="Graph-pMHC dataset",
        url="https://zenodo.org/records/8429039",
        role="benchmark_and_ablation",
        license_note="Dataset is CC-BY 4.0; Genentech code is non-commercial and must not be reused in released implementation.",
        expected_files=(),
        notes="Large benchmark dataset, roughly 5.6 GB.",
    ),
    "ipd_imgt_hla": DataSource(
        key="ipd_imgt_hla",
        title="IPD-IMGT/HLA official allele list",
        url="https://github.com/ANHIG/IMGTHLA",
        role="reference_lookup",
        license_note="IPD-IMGT/HLA reference data. Free to redistribute with attribution.",
        expected_files=("Allelelist.txt",),
        notes="Used to disambiguate concatenated DTU allele names like HLA-DPA10103-DPB110401 (could be DPB1*10:401 or DPB1*104:01).",
    ),
}


CHECKPOINT_TRACKS = (
    "public_reproduce",
    "research_sota",
    "weak_augmented",
)
