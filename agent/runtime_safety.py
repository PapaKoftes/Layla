import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from layla.time_utils import utcnow
from services.workspace.file_lock import path_lock

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
GOV_PATH = AGENT_DIR / ".governance"
APPROVAL_FILE = GOV_PATH / "approvals.json"
EXEC_LOG_FILE = GOV_PATH / "execution_log.jsonl"  # append-only JSON-lines (see log_execution)
_EXEC_LOG_LEGACY = GOV_PATH / "execution_log.json"  # pre-1.0 whole-file array; removed by _bg_cleanup
IDENTITY_FILE = AGENT_DIR / "system_identity.txt"
PERSONALITY_EXPRESSION_FILE = AGENT_DIR / "personality_expression.txt"
COGNITIVE_LENS_FILE = AGENT_DIR / "cognitive_lens.txt"
BEHAVIORAL_RHYTHM_FILE = AGENT_DIR / "behavioral_rhythm.txt"
UI_REFLECTION_FILE = AGENT_DIR / "ui_reflection.txt"
LENS_KNOWLEDGE_DIR = AGENT_DIR / "lens_knowledge"
OPERATIONAL_GUIDANCE_FILE = AGENT_DIR / "operational_guidance.txt"
def resolve_layla_data_dir() -> Path | None:
    """Per-user data root when `LAYLA_DATA_DIR` is set (Windows installer / launcher)."""
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def default_models_dir() -> Path:
    """Models directory: `%LAYLA_DATA_DIR%/models` when installed, else `repo/models`."""
    d = resolve_layla_data_dir()
    if d:
        p = d / "models"
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.debug("default_models_dir mkdir failed: %s", e)
        return p
    return REPO_ROOT / "models"


def _resolve_config_file() -> Path:
    d = resolve_layla_data_dir()
    if d:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.debug("resolve_config_file data dir mkdir failed: %s", e)
        return d / "runtime_config.json"
    return AGENT_DIR / "runtime_config.json"


CONFIG_FILE = _resolve_config_file()
BACKUP_DIR = AGENT_DIR / ".backup"


def workspace_under_layla_repository(workspace_root: str) -> bool:
    """True when ``workspace_root`` resolves to a directory inside the Layla source tree (``REPO_ROOT``)."""
    if not (workspace_root or "").strip():
        return False
    try:
        wp = Path(workspace_root).expanduser().resolve()
        rr = REPO_ROOT.resolve()
        return wp == rr or rr in wp.parents
    except Exception:
        return False


def effective_auto_lint_test_fix_ruff_fix(cfg: dict, workspace_root: str = "") -> bool:
    """Effective ``auto_lint_test_fix_ruff_fix``: explicit bool in config wins; else True only under this repo."""
    v = cfg.get("auto_lint_test_fix_ruff_fix", None)
    if isinstance(v, bool):
        return v
    return workspace_under_layla_repository(workspace_root)


SAFE_TOOLS = ["git_status", "read_file", "list_dir"]
DANGEROUS_TOOLS = [
    "write_file", "write_files_batch", "shell", "shell_session_start", "run_python", "apply_patch", "replace_in_file", "git_commit", "mcp_tools_call",
    "git_push", "git_revert", "git_clone", "git_worktree_add", "git_worktree_remove", "run_tests", "pip_install",
    "search_replace", "rename_symbol", "generate_gcode", "geometry_execute_program", "docker_run",
    "github_pr", "send_email", "send_webhook", "discord_send", "clipboard_write", "browser_click", "browser_fill",
    "code_format", "write_csv", "calendar_add_event", "create_svg", "create_mermaid",
    "notebook_edit_cell", "run_skill_pack",
]

PROTECTED_FILES = [
    AGENT_DIR / "main.py",
    AGENT_DIR / "agent_loop.py",
    AGENT_DIR / "runtime_safety.py",
]

_config_cache: dict | None = None
_config_mtime: float = 0.0
_config_last_check: float = 0.0
_CONFIG_CHECK_TTL: float = 2.0  # skip stat() for 2 s during hot loops
_config_lock = threading.Lock()
_applying_auto_tune: bool = False  # re-entrancy guard: auto-tune → get_recommended_settings → load_config
_file_cache_lock = threading.Lock()
_hw_lock = threading.Lock()
_hardware_probe_cache: dict | None = None


def _reset_config_cache_locked() -> None:
    """Clear the TTL config cache. Caller MUST already hold _config_lock."""
    global _config_cache, _config_mtime, _config_last_check
    _config_cache = None
    _config_mtime = 0.0
    _config_last_check = 0.0


def invalidate_config_cache() -> None:
    """Clear the TTL config cache under lock. Use after writing runtime_config.json."""
    with _config_lock:
        _reset_config_cache_locked()


_PLAINTEXT_SECRET_KEYS = (
    "remote_api_key", "discord_bot_token", "spotify_client_secret", "slack_bot_token",
    "slack_app_token", "telegram_bot_token", "firecrawl_api_key", "tailscale_auth_key",
    "elasticsearch_api_key", "meilisearch_api_key", "qdrant_api_key", "mem0_api_key",
)
_warned_plaintext_secrets = False


def _warn_plaintext_secrets(cfg: dict) -> None:
    """Warn ONCE if provider secrets are stored as plaintext in runtime_config.json (A1). The file
    is chmod 0600 now, but the OS keyring (used when saving via the UI) is stronger."""
    global _warned_plaintext_secrets
    if _warned_plaintext_secrets:
        return
    try:
        present = [k for k in _PLAINTEXT_SECRET_KEYS if str(cfg.get(k) or "").strip()]
        _lk = cfg.get("litellm_api_keys")
        if isinstance(_lk, dict) and any(str(v).strip() for v in _lk.values()):
            present.append("litellm_api_keys")
        if present:
            _warned_plaintext_secrets = True
            logger.warning(
                "Provider secret(s) stored in plaintext in runtime_config.json: %s. The file is "
                "restricted to owner-only (0600); for stronger protection save secrets via the UI "
                "(uses the OS keyring when available).", ", ".join(present),
            )
    except Exception:
        pass


# ── CONFIG INVARIANTS — enforced on the WRITE PATH, not per surface ─────────────
#
# WHY THIS IS HERE AND NOT IN A HANDLER.
# install/setup_profiles.apply_setup refused to persist `remote_enabled` with no credential
# and explained exactly why in a comment. POST /settings/themes and POST /settings did not,
# because the refusal was written as a line inside ONE surface instead of as a property of the
# configuration. Driven live against a temp instance:
#
#     POST /settings/themes {"key":"remote_access","enabled":true}
#       -> 200 {"ok":true,"enabled":true,"in_force":true}   (a clean green success)
#       -> runtime_config.json: remote_enabled true, no tunnel_token_hash, no remote_api_key
#       -> the VERY NEXT GET /settings on the same instance: 403 "no auth configured"
#
# The operator locked themselves out of their own localhost with a checkbox, and was told it
# worked. POST /settings {"remote_enabled": true} did the identical thing — so patching the
# themes handler would have fixed one of two surfaces and left the next one to be written
# unprotected. An invariant that any surface can bypass is not an invariant; it is a habit.
#
# So it lives where every surface funnels: the two functions that serialise a config dict to
# runtime_config.json. A future endpoint, CLI, migration or plugin that writes config gets the
# guarantee without knowing this rule exists — which is the only version of the rule that holds.


