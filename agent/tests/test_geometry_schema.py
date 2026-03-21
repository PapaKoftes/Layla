"""Geometry program schema validation."""

import pytest


def test_parse_minimal_dxf_program():
    from layla.geometry.schema import parse_program

    p = parse_program(
        {
            "version": "1",
            "ops": [
                {"op": "dxf_begin", "units": "mm"},
                {"op": "dxf_line", "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                {"op": "dxf_save", "path": "out.dxf"},
            ],
        }
    )
    assert len(p.ops) == 3


def test_reject_unknown_op():
    from layla.geometry.schema import parse_program

    with pytest.raises(Exception):
        parse_program({"version": "1", "ops": [{"op": "unknown_op"}]})


def test_validate_program_dict():
    from layla.geometry.schema import validate_program_dict

    ok, msg, prog = validate_program_dict({"version": "1", "ops": [{"op": "dxf_begin"}]})
    assert ok
    assert prog is not None
