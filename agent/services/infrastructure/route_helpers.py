"""Helpers shared by FastAPI routers (extracted from main)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_plugins_cache: dict = {}
_plugins_cache_ts: float = 0.0
_PLUGINS_CACHE_TTL: float = 60.0


def get_cached_plugins(cfg: dict) -> dict:
    """Avoid rescanning plugins on every UI refresh."""
    global _plugins_cache, _plugins_cache_ts
    now = time.time()
    if _plugins_cache and (now - _plugins_cache_ts) < _PLUGINS_CACHE_TTL:
        return _plugins_cache
    from services.skills.plugin_loader import load_plugins

    _plugins_cache = load_plugins(cfg)
    _plugins_cache_ts = now
    return _plugins_cache


def _values_agree(a: Any, b: Any) -> bool:
    """Is the stored value the same value as the effective one?

    Deliberately not `a == b`: JSON round-trips ints to floats, list-typed settings compare by
    content, and `True == 1` in Python — which would let a boolean setting coerced to an int
    read as "took effect". Booleans are compared by identity of type so that coercion shows up
    as a disagreement rather than hiding inside ==.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_values_agree(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_values_agree(a[k], b[k]) for k in a)
    return a == b


def readback(stored: dict[str, Any], *, adjust_reason: dict | None = None,
             raw: dict | None = None, order=None) -> dict:
    """THE READ-BACK, as one function every config-writing surface calls.

    Give it {key: the value that was actually WRITTEN}; it re-reads the effective config —
    what the running app now sees, not the file it was written to — and returns

        {report: [{key, requested, effective?, outcome, owner, reason}],
         overridden: [key], not_in_force: [row], in_force: bool, readable: bool,
         note: str}

    `outcome` is took_effect / clamped / overridden / unknown.

    WHY THIS IS A FUNCTION AND NOT A PARAGRAPH INSIDE POST /settings.
    It was a paragraph inside POST /settings, and the two surfaces one call away from it —
    POST /settings/preset and POST /settings/themes — each answered from INTENT instead.
    /settings/preset ran `save_config_keys(...)`, discarded the return, and replied
    {"ok": true, "applied": [16 keys]} unconditionally; driven on a CPU box the "potato"
    preset reported n_batch 256, max_runtime_seconds 20 and completion_max_tokens 256 applied
    while the effective config held 512 / 300 / 320. Every one of those keys is an
    auto_tune.PROFILE_KEY that `key_owner` already answers for correctly — the engine was
    right there, one function below, and the caller simply did not ask it. So the read-back
    stops being something a surface can forget to do and becomes the thing it calls.

    `raw` is the pre-clamp request, used only to quote what the operator typed in a clamp
    message. `order` fixes the report order (default: the order of `stored`).
    """
    from install.feature_status import KNOWN_OWNERS, effective_config, key_owner
    from services.safety.secret_filter import REDACTED, is_secret_key

    adjust_reason = adjust_reason or {}
    raw = raw if isinstance(raw, dict) else {}
    keys = list(order) if order is not None else list(stored)

    try:
        cfg = effective_config()
        readable = True
    except Exception as e:
        # We cannot see what is in force. That is UNKNOWN, and UNKNOWN is not success — the
        # one thing we must not do is fall back to "what was requested", which is the very
        # inference this whole change deletes.
        logger.warning("readback: effective config unreadable: %s", e)
        cfg, readable = {}, False

    def _shown(key: str, value: Any) -> Any:
        """Never echo a credential back in a status message."""
        return REDACTED if is_secret_key(key) and value not in (None, "", [], {}) else value

    report: list[dict] = []
    overridden: list[str] = []
    for k in keys:
        want = stored.get(k)
        row: dict = {"key": k, "requested": _shown(k, want)}
        if not readable:
            row.update({"outcome": "unknown", "owner": "unreadable",
                        "reason": "could not re-read the effective configuration, so whether "
                                  "this value is in force could not be confirmed."})
            report.append(row)
            continue
        effective = cfg.get(k)
        if _values_agree(want, effective):
            if k in adjust_reason:
                row.update({"outcome": "clamped", "owner": "schema",
                            "reason": f"{adjust_reason[k]} to {want!r} (you entered "
                                      f"{_shown(k, raw.get(k))!r})"})
            else:
                row.update({"outcome": "took_effect", "owner": "", "reason": ""})
            report.append(row)
            continue
        # Written, and NOT in force. Ask the shared owner registry — the wizard's, not a
        # second copy — and fall back to an honest unknown rather than a silent green.
        row["effective"] = _shown(k, effective)
        hit = key_owner(k, cfg)
        if hit:
            row.update({"outcome": "overridden", "owner": hit[0], "reason": hit[1]})
        else:
            row.update({
                "outcome": "overridden", "owner": "unknown",
                "reason": f"saved to disk, but the running configuration still reads "
                          f"{_shown(k, effective)!r} and no known owner ({KNOWN_OWNERS}) "
                          f"accounts for it. Reason unknown — this value did NOT take effect.",
            })
        overridden.append(k)
        report.append(row)

    not_in_force = [r for r in report if r["outcome"] in ("overridden", "unknown")]
    note = ""
    if not_in_force:
        # One note per OWNER's own words. The old note hardcoded auto-tune's remedy
        # ("add the key to auto_tune_locked_keys") for every override, so a maturity-gated key
        # — if it had ever been detected — would have sent the operator to a lock list that
        # cannot unlock it.
        note = "saved to disk, but not in force: " + " · ".join(
            f"{r['key']} — {r['reason']}" for r in not_in_force
        )
    return {"report": report, "overridden": sorted(overridden), "not_in_force": not_in_force,
            "in_force": not not_in_force, "readable": readable, "note": note, "cfg": cfg}