def remote_credential_present(cfg: dict) -> bool:
    """Can ANY caller actually authenticate against this config?

    This is deliberately the same test tunnel_auth.validate_token applies (`stored_hash` or
    `legacy_usable`), not the looser "is either key non-empty". A `remote_api_key` with
    `allow_legacy_remote_api_key` off is refused BY THE AUTHENTICATOR — so a config holding
    only that key has no working credential at all, and enabling remote on it produces the
    same total lockout as having no key. Asking the looser question here would have let
    exactly that state through while reporting it as safe.

    Secrets may live in the OS keyring rather than runtime_config.json, so each candidate is
    resolved through the secret store before being judged absent. Reading the raw dict alone
    would refuse a legitimately-credentialled operator whose token is in the keyring — a
    security check that blocks the safe configuration teaches people to disable it.
    """
    def _resolved(key: str) -> str:
        raw = cfg.get(key)
        try:
            from services.safety.secret_store import get_secret

            raw = get_secret(key, raw)
        except Exception as e:  # keyring absent/broken -> fall back to the plaintext value
            logger.debug("remote_credential_present: secret lookup for %s failed: %s", key, e)
        return str(raw or "").strip()

    if _resolved("tunnel_token_hash"):
        return True
    return bool(_resolved("remote_api_key") and cfg.get("allow_legacy_remote_api_key", False))


def _invariant_remote_needs_credential(cfg: dict) -> dict | None:
    """remote_enabled with no usable credential is a self-lockout, not a configuration.

    `remote_require_auth_always` defaults to auto, i.e. ON whenever remote_enabled (see
    services/safety/auth.require_auth_always). With no credential to check against, EVERY
    request — the operator's own localhost included — answers 403 "no auth configured". The
    machine's owner is locked out of the machine, and the only way back is hand-editing JSON.
    """
    if not cfg.get("remote_enabled"):
        return None
    if remote_credential_present(cfg):
        return None
    return {
        "key": "remote_enabled",
        "requested": True,
        "forced": False,
        "owner": "security_policy",
        "reason": (
            "remote access cannot be switched on without an auth credential: with none, "
            "every request — including your own localhost — answers 403 'no auth configured', "
            "which locks you out of this machine. Rotate a tunnel token (POST "
            "/remote/token/rotate) or set remote_api_key with allow_legacy_remote_api_key, "
            "then enable remote access."
        ),
    }


#: Ordered list of invariant probes. Each takes the config ABOUT TO BE PERSISTED and returns
#: None (nothing to do) or a refusal dict describing the key it is forcing and why. Add an
#: invariant here and every writer inherits it.
CONFIG_INVARIANTS: list = [_invariant_remote_needs_credential]


def enforce_config_invariants(cfg: dict) -> list[dict]:
    """Coerce *cfg* IN PLACE to a state that is safe to persist; return the refusals.

    Returns ``[{key, requested, forced, owner, reason}]`` — empty when nothing was refused.
    The return value is the whole point: a refusal the caller cannot see is a silent snap-back,
    which is the same lie as a false success. Every caller is expected to report it.
    """
    refusals: list[dict] = []
    for probe in CONFIG_INVARIANTS:
        try:
            hit = probe(cfg)
        except Exception as e:
            # A broken probe must FAIL LOUD rather than silently permit the state it exists to
            # prevent — but it must also not make the config unwritable. Log at warning and
            # carry on; the surrounding refusal reporting still says nothing was refused, which
            # is honest about what this function knows.
            logger.warning("config invariant %s failed: %s", getattr(probe, "__name__", probe), e)
            continue
        if hit:
            cfg[hit["key"]] = hit["forced"]
            refusals.append(hit)
            logger.warning("config invariant refused %s=%r: %s",
                           hit["key"], hit["requested"], hit["reason"])
    return refusals


def atomic_write_config(cfg: dict) -> list[dict]:
    """Atomically persist a full config dict and invalidate the cache.

    Writes to a sibling temp file then os.replace()s it into place, so a crash or
    power-loss mid-write can never leave a truncated/empty runtime_config.json
    (which would silently revert every setting — including security ones — to
    defaults). Serialised on _config_lock so concurrent writers don't interleave.

    Returns the invariant refusals (see `enforce_config_invariants`) so a caller can report
    them; the write itself always proceeds, with the offending key coerced to a safe value.
    """
    with _config_lock:
        refusals = enforce_config_invariants(cfg)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
        # fsync the temp file BEFORE the rename: os.replace makes the metadata rename atomic but does NOT
        # flush the data blocks, so a power-loss right after the rename could land a 0-length/truncated
        # config — silently reverting every setting (incl. security toggles) to defaults. (Same reason
        # memory_graph._save_graph fsyncs.) The docstring promised this crash-safety; now the code delivers.
        with open(tmp, "w", encoding="utf-8") as _f:
            _f.write(json.dumps(cfg, indent=2))
            _f.flush()
            os.fsync(_f.fileno())
        # A1: runtime_config.json can hold provider secrets/tokens in plaintext (on keyring-less
        # boxes). Restrict it to owner-only BEFORE it lands, so it isn't group/world-readable.
        try:
            os.chmod(tmp, 0o600)
        except Exception:
            pass  # best-effort (no-op on filesystems without POSIX perms, e.g. some Windows FS)
        os.replace(tmp, CONFIG_FILE)
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass
        _reset_config_cache_locked()
        _warn_plaintext_secrets(cfg)
    return refusals


def save_config_keys(updates: dict, *, editable_only: bool = True, clamp: bool = True) -> list[str]:
    """Race-safe read-modify-write of specific config keys. Returns the keys actually saved.

    Thin wrapper over `save_config_keys_detailed` for callers that only need the key list.
    """
    return save_config_keys_detailed(updates, editable_only=editable_only, clamp=clamp)["saved"]


