# Security Policy

## Scope

Layla is a **local-first** application. By default it binds only to `127.0.0.1` and has no shared infrastructure, no cloud accounts, and no user data sent externally. The attack surface is limited to your own machine.

Areas to be aware of:

- **Code execution**: `run_python` and `shell` tools execute code on your machine. They are approval-gated by default (`allow_run` must be explicitly set to `true`).
- **File writes**: `write_file`, `apply_patch` require `allow_write: true` AND approval-gate confirmation.
- **HTTP fetch**: `fetch_url` respects `robots.txt` and an operator-configured allowlist.
- **Remote mode**: If `remote_enabled: true` in config, the server is protected by a Bearer token. Default is disabled.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue:

1. Open a [GitHub private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) in this repository.
2. Include: a description of the issue, steps to reproduce, and potential impact.
3. We will acknowledge within 72 hours and aim to resolve critical issues within 14 days.

## Supported versions

Only the latest `main` branch is actively maintained and receives security fixes.
