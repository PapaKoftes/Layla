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
# It swaps the operator's runtime_config.json for a stub and ALWAYS restores it — and, since
# the restore is the single most damaging thing this script can get wrong, it now VERIFIES the
# restore by hash and refuses to delete the backup unless the verification passed.
#
# Output: the raw pytest tail plus a machine-readable last line:
#   CI_GATE_RESULT status=<STATUS> exit=<code> passed=<n> failed=<n> errors=<n>
# STATUS is the honest one: GREEN / RED / TIMEOUT / ABORTED / COLLECT_ERROR / NO_TESTS / SETUP
# / RESTORE_FAILED. Non-zero exit === do not merge. Anything other than status=GREEN === do not
# merge, even if failed=0 (see the TIMEOUT/ABORTED note below).
#
# READ THE **LAST** CI_GATE_RESULT LINE — it is the authoritative one. The restore runs in the
# EXIT trap, i.e. AFTER the normal result line is printed, so a run whose tests passed but whose
# config restore FAILED prints `status=GREEN ...` and then `status=RESTORE_FAILED ...`. A consumer
# that takes the first match (or greps for `status=GREEN`) reads a clobbered config as a good
# green. Take the last line, or check the exit code.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AUDIT_DIR="$ROOT/.planning/audit"
cd "$ROOT/agent" || { echo "CI_GATE_RESULT status=SETUP exit=97 passed=-1 failed=-1 errors=-1 (cannot cd agent)"; exit 97; }

RC="runtime_config.json"
# FIXED backup path (was: mktemp). A random temp name cannot be found again after a crash, so
# an interrupted run left an unfindable orphan AND a clobbered config. A deterministic path is
# what makes the orphan check at the bottom of this block possible at all.
BAK="$AUDIT_DIR/.ci-gate-rc.bak"
STAMP="$AUDIT_DIR/.ci-gate-rc.sha"

shout() { printf '\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n%s\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n' "$*" >&2; }
hash_of() { sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }

# A file is "the operator's real config" if it is NOT the CI stub and is substantial.
# The real config is ~16KB / 437 keys; the stub is ~335 bytes / 11 keys.
is_operator_config() {
  [ -f "$1" ] || return 1
  grep -q 'ci-stub\.gguf' "$1" && return 1
  [ "$(wc -c < "$1" | tr -d ' ')" -gt 2000 ] || return 1
  return 0
}

# ---------------------------------------------------------------------------------------
# SINGLE-INSTANCE LOCK. Two gates running at once each back up runtime_config.json, but the
# second backs up the FIRST's already-swapped stub — so "restore" restores the stub and the
# operator config is permanently clobbered. Refuse if another gate holds the lock (mkdir is
# atomic). A lock left by a SIGKILLed run is reclaimed only after proving the owner is dead,
# so a crash cannot wedge the gate forever.
# ---------------------------------------------------------------------------------------
LOCKDIR="$AUDIT_DIR/.ci-gate.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  OWNER="$(cat "$LOCKDIR/pid" 2>/dev/null || echo "")"
  if [ -n "$OWNER" ] && kill -0 "$OWNER" 2>/dev/null; then
    echo "CI_GATE_RESULT status=SETUP exit=96 passed=-1 failed=-1 errors=-1 (another ci-gate (pid $OWNER) is running — refusing to avoid config clobber)"
    exit 96
  fi
  shout "STALE LOCK from dead pid '${OWNER:-unknown}' — reclaiming. If a gate IS running, kill this one now."
  rm -rf "$LOCKDIR" && mkdir "$LOCKDIR" || {
    echo "CI_GATE_RESULT status=SETUP exit=96 passed=-1 failed=-1 errors=-1 (cannot reclaim stale lock)"; exit 96; }
fi
echo $$ > "$LOCKDIR/pid"

# ---------------------------------------------------------------------------------------
# ORPHANED-BACKUP CHECK — the A1 bug. A pytest-timeout session kill previously left
# runtime_config.json as the 11-key ci-stub while the backup sat orphaned in a temp dir. The
# running operator app then read the stub for ~10 minutes; it survived only because it never
# reloaded. If we blindly backed up again here we would snapshot the STUB and make the
# clobber permanent on restore. So: never back up over an existing orphan — repair, or refuse.
# ---------------------------------------------------------------------------------------
if [ -e "$BAK" ]; then
  shout "ORPHANED BACKUP $BAK — a previous ci-gate run did not finish its restore."
  if ! is_operator_config "$BAK"; then
    shout "REFUSING: the orphaned backup is not a valid operator config (it may itself be a stub).