def save_config_keys_detailed(updates: dict, *, editable_only: bool = True,
                              clamp: bool = True) -> dict:
    """Race-safe read-modify-write of specific config keys, reporting what was ADJUSTED.

    Reads the current runtime_config.json, applies (clamped) updates for the given
    keys, and atomically writes the result — the whole read+write happens under
    _config_lock, so two concurrent /settings writes can't lose each other's
    changes (the classic read-modify-write lost-update race).

    Returns {"saved": [key], "adjusted": [{key, requested, stored, reason}],
             "changed": [key], "refused": [{key, requested, forced, owner, reason}]}.

    `refused` is `enforce_config_invariants` applied to the MERGED result — the config as it
    would actually land, which is the only dict that can answer "is this state safe". Judging
    the update dict alone would miss `remote_enabled` arriving on a config that already has no
    credential (the exact shape POST /settings/themes sent), and judging the file alone would
    miss the credential arriving in the same request as the flag.

    `adjusted` is the point. This loop did `cfg[k] = coerce_and_clamp(k, v)` and then
    `saved.append(k)` without ever comparing the two, so the caller could not tell a value
    that was honoured from one that was silently rewritten — 28 of the 91 editable keys carry
    a min/max. `changed` is the keys whose stored value actually moved, which lets the caller
    warn about auto-tune only for settings the user really touched.
    """
    from config_schema import coerce_and_clamp, describe_adjustment, get_editable_keys

    editable = get_editable_keys() if editable_only else None
    with _config_lock:
        cfg: dict = {}
        if CONFIG_FILE.exists():
            try:
                loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cfg = loaded
            except Exception as e:
                logger.debug("save_config_keys read failed: %s", e)
        saved: list[str] = []
        adjusted: list[dict] = []
        changed: list[str] = []
        for k, v in updates.items():
            if editable is not None and k not in editable:
                continue
            _missing = object()
            before = cfg.get(k, _missing)
            stored = coerce_and_clamp(k, v) if clamp else v
            cfg[k] = stored
            saved.append(k)
            if before is _missing or before != stored:
                changed.append(k)
            if clamp:
                reason = describe_adjustment(k, v, stored)
                if reason:
                    adjusted.append({"key": k, "requested": v, "stored": stored,
                                     "reason": reason})
        # THE INVARIANT, on the merged config, before it is serialised. `saved` deliberately
        # still lists the refused key: it WAS processed by this write, and the caller's
        # read-back is what reports the value that actually landed. Dropping it from `saved`
        # would hide the key from the read-back entirely and turn a loud refusal back into a
        # silent no-op.
        refused = enforce_config_invariants(cfg)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
        # fsync before rename (see atomic_write_config) so a power-loss can't truncate the config to 0-length.
        with open(tmp, "w", encoding="utf-8") as _f:
            _f.write(json.dumps(cfg, indent=2))
            _f.flush()
            os.fsync(_f.fileno())
        os.replace(tmp, CONFIG_FILE)
        _reset_config_cache_locked()
    return {"saved": saved, "adjusted": adjusted, "changed": changed, "refused": refused}


def _probe_hardware() -> dict:
    """Probe CPU, RAM, GPU/VRAM once per process. Returns ram_gb, vram_gb, cpu_logical."""
    global _hardware_probe_cache
    if _hardware_probe_cache is not None:
        return _hardware_probe_cache
    with _hw_lock:
        if _hardware_probe_cache is not None:
            return _hardware_probe_cache
        result: dict
        try:
            from services.infrastructure.hardware_detect import detect_hardware
            h = detect_hardware()
            result = {
                "ram_gb": h["ram_gb"],
                "vram_gb": h["vram_gb"],
                "cpu_logical": h["cpu_cores"],
            }
        except Exception as e:
            logger.debug("runtime_safety hardware_detect failed: %s", e)
            cpu_count = os.cpu_count() or 4
            ram_gb = 16.0
            vram_gb = 0.0
            try:
                import psutil
                mem = psutil.virtual_memory()
                ram_gb = round(mem.total / (1024**3), 1)
            except Exception as pe:
                logger.debug("runtime_safety psutil fallback failed: %s", pe)
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = r.stdout.strip().split("\n")[0].strip().replace("MiB", "").replace("MB", "").strip()
                    try:
                        vram_mb = int(raw)
                        vram_gb = round(vram_mb / 1024.0, 1)
                    except ValueError:
                        pass
            except Exception as ne:
                logger.debug("runtime_safety nvidia-smi failed: %s", ne)
            result = {"ram_gb": ram_gb, "vram_gb": vram_gb, "cpu_logical": cpu_count}
        _hardware_probe_cache = result
        return _hardware_probe_cache


def _hardware_derived_defaults() -> dict:
    """Return LLM-related defaults derived from probed hardware. Override in runtime_config.json."""
    h = _probe_hardware()
    ram_gb = h["ram_gb"]
    vram_gb = h["vram_gb"]

    if vram_gb >= 16 and ram_gb >= 24:
        return {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024, "use_mlock": True, "completion_max_tokens": 512}
    if vram_gb >= 12 and ram_gb >= 16:
        return {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 512, "use_mlock": ram_gb >= 24, "completion_max_tokens": 512}
    if vram_gb >= 8 and ram_gb >= 12:
        return {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 512, "use_mlock": False, "completion_max_tokens": 384}
    if vram_gb >= 6:
        return {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 256, "use_mlock": False, "completion_max_tokens": 256}
    if vram_gb >= 4:
        return {"n_ctx": 4096, "n_gpu_layers": 20, "n_batch": 256, "use_mlock": False, "completion_max_tokens": 256}
    if vram_gb >= 2:
        return {"n_ctx": 2048, "n_gpu_layers": 10, "n_batch": 128, "use_mlock": False, "completion_max_tokens": 256}
    # CPU-only or no GPU
    if ram_gb >= 8:
        # A capable CPU box (8GB+): a larger context + batch materially help coding and CPU
        # prefill, and there's ample RAM headroom (KV at 4096 for a 3-7B Q4 is well under 1GB).
        # n_batch=128 badly under-utilizes CPU SIMD on big prompts — 512 is the CPU sweet spot.
        return {"n_ctx": 4096, "n_gpu_layers": 0, "n_batch": 512, "use_mlock": ram_gb >= 16, "completion_max_tokens": 256}
    return {"n_ctx": 2048, "n_gpu_layers": 0, "n_batch": 128, "use_mlock": False, "completion_max_tokens": 256}


