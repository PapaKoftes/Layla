#!/usr/bin/env bash
# ci-gate.sh — authoritative green-gate for the self-running audit loop.
#
# WHY: the loop's fast `test_cmd` runs against whatever runtime_config.json the operator
# has on disk. That config both (a) MASKS failures that only surface under CI's clean,
# tiny-context stub config, and (b) INTRODUCES operator-only artifacts (litellm/meili/etc).
# A green run there is NOT the same as a green CI run — which is what actually gates a merge.
# This script reproduces CI's exact environment (clean stub config + CI=true + CI marker
# expression + n_ctx=2048) so "green" means "CI will be green".
#
# It ALWAYS restores the operator's runtime_config.json (trap on EXIT), even on failure/interrupt.
#
# Output: the raw pytest tail plus a machine-readable last line:
#   CI_GATE_RESULT exit=<code> failed=<n>
# and every "FAILED tests/..." node id on its own line, so the integrator can diff against
# the CI baseline. Non-zero exit === at least one failing test under CI config.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/agent" || { echo "CI_GATE_RESULT exit=97 failed=-1 (cannot cd agent)"; exit 97; }

RC="runtime_config.json"
BAK="$(mktemp -t layla-rc.XXXXXX)"
HAD_RC=0
if [ -f "$RC" ]; then cp "$RC" "$BAK"; HAD_RC=1; fi

restore() {
  if [ "$HAD_RC" -eq 1 ]; then cp "$BAK" "$RC"; else rm -f "$RC"; fi
  rm -f "$BAK"
}
trap restore EXIT INT TERM

# Exact CI stub config (mirrors .github/workflows/ci.yml "Write CI runtime config").
cat > "$RC" <<'EOF'
{
  "model_filename": "ci-stub.gguf",
  "use_chroma": false,
  "sandbox_root": "/tmp/layla-ci",
  "max_tool_calls": 2,
  "max_runtime_seconds": 30,
  "n_ctx": 2048,
  "n_gpu_layers": 0,
  "scheduler_study_enabled": false,
  "embedding_cache_warmup_enabled": false,
  "embedder_prewarm_enabled": false,
  "llm_prewarm_enabled": false
}
EOF

PY="../.venv-test/Scripts/python.exe"
OUT="$(mktemp -t layla-ci-out.XXXXXX)"
# Same marker expression the CI job uses; no --cov (speed) — coverage isn't gated.
CI=true PYTHONIOENCODING=utf-8 "$PY" -m pytest tests/ \
  -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint" \
  --timeout=60 -p no:cacheprovider -q > "$OUT" 2>&1
CODE=$?

grep -E "^FAILED " "$OUT" || true
tail -n 3 "$OUT"
NFAIL="$(grep -cE "^FAILED " "$OUT" || true)"
echo "CI_GATE_RESULT exit=$CODE failed=$NFAIL"
rm -f "$OUT"
exit "$CODE"
