# Audit rubric (Layla)

Use this for **engineering** self-review and release gates. Scores are **evidence-based**: cite files, tests, or manual steps. A “9+” target means **all P0/P1 rows are satisfied**, not a claim about model cognition.

## Scoring

| Score | Meaning |
|-------|---------|
| 1–3 | Missing or broken |
| 4–6 | Partial / flaky |
| 7–8 | Good; minor gaps documented |
| 9–10 | Green with evidence (tests or recorded checks) |

## Categories

### P0 — Safety gates

| Item | Evidence |
|------|----------|
| Tool writes / shell gated by approval + allow flags | `agent/layla/tools/registry.py`, `test_approval_flow.py`, `test_golden_flow_http.py` |
| Pending queue + approve path | `routers/approvals.py`, `shared_state.py` |
| No secrets in committed config | `.gitignore` on `runtime_config.json` |

### P1 — Privacy & data

| Item | Evidence |
|------|----------|
| Local-first defaults documented | `PROJECT_BRAIN.md`, `VALUES.md` |
| Session export for operator backup | `GET /session/export` in `main.py` |
| Knowledge / DB git policy | `.gitignore`, `AGENTS.md` |

### P1 — UX flows

| Item | Evidence |
|------|----------|
| Multi-chat + conversation APIs | `/conversations*`, UI rail |
| Projects API + agent `project_id` | `/projects`, `routers/agent.py` |
| Help / shortcuts discoverable | Web UI Help tab |

### P2 — Model / config

| Item | Evidence |
|------|----------|
| Config load single source | `runtime_safety.load_config()` |
| Health exposes limits / deps | `GET /health`, `test_health_endpoint.py` |

### P2 — Performance

| Item | Evidence |
|------|----------|
| Context / token pressure documented | `docs/CORE_LOOP.md`, `context_manager` |
| Scheduler / study opt-out | `runtime_config.example.json` |

## Sign-off template

- Date:
- Version / commit:
- P0 result:
- P1 result:
- Open exceptions (with ticket/docs):
