# 07 -- API Surface: HTTP Routers

> Design document for Layla's REST + WebSocket API.
> Generated from analysis of all 37 router files under `agent/routers/`
> and the mounting logic in `agent/main.py`.

---

## 1. Complete Endpoint Table

| # | Method | Path | Router | Pydantic? | Auth | Description |
|---|--------|------|--------|-----------|------|-------------|
| 1 | POST | `/agent` | agent | AgentRequest | remote | Main chat endpoint (streaming + JSON) |
| 2 | GET | `/agent/decision_trace` | agent | -- | remote | Last decision policy trace |
| 3 | POST | `/agent/steer` | agent | SteerRequest | remote | Queue redirect for in-flight run |
| 4 | DELETE | `/agent` | system | -- | remote | Cancel latest agent run |
| 5 | POST | `/agent/cancel/{conversation_id}` | system | -- | remote | Cancel specific conversation run |
| 6 | GET | `/agent/cot_stats` | system | -- | remote | Dual-model CoT cost stats |
| 7 | POST | `/agent/background` | agent_tasks | raw dict | remote | Start background autonomous task |
| 8 | GET | `/agent/tasks` | agent_tasks | -- | remote | List background tasks |
| 9 | GET | `/agent/tasks/{task_id}` | agent_tasks | -- | remote | Get task detail |
| 10 | DELETE | `/agent/tasks/{task_id}` | agent_tasks | -- | remote | Cancel background task |
| 11 | POST | `/agent/tasks/{task_id}/cancel` | agent_tasks | -- | remote | Cancel background task (POST alias) |
| 12 | POST | `/agent/persistent_tasks/{task_id}/resume` | agent_tasks | raw dict | remote | Resume coordinator task from checkpoint |
| 13 | POST | `/resume` | agent_tasks | raw dict | remote | Resume paused-high-load run |
| 14 | POST | `/execute_plan` | agent_tasks | raw dict | remote | Execute pre-generated plan steps |
| 15 | GET | `/memories` | learn | -- | remote | Search memories by query |
| 16 | POST | `/schedule` | learn | ScheduleRequest | remote | Schedule tool for background run |
| 17 | POST | `/learn/` | learn | LearnRequest | remote | Save a new learning |
| 18 | GET | `/memory/stats` | memory | -- | remote | Memory state summary |
| 19 | GET | `/memory/export` | memory | -- | remote | Download ZIP bundle of knowledge+learnings |
| 20 | POST | `/memory/import` | memory | UploadFile | remote | Import memory bundle ZIP |
| 21 | GET | `/memory/elasticsearch/search` | memory | -- | remote | Elasticsearch learning search |
| 22 | GET | `/memory/file_checkpoints` | memory | -- | remote | List pre-write file checkpoints |
| 23 | POST | `/memory/file_checkpoints/restore` | memory | raw dict | remote | Restore file checkpoint |
| 24 | GET | `/memory/browse` | memory | -- | remote | Paginated learning browser |
| 25 | PATCH | `/memory/{learning_id}` | memory | raw dict | remote | Update learning content/tags |
| 26 | DELETE | `/memory/{learning_id}` | memory | -- | remote | Delete learning by ID |
| 27 | POST | `/memory/rebuild` | system | -- | remote | Rebuild Chroma from SQLite |
| 28 | POST | `/debate` | debate | DebateRequest | remote | Multi-aspect deliberation |
| 29 | GET | `/debate/modes` | debate | -- | remote | List deliberation modes |
| 30 | POST | `/plans` | plans | raw dict | remote | Create a durable plan |
| 31 | GET | `/plans` | plans | -- | remote | List plans |
| 32 | GET | `/plans/similar` | plans | -- | remote | Find similar past plans |
| 33 | GET | `/plans/{plan_id}` | plans | -- | remote | Get single plan |
| 34 | PATCH | `/plans/{plan_id}` | plans | raw dict | remote | Update plan goal/steps/status |
| 35 | POST | `/plans/{plan_id}/approve` | plans | -- | remote | Approve plan for execution |
| 36 | POST | `/plans/{plan_id}/execute` | plans | raw dict | remote | Execute approved plan |
| 37 | GET | `/plans/{plan_id}/viz` | plans | -- | remote | Gantt visualization data |
| 38 | POST | `/plan/create` | plan_file | raw dict | remote | Create file-backed plan |
| 39 | GET | `/plan/{plan_id}` | plan_file | -- | remote | Get file-backed plan |
| 40 | POST | `/plan/{plan_id}/approve` | plan_file | -- | remote | Approve file-backed plan |
| 41 | POST | `/plan/{plan_id}/add_steps` | plan_file | raw dict | remote | Add steps to file-backed plan |
| 42 | POST | `/plan/{plan_id}/execute_next` | plan_file | -- | remote | Execute next step |
| 43 | POST | `/plan/{plan_id}/run_continuous` | plan_file | raw dict | remote | Run plan continuously in background |
| 44 | POST | `/research_mission` | research | raw dict | remote | Full research mission (autonomous) |
| 45 | GET | `/research_mission/state` | research | -- | remote | Mission progress state |
| 46 | GET | `/research_output/last` | research | -- | remote | Last research report |
| 47 | GET | `/research_brain/file` | research | -- | remote | Read research brain file |
| 48 | GET | `/research_mission/debug` | research | -- | remote | Debug research pipeline |
| 49 | GET | `/research_mission/verify` | research | -- | remote | Verify mission pipeline readiness |
| 50 | POST | `/research` | research | raw dict | remote | Read-only repo research |
| 51 | POST | `/autonomous/run` | autonomous | raw dict | remote | Tier-0 autonomous task |
| 52 | GET | `/study_plans` | study | -- | remote | List active study plans |
| 53 | POST | `/study_plans` | study | raw dict | remote | Add study plan |
| 54 | DELETE | `/study_plans/{plan_id}` | study | -- | remote | Delete study plan |
| 55 | GET | `/study_plans/presets` | study | -- | remote | Curated study topics |
| 56 | GET | `/study_plans/suggestions` | study | -- | remote | Workspace-based suggestions |
| 57 | POST | `/study_plans/derive_topic` | study | raw dict | remote | Derive topic from text |
| 58 | POST | `/study_plans/record_progress` | study | raw dict | remote | Record study progress |
| 59 | GET | `/wakeup` | study | -- | remote | Session wakeup greeting |
| 60 | GET | `/capabilities` | study | -- | remote | Capability domains and growth |
| 61 | GET | `/aspects/{aspect_id}/title` | study | -- | remote | Get aspect earned title |
| 62 | POST | `/aspects/{aspect_id}/title` | study | raw dict | remote | Set aspect earned title |
| 63 | GET | `/aspects/{aspect_id}` | aspects | -- | remote | Get aspect metadata (character sheet) |
| 64 | GET | `/setup_status` | settings | -- | remote | First-run readiness state |
| 65 | GET | `/setup/models` | settings | -- | remote | Model catalog for picker |
| 66 | GET | `/setup/download` | settings | -- | remote | Stream model download (SSE) |
| 67 | POST | `/setup/auto` | settings | -- | remote | Idempotent auto-setup |
| 68 | GET | `/settings` | settings | -- | remote | Get all editable settings |
| 69 | GET | `/settings/schema` | settings | -- | remote | Config schema for UI |
| 70 | GET | `/settings/appearance` | settings | -- | remote | Get appearance settings |
| 71 | POST | `/settings/appearance` | settings | raw dict | remote | Save appearance settings |
| 72 | POST | `/settings` | settings | raw dict | remote | Update runtime_config.json |
| 73 | POST | `/settings/preset` | settings | raw dict | remote | Apply named config preset |
| 74 | GET | `/settings/optional_features` | settings | -- | remote | Optional Python feature bundles |
| 75 | POST | `/settings/install_feature` | settings | raw dict | remote | pip install optional feature |
| 76 | POST | `/settings/git_undo_checkpoint` | settings | raw dict | remote | Revert admin checkpoint |
| 77 | GET | `/operator/quiz/stage/{stage_idx}` | settings | -- | remote | Quiz questions for stage |
| 78 | POST | `/operator/quiz/submit` | settings | raw dict | remote | Submit quiz answers |
| 79 | GET | `/operator/profile` | settings | -- | remote | Current operator profile |
| 80 | POST | `/operator/profile/stat` | settings | raw dict | remote | Override stat value |
| 81 | POST | `/conversations` | conversations | Body dict | remote | Create conversation |
| 82 | GET | `/conversations` | conversations | -- | remote | List conversations |
| 83 | GET | `/conversations/search` | conversations | -- | remote | Search conversations |
| 84 | POST | `/conversations/{id}/tags` | conversations | raw dict | remote | Set conversation tags |
| 85 | GET | `/conversations/tags/suggest` | conversations | -- | remote | Tag autocomplete |
| 86 | GET | `/conversations/{id}` | conversations | -- | remote | Get conversation detail |
| 87 | GET | `/conversations/{id}/messages` | conversations | -- | remote | Get conversation messages |
| 88 | POST | `/conversations/{id}/rename` | conversations | raw dict | remote | Rename conversation |
| 89 | DELETE | `/conversations/{id}` | conversations | -- | remote | Delete conversation |
| 90 | GET | `/knowledge/ingest/sources` | knowledge | -- | remote | List ingested sources |
| 91 | POST | `/knowledge/ingest` | knowledge | raw dict | remote | Ingest knowledge docs |
| 92 | POST | `/workspace/index` | knowledge | raw dict | remote | Index workspace for search |
| 93 | POST | `/workspace/cognition/sync` | knowledge | raw dict | remote | Sync repo cognition |
| 94 | GET | `/workspace/cognition` | knowledge | -- | remote | List cognition snapshots |
| 95 | POST | `/knowledge/import_chat_preview` | knowledge | raw dict | remote | Preview chat import |
| 96 | POST | `/knowledge/import_chat` | knowledge | raw dict | remote | Write chat export as Markdown |
| 97 | GET | `/search` | search | -- | remote | Global cross-context search |
| 98 | GET | `/sync/status` | sync | -- | remote | Syncthing sync state |
| 99 | POST | `/sync/rescan` | sync | -- | remote | Trigger Syncthing rescan |
| 100 | GET | `/sync/device-id` | sync | -- | remote | This device's Syncthing ID |
| 101 | POST | `/sync/add-device` | sync | AddDeviceRequest | remote | Add peer device |
| 102 | GET | `/sync/setup-guide` | sync | -- | remote | Setup instructions |
| 103 | GET | `/metrics` | metrics | -- | remote | Prometheus scrape endpoint |
| 104 | GET | `/metrics/summary` | metrics | -- | remote | Human-readable metrics |
| 105 | GET | `/health` | system | -- | remote | System health check |
| 106 | GET | `/health/context_budget` | system | -- | remote | Context token usage |
| 107 | GET | `/health/trace` | system | -- | remote | Per-request latency traces |
| 108 | GET | `/health/deps` | system | -- | remote | Dependency matrix |
| 109 | GET | `/version` | system | -- | remote | Version number |
| 110 | GET | `/update/check` | system | -- | remote | Check for updates |
| 111 | POST | `/update/apply` | system | raw dict | remote | Apply update (git pull) |
| 112 | POST | `/undo` | system | -- | remote | Revert last auto-commit |
| 113 | GET | `/usage` | system | -- | remote | Token usage stats |
| 114 | GET | `/history` | system | -- | remote | Recent prompts for UI recall |
| 115 | GET | `/skills` | system | -- | remote | List skills |
| 116 | GET | `/local_access_info` | system | -- | remote | LAN URL for remote access |
| 117 | GET | `/doctor` | system | -- | remote | Full system diagnostics |
| 118 | GET | `/doctor/capabilities` | system | -- | remote | Extended capability probe |
| 119 | GET | `/session/stats` | system | -- | remote | Session metrics alias |
| 120 | GET | `/debug/state` | system | -- | remote | Last execution snapshot |
| 121 | GET | `/debug/tasks` | system | -- | remote | Recent coordinator tasks |
| 122 | GET | `/models/providers` | system | -- | remote | LiteLLM multi-provider status |
| 123 | GET | `/models/providers/{provider}/status` | system | -- | remote | Provider health |
| 124 | GET | `/models/costs` | system | -- | remote | Cost tracking |
| 125 | POST | `/remote/tunnel/start` | system | -- | remote | Start cloudflared tunnel |
| 126 | GET | `/remote/tunnel/status` | system | -- | remote | Tunnel status |
| 127 | POST | `/remote/tunnel/stop` | system | -- | remote | Stop tunnel |
| 128 | GET | `/remote/tunnel/health` | system | -- | remote | Tunnel health check |
| 129 | POST | `/remote/token/rotate` | system | -- | remote | Rotate auth token |
| 130 | GET | `/remote/audit` | system | -- | remote | Tunnel access audit log |
| 131 | GET | `/remote/audit/summary` | system | -- | remote | Audit summary stats |
| 132 | GET | `/remote/tailscale/status` | system | -- | remote | Tailscale VPN status |
| 133 | POST | `/remote/tailscale/start` | system | -- | remote | Start Tailscale |
| 134 | POST | `/remote/tailscale/stop` | system | -- | remote | Stop Tailscale |
| 135 | POST | `/remote/tailscale/funnel/start` | system | -- | remote | Start Tailscale Funnel |
| 136 | POST | `/remote/tailscale/funnel/stop` | system | -- | remote | Stop Tailscale Funnel |
| 137 | GET | `/search/status` | system | -- | remote | Search backend status |
| 138 | GET | `/skill_packs` | system | -- | remote | List installed skill packs |
| 139 | POST | `/skill_packs/install` | system | raw dict | remote | Install skill pack from git |
| 140 | POST | `/skill_packs/remove` | system | raw dict | remote | Remove skill pack |
| 141 | GET | `/rl/preferences` | system | -- | remote | RL tool preference table |
| 142 | GET | `/aspects/reload` | system | -- | remote | Hot-reload aspect definitions |
| 143 | GET | `/projects` | projects | -- | remote | List projects |
| 144 | POST | `/projects` | projects | Body dict | remote | Create project |
| 145 | GET | `/projects/{id}` | projects | -- | remote | Get project |
| 146 | PATCH | `/projects/{id}` | projects | Body dict | remote | Update project |
| 147 | DELETE | `/projects/{id}` | projects | -- | remote | Delete project |
| 148 | POST | `/mission` | missions | raw dict | remote | Create and start mission |
| 149 | GET | `/mission/{id}` | missions | -- | remote | Get mission detail |
| 150 | GET | `/missions` | missions | -- | remote | List missions |
| 151 | POST | `/mission/{id}/pause` | missions | -- | remote | Pause running mission |
| 152 | POST | `/mission/{id}/resume` | missions | -- | remote | Resume paused mission |
| 153 | POST | `/mission/{id}/cancel` | missions | -- | remote | Cancel/abort mission |
| 154 | GET | `/missions/board` | missions | -- | remote | Kanban board view |
| 155 | GET | `/missions/horizon` | missions | -- | remote | Long-horizon plan checkpoints |
| 156 | GET | `/character/summary` | character | -- | remote | Character lab summary |
| 157 | GET | `/character/aspects` | character | -- | remote | All aspect profiles |
| 158 | GET | `/character/aspects/{id}` | character | -- | remote | Single aspect profile |
| 159 | PATCH | `/character/aspects/{id}` | character | AspectCustomization | remote | Customize aspect personality |
| 160 | POST | `/character/aspects/{id}/reset` | character | -- | remote | Reset aspect to defaults |
| 161 | GET | `/character/aspects/{id}/titles` | character | -- | remote | Available titles at rank |
| 162 | POST | `/character/aspects/{id}/title` | character | raw dict | remote | Set active title |
| 163 | GET | `/character/aspects/{id}/prompt-hints` | character | -- | remote | Personality prompt hints |
| 164 | GET | `/character/tutorial` | character | -- | remote | Tutorial progress |
| 165 | POST | `/character/tutorial/advance` | character | TutorialAdvance | remote | Advance tutorial step |
| 166 | POST | `/character/main-aspect` | character | MainAspectSet | remote | Set default aspect |
| 167 | GET | `/character/traits` | character | -- | remote | Personality trait metadata |
| 168 | GET | `/character/voice-params` | character | -- | remote | Voice parameter metadata |
| 169 | GET | `/character/earnable-titles` | character | -- | remote | All earnable titles |
| 170 | GET | `/platform/models` | workspace | -- | remote | Model list + benchmarks |
| 171 | GET | `/platform/plugins` | workspace | -- | remote | Plugin/skill status |
| 172 | GET | `/platform/knowledge` | workspace | -- | remote | Knowledge dashboard |
| 173 | GET | `/platform/projects` | workspace | -- | remote | Project context |
| 174 | GET | `/project_context` | workspace | -- | remote | Get project context |
| 175 | POST | `/project_context` | workspace | raw dict | remote | Set project context |
| 176 | GET | `/project_discovery` | workspace | -- | remote | Project discovery scan |
| 177 | GET | `/file_intent` | workspace | -- | remote | File analysis / intent |
| 178 | GET | `/file_content` | workspace | -- | remote | Read file (sandboxed) |
| 179 | POST | `/workspace/awareness/refresh` | workspace | raw dict | remote | Force project memory rescan |
| 180 | GET | `/workspace/project_memory` | workspace | -- | remote | View .layla/project_memory.json |
| 181 | GET | `/workspace/symbol_search` | workspace | -- | remote | Code symbol search |
| 182 | GET | `/v1/models` | openai_compat | -- | remote | OpenAI-compatible model list |
| 183 | POST | `/v1/chat/completions` | openai_compat | raw dict | remote | OpenAI-compatible chat |
| 184 | POST | `/agents/spawn` | agents | raw dict | remote | Spawn tiny agent worker |
| 185 | GET | `/agents/blackboard/{job_id}` | agents | -- | remote | Get shared blackboard data |
| 186 | POST | `/compact` | session | -- | remote | Compact conversation history |
| 187 | GET | `/ctx_viz` | session | -- | remote | Context budget visualization |
| 188 | GET | `/session/export` | session | -- | remote | Session data export |
| 189 | GET | `/system_export` | session | -- | remote | Full system state export |
| 190 | GET | `/learnings` | session | -- | remote | Paginated learnings list |
| 191 | DELETE | `/learnings/{learning_id}` | session | -- | remote | Delete learning |
| 192 | GET | `/audit` | session | -- | remote | Paginated audit log |
| 193 | GET | `/pending` | approvals | -- | remote | List pending approvals |
| 194 | POST | `/approve` | approvals | raw dict | remote | Approve pending action |
| 195 | POST | `/deny` | approvals | raw dict | remote | Deny pending action |
| 196 | GET | `/session/grants` | approvals | -- | remote | Active session grants |
| 197 | POST | `/session/grants/clear` | approvals | -- | remote | Revoke all session grants |
| 198 | POST | `/refresh_lens_knowledge` | approvals | -- | remote | Rebuild lens knowledge |
| 199 | POST | `/voice/transcribe` | voice | raw bytes | remote | STT: audio to text |
| 200 | POST | `/voice/speak` | voice | raw bytes/JSON | remote | TTS: text to audio/wav |
| 201 | GET | `/codex/relationship` | codex | -- | remote | Get relationship codex |
| 202 | PUT | `/codex/relationship` | codex | Body dict | remote | Replace relationship codex |
| 203 | GET | `/codex/proposals` | codex | -- | remote | List codex proposals |
| 204 | POST | `/codex/proposals/generate` | codex | Body dict | remote | Generate codex proposals |
| 205 | POST | `/codex/proposals/approve` | codex | -- | remote | Approve codex proposal |
| 206 | POST | `/codex/proposals/dismiss` | codex | -- | remote | Dismiss codex proposal |
| 207 | GET | `/journal` | journal | -- | remote | List journal entries |
| 208 | GET | `/journal/daily` | journal | -- | remote | Daily journal view |
| 209 | POST | `/journal` | journal | Body dict | remote | Add journal entry |
| 210 | GET | `/improvements` | improvements | -- | remote | List improvement proposals |
| 211 | POST | `/improvements/generate` | improvements | Body dict | remote | Generate improvement proposals |
| 212 | POST | `/improvements/approve_batch` | improvements | Body dict | remote | Approve improvements by ID |
| 213 | POST | `/improvements/reject` | improvements | Body dict | remote | Reject improvements by ID |
| 214 | GET | `/pairing/peers` | pairing | -- | remote | List mDNS-discovered peers |
| 215 | GET | `/pairing/status` | pairing | -- | remote | mDNS service status |
| 216 | POST | `/pairing/start` | pairing | -- | remote | Start mDNS broadcasting |
| 217 | POST | `/pairing/stop` | pairing | -- | remote | Stop mDNS service |
| 218 | POST | `/pairing/pair` | pairing | PairRequest | remote | Initiate pairing with PIN |
| 219 | POST | `/pairing/confirm` | pairing | ConfirmPairRequest | remote | Confirm pairing by PIN |
| 220 | GET | `/pairing/paired-devices` | pairing | -- | remote | List paired devices |
| 221 | DELETE | `/pairing/{instance_id}` | pairing | -- | remote | Unpair device |
| 222 | GET | `/pairing/peer/{id}/health` | pairing | -- | remote | Peer health check |
| 223 | POST | `/pairing/refresh` | pairing | -- | remote | Force peer discovery |
| 224 | PATCH | `/pairing/{instance_id}/permissions` | pairing | dict body | remote | Update device permissions |
| 225 | POST | `/obsidian/connect` | obsidian | raw dict | remote | Set Obsidian vault path |
| 226 | GET | `/obsidian/status` | obsidian | -- | remote | Vault connection status |
| 227 | GET | `/obsidian/diff` | obsidian | -- | remote | Dry-run sync diff |
| 228 | POST | `/obsidian/sync` | obsidian | raw dict | remote | Sync vault to knowledge |
| 229 | GET | `/obsidian/suggest` | obsidian | -- | remote | Suggest learnings for export |
| 230 | POST | `/obsidian/export` | obsidian | raw dict | remote | Export learnings to vault |
| 231 | GET | `/german/profile` | german | -- | remote | German learning profile |
| 232 | POST | `/german/profile/level` | german | raw dict | remote | Set CEFR level |
| 233 | POST | `/german/correct` | german | raw dict | remote | Correct German text |
| 234 | GET | `/german/corrections` | german | -- | remote | Correction history |
| 235 | GET | `/german/calibrate/{level}` | german | -- | remote | Calibration sentences |
| 236 | POST | `/german/calibrate` | german | raw dict | remote | Submit calibration answers |
| 237 | GET | `/german/flashcards/due` | german | -- | remote | Due flashcards |
| 238 | GET | `/german/flashcards/stats` | german | -- | remote | Flashcard deck stats |
| 239 | POST | `/german/flashcards` | german | raw dict | remote | Add flashcard |
| 240 | POST | `/german/flashcards/{id}/review` | german | raw dict | remote | Record review quality |
| 241 | DELETE | `/german/flashcards/{id}` | german | -- | remote | Delete flashcard |
| 242 | GET | `/tools/history` | tools_history | -- | remote | Tool call trace records |
| 243 | GET | `/tools/analysis` | tools_history | -- | remote | Tool health dashboard |
| 244 | GET | `/intelligence/info` | intelligence | -- | remote | All intelligence services status |
| 245 | GET | `/intelligence/airllm/info` | intelligence | -- | remote | AirLLM config status |
| 246 | POST | `/intelligence/airllm/generate` | intelligence | AirLLMGenerateRequest | remote | AirLLM text generation |
| 247 | POST | `/intelligence/airllm/chat` | intelligence | AirLLMChatRequest | remote | AirLLM chat generation |
| 248 | POST | `/intelligence/airllm/unload` | intelligence | -- | remote | Unload AirLLM model |
| 249 | POST | `/intelligence/compress` | intelligence | CompressRequest | remote | Compress text |
| 250 | POST | `/intelligence/compress/rag` | intelligence | CompressRAGRequest | remote | Compress RAG documents |
| 251 | POST | `/intelligence/optimize` | intelligence | OptimizeRequest | remote | Optimize user prompt |
| 252 | GET | `/intelligence/kb/info` | intelligence | -- | remote | KB builder status |
| 253 | POST | `/intelligence/kb/build/text` | intelligence | KBBuildFromTextRequest | remote | Build KB from text |
| 254 | POST | `/intelligence/kb/build/urls` | intelligence | KBBuildFromURLsRequest | remote | Build KB from URLs |
| 255 | POST | `/intelligence/kb/build/directory` | intelligence | KBBuildFromDirectoryRequest | remote | Build KB from directory |
| 256 | GET | `/intelligence/kb/articles` | intelligence | -- | remote | List KB articles |
| 257 | GET | `/intelligence/kb/articles/{id}` | intelligence | -- | remote | Get KB article |
| 258 | WS | `/ws` | ws | -- | WS auth | Main WebSocket endpoint |
| 259 | WS | `/ws/stream/{session_id}` | ws | -- | WS auth | Session-specific streaming |
| 260 | GET | `/ws/clients` | ws | -- | remote | List connected WS clients |
| 261 | GET | `/` | main.py | -- | none | Root UI (index.html) |
| 262 | GET | `/ui` | main.py | -- | none | Web UI |
| 263 | GET | `/manifest.json` | main.py | -- | none | PWA manifest |
| 264 | GET | `/sw.js` | main.py | -- | none | Service worker |
| 265 | GET | `/values.md` | main.py | -- | none | VALUES.md static |

