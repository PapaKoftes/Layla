"""Tests for skill pack manifest validation."""
import pytest


class TestValidManifest:
    def _valid(self):
        return {
            "name": "test-pack",
            "version": "1.0.0",
            "description": "A test pack",
            "entry_point": "main.py",
            "dependencies": ["requests>=2.28"],
            "permissions": ["read_memory"],
            "tags": ["test"],
        }

    def test_valid_manifest(self):
        from services.skill_manifest import validate_manifest
        errors = validate_manifest(self._valid())
        assert errors == []

    def test_minimal_valid(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert errors == []

    def test_semver_variants(self):
        from services.skill_manifest import validate_manifest
        for v in ("1.0.0", "0.1.0", "2.3", "1.0.0-alpha", "1.0.0-rc.1"):
            m = {"name": "x", "version": v, "description": "d", "entry_point": "e.py"}
            errors = validate_manifest(m)
            assert not errors, f"Version '{v}' should be valid"


class TestMissingFields:
    def test_missing_name(self):
        from services.skill_manifest import validate_manifest
        m = {"version": "1.0", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("name" in e for e in errors)

    def test_empty_name(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "", "version": "1.0", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("name" in e for e in errors)

    def test_missing_version(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("version" in e for e in errors)

    def test_missing_description(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("description" in e for e in errors)

    def test_missing_entry_point(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d"}
        errors = validate_manifest(m)
        assert any("entry_point" in e for e in errors)


class TestNameValidation:
    def test_name_with_spaces(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "bad name", "version": "1.0", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("name" in e for e in errors)

    def test_name_with_special_chars(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "bad@name!", "version": "1.0", "description": "d", "entry_point": "e.py"}
        errors = validate_manifest(m)
        assert any("name" in e for e in errors)

    def test_valid_names(self):
        from services.skill_manifest import validate_manifest
        for name in ("my-pack", "my_pack", "pack123", "A-Z_0"):
            m = {"name": name, "version": "1.0", "description": "d", "entry_point": "e.py"}
            errors = validate_manifest(m)
            assert not any("name" in e for e in errors), f"Name '{name}' should be valid"


class TestEntryPointValidation:
    def test_path_traversal(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "../evil.py"}
        errors = validate_manifest(m)
        assert any("entry_point" in e for e in errors)

    def test_absolute_path(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "/etc/passwd"}
        errors = validate_manifest(m)
        assert any("entry_point" in e for e in errors)


class TestPermissions:
    def test_valid_permissions(self):
        from services.skill_manifest import VALID_PERMISSIONS, validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py",
             "permissions": list(VALID_PERMISSIONS)[:3]}
        errors = validate_manifest(m)
        assert not any("permissions" in e.lower() for e in errors)

    def test_invalid_permission(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py",
             "permissions": ["hack_the_planet"]}
        errors = validate_manifest(m)
        assert any("permission" in e.lower() for e in errors)

    def test_permissions_not_list(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py",
             "permissions": "read_memory"}
        errors = validate_manifest(m)
        assert any("permissions" in e.lower() for e in errors)


class TestDependencies:
    def test_valid_deps(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py",
             "dependencies": ["requests>=2.28", "numpy"]}
        errors = validate_manifest(m)
        assert not any("dependencies" in e.lower() for e in errors)

    def test_deps_not_list(self):
        from services.skill_manifest import validate_manifest
        m = {"name": "x", "version": "1.0", "description": "d", "entry_point": "e.py",
             "dependencies": "requests"}
        errors = validate_manifest(m)
        assert any("dependencies" in e.lower() for e in errors)


class TestGenerateTemplate:
    def test_template_is_valid(self):
        from services.skill_manifest import generate_template, validate_manifest
        tpl = generate_template("my-pack")
        errors = validate_manifest(tpl)
        assert errors == []

    def test_template_has_name(self):
        from services.skill_manifest import generate_template
        tpl = generate_template("custom-name")
        assert tpl["name"] == "custom-name"


class TestFindManifest:
    def test_finds_layla_skill_json(self, tmp_path):
        from services.skill_manifest import find_manifest
        (tmp_path / "layla-skill.json").write_text('{"name": "test"}')
        assert find_manifest(tmp_path) is not None

    def test_finds_manifest_json(self, tmp_path):
        from services.skill_manifest import find_manifest
        (tmp_path / "manifest.json").write_text('{"name": "test"}')
        assert find_manifest(tmp_path) is not None

    def test_prefers_layla_skill_json(self, tmp_path):
        from services.skill_manifest import find_manifest
        (tmp_path / "layla-skill.json").write_text('{"name": "layla"}')
        (tmp_path / "manifest.json").write_text('{"name": "generic"}')
        path = find_manifest(tmp_path)
        assert path.name == "layla-skill.json"

    def test_returns_none_when_missing(self, tmp_path):
        from services.skill_manifest import find_manifest
        assert find_manifest(tmp_path) is None
