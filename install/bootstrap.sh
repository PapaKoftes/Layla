#!/usr/bin/env bash
# Layla - one-command installer (macOS / Linux) powered by uv.
#
# Installs Python ITSELF + every dependency, then provisions a model for your
# hardware and runs a deep self-test. No system Python, no C/C++ toolchain, no
# admin: uv fetches a standalone Python and we install prebuilt CPU wheels for
# llama-cpp + torch (the same wheel indexes the Windows installer uses), so there
# is nothing to compile on any OS.
#
#   git clone https://github.com/PapaKoftes/Layla.git
#   cd Layla && ./install/bootstrap.sh
#
# Options:
#   --prefer quality|balanced|lite|speed   model bias for detected hardware (default balanced)
#   --skip-model                           set up the env but don't download a model yet
#   --verify                               skip install; just run the deep self-test
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PREFER="balanced"; SKIP_MODEL=0; VERIFY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prefer) PREFER="$2"; shift 2;;
    --skip-model) SKIP_MODEL=1; shift;;
    --verify) VERIFY=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

echo ""
echo "  LAYLA - installer (uv, compiler-free)"
echo "  -------------------------------------"

LLAMA_INDEX="https://abetlen.github.io/llama-cpp-python/whl/cpu"
LLAMA_SPEC="llama-cpp-python>=0.3.1,<0.4"
VPY=".venv/bin/python"

# 1) ensure uv (single static binary; needs no Python, no admin)
if ! command -v uv >/dev/null 2>&1; then
  echo "  [1/6] Installing uv (Astral) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # the installer drops uv here by default; make it visible for the rest of this run
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "  [!] uv is installed but not on PATH. Open a NEW terminal and re-run this script." >&2
  exit 1
fi
echo "  [1/6] uv $(uv --version | awk '{print $2}')"

# --verify: just re-run the self-test against an existing venv
if [ "$VERIFY" = "1" ]; then
  [ -x "$VPY" ] || { echo "  No .venv found - run without --verify first." >&2; exit 1; }
  exec "$VPY" scripts/selftest.py --server
fi

# 2) Python 3.12 (managed standalone build - no system Python required)
echo "  [2/6] Provisioning Python 3.12 ..."
uv python install 3.12

# 3) virtual environment
echo "  [3/6] Creating .venv ..."
uv venv --python 3.12 .venv

# 4) compiler-free heavy wheels FIRST (prebuilt; no toolchain), then the app
echo "  [4/6] Installing dependencies (prebuilt CPU wheels - no compiler) ..."
uv pip install --python "$VPY" "$LLAMA_SPEC" \
  --extra-index-url "$LLAMA_INDEX" --index-strategy unsafe-best-match
# torch: Linux uses the CPU-only wheel index (no CUDA, smaller). macOS wheels are NOT on that index
# (download.pytorch.org/whl/cpu has no macOS build) — pinning it there made the install fail on Macs,
# so on Darwin install torch from the default PyPI index instead.
if [ "$(uname -s)" = "Darwin" ]; then
  uv pip install --python "$VPY" torch
else
  uv pip install --python "$VPY" torch --index-url https://download.pytorch.org/whl/cpu
fi
uv pip install --python "$VPY" -e ".[cpu,llm]"

# 5) detect hardware -> provision the best coding kit + write config
if [ "$SKIP_MODEL" = "1" ]; then
  echo "  [5/6] Skipping model download (--skip-model)."
  echo "        Later: ( cd agent && ../$VPY install/provision_model.py )"
else
  echo "  [5/6] Detecting hardware and provisioning a model ($PREFER) ..."
  ( cd agent && "../$VPY" install/provision_model.py --prefer "$PREFER" )
fi

# 6) deep self-test - prove the model loads + completes a real turn (SIGILL/OOM/corrupt gate)
if [ "$SKIP_MODEL" != "1" ]; then
  echo "  [6/6] Deep self-test (model load + real inference turn) ..."
  if ! "$VPY" scripts/selftest.py; then
    echo "  Self-test failed - reinstalling the llama-cpp CPU wheel (handles a corrupt wheel"
    echo "  or an AVX build this CPU can't run) and retrying ..."
    uv pip install --python "$VPY" --reinstall "$LLAMA_SPEC" \
      --extra-index-url "$LLAMA_INDEX" --index-strategy unsafe-best-match
    "$VPY" scripts/selftest.py || {
      echo "  Self-test still failing - see the [FAIL] lines above. Try --prefer lite for a"
      echo "  smaller model, or free more RAM. The install is otherwise complete." >&2
      exit 1
    }
  fi
  echo "  Self-test passed - Layla loads a model and completes a turn on this machine."
fi

echo ""
echo "  Done. Start Layla:  ./layla          (or: $VPY agent/serve.py)"
echo "  Layla opens at:     http://127.0.0.1:8000/ui"
echo "  Re-check anytime:   ./install/bootstrap.sh --verify"
echo ""
