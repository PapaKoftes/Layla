# Ethical AI Principles — Layla

This document codifies the ethical AI principles that govern Layla's design and implementation. All features, tools, and behaviors must align with these principles.

**Project values:** See [VALUES.md](../VALUES.md) — sovereignty, privacy, anti-surveillance capitalism, solidarity. Development aligns with these.

**Reference:** `knowledge/lilith-ethics-autonomy.md` — detailed ethics framework (autonomy, consent, honesty, real harm vs. safety theater).

---

## 0. Policy invariants (system, not vibes)

**Principle:** Operator safety and governance are **hard constraints**. Memory, codex, learnings, or subsystem hints must not override them.

**Implementation:**
- `operator_protection_policy_pin_enabled` injects an invariant block in `_build_system_head` (`agent_loop.py`).
- `decision_policy.py` clamps tool allowlists from outcome and workspace signals but **cannot** disable `require_approval` or sandbox checks from SQLite content.
- Approval flow and `inside_sandbox` remain authoritative. See `AGENTS.md` hard rules.

---

## 1. Human-in-the-loop (Consent)

**Principle:** Layla never modifies files or runs code without explicit user approval.

**Implementation:**
- `allow_write` / `allow_run` required for write/run tools
- `write_file`, `apply_patch`, `shell`, `run_python`, `git_commit` return `approval_required` → user must approve via `POST /approve` or CLI
- `runtime_safety.require_approval()` gates dangerous tools
- `agent/routers/approvals.py` — approval endpoint

**Hard rule:** Never bypass the approval gate. See `AGENTS.md` §5.

---

## 2. Sandbox (Scope)

**Principle:** Layla operates only within the user-defined sandbox. No access outside.

**Implementation:**
- `inside_sandbox(path)` in `layla/tools/registry.py` — every file/tool checks before read/write
- `sandbox_root` in `runtime_config.json` — user configurable (first-run wizard and Web setup should set a **dedicated workspace folder**, not your entire user profile; the schema default may still be `~` for backward compatibility until the operator tightens it)
- Tools return `{"ok": false, "error": "Outside sandbox"}` when path is outside

**Hard rule:** No tool may read or write outside the sandbox.

---

## 3. Shell Blocklist (Harm Prevention)

**Principle:** Certain commands are never allowed, even with approval.

**Implementation:**
- `layla/tools/sandbox_core.py` — `_SHELL_BLOCKLIST` (never allowed): `rm`, `del`, `rmdir`, `format`, `mkfs`, `dd`, `shutdown`, `reboot`, `powershell`, `cmd`, `reg`, `netsh`, `sc`, `taskkill`, `cipher`
- `_SHELL_NETWORK_DENYLIST` — `curl`, `wget`, `ssh`, `nc`, `nmap`, … blocked at the shell layer when enforced
- `_SHELL_INJECTION_WARN` — patterns that trigger warnings / refusal (command substitution, dangerous redirects)
- Returns `{"ok": false, "error": "Command blocked"}` (or equivalent) before execution

---

## 4. Refusal (Honest Pushback)

**Principle:** Layla can refuse requests that conflict with her values. She is not a yes-machine.

**Implementation:**
- Aspects with `will_refuse` or `can_refuse` (e.g. Lilith) can output `[REFUSED: reason]`
- `agent_loop.py` parses refusal, sets `state["refused"]`, does not run tools
- Orchestrator prompts: "If you must refuse, start with [REFUSED: reason]."

**Reference:** `knowledge/lilith-ethics-autonomy.md` — real harm vs. safety theater.

---

## 5. Content Policy (No Over-censorship)

**Principle:** Refuse only for genuine harm. Do not censor uncomfortable topics.

**Implementation:**
- System prompt: "Refuse only for genuine harm (illegal, non-consensual, abuse)"
- `uncensored` / `nsfw_allowed` config — user controls content boundaries
- `knowledge/lilith-ethics-autonomy.md` — real harm categories vs. discomfort

---

## 6. Privacy (Local-first)

**Principle:** User data stays on the user's machine. No cloud. No third-party telemetry.

**Implementation:**
- `layla.db` — local SQLite only (gitignored)
- `knowledge/` — local by default (gitignored)
- `runtime_config.json` — local paths only (gitignored)
- No API keys required for core operation
- Remote access is opt-in (`remote_enabled`)

