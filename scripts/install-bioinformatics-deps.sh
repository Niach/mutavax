#!/usr/bin/env bash
# Install the three external binaries the live ingestion + alignment stages
# need: samtools, pigz, strobealign.
#
# Tested on Linux Mint 22.3 / Ubuntu 24.04. Run with:
#
#   sudo bash scripts/install-bioinformatics-deps.sh
#
set -euo pipefail

STROBEALIGN_VERSION="0.17.0"
STROBEALIGN_SRC_DIR="strobealign-${STROBEALIGN_VERSION}"
STROBEALIGN_TARBALL="v${STROBEALIGN_VERSION}.tar.gz"
STROBEALIGN_URL="https://github.com/ksahlin/strobealign/archive/refs/tags/${STROBEALIGN_TARBALL}"
INSTALL_DIR="/usr/local/bin"
WORK_DIR="$(mktemp -d -t cancerstudio-strobealign.XXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must be run as root (try: sudo bash $0)" >&2
  exit 1
fi

echo "==> Installing samtools, pigz, and the strobealign build toolchain via apt"
apt-get update
apt-get install -y samtools pigz build-essential cmake zlib1g-dev

echo "==> Downloading strobealign v${STROBEALIGN_VERSION}"
curl -fsSL "${STROBEALIGN_URL}" -o "${WORK_DIR}/${STROBEALIGN_TARBALL}"
tar -xzf "${WORK_DIR}/${STROBEALIGN_TARBALL}" -C "${WORK_DIR}"

echo "==> Building strobealign (Release)"
cmake -B "${WORK_DIR}/${STROBEALIGN_SRC_DIR}/build" \
      -S "${WORK_DIR}/${STROBEALIGN_SRC_DIR}" \
      -DCMAKE_BUILD_TYPE=Release
make -C "${WORK_DIR}/${STROBEALIGN_SRC_DIR}/build" -j"$(nproc)"

echo "==> Installing strobealign to ${INSTALL_DIR}"
install -m 0755 \
  "${WORK_DIR}/${STROBEALIGN_SRC_DIR}/build/strobealign" \
  "${INSTALL_DIR}/strobealign"

echo
echo "==> Verifying installations"
echo -n "samtools: "; samtools --version | head -1
echo -n "pigz: "; pigz --version 2>&1 | head -1
echo -n "strobealign: "; strobealign --version 2>&1 | tail -1

echo
echo "Done. Restart the backend (kill the running uvicorn, re-launch) so the"
echo "new tools are picked up on PATH."
