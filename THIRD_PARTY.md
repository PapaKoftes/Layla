# Third-Party Notices & License Accounting

Layla ships under a **"Free for non-commercial use"** license (see [`LICENSE`](LICENSE)).
That license is **incompatible with strong copyleft** (AGPL / GPL / SSPL): bundling or
distributing such a dependency would force the whole project under copyleft terms. This
document records the third-party dependency licensing position and the automated guard
that enforces it.

## Policy

| License class | Examples | Status |
|---|---|---|
| Permissive | MIT, BSD-2/3, Apache-2.0, ISC, PSF, Zlib | ✅ Allowed |
| Weak copyleft | LGPL, MPL-2.0 (file-level), GPL **with linking exception** | ✅ Allowed (dynamic use / per-file) |
| Strong copyleft | **AGPL, GPL-2/3 (no exception), SSPL** | ❌ Blocked |

## Enforcement (source of truth)

`scripts/check_copyleft.py` is the authoritative gate. It scans **installed
distribution metadata** (SPDX `License-Expression` + trove `License ::` classifiers)
on every push/PR via the **License compliance** step in [`.github/workflows/ci.yml`](.github/workflows/ci.yml),
and fails the build if a strong-copyleft package is present without an escape hatch
(linking exception, or a dual-licensed permissive option). This is what removed the
historical **PyMuPDF (AGPL)** dependency and prevents a regression.

Run it locally:

```bash
python scripts/check_copyleft.py          # exits non-zero on a blocking dep
python scripts/check_copyleft.py --list   # show what (if anything) is flagged
```

Because it reads real installed metadata, the guard is always accurate to what would
actually ship — it does not rely on the hand-maintained table below.

## Known weak-copyleft dependency

- **python-zeroconf** (`network` extra) — **LGPL-2.1**. Weak copyleft; used as an
  unmodified library via the package API, which LGPL permits. Allowed by policy.
  Only pulled in by the optional `network` (mDNS discovery) extra.

## Direct dependencies (best-effort accounting)

Grouped by install extra from [`pyproject.toml`](pyproject.toml). Licenses are
best-effort and may drift across releases — **the CI guard, not this table, is
authoritative.**

### `core`
fastapi (MIT) · pydantic (MIT) · uvicorn (BSD-3) · python-multipart (Apache-2.0) ·
httpx (BSD-3) · requests (Apache-2.0) · tenacity (Apache-2.0) · sqlite-utils (Apache-2.0) ·
diskcache (Apache-2.0) · sentence-transformers (Apache-2.0) · chromadb (Apache-2.0) ·
langchain-text-splitters (MIT) · rank-bm25 (Apache-2.0) · torchao (BSD-3) · tiktoken (MIT) ·
numpy (BSD-3) · psutil (BSD-3) · keyring (MIT) · apscheduler (MIT) · networkx (BSD-3) ·
orjson (Apache-2.0 / MIT) · PyYAML (MIT) · unidiff (MIT) · Pillow (HPND / MIT-CMU)

### `llm`
llama-cpp-python (MIT) · litellm (MIT) · instructor (MIT)

### `voice`
faster-whisper (MIT) · pyttsx3 (MPL-2.0, the shipped default TTS) · soundfile (BSD-3)

### `voice-kokoro` (opt-in only)
kokoro-onnx — **GPLv3+** (it pulls `phonemizer-fork`, GNU GPL v3). Strong copyleft is
incompatible with Layla's non-commercial source license, so it is **not** in the default
install or the `voice` extra. Install explicitly only if you accept GPLv3:
`pip install kokoro-onnx soundfile` (or, from the source tree, `pip install ".[voice-kokoro]"`).

### `vision`
easyocr (Apache-2.0)

### `crawl`
trafilatura (Apache-2.0) · beautifulsoup4 (MIT) · playwright (Apache-2.0)

### `research`
pypdf (BSD-3 — the permissive replacement for the removed PyMuPDF) · wikipedia (MIT) ·
duckduckgo-search (MIT) · arxiv (MIT) · pandas (BSD-3) · nbformat (BSD-3)

### `data`
duckdb (MIT) · yfinance (Apache-2.0) · scipy (BSD-3) · scikit-learn (BSD-3) ·
sympy (BSD-3) · feedparser (BSD-2)

### `docs`
python-docx (MIT) · openpyxl (MIT)

### `viz`
matplotlib (Matplotlib License — BSD-style)

### `nlp`
keybert (MIT) · deep-translator (MIT)

### `security`
bandit (Apache-2.0)

### `tui`
textual (MIT)

### `network`
**zeroconf (LGPL-2.1 — weak copyleft, see above)**

---
*Generated for REQ-02 (legal & launch safety). Update when adding a dependency; the CI
guard will block a strong-copyleft addition automatically.*