**Local observability (not “phone home”):** The `telemetry_enabled` / performance keys in `runtime_config.json` refer to **on-disk, operator-owned logging and metrics** (e.g. tool latency in local SQLite / logs). They do **not** send behavior to vendors or cloud analytics. Third-party or off-device telemetry requires an explicit, separate opt-in (e.g. Langfuse with keys you provide).

---

## 7. Audit Trail (Accountability)

**Principle:** All tool executions are logged. User can review what Layla did.

**Implementation:**
- `layla/memory/audit_session.py` — `log_audit()` → SQLite **`audit`** table (`timestamp`, `tool`, `args_summary`, `approved_by`, `result_ok`); re-exported from `layla/memory/db.py`
- `GET /audit` — paginated audit log (`routers/session.py`)
- `_audit()` in `main.py` — after approval execution: append-only **flat file** under `.layla_gov/audit.log` **and** `log_audit()` to SQLite so CLI/UI stay in sync

---

## 8. Learning Quality (Honesty)

**Principle:** Do not store uncertain or low-quality learnings. Honesty about uncertainty.

**Implementation:**
- `services/learning_filter.py` — rejects `UNCERTAINTY_PHRASES` ("maybe", "not sure", "i don't know", etc.)
- `add_learning` — quality filter before persistence
- `knowledge/lilith-ethics-autonomy.md` — "Honesty about uncertainty"

---

## 9. Protected Files (Integrity)

**Principle:** Core system files cannot be modified by the agent.

**Implementation:**
- `runtime_safety.PROTECTED_FILES`: `main.py`, `agent_loop.py`, `runtime_safety.py`
- `is_protected(path)` — blocks writes to these

---

## 10. Transparency (Explainability)

**Principle:** User understands what Layla is doing and why.

**Implementation:**
- Approval flow shows tool name and args before execution
- `ux_states` — thinking, verifying, changing_approach
- Deliberation mode — shows aspect reasoning when requested
- `show_thinking: true` — multi-aspect deliberation visible

---

## 11. Non-clinical boundary (psychology / collaboration)

**Principle:** Layla may use psychology-informed language for **collaboration, reflection, and communication style** — not as a clinician, diagnostician, or substitute for professional care.

**Forbidden (product behavior):**
- Claiming or implying a **psychiatric diagnosis**, or applying **DSM / ICD** (or similar) **disorder labels to the operator** (“you have X”, “you are diagnosable with …”).
- Storing inferred **clinical labels** about the operator as facts in memory.
- Presenting **risk assessment** or **treatment plans** as authoritative medical guidance.

**Allowed:**
- Describing **observable patterns** in language, emotion, or work style; offering **hypotheses as questions**; using frameworks (e.g. CBT, DBT) as **shared vocabulary**, not as labels pinned on a person.
- Encouraging **qualified professionals** when the situation clearly warrants it (e.g. persistent distress, self-harm ideation, harm to others).
- **Crisis handoff (generic):** If the user appears in **immediate danger**, encourage contacting **local emergency services** or a **local crisis line**; do not rely on the model as a safety net. Do not pretend to monitor or intervene offline.

**Implementation (see also):**
- `knowledge/echo-psychology-frameworks.md` — frameworks + explicit guardrails
- `direct_feedback_enabled` in `runtime_config.json` — opt-in blunt collaboration (see `docs/CONFIG_REFERENCE.md`)

---

## Checklist for Contributors

When adding or changing behavior, verify:

- [ ] No approval bypass for write/run tools
- [ ] All file paths checked with `inside_sandbox()`
- [ ] No new shell commands that bypass blocklist
- [ ] Refusal path remains available for aspects
- [ ] No cloud / third-party telemetry without explicit opt-in (local observability is OK; document it)
- [ ] Audit logged for tool executions
- [ ] Learning filter applied for `add_learning`
- [ ] Protected files remain protected
- [ ] No new features that **diagnose** the user or assign **clinical disorder labels**; collaboration-style inference only

---

## References

- `AGENTS.md` — hard rules, never violate
- `knowledge/lilith-ethics-autonomy.md` — ethics framework
- `docs/OPERATOR_PSYCHOLOGY_SOURCES.md` — inventory of behavioral/psychology knowledge paths, optional libraries, and non-clinical guidance
- `LAYLA_NORTH_STAR.md` §20 — safe self-upgrade
- `ARCHITECTURE.md` — request flow
