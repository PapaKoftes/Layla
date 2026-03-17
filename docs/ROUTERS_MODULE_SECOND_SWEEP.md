# Routers Module Second Sweep — Report

Based on a systematic investigation of `agent/routers/` (agent.py, approvals.py, study.py, research.py) and related routes in main.py and routers/memory.py.

**Status: All fixes implemented.**

---

## 1. Medium Severity — SSRF in Image URL Fetch (agent.py)

**Location:** `_get_image_context()`, line ~135

**Issue:** `urllib.request.urlopen(image_url)` fetches user-provided URLs without validation. A malicious client could pass `http://127.0.0.1:22` or `http://169.254.169.254/latest/meta-data/` (cloud metadata) to probe internal services.

**Fix:** Validate URL scheme (http/https only) and block private/localhost IP ranges before fetching.

---

## 2. Medium Severity — Empty/Silent Catch Blocks (agent.py)

**Location:** `_get_image_context()` lines 152-154, 159-161

**Issue:** `except Exception: pass` with no logging. Failures are silent, making debugging difficult.

**Fix:** Add `logger.debug("describe_image/ocr_image failed: %s", e)`.

---

## 3. Medium Severity — Input Length Limits Missing (study.py)

**Location:** `add_study_plan()`, `set_aspect_title()`

**Issue:** `topic` and `title` have no max length. A client could send a 10MB string, causing DB bloat or DoS.

**Fix:** Enforce reasonable limits (e.g. topic 500 chars, title 200 chars) and reject with clear error.

---

## 4. Low Severity — Bare except in study.py

**Locations:** `_wakeup_initiative_suggestion` (43-45), `wakeup()` (135, 157-158, 164-166, 183-186, 214, 216)

**Issue:** `except Exception: pass` with no logging. Failures are invisible.

**Fix:** Add `logger.debug(...)` or `logger.warning(...)` for non-critical paths.

---

## 5. Low Severity — schedule delay_seconds Validation (agent.py)

**Location:** `schedule()` line 64

**Issue:** `float(r.get("delay_seconds") or 0)` — negative or inf/NaN could cause unexpected behavior.

**Fix:** Clamp to `max(0, min(86400, float(...)))` (0–24h) or reject invalid values.

---

## 6. Low Severity — memory/import Zip Slip (routers/memory.py)

**Location:** `import_bundle()` line 132

**Issue:** `target = REPO_ROOT / name.replace("/", ...)` — if a malicious ZIP contains `knowledge/../../../etc/passwd`, the path could escape. `name.startswith("knowledge/")` helps but `knowledge/../../evil` still resolves under REPO_ROOT. Actually `REPO_ROOT / "knowledge/../../evil"` = REPO_ROOT.parent / "evil". So path traversal is possible.

**Fix:** Use `Path(name).resolve()` and ensure result is under `REPO_ROOT / "knowledge"` with `result.resolve().is_relative_to(REPO_ROOT / "knowledge")` (Python 3.9+) or equivalent.

---

## 7. Low Severity — workspace_index Path Validation (main.py)

**Location:** `workspace_index()` line 1004

**Issue:** `root = (req or {}).get("workspace_root", "")` — no validation. A path like `../../../etc` could be passed. The workspace_index service will try to index it. Low risk for local-only use but worth validating.

**Fix:** Resolve path and ensure it exists and is a directory; optionally reject paths outside a configured allowed roots.

---

## 8. Consistency — Undo Endpoint Mismatch

**Location:** main.py `/undo`, UI approval flow

**Issue:** The UI sends `{ id: approvalId }` to `POST /undo` after approving an action, but the `/undo` endpoint ignores the body and only reverts the last git commit. The approval "Undo" link may be misleading—users might expect to undo the approval, not trigger a git revert.

**Fix:** Document behavior or add a separate `/approvals/undo` endpoint if approval-undo is desired. For now, document that /undo is git-only.

---

## Implementation Order

1. **Phase 1:** SSRF fix (1), input limits (3), Zip slip (6)
2. **Phase 2:** Empty catch logging (2, 4), schedule validation (5)
3. **Phase 3:** workspace_index validation (7), undo documentation (8)
