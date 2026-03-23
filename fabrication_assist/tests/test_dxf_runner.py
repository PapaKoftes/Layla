"""
Tests for fabrication_assist.assist.runner.DXFBuildRunner.
Requires ezdxf: pip install ezdxf
Tests gracefully skip if ezdxf is not installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the repo root is on sys.path so fabrication_assist is importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_ezdxf_available = False
try:
    import ezdxf
    _ezdxf_available = True
except ImportError:
    pass

pytestmark_ezdxf = pytest.mark.skipif(
    not _ezdxf_available, reason="ezdxf not installed (pip install ezdxf)"
)


# ---------------------------------------------------------------------------
# Schema tests (always run — no ezdxf needed)
# ---------------------------------------------------------------------------

class TestFabricationSchemas:
    def test_fabrication_operation_defaults(self):
        from fabrication_assist.assist.schemas import FabricationOperation
        op = FabricationOperation(type="cut_rect", x=10, y=20, width=50, height=30)
        assert op.type == "cut_rect"
        assert op.x == 10.0
        assert op.width == 50.0
        assert op.path_points == []

    def test_fabrication_job_defaults(self):
        from fabrication_assist.assist.schemas import FabricationJob
        job = FabricationJob(name="test_job")
        assert job.name == "test_job"
        assert job.units == "mm"
        assert job.operations == []

    def test_build_result_ok(self):
        from fabrication_assist.assist.schemas import BuildResult
        r = BuildResult(ok=True, output_path="/tmp/foo.dxf")
        assert r.ok is True
        assert r.output_path == "/tmp/foo.dxf"
        assert r.error == ""

    def test_build_result_error(self):
        from fabrication_assist.assist.schemas import BuildResult
        r = BuildResult(ok=False, error="something went wrong")
        assert r.ok is False
        assert r.error == "something went wrong"


# ---------------------------------------------------------------------------
# DXFBuildRunner: import raises RuntimeError if ezdxf not installed
# ---------------------------------------------------------------------------

class TestDXFBuildRunnerImportGuard:
    def test_raises_if_ezdxf_missing(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob

        job = FabricationJob(name="test", operations=[])

        with patch.dict("sys.modules", {"ezdxf": None}):
            runner = DXFBuildRunner(output_dir=tmp_path)
            with pytest.raises(RuntimeError, match="ezdxf required"):
                runner.run(job)


# ---------------------------------------------------------------------------
# DXFBuildRunner functional tests (ezdxf required)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ezdxf_available, reason="ezdxf not installed")
class TestDXFBuildRunner:
    def _make_runner(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        return DXFBuildRunner(output_dir=tmp_path)

    def test_simple_rect_cut_creates_file(self, tmp_path):
        """rect cut job produces a .dxf file that ezdxf can read back."""
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="rect_test",
            operations=[
                FabricationOperation(type="cut_rect", x=0, y=0, width=100, height=50),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        assert result.error == ""
        output = Path(result.output_path)
        assert output.exists()
        assert output.suffix == ".dxf"

        # Verify ezdxf can read the output
        doc = ezdxf.readfile(str(output))
        msp = doc.modelspace()
        entities = list(msp)
        assert len(entities) >= 1
        # Should have a LWPOLYLINE
        types = [e.dxftype() for e in entities]
        assert "LWPOLYLINE" in types

    def test_circle_cut(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="circle_test",
            operations=[
                FabricationOperation(type="cut_circle", x=50, y=50, radius=25),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        doc = ezdxf.readfile(result.output_path)
        types = [e.dxftype() for e in doc.modelspace()]
        assert "CIRCLE" in types

    def test_slot_cut(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="slot_test",
            operations=[
                FabricationOperation(
                    type="cut_slot",
                    radius=5.0,
                    start=[10.0, 10.0],
                    end=[60.0, 10.0],
                ),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        doc = ezdxf.readfile(result.output_path)
        types = [e.dxftype() for e in doc.modelspace()]
        # Should have lines and arcs
        assert "LINE" in types
        assert "ARC" in types

    def test_pocket_operation(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="pocket_test",
            operations=[
                FabricationOperation(
                    type="pocket",
                    path_points=[[0, 0], [40, 0], [40, 30], [0, 30]],
                ),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        doc = ezdxf.readfile(result.output_path)
        types = [e.dxftype() for e in doc.modelspace()]
        assert "LWPOLYLINE" in types

    def test_profile_operation(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="profile_test",
            operations=[
                FabricationOperation(
                    type="profile",
                    path_points=[[0, 0], [50, 0], [50, 25], [25, 50]],
                ),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        doc = ezdxf.readfile(result.output_path)
        types = [e.dxftype() for e in doc.modelspace()]
        assert "LWPOLYLINE" in types

    def test_multiple_operations(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="multi_op",
            operations=[
                FabricationOperation(type="cut_rect", x=0, y=0, width=200, height=100),
                FabricationOperation(type="cut_circle", x=50, y=50, radius=10),
                FabricationOperation(type="cut_circle", x=150, y=50, radius=10),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        doc = ezdxf.readfile(result.output_path)
        entities = list(doc.modelspace())
        # 1 rect + 2 circles = 3 entities minimum
        assert len(entities) >= 3

    def test_unknown_operation_warns_but_continues(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="warn_test",
            operations=[
                FabricationOperation(type="cut_rect", x=0, y=0, width=50, height=50),
                FabricationOperation(type="unknown_op"),
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        assert any("unknown_op" in w.lower() or "Unknown operation" in w for w in result.warnings)

    def test_empty_job(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob

        job = FabricationJob(name="empty_job", operations=[])
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        assert Path(result.output_path).exists()

    def test_slot_missing_start_end_warns(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob, FabricationOperation

        job = FabricationJob(
            name="slot_warn_test",
            operations=[
                FabricationOperation(type="cut_slot", radius=5.0),  # no start/end
            ],
        )
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert result.ok is True
        assert any("start" in w.lower() or "missing" in w.lower() for w in result.warnings)

    def test_output_file_named_after_job(self, tmp_path):
        from fabrication_assist.assist.runner import DXFBuildRunner
        from fabrication_assist.assist.schemas import FabricationJob

        job = FabricationJob(name="my_part", operations=[])
        runner = DXFBuildRunner(output_dir=tmp_path)
        result = runner.run(job)

        assert "my_part" in Path(result.output_path).name

    def test_run_build_compat_shim(self, tmp_path):
        """run_build() should work like a BuildRunner protocol member."""
        from fabrication_assist.assist.runner import DXFBuildRunner

        runner = DXFBuildRunner(output_dir=tmp_path)
        config = {
            "name": "shim_test",
            "operations": [
                {"type": "cut_rect", "x": 0, "y": 0, "width": 30, "height": 20},
            ],
        }
        result = runner.run_build(config)

        assert isinstance(result, dict)
        assert result["variant_id"] == "shim_test"
        assert result["feasible"] is True