def raw_config_file() -> dict:
    """What runtime_config.json ASKS for — the request, before any owner overlays it.

    load_config() is the answer to "what is in force"; this is the answer to "what did the
    operator ask for", and every honest "you asked for X, X is off because Y" needs both.
    Missing or unreadable file -> {} (we know of no request), never an exception into a caller
    that would then report the effective config as if it were the intent.
    """
    import json

    import runtime_safety as _rs

    try:
        raw = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("raw_config_file: unreadable: %s", e)
        return {}


def not_in_force_report() -> dict:
    """Every editable key the config FILE asks for that the RUNNING APP does not honour.

    C3 — THE MISSING GET CONSUMER. `key_owner` had exactly one caller shape: a response to a
    write. So the settings panel could only learn that a key was not in force in the instant
    it saved that key, and the amber warning it drew was retracted by the next unrelated save:

        1. tick hyde_enabled, save  -> amber "NOT in force — held by auto_tune", row marked
        2. edit max_tool_calls, save -> GREEN "Saved 1 change", panel gone, hyde still ticked

    Step 2 is a green success next to a ticked box for a setting that is not in force, and no
    amount of care in the save path fixes it: the panel posts only what changed (deliberately —
    that is what keeps the warning from becoming wallpaper), so hyde_enabled is simply not in
    that response. The state is not a property of a save. It is a property of the CONFIG, and
    it has to be readable as one.

    Comparing the file against the effective config is the same write-then-read gap the whole
    slice is built on, asked without a write: the file is what was requested, load_config() is
    what is in force, and every key where they disagree is a request that did not land.
    """
    import json

    import runtime_safety as _rs
    from config_schema import get_editable_keys

    try:
        raw = json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except FileNotFoundError:
        raw = {}
    except Exception as e:
        # We cannot read what was requested, so we cannot say anything about it. Report the
        # failure rather than an empty (== "everything is fine") list — and `in_force` is None,
        # not True: UNKNOWN is not "all clear". Returning True beside ok:False would be a
        # cheerful answer assembled from a failure, which is this slice's whole subject.
        logger.warning("not_in_force_report: config file unreadable: %s", e)
        return {"ok": False, "error": f"could not read the configuration file: {e}",
                "not_in_force": [], "in_force": None, "note": ""}

    editable = get_editable_keys()
    rb = readback({k: v for k, v in raw.items() if k in editable})
    return {"ok": True, "not_in_force": rb["not_in_force"], "in_force": rb["in_force"],
            "note": rb["note"], "readable": rb["readable"]}


