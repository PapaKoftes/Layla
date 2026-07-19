"""Process-wide filesystem *write* tracer.

Why this exists
---------------
Layla has a recurring defect class: a module resolves its data path at IMPORT time
from ``Path(__file__).parent...`` or ``Path.home()``, ignores ``LAYLA_DATA_DIR``, and
therefore writes into the operator's real state during the test suite. It has now
been found five separate times (working_memory, frame_modifier, tunnel_audit,
repo_indexer, skill_registry).

A hardcoded list of "known writers" cannot catch the sixth instance — by
construction it only knows about the ones already found. This module is the net:
it wraps every stdlib entry point that can create or modify a file and records any
write that lands outside the sanctioned roots.

The piece that is easy to miss
------------------------------
``sqlite3.connect`` opens its file through SQLite's own C layer. It never calls
``io.open`` or ``os.open`` at the Python level, so a tracer that patches only
io/os/pathlib is **blind to every database write in the codebase** — which is
exactly the defect class being hunted. It is patched here explicitly.
"""
from __future__ import annotations

import builtins
import io
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------

# Path *segments* that are always fine to write: build caches and test scaffolding.
_ALLOWED_SEGMENTS = (
    "__pycache__",
    ".pytest_cache",
    ".hypothesis",
    "site-packages",
    ".git",
)

# The null device is not a file. On Windows it normalises to \\.\nul.
_DEVNULL_NAMES = {"nul", "null", os.path.normcase(os.devnull)}

# Third-party libraries' own caches. Not Layla state, not the operator's data — and blocking them
# would only make the suite fail differently (a model download would error instead of caching).
# Kept explicit and narrow so it reads as a decision rather than an oversight.
_ALLOWED_SEGMENTS += (
    os.path.join(".cache", "huggingface"),
    os.path.join(".cache", "torch"),
    os.path.join("huggingface", "hub"),
    ".cache/huggingface",
)

# Filename suffixes that are always fine.
_ALLOWED_SUFFIXES = (".pyc", ".pyo", ".lock")

# Filename prefixes that are always fine (coverage data, editor swap files).
_ALLOWED_NAME_PREFIXES = (".coverage",)


def _norm(p) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.fspath(p)))
    except Exception:
        return ""


def _under(path: str, root: str) -> bool:
    if not root or not path:
        return False
    root = os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root + os.sep)


def sanctioned_roots() -> list[str]:
    """Roots a test is allowed to write to.

    Deliberately narrow: the isolated data dir and the machine's temp area (which is
    where ``tmp_path``/``tmp_path_factory`` live). Everything else is a finding.

    ``LAYLA_WRITE_TRACE_ROOTS`` (os.pathsep-separated) overrides the set entirely. That exists so
    the guard can prove itself: a canary run narrows the sanctioned set to one temp directory and
    checks the tracer still catches a brand-new wrong-root writer, without any test having to
    write to a genuinely protected location to demonstrate it.
    """
    override = (os.environ.get("LAYLA_WRITE_TRACE_ROOTS") or "").strip()
    if override:
        return [r for r in override.split(os.pathsep) if r]

    roots: list[str] = []
    data_dir = os.environ.get("LAYLA_DATA_DIR")
    if data_dir:
        roots.append(data_dir)
    roots.append(tempfile.gettempdir())
    # Some CI images resolve TMP to a short path but hand out long paths (or vice
    # versa); include both spellings so the net does not fire on its own scaffolding.
    try:
        roots.append(str(Path(tempfile.gettempdir()).resolve()))
        if data_dir:
            roots.append(str(Path(data_dir).resolve()))
    except Exception:
        pass
    return [r for r in roots if r]


def is_sanctioned(path: str, roots: list[str] | None = None) -> bool:
    if not path:
        return True
    norm = os.path.normcase(path)
    # ntpath treats the Windows null device as a UNC share, so basename() returns "".
    # Split on both separators manually instead.
    tail = norm.replace("/", "\\").rsplit("\\", 1)[-1]
    if tail in _DEVNULL_NAMES or norm in _DEVNULL_NAMES:
        return True
    for seg in _ALLOWED_SEGMENTS:
        if os.path.normcase(seg) in norm:
            return True
    name = os.path.basename(norm)
    if name.endswith(_ALLOWED_SUFFIXES) or name.startswith(_ALLOWED_NAME_PREFIXES):
        return True
    for root in roots if roots is not None else sanctioned_roots():
        if _under(norm, root):
            return True
    return False


