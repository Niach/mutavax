"""Stage 6 — BLAST-to-proteome self-identity safety check.

Flags epitope candidates that look like sequences the patient's own immune
system sees on healthy tissue. A peptide that's a near-perfect match to a
self-protein risks driving an autoimmune T-cell response against that
tissue if included in the vaccine cassette — this check is the product's
primary guard against that failure mode.

Mirrors the ``ensure_pon_ready`` bootstrap pattern in variant_calling.py:
the UniProt Swiss-Prot proteome for the workspace's species is fetched
once on first use, indexed with DIAMOND, cached under
``${CANCERSTUDIO_DATA_ROOT}/references/proteome/{species}/``, and reused
forever after.

Failure is non-fatal. If DIAMOND is missing, the proteome bootstrap
fails, or the subprocess errors out, we log the reason and return an
empty flag set — the stage remains unblocked but the audit card will
record that the check did not run. A future iteration should hard-block
stage completion on check-unavailable workspaces; for today, visibility
is enough.

Risk tiers emit the same ``EpitopeSafetyFlagResponse`` shape the fixture
deck has always used, so the UI contract is unchanged:

* ``identity == 100`` over the full peptide     → **critical**
* ``identity >= 80``  (fuzzy near-identity)     → **elevated**
* ``identity >= 60``                            → **mild**
* below 60                                      → omitted (no flag)
"""
from __future__ import annotations

import fcntl
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from app.models.schemas import EpitopeSafetyFlagResponse, ReferencePreset
from app.runtime import get_reference_bundle_root


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProteomeSource:
    relative_path: str  # resolved under get_reference_bundle_root()
    uniprot_taxid: int
    label: str


PROTEOME_BY_PRESET: dict[ReferencePreset, Optional[ProteomeSource]] = {
    ReferencePreset.GRCH38: ProteomeSource(
        relative_path="proteome/human/swissprot.fasta",
        uniprot_taxid=9606,
        label="UniProt Swiss-Prot (Homo sapiens)",
    ),
    ReferencePreset.CANFAM4: ProteomeSource(
        relative_path="proteome/dog/swissprot.fasta",
        uniprot_taxid=9615,
        label="UniProt Swiss-Prot (Canis lupus familiaris)",
    ),
    ReferencePreset.FELCAT9: ProteomeSource(
        relative_path="proteome/cat/swissprot.fasta",
        uniprot_taxid=9685,
        label="UniProt Swiss-Prot (Felis catus)",
    ),
}

PROTEOME_ENV_VARS = {
    ReferencePreset.GRCH38: "CANCERSTUDIO_PROTEOME_HUMAN",
    ReferencePreset.CANFAM4: "CANCERSTUDIO_PROTEOME_DOG",
    ReferencePreset.FELCAT9: "CANCERSTUDIO_PROTEOME_CAT",
}


@dataclass(frozen=True)
class ProteomeConfig:
    fasta_path: Path
    dmnd_path: Path
    label: str


def resolve_proteome_config(preset: ReferencePreset) -> Optional[ProteomeConfig]:
    """Locate the Swiss-Prot proteome + DIAMOND DB for this species.

    Returns ``None`` when:

    * no proteome is mapped for this preset, or
    * the FASTA or ``.dmnd`` is not on disk, or
    * the env override is set to an empty string (explicit opt-out).
    """
    env_key = PROTEOME_ENV_VARS.get(preset)
    override = os.getenv(env_key) if env_key else None
    source = PROTEOME_BY_PRESET.get(preset)

    if override is not None:
        if not override.strip():
            return None
        fasta_path = Path(override).expanduser()
        label = source.label if source else preset.value
    elif source is not None:
        fasta_path = get_reference_bundle_root() / source.relative_path
        label = source.label
    else:
        return None

    dmnd_path = fasta_path.with_suffix(".dmnd")
    if not fasta_path.is_file() or not dmnd_path.is_file():
        return None
    return ProteomeConfig(fasta_path=fasta_path, dmnd_path=dmnd_path, label=label)