Not touching $RC. Inspect both files by hand:
  backup: $BAK
  live:   $ROOT/agent/$RC"
    rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
    echo "CI_GATE_RESULT status=SETUP exit=94 passed=-1 failed=-1 errors=-1 (orphaned backup is not a valid operator config)"
    exit 94
  fi
  if is_operator_config "$RC"; then
    KEEP="$BAK.stale.$(date +%s)"
    mv "$BAK" "$KEEP"
    rm -f "$STAMP"
    shout "Live $RC is intact; orphan archived to $KEEP (delete it once you have checked it). Continuing."
  else
    cp "$BAK" "$RC" || { shout "RESTORE FROM ORPHAN FAILED"; rm -rf "$LOCKDIR"; \
      echo "CI_GATE_RESULT status=SETUP exit=93 passed=-1 failed=-1 errors=-1 (could not restore orphaned backup)"; exit 93; }
    if is_operator_config "$RC"; then
      rm -f "$BAK" "$STAMP"
      shout "REPAIRED: $RC was a stub and has been restored from the orphaned backup.
Refusing to also run tests in this invocation — verify your config, then re-run the gate."
      rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
      echo "CI_GATE_RESULT status=SETUP exit=95 passed=-1 failed=-1 errors=-1 (repaired clobbered config from orphaned backup — re-run the gate)"
      exit 95
    fi
    shout "RESTORE FROM ORPHAN DID NOT PRODUCE A VALID CONFIG — leaving everything in place."
    rm -rf "$LOCKDIR"
    echo "CI_GATE_RESULT status=SETUP exit=93 passed=-1 failed=-1 errors=-1 (restore from orphan did not verify)"
    exit 93
  fi
fi

# Refuse to start if the live config is already a stub with no backup to repair from — that is
# a clobber we cannot undo, and backing it up would bake it in.
if [ -f "$RC" ] && ! is_operator_config "$RC"; then
  shout "REFUSING: $RC already looks like a CI stub and there is no backup to restore from.
Restore your operator config (git / your own backup) before running the gate."
  rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
  echo "CI_GATE_RESULT status=SETUP exit=92 passed=-1 failed=-1 errors=-1 (live config is already a stub, no backup)"
  exit 92
fi

HAD_RC=0
if [ -f "$RC" ]; then
  cp "$RC" "$BAK" || { echo "CI_GATE_RESULT status=SETUP exit=91 passed=-1 failed=-1 errors=-1 (cannot back up $RC)"; rm -rf "$LOCKDIR"; exit 91; }
  hash_of "$BAK" > "$STAMP"
  HAD_RC=1
fi

# restore() is idempotent (signal handler + EXIT handler both fire) and VERIFIES. The old
# version ended with `rm -f "$BAK"` unconditionally, so a restore that silently failed left no
# backup and no warning. Now the backup is deleted ONLY after the hash matches.
_RESTORED=0
restore() {
  [ "$_RESTORED" -eq 1 ] && return 0
  _RESTORED=1
  if [ "$HAD_RC" -eq 1 ]; then
    if ! cp "$BAK" "$RC" 2>/dev/null; then
      shout "RESTORE FAILED: could not copy $BAK back to $RC.
YOUR OPERATOR CONFIG IS STILL THE CI STUB. The backup is preserved at:
  $BAK"
      echo "CI_GATE_RESTORE_FAILED backup=$BAK"
      # Overriding result line: the EXIT trap runs AFTER the normal CI_GATE_RESULT, so a
      # consumer reading the LAST CI_GATE_RESULT gets the truth (a GREEN test run with a
      # clobbered config on disk is NOT a usable green).
      echo "CI_GATE_RESULT status=RESTORE_FAILED exit=89 passed=-1 failed=-1 errors=-1 (tests may have passed, but $RC was NOT restored)"
      rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
      return 1
    fi
    WANT="$(cat "$STAMP" 2>/dev/null || echo "")"
    GOT="$(hash_of "$RC")"
    if [ -z "$WANT" ] || [ "$WANT" != "$GOT" ]; then
      shout "RESTORE DID NOT VERIFY: $RC hash '$GOT' != expected '$WANT'.
The backup has been PRESERVED (not deleted) at:
  $BAK
Compare them by hand before running anything else."
      echo "CI_GATE_RESTORE_FAILED backup=$BAK"
      # Overriding result line: the EXIT trap runs AFTER the normal CI_GATE_RESULT, so a
      # consumer reading the LAST CI_GATE_RESULT gets the truth (a GREEN test run with a
      # clobbered config on disk is NOT a usable green).
      echo "CI_GATE_RESULT status=RESTORE_FAILED exit=89 passed=-1 failed=-1 errors=-1 (tests may have passed, but $RC was NOT restored)"
      rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
      return 1
    fi
    rm -f "$BAK" "$STAMP"
  else
    rm -f "$RC" "$BAK" "$STAMP"
  fi
  rmdir "$LOCKDIR" 2>/dev/null || rm -rf "$LOCKDIR"
  return 0
}
# HUP/QUIT added: a closed terminal or a session kill previously bypassed the trap entirely.
trap 'restore; exit 2' INT TERM HUP QUIT
# `|| exit 89`: the restore runs in the EXIT trap, i.e. AFTER the result line and after the
# script's own `exit "$CODE"` — so without this a FAILED restore still exited 0 and the run was
# reported GREEN while the operator's config sat clobbered on disk (caught by the sandbox
# corrupt-backup test). Exiting from inside the EXIT trap overrides that status.
trap 'restore || exit 89' EXIT

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
# -p no:randomly: pytest-randomly reorders every run, so a slow-test/timeout interaction made
#   "green" a coin flip (one machine exit=0 3433 passed, another exit=1 failed=0 three times in
#   a row). A gate must be reproducible before it can be authoritative.
# NO --timeout here: the old --timeout=60 silently OVERRODE agent/pytest.ini's timeout=120 and
#   killed genuinely slow real-venv tests. pytest.ini is now the single source of truth.
# PYTHONUNBUFFERED + -v: so the last line of the log names the test that was RUNNING when a
#   session-killing timeout hit. With -q and block buffering that information was lost.
CI=true PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 "$PY" -m pytest tests/ \
  -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint" \
  -p no:randomly -p no:cacheprovider -v --durations=10 > "$OUT" 2>&1
