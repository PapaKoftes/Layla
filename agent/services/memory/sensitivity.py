"""Cheap, deterministic sensitivity classifier for memory content (PLAN ITEM 20 / BL-020).

The encryption-at-rest cipher (`services.memory.memory_encryption`) only fires for content
whose ``privacy_level == "sensitive"``. Historically *nothing* set that flag on the production
write path, so the cipher never engaged and every "remember this" landed in the DB as plaintext.
This module is the missing piece: a keyword/regex classifier that tags a learning (or entity)
as ``"sensitive"`` vs ``"public"`` so the write path can mark it for encryption.

Design principles:
  • **No model, no I/O, no config** — pure regex over the text. Safe to call on every write.
  • **Conservative by construction** — a false positive only *over-encrypts* (the row becomes
    keyword-unsearchable but is still readable by id/recency); a false negative leaks a secret to
    disk in plaintext. So when in doubt we classify ``sensitive``.
  • **Deterministic** — the same text always yields the same label; easy to test and audit.

What counts as sensitive (any single category match → ``sensitive``):
  credentials / secrets / API keys / tokens / passwords, health / medical, financial / banking,
  government IDs (SSN, passport, driver's licence, tax id), and direct PII (email, phone,
  postal address, date of birth).

Public API:
  ``classify(text, entity_type=None) -> "sensitive" | "public"``
  ``is_sensitive(text, entity_type=None) -> bool``
  ``explain(text, entity_type=None) -> list[str]``  (matched category labels; for tests/audits)
"""
from __future__ import annotations

import re

# ── entity-type hook ─────────────────────────────────────────────────────────
# Content is the primary signal, but some entity *types* are sensitive regardless of wording.
# The current EntityType enum has none of these, so this is forward-compatible: if a caller ever
# tags an entity with one of these types, it is treated as sensitive without inspecting the text.
_SENSITIVE_ENTITY_TYPES = frozenset({
    "credential", "credentials", "secret", "password", "api_key", "apikey", "token",
    "medical", "health", "financial", "government_id", "gov_id", "pii",
})


# ── keyword categories ───────────────────────────────────────────────────────
# Each entry is an alternation of phrases matched case-insensitively with word boundaries
# (``_kw``). Multi-word phrases are fine — ``\b`` anchors the whole phrase. Ordered roughly by
# how strong/unambiguous the signal is; the label is returned by ``explain()`` for auditability.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "credential": (
        "password", "passwords", "passwd", "passphrase", "passcode", "pass code",
        "secret key", "secret token", "client secret", "api key", "api-key", "apikey",
        "access token", "auth token", "refresh token", "bearer token", "session token",
        "private key", "ssh key", "credential", "credentials", "login details",
        "one[- ]time code", "otp", "mfa code", "2fa", "two[- ]factor", "verification code",
        "security code", "activation code", "gate code", "door code", "pin code",
        "pin number", "seed phrase", "recovery phrase", "mnemonic", "cvv", "cvc",
        "secret",  # broad but intentional: over-encrypting a "secret" is the safe failure
    ),
    "health": (
        "diagnos", "medical condition", "medical history", "medical record", "prescription",
        "prescribed", "medication", "mental health", "depression", "anxiety", "bipolar",
        "schizophreni", "\\bhiv\\b", "\\baids\\b", "cancer", "tumou?r", "chemotherapy",
        "pregnan", "miscarriage", "surgery", "therapist", "therapy", "psychiatr",
        "disorder", "disease", "illness", "symptom", "disability", "addiction", "rehab",
        "blood pressure", "blood type",
    ),
    "financial": (
        "bank account", "account number", "routing number", "sort code", "iban",
        "swift code", "\\bbic\\b", "credit card", "debit card", "card number", "cvv",
        "salary", "net worth", "mortgage", "loan balance", "wire transfer", "paycheck",
        "crypto wallet", "wallet address", "seed phrase",
    ),
    "government_id": (
        "social security", "\\bssn\\b", "passport number", "passport no", "passport #",
        "driver'?s licen[cs]e", "driving licen[cs]e", "national id", "national insurance",
        "\\bnino\\b", "tax id", "\\btin\\b", "\\bein\\b", "aadhaar", "medicare number",
    ),
    "pii": (
        "home address", "mailing address", "street address", "postal address",
        "date of birth", "\\bdob\\b", "maiden name", "mother'?s maiden",
    ),
}

_KW_RES: dict[str, re.Pattern] = {
    label: re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)
    for label, phrases in _KEYWORDS.items()
}


# ── structured (regex-shaped) detectors ──────────────────────────────────────
# These catch the *value* itself even when no keyword frames it (e.g. a raw SSN pasted alone).
_STRUCTURED: dict[str, re.Pattern] = {
    # US SSN: 123-45-6789 (also space-separated). Kept strict to avoid matching phone/zip runs.
    "government_id": re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
    # Email address.
    "pii_email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    # Phone: optional +cc, area code, 7 subscriber digits with common separators.
    "pii_phone": re.compile(
        r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)"
    ),
    # Postal street address: number + words + a street-type suffix.
    "pii_address": re.compile(
        r"\b\d{1,6}\s+(?:[A-Za-z0-9.'\-]+\s+){0,4}"
        r"(?:street|st|avenue|ave|road|rd|lane|ln|boulevard|blvd|drive|dr|court|ct|"
        r"way|place|pl|terrace|ter|circle|cir|highway|hwy)\b",
        re.IGNORECASE,
    ),
    # Payment card: 13-19 digits, optionally grouped by spaces/dashes.
    "financial_card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    # IBAN: 2 letters + 2 check digits + up to 30 alnum.
    "financial_iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
}

# High-signal secret/token shapes (well-known key prefixes + PEM + JWT). A match here is almost
# never a false positive, so these are listed separately from the broad keyword set.
_SECRET_SHAPES: tuple[re.Pattern, ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                     # OpenAI-style
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),           # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                 # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
)


def explain(text, *, entity_type=None) -> list[str]:
    """Return the list of sensitivity category labels that *text* matches (empty → public).

    Useful in tests and audits to see *why* something was classified sensitive.
    """
    labels: list[str] = []
    et = str(entity_type or "").strip().lower()
    if et and et in _SENSITIVE_ENTITY_TYPES:
        labels.append(f"entity_type:{et}")
    if not isinstance(text, str) or not text:
        return labels
    for label, rx in _KW_RES.items():
        if rx.search(text):
            labels.append(label)
    for label, rx in _STRUCTURED.items():
        if rx.search(text):
            labels.append(label)
    for rx in _SECRET_SHAPES:
        if rx.search(text):
            labels.append("credential_shape")
            break
    # Preserve first-seen order without duplicates.
    seen: set[str] = set()
    return [x for x in labels if not (x in seen or seen.add(x))]


def is_sensitive(text, *, entity_type=None) -> bool:
    """True if *text* (or *entity_type*) matches any sensitivity category."""
    return bool(explain(text, entity_type=entity_type))


def classify(text, *, entity_type=None) -> str:
    """Return ``"sensitive"`` or ``"public"`` for *text*.

    Conservative: any single category match yields ``"sensitive"``.
    """
    return "sensitive" if is_sensitive(text, entity_type=entity_type) else "public"
