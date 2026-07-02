# GUI Audit 06 — Settings / Customization · Connectivity · Diagnostics

**Scope:** the full settings surface (dual: flat schema modal + curated right‑panel "Settings" tab),
content policy, permissions/safety knobs, presets, appearance, admin mode, optional‑features
installer, import‑chat; connectivity (pairing/mDNS, remote access, cloudflared tunnel, tailscale,
Syncthing, phone URL, Obsidian); cluster (parked); diagnostics (health/doctor/version/update/metrics/
audit/tools/search‑status).
**Method:** READ‑ONLY. Traced UI (`agent/ui/`) → actions/compat → `fetch()` → FastAPI router →
service module, file:line each hop. The startup/onboarding *flow* is audited elsewhere; here the
settings KEYS are documented for meaning/effect.

> **Live‑UI reality (critical framing).** The running UI is `agent/ui/index.html` (~99 KB) +
> `agent/ui/main.js` (ES‑module entry). The `.planning/GUI-REBUILD.md` "G1 rebuild" so far is a
> **design‑system CSS foundation** (`agent/ui/css/layla-rebuild.css`), **not** a re‑IA. So the
> "8 grouped settings pages" and "Settings › Connectivity" in `GUI-FEATURE-MAP.md` §C are
> **aspirational** — they do not exist as code yet. What exists today is:
> 1. a **flat schema modal** (`#settings-overlay`, index.html:1143) that renders EVERY
>    `EDITABLE_SCHEMA` key as a raw input (`settings-full.js:openSettings`), plus
> 2. a **curated right‑panel "Settings" tab** (`data-rcp="prefs"`, index.html:571–772) with 7
>    accordions (Chat, Permissions&Safety, Workspace, Voice, Research, Integrations, Performance).
> Two different surfaces, partially overlapping, with several dead/mis‑wired controls (below).

---

## PART A — SETTINGS SURFACE

### A0. The two settings surfaces + how a key reaches the server

**Flat schema modal** — `openSettings()` (`settings-full.js:11`) GETs `/settings/schema`
(`settings.py:351` → `config_schema.get_schema_for_api`) + `/settings` (`settings.py:327`), then
renders one row per field by `type` (boolean→checkbox, number→number, else text). `saveSettings()`
(`settings-full.js:62`) re‑fetches the schema, reads each `#cfg_<key>` input, and POSTs the whole
object to `/settings` (`settings.py:378` → `route_helpers.sync_save_settings`).
Backend safeguards on POST /settings:
- **Redaction‑mask drop** (`settings.py:388`): values equal to the `REDACTED` sentinel are removed so
  re‑saving the form never overwrites a stored secret with the mask.
- **Remote‑protected keys** (`settings.py:29` `_REMOTE_PROTECTED_KEYS`): a non‑local caller cannot
  change `sandbox_root, safe_mode, uncensored, remote_enabled, remote_api_key,
  allow_legacy_remote_api_key, remote_rate_limit_per_minute, remote_allowlist, allowed_hosts,
  tunnel_enabled, tunnel_token_hash` (they are silently popped; `settings.py:396` `is_direct_local`).
- **Keyring routing** (`settings.py:407` `persist_secret_keys`): secret‑typed keys go to the OS
  keyring instead of plaintext `runtime_config.json` when a backend exists.
- **GET redaction** (`settings.py:344`): secret keys are returned as `REDACTED` so the modal shows a
  mask, never the real token.

**STATUS: working** (flat modal is the real, complete editor for all keys).

---

### A1. EDITABLE_SCHEMA — every key, grouped, plain‑English meaning + safe range

Source: `agent/config_schema.py:32`. "core"=always shown label group; the modal renders all regardless.

**Model / inference (category `core` + `model`)**
- `model_filename` (str) — GGUF file in `models/`. Changing it swaps the model; **restart required**.
- `models_dir` (str) — where GGUFs live (default repo `models/` or `~/.layla/models/`).
- `sandbox_root` (str) — **the file jail**; Layla can only read/write under this path. Widening it
  widens blast radius → remote‑protected.
- `temperature` (0.01–1.5, def 0.2) — randomness; low=deterministic, high=creative.
- `completion_max_tokens` (64–8192, def 256) — max tokens/response; higher=longer+slower.
- `n_ctx` (256–131072, def 4096) — context window; larger=more RAM.
- `n_gpu_layers` (−1..99, def −1) — layers on GPU; −1=all, 0=CPU‑only.
- `n_batch` (64–2048, def 512) — prompt batch size (throughput vs RAM).
- `n_threads` (1–64, null=auto) — CPU threads.
- `top_p` (0–1, def 0.95), `top_k` (1–100, def 40), `repeat_penalty` (1–2, def 1.1) — sampling knobs.
- `llama_server_url` (str) — external llama.cpp server; **overrides local model** (HTTP backend).

