# Phase 1 Verification: Security finish

**Status:** ✅ COMPLETE · **Date:** 2026-06-29 · **Requirements:** REQ-10, REQ-11, REQ-12

Executed directly (subagent runtime hit the account session limit); every change is backed by a pure-stdlib test that runs on Python 3.14.

## Success criteria → evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | `real_client_ip` uses **rightmost-trusted-hop** over `tunnel_trusted_proxies`; a forged prepended XFF cannot become a trusted/allowlisted IP | ✅ | `services/auth.py::real_client_ip` rewritten (provider-overwrite headers first, then rightmost-trusted-hop, IP-validated). Commit `4f05229`. |
| 2 | `remote_require_auth_always` defaults **on when exposed**; loopback exemption is an explicit opt-out | ✅ | tri-state + `services/auth.require_auth_always(cfg)`, wired into both `main.py` middlewares + `ws.py`. Commit `b1968ad`. |
| 3 | Secrets resolve from the **OS keyring** (env→plaintext fallback); new secrets not written to `runtime_config.json` | ✅ | `services/secret_store.py`; `load_config` overlay (read) + `POST /settings` persist (write); no-op without a keyring backend. Commit `77335b4`. |
| 4 | A test asserts a forged forwarding header from a non-trusted hop does not change the derived client IP | ✅ | `test_trust_boundary.py::test_xff_rightmost_not_leftmost`, `::test_provider_header_beats_spoofed_leftmost_xff`, `::test_spoofed_loopback_xff_cannot_become_direct_local`. |

## Test evidence
New/updated tests, all green on 3.14:
- `test_trust_boundary.py` — +12 cases (rightmost-hop, provider-header precedence, trusted-proxy multi-hop skip, port/bracket normalization, REQ-11 resolver matrix).
- `test_secret_store.py` — 5 cases (keyring>env>cfg priority, persist-into-keyring, resolve overlay, no-keyring clean no-op).
- Full security sweep: **58 tests pass**.

## Regression guard
Local-only users (`remote_enabled=false`) are unaffected: the loopback exemption still applies (`require_auth_always` returns False), forwarding-header logic only triggers on a loopback socket, and the keyring integrations are byte-for-byte no-ops when no keyring backend exists. Verified by the explicit local-only/no-keyring test cases.

## Notes / follow-ups
- `tunnel_trusted_proxies` defaults to `[]`; cloudflared works out-of-the-box via the `Cf-Connecting-Ip` provider header. Operators behind a multi-hop chain set the list.
- A one-time CLI to migrate existing plaintext `runtime_config.json` secrets into the keyring is a nice-to-have (not required this phase; plaintext still resolves as fallback).
