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
#   --accel auto|gpu|cpu                   NVIDIA GPU offload: auto-detect (default), force on, or force off
#   --skip-model                           set up the env but don't download a model yet
#   --verify                               skip install; just run the deep self-test
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PREFER="balanced"; SKIP_MODEL=0; VERIFY=0; ACCEL="${ACCEL:-auto}"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefer) PREFER="$2"; shift 2;;
    --accel) ACCEL="$2"; shift 2;;
    --skip-model) SKIP_MODEL=1; shift;;
    --verify) VERIFY=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

echo ""
echo "  LAYLA - installer (uv, compiler-free)"
echo "  -------------------------------------"

LLAMA_INDEX_CPU="https://abetlen.github.io/llama-cpp-python/whl/cpu"
LLAMA_INDEX_CUDA="https://abetlen.github.io/llama-cpp-python/whl/cu124"
LLAMA_SPEC="llama-cpp-python>=0.3.1,<0.4"
VPY=".venv/bin/python"

# CPU vs CUDA llama.cpp build. GPU offload (n_gpu_layers, set by provision_model when a GPU is
# detected) does nothing unless the CUDA wheel is installed - the CPU wheel silently ignores it.
# Auto-detect an NVIDIA card via nvidia-smi (Linux only; macOS uses the CPU wheel - a Metal build
# needs a source compile). ACCEL=gpu|cpu forces it. The CUDA wheel bundles the CUDA 12.4 runtime;
# if it fails to load, the self-test step falls back to the CPU wheel so the install still works.
USE_GPU=0
GPU_NAME=""
if [ "${ACCEL:-auto}" != "cpu" ] && [ "$(uname -s)" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
  GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 | sed 's/^ *//;s/ *$//')"
  [ -n "$GPU_NAME" ] && USE_GPU=1
fi
if [ "${ACCEL:-auto}" = "gpu" ] && [ "$USE_GPU" = "0" ]; then
  echo "  ACCEL=gpu requested but no NVIDIA GPU found (nvidia-smi / Linux only). Using the CPU build."
fi
if [ "$USE_GPU" = "1" ]; then LLAMA_INDEX="$LLAMA_INDEX_CUDA"; else LLAMA_INDEX="$LLAMA_INDEX_CPU"; fi

# 1) ensure uv (single static binary; needs no Python, no admin)
if ! command -v uv >/dev/null 2>&1; then
  echo "  [1/7] Installing uv (Astral) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # the installer drops uv here by default; make it visible for the rest of this run
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "  [!] uv is installed but not on PATH. Open a NEW terminal and re-run this script." >&2
  exit 1
fi
echo "  [1/7] uv $(uv --version | awk '{print $2}')"

# --verify: just re-run the self-test against an existing venv
if [ "$VERIFY" = "1" ]; then
  [ -x "$VPY" ] || { echo "  No .venv found - run without --verify first." >&2; exit 1; }
  exec "$VPY" scripts/selftest.py --server
fi

# 2) Python 3.12 (managed standalone build - no system Python required)
echo "  [2/7] Provisioning Python 3.12 ..."
uv python install 3.12

# 3) virtual environment. Reuse an existing one so a RE-RUN (e.g. a bugfix update) does not wipe the
# venv and reinstall every wheel - uv pip install below is idempotent. (To switch CPU<->GPU on an
# existing install, re-run with a removed .venv or use --accel with a fresh env.)
if [ -x "$VPY" ]; then
  echo "  [3/7] Reusing existing .venv (re-run: nothing re-downloaded that is already present)"
else
  echo "  [3/7] Creating .venv ..."
  uv venv --python 3.12 .venv
fi

# 4) compiler-free heavy wheels FIRST (prebuilt; no toolchain), then the app
if [ "$USE_GPU" = "1" ]; then
  echo "  [4/7] NVIDIA GPU detected ($GPU_NAME) - installing the CUDA llama.cpp build for GPU offload ..."
else
  echo "  [4/7] Installing dependencies (prebuilt CPU wheels - no compiler) ..."
fi
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
# research + crawl: web search, article extraction, PDF/arXiv/Wikipedia reading. These were
# omitted, so a bootstrap install came up with the web-facing tools permanently degraded —
# the README advertises "can browse the web" and the tool then reported a missing library.
# Pure-Python/small wheels, no compiler. (playwright still needs `playwright install chromium`
# for real browser automation — see README.)
uv pip install --python "$VPY" -e ".[cpu,llm,research,crawl]"

# 5) detect hardware -> provision the best coding kit + write config
if [ "$SKIP_MODEL" = "1" ]; then
  echo "  [5/7] Skipping model download (--skip-model)."
  echo "        Later: ( cd agent && ../$VPY install/provision_model.py )"
else
  echo "  [5/7] Detecting hardware and provisioning a model ($PREFER) ..."
  ( cd agent && "../$VPY" install/provision_model.py --prefer "$PREFER" --skip-embedder )
fi

# 6) embedding model - fetched HERE, at install time, while we know the machine is online.
# It used to be downloaded from HuggingFace on FIRST USE, so anyone who installed and then went
# offline (the advertised way to run Layla) silently got keyword-only search forever. Non-fatal:
# `set -e` is suppressed on purpose, because everything above is already installed and works.
echo "  [6/7] Fetching the embedding model (offline semantic search) ..."
if ! ( cd agent && "../$VPY" install/provision_model.py --embedder-only ); then
  echo "  Embedding model not installed - semantic search will use KEYWORD-ONLY matching."
  echo "  Fix later (needs internet): ( cd agent && ../$VPY install/provision_model.py --embedder-only )"
fi

# 7) deep self-test - prove the model loads + completes a real turn (SIGILL/OOM/corrupt gate)
if [ "$SKIP_MODEL" != "1" ]; then
  echo "  [7/7] Deep self-test (model load + real inference turn) ..."
  if ! "$VPY" scripts/selftest.py; then
    RETRY_INDEX="$LLAMA_INDEX"
    if [ "$USE_GPU" = "1" ]; then
      echo "  Self-test failed with the CUDA build - the NVIDIA driver may be too old or a runtime"
      echo "  library is missing. Falling back to the CPU build so Layla still runs (update your"
      echo "  driver, then re-run to get GPU speed) ..."
      RETRY_INDEX="$LLAMA_INDEX_CPU"
      # CPU build cannot offload; record n_gpu_layers=0 so config reflects reality.
      "$VPY" -c "import json,pathlib; p=pathlib.Path('agent/runtime_config.json'); d=json.loads(p.read_text('utf-8')) if p.exists() else {}; d['n_gpu_layers']=0; p.write_text(json.dumps(d,indent=2),encoding='utf-8')" 2>/dev/null || true
    else
      echo "  Self-test failed - reinstalling the llama-cpp CPU wheel (handles a corrupt wheel"
      echo "  or an AVX build this CPU can't run) and retrying ..."
    fi
    uv pip install --python "$VPY" --reinstall "$LLAMA_SPEC" \
      --extra-index-url "$RETRY_INDEX" --index-strategy unsafe-best-match
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