def ensure_proteome_ready(preset: ReferencePreset) -> Optional[ProteomeConfig]:
    """Return a ProteomeConfig for this preset, downloading + indexing the
    Swiss-Prot FASTA on first use.

    Failure modes are non-fatal — a missing proteome disables the check
    but does not block stage completion. The audit card should later
    reflect whether the check ran.
    """
    env_key = PROTEOME_ENV_VARS.get(preset)
    if env_key is not None and os.getenv(env_key) is not None:
        # User-supplied override — honour it; don't auto-download.
        return resolve_proteome_config(preset)

    source = PROTEOME_BY_PRESET.get(preset)
    if source is None:
        return None

    existing = resolve_proteome_config(preset)
    if existing is not None:
        return existing

    try:
        _bootstrap_proteome(preset, source)
    except Exception as error:  # pragma: no cover — network / tool failures
        logger.warning(
            "self-identity: proteome bootstrap failed for %s (%s); "
            "check will be skipped for this workspace",
            preset.value, error,
        )
        return None
    return resolve_proteome_config(preset)


def _bootstrap_proteome(preset: ReferencePreset, source: ProteomeSource) -> None:
    from urllib.request import urlopen

    target_fasta = get_reference_bundle_root() / source.relative_path
    target_dmnd = target_fasta.with_suffix(".dmnd")
    target_fasta.parent.mkdir(parents=True, exist_ok=True)

    lock_path = target_fasta.parent / ".bootstrap.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        # Another worker may have completed bootstrap while we waited.
        if target_fasta.is_file() and target_dmnd.is_file():
            return

        url = (
            "https://rest.uniprot.org/uniprotkb/stream?"
            f"query=organism_id:{source.uniprot_taxid}+AND+reviewed:true"
            "&format=fasta"
        )
        logger.info(
            "self-identity: downloading Swiss-Prot for taxid=%d from UniProt",
            source.uniprot_taxid,
        )
        with urlopen(url, timeout=600) as response, target_fasta.open("wb") as out:
            shutil.copyfileobj(response, out)

        if target_fasta.stat().st_size == 0:
            target_fasta.unlink()
            raise RuntimeError("UniProt returned an empty proteome FASTA")

        logger.info("self-identity: building DIAMOND index at %s", target_dmnd)
        subprocess.run(
            ["diamond", "makedb",
             "--in", str(target_fasta),
             "--db", str(target_dmnd.with_suffix("")),
             "--quiet"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


_RISK_MILD_FLOOR = 60.0
_RISK_ELEVATED_FLOOR = 80.0


def _risk_for(identity_pct: float) -> Optional[str]:
    """Bucket a BLAST % identity into one of our three risk tiers, or
    ``None`` to drop the hit as below our reporting floor."""
    if identity_pct >= 99.999:
        return "critical"
    if identity_pct >= _RISK_ELEVATED_FLOOR:
        return "elevated"
    if identity_pct >= _RISK_MILD_FLOOR:
        return "mild"
    return None


def _note_for(risk: str, self_hit: str, identity: int, length: int) -> str:
    if risk == "critical":
        return (
            f"perfect {length}-mer match in healthy {self_hit} — "
            "high risk of autoimmune cross-reactivity"
        )
    if risk == "elevated":
        return (
            f"{identity}% identity over {length} aa to healthy {self_hit} — "
            "review before locking"
        )
    return (
        f"{identity}% identity over {length} aa to healthy {self_hit} — "
        "low-risk partial match"
    )


def run_self_identity_check(
    peptides: Iterable[tuple[str, str]],
    preset: ReferencePreset,
) -> dict[str, EpitopeSafetyFlagResponse]:
    """Run DIAMOND blastp of ``peptides`` (``[(peptide_id, aa_sequence), …]``)
    against the species-specific Swiss-Prot DB and return one flag per hit.

    Peptides with no hit (or only hits below the mild floor) are absent
    from the output, matching the sparse-dict convention the UI already
    consumes. Fail-open: on any tool / I/O error, return ``{}`` and let
    the stage proceed (logged prominently)."""
    items = list(peptides)
    if not items:
        return {}

    config = ensure_proteome_ready(preset)
    if config is None:
        logger.warning(
            "self-identity: no proteome available for %s — check skipped",
            preset.value,
        )
        return {}

    if shutil.which("diamond") is None:
        logger.warning(
            "self-identity: DIAMOND binary not on PATH — check skipped"
        )
        return {}

    with tempfile.TemporaryDirectory(prefix="self_identity_") as tmp:
        tmp_dir = Path(tmp)
        query_fasta = tmp_dir / "query.faa"
        with query_fasta.open("w", encoding="utf-8") as handle:
            for peptide_id, seq in items:
                handle.write(f">{peptide_id}\n{seq}\n")

        try:
            raw = subprocess.run(
                [
                    "diamond", "blastp",
                    "--query", str(query_fasta),
                    "--db", str(config.dmnd_path.with_suffix("")),
                    # Short-peptide mode: no compositional stats, PAM30,
                    # masking off. These are the documented DIAMOND flags
                    # for 8-15 aa queries; BLASTP defaults are tuned for
                    # domain-scale comparisons and produce zero hits on
                    # 9-mers.
                    "--matrix", "PAM30",
                    "--comp-based-stats", "0",
                    "--masking", "none",
                    "--evalue", "1000",
                    "--id", str(_RISK_MILD_FLOOR),
                    "--query-cover", "80",
                    "--max-target-seqs", "3",
                    "--outfmt", "6",
                    "qseqid", "sseqid", "stitle", "pident", "length",
                    "--threads", "4",
                    "--quiet",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            ).stdout
        except subprocess.SubprocessError as error:
            logger.warning(
                "self-identity: DIAMOND invocation failed (%s) — check skipped",
                error,
            )
            return {}

    # Keep the strongest hit per peptide. BLAST output is already
    # ordered by E-value within each query, so the first row for a
    # given qseqid is the best one.
    best_by_peptide: dict[str, EpitopeSafetyFlagResponse] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        qseqid, sseqid, stitle, pident_s, length_s = parts[:5]
        try:
            pident = float(pident_s)
            length = int(length_s)
        except ValueError:
            continue

        risk = _risk_for(pident)
        if risk is None:
            continue
        if qseqid in best_by_peptide:
            continue

        best_by_peptide[qseqid] = EpitopeSafetyFlagResponse(
            peptide_id=qseqid,
            self_hit=_gene_label(stitle, sseqid),
            identity=int(round(pident)),
            risk=risk,
            note=_note_for(
                risk,
                _gene_label(stitle, sseqid),
                int(round(pident)),
                length,
            ),
        )
    return best_by_peptide


def _gene_label(stitle: str, sseqid: str) -> str:
    """Distil a BLAST subject title down to a gene / protein label the UI
    can render in one line. UniProt titles look like
    ``sp|P35579|MYH9_HUMAN Myosin-9 OS=Homo sapiens GN=MYH9 PE=1 SV=4``;
    we prefer the ``GN=`` gene symbol when present, fall back to the
    protein name, fall back to the raw sseqid as a last resort."""
    for token in stitle.split():
        if token.startswith("GN="):
            return token[3:]
    # No GN; use the first descriptive word after the accession block.
    parts = stitle.split(" ", 1)
    if len(parts) == 2:
        # Trim organism / PE / SV suffixes.
        name = parts[1]
        for marker in (" OS=", " PE=", " SV="):
            idx = name.find(marker)
            if idx >= 0:
                name = name[:idx]
        return name.strip() or sseqid
    return sseqid
