# Layla Module Second Sweep — Report

**Status: All fixes implemented.**

## 1. High Severity — Zip Slip in extract_archive (registry.py)

**Issue:** `zipfile.ZipFile.extractall(out)` and `tarfile.extractall(out)` can write outside `out` if archive contains paths like `evil/../../etc/passwd`.

**Fix:** Extract members one-by-one, validate each path stays under `out` before writing.

## 2. Medium Severity — SSRF in fetch_url (web.py)

**Issue:** When allowlist is empty or permissive, no private-IP block. Could fetch 127.0.0.1, 169.254.169.254.

**Fix:** Add _is_safe_url check (block private/localhost) before fetch, mirroring browser service.

## 3. Low Severity — Silent catches (file_understanding, web, registry)

**Locations:** _analyze_json, _analyze_ipynb, _get_allowlist, _robots_allowed, grep_code fallback loop.

**Fix:** Add logger.debug() for debugging.
