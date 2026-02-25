"""
One-shot: fetch all configured and curated docs into knowledge/fetched/.
Run from repo root: python scripts/fetch_knowledge.py
"""
import re
import json
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = REPO_ROOT / "knowledge"
FETCHED = KNOWLEDGE / "fetched"
MAX_BYTES_PER_FILE = 60_000

# Full knowledge library: core stack + personality/culture. Merge with runtime_config.json knowledge_sources.
# See knowledge/KNOWLEDGE_LIBRARY_FULL.md for the full checklist.
URLS = [
    ("https://fastapi.tiangolo.com/tutorial/first-steps/", "fastapi-quickstart"),
    ("https://docs.python.org/3/library/asyncio-task.html", "asyncio-tasks"),
    ("https://docs.python.org/3/library/pathlib.html", "pathlib"),
    ("https://www.sqlite.org/lang.html", "sqlite-lang"),
    ("https://docs.python.org/3/library/json.html", "python-json"),
    ("https://docs.python.org/3/library/dataclasses.html", "python-dataclasses"),
    ("https://fastapi.tiangolo.com/advanced/", "fastapi-advanced"),
    ("https://github.com/abetlen/llama-cpp-python/blob/main/README.md", "llama-cpp-python-readme"),
    ("https://docs.python.org/3/library/typing.html", "python-typing"),
    ("https://docs.pydantic.dev/latest/", "pydantic-overview"),
    # Add more below or via runtime_config.json "knowledge_sources"
]

# Raw GitHub markdown
GITHUB_RAW = "https://raw.githubusercontent.com/abetlen/llama-cpp-python/main/README.md"


def strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Layla-Knowledge-Fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


def main():
    FETCHED.mkdir(parents=True, exist_ok=True)
    config_path = REPO_ROOT / "agent" / "runtime_config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            for item in data.get("knowledge_sources", []):
                u, s = item.get("url"), item.get("slug")
                if u and s and not any(slug == s for _, slug in URLS):
                    URLS.append((u, s))
        except Exception:
            pass
    for url, slug in URLS:
        if slug == "llama-cpp-python-readme":
            url = GITHUB_RAW
        out = FETCHED / f"{slug}.txt"
        try:
            raw = fetch(url)
            if "raw.githubusercontent.com" in url or url.endswith(".md"):
                text = raw
            else:
                text = strip_html(raw)
            text = text[:MAX_BYTES_PER_FILE]
            out.write_text(text, encoding="utf-8")
            print(f"OK {slug} ({len(text)} chars)")
        except Exception as e:
            print(f"SKIP {slug}: {e}")
    print("Done. Restart Layla or re-index Chroma to pick up new knowledge.")


if __name__ == "__main__":
    main()