**Total: 265 endpoints across 37 router files + main.py**

---

## 2. Router Mounting

All routers are mounted in `agent/main.py` via `app.include_router()`. The mounting is done in two waves, separated only by import order, not by any grouping logic.

### Mounting Order and Prefixes

| Router Module | Prefix | Tags | Mounting |
|---------------|--------|------|----------|
| `study` | (none) | `study` | `app.include_router(study.router)` |
| `system` | (none) | `system` | `app.include_router(system_router.router)` |
| `approvals` | (none) | `approvals` | `app.include_router(approvals.router)` |
| `agent` | (none) | `agent` | `app.include_router(agent_router.router)` -- sub-includes `learn` and `agent_tasks` |
| `agents` | `/agents` | `agents` | `app.include_router(agents_router.router)` |
| `research` | (none) | `research` | `app.include_router(research_router.router)` |
| `memory` | `/memory` | `memory` | `app.include_router(memory_router.router)` |
| `autonomous` | (none) | `autonomous` | `app.include_router(autonomous_router.router)` |
| `codex` | `/codex` | `codex` | `app.include_router(codex_router.router)` |
| `aspects` | (none) | `aspects` | `app.include_router(aspects_router.router)` |
| `journal` | (none) | `journal` | `app.include_router(journal_router.router)` |
| `improvements` | (none) | `improvements` | `app.include_router(improvements_router.router)` |
| `projects` | (none) | `projects` | `app.include_router(projects_router.router)` |
| `plans` | `/plans` | `plans` | `app.include_router(plans_router.router)` |
| `plan_file` | `/plan` | `plan-file` | `app.include_router(plan_file_router.router)` |
| `settings` | (none) | `settings` | `app.include_router(settings_router.router)` |
| `session` | (none) | `session` | `app.include_router(session_router.router)` |
| `conversations` | (none) | `conversations` | `app.include_router(conversations_router.router)` |
| `knowledge` | (none) | `knowledge` | `app.include_router(knowledge_router.router)` |
| `workspace` | (none) | `workspace` | `app.include_router(workspace_router.router)` |
| `openai_compat` | (none) | `openai` | `app.include_router(openai_compat_router.router)` |
| `missions` | (none) | `missions` | `app.include_router(missions_router.router)` |
| `voice` | (none) | `voice` | `app.include_router(voice_router.router)` |
| `tools_history` | (none) | `tools` | `app.include_router(tools_history_router.router)` |
| `search` | (none) | `search` | `app.include_router(search_router.router)` |
| `obsidian` | (none) | `obsidian` | `app.include_router(obsidian_router.router)` |
| `german` | `/german` | `german` | `app.include_router(german_router.router)` |
| `agent_tasks` | (none) | `agent` | sub-included by `agent` router |
| `sync` | `/sync` | `sync` | `app.include_router(sync_router.router)` |
| `pairing` | `/pairing` | `pairing` | `app.include_router(pairing_router.router)` |
| `intelligence` | `/intelligence` | `intelligence` | `app.include_router(intelligence_router.router)` |
| `debate` | (none) | `debate` | `app.include_router(debate_router.router)` |
| `metrics` | (none) | `metrics` | `app.include_router(metrics_router.router)` |
| `character` | `/character` | `character` | `app.include_router(character_router.router)` |
| `ws` | (none) | `websocket` | `app.include_router(ws_router.router)` |