def sync_save_settings(body: dict, *, blocked_keys=None, keyring_keys=None) -> dict:
    """Blocking: merge editable keys into runtime_config.json (race-safe, atomic, clamped),
    then RE-READ THE EFFECTIVE CONFIG and report, per key, what actually happened.

    This endpoint answered a blanket {"ok": true} for every write, which was false in two
    distinct ways:

      1. a key outside EDITABLE_SCHEMA is dropped on the floor by save_config_keys — the
         list of keys it actually saved was already computed and thrown away;
      2. some editable keys are OWNED by a subsystem that overwrites them on every config
         load. The write lands in the file and is then reverted before anything reads it, so
         "saved" was true and meaningless. The user edits n_ctx, is told it worked, and the
         old value is back on the next load.

    S1 — WHY THE FIRST FIX FOR (2) WAS ITSELF TWO LIES.
    It read:

        overridden = [k for k in res["changed"]
                      if k in auto_tune_managed_keys() and k not in locked]

    (a) ONE OWNER, HARDCODED. auto-tune was enumerated; runtime_safety.MATURITY_GATED_KEYS was
        not. POST {"inline_initiative_enabled": true} returned ok:true with every warning list
        empty — a clean green success for a value the maturity gate reverts at load. Any future
        owner would have been invisible the same way, because the list was a literal.
    (b) THE `changed` FILTER SILENCED IT EXACTLY WHEN IT MATTERED. `changed` compares the
        request against the FILE, but the checkbox is rendered from the EFFECTIVE config (GET
        /settings → load_config). Once file == request while effective != request — the STEADY
        STATE after any wizard apply — the key is not "changed", so the warning was suppressed
        precisely in the case it exists for.

    THE FIX IS THE READ-BACK PRINCIPLE, applied here as it already is in the wizard: do not
    derive the outcome from a diff against a hardcoded owner list. Write, re-read what the
    running app now sees, and compare. Ownership is answered by install/feature_status.key_owner
    — the SAME registry the wizard uses, not a second one — and an owner nobody has written a
    probe for still yields an honest "did not take effect, reason unknown", never a silent green.

    `report` is the per-key answer: took_effect / clamped / overridden / rejected / refused.
    """
    import runtime_safety as _rs
    from config_schema import coerce_and_clamp, get_editable_keys, normalize_list_value

    body = body if isinstance(body, dict) else {}
    editable = get_editable_keys()
    # `blocked_keys` are the security-critical keys a REMOTE caller is not allowed to write.
    # POST /settings strips them from the body BEFORE calling us, so they were absent from
    # `body` by the time `rejected` was computed: a remote operator editing safe_mode or
    # sandbox_root got {"ok": true, "saved": [...]} and a green toast for a refused write.
    # They are refusals and must be reported as such.
    refused_remote = sorted(set(blocked_keys or []))
    rejected = sorted(set(k for k in body if k not in editable) | set(refused_remote))

    # Only auto-tune-managed keys can be locked; a typo'd or non-managed key in the lock list
    # would silently do nothing, which is the same class of lie this whole change removes.
    bad_locks: list[str] = []
    if "auto_tune_locked_keys" in body:
        from config_schema import auto_tune_managed_keys

        managed = auto_tune_managed_keys()
        requested = normalize_list_value(body["auto_tune_locked_keys"])
        bad_locks = sorted(k for k in requested if k not in managed)
        body = dict(body)
        body["auto_tune_locked_keys"] = [k for k in requested if k in managed]

    # save_config_keys_detailed reads+writes under _config_lock and clamps each value to the
    # schema (config_schema.coerce_and_clamp), so out-of-range input can't be persisted
    # and two concurrent writers can't lose each other's changes. It also reports which
    # values it had to REWRITE to do that (BL: "Settings saved (90)" in green while the 500
    # you typed became 50 on disk) — a write that lands as a different value is neither a
    # rejection nor a clean save, so it gets its own field.
    res = _rs.save_config_keys_detailed(body, editable_only=True, clamp=True)
    saved = res["saved"]
    adjusted = res["adjusted"]
    adjust_reason = {a["key"]: a["reason"] for a in adjusted}

    # The value that actually LANDED, which is what "in force" has to be compared against —
    # not the raw request. save_config_keys_detailed clamps and coerces every key but only
    # reports `stored` for the ones it considered worth flagging, and a type-equivalent
    # coercion ("7" from a text input -> 7, "true" -> True) is deliberately NOT flagged.
    # Comparing the raw "7" against the effective 7 makes every text-input save read as
    # "did not take effect, reason unknown" — a false alarm, which is the same lie with the
    # sign flipped, and a warning that cries wolf is the wallpaper this reporting removed.
    def _stored_value(key: str):
        try:
            return coerce_and_clamp(key, body[key])
        except Exception:
            return body.get(key)

    # THE READ-BACK, shared with every other surface that writes config (see `readback`).
    rb = readback({k: _stored_value(k) for k in saved},
                  adjust_reason=adjust_reason, raw=body, order=saved)
    report = rb["report"]
    overridden = rb["overridden"]
    not_in_force = rb["not_in_force"]

    # C5 — A SUCCESSFUL SAVE REPORTED AS "Nothing was saved".
    # POST /settings routes secret-typed keys into the OS keyring and hands us the body with
    # those keys REMOVED (that is the point: they must not reach runtime_config.json in
    # plaintext). They were therefore absent from `saved`, so saving only a secret — an api
    # key, a tunnel token — produced saved=[] and the UI's honest last branch, "Nothing was
    # saved", over a write that fully succeeded. That is this slice's defect with the sign
    # flipped, and it costs the same thing: an operator who learns to disbelieve true messages.
    #
    # They are NOT run through the config read-back, because the config is not where they
    # went. Their confirmation is set_secret() returning True, which is what put them in this
    # list; re-reading runtime_config.json for a key deliberately kept out of it would
    # manufacture a not-in-force warning for a correct write.
    secret_saved = sorted(set(keyring_keys or []))
    for k in secret_saved:
        report.append({"key": k, "requested": "***", "outcome": "took_effect",
                       "owner": "keyring",
                       "reason": "stored in the OS keyring, not in runtime_config.json"})
    saved = saved + [k for k in secret_saved if k not in saved]

    out: dict = {
        "ok": not rejected and not bad_locks,
        "saved": saved,
        "secrets_saved": secret_saved,
        "changed": res["changed"],
        "rejected": rejected,
        "adjusted": adjusted,
        "overridden": overridden,
        "report": report,
        # The single flag the UI needs to decide green vs amber. Derived from the read-back,
        # so it stays correct when a future owner appears that no probe recognises.
        "in_force": rb["in_force"],
    }
    if adjusted:
        out["adjusted_note"] = "; ".join(
            f"{a['key']}: {a['reason']} {a['requested']!r} → {a['stored']!r}" for a in adjusted
        )
    # Both refusals can happen in one request; appending rather than assigning keeps the
    # second from silently erasing the first (which would drop a security refusal on the floor).
    errors: list[str] = []
    if refused_remote:
        out["refused_remote"] = refused_remote
        errors.append(
            "these settings can only be changed from the machine Layla runs on: "
            + ", ".join(refused_remote)
        )
    if bad_locks:
        out["rejected_locks"] = bad_locks
        errors.append(
            "these are not auto-tune-managed settings and cannot be locked: "
            + ", ".join(bad_locks)
        )
    if errors:
        out["error"] = "; ".join(errors)
    if not_in_force:
        out["overridden_note"] = rb["note"]
    return out


