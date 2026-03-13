# Missions — Long-Running Agent Tasks (v1.1)

Missions let Layla run research or engineering tasks asynchronously. A mission is created from a goal, decomposed into steps by the planner, and executed one step at a time in the background. Progress is persisted so missions survive server restarts.

---

## Mission Lifecycle

1. **Create** — `POST /mission` with `{"goal": "..."}`. The planner produces 3–6 steps.
2. **Pending** — Mission is stored, status `pending`. Call `run_mission(id)` or `POST /mission` auto-starts it.
3. **Running** — `mission_worker` (APScheduler) executes one step per run. Each step calls `autonomous_run` with the step goal.
4. **Completed** — All steps done, or `max_mission_steps` reached. Status set to `completed`.
5. **Failed** — Error during a step, or `max_mission_runtime` exceeded. Status set to `failed`.

---

## Mission Persistence

- Missions are stored in SQLite (`missions` table in `layla.db`).
- Fields: `id`, `goal`, `plan_json`, `status`, `current_step`, `results_json`, `created_at`, `updated_at`, `workspace_root`, `allow_write`, `allow_run`.
- After each step, `current_step` and `results_json` are updated. If the server restarts, `mission_worker` picks up active missions (`running` or `pending`) and continues from `current_step`.

---

## Mission Safety Limits

- **max_mission_steps** — Hard cap of 10 steps per mission. Prevents runaway plans.
- **max_mission_runtime_seconds** — Configurable in `runtime_config.json`. Default 3600 (1 hour). If a mission exceeds this since `created_at`, it is aborted and marked `failed`.

---

## API

| Route | Method | Description |
|-------|--------|-------------|
| `/mission` | POST | Create and start a mission. Body: `{ "goal": str, "workspace_root"?: str, "allow_write"?: bool, "allow_run"?: bool }` |
| `/mission/{id}` | GET | Fetch mission by id |
| `/missions` | GET | List missions. Query: `status` (pending\|running\|completed\|failed), `limit` |

---

## Config

In `agent/runtime_config.json`:

```json
{
  "max_mission_runtime_seconds": 3600,
  "mission_worker_interval_minutes": 2
}
```

- `max_mission_runtime_seconds` — Abort mission after this many seconds. Default 3600.
- `mission_worker_interval_minutes` — How often the background worker runs (1–10). Default 2.
