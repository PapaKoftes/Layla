# Geometry module — Second sweep

**Area:** `agent/layla/geometry/`  
**Status:** Done  
**Template:** [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md)

---

## 1. Scope and entry points

| Kind | Location |
|------|----------|
| Schema | `schema.py` — Pydantic v1 `GeometryProgram`, discriminated `GeometryOp` |
| Execution | `executor.py` — `execute_program()`, `list_framework_status()` |
| Backends | `backends/` — ezdxf, cadquery (subprocess), OpenSCAD CLI, trimesh |
| HTTP bridge | `bridges/http_cad_bridge.py` — `fetch_program()` for operator-hosted CAD sequence services |
| Tools | `layla/tools/registry.py` — `geometry_validate_program`, `geometry_execute_program` (approval), `geometry_list_frameworks` |

**Out of scope:** Full CAD kernel parity with commercial packages; optional deps (cadquery, trimesh, OpenSCAD) are best-effort when installed.

---

## 2. Data flow

1. User or LLM produces JSON matching `GeometryProgram` → `parse_program()` / `validate_program_dict()`.
2. `execute_program(program, workspace_root, output_basename, cfg)` loads config via `runtime_safety.load_config()` if `cfg` omitted.
3. **Sandbox:** `sandbox_root` from config (default `Path.home()`); `workspace_root` and `output_dir` must resolve **inside** `sandbox_root`.
4. Ops dispatch to the first backend that `supports(op)`; `cad_bridge_fetch` calls `fetch_program()`, parses nested program, recurses with `MAX_BRIDGE_DEPTH = 3`.

See [ARCHITECTURE.md](../ARCHITECTURE.md) capability / file ecosystem rows; North Star §4–§5 in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

---

## 3. Safety and invariants

| Invariant | Mechanism |
|-----------|-----------|
| Writes only under sandbox | `_inside_sandbox()` using `Path.relative_to()`; workspace and `output_basename` output dir checked |
| Bridge SSRF / open redirect | `http_cad_bridge._allowed_url()`: same scheme (http/https), **same netloc** as base, path must stay under base URL (blocks absolute `http(s)://other-host/...` passed as `path` after `urljoin`); optional `geometry_external_bridge_allow_insecure_localhost` for `127.0.0.1` / `localhost` / `::1` |
| Bridge recursion | `MAX_BRIDGE_DEPTH`; exceeded steps record error, no infinite nesting |
| Dangerous tools | `geometry_execute_program` gated by approval + `allow_run`-style policy in registry (see tools table) |

**Config keys (see `runtime_config.example.json`):** `sandbox_root`, `geometry_frameworks_enabled`, `openscad_executable`, `geometry_subprocess_timeout_seconds`, `geometry_external_bridge_url`, `geometry_external_bridge_allow_insecure_localhost`.

---

## 4. Failure modes and logging

| Failure | Behavior |
|---------|----------|
| Workspace outside sandbox | `{"ok": False, "error": "workspace_root must be inside sandbox_root"}` |
| Output path escapes | `error: "output path escapes sandbox"` |
| Missing optional backend | Step `ok: False`, message from backend (e.g. import error truncated) |
| Bridge: URL not allowlisted | No HTTP request; `error: "URL not under allowlisted base"` |
| Bridge: HTTP / JSON errors | Structured error string; no partial write |
| `cad_bridge_fetch` parse error | Step records exception message |

Geometry paths use the shared `layla` logger in backends where applicable; executor returns structured dicts for tool/UI consumption.

---

## 5. Tests and verification

| Test file | Covers |
|-----------|--------|
| `agent/tests/test_geometry_schema.py` | Schema validation |
| `agent/tests/test_geometry_executor.py` | Happy path (ezdxf when installed), `list_framework_status` |
| `agent/tests/test_geometry_bridge_security.py` | Bridge allowlist / localhost policy **without** network; sandbox rejection **without** CAD deps |

Run: `cd agent && pytest tests/test_geometry_*.py -q`

---

## 6. Open risks / follow-ups

- **Dependency drift:** cadquery / OpenSCAD / trimesh versions vary; `list_framework_status` is operator-facing probe only.
- **Bridge trust:** Same-netloc rule assumes the operator controls the bridge host; TLS for remote bridges is recommended.
- **Nested bridge programs:** Malicious nested programs are still constrained by sandbox + depth; content policy is operator responsibility.
