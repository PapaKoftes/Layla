"""
A1/A2/A3 — a refused write is reported as refused, on every surface that can ask.

WHY THIS FILE EXISTS, GIVEN A GREEN GATE AND A WHOLE FILE ABOUT READ-BACKS

test_settings_readback.py drives POST /settings and asserts that a write an OWNER reverts comes
back flagged. It passed. And POST /settings/themes {"key":"remote_access","enabled":true} still
persisted remote_enabled with no credential and answered {"ok":true,"in_force":true} — because
"an owner reverts it at load" and "this must never be persisted" are different mechanisms, and
only the first one had tests. Driven against a live temp instance before the fix:

    POST /settings/themes {"key":"remote_access","enabled":true}
      -> 200 {"ok":true,"enabled":true,"in_force":true}
      -> runtime_config.json: remote_enabled true, no tunnel_token_hash, no remote_api_key
      -> the VERY NEXT GET /settings on that instance: 403 "no auth configured"

The operator locked themselves out of their own localhost with a checkbox and was told it
worked. install/setup_profiles.apply_setup had refused exactly this write for the exact reason,
in a comment — so the knowledge existed and the guard was in one surface out of three.

THE SHAPE OF THE TESTS THAT WOULD HAVE CAUGHT IT
`test_no_surface_can_persist_remote_without_a_credential` does not name the themes endpoint. It
asserts the INVARIANT: whatever writes the config, this state cannot land on disk. A test that
only covered the surfaces that exist today would pass again the day a fourth one is written,
which is precisely how this bug arrived at the third.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """Throwaway config — no test may touch operator state."""
    import runtime_safety as rs

    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


@pytest.fixture()
def no_keyring(monkeypatch):
    """No OS keyring, so the credential test reads only the config under test.

    Without this the assertions depend on whatever the developer's own machine has stored under
    the "layla" service — a test that passes or fails based on the runner's keychain is not a
    test. (remote_credential_present resolves through the keyring on purpose: a token stored
    there IS a credential, and refusing it would block the safe configuration.)
    """
    import services.safety.secret_store as ss

    monkeypatch.setattr(ss, "_keyring", lambda: None)
    monkeypatch.delenv("LAYLA_TUNNEL_TOKEN_HASH", raising=False)
    monkeypatch.delenv("LAYLA_REMOTE_API_KEY", raising=False)


def _disk(cfg_file) -> dict:
    return json.loads(cfg_file.read_text(encoding="utf-8"))


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


# ── A1: THE INVARIANT ───────────────────────────────────────────────────────────

#: Every writer that can put a config dict on disk. The point of naming them as data is that
#: adding a writer without adding it here is visible; adding one without ENFORCING the
#: invariant is not possible, because they all funnel through runtime_safety.
def _write_via_atomic(cfg_file, cfg):
    """atomic_write_config replaces the WHOLE config, so its callers (first_run.save_config,
    setup_engine.save_config, self_improvement) read-modify-write. Mirror that, or the writer
    would silently drop the seeded credential and "prove" a refusal that was really just a
    dict that no longer had the token in it."""
    import runtime_safety as rs

    rs.atomic_write_config({**_disk(cfg_file), **cfg})


def _write_via_save_keys(cfg_file, cfg):
    import runtime_safety as rs

    rs.save_config_keys(dict(cfg), editable_only=False, clamp=False)


def _write_via_save_keys_editable(cfg_file, cfg):
    import runtime_safety as rs

    rs.save_config_keys(dict(cfg), editable_only=True, clamp=True)


def _write_via_apply_setup(cfg_file, cfg):
    import runtime_safety as rs
    from install.setup_profiles import apply_setup

    rs.save_config_keys(dict(cfg), editable_only=False, clamp=False)
    apply_setup([], ["remote"], save=True)


def _write_via_post_settings(cfg_file, cfg):
    _client().post("/settings", json=dict(cfg))


def _write_via_post_themes(cfg_file, cfg):
    _client().post("/settings/themes", json={"key": "remote_access", "enabled": True})


ALL_WRITERS = [
    pytest.param(_write_via_atomic, id="atomic_write_config"),
    pytest.param(_write_via_save_keys, id="save_config_keys"),
    pytest.param(_write_via_save_keys_editable, id="save_config_keys_editable_clamped"),
    pytest.param(_write_via_apply_setup, id="setup_wizard_apply_setup"),
    pytest.param(_write_via_post_settings, id="POST_settings"),
    pytest.param(_write_via_post_themes, id="POST_settings_themes"),
]


@pytest.mark.parametrize("writer", ALL_WRITERS)
def test_no_surface_can_persist_remote_without_a_credential(cfg_file, no_keyring, writer):
    """THE INVARIANT, asked of every writer: this state must never reach the disk.

    Not "the themes endpoint refuses it" — that phrasing is what produced a fix in one handler
    and left two others open. The subject of the sentence is the CONFIG.
    """
    writer(cfg_file, {"remote_enabled": True})

    assert _disk(cfg_file).get("remote_enabled") is not True, (
        "remote_enabled was persisted with no credential — every request, localhost included, "
        "now answers 403 and the operator is locked out of their own machine"
    )
    import runtime_safety as rs

    rs.invalidate_config_cache()
    assert rs.load_config().get("remote_enabled") is not True


@pytest.mark.parametrize("writer", ALL_WRITERS)
def test_every_surface_still_permits_remote_with_a_credential(cfg_file, no_keyring, writer):
    """The other half, and the half a security guard usually gets wrong.

    A check that also blocks the SAFE configuration is worse than no check: it teaches the
    operator that the guard is broken, and the way past a guard you believe is broken is to
    remove it. With a real token hash already stored, every one of these writers must let
    remote through.

    The credential is seeded FIRST rather than sent alongside the flag, because that is the
    only flow that exists: `tunnel_token_hash` is not in EDITABLE_SCHEMA, so POST /settings
    drops it by design and the token can only arrive via /remote/token/rotate. A test that
    sent both in one request would be asserting against a request no surface can make — and
    would have "failed" here for a reason that has nothing to do with the invariant.
    """
    import runtime_safety as rs

    rs.save_config_keys({"tunnel_token_hash": "a" * 64}, editable_only=False, clamp=False)

    writer(cfg_file, {"remote_enabled": True})

    assert _disk(cfg_file).get("remote_enabled") is True
    rs.invalidate_config_cache()
    assert rs.load_config().get("remote_enabled") is True


def test_a_legacy_key_the_authenticator_will_not_honour_is_not_a_credential(cfg_file, no_keyring):
    """`remote_api_key` alone does not open the door — so it must not open this gate either.

    tunnel_auth.validate_token honours the plaintext key ONLY when
    allow_legacy_remote_api_key is true. A config holding just the key can therefore
    authenticate nobody, and enabling remote on it is the same total lockout as having no key
    at all. The looser "either field is non-empty" test — which is what this check used to be
    in setup_profiles and feature_status — calls that state credentialled and waves it through.
    """
    import runtime_safety as rs

    assert rs.remote_credential_present({"remote_api_key": "k"}) is False
    assert rs.remote_credential_present(
        {"remote_api_key": "k", "allow_legacy_remote_api_key": True}) is True
    assert rs.remote_credential_present({"tunnel_token_hash": "h"}) is True
    assert rs.remote_credential_present({"tunnel_token_hash": "   "}) is False, \
        "whitespace is not a credential"

    rs.save_config_keys({"remote_enabled": True, "remote_api_key": "k"},
                        editable_only=False, clamp=False)
    assert _disk(cfg_file).get("remote_enabled") is not True

    rs.save_config_keys({"remote_enabled": True, "allow_legacy_remote_api_key": True},
                        editable_only=False, clamp=False)
    assert _disk(cfg_file).get("remote_enabled") is True


def test_a_keyring_stored_token_counts_as_a_credential(cfg_file, monkeypatch):
    """A token in the OS keyring is a real credential, and refusing it would be a false alarm.

    resolve_config_secrets only overlays keys already PRESENT in the config dict, so a keyring
    token on a config that never mentions the key is invisible to a raw-dict comparison. That
    operator is fully credentialled and would have been told to go and get a credential.
    """
    import runtime_safety as rs
    import services.safety.secret_store as ss

    monkeypatch.setattr(ss, "get_secret",
                        lambda key, cfg_value=None: "hash-from-keyring"
                        if key == "tunnel_token_hash" else cfg_value)
    assert rs.remote_credential_present({}) is True

    rs.save_config_keys({"remote_enabled": True}, editable_only=False, clamp=False)
    assert _disk(cfg_file).get("remote_enabled") is True


def test_the_refusal_is_reported_with_a_reason_not_silently_snapped_back(cfg_file, no_keyring):
    """A silent coercion is the same lie as a false success — it just fails later.

    The operator must be told (a) it did not happen and (b) the precondition, in the response
    to the click that asked for it.
    """
    from services.infrastructure.route_helpers import sync_save_settings

    d = sync_save_settings({"remote_enabled": True})

    assert d["ok"] is False, "a refused write must not report ok"
    assert d["refused"] == ["remote_enabled"]
    row = next(r for r in d["report"] if r["key"] == "remote_enabled")
    assert row["outcome"] == "refused", "'overridden' would send them hunting for an owner"
    assert row["owner"] == "security_policy"
    assert row["effective"] is False
    # The reason has to carry the CONSEQUENCE and the REMEDY, or it is just a denial.
    assert "403" in row["reason"] and "localhost" in row["reason"]
    assert "/remote/token/rotate" in row["reason"]


def test_the_themes_toggle_reports_the_refusal_and_the_effective_state(cfg_file, no_keyring):
    """A1's headline surface, end to end through the real app."""
    r = _client().post("/settings/themes", json={"key": "remote_access", "enabled": True})
    d = r.json()

    assert d["ok"] is False, "a caller that checks only d.ok must not read this as success"
    assert d["enabled"] is False, "the checkbox must not be left showing a grant that was refused"
    assert d["requested"] is True
    assert d["in_force"] is False
    assert d["refused"] == ["remote_enabled"]
    assert "403" in d["error"] and "/remote/token/rotate" in d["error"]
    assert _disk(cfg_file).get("remote_enabled") is not True


