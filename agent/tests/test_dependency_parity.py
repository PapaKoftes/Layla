"""Static dependency-parity gate (Phase 13 / S1).

Two divergences between "what CI installs" and "what a user can install":

  A. CI installs a dist no user can obtain.
     Every CI job runs `pip install -r agent/requirements.txt`. If a dist there appears in NO
     pyproject extra, CI exercises that dep's code path but nobody installing Layla can
     reproduce it. CI is then green on a configuration that does not ship.

  B. A dist every default user gets, but CI never installs.
     If a dist reachable from `pip install layla[all]` FLIPS A PATH (its absence silently
     changes behaviour instead of failing) and it is absent from requirements.txt, then CI
     permanently tests the *fallback* branch while every real user takes the *present* branch.
     The branch that ships is the branch nothing tests.

THE PATH-FLIPPING SET IS DERIVED BY AST, NEVER HAND-MAINTAINED.
We walk agent/**/*.py and find every `try: import X` whose except handler catches ImportError
and does not propagate the import failure. This matters: the predecessor of this gate used a
hand-written dict of "deps we think flip a path", and it missed `keyring` — which is in
[core]+[cpu] (every user has it), absent from requirements.txt (CI never installs it), and
flips a path in services/safety/secret_store.py. A guard with a hand-maintained inclusion list
is a guard that misses the next instance. This gate exists because one did.

DELIBERATE SCOPE LIMITS (stated so the gate stays true rather than convenient):
  * Direction B is scoped to the `[all]` closure — the default install surface. `[cpu]` and
    `[voice-kokoro]` are deliberately NOT in `[all]`: [cpu] is the alternative compiler-free
    laptop profile, [voice-kokoro] is a GPLv3 opt-in excluded for licence reasons (REQ-02).
    Their divergences (model2vec/sqlite-vec, kokoro-onnx/soundfile) are REAL but are not
    enforced here — fixing them means resolving a profile conflict and a licence conflict
    respectively. They are recorded in the phase report. A permanently-red test gets
    deselected, and a deselected test is worse than an honest scope limit.
  * `[dev]` IS a valid destination for direction A: `pip install layla[dev]` is a real command,
    so pytest et al. in requirements.txt are legitimately reachable by a user.
  * Only `agent/` is scanned; requirements-e2e.txt (e2e-only tooling) is out of scope.

This gate is pure static analysis: no dep is imported, no network, no skipif. It must produce
the same verdict on both venvs and in CI. A gate that silently passes is this codebase's
signature failure mode.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import tomllib  # stdlib >=3.11; pyproject pins requires-python >=3.11

TESTS_DIR = pathlib.Path(__file__).resolve().parent
AGENT_DIR = TESTS_DIR.parent
REPO_ROOT = AGENT_DIR.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = AGENT_DIR / "requirements.txt"

# Handlers that swallow an ImportError. ImportError/ModuleNotFoundError are the precise ones;
# Exception/BaseException/bare are supersets that also swallow it. `keyring` is caught only
# because we include Exception — secret_store.py uses `except Exception`, so an
# ImportError-only scan would miss the very instance this gate was built to find.
_IMPORT_CATCHING = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}

# dist name -> import name, for the cases where it is not a mechanical transform.
# Guarded by test_alias_map_burns_down: an alias for a dist we no longer declare must go.
_DIST_TO_MODULE = {
    "pyyaml": "yaml",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn",
    "python-docx": "docx",
    "llama-cpp-python": "llama_cpp",
    "python-multipart": "multipart",
}

# [all]-closure dists that are never imported anywhere under agent/. Each needs a REASON, and
# test_resolution_allowlist_burns_down deletes the entry the moment the module does get
# imported — so this cannot rot into the hand-list it replaces.
_NOT_IMPORTED_OK = {
    "bandit": "CLI only: invoked as `[sys.executable, '-m', 'bandit', ...]` via subprocess in "
              "layla/tools/impl/code.py security_scan(). Never imported, so it cannot flip an "
              "import path.",
    "python-multipart": "Imported by FastAPI internally (as `multipart`) to parse form data; "
                        "our code never imports it directly.",
    "requests": "FINDING (dead dep): declared in [core]+[cpu] and requirements.txt but not "
                "imported anywhere in live code — httpx is used instead. Removal is a separate "
                "change; recorded, not fixed here.",
    "orjson": "FINDING (dead dep): declared in [core]+[cpu] and requirements.txt but not "
              "imported anywhere in live code. Removal is a separate change.",
    "diskcache": "FINDING (dead dep): went dead when services/retrieval/retrieval_cache.py was "
                 "rewritten to a bounded OrderedDict LRU; only the stale build/lib/ copy still "
                 "imports it. Removal is a separate change.",
}


def _norm(dist: str) -> str:
    """PEP 503-ish normalisation: strip extras/markers/specifiers, lowercase, _ -> -."""
    base = re.split(r"[\[<>=!;~\s]", dist.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", base.strip().lower())


def _module_for(dist: str) -> str:
    return _DIST_TO_MODULE.get(dist, dist.replace("-", "_"))


def _read_extras() -> dict[str, list[str]]:
    assert PYPROJECT.is_file(), f"pyproject.toml not found at {PYPROJECT}"
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def _extra_to_dists() -> dict[str, set[str]]:
    """extra name -> {normalised dist}. `layla[a,b]` self-references are expanded."""
    extras = _read_extras()
    out: dict[str, set[str]] = {}
    for name, deps in extras.items():
        direct, refs = set(), []
        for d in deps:
            m = re.fullmatch(r"layla\[([^\]]+)\]", d.strip())
            if m:
                refs.extend(x.strip() for x in m.group(1).split(","))
            else:
                direct.add(_norm(d))
        out[name] = direct
        out.setdefault(f"__refs__{name}", set()).update(refs)
    # expand self-references (only [all] uses them today) to a fixed point
    for name in list(extras):
        seen, stack = set(), list(out.get(f"__refs__{name}", ()))
        while stack:
            r = stack.pop()
            if r in seen:
                continue
            seen.add(r)
            out[name] |= out.get(r, set())
            stack.extend(out.get(f"__refs__{r}", ()))
    return {k: v for k, v in out.items() if not k.startswith("__refs__")}


def _requirements_dists() -> set[str]:
    assert REQUIREMENTS.is_file(), f"requirements.txt not found at {REQUIREMENTS}"
    dists = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            dists.add(_norm(line))
    return dists


def _handler_catches_import_error(h: ast.ExceptHandler) -> bool:
    if h.type is None:
        return True  # bare except
    node = h.type
    names = [ast.unparse(e) for e in node.elts] if isinstance(node, ast.Tuple) else [ast.unparse(node)]
    return any(n.split(".")[-1] in _IMPORT_CATCHING for n in names)


def _handler_fails_closed(h: ast.ExceptHandler) -> bool:
    """True iff the handler propagates the IMPORT failure (dep absent => module unusable).

    Only the handler's last top-level statement counts, and only when it re-raises *the import
    error*: a bare `raise`, `raise <the name this handler bound>`, or `raise NewError(...)`.

    `raise <some other local>` is NOT failing closed. That distinction is load-bearing:
    services/infrastructure/retry_util.py catches ImportError for `tenacity`, runs a full stdlib
    retry loop, and ends `raise last` — re-raising the *wrapped callable's* error, not the
    import error. tenacity genuinely flips a path there; a naive "handler contains a raise"
    rule silently exempts it.
    """
    if not h.body:
        return False
    last = h.body[-1]
    if not isinstance(last, ast.Raise):
        return False
    if last.exc is None:
        return True
    if isinstance(last.exc, ast.Call):
        return True
    if isinstance(last.exc, ast.Name) and h.name and last.exc.id == h.name:
        return True
    return False


def _toplevel_imports(nodes) -> set[str]:
    mods: set[str] = set()
    for stmt in nodes:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Import):
                for a in n.names:
                    mods.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.add(n.module.split(".")[0])
    return mods


def _first_party() -> set[str]:
    """Top-level names importable from agent/ itself (`import services`, `import runtime_safety`),
    plus repo-root packages. Derived from the tree, not listed by hand."""
    names = {p.stem if p.is_file() else p.name
             for p in AGENT_DIR.iterdir()
             if (p.is_dir() and (p / "__init__.py").exists()) or p.suffix == ".py"}
    names |= {p.name for p in REPO_ROOT.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    return names


def _scan() -> tuple[set[str], dict[str, list[str]], int]:
    """-> (every module imported anywhere, path-flipping module -> ['file:line'], files scanned).

    A try-body is walked recursively, so a guarded block that also imports stdlib would credit
    e.g. `pathlib` as path-flipping. Stdlib and first-party names cannot be optional deps, so
    they are filtered out — via sys.stdlib_module_names and the tree, never a hand-written list.
    """
    ignore = set(sys.stdlib_module_names) | _first_party()
    all_imports: set[str] = set()
    flipping: dict[str, list[str]] = {}
    n_files = 0
    for path in sorted(AGENT_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        n_files += 1
        rel = path.relative_to(AGENT_DIR).as_posix()
        all_imports |= _toplevel_imports(tree.body)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                all_imports |= _toplevel_imports([node])
            if not isinstance(node, ast.Try):
                continue
            mods = _toplevel_imports(node.body)
            if not mods:
                continue
            for h in node.handlers:
                if not _handler_catches_import_error(h) or _handler_fails_closed(h):
                    continue
                for m in mods - ignore:
                    flipping.setdefault(m, []).append(f"{rel}:{node.lineno}")
    return all_imports, flipping, n_files


ALL_IMPORTS, FLIPPING, N_FILES = _scan()
EXTRAS = _extra_to_dists()
SHIPPED_DEFAULT = EXTRAS["all"]          # the default install surface
REQS = _requirements_dists()


def test_scanner_is_not_vacuous():
    """The gate's own teeth. If the scan silently finds nothing, every other test here passes
    trivially — which is precisely the failure mode this phase exists to kill."""
    assert N_FILES > 500, f"AST scan only reached {N_FILES} files; the walk is broken"
    assert len(ALL_IMPORTS) > 100, f"only {len(ALL_IMPORTS)} distinct imports found"
    assert len(FLIPPING) > 50, f"only {len(FLIPPING)} path-flipping modules found"
    # Known-true anchors: these are try/except-ImportError optional imports in live code.
    for mod in ("sentence_transformers", "chromadb", "keyring", "torch"):
        assert mod in FLIPPING, f"{mod} should be detected as path-flipping"
    # Known-false anchors: stdlib and first-party names are not optional deps and must never be
    # reported as path-flipping, however they appear inside a guarded try-body.
    assert "pathlib" not in FLIPPING
    assert "services" not in FLIPPING
    # The extras must actually have parsed.
    assert len(SHIPPED_DEFAULT) > 30, f"[all] closure only resolved {len(SHIPPED_DEFAULT)} dists"
    assert "sentence-transformers" in SHIPPED_DEFAULT, "[all] closure did not expand layla[core,...]"
    assert len(REQS) > 30, f"requirements.txt only parsed {len(REQS)} dists"


def test_ci_installed_dists_are_reachable_from_an_extra():
    """Direction A: everything CI installs must be obtainable via `pip install layla[<extra>]`."""
    declared: set[str] = set()
    for dists in EXTRAS.values():
        declared |= dists
    orphans = sorted(REQS - declared)
    assert not orphans, (
        "requirements.txt installs dists that are in NO pyproject extra, so CI tests code paths "
        "no `pip install layla[...]` can reproduce: " + ", ".join(orphans)
    )


def test_default_profile_path_flipping_dists_are_installed_by_ci():
    """Direction B: a dep every `layla[all]` user gets, whose absence silently flips a path,
    must be in requirements.txt — otherwise CI only ever tests the fallback branch."""
    violations = []
    for dist in sorted(SHIPPED_DEFAULT):
        if dist in REQS:
            continue
        mod = _module_for(dist)
        sites = FLIPPING.get(mod)
        if sites:
            violations.append(f"{dist} (import {mod}; flips at {', '.join(sites[:3])})")
    assert not violations, (
        "These dists are in the `layla[all]` default install surface and silently flip a code "
        "path when absent, but requirements.txt never installs them — so CI permanently tests "
        "the fallback branch while every user takes the other one:\n  " + "\n  ".join(violations)
    )


def test_shipped_dists_resolve_to_a_real_import():
    """Protects the alias map from rotting. If a dist's import name is guessed wrong, direction B
    silently skips it — the same silent-miss this gate exists to prevent. Every [all] dist must
    resolve to a module actually imported under agent/, or be allowlisted with a reason."""
    unresolved = []
    for dist in sorted(SHIPPED_DEFAULT):
        if dist in _NOT_IMPORTED_OK:
            continue
        mod = _module_for(dist)
        if mod not in ALL_IMPORTS:
            unresolved.append(f"{dist} -> guessed import {mod!r}, never imported under agent/")
    assert not unresolved, (
        "Cannot map these shipped dists to an import. Either the dist is unused (record it in "
        "_NOT_IMPORTED_OK with a reason) or _DIST_TO_MODULE needs the real import name — leaving "
        "it unresolved would make test_default_profile_path_flipping_dists_are_installed_by_ci "
        "silently skip it:\n  " + "\n  ".join(unresolved)
    )


def test_resolution_allowlist_burns_down():
    """Every _NOT_IMPORTED_OK entry must still be necessary and still be a shipped dist. The
    moment a dep is actually imported (or dropped), its exemption must go — an allowlist that
    outlives its reason is the hand-maintained list this gate replaced."""
    stale = []
    for dist, reason in _NOT_IMPORTED_OK.items():
        assert reason.strip(), f"{dist} allowlisted with no reason"
        if dist not in SHIPPED_DEFAULT:
            stale.append(f"{dist}: no longer in the [all] closure — drop the exemption")
        elif _module_for(dist) in ALL_IMPORTS:
            stale.append(f"{dist}: now imported under agent/ — exemption is obsolete, drop it")
    assert not stale, "Stale _NOT_IMPORTED_OK entries:\n  " + "\n  ".join(stale)


def test_alias_map_burns_down():
    """Every _DIST_TO_MODULE alias must still name a dist we actually declare."""
    declared: set[str] = set()
    for dists in EXTRAS.values():
        declared |= dists
    stale = sorted(d for d in _DIST_TO_MODULE if d not in declared)
    assert not stale, f"_DIST_TO_MODULE aliases a dist no extra declares: {stale}"