**Memory & retrieval (`memory`)**
- `use_chroma` (bool, def true) — semantic search + learnings via ChromaDB. Off = keyword/SQL only.
- `knowledge_chunks_k` (1–20, def 5) — KB chunks injected per turn.
- `learnings_n` (5–100, def 30) — learnings injected into context.
- `semantic_k` (1–20, def 5) — semantic hits returned.
- `memory_retrieval_min_adjusted_confidence` (0–1, def 0) — drop recalls below this confidence; 0=no filter.
- `project_discovery_auto_inject` (bool, def false) — inject a deterministic workspace scan (filesystem only).
- `learning_quality_gate_enabled` (bool, def true) + `learning_quality_min_score` (0.05–1, def 0.35) —
  reject weak distilled learnings before DB insert.
- `file_checkpoint_enabled` (bool, def true) — snapshot files before write/patch/replace so
  `restore_file_checkpoint` can undo. `file_checkpoint_max_count` (def 200; 0=∞) and
  `file_checkpoint_max_bytes` (~200 MB; 0=∞) bound the store (oldest deleted first).
- `elasticsearch_enabled` (bool, def false) + `elasticsearch_url` + `elasticsearch_index_prefix`
  (def "layla") + `elasticsearch_api_key` — optional ES mirror of learnings; queried via
  `GET /memory/elasticsearch/search`.

**Voice (`voice`)**
- `tts_voice` (enum af_heart/af_sky/am_adam/bf_emma/bm_george) — TTS voice.
- `whisper_model` (tiny/base/small/medium) — STT model; tiny=fastest, medium=best.
- `tts_speed` (0.5–2, def 1.0) — playback speed.

**Scheduler (`scheduler`)**
- `scheduler_study_enabled` (bool, def true) — background study‑plan scheduler on/off.
- `scheduler_interval_minutes` (5–120, def 30) — minutes between runs.
- `scheduler_recent_activity_minutes` (15–480, def 90) — "user is active" window.

**Runtime limits (`limits`)** — effective values also echoed in `/health` `effective_limits`.
- `performance_mode` (auto/low/mid/high, def auto) — CPU/RAM cap tier; `low` tightens ctx + tool budgets.
- `max_tool_calls` (1–50, def 5) — tool calls per normal turn.
- `max_runtime_seconds` (5–3600, def 900) — wall time per turn (align with `ui_agent_stream_timeout_seconds`).
- `tool_call_timeout_seconds` (5–600, def 60) — per‑tool kill timeout.
- `approval_ttl_seconds` (60–86400, def 3600) — pending‑approval expiry.
- `hyde_enabled` (bool, def false) — HyDE retrieval (extra LLM call, better recall).
- `research_max_tool_calls` (1–100, def 20) + `research_max_runtime_seconds` (30–14400, def 1800) —
  research‑mode budgets.
- `llm_serialize_per_workspace` (bool, def false) — per‑workspace run lock for multi‑repo parallelism
  (local generation stays globally serialized regardless).

**Safety & behaviour (`safety`)**
- `safe_mode` (bool, def true) — **require approval for file writes + code execution.** Remote‑protected.
- `uncensored` (bool, def true) — broad uncensored system policy. Remote‑protected.
- `nsfw_allowed` (bool, def true) — allow adult content when combined with `uncensored` (Lilith mode).
- `enable_cot` (bool, def true) — chain‑of‑thought.
- `deliberation_mode` (solo/auto/debate/council/tribunal, def auto) — how many aspects deliberate.
- `enable_self_reflection` (bool, def false) — post‑response self‑critique.
- `direct_feedback_enabled` (bool, def false) — blunt honest critique of *work* (non‑clinical).
- `pin_psychology_framework_excerpt` (bool, def true) — inject a short non‑clinical interaction reminder.
- `custom_system_prefix` (str, multiline) — appended to the system prompt.
- `inline_initiative_enabled` (bool, def false) — after 2+ tool steps, append one next‑step suggestion.
- **Engineering pipeline / governance** (all `safety`): `engineering_pipeline_enabled`,
  `engineering_pipeline_default_mode` (chat/plan/execute), `engineering_pipeline_max_clarify_rounds`
  (1–10, def 3; hint says "reserved"), `engineering_pipeline_validator_max_retries` (0–2),
  `completion_gate_enabled`, `deterministic_tool_routes_enabled`, `planning_strict_mode`,
  `in_loop_plan_governance_enabled` (def true), `in_loop_plan_default_max_retries`,
  `plan_governance_require_nonempty_step_tools`, `plan_governance_reject_auto_filled_tools`,
  `plan_governance_strict_tool_evidence`, `plan_governance_hard_mode` (one‑switch = the last three).
  These gate the structured‑engineering partner + plan approval; meaning is documented in‑hint.
- **Admin mode** (`safety`): `admin_mode` (auto‑approve dangerous tools, still audited),
  `admin_auto_checkpoint` (def true — git commit before mutating tools), `admin_blocklist_override`
  (DANGEROUS — allow shell blocklist bypass).

**Remote (`remote`)** — see Part B.2: `remote_enabled`, `remote_api_key`,
`allow_legacy_remote_api_key`, `remote_rate_limit_per_minute` (def 100; 0=∞).

**UI/wizard (`core`)**: `ui_theme_preset` (applied on load), `wizard_complete` (flag set by UI).

