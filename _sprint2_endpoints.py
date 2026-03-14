import codecs

NEW_BLOCK = (
    '\n\n'
    '# Study plans API\n\n'
    '@app.get("/study_plans")\n'
    'def list_study_plans():\n'
    '    try:\n'
    '        from layla.memory.db import get_active_study_plans, _conn, migrate\n'
    '        migrate()\n'
    '        plans = get_active_study_plans()\n'
    '        enriched = []\n'
    '        with _conn() as db:\n'
    '            for p in plans:\n'
    '                topic_snip = (p.get("topic") or "")[:30]\n'
    '                try:\n'
    '                    row = db.execute(\n'
    '                        "SELECT COUNT(*) as cnt, MAX(timestamp) as last FROM audit '
    'WHERE tool=\'study\' AND args_summary LIKE ?",\n'
    '                        (f"%{topic_snip}%",)\n'
    '                    ).fetchone()\n'
    '                    sessions = row["cnt"] if row else 0\n'
    '                    last = row["last"] if row else None\n'
    '                except Exception:\n'
    '                    sessions = 0\n'
    '                    last = None\n'
    '                enriched.append({\n'
    '                    "id": p.get("id"),\n'
    '                    "topic": p.get("topic", ""),\n'
    '                    "notes": p.get("notes", "") or "",\n'
    '                    "created_at": p.get("created_at", ""),\n'
    '                    "study_sessions": sessions,\n'
    '                    "last_studied": last,\n'
    '                })\n'
    '        return JSONResponse({"plans": enriched})\n'
    '    except Exception as e:\n'
    '        return JSONResponse({"error": str(e), "plans": []})\n\n\n'
    '@app.delete("/study_plans/{plan_id}")\n'
    'def delete_study_plan(plan_id: int):\n'
    '    try:\n'
    '        from layla.memory.db import _conn, migrate\n'
    '        migrate()\n'
    '        with _conn() as db:\n'
    '            db.execute("DELETE FROM study_plans WHERE id=?", (plan_id,))\n'
    '            db.commit()\n'
    '        return {"ok": True}\n'
    '    except Exception as e:\n'
    '        return JSONResponse({"error": str(e)}, status_code=500)\n\n\n'
    '# File content (safe read for diff viewer)\n\n'
    '@app.get("/file_content")\n'
    'def read_file_content(path: str = ""):\n'
    '    if not path:\n'
    '        return JSONResponse({"error": "path required"}, status_code=400)\n'
    '    import runtime_safety as _rs\n'
    '    try:\n'
    '        cfg = _rs.load_config()\n'
    '        sandbox = cfg.get("sandbox_root", "")\n'
    '        p = Path(path).resolve()\n'
    '        if sandbox:\n'
    '            sb = Path(sandbox).resolve()\n'
    '            try:\n'
    '                p.relative_to(sb)\n'
    '            except ValueError:\n'
    '                return JSONResponse({"error": "path outside sandbox"}, status_code=403)\n'
    '        if not p.exists():\n'
    '            return JSONResponse({"exists": False, "content": ""})\n'
    '        if p.stat().st_size > 500_000:\n'
    '            return JSONResponse({"error": "file too large (>500 KB)"}, status_code=413)\n'
    '        content = p.read_text(encoding="utf-8", errors="replace")\n'
    '        return JSONResponse({"exists": True, "content": content, "path": str(p)})\n'
    '    except Exception as e:\n'
    '        return JSONResponse({"error": str(e)}, status_code=500)\n\n'
)

content = codecs.open("agent/main.py", encoding="utf-8-sig").read()
marker = "# Voice endpoints"
idx = content.find(marker)
if idx == -1:
    print("MARKER NOT FOUND")
else:
    line_start = content.rfind("\n", 0, idx)
    insert_pos = line_start
    new_content = content[:insert_pos] + NEW_BLOCK + content[insert_pos:]
    with open("agent/main.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"OK - inserted {len(NEW_BLOCK)} chars at position {insert_pos}")
