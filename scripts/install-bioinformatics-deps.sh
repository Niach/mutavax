#!/usr/bin/env bash
# Install the three external binaries the live ingestion + alignment stages
# need: samtools, pigz, bwa-mem2.
#
# Tested on Linux Mint 22.3 / Ubuntu 24.04. Run with:
#
#   sudo bash scripts/install-bioinformatics-deps.sh
#
set -euo pipefail

BWA_VERSION="2.2.1"
BWA_RELEASE="bwa-mem2-${BWA_VERSION}_x64-linux"
BWA_TARBALL="${BWA_RELEASE}.tar.bz2"
BWA_URL="https://github.com/bwa-mem2/bwa-mem2/releases/download/v${BWA_VERSION}/${BWA_TARBALL}"
INSTALL_DIR="/usr/local/bin"
WORK_DIR="$(mktemp -d -t cancerstudio-bwa-mem2.XXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must be run as root (try: sudo bash $0)" >&2
  exit 1
fi

echo "==> Installing samtools and pigz via apt"
apt-get update
apt-get install -y samtools pigz

echo "==> Downloading bwa-mem2 v${BWA_VERSION}"
curl -fsSL "${BWA_URL}" -o "${WORK_DIR}/${BWA_TARBALL}"
tar -xjf "${WORK_DIR}/${BWA_TARBALL}" -C "${WORK_DIR}"

echo "==> Installing bwa-mem2 wrapper and SIMD variants to ${INSTALL_DIR}"
install -m 0755 "${WORK_DIR}/${BWA_RELEASE}/bwa-mem2" "${INSTALL_DIR}/bwa-mem2"
for variant in "${WORK_DIR}/${BWA_RELEASE}"/bwa-mem2.*; do
  install -m 0755 "${variant}" "${INSTALL_DIR}/$(basename "${variant}")"
done

echo
echo "==> Verifying installations"
echo -n "samtools: "; samtools --version | head -1
echo -n "pigz: "; pigz --version 2>&1 | head -1
echo -n "bwa-mem2: "; bwa-mem2 version 2>&1 | tail -1

echo
echo "Done. Restart the backend (kill the running uvicorn, re-launch) so the"
echo "new tools are picked up on PATH."
