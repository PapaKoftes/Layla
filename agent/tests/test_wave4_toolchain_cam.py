from __future__ import annotations


def test_suggest_cheaper_path_ir_before_gcode():
    from services.tools.toolchain_graph import suggest_cheaper_path

    h = suggest_cheaper_path(["generate_gcode"])
    assert "geometry_extract_machining_ir" in h


def test_cam_feed_speed_hint_tool():
    from layla.tools.impl.geometry import cam_feed_speed_hint

    r = cam_feed_speed_hint(material="plywood", tool_diameter_mm=3.0)
    assert r.get("ok") is True
    assert "sfm_range_fpm" in r



def test_lookup_sfm():
    from layla.cam.feeds_speeds import lookup_sfm

    x = lookup_sfm("6061 aluminum", 6.0)
    assert "sfm_range_fpm" in x
