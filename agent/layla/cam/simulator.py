"""Trivial motion-time estimate (length / feed) — not collision-aware."""

from __future__ import annotations

import math
import re


def estimate_rough_time_minutes(*, path_length_mm: float, feed_mm_per_min: float) -> float:
    pl = max(0.0, float(path_length_mm or 0.0))
    f = max(1e-6, float(feed_mm_per_min or 1.0))
    return round(pl / f, 3)


def simulate_gcode(gcode_text: str) -> dict[str, object]:
    """
    Minimal 2D/3D path simulator for G0/G1/G2/G3.
    Returns path lengths, bounding box, estimated time, and move count.
    Not machine-accurate: ignores accel/jerk, tool radius, spindle, and modal planes beyond XY.
    """
    text = (gcode_text or "").strip()
    if not text:
        return {"ok": False, "error": "empty_gcode"}

    def _strip_comment(line: str) -> str:
        ln = line.strip()
        if not ln or ln.startswith(";"):
            return ""
        if ";" in ln:
            ln = ln.split(";", 1)[0].strip()
        # Remove parenthesis comments.
        ln = re.sub(r"\([^)]*\)", "", ln).strip()
        return ln

    def _parse_words(line: str) -> dict[str, float | str]:
        out: dict[str, float | str] = {}
        for w in re.findall(r"[A-Za-z][-+0-9.]+", line):
            k = w[0].upper()
            v = w[1:]
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
        return out

    def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

    units_scale = 1.0  # mm
    absolute = True
    x = y = z = 0.0
    feed = 0.0
    cut_len = 0.0
    rapid_len = 0.0
    move_count = 0
    x_min = x_max = x
    y_min = y_max = y
    z_min = z_max = z

    for raw in text.splitlines():
        ln = _strip_comment(raw)
        if not ln:
            continue
        up = ln.upper()
        words = _parse_words(up)

        # Units / positioning
        if "G20" in up:
            units_scale = 25.4  # inches -> mm
        if "G21" in up:
            units_scale = 1.0
        if "G90" in up:
            absolute = True
        if "G91" in up:
            absolute = False

        if "F" in words and isinstance(words["F"], float):
            feed = float(words["F"]) * units_scale

        # Modal motion: default to None if not present.
        motion = None
        if up.startswith("G0") or up.startswith("G00") or "G0" in up or "G00" in up:
            motion = "G0"
        if up.startswith("G1") or up.startswith("G01") or "G1" in up or "G01" in up:
            motion = "G1"
        if up.startswith("G2") or up.startswith("G02") or "G2" in up or "G02" in up:
            motion = "G2"
        if up.startswith("G3") or up.startswith("G03") or "G3" in up or "G03" in up:
            motion = "G3"

        if motion is None:
            continue

        # Target position
        tx, ty, tz = x, y, z
        if "X" in words and isinstance(words["X"], float):
            v = float(words["X"]) * units_scale
            tx = v if absolute else (tx + v)
        if "Y" in words and isinstance(words["Y"], float):
            v = float(words["Y"]) * units_scale
            ty = v if absolute else (ty + v)
        if "Z" in words and isinstance(words["Z"], float):
            v = float(words["Z"]) * units_scale
            tz = v if absolute else (tz + v)

        start = (x, y, z)
        end = (tx, ty, tz)

        seg_len = 0.0
        if motion in ("G0", "G1"):
            seg_len = _dist(start, end)
        elif motion in ("G2", "G3"):
            # XY arc with I/J center offsets from start point.
            i = float(words.get("I", 0.0) or 0.0) * units_scale if isinstance(words.get("I", 0.0), float) else 0.0
            j = float(words.get("J", 0.0) or 0.0) * units_scale if isinstance(words.get("J", 0.0), float) else 0.0
            cx, cy = x + i, y + j
            r = math.hypot(x - cx, y - cy)
            if r <= 1e-9:
                seg_len = _dist(start, end)
            else:
                a0 = math.atan2(y - cy, x - cx)
                a1 = math.atan2(ty - cy, tx - cx)
                da = a1 - a0
                if motion == "G2":  # CW
                    if da >= 0:
                        da -= 2 * math.pi
                else:  # G3 CCW
                    if da <= 0:
                        da += 2 * math.pi
                seg_len = abs(da) * r

        if motion == "G0":
            rapid_len += seg_len
        else:
            cut_len += seg_len

        x, y, z = tx, ty, tz
        move_count += 1
        x_min, x_max = min(x_min, x), max(x_max, x)
        y_min, y_max = min(y_min, y), max(y_max, y)
        z_min, z_max = min(z_min, z), max(z_max, z)

    # Time: assume rapids at 3x feed if feed known; otherwise 0 for rapids.
    feed_eff = max(1e-6, float(feed or 1.0))
    rapid_feed = feed_eff * 3.0
    est_min = estimate_rough_time_minutes(path_length_mm=cut_len, feed_mm_per_min=feed_eff)
    est_min += estimate_rough_time_minutes(path_length_mm=rapid_len, feed_mm_per_min=rapid_feed)

    return {
        "ok": True,
        "cut_length_mm": round(cut_len, 3),
        "rapid_length_mm": round(rapid_len, 3),
        "move_count": move_count,
        "bounding_box": {
            "x_min": round(x_min, 3),
            "x_max": round(x_max, 3),
            "y_min": round(y_min, 3),
            "y_max": round(y_max, 3),
            "z_min": round(z_min, 3),
            "z_max": round(z_max, 3),
        },
        "estimated_time_min": round(float(est_min), 3),
        "disclaimer": "Heuristic only — not a machine-accurate simulation.",
    }
