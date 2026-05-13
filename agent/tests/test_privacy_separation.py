"""TIER 6 — Privacy separation tests for Entity schema and memory routing."""
import pytest


# ── PrivacyLevel enum ────────────────────────────────────────────────────────


class TestPrivacyLevel:
    def test_enum_values(self):
        from schemas.entity import PrivacyLevel
        assert PrivacyLevel.PUBLIC.value == "public"
        assert PrivacyLevel.WORKSPACE.value == "workspace"
        assert PrivacyLevel.PERSONAL.value == "personal"
        assert PrivacyLevel.SENSITIVE.value == "sensitive"

    def test_rank_order(self):
        from schemas.entity import PrivacyLevel, _PRIVACY_RANK
        assert _PRIVACY_RANK.index(PrivacyLevel.PUBLIC) < _PRIVACY_RANK.index(PrivacyLevel.WORKSPACE)
        assert _PRIVACY_RANK.index(PrivacyLevel.WORKSPACE) < _PRIVACY_RANK.index(PrivacyLevel.PERSONAL)
        assert _PRIVACY_RANK.index(PrivacyLevel.PERSONAL) < _PRIVACY_RANK.index(PrivacyLevel.SENSITIVE)


# ── privacy_allows ───────────────────────────────────────────────────────────


class TestPrivacyAllows:
    def test_public_allows_public(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("public", "public") is True

    def test_public_blocks_workspace(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("workspace", "public") is False

    def test_workspace_allows_public(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("public", "workspace") is True

    def test_workspace_allows_workspace(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("workspace", "workspace") is True

    def test_workspace_blocks_personal(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("personal", "workspace") is False

    def test_personal_allows_up_to_personal(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("public", "personal") is True
        assert privacy_allows("workspace", "personal") is True
        assert privacy_allows("personal", "personal") is True
        assert privacy_allows("sensitive", "personal") is False

    def test_sensitive_allows_everything(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("public", "sensitive") is True
        assert privacy_allows("workspace", "sensitive") is True
        assert privacy_allows("personal", "sensitive") is True
        assert privacy_allows("sensitive", "sensitive") is True

    def test_unknown_level_fails_open(self):
        from schemas.entity import privacy_allows
        assert privacy_allows("unknown_level", "personal") is True
        assert privacy_allows("public", "unknown_max") is True


# ── Entity privacy_level field ───────────────────────────────────────────────


class TestEntityPrivacy:
    def test_default_privacy_public(self):
        from schemas.entity import Entity
        e = Entity(type="concept", canonical_name="test")
        assert e.privacy_level == "public"

    def test_person_defaults_personal(self):
        from schemas.entity import person
        p = person("John Doe")
        assert p.privacy_level == "personal"

    def test_technology_defaults_public(self):
        from schemas.entity import technology
        t = technology("Python")
        assert t.privacy_level == "public"

    def test_concept_defaults_public(self):
        from schemas.entity import concept
        c = concept("clean architecture")
        assert c.privacy_level == "public"

    def test_code_function_defaults_workspace(self):
        from schemas.entity import code_function
        f = code_function("do_thing", module="core")
        assert f.privacy_level == "workspace"

    def test_custom_privacy_on_person(self):
        from schemas.entity import person
        p = person("Public Figure", privacy_level="public")
        assert p.privacy_level == "public"

    def test_privacy_level_in_dict(self):
        from schemas.entity import Entity
        e = Entity(type="concept", canonical_name="test", privacy_level="sensitive")
        d = e.to_dict()
        assert d["privacy_level"] == "sensitive"

    def test_from_dict_preserves_privacy(self):
        from schemas.entity import Entity
        e = Entity.from_dict({
            "type": "concept",
            "canonical_name": "test",
            "privacy_level": "personal",
        })
        assert e.privacy_level == "personal"

    def test_from_dict_defaults_when_missing(self):
        from schemas.entity import Entity
        e = Entity.from_dict({
            "type": "concept",
            "canonical_name": "test",
        })
        assert e.privacy_level == "public"


# ── Entity validation ────────────────────────────────────────────────────────


class TestEntityValidation:
    def test_valid_privacy_levels(self):
        from schemas.entity import Entity, validate_entity
        for level in ("public", "workspace", "personal", "sensitive"):
            e = Entity(type="concept", canonical_name="t", privacy_level=level)
            errors = validate_entity(e)
            assert not errors, f"Level {level} should be valid, got errors: {errors}"

    def test_invalid_privacy_level(self):
        from schemas.entity import Entity, validate_entity
        e = Entity(type="concept", canonical_name="t", privacy_level="top_secret")
        errors = validate_entity(e)
        assert any("privacy_level" in err for err in errors)

    def test_empty_privacy_level_valid(self):
        from schemas.entity import Entity, validate_entity
        e = Entity(type="concept", canonical_name="t", privacy_level="")
        # Empty string is allowed (will be treated as "public" at query time)
        errors = validate_entity(e)
        # No error for empty — it's falsy, skips validation
        assert not any("privacy_level" in err for err in errors)


# ── Config defaults ──────────────────────────────────────────────────────────


class TestPrivacyConfig:
    def test_config_has_privacy_defaults(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "privacy_default_level" in cfg
        assert "privacy_max_retrieval_level" in cfg
        assert cfg["privacy_default_level"] == "public"
        assert cfg["privacy_max_retrieval_level"] == "personal"

    def test_config_has_expertise_boost(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert cfg.get("expertise_domain_boost_enabled") is True


# ── Memory router privacy filtering ─────────────────────────────────────────


class TestMemoryRouterPrivacy:
    def test_max_privacy_from_config(self):
        from services.memory_router import _max_privacy_from_config
        result = _max_privacy_from_config()
        assert result in ("public", "workspace", "personal", "sensitive")

    def test_query_accepts_max_privacy(self):
        from services.memory_router import query
        # Should not error even if no data
        results = query("test", max_privacy="public", limit=5)
        assert isinstance(results, list)