def sync_apply_runtime_preset(name: str) -> dict:
    """Blocking: merge named preset into runtime_config.json, then REPORT WHAT IS IN FORCE.

    C1. This called save_config_keys, threw the return away, and answered
    {"ok": True, "applied": <the preset's key list>} — the INTENT, unconditionally, with no
    path by which it could ever say otherwise. Driven on this CPU box, "potato" reported 16
    keys applied while the effective config disagreed with three of them:

        n_batch              asked 256 -> in force 512
        max_runtime_seconds  asked  20 -> in force 300
        completion_max_tokens asked 256 -> in force 320

    …because all three are auto_tune.PROFILE_KEYS and auto-tune re-derives them on every load.
    So the one preset whose entire purpose is "make this box behave like a potato" could not,
    and said it had. `applied` now means WHAT IS ACTUALLY IN FORCE — the question the caller
    was really asking — and `not_in_force` names the rest with their owner and remedy.
    """
    import runtime_safety as _rs
    from config_schema import SETTINGS_PRESETS, apply_settings_preset

    if name.lower() not in SETTINGS_PRESETS:
        raise ValueError("unknown_preset")
    merged, applied = apply_settings_preset({}, name)
    if merged is None:
        raise ValueError("unknown_preset")
    requested = {k: merged[k] for k in applied}
    res = _rs.save_config_keys_detailed(requested, editable_only=True, clamp=True)
    saved = res["saved"]
    adjust_reason = {a["key"]: a["reason"] for a in res["adjusted"]}

    # Compare against the value that LANDED, not the value asked for: save_config_keys_detailed
    # clamps to the schema, and a clamp is its own outcome, not a silent override.
    stored = dict(requested)
    for a in res["adjusted"]:
        stored[a["key"]] = a["stored"]
    rb = readback({k: stored[k] for k in saved}, adjust_reason=adjust_reason,
                  raw=requested, order=saved)

    in_force = [r["key"] for r in rb["report"] if r["outcome"] in ("took_effect", "clamped")]
    out = {
        # `ok` still reports the WRITE — the operator asked for a preset and the preset was
        # written. Whether every key survived the read is `in_force`, and the UI must show
        # amber on that, not green on this. Conflating them would swing the lie the other way
        # (a preset that applied 15 of 16 keys is not a failure).
        "ok": True,
        "preset": name.lower(),
        "applied": in_force,
        "requested": saved,
        "dropped": sorted(set(requested) - set(saved)),
        "adjusted": res["adjusted"],
        "report": rb["report"],
        "not_in_force": [r["key"] for r in rb["not_in_force"]],
        "in_force": rb["in_force"],
    }
    if rb["not_in_force"]:
        out["not_in_force_note"] = rb["note"]
    return out


