"""
File understanding for Layla: intent-focused analysis (North Star §4).
Read-only; Layla contextualizes and does not modify without approval.

Geometry: .3dm, .gh, .dxf, .dwg, .step, .stp, .iges, .igs, .stl, .obj
Fabrication: .nc, .gcode, .tap, .sbp, .cix, .mpr, .bpp
Programming: .py, .ipynb, .json, .yaml, .toml
Documentation: .md, .pdf, .docx
Visual: .png, .jpg, .svg
"""

from pathlib import Path

# North Star §4: intent by extension (binary or opaque → describe from context)
_FILE_INTENT = {
    ".3dm": ("Rhino", "3D model; intent from filename/context"),
    ".gh": ("Grasshopper", "Parametric definition; intent from filename/context"),
    ".dxf": ("DXF", "CAD/fabrication geometry"),
    ".dwg": ("DWG", "CAD drawing; intent from filename/context"),
    ".step": ("STEP", "Exchange 3D geometry; intent from context"),
    ".stp": ("STEP", "Exchange 3D geometry; intent from context"),
    ".iges": ("IGES", "Exchange geometry; intent from context"),
    ".igs": ("IGES", "Exchange geometry; intent from context"),
    ".stl": ("STL", "Mesh for 3D print/CAM; intent from context"),
    ".obj": ("OBJ", "Mesh/geometry; intent from context"),
    ".nc": ("NC", "CNC program; machine intent"),
    ".gcode": ("G-code", "CNC/3D print; machine intent"),
    ".tap": ("TAP", "CNC program; machine intent"),
    ".sbp": ("SBP", "ShopBot CNC; machine intent"),
    ".cix": ("CIX", "Fabrication; intent from context"),
    ".mpr": ("MPR", "Fabrication; intent from context"),
    ".bpp": ("BPP", "Fabrication; intent from context"),
    ".py": ("Python", "Script or module"),
    ".ipynb": ("Jupyter", "Notebook; code and narrative"),
    ".json": ("JSON", "Structured data; intent from context"),
    ".yaml": ("YAML", "Config/data; intent from context"),
    ".yml": ("YAML", "Config/data; intent from context"),
    ".toml": ("TOML", "Config; intent from context"),
    ".md": ("Markdown", "Documentation or notes"),
    ".pdf": ("PDF", "Document; intent from context"),
    ".docx": ("Word", "Document; intent from context"),
    ".png": ("PNG", "Image; intent from context"),
    ".jpg": ("JPEG", "Image; intent from context"),
    ".jpeg": ("JPEG", "Image; intent from context"),
    ".svg": ("SVG", "Vector image; intent from context"),
}


def _analyze_dxf(content: bytes | str) -> dict:
    """Intent-focused DXF summary: layers, entity counts, units if available."""
    out = {"format": "DXF", "intent": "CAD/fabrication geometry", "layers": [], "entity_summary": ""}
    try:
        from io import BytesIO

        import ezdxf
        bio = BytesIO(content.encode("utf-8") if isinstance(content, str) else content)
        doc = ezdxf.read(bio)
        msp = doc.modelspace()
        layers = list({e.dxf.layer for e in msp})
        out["layers"] = layers[:50]
        out["entity_summary"] = f"{len(list(msp))} entities, {len(layers)} layers"
        if doc.units:
            out["units"] = str(doc.units)
    except Exception:
        out["entity_summary"] = "DXF file; parse skipped or ezdxf not available"
    return out


def _analyze_python(content: str) -> dict:
    """Intent from docstrings, imports, and first block; no execution."""
    out = {"format": "Python", "intent": "Script or module"}
    lines = content.splitlines()
    doc_parts = []
    in_doc = False
    for i, line in enumerate(lines[:120]):
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            in_doc = not in_doc
            doc_parts.append(s.strip("'\""))
        elif in_doc:
            doc_parts.append(s)
        if i < 30 and ("import " in s or "from " in s):
            out.setdefault("imports", []).append(s[:80])
    if doc_parts:
        out["doc_summary"] = " ".join(doc_parts)[:400]
    if "ezdxf" in content:
        out.setdefault("hints", []).append("DXF/graphics")
    if "opencv" in content.lower() or "cv2" in content:
        out.setdefault("hints", []).append("image/geometry analysis")
    return out


def _analyze_markdown(content: str) -> dict:
    """Documentation intent: headings and first block."""
    out = {"format": "Markdown", "intent": "Documentation or notes"}
    lines = content.splitlines()[:80]
    headings = [ln.strip() for ln in lines if ln.strip().startswith("#")]
    if headings:
        out["headings"] = headings[:15]
    if lines:
        out["preview"] = "\n".join(lines[:20])[:500]
    return out


def _analyze_json(content: str) -> dict:
    """Intent from top-level keys or list length."""
    out = {"format": "JSON", "intent": "Structured data"}
    try:
        import json as _json
        data = _json.loads(content)
        if isinstance(data, dict):
            out["top_level_keys"] = list(data.keys())[:20]
        elif isinstance(data, list):
            out["list_length"] = len(data)
    except Exception:
        pass
    return out


def _analyze_ipynb(content: str) -> dict:
    """Notebook: cell count and types."""
    out = {"format": "Jupyter", "intent": "Notebook; code and narrative"}
    try:
        import json as _json
        nb = _json.loads(content)
        cells = nb.get("cells") or []
        out["cell_count"] = len(cells)
        out["cell_types"] = list({c.get("cell_type", "code") for c in cells})
    except Exception:
        pass
    return out


def _intent_from_extension(ext: str, path: Path) -> dict:
    """Binary or opaque format: format + intent from North Star map."""
    ext = ext.lower()
    name = path.stem if path else "file"
    fmt, intent = _FILE_INTENT.get(ext, ("unknown", "Unknown format; describe from context"))
    return {"format": fmt, "intent": intent, "filename": name}


def analyze_file(file_path: str | Path = "", content: str | bytes | None = None) -> dict:
    """
    Analyze a file for intent and structure (North Star §4). Read-only.
    Returns dict: format, intent, and format-specific keys.
    """
    path = Path(file_path) if file_path else None
    ext = (path.suffix.lower() if path else "") or ""
    if content is None and path and path.exists():
        try:
            raw = path.read_bytes()
            content = raw.decode("utf-8", errors="replace") if ext in (
                ".py", ".dxf", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ipynb"
            ) else raw
        except Exception:
            content = b""
    if content is None:
        content = b"" if ext not in (".py", ".dxf", ".md", ".json", ".ipynb", ".yaml", ".yml", ".toml") else ""

    if ext == ".dxf":
        return _analyze_dxf(content)
    if ext == ".py":
        return _analyze_python(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
    if ext == ".md":
        return _analyze_markdown(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
    if ext == ".json":
        return _analyze_json(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
    if ext == ".ipynb":
        return _analyze_ipynb(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
    if ext in _FILE_INTENT:
        return _intent_from_extension(ext, path or Path(""))
    return {"format": ext or "unknown", "intent": "Unknown format; describe from context"}


def get_supported_extensions() -> list[str]:
    """Return list of extensions Layla can contextualize (North Star §4)."""
    return sorted(set(_FILE_INTENT.keys()))