def load_config() -> dict:
    """Load runtime config. Cached: skips disk stat for _CONFIG_CHECK_TTL seconds during hot loops."""
    global _config_cache, _config_mtime, _config_last_check, _applying_auto_tune
    now = time.monotonic()
    # Fast path: TTL not expired and cache warm — zero I/O, no lock needed (read-only reference)
    if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_TTL:
        return _config_cache
    # Re-entrancy guard: the auto-tune overlay (below) calls hardware_detect.get_recommended_settings()
    # which calls load_config() again on THIS thread. _config_lock is a plain Lock, so re-locking
    # would deadlock — return the last-known config (or {}) without taking the lock. The inner
    # caller only needs a few keys (e.g. model_path) and tolerates a stale/empty read.
    if _applying_auto_tune:
        return _config_cache if _config_cache is not None else {}
    with _config_lock:
        # Re-check inside lock to avoid redundant reloads from concurrent threads
        now = time.monotonic()
        if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_TTL:
            return _config_cache
        _config_last_check = now
        try:
            current_mtime = CONFIG_FILE.stat().st_mtime
        except Exception as e:
            logger.debug("runtime_safety config stat failed: %s", e)
            current_mtime = 0.0
        if _config_cache is not None and current_mtime == _config_mtime:
            return _config_cache
        # Static defaults (safe fallbacks)
        defaults = {
            "max_cpu_percent": 95,
            "max_ram_percent": 95,
            "warn_cpu_percent": 70,
            "hard_cpu_percent": 85,
            "max_active_runs": 1,
            "response_pacing_ms": 0,
            "repo_cognition_inject_enabled": True,
            "repo_cognition_max_chars": 6000,
            "workspace_awareness_auto_enabled": True,
            "workspace_awareness_debounce_seconds": 5.0,
            "project_memory_enabled": True,
            "project_memory_max_bytes": 1_500_000,
            "project_memory_inject_max_chars": 4000,
            "project_memory_max_file_entries": 500,
            "project_memory_max_list_entries": 200,
            "project_memory_persist_plan": True,
            "planning_strict_mode": False,
            "planning_enabled": True,
            "plan_system_first_enabled": False,
            "plan_llm_gap_fill_only": False,
            "decision_policy_enabled": True,
            "tool_replay_policy_enabled": False,
            "pkg_policy_strict_enabled": False,
            "chat_lite_mode": False,
            "task_budget_enabled": True,
            "force_full_pipeline": False,
            "run_budget_summary_log_enabled": True,
            "api_confidence_enabled": True,
            "langfuse_enabled": False,
            "langfuse_public_key": None,
            "langfuse_secret_key": None,
            "langfuse_host": "https://cloud.langfuse.com",
            "operator_protection_policy_pin_enabled": True,
            "ui_decision_trace_enabled": False,
            "aspect_tool_ordering_enabled": True,
            "initiative_ledger_enabled": True,
            "initiative_escalation_after_ignores": 4,
            "in_loop_plan_governance_enabled": True,
            "in_loop_plan_default_max_retries": 1,
            "plan_governance_require_nonempty_step_tools": False,
            "plan_governance_reject_auto_filled_tools": False,
            "plan_governance_strict_tool_evidence": False,
            "plan_governance_hard_mode": False,
            "llm_serialize_per_workspace": False,
            "plan_step_default_read_tools": ["read_file", "list_dir", "grep_code"],
            "file_plan_refinement_enabled": False,
            "ui_agent_stream_timeout_seconds": 900,
            "ui_agent_json_timeout_seconds": 900,  # must be >= max_runtime_seconds (was 720 < 900)
            "ui_stream_keepalive_seconds": 20,
            "ui_stalled_silence_ms": 0,
            "honesty_and_boundaries_enabled": True,
            "lite_mode_auto": True,  # PR #1: auto-detect low hardware → performance_mode low
            "dual_model_threshold_gb": 24,
            "force_dual_models": False,
            "route_default_to_chat_model": False,
            "auto_pip_install_optional": False,
            "performance_mode": "auto",
            "anti_drift_prompt_enabled": True,
            "chat_model_path": "",
            "agent_model_path": "",
            "max_runtime_seconds": 900,
            "chat_light_max_runtime_seconds": 90,
            "max_plan_depth": 3,
            "max_tool_calls": 20,
            "tool_call_timeout_seconds": 180,  # was 60 — real pytest/build/install steps exceed 60s and got killed
            "approval_ttl_seconds": 3600,
            "hyde_enabled": False,
            # BL-100 inline RAG grounding (cite-or-abstain). Off by default (non-invasive);
            # "flag" annotates a grounding block, "abstain" recommends hedging when a
            # substantive claim isn't supported by retrieved context. min_support is the
            # lexical-support threshold (0-1) for the default model-free scorer.
            "grounding_enabled": False,
            "grounding_mode": "flag",
            "grounding_min_support": 0.35,
            # BL-103 reranker backend: auto (flashrank→cross-encoder→bm25) | flashrank | cross_encoder | bm25.
            "reranker_backend": "auto",
            # BL-102 hybrid escalation: re-ask a bigger model when the small model's answer looks
            # low-confidence. Off + no target by default → no-op on a single-model box.
            "hybrid_escalation_enabled": False,
            "escalation_confidence_threshold": 0.5,
            "escalation_model": "",
            # BL-107 release-gate/eval determinism: force greedy decoding (temp 0, top_k 1) so
            # the same prompt reproduces the same output. Off by default (normal chat stays sampled).
            "deterministic_decoding_enabled": False,
            "ollama_base_url": "",
            "inference_backend": "llama_cpp",
            "context_auto_compact_ratio": 0.75,
            "context_aggressive_compress_enabled": True,
            "context_sliding_keep_messages": 0,
            "tool_step_context_max_tokens": 500,
            "system_head_budget_ratio": 0.35,
            "tiered_prompt_budget_enabled": True,
            "llm_timeout_seconds": 180,  # must be >= llm_local_timeout_seconds (180); was 120 < 180 → false mid-gen timeouts
            "agent_timeout_seconds": 300,
            "tool_timeout_seconds": 30,
            "tool_routing_enabled": True,
            # Quality enforcement: match runtime_config.example.json; explicit false in runtime_config.json still overrides.
            "deterministic_tool_routes_enabled": True,
            # Default MUST be False (matches config_schema.py:176). When True, the completion gate
            # appends retry-injection text ("[System: Your last response…]") to the goal, which a
            # weak model can echo VERBATIM into the reply — a reply-bleedover source. The loader
            # default had drifted to True (fresh installs shipped the leak risk); realigned to False.
            "completion_gate_enabled": False,
            "tools_profile": "full",
            "tools_allow": [],
            "tools_deny": [],
            "tool_groups": {},
            "tools_by_provider": {},
            "tool_loop_detection_enabled": True,
            "tool_loop_history_size": 30,
            "tool_loop_warning_threshold": 10,
            "tool_loop_stop_threshold": 20,
            "tool_loop_detect_repeat": True,
            "tool_loop_detect_pingpong": True,
            "http_cache_ttl_seconds": 0,
            "http_cache_max_entries": 200,
            "inference_fallback_urls": [],
            "image_model": None,
            "image_generation_model": None,
            "markdown_skills_dir": None,
            "markdown_skills_watch": False,
            "browser_default_profile": "default",
            "browser_profiles": {},
            "browser_persistent_profiles": False,
            "use_instructor_for_decisions": True,
            "structured_generation_enabled": True,
            "gbnf_decoding_enabled": True,
            "self_consistency_samples": 1,
            "worker_pool_enabled": True,
            "max_workers": 0,
            "admin_mode": False,
            "admin_auto_checkpoint": True,
            "admin_blocklist_override": False,
            "tool_approval_bypass": False,
            "remote_cors_origins": [],
            "cloudflared_path": "",
            # Autonomous Research v2 (Tier 0 only; proposal-only; local-first)
            "autonomous_mode": False,
            "autonomous_max_steps": 50,
            "autonomous_timeout_seconds": 60,
            "autonomous_max_subagents": 3,
            "autonomous_research_mode": False,
            "autonomous_allow_network": False,
            "autonomous_tool_allowlist": [
                "read_file",
                "list_dir",
                "grep_code",
                "glob_files",
                "file_info",
                "python_ast",
                "workspace_map",
                "search_codebase",
            ],
            "autonomous_wiki_enabled": True,
            "autonomous_wiki_export_enabled": False,
            "autonomous_prefetch_enabled": True,
            "autonomous_reuse_match_threshold": 0.22,
            "autonomous_wiki_match_threshold": 0.18,
            "autonomous_chroma_enabled": True,
            "autonomous_chroma_match_threshold": 0.75,
            "autonomous_chroma_top_k": 3,
            # Fabrication Assist (separate deterministic kernel; opt-in subprocess runner)
            # Default: StubRunner only. Subprocess runner must be explicitly enabled by operator config.
            "fabrication_assist": {"enable_subprocess": False},
            "retrieval_cache_ttl_seconds": 60,
            "completion_cache_enabled": True,
            "completion_cache_ttl_seconds": 45,
            "completion_cache_max_entries": 500,
            "response_cache_enabled": True,
            "response_cache_ttl_seconds": 300,
            "response_cache_max_entries": 300,
            "telemetry_enabled": True,
            "sandbox_runner_timeout_seconds": 120.0,
            "sandbox_python_timeout_seconds": 45.0,
            "shell_restrict_to_allowlist": False,
            "shell_allowlist_extra": [],
            "tool_args_validation_enabled": True,
            "coding_model_large_context": None,
            "coding_large_context_threshold": 12000,
            "retrieval_hybrid_vector_weight": 1.0,
            "retrieval_hybrid_bm25_weight": 1.0,
            "retrieval_hybrid_coding_bm25_boost": 1.25,
            "use_bge_reranker": False,
            "bge_reranker_model": "",
            "knowledge_ingestion_enabled": True,
            "multi_agent_orchestration_enabled": False,
            "learning_quality_gate_enabled": True,
            "learning_quality_min_score": 0.35,
            "learning_min_score": 0.3,
            "auto_lint_test_fix": True,
            "auto_lint_test_fix_ruff_fix": False,
            "auto_lint_test_fix_run_tests": True,
            "output_quality_gate_enabled": True,
            "enable_self_reflection": True,
            "self_reflection_min_length": 200,
            "git_auto_commit": False,
            "github_repo": "",
            "auto_update_check_enabled": False,
            "research_max_tool_calls": 20,
            "research_max_runtime_seconds": 1800,
            "safe_mode": True,
            "mcp_client_enabled": False,
            "mcp_stdio_servers": [],
            "mcp_inject_tool_summary_in_decisions": False,
            "mcp_tool_summary_ttl_seconds": 300,
            "agent_hooks_enabled": True,
            "hooks_require_allow_run": True,
            "agent_hooks": [],
            "background_use_subprocess_workers": False,
            "background_subprocess_local_gguf_policy": "warn",
            "background_worker_grace_seconds": 4.0,
            "background_job_max_stdout_bytes": 8000000,
            "background_worker_force_sandbox_only": False,
            "background_worker_rlimits_enabled": False,
            "background_worker_rlimit_as_bytes": 0,
            "background_worker_windows_job_limits_enabled": False,
            "background_worker_windows_job_memory_mb": 0,
            "background_worker_windows_job_cpu_percent": 0,
            "background_worker_rlimit_cpu_seconds": 0,
            "background_worker_wrapper_command": [],
            "background_progress_stream_enabled": True,
            "background_progress_min_interval_seconds": 0.35,
            "background_progress_max_events": 200,
            "background_progress_tail_max": 50,
            "background_job_max_stderr_bytes": 2_000_000,
            "background_worker_cgroup_auto_enabled": False,
            "background_worker_cgroup_memory_max_bytes": 0,
            "background_worker_cgroup_cpu_max": "",
            "temperature": 0.2,
            "n_ctx": 4096,
            "n_gpu_layers": -1,  # full GPU offload by default; overridden by hardware probe
            "n_batch": 512,
            # Max GGUF models kept resident at once (task/dual-model routing).
            # Bounds memory so routing can't OOM the single process; raise it only
            # if you have the RAM/VRAM for multiple concurrently-loaded models.
            "max_resident_models": 2,
            "n_threads": None,
            "n_threads_batch": None,
            "use_mlock": False,
            "use_mmap": True,
            "top_p": 0.95,
            "repeat_penalty": 1.1,
            "top_k": 40,
            "model_filename": "your-model.gguf",
            "available_models": [],
            "models_dir": str(default_models_dir()),
            "sandbox_root": str(Path.home() / "layla-workspace"),
            "web_allowlist": [],
            "knowledge_sources": [],
            "knowledge_max_bytes": 4000,
            "knowledge_chunks_k": 5,
            "learnings_n": 30,
            "semantic_k": 5,
            "memory_retrieval_min_adjusted_confidence": 0.0,
            "coordinator_enabled": True,
            "coordinator_graph_execution_enabled": True,
            "coordinator_plan_threshold": 0.45,
            "coordinator_task_budget_hint_enabled": True,
            "coordinator_dispatch_max_attempts": 1,
            "coordinator_dispatch_retry_on_statuses": ["system_busy", "error"],
            "coordinator_strategy_feedback_enabled": False,
            "strategy_preference_min_samples": 5,
            "pipeline_enforcement_enabled": True,
            "tool_first_enforcement_enabled": False,
            "parallel_execution_enabled": False,
            "worktree_isolation_enabled": False,
            "opentelemetry_enabled": False,
            "background_reflection_interval_minutes": 5,
            "background_codex_update_interval_minutes": 10,
            "background_memory_consolidation_interval_minutes": 30,
            "prompt_static_cache_enabled": True,
            "task_persistence_enabled": True,
            "execution_trace_log_enabled": True,
            "knowledge_retrieval_domain_boost": 1.15,
            "memory_cleanup_confidence_threshold": 0.08,
            "inline_initiative_enabled": False,
            "initiative_engine_enabled": False,
            "initiative_project_proposals_enabled": False,
            # BL-190 mood: was read at system_head_builder.py:896 but set nowhere, so it defaulted
            # off and never injected. On + nudged from the turn loop = a mood that actually carries.
            "emotional_presence_enabled": True,
            # BL-238: learn a reusable skill from a finished multi-step run (≥3 tool steps).
            "skill_acquisition_enabled": True,
            # BL-241: inject the world-model summary (project/blockers/index/machine) so responses
            # are situationally aware, instead of world_state being an inert GET /world nobody reads.
            "world_state_inject_enabled": True,
            # Async LLM polish of the conversation rail title on the first exchange (ChatGPT-style),
            # over the instant extractive title. Off → keep the extractive title only.
            "conversation_title_synthesis_enabled": True,
            # Deterministic capture of durable facts the operator explicitly states ("call me X",
            # "my timezone is Y") into user_identity, with a "memory updated" receipt.
            "identity_capture_enabled": True,
            "autonomy_optimizer_enabled": False,
            "autonomy_trust_tiers_enabled": True,  # gates capabilities behind XP thresholds (more cautious)
            "trust_tier_override": None,
            "voice_adjustment_inject_enabled": False,
            "planning_outcome_bias_enabled": True,
            "relationship_codex_inject_enabled": False,
            "relationship_codex_inject_max_chars": 1000,
            "project_discovery_auto_inject": False,
            "aspect_memories_n": 10,
            "convo_turns": 0,
            "stop_sequences": ["\nUser:", " User:"],
            "completion_max_tokens": 256,
            "remote_model_name": "llama3.1",
            "llama_server_url": None,
            "coding_model": None,
            "reasoning_model": None,
            "chat_model": None,
            "model_override_enabled": True,
            "reasoning_budget": -1,
            "scheduler_study_enabled": True,
            "scheduler_interval_minutes": 30,
            "scheduler_recent_activity_minutes": 90,
            "wakeup_include_initiative": False,
            "wakeup_include_discovery_line": False,
            # ── Remote access ─────────────────────────────────────────────
            "remote_enabled": False,
            "remote_api_key": None,  # DEPRECATED: use tunnel_token_hash instead (Phase 3)
            "remote_allow_endpoints": [],
            "remote_mode": "observe",
            "remote_rate_limit_per_minute": 100,
            # Tri-state: None=auto (require auth even for loopback whenever
            # remote_enabled — the safe default when exposed), True=always,
            # False=never (explicit opt-out, loopback stays exempt even exposed).
            # Resolved by services.auth.require_auth_always().
            "remote_require_auth_always": None,
            # Trusted reverse-proxy / tunnel IPs or CIDRs. Used for rightmost-
            # trusted-hop client-IP derivation from X-Forwarded-For (anti-spoof).
            # Empty => the rightmost XFF entry (appended by the loopback relay) is
            # used; a client cannot poison the allowlist by prepending a fake hop.
            "tunnel_trusted_proxies": [],
            "trace_id_enabled": False,
            "use_chroma": True,
            "uncensored": True,
            "nsfw_allowed": True,
            # dignity_engine: Layla's autonomy to push back on rude/abusive input
            "dignity_engine_enabled": True,
            "dignity_sensitivity": 0.5,
            "dignity_enforcement": "soft",
            # content_guard: deterministic pre-model filter for universally harmful content
            "content_guard_enabled": True,
            "content_guard_age_verified": False,
            "content_guard_hardcoded_only": False,
            # privacy: entity and memory privacy separation
            "privacy_default_level": "public",
            "privacy_max_retrieval_level": "personal",
            # expertise_domain_boost: aspect-aware retrieval boosting
            "expertise_domain_boost_enabled": True,
            # ── LiteLLM: multi-provider LLM gateway (Phase 1) ───────────
            "litellm_enabled": False,
            "litellm_default_model": None,
            "litellm_fallback_chain": [],
            "litellm_api_keys": {},
            "litellm_timeout_seconds": 120,  # separate from llm_timeout_seconds (local inference)
            "litellm_max_retries": 2,
            # ── Discord bot (Phase 2) ────────────────────────────────────
            "discord_bot_autostart": False,
            "discord_bot_token": None,
            "discord_bot_default_aspect": None,
            "enable_personality_expression": True,
            "enable_cognitive_lens": True,
            "enable_behavioral_rhythm": True,
            "enable_ui_reflection": True,
            "enable_lens_knowledge": True,
            "enable_lens_refresh": True,
            "lens_refresh_interval_days": 7,
            "enable_operational_guidance": True,
            "enable_cognitive_workspace": True,
            # OFF by default: the multi-aspect debate prompt seeds six "[⚔ MORRIGAN] …" lines
            # that a small model renders as ~6 stitched answers. Normal chat is single-voice.
            "deliberation_enabled": False,
            "deliberation_min_length": 100,
            "engineering_pipeline_enabled": False,
            "engineering_pipeline_default_mode": "chat",
            "engineering_pipeline_max_clarify_rounds": 3,
            "engineering_pipeline_validator_max_retries": 1,
            "spotify_client_id": None,
            "spotify_client_secret": None,
            "slack_bot_token": None,
            "slack_app_token": None,
            "telegram_bot_token": None,
            "transport_allowlist": "",
            "transport_require_allowlist": False,
            "openclaw_gateway_url": None,
            "sandbox_python_memory_limit_mb": 0,
            "max_chars_per_source": 500,
            "retrieval_line_overlap_threshold": 0.7,
            "write_file_max_bytes": 5_000_000,  # 5MB for new files; existing files use explosion_factor
            "write_file_explosion_factor": 5,
            "max_patch_lines": 0,
            "doc_injection_guard_enabled": True,
            "telemetry_log_trivial": False,
            "embedder_prewarm_enabled": False,
            "voice_stt_prewarm_enabled": False,
            "voice_tts_prewarm_enabled": False,
            "geometry_frameworks_enabled": {"ezdxf": True, "cadquery": True, "openscad": True, "trimesh": True},
            "openscad_executable": "openscad",
            "geometry_subprocess_timeout_seconds": 120.0,
            "geometry_external_bridge_url": "",
            "geometry_external_bridge_allow_insecure_localhost": False,
            "direct_feedback_enabled": False,
            "pin_psychology_framework_excerpt": True,
            "file_checkpoint_enabled": True,
            "file_checkpoint_max_count": 200,
            "file_checkpoint_max_bytes": 209_715_200,
            # ── Search backends (Phase 5) ─────────────────────────────────
            "search_backend": "auto",  # "auto" | "meilisearch" | "elasticsearch" | "sqlite_fts"
            "elasticsearch_enabled": False,
            "elasticsearch_url": None,
            "elasticsearch_index_prefix": "layla",
            "elasticsearch_api_key": None,
            "meilisearch_enabled": False,
            "meilisearch_url": "http://localhost:7700",
            "meilisearch_api_key": None,
            "meilisearch_index": "layla-learnings",
            # ── Tunnel auth & audit (Phase 3) ────────────────────────────
            "tunnel_token_hash": None,
            "tunnel_token_created_at": None,
            "tunnel_token_ttl_hours": 0,  # 0 = never expires
            "tunnel_ip_allowlist": [],
            "tunnel_audit_enabled": False,  # activates when remote_enabled is True
            "tunnel_audit_retention_days": 90,
            "tailscale_enabled": False,
            "tailscale_auth_key": None,
            # ── Web crawling (Phase 6A) ──────────────────────────────────
            "crawler_backend": "auto",  # "auto" | "firecrawl" | "crawl4ai" | "basic"
            "firecrawl_api_key": None,
            "firecrawl_api_url": "https://api.firecrawl.dev",
            "crawl4ai_enabled": False,  # opt-in like all other integrations
            # ── Document ingestion (Phase 6B) ────────────────────────────
            "docling_enabled": False,
            "docling_chunk_size": 1000,
            "docling_overlap": 200,
            # ── Vector store (Phase 6C) ──────────────────────────────────
            "vector_backend": "chroma",  # "chroma" | "qdrant"
            "qdrant_url": "http://localhost:6333",
            "qdrant_api_key": None,
            "qdrant_collection": "layla-memories",
            # ── Memory extraction (Phase 6D) ─────────────────────────────
            "mem0_enabled": False,
            "mem0_api_key": None,
            "mem0_provider": "local",  # "local" | "cloud"
            "aspect_model_overrides": {},
            # Debate engine: "solo" (default), "auto", "debate", "council", "tribunal"
            "deliberation_mode": "auto",  # auto-detects when debate/council is useful
            "debate_max_tokens": 800,
            "debate_temperature": 0.7,
            "debate_synthesis_max_tokens": 1200,
            "deliberation_auto_threshold": 0.7,
            # Heterogeneous council: map aspect_id -> model tag ("coding"/
            # "reasoning"/"chat") or a GGUF filename. Empty => all aspects use the
            # default model. e.g. {"morrigan": "coding", "nyx": "reasoning"}.
            "council_aspect_models": {},
            # Phase 5: Advanced Token Management
            "dynamic_budget_enabled": True,
            "budget_pressure_threshold": 0.85,
            "auto_chunk_long_tasks": True,
            "chunk_step_threshold": 50,
            "chunk_handoff_max_tokens": 600,
            "context_attribution_enabled": True,
            "attribution_min_score": 0.15,
            # Phase 6: Autonomy Engine
            "long_horizon_enabled": True,
            "max_horizon_days": 14,
            "hours_per_day_chunk": 4.0,
            "checkpoint_auto_save": True,
            "idle_detection_enabled": True,
            "idle_cpu_threshold": 0.30,
            "idle_timeout_minutes": 10,
            # Resource Governor (WHISPER / BREATHE / SPRINT)
            "resource_governor_enabled": True,
            "whisper_cpu_cap": 0.05,
            "breathe_cpu_cap": 0.25,
            "sprint_cpu_cap": 0.80,
            "whisper_timeout_seconds": 60,
            "sprint_timeout_seconds": 600,
            "governor_tick_seconds": 15,
            "system_tray_enabled": True,
            # Phase 9: Multi-Device / Networking
            "cluster_enabled": False,
            "node_role": "queen",
            "cluster_heartbeat_interval": 30,
            "cluster_task_timeout": 300,
            "cluster_sync_interval": 300,
            "cluster_offload_enabled": False,
            "hardware_tier": "cpu",
            "hardware_aware_startup": True,
            # Phase 10: Character Creator + Tutorial
            "character_creator_enabled": True,
            "tutorial_enabled": True,
            "tutorial_auto_start": True,
            # Optional features (all enabled by default per design)
            "maturity_enabled": True,
            "skills_enabled": True,
            "german_mode_enabled": False,  # language-specific; off by default
            "golden_examples_enabled": True,
            "speculative_decoding_enabled": False,
        }
        hw_defaults = _hardware_derived_defaults()
        defaults.update(hw_defaults)
        # Auto-enable lite mode based on hardware when lite_mode_auto is true
        # (only if performance_mode is still "auto" — user override wins)
        if defaults.get("lite_mode_auto", True) and defaults.get("performance_mode", "auto") == "auto":
            h = _probe_hardware()
            if h["ram_gb"] < 8 or h["vram_gb"] < 4:
                defaults["performance_mode"] = "low"
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
                # Validate/clamp editable numeric+boolean keys so a hand-edited
                # runtime_config.json (temperature=50, n_gpu_layers=-999, n_ctx="abc")
                # can never reach llama.cpp as an out-of-range/garbage value.
                try:
                    from config_schema import _SCHEMA_BY_KEY, coerce_and_clamp
                    for _k in _SCHEMA_BY_KEY:
                        if _k in data:
                            defaults[_k] = coerce_and_clamp(_k, defaults[_k])
                except Exception as _ce:
                    logger.debug("config clamp skipped: %s", _ce)
        except Exception as e:
            logger.debug("runtime_safety config load failed: %s", e)
        # Startup gate (main.py): Chroma wheels unusable on this interpreter — disable semantic layer only.
        if (os.environ.get("LAYLA_CHROMA_DISABLED") or "").strip().lower() in ("1", "true", "yes"):
            defaults["use_chroma"] = False
        try:
            # expanduser(): sandbox_root is stored as "~/layla-workspace". Without this the
            # mkdir takes "~" literally and creates a junk `agent/~/layla-workspace/` tree in
            # the source checkout instead of the operator's real workspace.
            Path(defaults["sandbox_root"]).expanduser().mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug("sandbox_root mkdir failed: %s", e)
        # Phase 1B: Apply maturity rank gates — overlay config based on earned rank
        try:
            _apply_maturity_gates(defaults)
        except Exception as _mg_err:
            logger.debug("maturity gates overlay failed: %s", _mg_err)

        # REQ-12: overlay secret-typed keys from the OS keyring / env (no-op when
        # no keyring backend exists, so the plaintext path is unchanged). Done
        # once per cache build, not on the hot fast-path return.
        try:
            from services.safety.secret_store import resolve_config_secrets
            defaults = resolve_config_secrets(defaults)
        except Exception as e:
            logger.debug("secret resolution skipped: %s", e)
        # Hardware-adaptive optimization suite: overlay the auto-tune profile (inference +
        # pipeline weight for the detected hardware tier) AUTHORITATIVELY, so the machine is
        # always configured for its capability without hand-tuning. Off via auto_tune_enabled
        # =false; per-key opt-out via auto_tune_locked_keys. Guarded above against the re-entry
        # from get_recommended_settings() (which calls load_config()).
        try:
            _applying_auto_tune = True
            from services.infrastructure.auto_tune import apply_auto_tune
            defaults = apply_auto_tune(defaults)
        except Exception as _at_err:
            logger.debug("auto-tune overlay skipped: %s", _at_err)
        finally:
            _applying_auto_tune = False
        _config_cache = defaults
        _config_mtime = current_mtime
        return _config_cache