def sync_set_project_context(body: dict) -> dict:
    from layla.memory.db import PROJECT_LIFECYCLE_STAGES, set_project_context

    set_project_context(
        project_name=body.get("project_name", ""),
        domains=body.get("domains"),
        key_files=body.get("key_files"),
        goals=body.get("goals", ""),
        lifecycle_stage=body.get("lifecycle_stage", ""),
        progress=body.get("progress", ""),
        blockers=body.get("blockers", ""),
        last_discussed=body.get("last_discussed", ""),
    )
    return {"ok": True, "lifecycle_stages": list(PROJECT_LIFECYCLE_STAGES)}


def sync_ingest_docs(source: str, label: str) -> dict:
    from services.workspace.doc_ingestion import ingest_docs

    return ingest_docs(source, label)


def sync_create_and_run_mission(body: dict) -> dict:
    from services.planning.mission_manager import create_mission, run_mission

    goal = (body.get("goal") or "").strip()
    if not goal:
        raise ValueError("goal required")
    mission = create_mission(
        goal=goal,
        workspace_root=(body.get("workspace_root") or "").strip(),
        allow_write=bool(body.get("allow_write")),
        allow_run=bool(body.get("allow_run")),
    )
    if not mission:
        raise ValueError("mission creation failed (plan empty or planner error)")
    run_mission(mission["id"])
    return {"ok": True, "mission": mission}