### Sub-router Inclusion

The `agent` router includes two child routers via `router.include_router()`:
- `learn.router` -- provides `/memories`, `/schedule`, `/learn/`
- `agent_tasks.router` -- provides `/resume`, `/execute_plan`, `/agent/background`, `/agent/tasks/*`

### Static Mounts

- `/docs` -- static file mount from `docs/` directory
- `/layla-ui` -- static file mount from `agent/ui/` directory

---

## 3. Authentication

### Architecture

Authentication is **optional and conditional**. It only activates when `remote_enabled: true` is set in `runtime_config.json`. Localhost connections are always allowed through without auth.

### HTTP Middleware

Defined in `main.py` as `remote_auth_middleware`:

1. **Checks `remote_enabled`** in runtime config. If false, passes through.
2. **Checks client IP** via `_is_localhost()`. If localhost, passes through.
3. **Extracts Bearer token** from `Authorization` header.
4. **Calls `services.auth.check_auth()`** with token, client host, and config.
5. **Checks endpoint allowlist** via `_remote_allowed_paths()`. Returns 403 if path not allowed.
6. **Audit logging** when `tunnel_audit_enabled` is set.

Returns 401 for missing/invalid token, 403 for endpoints not on the allowlist.

### WebSocket Auth

The `ws.py` router has its own `_ws_check_auth()` function:
- Reads `token` query parameter (not Bearer header)
- Uses the same `services.auth.check_auth()` logic
- Closes socket with code 4003 on failure

