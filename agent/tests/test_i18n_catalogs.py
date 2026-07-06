"""i18n: every locale catalog is valid UTF-8 JSON with the SAME key set as the English
base, all values non-empty strings, and interpolation tokens preserved. Guards against a
translator dropping/renaming a key (which would silently fall back to English)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_LOCALES = Path(__file__).resolve().parent.parent / "ui" / "locales"
_EXPECTED = ["es", "de", "fr", "it", "pt", "ja", "zh", "ar", "ru", "ko"]  # SUPPORTED minus en
_TOKEN = re.compile(r"\{(\w+)\}")


def _flatten(obj, prefix=""):
    out = {}
    for k, v in (obj or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _load(name):
    return _flatten(json.loads((_LOCALES / f"{name}.json").read_text(encoding="utf-8")))


def test_english_base_exists():
    en = _load("en")
    assert len(en) >= 100  # a substantial catalog
    assert all(isinstance(v, str) and v.strip() for v in en.values())


@pytest.mark.parametrize("lang", _EXPECTED)
def test_locale_matches_english_keys(lang):
    en = _load("en")
    loc = _load(lang)
    en_keys, loc_keys = set(en), set(loc)
    assert loc_keys == en_keys, (
        f"{lang}: missing={sorted(en_keys - loc_keys)[:5]} extra={sorted(loc_keys - en_keys)[:5]}"
    )
    # Non-empty strings.
    empty = [k for k, v in loc.items() if not (isinstance(v, str) and v.strip())]
    assert not empty, f"{lang}: empty values for {empty[:5]}"
    # Interpolation tokens preserved per key.
    for k, en_v in en.items():
        assert _TOKEN.findall(en_v) == _TOKEN.findall(loc[k]) or set(_TOKEN.findall(en_v)) == set(_TOKEN.findall(loc[k])), \
            f"{lang}: token mismatch on {k!r}"


def test_all_supported_languages_present():
    for lang in ["en", *_EXPECTED]:
        assert (_LOCALES / f"{lang}.json").exists(), f"missing catalog: {lang}.json"