#: UI-only appearance keys. Not in EDITABLE_SCHEMA (POST /settings would silently drop them), so this
#: endpoint exists to accept them: editable_only=False, clamp=False.
#:
#: This IS a hand-maintained allowlist, which is normally how a guard misses the very thing it was built
#: to catch — a key absent from here is dropped in silence. That is survivable ONLY because
#: sync_save_appearance now reports `rejected` instead of swallowing it: forget to add a key here and the
#: caller is TOLD, rather than being handed "ok" over a no-op. The list stays because it is a genuine
#: security boundary (an open passthrough would let any caller write arbitrary config keys); the
#: reporting is what makes forgetting it loud.
APPEARANCE_KEYS = (
    "ui_avatar_seed",
    "ui_avatar_style",
    "ui_tts_rate",
    "chat_lite_mode",
    "ui_decision_trace_enabled",
    "ui_appearance_json",
    "ui_font_size",        # BL-335: the text-size accessibility control
    "ui_animation_level",  # BL-335
)


def sync_save_appearance(body: dict) -> dict:
    """Save UI appearance keys and report EXACTLY what was and was not saved.

    BL-366. `save_config_keys` has always returned the list of keys it actually saved — the information
    needed to stop lying was already computed, and the router threw it away and returned a flat
    `{"ok": True}`. So "Appearance saved" was printed with equal confidence whether the write landed or
    the key was dropped on the floor.

    Now `rejected` comes back too, and `ok` is True only when NOTHING was dropped. That closes the lie
    for every future key, not just this one: a caller that posts an unknown key gets told, instead of a
    success toast over a no-op.
    """
    import runtime_safety as _rs

    updates = {k: body[k] for k in APPEARANCE_KEYS if k in body}
    rejected = sorted(k for k in body if k not in APPEARANCE_KEYS)
    saved = _rs.save_config_keys(updates, editable_only=False, clamp=False)
    return {"ok": not rejected, "saved": saved, "rejected": rejected}


def sync_compact_history() -> dict:
    """Summarize in-memory chat history when over context threshold."""
    import runtime_safety
    from services.context.context_manager import summarize_history
    from shared_state import get_history

    cfg = runtime_safety.load_config()
    n_ctx = int(cfg.get("n_ctx", 4096))
    ratio = float(cfg.get("context_auto_compact_ratio", 0.75))
    _history = get_history()
    dict_msgs = [{"role": m.get("role"), "content": m.get("content", "")} for m in _history if isinstance(m, dict)]
    if not dict_msgs:
        return {"ok": True, "summary": "", "messages_remaining": 0}
    new_msgs = summarize_history(dict_msgs, n_ctx=n_ctx, threshold_ratio=ratio)
    summary = ""
    if new_msgs and str(new_msgs[0].get("role", "")).lower() == "system":
        summary = str(new_msgs[0].get("content", ""))
    _history.clear()
    for m in new_msgs:
        _history.append(m)
    try:
        from routers.paths import REPO_ROOT

        hist_file = REPO_ROOT / "conversation_history.json"
        hist_file.write_text(json.dumps(list(_history), indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("sync_compact_history save failed: %s", e)
    return {"ok": True, "summary": summary[:12000], "messages_remaining": len(_history)}