### Rate Limiting

A second middleware `remote_rate_limit_middleware` applies per-IP rate limits for non-localhost connections. Configurable via `remote_rate_limit_per_minute` (default: 100).

### Endpoint Allowlist

When `remote_mode: "interactive"`, these paths are allowed remotely: `/wakeup`, `/project_discovery`, `/health`, `/agent`, `/v1/chat/completions`, `/learn/`, `/memories`, `/schedule`, `/conversations`, `/settings`, `/approve`, `/pending`, and many more (see `_remote_allowed_paths()` in main.py).

When `remote_mode: "observe"` (default), only `/wakeup`, `/project_discovery`, `/health` are allowed.

### Per-Endpoint Auth

No individual endpoint has its own auth decorator. All auth is done at the middleware level. The `autonomous.py` router duplicates the localhost and allowlist checks internally as a defense-in-depth measure, but this is redundant with the middleware.

### Known Auth Issues

- **No per-endpoint granularity**: All allowed endpoints share the same token. There is no role-based access control.
- **WebSocket token via query param**: The WS token is visible in server logs and browser history since it travels as `?token=`.
- **Autonomous router duplicates auth**: The `/autonomous/run` handler re-checks localhost and allowlist independently, which can drift from the middleware version.

---

## 4. WebSocket