def test_the_instance_does_not_lock_itself_out(cfg_file, no_keyring):
    """THE ORIGINAL SYMPTOM, asserted as behaviour rather than as config.

    Before the fix this exact sequence answered 403 "no auth configured" — the verifier who
    found A1 did it to their own instance. This is the test that fails loudly if a future
    refactor lets the flag through by some path the config assertions miss.
    """
    c = _client()
    c.post("/settings/themes", json={"key": "remote_access", "enabled": True})

    after = c.get("/settings")
    assert after.status_code == 200, (
        f"the instance locked itself out of its own localhost: "
        f"{after.status_code} {after.text[:200]}"
    )


def test_the_rotate_endpoint_actually_stores_the_hash_it_hands_out(cfg_file, no_keyring):
    """The refusal's remedy has to work, or the refusal is a dead end.

    /remote/token/rotate wrote to a hardcoded AGENT_DIR/runtime_config.json while every reader
    uses runtime_safety.CONFIG_FILE (which honours LAYLA_DATA_DIR). On an installed instance
    those differ: the operator was shown a token, told to save it, and remote access still had
    no credential — with the refusal message still telling them to rotate one.
    """
    import runtime_safety as rs

    d = _client().post("/remote/token/rotate").json()

    assert d["ok"] is True and d["token"]
    assert _disk(cfg_file).get("tunnel_token_hash"), \
        "the hash was written somewhere nothing reads"
    assert rs.remote_credential_present(_disk(cfg_file)) is True

    # And now the previously-refused write is permitted — the remedy leads somewhere.
    r = _client().post("/settings/themes", json={"key": "remote_access", "enabled": True})
    assert r.json()["ok"] is True
    assert _disk(cfg_file).get("remote_enabled") is True


