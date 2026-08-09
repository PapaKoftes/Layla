"""
Phase 3 (North Star 5/17): recognize MACHINABLE FEATURES from raw primitives.

Consumes read_geometry() / machining_ir output (2D DXF features or 3D B-rep holes) and groups
primitives into the things a machinist actually thinks in: same-size hole groups (one tool),
bolt circles, rectangular hole patterns, linear arrays, and pockets (a closed contour with
islands). Pure deterministic geometry -- no LLM, no CAM certification.
"""
from __future__ import annotations

import math
from typing import Any

_ANG_TOL_DEG = 1.5      # angular evenness tolerance for a bolt circle
_REL_TOL = 0.02         # relative distance tolerance (2%)
_ABS_TOL = 1e-3


def _extract_holes(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize holes from either 3D B-rep output ('holes') or 2D machining IR ('features')."""
    holes: list[dict[str, Any]] = []
    for h in geometry.get("holes") or []:
        c = h.get("center") or [0.0, 0.0, 0.0]
        holes.append({
            "x": float(c[0]), "y": float(c[1]), "z": float(c[2]) if len(c) > 2 else 0.0,
            "r": float(h.get("radius") or 0.0),
            "axis": tuple(round(float(a), 4) for a in (h.get("axis_dir") or (0.0, 0.0, 1.0))),
        })
    for f in geometry.get("features") or []:
        if f.get("type") == "hole":
            c = f.get("center") or [0.0, 0.0]
            holes.append({
                "x": float(c[0]), "y": float(c[1]), "z": 0.0,
                "r": float(f.get("radius") or 0.0), "axis": (0.0, 0.0, 1.0),
            })
    return holes


def group_holes_by_size(holes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group holes by radius -> each group is one drill/tool. Sorted by diameter."""
    groups: dict[float, list[dict[str, Any]]] = {}
    for h in holes:
        groups.setdefault(round(h["r"], 3), []).append(h)
    return [
        {"diameter": round(2 * r, 4), "radius": r, "count": len(v),
         "centers": [[round(h["x"], 4), round(h["y"], 4)] for h in v]}
        for r, v in sorted(groups.items())
    ]


def _centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def detect_bolt_circle(holes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Equal-radius holes, equidistant from a common centre, evenly spaced in angle."""
    if len(holes) < 3:
        return None
    if max(h["r"] for h in holes) - min(h["r"] for h in holes) > _ABS_TOL:
        return None
    pts = [(h["x"], h["y"]) for h in holes]
    cx, cy = _centroid(pts)
    dists = [math.hypot(x - cx, y - cy) for x, y in pts]
    pcd_r = sum(dists) / len(dists)
    if pcd_r <= _ABS_TOL:
        return None
    if max(abs(d - pcd_r) for d in dists) > max(_ABS_TOL, _REL_TOL * pcd_r):
        return None
    angs = sorted(math.degrees(math.atan2(y - cy, x - cx)) % 360 for x, y in pts)
    exp = 360.0 / len(angs)
    diffs = [(angs[(i + 1) % len(angs)] - angs[i]) % 360 for i in range(len(angs))]
    if max(abs(d - exp) for d in diffs) > _ANG_TOL_DEG:
        return None
    return {
        "type": "bolt_circle", "count": len(holes),
        "center": [round(cx, 4), round(cy, 4)],
        "pitch_circle_diameter": round(2 * pcd_r, 4),
        "hole_diameter": round(2 * holes[0]["r"], 4),
    }


def detect_rectangular_pattern(holes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Equal-radius holes on a full cols x rows grid of distinct X and Y positions."""
    if len(holes) < 4:
        return None
    if max(h["r"] for h in holes) - min(h["r"] for h in holes) > _ABS_TOL:
        return None
    xs = sorted({round(h["x"], 3) for h in holes})
    ys = sorted({round(h["y"], 3) for h in holes})
    if len(xs) >= 2 and len(ys) >= 2 and len(xs) * len(ys) == len(holes):
        return {
            "type": "rectangular_pattern", "count": len(holes),
            "cols": len(xs), "rows": len(ys),
            "x_positions": xs, "y_positions": ys,
            "hole_diameter": round(2 * holes[0]["r"], 4),
        }
    return None


def detect_linear_array(holes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Equal-radius holes that are collinear and evenly spaced."""
    if len(holes) < 3:
        return None
    if max(h["r"] for h in holes) - min(h["r"] for h in holes) > _ABS_TOL:
        return None
    pts = sorted(((h["x"], h["y"]) for h in holes), key=lambda p: (p[0], p[1]))
    (x0, y0), (xn, yn) = pts[0], pts[-1]
    dx, dy = xn - x0, yn - y0
    span = math.hypot(dx, dy)
    if span <= _ABS_TOL:
        return None
    ux, uy = dx / span, dy / span
    # collinear: every point's perpendicular distance to the line ~ 0
    for x, y in pts:
        perp = abs((x - x0) * (-uy) + (y - y0) * ux)
        if perp > max(_ABS_TOL, _REL_TOL * span):
            return None
    projs = sorted((x - x0) * ux + (y - y0) * uy for x, y in pts)
    step = span / (len(pts) - 1)
    for i in range(1, len(projs)):
        if abs((projs[i] - projs[i - 1]) - step) > max(_ABS_TOL, _REL_TOL * span):
            return None
    return {
        "type": "linear_array", "count": len(holes),
        "pitch": round(step, 4), "length": round(span, 4),
        "hole_diameter": round(2 * holes[0]["r"], 4),
    }


def detect_pockets(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    """A pocket = a closed contour (from the 2D IR) that encloses hole(s)/island(s)."""
    feats = geometry.get("features") or []
    contours = [f for f in feats if f.get("type") == "contour" and f.get("bbox")]
    holes = [f for f in feats if f.get("type") == "hole"]
    pockets: list[dict[str, Any]] = []
    for c in contours:
        x0, y0, x1, y1 = c["bbox"]
        inside = [h for h in holes if x0 <= (h.get("center") or [0, 0])[0] <= x1
                  and y0 <= (h.get("center") or [0, 0])[1] <= y1]
        if inside:
            pockets.append({
                "type": "pocket", "contour_id": c.get("id"),
                "bbox": c["bbox"], "islands": len(inside),
                "perimeter": c.get("perimeter"),
            })
    return pockets


def recognize_features(geometry: dict[str, Any]) -> dict[str, Any]:
    """Top-level: extract holes, group by size, and recognize the strongest overall pattern.

    Per same-size group we try bolt_circle -> rectangular_pattern -> linear_array (most specific
    first). Groups that match nothing are reported as plain hole groups. Also detects pockets (2D).
    """
    holes = _extract_holes(geometry)
    size_groups = group_holes_by_size(holes)
    patterns: list[dict[str, Any]] = []
    for g in size_groups:
        same = [h for h in holes if round(h["r"], 3) == g["radius"]]
        pat = detect_bolt_circle(same) or detect_rectangular_pattern(same) or detect_linear_array(same)
        if pat:
            patterns.append(pat)
    pockets = detect_pockets(geometry)
    return {
        "ok": bool(geometry.get("ok", True)),
        "hole_count": len(holes),
        "hole_size_groups": size_groups,
        "patterns": patterns,
        "pockets": pockets,
    }