# Config keys this module OWNS on behalf of the XP/maturity system: key -> the minimum
# maturity rank at which the key is allowed to be true. Below that rank the key is forced
# False at config-load, whatever the file says.
#
# DECLARATIVE ON PURPOSE. This used to be a run of `if rank < N: cfg[...] = False` blocks,
# which meant the ownership was knowable only by running load_config() and diffing. Anything
# that wants to EXPLAIN why a feature is off (see install/feature_status.py) needs to ask
# "who owns this key, and what do they require?" without re-implementing the gate — an
# explanation derived from a copy of the rule is the next thing to drift out of sync with it.
# _apply_maturity_gates below is the only consumer that enforces; everyone else reads.
MATURITY_GATED_KEYS: dict[str, int] = {
    # Rank < 1: no proactive behaviour
    "inline_initiative_enabled": 1,
    "initiative_engine_enabled": 1,
    # Rank < 3: no autonomous research mode
    "autonomous_research_mode": 3,
    # Rank < 5: no multi-step planning autonomy
    # (planning_enabled stays True for user-driven plans at all ranks)
    "autonomous_mode": 5,
    # Rank < 10: no full initiative/autonomy
    "initiative_project_proposals_enabled": 10,
    "autonomy_optimizer_enabled": 10,
}


def current_maturity_rank() -> int | None:
    """The live maturity rank, or None when the maturity engine is unavailable.

    None is meaningfully different from 0: it means the gate is NOT being applied (see
    _apply_maturity_gates' early return), so a caller must not report "requires rank N".
    """
    try:
        from services.personality.maturity_engine import get_state

        return int(get_state().rank)
    except Exception:
        return None