# ── A2: the pairing permission endpoint ─────────────────────────────────────────

@pytest.fixture()
def paired_device(tmp_path, monkeypatch):
    """A paired device in a throwaway store — agent/.governance is operator state."""
    import routers.pairing as pairing

    store = tmp_path / "paired_devices.json"
    monkeypatch.setattr(pairing, "_PAIRED_DEVICES_FILE", store)
    pairing._save_paired_devices(
        {"dev1": {"name": "Test Drone", "permissions": {"read_learnings": True}}})
    return store


def test_unknown_permission_keys_are_refused_by_name(paired_device):
    """A2's server half.

    The loop dropped unknown keys and still answered {"ok": true, "permissions": {...}}.
    Driven: update_permissions("dev1", {"remote_toolz": True, "execute_anything": True})
    -> {"ok": True, "permissions": {"read_learnings": True}} with NEITHER key written. Since
    `remote_tools` grants REMOTE TOOL EXECUTION, a typo produced a confident success for a
    privilege grant that does not exist.
    """
    d = _client().patch("/pairing/dev1/permissions",
                        json={"remote_toolz": True, "execute_anything": True}).json()

    assert d["ok"] is False
    assert d["rejected"] == ["execute_anything", "remote_toolz"]
    assert d["applied"] == []
    assert "remote_toolz" in d["error"] and "remote_tools" in d["error"], \
        "the refusal must name what was refused AND what is valid"
    # Nothing was written — the read-back is from the stored record, not the request.
    assert d["permissions"] == {"read_learnings": True}
    assert json.loads(paired_device.read_text(encoding="utf-8"))["dev1"]["permissions"] == \
        {"read_learnings": True}