**Integrations (`integrations`)**: `mcp_client_enabled` (enable MCP stdio client; needs allow_run +
approvals), `discord_webhook_url`, `discord_bot_token`, `slack_webhook_url`.

#### Inert / unused / cosmetic‑only keys (evidence)
- `ui_theme_preset` — in schema (`config_schema.py:172`) but **no reader** in the live UI applies it on
  load (grep of `agent/ui` shows no `ui_theme_preset` consumer). **inert.**
- `mcp_client_enabled`, `discord_webhook_url`, `discord_bot_token`, `slack_webhook_url` — editable via
  the flat modal only; **no curated‑tab UI and no dedicated setup panel** (the tab's Integrations
  group only has Obsidian + mDNS). Backend tools exist, but the settings surface for them is the raw
  form → **backend/tool without curated UI.**
- Every `plan_governance_*`, `engineering_pipeline_*`, `in_loop_plan_*` key is **flat‑modal‑only** —
  no curated control; power‑user text/number rows. Functional but discoverable only via the raw form.

---

### A2. SETTINGS_PRESETS (potato / low‑resource)

**What/why:** one named merge, `potato` (`config_schema.py:11`): forces `performance_mode:low`,
`n_ctx:2048`, `n_batch:256`, `n_gpu_layers:0`, `max_tool_calls:2`, `max_runtime_seconds:20`,
`research_max_*` down, `use_chroma:false`, `completion_max_tokens:192`, `semantic_k/knowledge_chunks_k:3`,
`learnings_n:15`, `scheduler_study_enabled:false`, `whisper_model:tiny`. For weak hardware.
**How used:** modal button "Apply potato preset" (index.html:1156, `data-action="applySettingsPreset"
data-arg="potato"`) → `applySettingsPreset('potato')` (`settings-full.js:264`) → `POST
/settings/preset/potato`.
**Trace hop mismatch (works, but by a different route than expected):** the UI calls
`POST /settings/preset/{name}` (path param). The router `apply_runtime_preset` (`settings.py:421`)
reads the preset from the **JSON body** (`body.get("preset")`/`name`), and `applySettingsPreset` sends
**no body**. So the *documented* `POST /settings/preset` handler would 400. **However** FastAPI also
matches `/settings/preset/potato` against… nothing here — there is no `@router.post("/settings/preset/{name}")`. → the call resolves to the body‑reading handler via trailing segment? **No** — verified only
one preset route exists (`settings.py:421`, no `{name}`). **The path‑style call 404s.** ⇒ potato preset
button is **broken as wired** (calls `/settings/preset/potato`, server only exposes `/settings/preset`
with body). Fix: send `{preset:name}` to `/settings/preset`, or add a `{name}` route.
**STATUS: broken (mis‑wired path)** — backend preset logic itself is working
(`config_schema.apply_settings_preset` + `route_helpers.sync_apply_runtime_preset`).

---

### A3. Appearance keys + endpoints

Two appearance concepts, and the UI conflates them:
- `GET/POST /settings/appearance` (`settings.py:359/366` → `route_helpers.sync_save_appearance:136`)
  persists ONLY: `ui_avatar_seed, ui_avatar_style, ui_tts_rate, chat_lite_mode,
  ui_decision_trace_enabled, ui_appearance_json`.
- The modal's "Appearance / lite" section (index.html:1177) has inputs `#ui_avatar_seed`,
  `#ui_avatar_style`, `#chat_lite_mode`, `#ui_decision_trace_enabled`, wired to
  **`data-action="saveAppearanceLite"`**.
**Bug:** `saveAppearanceLite()` (`settings-full.js:274`) reads `#app-font-size` and `#app-anim-level`
(which **do not exist** anywhere in `index.html` — grep = 0 hits), builds `{ui_font_size,
ui_animation_level}`, and POSTs to **`/settings`** (not `/settings/appearance`). Consequences:
  1. Font/anim ids missing → body is empty → nothing saved.
  2. It never reads the avatar/lite inputs that the button is attached to → those fields save **nothing.**
  3. `ui_font_size`/`ui_animation_level` aren't in `EDITABLE_SCHEMA` → even if present they'd be dropped.
**STATUS: broken** — the "Save appearance & lite" button is a no‑op; the real
`sync_save_appearance` capability (avatar/lite) is never exercised by the live UI.

---

### A4. Content policy (safe_mode / uncensored / nsfw_allowed)

**Curated‑tab control** (index.html:643–649): checkboxes `#opt-uncensored`, `#opt-nsfw-allowed`, button
"Save content policy" → `saveContentPolicySettings()` (`settings-full.js:324`) POSTs
`{uncensored, nsfw_allowed}` to `/settings`. **STATUS: working** (2 of 3 keys). Note: `safe_mode` has
**no curated toggle** — only editable via the flat modal or per‑request `allow_write/allow_run`.
The checkboxes are not pre‑populated from server state on tab open (no GET wiring shown), so they can
display stale defaults until saved.

---

### A5. Permissions / safety model as exposed in settings

