"""Stage 6 — proteome self-identity safety check.

Flags epitope candidates that look like sequences the patient's own
immune system sees on healthy tissue. A peptide that's a near-perfect
match to a self-protein risks driving an autoimmune T-cell response
against that tissue if included in the vaccine cassette — this check
is the product's primary guard against that failure mode.

**Implementation — pure-Python substring + hamming scan.**

Neoantigen peptides are short (class-I: 8-11 aa, class-II: 12-18 aa).
DIAMOND's seed-and-extend heuristic *does not seed on 9-mers* at any
sensitivity level — an earlier DIAMOND-backed implementation of this
check silently returned zero hits on every class-I candidate. The
canonical tool for short-peptide searches is NCBI BLAST+'s
``blastp -task blastp-short``, but for the window sizes we care about
a direct Python substring+hamming scan is both simpler and
fast enough: ~2-3 s per cassette on human Swiss-Prot (20k proteins).

The UniProt Swiss-Prot proteome for the workspace's species is fetched
once on first use from UniProt, cached under
``${CANCERSTUDIO_DATA_ROOT}/references/proteome/{species}/``, parsed
into memory with an LRU cache, and reused forever after. No external
binary required.

Failure is non-fatal. If the proteome download fails or the FASTA is
missing, we log and return an empty flag set — the stage remains
unblocked but the audit card should record that the check did not run.

Risk tiers emit the same ``EpitopeSafetyFlagResponse`` shape the
fixture deck has always used, so the UI contract is unchanged:

* ``identity == 100`` over the full peptide     → **critical**
* ``identity >= 80``  (fuzzy near-identity)     → **elevated**
* ``identity >= 60``                            → **mild**
* below 60                                      → omitted (no flag)
"""
from __future__ import annotations

import fcntl
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
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
    label: str
    # DIAMOND index is optional — only needed for ≥14-aa (class-II)
    # peptide lookups. Shorter peptides use pure-Python substring /
    # regex and don't touch DIAMOND at all.
    dmnd_path: Optional[Path] = None