def test_a_valid_permission_still_applies_and_reads_back(paired_device):
    d = _client().patch("/pairing/dev1/permissions", json={"remote_tools": True}).json()

    assert d["ok"] is True
    assert d["applied"] == ["remote_tools"] and d["rejected"] == []
    assert d["permissions"]["remote_tools"] is True
    assert json.loads(paired_device.read_text(encoding="utf-8"))["dev1"]["permissions"][
        "remote_tools"] is True


def test_a_partial_grant_is_not_reported_as_ok(paired_device):
    """One valid key beside one invalid key is not a success — the operator asked for both."""
    d = _client().patch("/pairing/dev1/permissions",
                        json={"remote_tools": True, "execute_anything": True}).json()

    assert d["ok"] is False
    assert d["applied"] == ["remote_tools"]
    assert d["rejected"] == ["execute_anything"]


def test_permissions_on_an_unpaired_device_is_not_a_success(paired_device):
    """The live 404 the UI toasted as "remote tools: enabled"."""
    r = _client().patch("/pairing/nope/permissions", json={"remote_tools": True})

    assert r.status_code == 404
    assert r.json()["detail"] == "Device not paired"


# ── A3: one owner for cluster_enabled ───────────────────────────────────────────

def test_cluster_enabled_has_exactly_one_working_surface(cfg_file, no_keyring):
    """A3. The cluster panel posted {cluster_enabled} to POST /settings, which is not in
    EDITABLE_SCHEMA — so it answered 200 {"ok": false, "rejected": [...]} and the panel's
    `if (d.ok) {...}` with no else did nothing at all, silently. The same flag worked through
    POST /settings/themes. One flag, two surfaces, one of them dead.

    The decision: /settings/themes owns it. This pins BOTH halves — the owner works, and the
    other surface refuses out loud rather than silently.
    """
    c = _client()

    rejected = c.post("/settings", json={"cluster_enabled": True}).json()
    assert rejected["ok"] is False, "the non-owning surface must not answer ok"
    assert rejected["rejected"] == ["cluster_enabled"]
    assert _disk(cfg_file).get("cluster_enabled") is not True

    owned = c.post("/settings/themes", json={"key": "clustering", "enabled": True}).json()
    assert owned["ok"] is True
    assert owned["enabled"] is True, "the owning surface must report the EFFECTIVE state"
    assert _disk(cfg_file).get("cluster_enabled") is True

    off = c.post("/settings/themes", json={"key": "clustering", "enabled": False}).json()
    assert off["ok"] is True and off["enabled"] is False
    assert _disk(cfg_file).get("cluster_enabled") is False
