# Phase 1 Context: Security finish

**Requirements:** REQ-10, REQ-11, REQ-12
**Goal:** A remote (tunnel) caller cannot poison the allowlist/rate-limiter/audit via forged forwarding headers; cannot reach an unauthenticated surface when exposed; provider secrets are not plaintext on disk.
**Grounding:** `.planning/research/security-patterns.md` (P0–P3 backlog), `.planning/codebase/` map. Builds on the already-remediated trust boundary (REQ-01).

## Locked decisions (substitute for discuss-phase)

### REQ-10 — Rightmost-trusted-hop forwarded-IP derivation
- **File:** `agent/services/auth.py::real_client_ip`. Current bug: on fall-through to `X-Forwarded-For` it takes the **leftmost** entry (`split(",")[0]`), which is client-spoofable when headers are appended (cloudflared → nginx → Layla).
- **Decision:** implement the canonical **rightmost-trusted-hop** walk — merge all forwarding-header entries left→right into a hop list, then iterate **right→left** skipping any IP that matches a configured trusted proxy; the first non-trusted IP is the real client. Mirror uvicorn `ProxyHeadersMiddleware` semantics.
- **New config:** `tunnel_trusted_proxies` (list of IPs/CIDRs; default `[]`). When empty, do **not** trust XFF at all — fall back to the socket peer (current safe behavior preserved). Keep the existing "only honor forwarding headers when the socket is loopback" guard and the `Cf-Connecting-Ip`/`True-Client-Ip` preference.
- **Validation:** normalize/parse every derived IP via `ipaddress` before it reaches allowlist / rate-limit / audit; reject unparseable.

### REQ-11 — Auth-required-when-exposed by default
- **Decision:** when `remote_enabled` is true, `remote_require_auth_always` is treated as **on unless explicitly set false** (the loopback exemption becomes an explicit opt-out, not the default). When `remote_enabled` is false (local-only), behavior is unchanged (loopback exempt).
- **Files:** the two `main.py` middlewares + `routers/ws.py` exemption condition; resolve the effective flag in one helper (e.g. `runtime_safety` or `services/auth`) so all three sites agree. Do not break local-only users.

### REQ-12 — Secrets via OS keyring
- **Decision:** add `agent/services/secret_store.py` — a resolver using the `keyring` package (DPAPI / macOS Keychain / Secret Service) with fallback order **keyring → env var → `runtime_config.json` (legacy/plaintext)**. On **save**, write secret-typed keys to the keyring and do NOT persist them to `runtime_config.json` (store a sentinel/marker instead). On **read**, resolve through the chain. Reuse the existing secret-key detection (`services/secret_filter.is_secret_key`) to decide which keys are secrets.
- **Keys covered:** `tunnel_token_hash`, `*_api_key`, `*_token`, `*_secret`, `litellm_api_keys`.
- **Dependency:** add `keyring` to the appropriate extra; degrade gracefully (fallback to env/plaintext) if the backend is unavailable (headless Linux without Secret Service).

## Constraints / non-goals
- **No regressions for local-only users** (`remote_enabled=false` path must be untouched in behavior).
- Pure-stdlib-testable where possible (the forwarded-hop logic and the secret-store resolver are testable on 3.14 with fakes; `keyring` calls mocked).
- Migration: existing plaintext secrets in `runtime_config.json` keep working (read fallback); offer a one-time migration to keyring but don't force it.
- Out of scope this phase: out-of-process/container tool sandboxing (later hardening tier).

## Success criteria (from ROADMAP)
1. `real_client_ip` uses rightmost-trusted-hop over `tunnel_trusted_proxies`; a forged prepended XFF cannot become a trusted/allowlisted IP.
2. `remote_require_auth_always` defaults on when exposed; loopback exemption is an explicit opt-out.
3. Secrets resolve from keyring (env→plaintext fallback); new secrets not written to `runtime_config.json`.
4. Tests: forged XFF/Cf-Connecting-Ip from a non-trusted hop does not change the derived client IP used for allowlist/rate-limit/audit; keyring resolver chain; auth-when-exposed default.
