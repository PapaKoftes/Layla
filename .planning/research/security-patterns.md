# Security Patterns: Tunnel Exposure & Agent Tool Sandboxing

**Researched:** 2026-06-29
**Scope:** Validate Layla's post-remediation security model (loopback-trust auth-bypass class just eliminated) against industry best practice for (a) exposing a self-hosted server through a tunnel/reverse proxy and (b) sandboxing an LLM agent's tool execution. Identify what is still missing.
**Confidence:** HIGH for proxy-header / sandboxing patterns (canonical sources + framework source code read directly); MEDIUM for ranking of the backlog (engineering judgment over a local-first single-operator threat model).

---

## Layla's current model (ground truth, from source)

Read directly so recommendations are concrete, not generic:

- **Forwarded-header parsing** — `agent/services/auth.py::real_client_ip()`. Honors forwarded headers **only when the socket peer is loopback** (the tunnel terminus). Header precedence: `cf-connecting-ip`, `true-client-ip`, `x-real-ip`, `x-forwarded-for`, `forwarded`. For XFF it takes `v.split(",")[0]` — the **leftmost** entry. `is_direct_local()` returns true only for a direct loopback request with no forwarding header; this is what closed the loopback-trust bypass.
- **Auth gate** — `agent/main.py::remote_auth_middleware`. When `remote_enabled`: direct-loopback is exempt unless `remote_require_auth_always`; everything else needs a Bearer token via `services/auth.py::check_auth` → `services/tunnel_auth.py::check_remote_access` (hashed token + IP allowlist + TTL). Then an endpoint allowlist and per-IP rate limit.
- **Token storage** — `tunnel_auth.py`: token is `secrets.token_urlsafe(32)`, stored as **SHA-256 hash** (`tunnel_token_hash`), compared with `hmac.compare_digest`. Legacy plaintext `remote_api_key` still accepted with a deprecation warning.
- **Tool sandbox** — `agent/layla/tools/sandbox_core.py`: path jail via `Path.relative_to(sandbox_root)` (`inside_sandbox`), shell blocklist (`rm`, `powershell`, `cmd`, …), network-tool denylist (`curl`, `ssh`, …), read-before-write mtime freshness check. `docker_run` (`impl/system.py`) blocks `--privileged`, host mounts/devices, `--cap-add`, `--security-opt`, host namespaces.
- **Approvals** — `runtime_safety.py`: `SAFE_TOOLS` auto-allowed; `DANGEROUS_TOOLS` require an entry in `approvals.json` unless `admin_mode`. Execution logged to `.governance/execution_log.json`.
- **Secrets at rest** — `runtime_config.json` holds `*_api_key`, `*_token`, `tunnel_token_hash` etc. **in plaintext** (see the ~40 secret-shaped keys in `runtime_safety.py` defaults: `firecrawl_api_key`, `discord_bot_token`, `litellm_api_keys`, `slack_*`, `spotify_*`, `qdrant_api_key`, …).

The remediation is sound. The findings below are about hardening what remains.

---

## (a) Trusted-proxy / forwarded-header handling

### The canonical rule: rightmost-trusted-hop, not leftmost

The authoritative reference is adam-p's "The perils of the 'real' client IP." Core principle, **counterintuitive but correct**:

> The leftmost IP in XFF is closest to the client and "most real" but is **trivially spoofable**. For any security decision use the **rightmost-ish** IP — the one your trusted proxy added.

Algorithm (also how frameworks implement it):
1. Merge **all** `X-Forwarded-For` header instances into one list (multiple instances can exist; attackers exploit inconsistent merging).
2. Walk the list **right-to-left**. Skip entries whose IP is a **known trusted proxy** (allowlist of proxy IPs/CIDRs). The first entry that is *not* a trusted proxy is the real client.
3. Validate each entry is a syntactically valid IP; reject private ranges unless on an internal network. Never store an unvalidated string as an "IP" (memory-exhaustion vector).

**Provider-set single-value headers (`CF-Connecting-IP`, `True-Client-IP`) are safer than XFF** *because the provider overwrites them* and a client cannot forge them — **but only if your edge actually sets them.** Cloudflare and nginx do; Fastly does not by default. The trust precondition is "the request genuinely came from that provider's edge."

