"""
Deterministic intermediate representation: DXF geometry → machining features → ordered toolpath groups.

No LLM / agent loop. Bridges file understanding and fabrication tools (e.g. generate_gcode).
See docs/FABRICATION_IR_AND_TOOLCHAIN.md.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def _arc_length(radius: float, a0: float, a1: float) -> float:
    da = abs(a1 - a0)
    while da > 2 * math.pi:
        da -= 2 * math.pi
    return abs(radius * da)


def extract_features_from_dxf(path: Path) -> list[dict[str, Any]]:
    """
    Parse DXF modelspace into structured features (deterministic).
    Feature types: hole (CIRCLE), contour (closed polyline), open_path, line_segment, arc_segment.
    """
    try:
        import ezdxf
    except ImportError:
        logger.debug("extract_features_from_dxf: ezdxf not installed")
        return []

    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return []

    try:
        doc = ezdxf.readfile(str(p))
    except Exception as e:
        logger.debug("extract_features_from_dxf read failed: %s", e)
        return []

    msp = doc.modelspace()
    features: list[dict[str, Any]] = []
    fid = 0

    for e in msp:
        layer = str(getattr(getattr(e, "dxf", None), "layer", "") or "")
        dt = e.dxftype()

        if dt == "CIRCLE":
            c = e.dxf.center
            r = float(e.dxf.radius)
            fid += 1
            features.append({
                "id": f"hole_{fid}",
                "type": "hole",
                "layer": layer,
                "center": [float(c[0]), float(c[1])],
                "radius": r,
                "perimeter": 2 * math.pi * r,
            })
        elif dt == "ARC":
            c = e.dxf.center
            r = float(e.dxf.radius)
            a0 = float(e.dxf.start_angle)
            a1 = float(e.dxf.end_angle)
            fid += 1
            features.append({
                "id": f"arc_{fid}",
                "type": "arc_segment",
                "layer": layer,
                "center": [float(c[0]), float(c[1])],
                "radius": r,
                "start_angle": a0,
                "end_angle": a1,
                "length": _arc_length(r, a0, a1),
            })
        elif dt == "LINE":
            s = e.dxf.start
            t = e.dxf.end
            fid += 1
            features.append({
                "id": f"seg_{fid}",
                "type": "line_segment",
                "layer": layer,
                "start": [float(s[0]), float(s[1])],
                "end": [float(t[0]), float(t[1])],
                "length": math.hypot(float(t[0]) - float(s[0]), float(t[1]) - float(s[1])),
            })
        elif dt == "LWPOLYLINE":
            pts = list(e.get_points("xy"))
            if len(pts) < 2:
                continue
            closed = bool(e.closed)
            plen = 0.0
            for i in range(len(pts) - 1):
                x0, y0 = float(pts[i][0]), float(pts[i][1])
                x1, y1 = float(pts[i + 1][0]), float(pts[i + 1][1])
                plen += math.hypot(x1 - x0, y1 - y0)
            if closed and len(pts) >= 3:
                x0, y0 = float(pts[-1][0]), float(pts[-1][1])
                x1, y1 = float(pts[0][0]), float(pts[0][1])
                plen += math.hypot(x1 - x0, y1 - y0)
            fid += 1
            features.append({
                "id": f"poly_{fid}",
                "type": "contour" if closed else "open_path",
                "layer": layer,
                "closed": closed,
                "vertex_count": len(pts),
                "perimeter": plen,
                "bbox": _bbox_poly(pts),
            })

    return features


def _bbox_poly(pts: list) -> list[float]:
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def plan_toolpath_order(features: list[dict[str, Any]]) -> list[str]:
    """
    Deterministic ordering: holes ascending by radius, then contours by perimeter (larger first),
    then remaining features by id.
    """
    holes = [f for f in features if f.get("type") == "hole"]
    contours = [f for f in features if f.get("type") == "contour"]
    rest = [f for f in features if f.get("type") not in ("hole", "contour")]

    holes.sort(key=lambda f: (float(f.get("radius") or 0), f.get("id", "")))
    contours.sort(key=lambda f: -float(f.get("perimeter") or 0))
    rest.sort(key=lambda f: str(f.get("id", "")))

    ordered = holes + contours + rest
    return [str(f.get("id", "")) for f in ordered if f.get("id")]


def build_machine_steps_preview(features: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    """Map ordered feature ids to coarse machine ops (preview only, not full CAM)."""
    by_id = {str(f.get("id")): f for f in features if f.get("id")}
    steps: list[dict[str, Any]] = []
    for i, fid in enumerate(order):
        f = by_id.get(fid)
        if not f:
            continue
        t = f.get("type", "")
        if t == "hole":
            steps.append({
                "step": i + 1,
                "op": "drill_or_pocket_circle",
                "feature_id": fid,
                "layer": f.get("layer", ""),
                "note": "circle at center, radius from feature",
            })
        elif t == "contour":
            steps.append({
                "step": i + 1,
                "op": "profile_cut_2d",
                "feature_id": fid,
                "layer": f.get("layer", ""),
                "note": "follow closed polyline; set depth/offset in CAM",
            })
        elif t == "open_path":
            steps.append({
                "step": i + 1,
                "op": "engrave_or_open_contour",
                "feature_id": fid,
                "layer": f.get("layer", ""),
            })
        elif t == "line_segment":
            steps.append({
                "step": i + 1,
                "op": "cut_segment",
                "feature_id": fid,
                "layer": f.get("layer", ""),
            })
        elif t == "arc_segment":
            steps.append({
                "step": i + 1,
                "op": "cut_arc",
                "feature_id": fid,
                "layer": f.get("layer", ""),
            })
        else:
            steps.append({"step": i + 1, "op": "review_geometry", "feature_id": fid})
    return steps


def build_machining_ir(dxf_path: str) -> dict[str, Any]:
    """Full IR package from a DXF path (sandbox-checked by caller)."""
    path = Path(dxf_path).expanduser().resolve()
    feats = extract_features_from_dxf(path)
    order = plan_toolpath_order(feats)
    machine_steps = build_machine_steps_preview(feats, order)
    return {
        "ok": True,
        "source": str(path),
        "feature_count": len(feats),
        "features": feats,
        "toolpath_order": order,
        "machine_steps_preview": machine_steps,
    }


def validate_machining_ir_dict(ir: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic checks only — not CAM-safe certification.
    Returns machine_readiness: interpretive_preview | not_validated
    """
    issues: list[str] = []
    if not isinstance(ir, dict):
        return {
            "ok": False,
            "issues": ["invalid_ir"],
            "machine_readiness": "not_validated",
        }
    feats = ir.get("features")
    if not isinstance(feats, list) or len(feats) == 0:
        issues.append("no_features")
    else:
        for f in feats[:500]:
            if not isinstance(f, dict):
                issues.append("bad_feature_row")
                break
            bb = f.get("bbox")
            if isinstance(bb, list) and len(bb) == 4:
                try:
                    x0, y0, x1, y1 = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
                    if x1 < x0 or y1 < y0:
                        issues.append("inverted_bbox")
                except (TypeError, ValueError):
                    issues.append("bbox_parse")
            if f.get("type") == "contour" and int(f.get("vertex_count") or 0) < 3:
                issues.append("degenerate_contour")
    steps = ir.get("machine_steps_preview")
    if isinstance(steps, list) and len(steps) == 0 and feats and len(feats) > 0:
        issues.append("empty_machine_steps")
    ok = len(issues) == 0
    return {
        "ok": ok,
        "issues": issues[:20],
        "machine_readiness": "interpretive_preview" if ok else "not_validated",
    }