Curated "Permissions & Safety" accordion (index.html:626):
- `#allow-write` / `#allow-run` — **not settings keys**; they are **per‑request flags** read at send
  time (`app.js:167,304`; `bootstrap.js:80`; `workspace.js:290`) and attached to the `/agent` body as
  `allow_write`/`allow_run`. They gate whether *that turn* may mutate files / run commands without
  per‑tool approval. They do NOT persist.
- `#tool-approval-bypass` — **persists**: change handler (`app.js:717`) POSTs
  `{tool_approval_bypass:on}` to `/settings`; pre‑populated from health config (`app.js:709`). When on,
  ALL tool approvals are skipped. A red warning banner (`#bypass-warning`) shows while active.
- Pending approvals list `#approvals-list` (index.html:651) — populated elsewhere (approvals router).
**What each really gates:** `safe_mode` (global, needs approval for writes/exec) → `allow_write/run`
(per‑turn opt‑in that satisfies `planning_strict_mode` bindings and skips approval for that class) →
`tool_approval_bypass` (nuclear: skip everything) → `admin_mode` (auto‑approve dangerous tools but
still audited; blocklist still applies unless `admin_blocklist_override`).
**STATUS: working** (bypass persists; allow‑write/run per‑turn as designed).

---

### A6. Admin mode + git‑undo checkpoint

