"""North Star §18: project discovery — detect opportunities, synthesize ideas, evaluate feasibility."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

logger = logging.getLogger("layla")

DISCOVERY_TIMEOUT_SECONDS = 60
DISCOVERY_MAX_ITEM_LENGTH = 500
SAFE_FALLBACK = {"opportunities": [], "ideas": [], "feasibility_notes": []}


def run_project_discovery() -> dict:
    """
    Run one structured LLM pass over project context + recent learnings.
    Returns {"opportunities": [...], "ideas": [...], "feasibility_notes": [...]}.
    Timeout-guarded; strict JSON parsing; safe fallback on any error.
    """
    try:
        from jinx.memory.db import get_project_context, get_recent_learnings
        from services.llm_gateway import run_completion
    except Exception as e:
        logger.warning("project_discovery imports failed: %s", e)
        return SAFE_FALLBACK.copy()

    pc = get_project_context()
    learnings = get_recent_learnings(n=15)
    name = (pc.get("project_name") or "").strip()
    goals = (pc.get("goals") or "").strip()
    stage = (pc.get("lifecycle_stage") or "").strip()
    domains = pc.get("domains") or []
    key_files = (pc.get("key_files") or [])[:10]

    learnings_preview = "\n".join(
        (item.get("content") or "")[:200] for item in learnings[:10]
    ).strip() or "None yet."

    prompt = (
        "You are an engineering partner. Based on the following project context and recent learnings, "
        "output a single JSON object with exactly these keys: opportunities, ideas, feasibility_notes. "
        "Each value is a list of short strings (one sentence each). Be concise.\n\n"
        "Project: " + (name or "(none)") + "\n"
        "Lifecycle stage: " + (stage or "(unset)") + "\n"
        "Goals: " + (goals[:500] if goals else "(none)") + "\n"
        "Domains: " + json.dumps(domains) + "\n"
        "Key files: " + json.dumps(key_files) + "\n\n"
        "Recent learnings (excerpts):\n" + learnings_preview + "\n\n"
        "Respond with only the JSON object, no other text."
    )

    def _do_completion():
        return run_completion(prompt, max_tokens=400, temperature=0.2, stream=False, timeout_seconds=DISCOVERY_TIMEOUT_SECONDS)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_do_completion)
            out = fut.result(timeout=DISCOVERY_TIMEOUT_SECONDS + 5)
    except FuturesTimeoutError:
        logger.warning("project_discovery timed out")
        return SAFE_FALLBACK.copy()
    except Exception as e:
        logger.warning("project_discovery completion failed: %s", e)
        return SAFE_FALLBACK.copy()

    try:
        text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        text = (text or "").strip()
        if not text:
            return SAFE_FALLBACK.copy()
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
        data = json.loads(text)
        if not isinstance(data, dict):
            return SAFE_FALLBACK.copy()
        return {
            "opportunities": _ensure_list(data.get("opportunities")),
            "ideas": _ensure_list(data.get("ideas")),
            "feasibility_notes": _ensure_list(data.get("feasibility_notes")),
        }
    except json.JSONDecodeError as e:
        logger.warning("project_discovery JSON parse failed: %s", e)
        return SAFE_FALLBACK.copy()
    except Exception as e:
        logger.warning("project_discovery parse failed: %s", e)
        return SAFE_FALLBACK.copy()


def _ensure_list(val):
    """Return list of strings, max 20 items, each trimmed to DISCOVERY_MAX_ITEM_LENGTH."""
    if val is None:
        return []
    if isinstance(val, list):
        out = []
        for x in val[:20]:
            s = str(x).strip()[:DISCOVERY_MAX_ITEM_LENGTH]
            if s:
                out.append(s)
        return out
    s = str(val).strip()[:DISCOVERY_MAX_ITEM_LENGTH]
    return [s] if s else []
