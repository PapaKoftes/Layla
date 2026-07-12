"""BL-239: plugin SDK — scaffold, validate, version pinning."""
from __future__ import annotations

from services.skills import plugin_sdk as sdk


def test_plugin_slug():
    assert sdk.plugin_slug("My Cool Plugin!") == "my_cool_plugin"
    assert sdk.plugin_slug("") == "plugin"


def test_validate_requires_name_and_version():
    r = sdk.validate_manifest({})
    assert not r["ok"]
    assert any("name" in e for e in r["errors"])
    assert any("version" in e for e in r["errors"])


def test_validate_rejects_non_semver():
    r = sdk.validate_manifest({"name": "x", "version": "v1", "skills": [1]})
    assert not r["ok"] and any("semver" in e for e in r["errors"])


def test_version_pin_satisfied():
    r = sdk.validate_manifest(
        {"name": "x", "version": "0.1.0", "requires": {"layla_api": ">=1.0"}, "tools": [1]},
        current_api="1.0",
    )
    assert r["ok"] and r["errors"] == []


def test_version_pin_unsatisfied():
    r = sdk.validate_manifest(
        {"name": "x", "version": "1.0.0", "requires": {"layla_api": ">=2.0"}, "tools": [1]},
        current_api="1.0",
    )
    assert not r["ok"] and any("layla_api" in e for e in r["errors"])


def test_missing_pin_is_warning_not_error():
    r = sdk.validate_manifest({"name": "x", "version": "0.1.0", "skills": [1]})
    assert r["ok"] and any("layla_api" in w for w in r["warnings"])


def test_api_satisfied_operators():
    assert sdk._api_satisfied(">=1.0", "1.0")
    assert sdk._api_satisfied(">=1.0", "1.5")
    assert not sdk._api_satisfied(">=1.5", "1.0")
    assert sdk._api_satisfied("==1.0", "1.0")
    assert not sdk._api_satisfied("<1.0", "1.0")


def test_scaffold_builtin(tmp_path):
    r = sdk.scaffold_plugin("Test Plugin", tmp_path, description="d", author="me", use_cookiecutter=False)
    assert r["ok"] and r["via"] == "builtin"
    root = tmp_path / "test_plugin"
    manifest = (root / "plugin.yaml").read_text(encoding="utf-8")
    assert "name: Test Plugin" in manifest
    assert "version: 0.1.0" in manifest
    assert 'layla_api: ">=1.0"' in manifest
    assert (root / "README.md").exists()
    # the generated manifest passes validation (needs a declared skill/tool)
    import yaml
    parsed = yaml.safe_load(manifest)
    assert sdk.validate_manifest(parsed)["ok"]


def test_scaffold_description_cannot_inject_manifest_keys(tmp_path):
    """Audit #5: a newline+YAML in `description` must NOT become a top-level key.

    Before the fix the manifest was f-string-spliced, so an un-indented
    `capabilities:` block in the description was parsed by yaml.safe_load as a
    real top-level key and load_plugins() would register the malicious impl.
    """
    evil = "x\ncapabilities:\n  - capability: vector_search\n    id: evil\n    module_path: some_module"
    r = sdk.scaffold_plugin("p", tmp_path, description=evil, use_cookiecutter=False)
    assert r["ok"]
    manifest = (tmp_path / "p" / "plugin.yaml").read_text(encoding="utf-8")

    import yaml
    parsed = yaml.safe_load(manifest)
    # The injected key must not have escaped into the manifest top level.
    assert "capabilities" not in parsed
    # The full evil string round-trips as the single `description` scalar value.
    assert parsed["description"] == evil


def test_scaffold_author_cannot_inject_manifest_keys(tmp_path):
    evil = "me\nskills:\n  - name: pwn\n    tools: [shell]"
    r = sdk.scaffold_plugin("q", tmp_path, author=evil, use_cookiecutter=False)
    assert r["ok"]
    manifest = (tmp_path / "q" / "plugin.yaml").read_text(encoding="utf-8")

    import yaml
    parsed = yaml.safe_load(manifest)
    assert parsed["author"] == evil
    # The legitimate scaffold skill is the only one; the injected `pwn` skill
    # must not have been parsed as a real manifest skill.
    skill_names = [s.get("name") for s in (parsed.get("skills") or [])]
    assert "pwn" not in skill_names


def test_scaffold_refuses_nonempty(tmp_path):
    (tmp_path / "dup").mkdir()
    (tmp_path / "dup" / "x").write_text("x", encoding="utf-8")
    r = sdk.scaffold_plugin("dup", tmp_path, use_cookiecutter=False)
    assert not r["ok"] and "already exists" in r["error"]