### Endpoints

| Endpoint | Purpose |
|----------|---------|
| `WS /ws` | Main bidirectional channel |
| `WS /ws/stream/{session_id}` | Session-specific streaming |
| `GET /ws/clients` | List connected clients (REST) |

### Connection Lifecycle

1. Client connects with optional query params: `client_id` (UUID default), `room` (default "general").
2. Server authenticates (see above), then accepts and sends a `welcome` JSON.
3. Client sends JSON messages. Server dispatches through `services.ws_manager.ConnectionManager.handle_client_message()`.
4. On disconnect or error, the connection manager cleans up.

### Message Format

**Server-to-client messages:**
```json
{"type": "welcome", "client_id": "...", "room": "...", "message": "Connected to Layla WebSocket."}
{"type": "error", "message": "Malformed JSON payload."}
```

**Client-to-server:** Any JSON object. Dispatched to the connection manager's `handle_client_message()` method. The specific message types are defined in `services/ws_manager.py` (not in the router itself).

### Session Streaming

The `/ws/stream/{session_id}` endpoint subscribes the client to a specific room identified by session_id. Broadcasts targeting that session reach only subscribers in that room.

---

## 5. Input Validation

### Pydantic-Validated Endpoints

The following endpoints use typed Pydantic `BaseModel` request bodies (FastAPI returns 422 on validation failure):