def _mode_writes(mode: str) -> bool:
    return any(c in (mode or "") for c in ("w", "a", "x", "+"))


def _flags_write(flags: int) -> bool:
    return bool(
        flags & (getattr(os, "O_WRONLY", 0) | getattr(os, "O_RDWR", 0) | getattr(os, "O_CREAT", 0))
    )


# --------------------------------------------------------------------------------------
# Tracer
# --------------------------------------------------------------------------------------


@dataclass
class WriteEvent:
    path: str
    op: str
    origin: str = ""

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{self.op:<18} {self.path}" + (f"\n    via {self.origin}" if self.origin else "")


@dataclass
class WriteTracer:
    """Records writes landing outside :func:`sanctioned_roots`.

    Only unsanctioned writes are recorded, so the hot path stays cheap enough to run a
    real slice of the suite under it.
    """

    events: list[WriteEvent] = field(default_factory=list)
    _installed: bool = False
    _saved: dict = field(default_factory=dict)
    _roots: list[str] = field(default_factory=list)
    # Guard against re-entrancy: our own bookkeeping must not trace itself.
    _busy: bool = False

    # -- recording ---------------------------------------------------------------

    def _origin(self) -> str:
        """Nearest frame outside this module and the stdlib — i.e. the culprit."""
        try:
            frame = sys._getframe(1)
        except Exception:
            return ""
        here = os.path.normcase(os.path.abspath(__file__))
        stdlib = os.path.normcase(os.path.dirname(os.__file__))
        depth = 0
        while frame is not None and depth < 40:
            fname = os.path.normcase(os.path.abspath(frame.f_code.co_filename))
            if fname != here and not fname.startswith(stdlib) and "importlib" not in fname:
                return f"{frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}"
            frame = frame.f_back
            depth += 1
        return ""

    def _record(self, path, op: str) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            norm = _norm(path)
            if norm and not is_sanctioned(norm, self._roots):
                self.events.append(WriteEvent(norm, op, self._origin()))
        except Exception:
            pass
        finally:
            self._busy = False

    # -- install/uninstall -------------------------------------------------------

    def install(self) -> "WriteTracer":
        if self._installed:
            return self
        self._roots = sanctioned_roots()
        rec = self._record

        # builtins.open / io.open (same object, patched on both namespaces)
        real_open = builtins.open
        self._saved["builtins.open"] = real_open
        self._saved["io.open"] = io.open

        # NOTE on ordering: every wrapper calls the real function FIRST and records only if it
        # returned. A write that raised (a test deliberately pointing at an impossible path)
        # changed nothing, and a net that flags it is reporting intent rather than effect.
        def traced_open(file, mode="r", *a, **kw):
            fh = real_open(file, mode, *a, **kw)
            if _mode_writes(mode if isinstance(mode, str) else ""):
                rec(file, "open")
            return fh

        builtins.open = traced_open
        io.open = traced_open

        # os.open
        real_os_open = os.open
        self._saved["os.open"] = real_os_open

        def traced_os_open(path, flags, *a, **kw):
            fd = real_os_open(path, flags, *a, **kw)
            if _flags_write(flags):
                rec(path, "os.open")
            return fd

        os.open = traced_os_open

        # sqlite3.connect — the entry point a naive tracer misses entirely.
        real_connect = sqlite3.connect
        self._saved["sqlite3.connect"] = real_connect

        def traced_connect(database, *a, **kw):
            con = real_connect(database, *a, **kw)
            db = database
            if isinstance(db, (str, bytes, os.PathLike)):
                s = os.fspath(db) if not isinstance(db, bytes) else db.decode("utf-8", "replace")
                if s and s != ":memory:" and not s.startswith("file::memory:"):
                    # Recorded even against an existing DB: callers immediately issue
                    # `PRAGMA journal_mode=WAL`, which writes -wal/-shm beside the file.
                    rec(s, "sqlite3.connect")
            return con

        sqlite3.connect = traced_connect

        # os-level mutators
        for name, op in (
            ("mkdir", "os.mkdir"),
            ("makedirs", "os.makedirs"),
            ("remove", "os.remove"),
            ("unlink", "os.unlink"),
            ("rmdir", "os.rmdir"),
        ):
            self._patch_os(name, op)
        self._patch_os_2arg("rename", "os.rename")
        self._patch_os_2arg("replace", "os.replace")

        # pathlib
        for name, op in (
            ("write_text", "Path.write_text"),
            ("write_bytes", "Path.write_bytes"),
            ("mkdir", "Path.mkdir"),
            ("touch", "Path.touch"),
            ("unlink", "Path.unlink"),
        ):
            self._patch_path(name, op)

        real_path_open = Path.open
        self._saved["Path.open"] = real_path_open

        def traced_path_open(self_p, mode="r", *a, **kw):
            fh = real_path_open(self_p, mode, *a, **kw)
            if _mode_writes(mode if isinstance(mode, str) else ""):
                rec(self_p, "Path.open")
            return fh

        Path.open = traced_path_open

        # shutil
        for name, op in (
            ("copy", "shutil.copy"),
            ("copy2", "shutil.copy2"),
            ("copyfile", "shutil.copyfile"),
            ("move", "shutil.move"),
            ("copytree", "shutil.copytree"),
        ):
            self._patch_shutil_dst(name, op)

        real_rmtree = shutil.rmtree
        self._saved["shutil.rmtree"] = real_rmtree

        def traced_rmtree(path, *a, **kw):
            result = real_rmtree(path, *a, **kw)
            rec(path, "shutil.rmtree")
            return result

        shutil.rmtree = traced_rmtree

        self._installed = True
        return self

    def _patch_os(self, name: str, op: str) -> None:
        real = getattr(os, name)
        self._saved[f"os.{name}"] = real
        rec = self._record
        # `mkdir(exist_ok=True)` against a directory that already exists is a genuine no-op.
        # Recording it would make the net fire on every `load_config()` (which ensures
        # sandbox_root exists) and train readers to ignore it.
        creates = name in ("mkdir", "makedirs")

        def traced(path, *a, **kw):
            existed = os.path.exists(path) if creates else False
            result = real(path, *a, **kw)
            if not existed:
                rec(path, op)
            return result

        setattr(os, name, traced)

    def _patch_os_2arg(self, name: str, op: str) -> None:
        real = getattr(os, name)
        self._saved[f"os.{name}"] = real
        rec = self._record

        def traced(src, dst, *a, **kw):
            result = real(src, dst, *a, **kw)
            rec(dst, op)
            return result

        setattr(os, name, traced)

    def _patch_path(self, name: str, op: str) -> None:
        real = getattr(Path, name)
        self._saved[f"Path.{name}"] = real
        rec = self._record
        creates = name == "mkdir"

        def traced(self_p, *a, **kw):
            existed = False
            if creates:
                try:
                    existed = self_p.exists()
                except Exception:
                    existed = False
            result = real(self_p, *a, **kw)
            if not existed:
                rec(self_p, op)
            return result

        setattr(Path, name, traced)

    def _patch_shutil_dst(self, name: str, op: str) -> None:
        real = getattr(shutil, name)
        self._saved[f"shutil.{name}"] = real
        rec = self._record

        def traced(src, dst, *a, **kw):
            result = real(src, dst, *a, **kw)
            rec(dst, op)
            return result

        setattr(shutil, name, traced)

    def uninstall(self) -> None:
        if not self._installed:
            return
        for key, obj in self._saved.items():
            mod, _, attr = key.partition(".")
            target = {"builtins": builtins, "io": io, "os": os, "shutil": shutil,
                      "sqlite3": sqlite3, "Path": Path}[mod]
            setattr(target, attr, obj)
        self._saved.clear()
        self._installed = False

    def __enter__(self) -> "WriteTracer":
        return self.install()

    def __exit__(self, *exc) -> None:
        self.uninstall()

    # -- reporting ---------------------------------------------------------------

    def report(self, limit: int = 40) -> str:
        if not self.events:
            return "(no unsanctioned writes)"
        by_path: dict[str, list[WriteEvent]] = {}
        for ev in self.events:
            by_path.setdefault(ev.path, []).append(ev)
        lines = [f"{len(self.events)} unsanctioned write(s) across {len(by_path)} path(s):"]
        for path, evs in sorted(by_path.items(), key=lambda kv: -len(kv[1]))[:limit]:
            ops = sorted({e.op for e in evs})
            lines.append(f"  {path}  x{len(evs)}  [{', '.join(ops)}]")
            origin = next((e.origin for e in evs if e.origin), "")
            if origin:
                lines.append(f"      first via {origin}")
        return "\n".join(lines)
