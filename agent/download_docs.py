"""
Knowledge seeder for Layla.

Reads `knowledge_sources` from agent/runtime_config.json, fetches each URL
with a safe non-blocking fetcher (timeout, no hang). Saves clean text to
knowledge/fetched/<slug>.txt. Never blocks research missions; never raises.

Usage:
    cd agent
    python download_docs.py

Add sources to runtime_config.json under "knowledge_sources":
    [
      {"url": "https://fastapi.tiangolo.com/tutorial/", "slug": "fastapi"},
      {"url": "https://docs.python.org/3/library/asyncio.html", "slug": "asyncio"}
    ]
"""
import json
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
CONFIG_FILE = AGENT_DIR / "runtime_config.json"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge" / "fetched"

# Ensure the agent package is importable
sys.path.insert(0, str(AGENT_DIR))


def safe_fetch(url: str, timeout: int = 10) -> str | None:
    """Fetch URL with timeout. Returns text up to 60000 chars or None. Never raises."""
    try:
        import requests
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 Layla Research Agent"},
        )
        if r.status_code != 200:
            return None
        return (r.text or "")[:60000]
    except Exception:
        return None


def _load_sources() -> list[dict]:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("knowledge_sources", [])
    except Exception as e:
        print(f"Could not read runtime_config.json: {e}")
        return []


def main() -> None:
    start = time.time()
    FETCH_TIME_LIMIT = 120

    sources = _load_sources()
    if not sources:
        print("No knowledge_sources configured in runtime_config.json. Nothing to fetch.")
        return

    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        print("FETCH FAILED: could not create knowledge/fetched dir")
        return

    for source in sources:
        if time.time() - start > FETCH_TIME_LIMIT:
            print("FETCH TIME LIMIT REACHED")
            break

        url = source.get("url", "").strip()
        slug = source.get("slug", "").strip().replace(" ", "_")
        if not url or not slug:
            print(f"FETCH SKIPPED: invalid entry {source}")
            continue

        content = None
        for attempt in range(2):
            content = safe_fetch(url)
            if content is not None:
                break
        if content is None:
            print(f"FETCH SKIPPED: {url}")
            continue

        text = (content or "").strip()
        if not text:
            print(f"FETCH SKIPPED: {url} (empty)")
            continue

        try:
            out_path = KNOWLEDGE_DIR / f"{slug}.txt"
            out_path.write_text(
                f"source: {url}\n\n{text[:30000]}",
                encoding="utf-8",
            )
            print(f"FETCH OK: {url} → {out_path} ({len(text)} chars)")
        except Exception as e:
            print(f"FETCH FAILED: {url} ({e})")

    print("Done.")


if __name__ == "__main__":
    main()