| Model | Endpoints | Key Constraints |
|-------|-----------|-----------------|
| `AgentRequest` | `POST /agent` | `message` max 100K chars, `aspect_id` max 64, `image_base64` max 10M |
| `DebateRequest` | `POST /debate` | `goal` required (min 1 char), `mode` validated against enum |
| `LearnRequest` | `POST /learn/` | `content` required (min 1 char), `type` max 50 chars |
| `ScheduleRequest` | `POST /schedule` | `tool_name` required, `delay_seconds` 0-86400 |
| `SteerRequest` | `POST /agent/steer` | `hint`/`steer`/`message` max 10K |
| `AddDeviceRequest` | `POST /sync/add-device` | `device_id` required |
| `PairRequest` | `POST /pairing/pair` | `instance_id` required |
| `ConfirmPairRequest` | `POST /pairing/confirm` | `pin` and `instance_id` required |
| `AspectCustomization` | `PATCH /character/aspects/{id}` | All fields optional, typed |
| `TutorialAdvance` | `POST /character/tutorial/advance` | `step` ge=0, le=99 |
| `MainAspectSet` | `POST /character/main-aspect` | `aspect_id` required |
| `AirLLMGenerateRequest` | `POST /intelligence/airllm/generate` | `prompt` required, `max_tokens` 1-8192 |
| `AirLLMChatRequest` | `POST /intelligence/airllm/chat` | `messages` required |
| `CompressRequest` | `POST /intelligence/compress` | `text` required, `target_ratio` 0.05-0.95 |
| `CompressRAGRequest` | `POST /intelligence/compress/rag` | `documents` and `query` required |
| `OptimizeRequest` | `POST /intelligence/optimize` | `message` required |
| `KBBuildFromTextRequest` | `POST /intelligence/kb/build/text` | `texts` required |
| `KBBuildFromURLsRequest` | `POST /intelligence/kb/build/urls` | `urls` required |
| `KBBuildFromDirectoryRequest` | `POST /intelligence/kb/build/directory` | `directory` required |

### Pydantic Response Models (sync router)

The `sync` router uses response models (`response_model=SyncStatusResponse` etc.) on its endpoints, which is the only router doing so.

### Raw Dict Endpoints

The majority of POST endpoints accept `raw dict` bodies with manual validation (if any). These endpoints parse `request.json()` directly and do ad-hoc string checks. About **75% of POST endpoints** use this pattern. Examples: `/research_mission`, `/autonomous/run`, `/plans`, `/conversations/{id}/rename`, all `study_plans/*` endpoints.

### Endpoints with No Input Validation

Many GET endpoints accept query parameters without range validation beyond what FastAPI's `Query()` provides. Most POST endpoints that accept raw dicts do minimal type checking (e.g., checking if a field is a string or empty) but do not validate field lengths, character sets, or structure.

---

## 6. Error Handling

### Status Code Usage

**Endpoints that return proper HTTP error codes:**

| Code | Usage | Examples |
|------|-------|---------|
| 400 | Missing/invalid input | `/agent` (empty message), `/plans` (goal required), `/autonomous/run` (missing goal) |
| 401 | Auth failure | Middleware (invalid token) |
| 403 | Forbidden | Middleware (endpoint not allowed), `/autonomous/run` (disabled), `/file_content` (outside sandbox) |
| 404 | Not found | `/plans/{id}`, `/conversations/{id}`, `/mission/{id}`, `/projects/{id}` |
| 409 | Conflict | `/plans/{id}` (plan not editable), `/plans/{id}/execute` (not approved) |
| 410 | Gone | `/approve` (expired approval) |
| 413 | Payload too large | `/memory/import` (100MB), `/file_content` (500KB) |
| 429 | Rate limited | Middleware (too many requests) |
| 500 | Internal error | Most endpoints wrap exceptions in 500 |
| 503 | Service unavailable | `/agent` (no model), `/voice/transcribe` (STT not ready), `/health` (degraded) |