- Admin keys (`admin_mode`, `admin_auto_checkpoint`, `admin_blocklist_override`) are **flat‑modal‑only**
  toggles (the modal's "Admin mode" note, index.html:1159, literally says "toggle … in the settings
  form above").
- **Git‑undo checkpoint** (index.html:1160): input `#admin-undo-workspace` + button
  `laylaGitUndoCheckpoint` (`settings-full.js:130`) → `POST /settings/git_undo_checkpoint`
  (`settings.py:502`) → `services.safety.admin_checkpoint.git_revert_last_checkpoint(ws)`. Reverts the
  last commit whose subject contains `layla-checkpoint`. Needs a real git repo + prior checkpoint.
**STATUS: working** (both endpoints present; UI wired; requires admin_auto_checkpoint to have produced a commit).

---

### A7. Optional‑features installer

**What it installs (fixed allowlist):** `FEATURES` in
`services/infrastructure/dependency_recovery.py:61` → `faster-whisper` (STT), `kokoro-onnx`+`soundfile`
(Kokoro TTS), `pyttsx3` (fallback TTS), `llama-cpp-python` (local inference). All must be in
`_PIP_ALLOWLIST` (line 23) or the install is refused.
**Trace:** modal "Optional features → Refresh list" → `laylaLoadOptionalFeatures()`
(`settings-full.js:86`) → `GET /settings/optional_features` (`settings.py:473` →
`get_optional_features`) renders each with an **Install** button for missing ones →
`laylaInstallFeature(id)` (`settings-full.js:105`) confirms then `POST /settings/install_feature`
(`settings.py:484` → `install_feature`) runs the allowlisted pip (does NOT require
`auto_pip_install_optional`; explicit operator action).
**STATUS: working.**

---

### A8. Import‑chat

**What:** paste a WhatsApp `_chat.txt` export → saved under `knowledge/imports/`.
**Trace:** modal "Import chat export" (index.html:1170) → `laylaImportChat()` (`settings-full.js:116`)
POSTs `{format:'whatsapp', text, title}` to `/knowledge/import_chat` (knowledge router).
**STATUS: working** (endpoint verified to exist in `routers/knowledge.py`; only WhatsApp format hard‑coded in UI).

---

## PART B — CONNECTIVITY

### B1. Device pairing (mDNS discovery + PIN + per‑device permissions + unpair)

**What/why:** find other Layla instances on the LAN via mDNS (`_layla._tcp`), pair them with a 6‑digit
PIN, grant per‑device permissions, health‑check, unpair. For a personal multi‑device mesh.
**How a user uses it** (curated tab → Integrations → "Network & Devices", index.html:738):
- "Start/Stop Discovery" (`#discovery-toggle-btn`, `data-action="toggleDiscovery"`) → `toggleDiscovery`
  wrapper (`main.js:424`) → `startDiscovery`/`stopDiscovery` (`pairing.js:31/48`) → `POST
  /pairing/start` / `/pairing/stop` (`pairing.py:211/224` → `mdns_discovery.start_service/stop_service`).
- Discovery starts a 10 s poll of `/pairing/peers` (`pairing.js:63` → `refreshPeersList` →
  `pairing.py:165` → `mdns_discovery.get_discovered_peers`). Each peer card shows tier/models/version/
  age + **Pair** and **Ping**.
- **Pair:** `initiatePairing` (`pairing.js:111`) → `POST /pairing/pair` (`pairing.py:235`) mints a PIN
  (server‑side `_pending_pairings`), shows a countdown PIN dialog. Confirmation
  (`confirmPairing`→`POST /pairing/confirm`, `pairing.py:279`) writes the device to
  `agent/.governance/paired_devices.json` with default permissions.
- **Per‑device permissions** (5 booleans: read_learnings, write_learnings, inference_offload,
  sync_knowledge, remote_tools) — toggles call `toggleDevicePermission` (`pairing.js:245`) → `PATCH
  /pairing/{id}/permissions` (`pairing.py:414`).
- **Unpair:** `unpairDevice` (`pairing.js:261`) → `DELETE /pairing/{id}` (`pairing.py:363`).
- **Ping:** `checkPeerHealth` → `GET /pairing/peer/{id}/health` (`pairing.py:376`).
**Wired?** Fully — UI ↔ router ↔ `mdns_discovery` service (470 lines) all present. Degrades gracefully
when `zeroconf` isn't installed (`/pairing/start` returns a helpful error).
**Caveat:** `refreshPeeringPanel` (`pairing.js:302`, sets instance‑id + peer‑count) is registered
(`main.js:397`) and there's a "Refresh" button, but **there is no code that calls it on tab‑open** — the
instance‑id/`paired-devices` list stay `—`/empty until the user clicks Refresh or Start Discovery.
**STATUS: working** (functional; minor: not auto‑refreshed on panel open). *Note: permissions stored on
paired_devices.json are recorded but nothing in this cluster consumes them for a live P2P transport — the
enforcement side (inference_offload/remote_tools between paired devices) is not exercised by any wired
UI path; treat cross‑device *actions* as **not‑proven**, pairing/record‑keeping as working.*

### B2. Remote access (remote_enabled / api_key / legacy key / rate‑limit)

**What/why:** allow non‑localhost clients to reach the API with a Bearer token, rate‑limited.
**Backend fully wired (not in the settings tab):**
- `remote_enabled` gate + Bearer‑token enforcement + endpoint allowlist: `main.py:1003`
  (`remote_auth`‑style middleware) and token validation `services/safety/auth.py:33+`.
- Legacy plaintext `remote_api_key` honored **only** when `allow_legacy_remote_api_key` is true
  (`auth.py:46–53`); otherwise the modern `tunnel_token_hash` path (rotate via `/remote/token/rotate`).
- `remote_rate_limit_per_minute` enforced in `remote_rate_limit_middleware` (`main.py:1084–1104` →
  `services/infrastructure/remote_rate_limit.check_rate_limit`).
- `GET /local_access_info` (`system.py:513`) returns LAN URL + whether remote is enabled / key required.
**UI reality:** there is **no curated toggle** for `remote_enabled`/`remote_api_key`/rate‑limit — they
are editable **only via the flat schema modal** (and remote‑protected, so only a local operator can
change them). `index.html:66` reads a `layla_remote_api_key` from localStorage for the client's own
outbound calls, but there is no panel to *enable* remote mode. `/local_access_info` has no UI caller.
**STATUS: backend working, ui‑without‑curated‑surface** (functional if you edit the raw form; not
discoverable in the "Settings" tab).

### B3. Tunnel (cloudflared)

**What/why:** one‑command public HTTPS URL to this machine (`cloudflared` quick tunnel), with
health‑check + auto‑restart. Endpoints: `POST /remote/tunnel/start|stop`, `GET
/remote/tunnel/status|health` (`system.py:593–640`). Service `tunnel_manager.py` (198 lines) is
**fully functional**: real `subprocess.Popen([cloudflared, tunnel, --url …])`, stderr scrape for the
`trycloudflare.com` URL, `health_check()`, `auto_restart_if_unhealthy()`.
**UI reality:** **NO UI.** grep of `agent/ui` for `tunnel`/`/remote/tunnel` = 0 hits. No button, no
action registration.
**STATUS: backend‑without‑ui** (works from curl/CLI; invisible in GUI).

### B4. Tailscale (+ funnel)

**What/why:** join a Tailscale VPN; optionally expose via Funnel (public HTTPS). Endpoints:
`GET /remote/tailscale/status`, `POST …/start|stop`, `POST …/funnel/start|stop` (`system.py:695–750`)
→ `tailscale_manager.py` (280 lines).
**UI reality:** **NO UI** (0 hits for `tailscale`/`funnel` in `agent/ui`).
**STATUS: backend‑without‑ui.**

### B5. Syncthing sync

**What/why:** multi‑device file sync of the Layla data folder via Syncthing. Endpoints under
`/sync/*` (`routers/sync.py`): status/rescan/device‑id/add‑device/setup‑guide → `syncthing_sync.py`
(259 lines). `/health` also embeds a Syncthing summary when enabled (`system.py:317`).
**UI reality:** **NO UI** (0 hits for `/sync/`, `syncthing`, `add-device` in `agent/ui`). Config keys
(`syncthing_api_key`, `syncthing_base_url`, `syncthing_folder_id`) are **not even in EDITABLE_SCHEMA**,
so they can't be set from the settings form either — only by hand‑editing config.
**STATUS: backend‑without‑ui** (and no schema surface → config‑file‑only to enable).

### B6. Phone‑access URL

**What:** show the LAN URL to open Layla on a phone.
**Two implementations, one wired:**
- `loadPhoneAccess()`/`copyPhoneUrl()` (`settings-full.js:364/384`) compute the URL client‑side from
  `location.*` and populate `#phone-access-url`. These are **exported but NOT registered** in
  `main.js` `registerActions` (grep: no `loadPhoneAccess`/`copyPhoneUrl` there) and **no `#phone-access-url`
  element exists** in `index.html` (0 hits). ⇒ **dead code.**
- The server‑side `GET /local_access_info` (`system.py:513`) is the real capability but has no caller.
**STATUS: dead (UI) / backend‑without‑ui (server).**

### B7. Obsidian (vault connect / sync / suggest / diff / export)

**What/why:** point Layla at an Obsidian vault, sync `.md` into the knowledge base, and suggest/export
high‑confidence learnings back as notes. Endpoints (`routers/obsidian.py`): connect/status/diff/sync/
suggest/export → `obsidian_sync.py` (264 lines).
**How used** (curated tab → Integrations → "Obsidian Vault", index.html:725): input
`#obsidian-vault-path` + buttons Connect / Sync / Suggest exports:
- Connect → `laylaObsidianConnect` (`obsidian.js:13`) → `POST /obsidian/connect` (persists path via
  `set_vault_path`), also caches to `localStorage`.
- Sync → `laylaObsidianSync` → `POST /obsidian/sync` (reports copied/conflicts).
- Suggest → `laylaObsidianSuggest` → `GET /obsidian/suggest?n=5` (counts exportable learnings).
Path is restored on load (`obsidian.js:73`). Actions registered `main.js:405–407`.
**Gaps:** `GET /obsidian/status`, `/obsidian/diff`, and `POST /obsidian/export` have **no UI caller** —
"Suggest" only prints a count and tells the user to hit the export API manually. So connect+sync work;
diff/export are backend‑only.
**STATUS: partial** (connect/sync/suggest working; diff + actual export unwired in UI).

---

## PART C — CLUSTER (queen/drone mesh) — parked/experimental

**What:** a distributed inference mesh (QUEEN dispatches WorkUnits to DRONEs; heartbeat, task submit/
poll/cancel, learning push/pull). Endpoints `routers/cluster.py` (`/cluster/*`), services under
`services/cluster/` (cluster_network, cluster_pairing, work_unit, resource_governor). Bearer‑auth for
remote; localhost bypass.
**UI:** a full "Cluster" panel exists (index.html:520–568) + `cluster.js`: enable toggle
(`toggleClusterEnabled` → `POST /settings {cluster_enabled}`), status refresh
(`/cluster/status|peers|queue/stats`), generate pairing token (`GET /cluster/pair/token`, QUEEN‑local),
pair‑as‑drone (`POST /cluster/pair`). Actions registered `main.js:390–393`. `initCluster()` runs at
startup and reveals the drone section if `cluster_enabled`.
**Status confirmation:** `cluster_enabled` is **not** in `EDITABLE_SCHEMA` (so it's a soft/off‑by‑default
flag written straight to config by the toggle), and `GUI-FEATURE-MAP.md` §A/§D marks Cluster **[PARK]**
(Settings › Advanced › Experimental, off by default). The code path is present and internally
consistent, but this is experimental infrastructure, not a wedge feature.
**STATUS: working‑but‑parked (experimental)** — wired end‑to‑end; intentionally de‑emphasized. Requires
a second running node + `services/cluster/*` runtime to be meaningful; single‑box it just reports
"Disabled/0 peers".

---

## PART D — DIAGNOSTICS

All endpoints live in `routers/system.py` (health/doctor/version/update/remote‑audit/search‑status),
`routers/metrics.py` (metrics), `routers/session.py` (`/audit`, `/system_export`), `routers/tools_history.py`.

| Endpoint | What it surfaces | Live? | UI caller |
|---|---|---|---|
| `GET /health` (`system.py:179`) | status, uptime, model_loaded, tools, learnings, degraded, backends, effective_limits, dependencies, syncthing, model_routing | **live** | `services/health.js` polls fast(15s)/deep(20s); Dashboard `#platform-health`, `#runtime-options-panel` |
| `GET /health/context_budget` (:404) | per‑section context token budget last turn | live | **none** |
| `GET /health/trace` (:423) | last N request traces (tokens/latency/aspect) + goal pre/post optimizer | live | **none** |
| `GET /health/deps` (:466) | dependency matrix (+`?deep` Chroma probe) | live | **none** (deps come via /health instead) |
| `GET /doctor` (:547) | full diagnostics (`system_doctor.run_diagnostics`) | live | Dashboard "/doctor" button → `laylaRunDoctor` dumps JSON into chat (`workspace.js:346`) |
| `GET /doctor/capabilities` (:558) | + browser/voice capability probe | live | **none** |
| `GET /version` (:114) | app version | live | `app.js:623` → `#app-version` |
| `GET /update/check` (:119) | update available? (git or release channel) | live | **MIS‑WIRED** — UI calls `/version/check_update` (`settings-full.js:315`) which **does not exist** → 404 → "Could not check" |
| `POST /update/apply` (:135) | apply update (needs `allow_run` + shell approval) | live | **none** |
| `POST /undo` (:155) | git‑revert last Layla auto‑commit | live | `workspace.js:332` (a Workspace button) |
| `GET /metrics` `/metrics/summary` `/metrics/security` `/metrics/observability` (`metrics.py`) | Prometheus + human summary + security‑audit events + unified snapshot | live | **none** (no UI caller in `agent/ui`) |
| `GET /audit` (`session.py:226`) | tool audit log (paged) | live | **none** |
| `GET /remote/audit` `/remote/audit/summary` (`system.py:674/685`) | tunnel access audit | live | **none** (no tunnel UI at all) |
| `GET /tools/history` `/tools/analysis` (`tools_history.py`) | tool‑call history + analysis | live | **none** |
| `GET /search/status` (`system.py:753`) | search backend status | live | **none** |
| `GET /system_export` (`session.py:83`) | full safe config export | live | modal link "⊕ export config" → opens `/system_export` in new tab (index.html:1151) |
| `GET /debug/state` `/debug/tasks` (`system.py:43/56`) | last exec snapshot / persisted tasks | live | Dashboard "Execution trace"/"Coordinator tasks" (`wsRefreshExecutionPanels`) |

**Summary:** the diagnostics *backend* is rich and live, but the current GUI surfaces only a thin slice —
health (polled), version, doctor (as a chat dump), undo, exec‑trace, coordinator‑tasks, system‑export.
**Metrics, audit, remote‑audit, tools‑history/analysis, health‑trace, health‑deps, context‑budget, and
doctor/capabilities have NO UI consumer.** Update‑check is broken by a wrong path.

---

## STATUS TABLE

| # | Feature / group | Status | Evidence (file:line) |
|---|---|---|---|
| A0 | Flat schema settings modal (all keys) | **working** | settings.py:327/351/378; settings-full.js:11/62 |
| A1 | EDITABLE_SCHEMA keys (meaning/effect) | **working** (documented) | config_schema.py:32–312 |
| A1 | `ui_theme_preset` applied on load | **inert** | schema config_schema.py:172; no UI reader |
| A1 | discord/slack/mcp_client curated surface | **backend‑without‑curated‑ui** | config_schema.py:301–311; only flat modal |
| A2 | Potato preset button | **broken** (calls `/settings/preset/{name}`, server = `/settings/preset` body) | index.html:1156 vs settings.py:421 |
| A3 | "Save appearance & lite" button | **broken** (reads nonexistent ids, wrong endpoint, non‑schema keys) | settings-full.js:274–287; index.html:1177 |
| A4 | Content policy (uncensored/nsfw) | **working** (safe_mode absent from tab; no prefill) | settings-full.js:324; index.html:643 |
| A5 | Permissions (allow‑write/run per‑turn) | **working** | app.js:167/304; bootstrap.js:80 |
| A5 | Bypass‑all‑approvals (persisted) | **working** | app.js:717 → POST /settings |
| A6 | Admin mode toggles | **working** (flat‑modal only) | index.html:1159; config_schema.py:280 |
| A6 | Git‑undo checkpoint | **working** | settings-full.js:130 → settings.py:502 |
| A7 | Optional‑features installer | **working** | settings-full.js:86/105 → settings.py:473/484; dependency_recovery.py:61 |
| A8 | Import‑chat (WhatsApp) | **working** | settings-full.js:116 → /knowledge/import_chat |
| B1 | Device pairing / mDNS / perms / unpair | **working** (not auto‑refreshed; cross‑device *actions* not‑proven) | pairing.js:*; pairing.py:*; mdns_discovery.py |
| B2 | Remote access (enable/key/rate‑limit) | **backend working, no curated UI** | main.py:1003/1084; auth.py:33; flat‑modal only |
| B3 | Cloudflared tunnel | **backend‑without‑ui** | system.py:593–640; tunnel_manager.py (0 UI hits) |
| B4 | Tailscale (+funnel) | **backend‑without‑ui** | system.py:695–750; tailscale_manager.py (0 UI hits) |
| B5 | Syncthing sync | **backend‑without‑ui** (+ no schema surface) | routers/sync.py; syncthing_sync.py; keys not in schema |
| B6 | Phone‑access URL | **dead (UI) / backend‑without‑ui** | settings-full.js:364 unregistered, no DOM; system.py:513 no caller |
| B7 | Obsidian connect/sync/suggest | **partial** (diff/export unwired) | obsidian.js:13–48; obsidian.py; /diff,/export no caller |
| C | Cluster (queen/drone) | **working‑but‑parked (experimental)** | cluster.js; cluster.py; GUI‑FEATURE‑MAP §A [PARK] |
| D | /health (+deep) | **working** | system.py:179; health.js |
| D | /doctor | **working** (chat‑dump only) | system.py:547; workspace.js:346 |
| D | version display | **working** | system.py:114; app.js:623 |
| D | update check | **broken** (wrong path `/version/check_update`) | settings-full.js:315 vs system.py:119 |
| D | update apply | **backend‑without‑ui** | system.py:135 |
| D | metrics (all 4) | **backend‑without‑ui** | metrics.py; 0 UI hits |
| D | audit log / remote‑audit | **backend‑without‑ui** | session.py:226; system.py:674 |
| D | tools history/analysis | **backend‑without‑ui** | tools_history.py; 0 UI hits |
| D | health trace/deps/context_budget, doctor/capabilities | **backend‑without‑ui** | system.py:404/423/466/558 |
| D | search status | **backend‑without‑ui** | system.py:753 |
| D | system export | **working** (link) | session.py:83; index.html:1151 |
| D | exec trace / coordinator tasks | **working** | system.py:43/56; wsRefreshExecutionPanels |

---

## TOP UX PROBLEMS (ranked)

1. **Update‑check is broken by a typo'd path.** The Dashboard "Check for updates" button
   (`settings-full.js:315`) calls `/version/check_update`, which returns 404; the real route is
   `/update/check`. Users always see "Could not check" and can never learn an update exists. *High
   impact, one‑line fix.*
2. **"Save appearance & lite" saves nothing.** `saveAppearanceLite` reads DOM ids that don't exist,
   ignores the avatar/lite inputs it's actually attached to, targets the wrong endpoint, and uses keys
   not in the schema. Any avatar/chat‑lite/decision‑trace change made in the modal is silently lost.
   *High impact (data‑loss illusion), correctness bug.*
3. **Potato preset button is mis‑wired.** It POSTs to `/settings/preset/potato` (path) but the only
   handler reads the preset from the JSON body at `/settings/preset`. The one control that exists for
   weak‑hardware users 404s. *High impact for the target audience.*
4. **Whole connectivity backends are invisible.** Tunnel (cloudflared), Tailscale/Funnel, Syncthing,
   remote‑enable, and phone‑URL are fully implemented server‑side but have **no GUI** (and Syncthing/
   phone aren't even in the settings schema). A user cannot turn on remote access or a public URL
   without hand‑editing `runtime_config.json` — which for remote keys is *also* blocked to non‑local
   callers. The map's promised "Settings › Connectivity" page does not exist. *High impact: advertised
   capability is unreachable.*
5. **Diagnostics richness is stranded.** `/metrics*`, `/audit`, `/remote/audit`, `/tools/history`,
   `/tools/analysis`, `/health/trace`, `/health/deps`, `/health/context_budget`, `/doctor/capabilities`
   all return live data with **zero UI**. "Doctor" is only a raw‑JSON dump into the chat transcript, not
   a readable panel. The "Doctor destination" in the map is really just three buttons on the Dashboard.
   *Medium‑high: observability exists but isn't usable by a non‑developer.*
6. **Two competing settings surfaces with overlap + drift.** The flat modal renders all ~80 keys as
   unlabeled raw inputs (checkbox/number/text) with only hints, while the curated tab covers a
   different, smaller subset. `safe_mode`, admin, remote, governance, discord/slack live *only* in the
   raw form; content‑policy/permissions live *only* in the tab. There is no single place to reason about
   safety, and the raw modal is a wall (exactly the "70‑key wall" the rebuild set out to kill).
   *Medium‑high: discoverability + mental‑model cost.*
7. **Curated panels don't self‑refresh / self‑prefill.** Pairing (`refreshPeeringPanel`) and content
   policy don't load current state on open — instance‑id shows `—`, checkboxes show defaults — so the UI
   can misrepresent server state until the user clicks Refresh/Save. *Medium.*
8. **Obsidian is half‑wired.** Connect/Sync work but "Suggest exports" only prints a count and tells the
   user to call the export API by hand; `/obsidian/diff` and `/obsidian/export` (the actual value —
   writing notes back) have no button. *Medium.*
9. **Paired‑device permissions are recorded but not enforced by any wired path.** The 5 per‑device
   toggles persist to `paired_devices.json`, but no live cross‑device action in this cluster consumes
   them, so granting `inference_offload`/`remote_tools` does nothing observable — a trust‑model
   affordance that implies more than it delivers. *Medium (safety‑perception).*
10. **Cluster is fully built but should stay parked.** It's wired end‑to‑end yet single‑box shows only
    "Disabled/0 peers"; per the map it's experimental. Leaving its panel visible at the current
    prominence invites confusion about a non‑wedge feature. *Low‑medium (IA noise).*

---

### Answers to the two key questions
- **Inert / unused settings keys:** `ui_theme_preset` (no loader); `syncthing_*` keys (not in schema,
  UI‑unreachable); and functionally‑stranded‑from‑the‑GUI clusters — `discord_*`, `slack_webhook_url`,
  `mcp_client_enabled`, all `plan_governance_*`/`engineering_pipeline_*`/`in_loop_plan_*`, `admin_*`,
  and the entire `remote_*` group — reachable *only* through the raw flat modal, with no curated
  control. The appearance keys `ui_font_size`/`ui_animation_level` referenced by the UI aren't schema
  keys at all (dead reference).
- **Connectivity: functional vs aspirational.** *Functional (server + UI):* mDNS **pairing**
  (record‑keeping/discovery), **Obsidian** connect+sync. *Functional server, NO/insufficient UI:*
  **remote access** (works, raw‑form only), **cloudflared tunnel**, **tailscale/funnel**, **Syncthing**,
  **phone‑URL** — all real backends with no reachable GUI. *Aspirational:* the map's "Settings ›
  Connectivity" grouped page and the whole tunnel/tailscale/sync front‑end; **cluster** is built but
  intentionally parked/experimental.
