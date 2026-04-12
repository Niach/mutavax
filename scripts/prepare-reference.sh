#!/usr/bin/env bash
# Standalone reference indexer for cancerstudio.
#
# Run this once in a clean terminal (dev servers + Electron + browser closed)
# when the backend's in-process "Preparing reference" step doesn't have enough
# memory to finish bwa-mem2 index. It re-runs the index on the already-
# downloaded FASTA in isolation, so nothing else is fighting for RAM.
#
# Usage:
#   scripts/prepare-reference.sh                 # indexes GRCh38 by default
#   scripts/prepare-reference.sh /path/genome.fa # indexes a specific FASTA
#
# After it finishes, restart the backend and the alignment stage will detect
# the existing index and skip the bootstrap step entirely.
set -euo pipefail

DEFAULT_FASTA="${HOME}/.local/share/cancerstudio/references/grch38/genome.fa"
FASTA="${1:-${DEFAULT_FASTA}}"

REQUIRED_GB=30
REQUIRED_KB=$(( REQUIRED_GB * 1024 * 1024 ))

if ! command -v bwa-mem2 > /dev/null; then
  echo "ERROR: bwa-mem2 is not on PATH." >&2
  echo "Run: sudo bash scripts/install-bioinformatics-deps.sh" >&2
  exit 1
fi

if ! command -v samtools > /dev/null; then
  echo "ERROR: samtools is not on PATH." >&2
  echo "Run: sudo bash scripts/install-bioinformatics-deps.sh" >&2
  exit 1
fi

if [[ ! -f "${FASTA}" ]]; then
  echo "ERROR: Reference FASTA not found at ${FASTA}" >&2
  echo "Point the script at an existing .fa file or let the backend download it first:" >&2
  echo "  scripts/prepare-reference.sh /path/to/genome.fa" >&2
  exit 1
fi

# /proc/meminfo MemAvailable is in kB. Compare to our requirement in kB.
if [[ -r /proc/meminfo ]]; then
  available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  available_gb=$(( available_kb / 1024 / 1024 ))
  if [[ "${available_kb}" -lt "${REQUIRED_KB}" ]]; then
    echo "ERROR: only ${available_gb} GB of memory is available (need at least ${REQUIRED_GB} GB)." >&2
    echo "Close heavy applications (browser, Electron, IDE, dev servers) and try again." >&2
    echo "bwa-mem2 index peaks at ~28 GB while building genome.fa.bwt.2bit.64." >&2
    exit 2
  fi
  echo "==> ${available_gb} GB of memory available (need ${REQUIRED_GB} GB, peak ~28 GB)"
fi

bundle_dir="$(dirname "${FASTA}")"
echo "==> Reference FASTA: ${FASTA}"
echo "==> Bundle directory: ${bundle_dir}"

if [[ ! -f "${FASTA}.fai" ]]; then
  echo "==> Running samtools faidx"
  samtools faidx "${FASTA}"
else
  echo "==> Skipping samtools faidx (${FASTA}.fai already exists)"
fi

# bwa-mem2 index doesn't support resuming, so the partial state gets overwritten.
# Leaving the old files in place is fine — bwa-mem2 just rewrites them.
if [[ -f "${FASTA}.bwt.2bit.64" ]]; then
  echo "==> ${FASTA}.bwt.2bit.64 already present; nothing to do."
  exit 0
fi

echo "==> Running bwa-mem2 index (this takes ~10-15 minutes and peaks at ~28 GB RAM)"
echo "    Keep an eye on memory; if it spills into swap, kill this and close more apps."
echo
bwa-mem2 index "${FASTA}"

echo
echo "==> Done. Full index written to ${bundle_dir}:"
ls -lh "${bundle_dir}"/genome.fa.* 2>&1 | sed 's/^/    /'
echo
echo "Restart the backend and the alignment stage will skip bootstrapping."
