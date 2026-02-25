"""
Export Layla's identity, personalities, and learnings into a JSONL dataset
for fine-tuning the local model (e.g. llama.cpp, unsloth, llama-factory).

Run from repo root:  python agent/export_finetune_data.py
Output: agent/finetune_data.jsonl (chat format: messages with role/content)
"""
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _identity() -> str:
    p = AGENT_DIR / "system_identity.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "You are Layla, a bounded AI companion."


def _fallback_personality() -> str:
    try:
        data = json.loads((REPO_ROOT / "personality.json").read_text(encoding="utf-8"))
        return (data.get("systemPromptAddition") or "").strip()
    except Exception:
        return ""


def _personality_files() -> list[tuple[str, dict]]:
    out = []
    personalities_dir = REPO_ROOT / "personalities"
    if not personalities_dir.exists():
        return out
    for f in sorted(personalities_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append((data.get("id", f.stem), data))
        except Exception:
            continue
    return out


def _learnings(limit: int = 500) -> list[dict]:
    try:
        from jinx.memory.db import migrate, get_recent_learnings
        migrate()
        rows = get_recent_learnings(n=limit)
        return [{"content": r.get("content", ""), "type": r.get("type", "fact")} for r in rows if r.get("content")]
    except Exception:
        return []


def _aspect_memories(limit: int = 200) -> list[dict]:
    try:
        from jinx.memory.db import migrate
        import sqlite3
        migrate()
        db_path = REPO_ROOT / "layla.db"
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT aspect_id, content FROM aspect_memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [{"aspect_id": r[0], "content": r[1]} for r in rows if r[1]]
    except Exception:
        return []


def build_records() -> list[dict]:
    identity = _identity()
    fallback = _fallback_personality()
    core_system = identity
    if fallback:
        core_system = identity + "\n\n" + fallback

    records = []

    # 1) Core identity + greeting
    records.append({
        "messages": [
            {"role": "system", "content": core_system},
            {"role": "user", "content": "Hello."},
            {"role": "assistant", "content": "Hi. I'm Layla. I'm here when you need me—thinking, coding, or just talking."},
        ]
    })

    # 2) Per-aspect: identity + that aspect's voice + trigger -> short reply
    for aid, p in _personality_files():
        sys_add = (p.get("systemPromptAddition") or "").strip()
        if not sys_add:
            continue
        system = identity + "\n\n" + sys_add
        triggers = p.get("triggers") or []
        name = p.get("name") or aid
        if triggers:
            user = triggers[0] if isinstance(triggers[0], str) else str(triggers[0])
        else:
            user = f"Talk to me as {name}."
        records.append({
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": f"[As {name}] I'm here. What's on your mind?"},
            ]
        })

    # 3) Learnings as fact reinforcement
    for L in _learnings():
        content = (L.get("content") or "").strip()
        if not content or len(content) > 800:
            continue
        records.append({
            "messages": [
                {"role": "system", "content": core_system},
                {"role": "user", "content": "Remember: " + content[:400]},
                {"role": "assistant", "content": "I'll remember: " + content[:300]},
            ]
        })

    # 4) Aspect memories as in-character observations (optional; can help tone)
    for M in _aspect_memories()[:50]:
        content = (M.get("content") or "").strip()
        if not content or len(content) > 400:
            continue
        records.append({
            "messages": [
                {"role": "system", "content": core_system},
                {"role": "user", "content": "What do you remember about us?"},
                {"role": "assistant", "content": content[:350]},
            ]
        })

    return records


def main() -> None:
    out_path = AGENT_DIR / "finetune_data.jsonl"
    records = build_records()
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} records to {out_path}")


if __name__ == "__main__":
    main()