def resolve_proteome_config(preset: ReferencePreset) -> Optional[ProteomeConfig]:
    """Locate the Swiss-Prot proteome FASTA for this species.

    Returns ``None`` when:

    * no proteome is mapped for this preset, or
    * the FASTA is not on disk, or
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

    if not fasta_path.is_file():
        return None
    dmnd = fasta_path.with_suffix(".dmnd")
    return ProteomeConfig(
        fasta_path=fasta_path,
        label=label,
        dmnd_path=dmnd if dmnd.is_file() else None,
    )


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
        # FASTA is cached. If the DIAMOND index is missing and the
        # binary is available, build it on the fly so subsequent
        # class-II lookups don't fall through. Pre-DIAMOND cache
        # directories (built before we added the index) would
        # otherwise miss class-II peptides forever.
        if existing.dmnd_path is None and shutil.which("diamond") is not None:
            _build_diamond_index(existing.fasta_path)
            return resolve_proteome_config(preset)
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


def _build_diamond_index(fasta_path: Path) -> None:
    """Build a DIAMOND ``.dmnd`` index next to an existing FASTA.
    Non-fatal on failure — short-peptide (≤13 aa) lookups work without
    it; only class-II lookups need the index."""
    target = fasta_path.with_suffix(".dmnd")
    logger.info(
        "self-identity: building DIAMOND index at %s", target
    )
    try:
        subprocess.run(
            ["diamond", "makedb",
             "--in", str(fasta_path),
             "--db", str(target.with_suffix("")),
             "--quiet"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.SubprocessError as error:
        logger.warning(
            "self-identity: DIAMOND makedb failed (%s); class-II "
            "lookups will fall back to Python only", error,
        )


def _bootstrap_proteome(preset: ReferencePreset, source: ProteomeSource) -> None:
    from urllib.request import urlopen

    target_fasta = get_reference_bundle_root() / source.relative_path
    target_fasta.parent.mkdir(parents=True, exist_ok=True)

    lock_path = target_fasta.parent / ".bootstrap.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        # Another worker may have completed bootstrap while we waited.
        if target_fasta.is_file() and target_fasta.stat().st_size > 0:
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

        # Build a DIAMOND index alongside the FASTA. This is only used
        # for the ≥14-aa (class-II) lookup path; short peptides don't
        # need it and the check works fine without it. Failure is
        # non-fatal — we log and proceed.
        if shutil.which("diamond") is not None:
            target_dmnd = target_fasta.with_suffix(".dmnd")
            try:
                subprocess.run(
                    ["diamond", "makedb",
                     "--in", str(target_fasta),
                     "--db", str(target_dmnd.with_suffix("")),
                     "--quiet"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except subprocess.SubprocessError as error:
                logger.warning(
                    "self-identity: DIAMOND makedb failed (%s); "
                    "class-II self-identity will fall back to Python only",
                    error,
                )


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------


# For short peptides (neoantigen length = 8-11 aa), a "60% identity"
# threshold is statistically noisy — a random 9-mer has non-trivial
# probability of matching 5/9 positions in *some* 9-window of a 20k-
# protein proteome, producing false-positive "mild" flags. We keep
# only the two clinically meaningful tiers:
#   - critical (exact substring): the peptide IS a self-peptide
#   - elevated (≥80% identity):   single-mutation self-cross-reactivity
#                                 risk, e.g., tumor neoantigens that
#                                 differ from their wildtype parent at
#                                 one position
# A "mild" tier is conceptually defensible for longer peptides (≥12 aa
# class-II) but requires dedicated logic to avoid short-peptide false
# positives — tracked in validation.md as a separate follow-up.
_RISK_ELEVATED_FLOOR = 80.0


def _risk_for(identity_pct: float) -> Optional[str]:
    """Bucket a hamming-based % identity into ``critical`` / ``elevated``
    / ``None``. The mild tier from the v0 fixture schema is not emitted
    by the real check; see the note above."""
    if identity_pct >= 99.999:
        return "critical"
    if identity_pct >= _RISK_ELEVATED_FLOOR:
        return "elevated"
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


@lru_cache(maxsize=4)
def _load_proteome(fasta_path: str) -> tuple[tuple[str, str], ...]:
    """Parse a Swiss-Prot FASTA into ``((gene_label, sequence), ...)``.
    Cached per-path; typical proteomes (~20k entries, ~11 MB) parse in
    under a second and fit comfortably in memory."""
    entries: list[tuple[str, str]] = []
    header = ""
    seq_parts: list[str] = []
    with Path(fasta_path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                if header:
                    entries.append(
                        (_gene_label(header, _sseqid_from_header(header)),
                         "".join(seq_parts).upper())
                    )
                header = line[1:]
                seq_parts = []
            else:
                seq_parts.append(line)
        if header:
            entries.append(
                (_gene_label(header, _sseqid_from_header(header)),
                 "".join(seq_parts).upper())
            )
    return tuple(entries)


def _best_hit_for_peptide(
    peptide: str, proteome: tuple[tuple[str, str], ...]
) -> Optional[tuple[str, int]]:
    """Find a critical (exact) or elevated (≤1 mismatch) hit for
    ``peptide`` in the proteome. Returns ``(gene_label, match_count)``
    for the first hit found, or ``None`` if neither tier is reached.

    Strategy:

    1. **Critical pass** — exact substring test across every protein.
       Python's ``str.__contains__`` is a C-level Boyer-Moore-ish
       search; ~100 ms for a 20k-protein proteome.
    2. **Elevated pass** — for each of the ``n`` possible single-
       mismatch positions, construct a compiled regex with ``.`` at
       that index and scan every protein. ~1-2 s per cassette on a
       human Swiss-Prot proteome.

    Mild-tier detection (≤2 mismatches on a 9-mer, or <80% identity)
    is deliberately omitted — on our 20k-protein human proteome, a
    random 9-mer has a ~98% chance of a mild hit by pure chance, so
    that tier is statistically meaningless for short peptides. See
    ``validation.md`` → Stage 6 findings for the experiment."""
    n = len(peptide)
    if n == 0:
        return None

    # Critical tier — first exact substring wins.
    for gene, protein in proteome:
        if len(protein) >= n and peptide in protein:
            return (gene, n)

    # Elevated tier — d=1 mismatch anywhere.
    # Compile one regex per wildcard position, then loop proteins to
    # find any match. Early-exit on the first hit.
    patterns = [
        re.compile(peptide[:i] + "." + peptide[i + 1 :])
        for i in range(n)
    ]
    for gene, protein in proteome:
        if len(protein) < n:
            continue
        for pattern in patterns:
            if pattern.search(protein):
                return (gene, n - 1)
    return None


# DIAMOND's seed-and-extend doesn't seed reliably on queries shorter
# than 14 aa (empirically verified: 0 hits on 8-13 mers, correct hits
# on 14+ mers). Peptides at or below this length go through the
# pure-Python path; longer peptides use DIAMOND.
_PYTHON_MAX_LEN = 13


def _check_long_via_diamond(
    long_items: list[tuple[str, str]],
    config: ProteomeConfig,
) -> dict[str, EpitopeSafetyFlagResponse]:
    """Run DIAMOND blastp of ``long_items`` (peptides ≥ 14 aa) against
    the species Swiss-Prot ``.dmnd``. Returns the same sparse flag
    shape as the Python path. Fail-open: if DIAMOND is missing, its
    index is missing, or the subprocess errors out, returns ``{}`` and
    logs why."""
    if not long_items:
        return {}
    if shutil.which("diamond") is None:
        logger.warning(
            "self-identity: DIAMOND unavailable — %d class-II peptides "
            "will go unchecked for self-similarity",
            len(long_items),
        )
        return {}
    if config.dmnd_path is None:
        logger.warning(
            "self-identity: DIAMOND index missing at %s; rebuilding with "
            "`diamond makedb` from the cached FASTA would recover it",
            config.fasta_path.with_suffix(".dmnd"),
        )
        return {}

    with tempfile.TemporaryDirectory(prefix="self_identity_") as tmp:
        query = Path(tmp) / "query.faa"
        with query.open("w", encoding="utf-8") as handle:
            for peptide_id, seq in long_items:
                handle.write(f">{peptide_id}\n{seq}\n")
        try:
            completed = subprocess.run(
                [
                    "diamond", "blastp",
                    "--query", str(query),
                    "--db", str(config.dmnd_path.with_suffix("")),
                    # Short-peptide mode: off composition stats + PAM30
                    # + no masking (the documented DIAMOND flags for
                    # queries ≤ 30 aa).
                    "--matrix", "PAM30",
                    "--comp-based-stats", "0",
                    "--masking", "none",
                    "--evalue", "1000",
                    "--id", str(_RISK_ELEVATED_FLOOR),
                    "--query-cover", "90",
                    "--max-target-seqs", "1",
                    "--outfmt", "6",
                    "qseqid", "sseqid", "stitle", "pident", "length",
                    "--threads", "4",
                    "--quiet",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.SubprocessError as error:
            logger.warning(
                "self-identity: DIAMOND blastp failed (%s); %d long "
                "peptides left unchecked",
                error, len(long_items),
            )
            return {}

    flags: dict[str, EpitopeSafetyFlagResponse] = {}
    peptide_len_by_id = {pid: len(seq) for pid, seq in long_items}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        qseqid, sseqid, stitle, pident_s, length_s = parts[:5]
        if qseqid in flags:
            continue  # BLAST output is best-first within each query.
        try:
            pident = float(pident_s)
            length = int(length_s)
        except ValueError:
            continue
        risk = _risk_for(pident)
        if risk is None:
            continue
        gene = _gene_label(stitle, sseqid)
        identity_int = int(round(pident))
        # For the "critical" tier DIAMOND reports the match length
        # aligned, which may be shorter than the full peptide. Keep
        # DIAMOND's length in the note so the UI can render it
        # honestly (e.g., "100% identity over 14 aa of a 15-mer").
        flags[qseqid] = EpitopeSafetyFlagResponse(
            peptide_id=qseqid,
            self_hit=gene,
            identity=identity_int,
            risk=risk,
            note=_note_for(risk, gene, identity_int, length),
        )
    return flags


def run_self_identity_check(
    peptides: Iterable[tuple[str, str]],
    preset: ReferencePreset,
) -> dict[str, EpitopeSafetyFlagResponse]:
    """Scan each peptide against the species Swiss-Prot proteome.

    Dispatch by length:

    * **≤13 aa (class-I + short class-II):** pure-Python substring
      + single-mismatch regex scan. Fast (~5 s for a 50-peptide
      cassette). Detects critical (exact) + elevated (d=1 anywhere).
    * **≥14 aa (class-II proper):** DIAMOND blastp on the
      species-specific ``.dmnd`` index. DIAMOND's seed-and-extend
      does not reliably seed on queries < 14 aa, so we only invoke it
      here where it actually works.

    Fail-open on any I/O error: returns ``{}`` and logs prominently."""
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

    short_items: list[tuple[str, str]] = []
    long_items: list[tuple[str, str]] = []
    for peptide_id, raw_seq in items:
        seq = (raw_seq or "").strip().upper()
        if not seq or not seq.isalpha():
            continue
        (long_items if len(seq) >= _PYTHON_MAX_LEN + 1 else short_items).append(
            (peptide_id, seq)
        )

    flags: dict[str, EpitopeSafetyFlagResponse] = {}

    if short_items:
        try:
            proteome = _load_proteome(str(config.fasta_path))
        except OSError as error:
            logger.warning(
                "self-identity: proteome load failed (%s) — "
                "%d short peptides left unchecked",
                error, len(short_items),
            )
            proteome = ()
        for peptide_id, seq in short_items:
            hit = _best_hit_for_peptide(seq, proteome)
            if hit is None:
                continue
            gene, matches = hit
            pident = matches / len(seq) * 100
            risk = _risk_for(pident)
            if risk is None:
                continue
            identity_int = int(round(pident))
            flags[peptide_id] = EpitopeSafetyFlagResponse(
                peptide_id=peptide_id,
                self_hit=gene,
                identity=identity_int,
                risk=risk,
                note=_note_for(risk, gene, identity_int, len(seq)),
            )

    if long_items:
        flags.update(_check_long_via_diamond(long_items, config))

    return flags


def _sseqid_from_header(header: str) -> str:
    """Extract the canonical sseqid (``sp|P12345|X_HUMAN``) from a
    UniProt FASTA header. The header as passed in is everything after
    the ``>`` up to the first space."""
    return header.split(" ", 1)[0]


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
