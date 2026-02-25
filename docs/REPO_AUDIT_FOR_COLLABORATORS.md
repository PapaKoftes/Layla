# Repo audit for collaborators

Checklist used before sharing the repo on GitHub. Covers secrets, personal data, and content that might cause issues.

---

## 1. Secrets and credentials

| Check | Status | Notes |
|-------|--------|------|
| No API keys or tokens in code | OK | `remote_api_key` is read from config only; no hardcoded secrets. |
| No passwords in repo | OK | None found. |
| RUNBOOKS | OK | Uses placeholder `"your-secret"` for remote API key. |
| runtime_config.json | Note | May contain local `sandbox_root`; no secrets. Use `runtime_config.example.json` as template. |

**Recommendation:** Do not commit a real `remote_api_key`. If remote is enabled, set the key locally or via env and document in RUNBOOKS.

---

## 2. Personal and machine-specific data

| Item | Location | Status |
|------|----------|--------|
| Execution log paths | `agent/.governance/execution_log.json` | Ignored via `agent/.gitignore` (`.governance/`). |
| Local path in config | `agent/runtime_config.json` → `sandbox_root` | Optional: gitignore this file and use example; collaborators set their own path. |
| User/operator name in docs | Cursor rules, personalities, knowledge | Genericized to "the user" / "operator"; dialogue label in code is "User:". |

---

## 3. Content

| Topic | Where | Note |
|-------|--------|------|
| Lilith NSFW register | `personalities/lilith.json` (nsfw_triggers, systemPromptAdditionNsfw), Cursor rules | Toggle by keyword (e.g. intimate, nsfw); documented. |
| Uncensored / nsfw_allowed | runtime_config | Optional product flags; documented. |
| Fetched knowledge | `knowledge/fetched/` | Public docs; consider adding to `.gitignore` to keep repo small. |

---

## 4. What should not be committed

- **Root:** `.venv/`, `layla.db`, `learnings.json`, large model files, Chroma DB dirs.
- **agent/:** `.governance/`, `.research_lab/`, `.research_output/`, `*.db`, `__pycache__/`, logs.
- **Optional:** `agent/runtime_config.json`, `knowledge/fetched/`.

Root `.gitignore` and `agent/.gitignore` are set so `.governance/`, `.venv/`, and `layla.db` are not committed.

---

## 5. Before pushing

- Run `git status` and ensure `.governance/`, `.venv/`, and `layla.db` are not staged.
- If `.governance/` was ever committed, remove it from history (e.g. `git rm -r --cached agent/.governance` and commit).