**Endpoints that always return 200 (even on error):**

Several endpoints return error information inside a 200 response body with `{"ok": false, "error": "..."}`:
- `POST /learn/` -- catches exceptions and returns `{"ok": false}` with status 200
- `GET /wakeup` -- always returns 200 (errors are absorbed into the greeting)
- `GET /capabilities` -- returns error inside 200 response
- Several study plan endpoints return errors inside `{"ok": false}` with 200
- `POST /compact` -- always returns result dict at 200
- Most `/remote/tailscale/*` and tunnel endpoints return error info at 200

### Error Response Shape

There is no unified error envelope. At least four patterns co-exist:

1. **`{"ok": false, "error": "message"}`** -- most common
2. **`{"error": "message"}`** -- missions, some system endpoints
3. **FastAPI 422 JSON** -- Pydantic validation failures (automatic)
4. **`{"ok": false, "error": "code", "detail": "human message"}`** -- middleware, plans

---

## 7. Dead Endpoints

Endpoints that appear mounted but have limited or no evidence of being called by the UI or other internal code:

| Endpoint | Router | Assessment |
|----------|--------|------------|
| `GET /memory/elasticsearch/search` | memory | Requires optional Elasticsearch; no UI calls it |
| `POST /memory/file_checkpoints/restore` | memory | UI would need to list checkpoints first; no UI component found |
| `GET /memory/file_checkpoints` | memory | Supporting endpoint for restore; likely unused |
| `GET /agents/blackboard/{job_id}` | agents | Shared blackboard for multi-agent; feature appears incomplete |
| `POST /refresh_lens_knowledge` | approvals | Legacy endpoint from earlier architecture |
| `GET /rl/preferences` | system | RL preference table; experiment-stage feature |
| `GET /aspects/reload` | system | Admin-only hot-reload; useful but no UI trigger |
| `GET /debug/state` | system | Developer debugging only |
| `GET /debug/tasks` | system | Developer debugging only |
| `POST /agent/persistent_tasks/{task_id}/resume` | agent_tasks | Coordinator resume; may only be called programmatically |
| `GET /research_mission/debug` | research | Developer debugging only |
| `GET /research_brain/file` | research | Requires specific file path knowledge |

---

## 8. Known Issues

### 8.1 Path Shadowing

**`GET /aspects/{aspect_id}` is defined twice:**
- In `aspects.py` -- returns full character sheet metadata from orchestrator
- In `study.py` as `GET /aspects/{aspect_id}/title` -- different endpoint, no shadow
- In `character.py` as `GET /character/aspects/{aspect_id}` -- different prefix, no shadow

The `aspects.py` `GET /aspects/{aspect_id}` and the `system.py` `GET /aspects/reload` could shadow each other since `reload` would match as an `aspect_id`. FastAPI resolves this by registration order (system is mounted first), so `/aspects/reload` takes priority. However, this is fragile.

### 8.2 Duplicate Learnings Delete

`DELETE /learnings/{learning_id}` exists in both:
- `session.py` at path `/learnings/{learning_id}`
- `memory.py` at path `/memory/{learning_id}`

These are different paths so they do not shadow, but the logic is duplicated. Both delete from SQLite and attempt Chroma cleanup.

### 8.3 Missing Validation

- **`POST /research_mission`**: Accepts any JSON body with no validation of `workspace_root`, `mission_type`, or `mission_depth` beyond basic string checks.
- **`POST /research`**: Accepts raw `dict` with no Pydantic model. The `repo_path` parameter is not sandboxed.
- **`POST /autonomous/run`**: Validates `goal` and `confirm_autonomous` but accepts arbitrary `max_steps` and `timeout_seconds` without upper bounds.
- **`POST /approve`**: The `grant_pattern` field is user-supplied and stored directly as a tool permission grant without sanitization.
- **`POST /settings`**: Accepts arbitrary JSON and merges it into runtime_config.json. Only the helper function does schema validation.
- **`POST /knowledge/import_chat`**: The `title` parameter undergoes character sanitization for filesystem safety but the `text` payload is only size-checked at 8MB.

### 8.4 Missing Auth on Specific Sensitive Endpoints

All auth is at the middleware level based on the path allowlist. The following endpoints are sensitive but may be on the "interactive" allowlist:

- `POST /settings` -- can change runtime config
- `POST /approve` -- executes tools
- `POST /update/apply` -- runs git pull
- `POST /remote/token/rotate` -- generates new auth token
- `POST /settings/install_feature` -- runs pip install

### 8.5 Inconsistent Error Shapes

As documented in section 6, there is no standard error envelope. Clients must handle at least four different shapes. This makes UI error handling fragile.

### 8.6 Token Usage Approximation

The OpenAI-compatible endpoint (`/v1/chat/completions`) reports token usage using `len(text.split())`, which is a word count, not an actual token count. This is misleading for clients expecting real usage data.

### 8.7 SSRF Partial Mitigation

The `/agent` endpoint's image URL fetcher has SSRF checks (blocking private IPs, localhost) but the check is in a try/except that silently continues on failure, meaning malformed URLs could bypass the check. The `else` clause only runs on success, but the overall pattern is fragile.

### 8.8 Autonomous Router Duplicates Main.py Auth Logic

The `autonomous.py` router has its own `_is_localhost()` and `_remote_allowed_paths()` functions copied from main.py. These can drift out of sync.

---

## 9. Stability Assessment