def _apply_maturity_gates(cfg: dict) -> None:
    """Overlay config keys based on maturity rank thresholds.

    This ensures that powerful capabilities are locked until the user has
    interacted enough for Layla to earn them through the XP system.
    """
    rank = current_maturity_rank()
    if rank is None:
        return  # If maturity engine isn't available, don't gate anything

    for key, min_rank in MATURITY_GATED_KEYS.items():
        if rank < min_rank:
            cfg[key] = False


def model_search_roots(cfg: dict | None = None) -> list[Path]:
    """
    Ordered directories to scan for .gguf files (first match wins for duplicates).
    1) configured models_dir (if set and exists)
    2) default_models_dir() (per-user data or repo when LAYLA_DATA_DIR unset)
    3) repo_root/models (always discoverable for dev clones when models live beside the repo)
    """
    if cfg is None:
        cfg = load_config()
    seen: set[str] = set()
    roots: list[Path] = []
    raw = (cfg.get("models_dir") or "").strip()
    if raw:
        try:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                key = str(p)
                if key not in seen:
                    seen.add(key)
                    roots.append(p)
        except OSError:
            pass
    try:
        d = default_models_dir().resolve()
        if d.is_dir():
            key = str(d)
            if key not in seen:
                seen.add(key)
                roots.append(d)
    except OSError:
        pass
    try:
        repo_m = (REPO_ROOT / "models").resolve()
        if repo_m.is_dir():
            key = str(repo_m)
            if key not in seen:
                seen.add(key)
                roots.append(repo_m)
    except OSError:
        pass
    return roots