Security consequences of getting this wrong (all confirmed across sources): **rate-limit bypass** (spoof a new leftmost IP per request), **access-control bypass / allowlist poisoning**, and **framing a victim** by putting their IP in XFF.

### How the frameworks do it

**uvicorn `ProxyHeadersMiddleware`** (read the source at `Kludex/uvicorn/.../proxy_headers.py`):
- Gated by `forwarded_allow_ips` / `--forwarded-allow-ips` (env `FORWARDED_ALLOW_IPS`, default `127.0.0.1`; `*` = trust everything — dangerous).
- Only processes forwarded headers when the **socket peer** is in the trusted set.
- Then derives the client by iterating XFF in **reverse**, returning the first host **not** in `trusted_hosts` — i.e. rightmost-untrusted. Quote: `for host_port in reversed(x_forwarded_for_hosts): ... if host not in self: return host, port`.
- **Known limitation (issue #1068):** if *all* hops are trusted, it falls back to the **leftmost** entry (`x_forwarded_for_hosts[0]`) — which is spoofable. Don't put the real client's network in `trusted_hosts`.

**FastAPI/Starlette:** ignore forwarded headers by default (safe). You opt in via uvicorn's middleware or `--proxy-headers` + `--forwarded-allow-ips`. FastAPI docs ("Behind a Proxy") explicitly frame this as a security choice: only trust specific proxies.

**nginx:** `real_ip_recursive on` + `set_real_ip_from <trusted-cidr>` strips forged IPs added *before* the trusted proxies — the same rightmost-trusted-hop logic, configured declaratively.

### Where Layla stands vs. this

Layla's `real_client_ip` is **already ahead of the naive case**: it refuses forwarded headers on non-loopback sockets, and prefers provider-set `cf-connecting-ip`/`true-client-ip` over XFF. That correctly closes the LAN-attacker-spoofs-XFF vector for the common cloudflared/ngrok-on-loopback topology.

**Two residual gaps:**
1. **XFF leftmost.** When it *does* fall through to `x-forwarded-for`, it takes `split(",")[0]` (leftmost = spoofable). If a request reaches Layla via `cloudflared → nginx → Layla`, or any chain that appends rather than overwrites XFF, a remote client can prepend a fake IP and poison the IP allowlist / rate-limiter / audit log. The fix is the rightmost-trusted-hop walk with a configurable trusted-proxy/hop count.
2. **Trust is "socket is loopback," not "request came from *my* cloudflared."** Anyone with local code execution (or another loopback-bound service) can hit Layla with a forged `Cf-Connecting-Ip` and be treated as an arbitrary remote IP. Lower severity given the single-operator local-first model, but it's the same class that was just remediated, one layer in. Defense-in-depth: Cloudflare Authenticated Origin Pulls (mTLS client cert from CF edge) or a tunnel-injected shared-secret header validated before trusting CF headers.

---

## (b) Auth for self-hosted AI behind a tunnel

The dominant lesson from the self-hosted-AI ecosystem is exactly the class Layla just fixed: **"trust localhost" is lethal once a tunnel is in front of you.**

- **Ollama** is the cautionary tale. It ships with **no auth** and binds `:11434`; a SentinelOne/Censys scan (293 days) found **~175,000 exposed hosts across 130 countries**, many serving models with no auth/firewall. Anyone reaching the port can run prompts, pull private models, and burn GPU. Ollama's own guidance: it has no built-in auth, so **put a reverse proxy (nginx basic-auth / OAuth) in front**, or keep it loopback-only and reach it via **Tailscale**. The mechanism that made these exposable is precisely "the app trusts whatever connects locally" + a forwarder that lands on loopback.
- **Open WebUI / LibreChat** do it right: real session/JWT auth, accounts, RBAC — they never treat the network position as identity. That's the bar.
- **Tunnel-edge auth is the strongest single control.** Both ngrok (Traffic Policy: `basic-auth`, `oauth`, IP restrictions, all over TLS) and Cloudflare (Access / Authenticated Origin Pulls) can require identity **before traffic reaches the app**. Cloudflare Tunnel additionally makes the origin **outbound-only with no public IP**, eliminating the exposed-port attack surface entirely.
- **OWASP-style principle:** authentication must be **complete mediation** — enforced independently of any "the caller is local" heuristic. Layla's `remote_require_auth_always` flag is the right escape hatch; the safer posture is to make auth-always the default once `remote_enabled` and document tunnel-edge auth as the primary control.

**Verdict for Layla:** the token model (hashed, constant-time, IP allowlist, TTL) is solid and on par with what a self-hosted app should ship. The improvements are: (1) make remote auth mandatory (not loopback-exempt) by default when exposed, (2) recommend/auto-detect a tunnel-edge auth layer, (3) finish killing the legacy plaintext `remote_api_key`.

---

## (c) Agent tool sandboxing

The ecosystem has converged on a **defense-in-depth ladder**, strongest last. OWASP **LLM06:2025 Excessive Agency** is the framing risk: damaging actions from "unexpected, ambiguous or manipulated" LLM output. Its three root causes map cleanly to controls — excessive *functionality* (tool minimization), excessive *permissions* (least privilege), excessive *autonomy* (human-in-the-loop). The interpreter-tool attack (agent tricked into running attacker code) carries an **OWASP AIVSS / CVSS v4.0 base 9.4**.

How the reference agents sandbox execution:

| Project | Mechanism | Notes |
|---|---|---|
| **OpenHands** | Per-run **Docker container** (DockerWorkspace); also E2B / Daytona / remote. Filesystem isolation, network policy, CPU/mem/disk limits. | Treats *every run* as untrusted code. Explicit: container isolation "is not magic" — use microVM/hardened K8s for high-risk. |
| **Open Interpreter** | Runs in a separate **process**; opt-in **Docker** or **E2B** for true isolation. | Docs state plainly: *no local Python sandbox is ever fully secure*; robust isolation requires Docker/E2B. |
| **smolagents** | **AST-walking `LocalPythonExecutor`** (not vanilla `exec`): import **allowlist** (submodules too), capped operation count (anti-infinite-loop), no arbitrary attribute access. Plus **E2B** and **Pyodide/Deno WebAssembly** executors for real isolation. | The AST interpreter is the closest analog to Layla's blocklist approach — but it's **allowlist-by-default**, the inverse of a blocklist. |
| **E2B / Firecracker** | **microVM** per execution, ephemeral. | The gold standard for "run untrusted LLM code." |
| **Claude Code / Codex-style** | Path-scoped FS + **per-action approval gates** + command allow/deny policy. | This is the tier Layla already targets. |

### Layla vs. the ladder

Layla sits at the **path-jail + command-policy + approval-gate** tier — the same tier as Claude Code, and appropriate for local-first single-operator use. Its `docker_run` flag-blocking is genuinely good (blocks the standard escape flags). **What it's missing relative to best practice:**

1. **Blocklist, not allowlist, for shell** (`_SHELL_BLOCKLIST`/`_SHELL_NETWORK_DENYLIST`). Every source that built a real sandbox (smolagents most explicitly) converged on **deny-by-default + allowlist**. A blocklist is bypassable: synonyms, absolute paths, shell features (`$(...)`, backticks — Layla only *warns* on these), encodings, busybox applets, new binaries. The shell allowlist exists (`shell_restrict_to_allowlist`) but is **off by default**.
2. **`run_python` / code execution is in-process** (it shares Layla's interpreter and host FS, jailed only by path checks). Per Open Interpreter and smolagents, **no in-process Python sandbox is secure** against a determined/manipulated model. The opt-in subprocess runner and OS rlimits/cgroups/Windows-job-object knobs exist in config but default off — so the strong isolation tier is present but not engaged.
3. **No mandatory ephemeral container / microVM tier** for genuinely untrusted execution. For a tool that can be exposed via a tunnel, "run agent-generated code in Docker/E2B" should be an available (ideally default-on-when-remote) mode, matching OpenHands/Open Interpreter.
4. **No network egress jail for the agent's own process.** The shell *denylist* blocks `curl`/`ssh`, but the in-process Python and tools can open sockets freely. Sandboxes enforce egress at the boundary (container netns / firewall), "independently of the agent's decisions."
5. **Complete-mediation gap:** approvals are a per-tool boolean in `approvals.json`; once `write_file`/`shell` is approved it stays approved (subject to `admin_mode`). OWASP LLM06 wants high-impact actions gated **per-invocation** with least privilege, not a sticky global grant.

None of these contradict the local-first model — they're the difference between "safe for a trusted operator on their own box" (true today) and "safe to expose through a tunnel and run untrusted/prompt-injected work" (the stated direction).

---

## (d) Secrets at rest

Layla stores all provider keys/tokens in **plaintext `runtime_config.json`**. Best practice, consistently across sources:

- **Never plaintext, never in VCS.** `.gitignore` is necessary but not sufficient — the file is readable by any process/user on the box and leaks via backups, screen-shares, support bundles, and the `/settings` API surface.
- **Encrypt at rest** (AES-256) or, better for a desktop app, use the **OS credential store**: Windows DPAPI / Credential Manager, macOS Keychain, Linux Secret Service — via Python **`keyring`**. This binds decryption to the OS user and avoids inventing crypto.
- **Separate config from secrets:** keep non-secret config in `runtime_config.json`; resolve secrets at load time from keyring (or env var → keyring → encrypted file fallback). Centralized stores (Vault, Infisical) are overkill for a single-operator desktop app; `keyring` is the right-sized control.
- **Rotation + least privilege + don't log secrets.** Layla already hashes `tunnel_token_hash` (good) and truncates token IDs in audit (good) — extend that discipline to *all* provider secrets.

The pragmatic, high-leverage step: a thin secrets layer that reads `keyring` first and falls back to the existing plaintext key (so nothing breaks), plus stop persisting newly-entered secrets to `runtime_config.json` once keyring is available.

---

## Security hardening backlog for Layla (ranked by value)

Ranked by (risk reduction × likelihood the exposed-tunnel path is used) ÷ effort. Top items are cheap and close real, current gaps.

### P0 — close the residual forwarded-header gap (cheap, same class as the bug just fixed)
1. **Rightmost-trusted-hop XFF parsing.** Replace `x-forwarded-for: split(",")[0]` in `real_client_ip` with a right-to-left walk that skips configured trusted-proxy IPs/CIDRs (new `tunnel_trusted_proxies` / `tunnel_proxy_hops` config). Until configured, treat XFF as **untrusted** and prefer the provider header or the socket peer. *Effort: low. Kills allowlist/rate-limit/audit poisoning when a non-overwriting proxy is chained.*
2. **Default `remote_require_auth_always = true` when `remote_enabled`.** Loopback-exempt-by-default re-creates the just-fixed class for any header-stripping forwarder (`ssh -R`, socat, nginx stream). Make auth mandatory once exposed; keep an explicit opt-out. *Effort: trivial.*
3. **Validate & normalize every derived IP** (reject non-parseable, optionally reject private ranges for remote) before it touches allowlist/rate-limit/audit. *Effort: trivial; closes the memory/garbage-IP vector.*

### P1 — finish the auth & secrets story
4. **Secrets via OS keyring.** Add a `keyring`-backed resolver (`keyring → env → plaintext fallback`); stop writing new secrets to `runtime_config.json`. Migrate `tunnel_token_hash`, `*_api_key`, `*_token`, `litellm_api_keys`. *Effort: medium. Removes plaintext-at-rest for all providers.*
5. **Remove/deprecate-hard the legacy plaintext `remote_api_key`.** It's a second, weaker auth path; gate it behind an explicit `allow_legacy_remote_api_key` and warn loudly. *Effort: low.*
6. **Document + optionally automate tunnel-edge auth** (Cloudflare Access / Authenticated Origin Pulls, ngrok Traffic Policy basic-auth/oauth) as the *primary* control, with app-token as defense-in-depth. Optionally validate a tunnel-injected shared-secret header before trusting `Cf-Connecting-Ip`. *Effort: low–medium (mostly docs + one header check).*

### P2 — raise the sandbox tier toward "safe to expose"
7. **Shell deny-by-default + allowlist on by default when remote.** Flip `shell_restrict_to_allowlist` to default-on under `remote_enabled`; treat `$(...)`/backticks as **block**, not warn. *Effort: low–medium. Converts the bypassable blocklist into the converged allowlist model.*
8. **Default agent-generated code execution to a subprocess with rlimits/cgroups/Windows-job-object** (the knobs already exist, just off). Engage them automatically under `remote_enabled` or an `untrusted_execution` mode. *Effort: medium; the plumbing is already present.*
9. **Optional ephemeral-container / E2B execution mode** for `run_python`/`shell`, default-on when exposed — matching OpenHands/Open Interpreter. *Effort: high; highest isolation ceiling.*
10. **Per-invocation approval for high-impact tools** (network/file-write/exec) instead of a sticky global grant, with least-privilege scoping — direct LLM06 mitigation. *Effort: medium.*
11. **Egress control for the agent process** (container netns or host firewall rules) so blocking `curl` at the shell isn't defeated by an in-process socket. *Effort: medium–high.*

### P3 — operational hardening
12. **Audit-by-default when remote** (`tunnel_audit_enabled` true with `remote_enabled`) and alert on abnormal tool-invocation patterns (OWASP LLM06 monitoring). *Effort: low.*
13. **Bound/rotate audit + execution logs** and ensure no secret material is ever logged. *Effort: low.*

---

## Confidence assessment

| Area | Confidence | Why |
|---|---|---|
| Forwarded-header / trusted-proxy patterns | HIGH | Canonical source (adam-p) + uvicorn middleware source read directly; Cloudflare/ngrok docs. |
| Self-hosted AI auth lessons | HIGH | Ollama exposure data (SentinelOne/Censys), Ollama's own guidance, ngrok/Cloudflare docs. |
| Agent sandboxing ladder | HIGH | OpenHands docs/SDK paper, Open Interpreter docs, smolagents docs, OWASP LLM06:2025. |
| Secrets-at-rest | HIGH | Consistent across security guidance; `keyring`/DPAPI is standard for desktop apps. |
| Backlog ranking | MEDIUM | Risk×effort judgment over Layla's local-first single-operator threat model; reorder if the "expose via tunnel for untrusted work" use case becomes primary. |

## Sources

- adam-p — The perils of the "real" client IP: https://adam-p.ca/blog/2022/03/x-forwarded-for/
- uvicorn ProxyHeadersMiddleware source: https://github.com/Kludex/uvicorn/blob/main/uvicorn/middleware/proxy_headers.py
- uvicorn settings (`forwarded_allow_ips`): https://uvicorn.dev/settings/
- uvicorn issue #1068 (all-trusted-hops fallback): https://github.com/Kludex/uvicorn/issues/1068
- FastAPI — Behind a Proxy: https://fastapi.tiangolo.com/advanced/behind-a-proxy/
- MDN — X-Forwarded-For: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Forwarded-For
- DevSec — Understanding X-Forwarded-For: https://devsec-blog.com/2025/04/understanding-the-x-forwarded-for-http-header-security-risks-and-best-practices/
- Cloudflare — Protect your origin server: https://developers.cloudflare.com/fundamentals/security/protect-your-origin-server/
- Cloudflare — Authenticated Origin Pulls: https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/explanation/
- ngrok — Basic Auth / OAuth Traffic Policy: https://ngrok.com/docs/traffic-policy/actions/basic-auth , https://ngrok.com/docs/traffic-policy/actions/oauth
- Ollama exposure (SentinelOne/Censys via DEV): https://dev.to/sharon_42e16b8da44dabde6d/ollama-exposed-unauthenticated-access-vulnerability-could-leak-your-llm-models-1dpo
- Ollama unauth misconfig (NSFOCUS / CNVD-2025-04094): https://nsfocusglobal.com/ollama-unauthorized-access-vulnerability-due-to-misconfiguration-cnvd-2025-04094/
- OpenHands — Docker Sandbox: https://docs.openhands.dev/sdk/guides/agent-server/docker-sandbox
- OpenHands SDK paper: https://arxiv.org/html/2511.03690v1
- Open Interpreter — Isolation: https://docs.openinterpreter.com/safety/isolation
- smolagents — Secure code execution: https://huggingface.co/docs/smolagents/en/tutorials/secure_code_execution
- OWASP LLM06:2025 Excessive Agency: https://genai.owasp.org/llmrisk/llm062025-excessive-agency/
- Strapi — How to Store API Keys Securely: https://strapi.io/blog/how-to-store-API-keys-securely
- GitGuardian — Secrets/API management best practices: https://blog.gitguardian.com/secrets-api-management/
