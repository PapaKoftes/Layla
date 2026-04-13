# Install Module Second Sweep — Report

**Status: All fixes implemented.**

## 1. Medium Severity — Path traversal in model_downloader (model_downloader.py)

**Issue:** `filename` from model dict or derived from URL. If filename is `../config` or `evil/../../etc/passwd`, `dest = models_dir / filename` could write outside models_dir.

**Fix:** Sanitize filename: use only basename, reject if contains `..`, `/`, or `\`.

## 2. Low Severity — SSRF in model_downloader (model_downloader.py)

**Issue:** `url` from model dict is used in urlretrieve without validation. Catalog is typically trusted, but add private-IP block for defense in depth.

**Fix:** Add _is_safe_url check before direct URL download (huggingface_hub uses its own URLs).