def resolve_model_path(cfg: dict | None = None) -> Path:
    """
    Resolve full path to model file. Uses models_dir from config if set, else default_models_dir.
    If missing at the primary location, searches model_search_roots for the same basename.
    """
    if cfg is None:
        cfg = load_config()
    model_filename = (cfg.get("model_filename") or "").strip()
    if not model_filename or model_filename == "your-model.gguf":
        return default_models_dir() / "your-model.gguf"  # placeholder
    models_dir_raw = cfg.get("models_dir")
    if models_dir_raw:
        models_dir = Path(models_dir_raw).expanduser().resolve()
    else:
        models_dir = default_models_dir()
    primary = models_dir / model_filename
    if primary.exists():
        return primary.resolve()
    basename = Path(model_filename).name
    for root in model_search_roots(cfg):
        cand = root / basename
        if cand.exists():
            return cand.resolve()
    return primary


def is_valid_gguf(path) -> bool:
    """True when *path* looks like a real, complete GGUF model file.

    Guards against a truncated download or an HTML error page saved as ``.gguf``
    being treated as a ready model: a genuine GGUF begins with the ``GGUF`` magic
    and is far larger than any error page. Used by setup-readiness, the model
    self-test, and the downloader's post-download verification.
    """
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size < 1024:
            return False
        with open(p, "rb") as f:
            return f.read(4) == b"GGUF"
    except Exception:
        return False


