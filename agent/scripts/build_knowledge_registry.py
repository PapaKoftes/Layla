#!/usr/bin/env python3
"""Assemble + validate knowledge/packs -> registry.json and presets.json.

Scans knowledge/packs/<id>/pack.json, validates every listed doc exists and carries
valid front matter (priority/domain/aspect/summary), recomputes approx_bytes, and writes
knowledge/packs/registry.json + presets.json. Exits non-zero on any validation failure so
CI (test_knowledge_packs.py) can gate it.

Run:  python agent/scripts/build_knowledge_registry.py [--check]
      --check = validate only, do not write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PACKS_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge" / "packs"
VALID_PRIORITY = {"core", "support", "flavor"}
VALID_ASPECT = {"", "morrigan", "nyx", "echo", "eris", "cassandra", "lilith"}

PRESETS = {
    "companion": ["core"],
    "maker": ["core", "fabrication", "embedded", "engineering"],
    "engineer": ["core", "engineering", "reasoning"],
    "researcher": ["core", "research", "reasoning", "psychology"],
    "everything": ["core", "engineering", "fabrication", "embedded", "research",
                   "reasoning", "psychology", "ethics", "creative"],
}


def parse_front_matter(text: str) -> dict | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fm: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def main() -> int:
    check_only = "--check" in sys.argv
    if not PACKS_DIR.exists():
        print(f"[error] no packs dir at {PACKS_DIR}")
        return 1

    errors: list[str] = []
    registry: dict[str, dict] = {}

    for pack_dir in sorted(p for p in PACKS_DIR.iterdir() if p.is_dir()):
        pid = pack_dir.name
        manifest_path = pack_dir / "pack.json"
        if not manifest_path.is_file():
            errors.append(f"{pid}: missing pack.json")
            continue
        try:
            man = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{pid}: pack.json invalid JSON: {e}")
            continue
        if man.get("id") != pid:
            errors.append(f"{pid}: pack.json id={man.get('id')!r} != dir name")

        # docs[] may be plain filenames or objects like {"file": "...", ...} — normalize.
        def _fname(item: object) -> str:
            if isinstance(item, dict):
                return str(item.get("file") or item.get("name") or "")
            return str(item)
        listed = [_fname(x) for x in (man.get("docs") or []) if _fname(x)]
        on_disk = sorted(f.name for f in pack_dir.glob("*.md"))
        for missing in set(listed) - set(on_disk):
            errors.append(f"{pid}: docs[] lists {missing!r} but file is absent")
        for extra in set(on_disk) - set(listed):
            errors.append(f"{pid}: {extra!r} on disk but not in docs[]")

        total_bytes = 0
        n_core = 0
        for md in sorted(pack_dir.glob("*.md")):
            raw = md.read_text(encoding="utf-8")
            total_bytes += len(raw.encode("utf-8"))
            fm = parse_front_matter(raw)
            if fm is None:
                errors.append(f"{pid}/{md.name}: missing/invalid front matter")
                continue
            pr = fm.get("priority", "")
            if pr not in VALID_PRIORITY:
                errors.append(f"{pid}/{md.name}: priority={pr!r} not in {VALID_PRIORITY}")
            if pr == "core":
                n_core += 1
            if fm.get("domain") != pid:
                errors.append(f"{pid}/{md.name}: domain={fm.get('domain')!r} != pack id")
            if fm.get("aspect", "") not in VALID_ASPECT:
                errors.append(f"{pid}/{md.name}: aspect={fm.get('aspect')!r} invalid")
            if not fm.get("summary"):
                errors.append(f"{pid}/{md.name}: missing summary")
            elif len(fm["summary"]) > 120:
                errors.append(f"{pid}/{md.name}: summary >120 chars")
        if pack_dir.glob("*.md") and n_core == 0:
            errors.append(f"{pid}: no doc marked priority: core")

        registry[pid] = {
            "id": pid,
            "title": man.get("title", pid),
            "aspect": man.get("aspect", ""),
            "summary": man.get("summary", ""),
            "docs": on_disk,
            "approx_bytes": total_bytes,
        }

    # presets must only reference packs that exist (or are reserved for later)
    for name, packs in PRESETS.items():
        for p in packs:
            if p not in registry and p not in ("ethics", "creative"):
                errors.append(f"preset {name!r} references unknown pack {p!r}")

    print(f"packs: {len(registry)}  | " + ", ".join(f"{k}({v['approx_bytes']//1000}KB)" for k, v in registry.items()))
    if errors:
        print(f"\n[FAIL] {len(errors)} validation error(s):")
        for e in errors:
            print("  -", e)
        return 1
    print("[OK] all packs valid")

    if not check_only:
        (PACKS_DIR / "registry.json").write_text(
            json.dumps({"packs": registry}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (PACKS_DIR / "presets.json").write_text(
            json.dumps(PRESETS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote registry.json ({len(registry)} packs) + presets.json ({len(PRESETS)} presets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
