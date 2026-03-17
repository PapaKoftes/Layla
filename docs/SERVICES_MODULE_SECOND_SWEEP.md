# Services Module Second Sweep — Report

Based on a systematic investigation of `agent/services/` (50 files).

**Status: All fixes implemented.**

---

## 1. Medium Severity — SSRF in Browser Service (browser.py)

**Location:** `navigate()`, `screenshot()`, `click_and_extract()`, `fill_form()` — all take user-provided `url`.

**Issue:** Playwright `page.goto(url)` fetches any URL. A malicious tool call could pass `http://127.0.0.1:22` or `http://169.254.169.254/latest/meta-data/` to probe internal services.

**Fix:** Add URL validation (scheme http/https, block private/localhost) before any goto, mirroring agent router's image_url check.

---

## 2. High Severity — Path Traversal in Integration Sandbox (integration_sandbox.py)

**Location:** `_sandbox_dir(session_id)` line 22-25

**Issue:** `d = _SANDBOX_BASE / session_id` — if `session_id` is `".."` or `"../../../etc"`, the resolved path escapes the sandbox. `shutil.rmtree(_sandbox_dir(sid))` could delete arbitrary directories.

**Fix:** Resolve path and ensure it stays under `_SANDBOX_BASE` using `resolve()` and `is_relative_to()` or equivalent.

---

## 3. Low Severity — Silent Catch in Browser close() (browser.py)

**Location:** Line 269-270

**Issue:** `except Exception: pass` — shutdown failures are silent.

**Fix:** Add `logger.debug("browser close failed: %s", e)`.

---

## 4. Low Severity — Silent Catch in Workspace Index (workspace_index.py)

**Locations:** `get_architecture_summary` (134), `build_workspace_graph` (284), `get_workspace_dependency_context` (341), `search_workspace` (284)

**Issue:** `except Exception: continue` or `return []` with no logging.

**Fix:** Add `logger.debug(...)` for debugging.

---

## 5. Low Severity — Silent Catch in Capability Discovery (capability_discovery.py)

**Location:** `_read_cache` line 73

**Issue:** `except Exception: return None` — cache read failures are silent.

**Fix:** Add `logger.debug("capability_discovery cache read failed: %s", e)`.

---

## 6. Low Severity — Silent Catch in Integration Sandbox (integration_sandbox.py)

**Location:** Line 205-206

**Issue:** `except Exception: pass` when cleaning up sandbox dir.

**Fix:** Add `logger.debug("integration_sandbox cleanup failed: %s", e)`.

---

## Implementation Order

1. **Phase 1:** Path traversal fix (2), SSRF in browser (1)
2. **Phase 2:** Silent catch logging (3, 4, 5, 6)