| Router | File | Endpoints | Stability | Notes |
|--------|------|-----------|-----------|-------|
| agent | `agent.py` | 3 | **STABLE** | Core chat path; heavily tested; uses Pydantic; streaming mature |
| learn | `learn.py` | 3 | **STABLE** | Simple CRUD; Pydantic models; correct error codes |
| ws | `ws.py` | 3 | **STABLE** | Clean connection lifecycle; proper auth; uses manager pattern |
| memory | `memory.py` | 6 | **STABLE** | ZIP export/import well-guarded; Zip-slip protection; size limits |
| debate | `debate.py` | 2 | **STABLE** | Pydantic input; clean error handling |
| plans | `plans.py` | 7 | **STABLE** | Full CRUD + execute lifecycle; proper status codes (404, 409) |
| plan_file | `plan_file.py` | 6 | **STABLE** | File-backed plans; proper validation; governance checks |
| research | `research.py` | 7 | **FRAGILE** | Raw dict inputs; no workspace sandbox check on `/research`; long-running with no timeout config |
| autonomous | `autonomous.py` | 1 | **STABLE** | Feature-gated; requires confirmation; duplicated auth is defense-in-depth |
| study | `study.py` | 10 | **STABLE** | Well-structured; used by wakeup flow daily |
| settings | `settings.py` | 14 | **STABLE** | Core setup wizard; model download SSE works; uses config schema |
| conversations | `conversations.py` | 9 | **STABLE** | Full CRUD; proper 404s; FTS search |
| knowledge | `knowledge.py` | 6 | **STABLE** | Ingestion pipeline; sandbox checks |
| search | `search.py` | 1 | **STABLE** | Clean multi-source aggregation |
| sync | `sync.py` | 5 | **STABLE** | Pydantic models everywhere; graceful degradation when Syncthing absent |
| metrics | `metrics.py` | 2 | **STABLE** | Simple Prometheus passthrough |
| system | `system.py` | 40+ | **FRAGILE** | Kitchen-sink router; too many concerns (health, tunnels, updates, RL, models, debug); should be split |
| projects | `projects.py` | 5 | **STABLE** | Clean CRUD; proper status codes |
| missions | `missions.py` | 8 | **STABLE** | Full lifecycle management; proper state machine |
| character | `character.py` | 14 | **STABLE** | Pydantic models; well-structured REST API |
| workspace | `workspace.py` | 12 | **STABLE** | Sandbox enforcement consistent |
| session | `session.py` | 6 | **STABLE** | Export and audit; straightforward |
| approvals | `approvals.py` | 6 | **STABLE** | Thread-safe with `_approve_lock`; expiry handling |
| voice | `voice.py` | 2 | **STABLE** | Graceful 503 when STT/TTS unavailable; recovery hints |
| codex | `codex.py` | 6 | **STABLE** | Sandbox-aware; workspace validation |
| journal | `journal.py` | 3 | **STABLE** | Simple CRUD wrapper |
| aspects | `aspects.py` | 1 | **FRAGILE** | Path could shadow `aspects/reload` from system router |
| improvements | `improvements.py` | 4 | **STABLE** | Simple proposal lifecycle |
| pairing | `pairing.py` | 10 | **STABLE** | Pydantic models; PIN-based pairing; cryptographic secrets |
| obsidian | `obsidian.py` | 6 | **STABLE** | Clean sync lifecycle; graceful degradation |
| paths | `paths.py` | 0 | **STABLE** | Constants-only module; no endpoints |
| openai_compat | `openai_compat.py` | 2 | **FRAGILE** | Token usage is fake (word count); no model validation beyond name parse; large code duplication with agent.py |
| agents | `agents.py` | 2 | **INCOMPLETE** | Blackboard feature appears unfinished; spawn works but lacks lifecycle management |
| agent_tasks | `agent_tasks.py` | 7 | **STABLE** | Background task lifecycle; cancel support; DB persistence |
| tools_history | `tools_history.py` | 2 | **STABLE** | Clean aggregation queries |
| intelligence | `intelligence.py` | 12 | **STABLE** | Pydantic everywhere; graceful 503; well-documented |
| german | `german.py` | 11 | **STABLE** | Complete learning module; SRS flashcards; calibration |

### Summary

| Rating | Count | Percentage |
|--------|-------|------------|
| STABLE | 30 | 83% |
| FRAGILE | 4 | 11% |
| INCOMPLETE | 1 | 3% |
| DEAD | 0 | 0% |
| Constants-only | 1 | 3% |

---

## 10. Architectural Observations

### 10.1 Router Size Distribution

The `system.py` router is by far the largest with 40+ endpoints spanning health checks, remote tunneling, Tailscale VPN, updates, debugging, model providers, skill packs, RL preferences, and more. It should be decomposed into at least 4 focused routers: `health`, `remote`, `models`, and `debug`.

### 10.2 Prefix Inconsistency

Some routers define their prefix at the router level (e.g., `plans` uses `prefix="/plans"`, `sync` uses `prefix="/sync"`), while others define paths in each endpoint decorator (e.g., `research` uses `/research_mission`, `/research`). This means the API has no consistent URL hierarchy.

### 10.3 Input Validation Coverage

Only about 25% of POST endpoints use Pydantic request models. The rest accept raw dicts with manual validation. The Pydantic-validated endpoints are concentrated in the newer routers (agent, debate, sync, pairing, character, intelligence).

### 10.4 Middleware Stack

The middleware stack in `main.py` is:
1. **GZipMiddleware** (responses > 500 bytes)
2. **CORSMiddleware** (only when `remote_cors_origins` configured)
3. **`remote_auth_middleware`** (bearer token + endpoint allowlist)
4. **`remote_rate_limit_middleware`** (per-IP rate limit)
5. **`trace_id_middleware`** (optional X-Trace-Id header)

Middleware ordering matters: rate limiting runs before auth, which means unauthenticated clients still consume rate limit tokens. This is arguably correct (prevents brute-force) but is worth noting.

### 10.5 Streaming Patterns

Two streaming patterns exist:
1. **SSE (Server-Sent Events)** via `StreamingResponse` with `text/event-stream` -- used by `/agent` (streaming mode), `/research` (streaming mode), `/v1/chat/completions` (streaming mode), `/setup/download`.
2. **WebSocket** -- used for persistent bidirectional communication via `/ws`.

Both SSE endpoints include keepalive pulses (`{"pulse": true}`) to prevent connection timeouts. The pulse interval is configurable via `ui_stream_keepalive_seconds` (default 20s).

### 10.6 The Agent Router as Gateway

The `POST /agent` endpoint is the system's primary gateway. A single request can trigger:
- Image processing (OCR/description)
- Response caching
- Plan generation
- Understand mode (repo scanning)
- Engineering pipeline
- Full autonomous run with tool calls
- Streaming token generation
- Conversation persistence
- Maturity XP award

This makes the endpoint a 1000+ line monolith. The `_dispatch_autonomous_run()` function delegates to `services.coordinator.run()` which wraps the actual agent loop.