def validate_gcode_text(gcode: str) -> dict[str, Any]:
    """Cheap structural checks — does not prove collision-free or machine-safe motion."""
    errors: list[str] = []
    warnings: list[str] = []
    text = (gcode or "").strip()
    if not text:
        return {
            "ok": False,
            "issues": ["empty_gcode"],
            "errors": ["empty_gcode"],
            "warnings": [],
            "machine_readiness": "not_validated",
        }
    lines = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith(";"):
            continue
        # Strip trailing ';' comments.
        if ";" in ln:
            ln = ln.split(";", 1)[0].strip()
        if ln:
            lines.append(ln)
    if not lines:
        errors.append("no_executable_lines")

    safe_g = {0, 1, 2, 3, 17, 18, 19, 20, 21, 28, 90, 91}
    safe_m = {0, 1, 2, 3, 4, 5, 6, 30}
    saw_units = False
    saw_spindle_on = False
    saw_spindle_off = False
    saw_feed = False
    saw_motion = False
    feed_before_first_cut_ok = True

    import re

    for ln in lines:
        up = ln.upper()
        # Units: G20 (inches) or G21 (mm)
        if "G20" in up or "G21" in up:
            saw_units = True
        # Spindle: M3/M4 on, M5 off
        if "M3" in up or "M4" in up:
            saw_spindle_on = True
        if "M5" in up:
            saw_spindle_off = True
        # Feed word
        if "F" in up:
            saw_feed = True
        # Unknown G/M codes outside safe subset
        for m in re.findall(r"\bG(\d{1,3})\b", up):
            try:
                code = int(m)
            except ValueError:
                continue
            if code not in safe_g:
                errors.append(f"unknown_g{code}")
        for m in re.findall(r"\bM(\d{1,3})\b", up):
            try:
                code = int(m)
            except ValueError:
                continue
            if code not in safe_m:
                errors.append(f"unknown_m{code}")

        # Motion presence + feed-before-cut heuristic (first G1/G2/G3 should have feed set)
        if up.startswith("G0") or up.startswith("G00") or up.startswith("G1") or up.startswith("G01") or up.startswith("G2") or up.startswith("G02") or up.startswith("G3") or up.startswith("G03"):
            saw_motion = True
        if (up.startswith("G1") or up.startswith("G01") or up.startswith("G2") or up.startswith("G02") or up.startswith("G3") or up.startswith("G03")) and not saw_feed:
            # Allow feed on same line (e.g., "G1 X.. Y.. F300")
            if "F" not in up:
                feed_before_first_cut_ok = False

    if not saw_units:
        warnings.append("missing_units_g20_g21")
    if not saw_motion:
        errors.append("no_motion_g0_g1_g2_g3")
    if not saw_feed:
        errors.append("no_feed_word")
    if not feed_before_first_cut_ok:
        errors.append("feed_not_set_before_first_cut_move")
    if saw_spindle_on and not saw_spindle_off:
        warnings.append("spindle_on_without_m5")
    if not saw_spindle_on:
        warnings.append("missing_spindle_on_m3_m4")

    # Back-compat: keep `issues` (combined) for existing callers.
    issues = (errors + warnings)[:40]
    ok = len(errors) == 0
    return {
        "ok": ok,
        "issues": issues[:20],
        "errors": errors[:20],
        "warnings": warnings[:20],
        "machine_readiness": "interpretive_preview" if ok else "not_validated",
    }
