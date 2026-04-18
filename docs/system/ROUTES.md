# FastAPI routes (inventory)

Mounted from [`agent/main.py`](../../agent/main.py) unless noted. Router **`prefix`** adds to each route below.

## App (`main.py`)

| Method | Path |
|--------|------|
| GET | `/values.md` |
| GET | `/sw.js` |
| GET | `/manifest.json` |
| GET | `/ui` |
| GET | `/` |
| (mount) | `/docs` — static when `docs/` exists |
| (mount) | `/layla-ui` — static `agent/ui` |

## Routers (no prefix unless stated)

| Method | Path | Module |
|--------|------|--------|
| GET | `/agent/decision_trace` | `routers/agent.py` |
| POST | `/agent/steer` | `routers/agent.py` |
| POST | `/agent` | `routers/agent.py` |
| POST | `/resume` | `routers/agent_tasks.py` |
| POST | `/agent/persistent_tasks/{task_id}/resume` | `routers/agent_tasks.py` |
| POST | `/execute_plan` | `routers/agent_tasks.py` |
| POST | `/agent/background` | `routers/agent_tasks.py` |
| GET | `/agent/tasks` | `routers/agent_tasks.py` |
| GET | `/agent/tasks/{task_id}` | `routers/agent_tasks.py` |
| DELETE | `/agent/tasks/{task_id}` | `routers/agent_tasks.py` |
| POST | `/agent/tasks/{task_id}/cancel` | `routers/agent_tasks.py` |
| GET | `/memories` | `routers/learn.py` |
| POST | `/schedule` | `routers/learn.py` |
| POST | `/learn/` | `routers/learn.py` |
| GET | `/pending` | `routers/approvals.py` |
| POST | `/approve` | `routers/approvals.py` |
| POST | `/deny` | `routers/approvals.py` |
| GET | `/session/grants` | `routers/approvals.py` |
| POST | `/session/grants/clear` | `routers/approvals.py` |
| POST | `/refresh_lens_knowledge` | `routers/approvals.py` |
| POST | `/autonomous/run` | `routers/autonomous.py` |
| POST | `/research_mission` | `routers/research.py` |
| GET | `/research_mission/state` | `routers/research.py` |
| GET | `/research_output/last` | `routers/research.py` |
| GET | `/research_brain/file` | `routers/research.py` |
| GET | `/research_mission/debug` | `routers/research.py` |
| GET | `/research_mission/verify` | `routers/research.py` |
| POST | `/research` | `routers/research.py` |
| GET | `/debug/state` | `routers/system.py` |
| GET | `/debug/tasks` | `routers/system.py` |
| GET | `/usage` | `routers/system.py` |
| GET | `/history` | `routers/system.py` |
| GET | `/skills` | `routers/system.py` |
| GET | `/version` | `routers/system.py` |
| GET | `/update/check` | `routers/system.py` |
| POST | `/update/apply` | `routers/system.py` |
| POST | `/undo` | `routers/system.py` |
| GET | `/health` | `routers/system.py` |
| GET | `/health/deps` | `routers/system.py` |
| GET | `/local_access_info` | `routers/system.py` |
| GET | `/doctor` | `routers/system.py` |
| GET | `/doctor/capabilities` | `routers/system.py` |
| GET | `/session/stats` | `routers/system.py` |
| POST | `/remote/tunnel/start` | `routers/system.py` |
| GET | `/remote/tunnel/status` | `routers/system.py` |
| POST | `/remote/tunnel/stop` | `routers/system.py` |
| GET | `/skill_packs` | `routers/system.py` |
| POST | `/skill_packs/install` | `routers/system.py` |
| POST | `/skill_packs/remove` | `routers/system.py` |
| GET | `/setup_status` | `routers/settings.py` |
| GET | `/setup/models` | `routers/settings.py` |
| GET | `/setup/download` | `routers/settings.py` |
| GET | `/settings` | `routers/settings.py` |
| GET | `/settings/schema` | `routers/settings.py` |
| GET | `/settings/appearance` | `routers/settings.py` |
| POST | `/settings/appearance` | `routers/settings.py` |
| POST | `/settings` | `routers/settings.py` |
| POST | `/settings/preset` | `routers/settings.py` |
| POST | `/setup/auto` | `routers/settings.py` |
| GET | `/settings/optional_features` | `routers/settings.py` |
| POST | `/settings/install_feature` | `routers/settings.py` |
| POST | `/settings/git_undo_checkpoint` | `routers/settings.py` |
| GET | `/operator/quiz/stage/{stage_idx}` | `routers/settings.py` |
| POST | `/operator/quiz/submit` | `routers/settings.py` |
| GET | `/operator/profile` | `routers/settings.py` |
| POST | `/operator/profile/stat` | `routers/settings.py` |
| POST | `/compact` | `routers/session.py` |
| GET | `/ctx_viz` | `routers/session.py` |
| GET | `/session/export` | `routers/session.py` |
| GET | `/system_export` | `routers/session.py` |
| GET | `/learnings` | `routers/session.py` |
| DELETE | `/learnings/{learning_id}` | `routers/session.py` |
| GET | `/audit` | `routers/session.py` |
| POST | `/conversations` | `routers/conversations.py` |
| GET | `/conversations` | `routers/conversations.py` |
| GET | `/conversations/search` | `routers/conversations.py` |
| POST | `/conversations/{conversation_id}/tags` | `routers/conversations.py` |
| GET | `/conversations/tags/suggest` | `routers/conversations.py` |
| GET | `/conversations/{conversation_id}` | `routers/conversations.py` |
| GET | `/conversations/{conversation_id}/messages` | `routers/conversations.py` |
| POST | `/conversations/{conversation_id}/rename` | `routers/conversations.py` |
| DELETE | `/conversations/{conversation_id}` | `routers/conversations.py` |
| GET | `/knowledge/ingest/sources` | `routers/knowledge.py` |
| POST | `/knowledge/ingest` | `routers/knowledge.py` |
| POST | `/workspace/index` | `routers/knowledge.py` |
| POST | `/workspace/cognition/sync` | `routers/knowledge.py` |
| GET | `/workspace/cognition` | `routers/knowledge.py` |
| POST | `/knowledge/import_chat_preview` | `routers/knowledge.py` |
| POST | `/knowledge/import_chat` | `routers/knowledge.py` |
| GET | `/platform/models` | `routers/workspace.py` |
| GET | `/platform/plugins` | `routers/workspace.py` |
| GET | `/platform/knowledge` | `routers/workspace.py` |
| GET | `/platform/projects` | `routers/workspace.py` |
| GET | `/project_context` | `routers/workspace.py` |
| GET | `/file_intent` | `routers/workspace.py` |
| POST | `/project_context` | `routers/workspace.py` |
| GET | `/project_discovery` | `routers/workspace.py` |
| POST | `/workspace/awareness/refresh` | `routers/workspace.py` |
| GET | `/workspace/project_memory` | `routers/workspace.py` |
| GET | `/workspace/symbol_search` | `routers/workspace.py` |
| GET | `/file_content` | `routers/workspace.py` |
| GET | `/v1/models` | `routers/openai_compat.py` |
| POST | `/v1/chat/completions` | `routers/openai_compat.py` |
| POST | `/mission` | `routers/missions.py` |
| GET | `/mission/{mission_id}` | `routers/missions.py` |
| GET | `/missions` | `routers/missions.py` |
| POST | `/voice/transcribe` | `routers/voice.py` |
| POST | `/voice/speak` | `routers/voice.py` |
| GET | `/journal` | `routers/journal.py` |
| GET | `/journal/daily` | `routers/journal.py` |
| POST | `/journal` | `routers/journal.py` |
| GET | `/improvements` | `routers/improvements.py` |
| POST | `/improvements/generate` | `routers/improvements.py` |
| POST | `/improvements/approve_batch` | `routers/improvements.py` |
| POST | `/improvements/reject` | `routers/improvements.py` |
| GET | `/projects` | `routers/projects.py` |
| POST | `/projects` | `routers/projects.py` |
| GET | `/projects/{project_id}` | `routers/projects.py` |
| PATCH | `/projects/{project_id}` | `routers/projects.py` |
| DELETE | `/projects/{project_id}` | `routers/projects.py` |
| GET | `/aspects/{aspect_id}` | `routers/aspects.py` |
| GET | `/study_plans/presets` | `routers/study.py` |
| GET | `/study_plans/suggestions` | `routers/study.py` |
| POST | `/study_plans/derive_topic` | `routers/study.py` |
| GET | `/study_plans` | `routers/study.py` |
| DELETE | `/study_plans/{plan_id}` | `routers/study.py` |
| GET | `/capabilities` | `routers/study.py` |
| POST | `/study_plans` | `routers/study.py` |
| POST | `/study_plans/record_progress` | `routers/study.py` |
| GET | `/wakeup` | `routers/study.py` |
| GET | `/aspects/{aspect_id}/title` | `routers/study.py` |
| POST | `/aspects/{aspect_id}/title` | `routers/study.py` |