_file_cache: dict[str, tuple[float, str]] = {}  # path -> (mtime, content)


def _read_cached(path: Path) -> str:
    """Read a file with mtime caching — safe to call on every inference turn."""
    key = str(path)
    with _file_cache_lock:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            return _file_cache.get(key, (0.0, ""))[1]
        cached = _file_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            content = ""
        _file_cache[key] = (mtime, content)
        return content


def load_identity() -> str:
    return _read_cached(IDENTITY_FILE)


def load_personality() -> str:
    try:
        p = json.loads(_read_cached(REPO_ROOT / "personality.json"))
        return p.get("systemPromptAddition", "")
    except Exception:
        return ""


def load_personality_expression() -> str:
    return _read_cached(PERSONALITY_EXPRESSION_FILE).strip() if PERSONALITY_EXPRESSION_FILE.exists() else ""


def load_cognitive_lens() -> str:
    return _read_cached(COGNITIVE_LENS_FILE).strip() if COGNITIVE_LENS_FILE.exists() else ""


def load_behavioral_rhythm() -> str:
    return _read_cached(BEHAVIORAL_RHYTHM_FILE).strip() if BEHAVIORAL_RHYTHM_FILE.exists() else ""


def load_ui_reflection() -> str:
    return _read_cached(UI_REFLECTION_FILE).strip() if UI_REFLECTION_FILE.exists() else ""


def load_operational_guidance() -> str:
    return _read_cached(OPERATIONAL_GUIDANCE_FILE).strip() if OPERATIONAL_GUIDANCE_FILE.exists() else ""


def load_lens_knowledge() -> str:
    """Load summarized lens knowledge from lens_knowledge/*.md (prompt-only). Cached per mtime."""
    summaries = []
    try:
        if LENS_KNOWLEDGE_DIR.exists():
            for f in sorted(LENS_KNOWLEDGE_DIR.glob("*.md")):
                summaries.append(_read_cached(f)[:600])
    except Exception:
        pass
    return "\n\n".join(summaries) if summaries else ""


def _knowledge_priority_from_text(text: str) -> str:
    """Parse optional YAML front matter priority. Default support."""
    if not (text or "").strip().startswith("---"):
        return "support"
    for line in (text or "").split("\n")[1:]:
        line = line.strip()
        if line == "---":
            break
        if line.lower().startswith("priority:") and ":" in line:
            val = line.split(":", 1)[1].strip().lower()
            if val in ("core", "support", "flavor"):
                return val
    return "support"


def load_knowledge_docs(max_bytes: int = 6000) -> str:
    """Walk knowledge/ and concatenate .md / .txt files up to max_bytes. Excludes .identity. Priority: core > support > flavor."""
    knowledge_dir = REPO_ROOT / "knowledge"
    if not knowledge_dir.exists():
        return ""
    collected = []
    for ext in ("*.md", "*.txt"):
        for f in sorted(knowledge_dir.rglob(ext)):
            if ".identity" in str(f):
                continue
            try:
                text = _read_cached(f)
                priority = _knowledge_priority_from_text(text)
                if text.strip().startswith("---"):
                    end = text.find("\n---", 3)
                    body = text[end + 4:].strip() if end >= 0 else text
                else:
                    body = text
                collected.append((priority, f"--- {f.name} ---\n{body[:8000]}"))
            except Exception:
                continue
    order = {"core": 0, "support": 1, "flavor": 2}
    collected.sort(key=lambda x: order.get(x[0], 1))
    parts = []
    total = 0
    for _, chunk in collected:
        if total >= max_bytes:
            break
        remaining = max_bytes - total
        parts.append(chunk[:remaining])
        total += len(parts[-1])
    return "\n\n".join(parts)


def is_tool_allowed(tool_name: str) -> bool:
    """
    Return True when a tool is currently allowed to execute without creating a new pending approval.

    Naming note:
    - This used to be called require_approval(), which was easy to misread.
    - Semantics are "is allowed/approved" (via approvals.json), not "does this tool require approval?".
    """
    if tool_name in SAFE_TOOLS:
        return True
    if tool_name in DANGEROUS_TOOLS:
        try:
            cfg = load_config()
            if bool(cfg.get("admin_mode")) and not bool(cfg.get("admin_blocklist_override")):
                return True
            with path_lock(APPROVAL_FILE):
                data = json.loads(APPROVAL_FILE.read_text(encoding="utf-8"))
            return data.get(tool_name, False) if isinstance(data, dict) else False
        except Exception:
            return False
    return False


def require_approval(tool_name: str) -> bool:
    """Back-compat alias for is_tool_allowed(tool_name)."""
    return is_tool_allowed(tool_name)


def is_protected(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return any(resolved == p for p in PROTECTED_FILES)
    except Exception:
        return False


def backup_file(path: Path) -> bool:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = utcnow().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"{path.stem}_{ts}{path.suffix}"
        shutil.copy2(str(path), str(dest))
        return True
    except Exception:
        return False


def log_execution(tool_name: str, payload: dict) -> None:
    # Redact secrets/PII and cap oversized content before persisting (REQ-42/43).
    # Centralized here so every tool_dispatch call site (incl. mcp_tools_call's
    # arbitrary args) is covered by one chokepoint.
    try:
        from services.safety.secret_filter import redact_payload
        safe_payload = redact_payload(payload)
    except Exception:
        safe_payload = payload
    entry = {
        "timestamp": utcnow().isoformat(),
        "tool": tool_name,
        "payload": safe_payload,
    }
    try:
        GOV_PATH.mkdir(parents=True, exist_ok=True)
        # Append-only JSON-lines: one object per line, NO read-back. The previous whole-file
        # read+append+rewrite was O(n) per call — O(n²) over a session — and grew unbounded.
        # A single open-append is O(1); _bg_cleanup tail-trims this file to execution_log_max_bytes.
        line = json.dumps(entry, ensure_ascii=False)
        with path_lock(EXEC_LOG_FILE):
            with open(EXEC_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