CODE=$?

grep -E "^FAILED |^ERROR " "$OUT" || true
grep -E "slowest .* durations" -A 11 "$OUT" || true
tail -n 3 "$OUT"

# ---------------------------------------------------------------------------------------
# HONEST RESULT. The old line counted `^FAILED ` greps, so a session-killing timeout — which
# prints NO failures and NO summary — reported "failed=0" and anyone grepping for that read a
# DEAD suite as green. Counts now come from pytest's own summary, and the absence of that
# summary is itself a reportable status rather than a silent zero.
# ---------------------------------------------------------------------------------------
SUMMARY="$(grep -E "^=+ .*(passed|failed|error|no tests ran).* =+$" "$OUT" | tail -n 1)"
count_of() { echo "$SUMMARY" | grep -oE "[0-9]+ $1" | head -n 1 | grep -oE "^[0-9]+" || true; }
NPASS="$(count_of passed)"; NPASS="${NPASS:-0}"
NFAIL="$(count_of failed)"; NFAIL="${NFAIL:-0}"
NERR="$(count_of 'errors?')"; NERR="${NERR:-0}"

if [ -z "$SUMMARY" ]; then
  # No summary line === pytest never finished. Never report failed=0 here.
  NPASS=-1; NFAIL=-1; NERR=-1
  if grep -q "Timeout" "$OUT"; then STATUS="TIMEOUT"; else STATUS="ABORTED"; fi
  DIED="$(grep -oE "^tests/[^ ]+::[^ ]+" "$OUT" | tail -n 1)"
  [ -z "$DIED" ] && DIED="$(grep -oE "in (test_[A-Za-z0-9_]+)" "$OUT" | tail -n 1)"
  shout "$STATUS: pytest produced no summary line — the suite DID NOT COMPLETE.
This is NOT a pass. Last test seen: ${DIED:-<unknown>}
Full log preserved at: $OUT"
  echo "CI_GATE_LAST_TEST ${DIED:-unknown}"
  KEEP_LOG=1
elif [ "$CODE" -eq 5 ]; then
  STATUS="NO_TESTS"
elif [ "$NERR" -gt 0 ] && [ "$NPASS" -eq 0 ] && [ "$NFAIL" -eq 0 ]; then
  STATUS="COLLECT_ERROR"
elif [ "$CODE" -eq 0 ] && [ "$NFAIL" -eq 0 ] && [ "$NERR" -eq 0 ]; then
  STATUS="GREEN"
else
  STATUS="RED"
fi

# ---------------------------------------------------------------------------------------
# MINIMUM-PASS FLOOR. "0 failures" is not "the suite ran". A marker-expression typo, a conftest
# import guard, or a plugin that deselects everything collapses collection and prints e.g.
# "1 passed" — which satisfies every check above and reports GREEN. That is the SAME silent-zero
# class as the timeout bug this script was rewritten to kill (and as `--timeout=60` quietly
# overriding pytest.ini). A floor is the only thing that notices work that never happened.
# Raise it when the suite grows; never lower it to make a run pass.
MIN_PASS=3400
if [ "$STATUS" = "GREEN" ] && [ "$NPASS" -lt "$MIN_PASS" ]; then
  STATUS="RED"
  shout "COLLECTION COLLAPSE: only $NPASS tests passed, floor is $MIN_PASS.
Zero failures does NOT mean the suite ran. Something stopped tests being collected —
check the marker expression, conftest imports, and plugin deselection before trusting anything."
fi

echo "CI_GATE_RESULT status=$STATUS exit=$CODE passed=$NPASS failed=$NFAIL errors=$NERR"
if [ "${KEEP_LOG:-0}" -eq 1 ]; then
  echo "CI_GATE_LOG $OUT"
else
  rm -f "$OUT"
fi
# A non-completing suite must never exit 0, whatever pytest's own code was.
if [ "$STATUS" != "GREEN" ] && [ "$CODE" -eq 0 ]; then exit 90; fi
exit "$CODE"