## Prefix `/plans`

| Method | Path |
|--------|------|
| POST | `/plans` |
| GET | `/plans` |
| GET | `/plans/{plan_id}` |
| PATCH | `/plans/{plan_id}` |
| POST | `/plans/{plan_id}/approve` |
| POST | `/plans/{plan_id}/execute` |

(`routers/plans.py`)

## Prefix `/plan`

| Method | Path |
|--------|------|
| POST | `/plan/create` |
| GET | `/plan/{plan_id}` |
| POST | `/plan/{plan_id}/approve` |
| POST | `/plan/{plan_id}/add_steps` |
| POST | `/plan/{plan_id}/execute_next` |
| POST | `/plan/{plan_id}/run_continuous` |

(`routers/plan_file.py`)

## Prefix `/memory`

| Method | Path |
|--------|------|
| GET | `/memory/stats` |
| GET | `/memory/export` |
| POST | `/memory/import` |
| GET | `/memory/elasticsearch/search` |
| GET | `/memory/file_checkpoints` |
| POST | `/memory/file_checkpoints/restore` |

(`routers/memory.py`)

## Prefix `/codex`

| Method | Path |
|--------|------|
| GET | `/codex/relationship` |
| PUT | `/codex/relationship` |
| GET | `/codex/proposals` |
| POST | `/codex/proposals/generate` |
| POST | `/codex/proposals/approve` |
| POST | `/codex/proposals/dismiss` |

(`routers/codex.py`)

## Prefix `/agents`

| Method | Path |
|--------|------|
| GET | `/agents/blackboard/{job_id}` |
| POST | `/agents/spawn` |

(`routers/agents.py`)
