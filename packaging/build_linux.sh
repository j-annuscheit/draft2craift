#!/usr/bin/env bash
# Build script for Linux — mirrors build_windows.ps1
#
# Usage:
#   bash packaging/build_linux.sh [cpu|cuda|metal] [full|minimal]
#
# Build profiles:
#   full    = all features, AGPL-3.0 distribution (default)
#             bundles pymupdf4llm (AGPL), html2text (GPL)
#   minimal = no AGPL/GPL optional packages, reduced PDF/HTML support
#             suitable if downstream consumers require a non-copyleft binary
#
# Outputs:
#   dist_portable/draft2craift-<PROFILE>-Portable-Linux-<VARIANT>.tar.gz
#
# Requirements:
#   python3, pip, optionally cmake (for CUDA/Metal llama-cpp-python builds)

set -euo pipefail

VARIANT="${1:-cpu}"      # cpu | cuda | metal
PROFILE="${2:-full}"     # full | minimal

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PROFILE_UPPER="${PROFILE^^}"
VARIANT_UPPER="${VARIANT^^}"
VENV_DIR=".venv-$VARIANT"

echo "==> Variant: $VARIANT_UPPER   Build profile: $PROFILE_UPPER"

# ── Create / reuse venv ───────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip install -U pip
pip install -U pyinstaller

# ── Install base deps (llama-cpp-python handled separately per variant) ───────
grep -v "^\s*llama-cpp-python" requirements.txt > /tmp/draft2craift-req-no-llama.txt
pip install -r /tmp/draft2craift-req-no-llama.txt
rm -f /tmp/draft2craift-req-no-llama.txt

# ── Optional profile deps ─────────────────────────────────────────────────────
OPT_REQ="packaging/requirements-optional-$PROFILE.txt"
if [ -f "$OPT_REQ" ]; then
  pip install -r "$OPT_REQ"
else
  echo "WARNING: Optional requirements file not found: $OPT_REQ"
fi

# ── Enforce minimal profile: remove AGPL / GPL packages ──────────────────────
if [ "$PROFILE" = "minimal" ]; then
  pip uninstall -y pymupdf pymupdf4llm html2text 2>/dev/null || true
fi

# ── Install llama-cpp-python for the selected compute variant ─────────────────
case "$VARIANT" in
  cuda)
    CMAKE_ARGS="-DGGML_CUDA=on" \
      pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python
    ;;
  metal)
    CMAKE_ARGS="-DGGML_METAL=on" \
      pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python
    ;;
  *)
    pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python
    ;;
esac

# ── PyInstaller build ─────────────────────────────────────────────────────────
PYI_ARGS=(--noconfirm --clean)

if [ "$PROFILE" = "minimal" ]; then
  PYI_ARGS+=(
    --exclude-module=fitz
    --exclude-module=pymupdf
    --exclude-module=pymupdf4llm
    --exclude-module=html2text
  )
fi

PYI_ARGS+=("packaging/draft2craift.spec")
pyinstaller "${PYI_ARGS[@]}"

# ── Package as portable tar.gz ────────────────────────────────────────────────
DIST_DIR="$REPO_ROOT/dist/draft2craift"
if [ ! -d "$DIST_DIR" ]; then
  echo "ERROR: PyInstaller output not found at $DIST_DIR" >&2
  exit 1
fi

PORTABLE_DIR="$REPO_ROOT/dist_portable"
mkdir -p "$PORTABLE_DIR"

TARBALL="$PORTABLE_DIR/draft2craift-${PROFILE_UPPER}-Portable-Linux-${VARIANT_UPPER}.tar.gz"
tar -czf "$TARBALL" -C "$REPO_ROOT/dist" draft2craift

echo ""
echo "==> Portable Linux bundle: $TARBALL"
