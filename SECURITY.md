# Security Policy

## Scope

Layla is a **local-first** application. By default it binds only to `127.0.0.1` and has no shared infrastructure, no cloud accounts, and no user data sent externally. The attack surface is limited to your own machine.

Areas to be aware of:

- **Code execution**: `run_python` and `shell` tools execute code on your machine. They are approval-gated by default (`allow_run` must be explicitly set to `true`).
- **File writes**: `write_file`, `apply_patch` require `allow_write: true` AND approval-gate confirmation.
- **HTTP fetch**: `fetch_url` respects `robots.txt` and an operator-configured allowlist.
- **Remote mode**: If `remote_enabled: true` in config, the server is protected by a Bearer token. Default is disabled. A remote caller can **never** self-grant `allow_write`/`allow_run` — the `/v1` endpoint forces both to `false` for any non-loopback caller, and fails **closed** if the trust check errors (regression-tested in `test_v1_rce_guard.py`).

## Content policy & the safety floor (uncensored models)

Layla is designed to run **local, user-chosen models**, and the installer lets you pick **uncensored / minimal-refusal** models (Dolphin, Hermes, Jinx, …). That is a deliberate product choice — Layla is your tool on your machine.

There is exactly **one non-negotiable safety floor**, `services/safety/content_guard.py`, that runs on input and output regardless of the model:

- **Tier 1 (never overridable):** CSAM-adjacent content, weapons-of-mass-destruction *synthesis* instructions, and malware/exploit *generation*. No config flag disables these.
- **Tier 2 (blocked unless `content_guard_age_verified: true`):** explicit self-harm/suicide *instructions*.

The guard is a **deterministic keyword/pattern floor with normalization** (it defeats common leetspeak like `r@ns0mw4re` and self-harm synonyms). It is **not** a complete content-moderation system: heavily letter-spaced obfuscation can still slip it, and it is not a substitute for the model's own alignment. It exists to stop the most clearly-illegal requests, not to censor a jailbroken model's normal range. If you need stricter moderation, keep `content_guard_enabled: true` (the default) and run a model whose alignment you trust.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue:

1. Open a [GitHub private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) in this repository.
2. Include: a description of the issue, steps to reproduce, and potential impact.
3. We will acknowledge within 72 hours and aim to resolve critical issues within 14 days.

## Supported versions

Only the latest `main` branch is actively maintained and receives security fixes.
