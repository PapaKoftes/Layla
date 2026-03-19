# Audit — OpenClaw core emulation (2026-03-19)

## Automated

`cd agent && python -m pytest tests/ -q` — **146 passed**, 1 skipped.

New coverage: `tests/test_openclaw_emulation.py` (tool policy, loop detection, HTTP cache, shell session blocklist, markdown skills, fallback URL list).

## Deliverables

| Area | Files |
|------|--------|
| Tool policy | `agent/services/tool_policy.py`, `agent_loop` integration |
| Loop detection | `agent/services/tool_loop_detection.py` |
| Shell sessions | `agent/services/shell_sessions.py`, `shell_session_start` / `shell_session_manage` |
| HTTP cache | `agent/services/http_response_cache.py`, `fetch_url_tool`, `ddg_search` |
| Browser profiles | `agent/services/browser.py` (`browser_persistent_profiles`), `.gitignore` `agent/.browser_profiles/` |
| Markdown skills | `agent/services/markdown_skills.py`, `skills/README.md`, planner via `get_skills_prompt_hint` |
| Memory aliases | `memory_search`, `memory_get` |
| Model extras | `structured_llm_task`, `inference_fallback_urls`, `image_model` for `describe_image` |
| Config | `agent/runtime_safety.py` defaults, `agent/runtime_config.example.json` |
| Docs | `docs/OPENCLAW_ALIGNMENT.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_STATUS.md`, `RUNBOOKS.md` |

## Notes

- `markdown_skills_watch` is reserved; no file watcher yet.
- `image_generation_model` is config-only placeholder (no new generation tool in this pass).
- OpenAI-compatible **streaming** still uses primary URL only (fallbacks apply to non-stream).
