# 13 -- Geometry, CAD/CAM & Domain-Specific Subsystem

> Design document for the geometry program execution engine, CAD backend
> abstraction, CAM heuristics, machining intermediate representation,
> external bridge integration, the standalone `fabrication_assist` package,
> and toolchain awareness services.

---

## 1. Geometry System

### 1.1 What It Does

The geometry subsystem lets Layla compose, validate, and execute sequences of
CAD-like operations expressed as JSON programs.  A `GeometryProgram` (v1) is an
ordered list of typed operations dispatched to pluggable backends.  The system
is intentionally _not_ a full parametric CAD kernel; it targets lightweight file
generation (DXF, STEP, STL) and mesh inspection rather than interactive
modeling.

### 1.2 GeometryProgram Schema

Defined in `agent/layla/geometry/schema.py`.

The root model:

```
GeometryProgram
  version: Literal["1"]
  ops: list[GeometryOp]        # discriminated union on `op` field
```

Supported operation types (the `GeometryOp` union):

| Op tag              | Pydantic model     | Backend    | Purpose                                   |
|---------------------|--------------------|------------|-------------------------------------------|
| `dxf_begin`         | `DxfBegin`         | ezdxf      | Start a new DXF document (units: mm/in)   |
| `dxf_line`          | `DxfLine`          | ezdxf      | Add a LINE entity                         |
| `dxf_circle`        | `DxfCircle`        | ezdxf      | Add a CIRCLE entity                       |
| `dxf_lwpolyline`    | `DxfLwPolyline`    | ezdxf      | Add an LWPOLYLINE (closed or open)        |
| `dxf_save`          | `DxfSave`          | ezdxf      | Save the accumulated DXF to disk          |
| `cq_box`            | `CqBox`            | cadquery   | Create an extruded box, export STEP/STL   |
| `openscad_render`   | `OpenScadRender`   | openscad   | Write .scad source, invoke CLI to render  |
| `mesh_info`         | `MeshInfo`         | trimesh    | Load mesh and return bbox + vertex count  |
| `cad_bridge_fetch`  | `CadBridgeFetch`   | HTTP       | POST to external bridge, get nested program |

Programs are parsed via `parse_program()` which uses a lazy `TypeAdapter` for
validation, and `validate_program_dict()` which returns a `(ok, message, prog)`
triple for non-throwing validation.

### 1.3 Executor

Defined in `agent/layla/geometry/executor.py`.

`execute_program()` iterates over ops, dispatches each to the first backend
whose `supports(op)` returns True, collects `StepResult` objects, and
aggregates them.

Key behaviors:

- **Sandbox enforcement**: `workspace_root` must resolve inside `sandbox_root`
  (from runtime config or `$HOME`).  Every output path is checked against the
  sandbox boundary via `_inside_sandbox()`.
- **Backend ordering**: `[EzdxfBackend, CadqueryBackend, OpenScadBackend,
  MeshBackend]` -- first match wins.
- **Bridge recursion**: `cad_bridge_fetch` ops are handled specially.  The
  executor fetches a program from the HTTP bridge, parses it, and recursively
  calls `execute_program()` with `_depth + 1`.  Maximum recursion depth is 3
  (`MAX_BRIDGE_DEPTH`).
- **Aggregate result**: `{ok, steps, artifacts, output_dir}`.  `ok` is False if
  any step failed.

`list_framework_status()` probes for installed Python modules (ezdxf, cadquery,
trimesh) and checks whether the OpenSCAD CLI binary is on PATH.  This is
exposed as the `geometry_list_frameworks` tool.

---

## 2. CAD Backends

### 2.1 Abstraction Layer

Defined in `agent/layla/geometry/backends/base.py`.

```
GeometryBackend (ABC)
  name: str
  supports(op: GeometryOp) -> bool
  execute(ctx: ExecutionContext, op: GeometryOp) -> StepResult

ExecutionContext (dataclass)
  sandbox_root, output_dir, cfg, dxf_doc, bridge_depth

StepResult (dataclass)
  ok: bool, message: str, artifacts: dict
```

Each backend checks `geometry_frameworks_enabled` in config before execution.
If disabled, it returns a StepResult with an explanatory message.

### 2.2 Backend Capability Matrix

| Backend   | File             | Ops handled            | Dependency      | Isolation  | Output formats |
|-----------|------------------|------------------------|-----------------|------------|----------------|
| ezdxf     | `ezdxf_backend.py`  | `dxf_begin`, `dxf_line`, `dxf_circle`, `dxf_lwpolyline`, `dxf_save` | `ezdxf` (pip) | in-process | .dxf |
| cadquery  | `cadquery_backend.py` | `cq_box`             | `cadquery` (pip) | subprocess | .step, .stl, .stp |
| openscad  | `openscad_backend.py` | `openscad_render`   | `openscad` CLI  | subprocess | .stl (any openscad output) |
| trimesh   | `mesh_backend.py`    | `mesh_info`          | `trimesh` (pip) | in-process | read-only (inspection) |

### 2.3 Per-Backend Details

**EzdxfBackend** -- The most mature backend.  Manages a DXF document lifecycle
across multiple ops via `ctx.dxf_doc` (mutable state on ExecutionContext).
`dxf_begin` creates a new R2010 document; subsequent ops add entities to its
modelspace; `dxf_save` writes and clears the reference.  Enforces that
`dxf_begin` must precede other DXF ops.

**CadqueryBackend** -- Runs CadQuery in a subprocess to isolate OpenCascade
crashes from the main process.  Generates a Python script as a string, executes
it via `subprocess.run([sys.executable, "-c", script])`.  Configurable timeout
via `geometry_subprocess_timeout_seconds` (default 120s).  Currently only
supports a single `cq_box` operation (extruded rectangular prism).  No
fillet, chamfer, union, or any other parametric operations.

**OpenScadBackend** -- Writes the provided `scad_source` to a temp file
(`_layla_temp.scad`) and invokes the OpenSCAD CLI (`-o output input`).  The
executable path is configurable via `openscad_executable` in config.  Same
configurable timeout.  Arbitrary OpenSCAD code is accepted but the backend
provides no validation of the SCAD source.

**MeshBackend** -- Read-only.  Loads a mesh file via `trimesh.load()` with
`force="scene"`, concatenates geometry if it is a Scene, and returns bounding
box and vertex count.  No mesh manipulation.

### 2.4 Common Path Resolution

All backends share a `_resolve()` helper that resolves `output_dir / rel_path`
and verifies it stays within `sandbox_root`.  Path-escape attempts return an
error string.

---

## 3. CAM System

Defined in `agent/layla/cam/`.

### 3.1 Architecture

The CAM subsystem consists of three small modules behind a facade
(`agent/layla/cam/__init__.py`).  It is explicitly **not production CAM** --
every output carries disclaimers.

### 3.2 Tool Library (`tool_library.py`)

A static dictionary of four tool types:

| Key             | Description                                    |
|-----------------|------------------------------------------------|
| `flat_endmill`  | General pocket/profile                         |
| `ball_endmill`  | 3D surfacing                                   |
| `vbit`          | Chamfer/engrave                                |
| `drill`         | Plunge-only                                    |

This is planning-level copy, not parametric tool definitions.  There is no tool
geometry (diameter, flute count, coating, etc.) and no tool-number registry.

### 3.3 Feeds & Speeds Calculator (`feeds_speeds.py`)

`lookup_sfm(material, tool_diameter_mm)` returns heuristic SFM ranges and
chipload values based on keyword matching of the material string:

| Material class   | SFM range (FPM) | Chipload formula                   |
|------------------|-----------------|-------------------------------------|
| non-ferrous (aluminum, 6061, 7075) | 200--450 | 0.02 + 0.01 * (d/6) |
| ferrous (steel, stainless, 4140)   | 80--200  | 0.015 + 0.005 * (d/6) |
| soft (wood, plywood, MDF, plastic) | 600--1200 | 0.05 + 0.02 * (d/6) |
| unknown (fallback)                 | 150--400 | 0.03 (fixed)          |

These are hobby-scale conservative values.  The code acknowledges they are not
machine-specific.

### 3.4 Simulator (`simulator.py`)

Two functions:

- `estimate_rough_time_minutes(path_length_mm, feed_mm_per_min)` -- trivial
  length / feed calculation.
- `simulate_gcode(gcode_text)` -- A minimal G-code path simulator that
  processes G0/G1/G2/G3 moves, tracks position, computes cut length vs. rapid
  length, bounding box, and estimated time.  Handles G20/G21 (inch/mm), G90/G91
  (absolute/incremental), arc center offsets (I/J).  Returns move count and a
  disclaimer.

Limitations: ignores acceleration/jerk, tool radius compensation, spindle
dynamics, modal planes beyond XY, helical moves, canned cycles, and cutter
compensation.  Rapids are estimated at 3x feed rate.

### 3.5 Machine Intent Builder (`__init__.py`)

`build_machine_intent()` bundles IR, G-code text, feeds/speeds, IR validation,
G-code validation, and G-code simulation into a single dict for handoff.  Every
bundle carries a `NOT_MACHINE_READY` disclaimer.

---

## 4. Machining IR

Defined in `agent/layla/geometry/machining_ir.py`.

### 4.1 Purpose

A deterministic intermediate representation that bridges DXF file understanding
and fabrication tool generation.  It extracts geometric features from DXF
files, orders them for toolpath planning, and generates coarse machine-step
previews.  No LLM or agent loop is involved.

### 4.2 Feature Extraction (`extract_features_from_dxf`)

Reads DXF modelspace entities and classifies them:

| DXF entity   | Feature type    | Extracted data                           |
|--------------|-----------------|------------------------------------------|
| CIRCLE       | `hole`          | center, radius, perimeter                |
| ARC          | `arc_segment`   | center, radius, start/end angle, length  |
| LINE         | `line_segment`  | start, end, length                       |
| LWPOLYLINE   | `contour` (if closed) / `open_path` | vertex count, perimeter, bbox |

Each feature gets a sequential ID (e.g., `hole_1`, `poly_3`).

### 4.3 Toolpath Ordering (`plan_toolpath_order`)

Deterministic ordering:
1. Holes -- ascending by radius
2. Contours -- descending by perimeter (largest first)
3. Remaining features -- sorted by ID string

Returns an ordered list of feature IDs.

### 4.4 Machine Steps Preview (`build_machine_steps_preview`)

Maps ordered features to coarse operation types:

| Feature type  | Machine op                   |
|---------------|------------------------------|
| hole          | `drill_or_pocket_circle`     |
| contour       | `profile_cut_2d`             |
| open_path     | `engrave_or_open_contour`    |
| line_segment  | `cut_segment`                |
| arc_segment   | `cut_arc`                    |
| other         | `review_geometry`            |

These are preview-level -- no depth, offset, or feed information.

### 4.5 IR Validation (`validate_machining_ir_dict`)

Structural checks only:
- Non-empty feature list
- Valid bounding boxes (non-inverted)
- Non-degenerate contours (>= 3 vertices)
- Non-empty machine steps when features exist

Returns `machine_readiness: "interpretive_preview"` or `"not_validated"`.

### 4.6 G-code Validation (`validate_gcode_text`)

Structural checks on G-code text:
- Whitelist of safe G-codes: {0,1,2,3,17,18,19,20,21,28,90,91}
- Whitelist of safe M-codes: {0,1,2,3,4,5,6,30}
- Checks for: units declaration, spindle on/off, feed word presence, motion
  commands, feed-before-first-cut
- Returns separate `errors` and `warnings` lists

This is explicitly not collision-checked or machine-safe certification.

---

## 5. HTTP CAD Bridge

Defined in `agent/layla/geometry/bridges/http_cad_bridge.py`.

### 5.1 Design

The bridge allows Layla to integrate with an operator-hosted external CAD
service.  When a `cad_bridge_fetch` op is encountered in a GeometryProgram, the
executor POSTs JSON to the configured URL and expects a GeometryProgram (or
`{program: {...}}`) in the response.  The returned program is then recursively
executed.

### 5.2 Configuration

| Config key                                    | Purpose                                     |
|-----------------------------------------------|---------------------------------------------|
| `geometry_external_bridge_url`                | Base URL for the bridge (required)          |
| `geometry_external_bridge_allow_insecure_localhost` | Allow HTTP to localhost (default: false) |

### 5.3 Security Controls

- **URL allowlisting**: `_allowed_url()` verifies the resolved URL shares the
  same scheme, netloc, and path prefix as the configured base URL.
- **Localhost blocking**: localhost/127.0.0.1/::1 are blocked unless
  `allow_insecure_localhost` is explicitly enabled.
- **Depth limiting**: The executor enforces `MAX_BRIDGE_DEPTH = 3` to prevent
  infinite recursion of bridge calls.
- **Schema validation**: The bridge response must parse as a valid
  `GeometryProgram`.

### 5.4 Implementation

Uses `urllib.request` (stdlib) for HTTP, not httpx.  The `gencad_generate_toolpath`
tool in `agent/layla/tools/impl/geometry.py` uses a _separate_ code path with
`httpx` to POST to the same bridge URL, but with a different payload structure
(`op`, `file`, `strategy`, `workspace_root`).  These two bridge integration
points are architecturally inconsistent:

- `http_cad_bridge.py` (schema ops) uses `urllib.request` and expects a
  GeometryProgram response.
- `gencad_generate_toolpath` (tool) uses `httpx` and expects an arbitrary
  JSON result.

---

## 6. `fabrication_assist` Package

### 6.1 Architectural Boundary

`fabrication_assist/` is a **separate top-level package** in the repo -- it is
not imported by the main agent on startup.  `pyproject.toml` lists both `agent`
and `fabrication_assist` as source roots.  Integration with the agent happens
through the `fabrication_assist_run` tool in `agent/layla/tools/impl/automation.py`,
which does a lazy `import` and delegates to the `assist()` function.

This separation is intentional: the fabrication assist layer is designed to run
standalone (CLI: `python -m fabrication_assist.assist "your question"`) or be
plugged into the agent loop on demand.

### 6.2 Components

| Module         | File                                  | Purpose                                   |
|----------------|---------------------------------------|-------------------------------------------|
| Orchestration  | `assist/layla_lite.py`                | `assist()` main entry, `parse_intent()`   |
| Schemas        | `assist/schemas.py`                   | Pydantic models for all data shapes       |
| Session        | `assist/session.py`                   | JSON session persistence (history, variants, outcomes) |
| Variants       | `assist/variants.py`                  | Heuristic variant proposal from intent    |
| Runner         | `assist/runner.py`                    | `BuildRunner` protocol + 3 implementations |
| Explain        | `assist/explain.py`                   | Markdown comparison table + best-pick summary |
| Echo kernel    | `assist/echo_kernel.py`               | Deterministic JSON-in/JSON-out test kernel |
| Errors         | `assist/errors.py`                    | Typed error hierarchy (5 classes)         |
| CLI            | `assist/__main__.py`                  | argparse CLI with exit codes 0-5          |

### 6.3 Execution Flow

```
User text
  -> parse_intent()           keyword-match to goal + strategies
  -> propose_variants()       3 variants (assembly, material, machining focus)
  -> for each variant:
       runner.run_build(cfg)  invoke deterministic kernel
  -> format_comparison_table() + summarize_best()
  -> save_session()           append to JSON session file
  -> return {intent, variants, results, markdown}
```

### 6.4 Runner Implementations

| Runner               | Use case          | Behavior                                    |
|----------------------|-------------------|---------------------------------------------|
| `StubRunner`         | Demos/tests       | SHA256-seeded deterministic scores           |
| `SubprocessJsonRunner` | Isolation       | Invokes `echo_kernel` in subprocess, validates stdout |
| `DXFBuildRunner`     | Real fabrication  | Converts `FabricationJob` to DXF via ezdxf  |

**DXFBuildRunner** is the only runner that produces real geometry output.  It
handles five operation types:

| Op type      | DXF output                              |
|--------------|-----------------------------------------|
| `cut_rect`   | Closed LWPOLYLINE rectangle             |
| `cut_circle` | CIRCLE entity                           |
| `cut_slot`   | Two parallel lines + two semicircle ARCs |
| `pocket`     | Closed LWPOLYLINE + HATCH fill          |
| `profile`    | Open LWPOLYLINE                         |

### 6.5 Session Model

`AssistSession` stores: `history` (timestamped entries), `variants` (latest
proposed set), `outcomes` (accumulated kernel results), `preferences` (operator
overrides).  Guard rails: max file size 4 MB, max JSON depth 32, max key count
50,000.  Atomic writes via temp-file-then-replace.

Important design invariant: **session data never drives execution**.  The
`_assert_session_metadata_only()` function documents (and the code path
enforces) that `propose_variants()` and `run_build()` receive only user-derived
intent, knowledge YAML, and the runner -- never session state.

### 6.6 Domain-Specific Context (PolyBoard / OptiNest / NcHops)

The operator's primary CAD/CAM toolchain (PolyBoard for cabinet design, OptiNest
for nesting/sheet optimization, NcHops for CNC post-processing) is referenced in
knowledge files and project memory but is not directly integrated in code.
There are no imports, API calls, or file format parsers for these tools.  They
exist as context for the LLM's reasoning about fabrication tasks.  The
`fabrication_assist` variant system uses generic YAML knowledge files that could
be populated with domain-specific data for these tools, but no such YAML files
ship in the repo.

---

## 7. Toolchain Awareness

### 7.1 `services/toolchain_awareness.py`

Provides a static weighted DAG representing the DXF-to-machine fabrication
pipeline:

```
dxf_parse (low/low)
  -> machining_ir_extract (low/med)
    -> toolpath_order (low/med)
      -> cam_feeds_offsets (high/high)
        -> gcode_post (med/high)
          -> machine_run (high/high)
```

Edge weights encode staged-dependency severity (higher = more costly to skip).

Functions:
- `toolchain_graph_summary()` -- returns nodes and edges as dicts
- `policy_hint_from_toolchain(goal)` -- returns `PolicyCaps` nudges (e.g.,
  require verification before mutation for fabrication goals)
- `toolchain_planning_hint()` -- generates a multi-line string for planning
  prompts

### 7.2 `services/toolchain_graph.py`

Complements `toolchain_awareness.py` with step-order cost suggestions for the
planner.  Defines ordered ideal chains for four domains:

| Route    | Chain                                                                  |
|----------|------------------------------------------------------------------------|
| CAM      | `geometry_extract_machining_ir -> generate_gcode -> validate_fabrication_bundle` |
| Code     | `read_file -> python_ast -> search_codebase -> apply_patch -> run_tests -> git_status -> git_diff` |
| Research | `ddg_search -> fetch_article -> summarize_text -> save_note`           |
| Docs     | `read_file -> understand_file -> write_file`                           |

`suggest_cheaper_path(steps_done)` warns when steps are executed out of order
(e.g., generating G-code without extracting machining IR first).

`deterministic_toolchain_route(goal)` classifies a goal string into a route
and returns the chain and allowed tool set.

### 7.3 Framework Detection (`list_framework_status`)

In `executor.py`, `list_framework_status()` probes at runtime:
- Python imports: ezdxf, cadquery, trimesh
- CLI: `shutil.which()` for the OpenSCAD executable
- Config: which frameworks are enabled in `geometry_frameworks_enabled`

This is exposed as the `geometry_list_frameworks` tool so the LLM can
introspect available capabilities before attempting geometry operations.

---

## 8. Tool Surface

The geometry and CAM subsystem exposes 11 tools to the agent:

| Tool name                       | Category     | Risk   | Approval | Source file      |
|---------------------------------|-------------|--------|----------|------------------|
| `geometry_validate_program`     | fabrication | low    | no       | `impl/geometry.py` |
| `geometry_execute_program`      | fabrication | medium | yes      | `impl/geometry.py` |
| `geometry_list_frameworks`      | fabrication | low    | no       | `impl/geometry.py` |
| `geometry_extract_machining_ir` | fabrication | low    | no       | `impl/geometry.py` |
| `validate_fabrication_bundle`   | fabrication | low    | no       | `impl/geometry.py` |
| `cam_feed_speed_hint`           | fabrication | low    | no       | `impl/geometry.py` |
| `cam_estimate_time`             | fabrication | low    | no       | `impl/geometry.py` |
| `cam_list_tool_types`           | fabrication | low    | no       | `impl/geometry.py` |
| `cam_build_machine_intent`      | fabrication | low    | no       | `impl/geometry.py` |
| `gencad_generate_toolpath`      | fabrication | medium | yes      | `impl/geometry.py` |
| `fabrication_assist_run`        | fabrication | medium | yes      | `impl/automation.py` |

All write-capable and external-calling tools require approval.  Read-only
inspection and validation tools do not.

---

## 9. Known Issues

### 9.1 Incomplete Backends

- **CadqueryBackend** supports only `cq_box`.  No fillet, chamfer, boolean,
  revolve, loft, or any parametric modeling operations.  For any non-trivial
  3D geometry, users must write OpenSCAD source or use the bridge.
- **MeshBackend** is read-only.  No mesh manipulation (boolean, remesh,
  slice, repair).
- **OpenScadBackend** accepts arbitrary SCAD source without validation.
  Malformed SCAD will fail at the CLI level with potentially unhelpful error
  messages.

### 9.2 Hardcoded Values

- `MAX_BRIDGE_DEPTH = 3` in executor.py -- not configurable.
- Tool library has exactly 4 tool types with no parametric data.
- Feeds/speeds are hobby-scale heuristics; no support for tool manufacturer
  data, machine-specific limits, or coolant modeling.
- G-code simulator assumes rapids at 3x feed -- arbitrary.
- DXF version is hardcoded to R2010 in both the ezdxf backend and
  DXFBuildRunner.

### 9.3 Architectural Inconsistencies

- Two separate HTTP bridge integration points use different HTTP libraries
  (`urllib.request` vs `httpx`) and different payload/response schemas.
- `gencad_generate_toolpath` sends `{op, file, strategy, workspace_root}` to
  the bridge, while `cad_bridge_fetch` sends arbitrary `body` dicts.  An
  operator implementing a bridge must support both contracts.
- The `assist()` function signature in `layla_lite.py` uses `user_text` as the
  first positional parameter, but the `fabrication_assist_run` tool calls it as
  `assist(objective=..., ...)` using a keyword argument named `objective`.
  This works because Python allows passing positional args by keyword, but it
  is a naming mismatch that could cause confusion.

### 9.4 Missing Capabilities

- No ARC or SPLINE ops in the GeometryProgram schema (only LWPOLYLINEs for
  curves).
- No 3D DXF support (all DXF ops are 2D, Z is ignored).
- No STEP/IGES import or conversion.
- No assembly modeling or constraints.
- No stock definition, fixture, or workholding modeling in the CAM layer.
- Toolpath ordering is purely geometric (hole radius, contour perimeter) with
  no consideration of tool changes, fixture access, or cut direction.
- G-code validation whitelists are incomplete (no G40-G44 cutter comp, no
  G54-G59 work coordinates, no G80-G89 canned cycles).
- No support for multi-setup or 4/5-axis operations.

### 9.5 Untested or Fragile Paths

- CadQuery subprocess isolation: if OCC crashes hard (SIGSEGV), the subprocess
  may not produce useful error output.
- OpenSCAD backend depends on the CLI being installed and on PATH, which is
  platform-specific and has no installer integration.
- Bridge recursion at depth 3 is untested in the main test suite beyond
  schema/executor unit tests.
- `fabrication_assist_run` does a lazy import of `fabrication_assist.assist` --
  import failure produces a generic error without guidance.

---

## 10. Stability Assessment

| Component                        | Status       | Rationale                                                |
|----------------------------------|--------------|----------------------------------------------------------|
| GeometryProgram schema           | **STABLE**   | Pydantic v1 schema, versioned, used in tests and tools   |
| Executor (dispatch + sandbox)    | **STABLE**   | Covered by test_geometry_executor.py, sandbox logic sound |
| EzdxfBackend                     | **STABLE**   | Feature-complete for 2D DXF; well-tested                 |
| CadqueryBackend                  | **INCOMPLETE** | Only `cq_box`; subprocess isolation works but coverage is minimal |
| OpenScadBackend                  | **FRAGILE**  | Depends on external CLI; no SCAD validation; platform-dependent |
| MeshBackend                      | **INCOMPLETE** | Read-only; does what it claims but offers no manipulation |
| HTTP CAD Bridge                  | **FRAGILE**  | Security controls present but bridge protocol is informal; two inconsistent integration points |
| Machining IR                     | **STABLE**   | Deterministic, well-structured, tested in toolchain CAM tests |
| G-code validator                 | **STABLE**   | Structural checks are sound; limited whitelist is by design |
| G-code simulator                 | **INCOMPLETE** | Handles G0-G3 and arcs; no canned cycles, cutter comp, or accel |
| Feeds/speeds calculator          | **STABLE**   | Deliberately conservative heuristics; works as intended  |
| Tool library                     | **INCOMPLETE** | Stub-level; 4 tool types with no parametric data         |
| Machine intent builder           | **STABLE**   | Simple aggregation; no logic to break                    |
| `fabrication_assist` orchestration | **STABLE** | Well-tested (7+ test files); clear error hierarchy       |
| DXFBuildRunner                   | **STABLE**   | Handles 5 op types correctly; tested                     |
| StubRunner / SubprocessJsonRunner | **STABLE**  | Deterministic and well-tested                            |
| Variant proposer                 | **STABLE**   | Heuristic but deterministic; tested                      |
| Session I/O                      | **STABLE**   | Guard rails on size/depth; atomic writes                 |
| Toolchain awareness              | **STABLE**   | Static DAG; pure functions; tested                       |
| Toolchain graph                  | **STABLE**   | Heuristic ordering; pure functions                       |

### Legend

- **STABLE** -- Works as designed, has test coverage, unlikely to break.
- **FRAGILE** -- Works but depends on external factors or has known weak spots.
- **INCOMPLETE** -- Partially implemented; functional within its narrow scope
  but missing expected capabilities.
- **DEAD** -- Not used or not reachable.  (None in this subsystem.)

---

## 11. Configuration Reference

All geometry/CAM configuration lives in `runtime_config.json`:

| Key                                           | Type         | Default      | Purpose                                           |
|-----------------------------------------------|-------------|--------------|---------------------------------------------------|
| `geometry_frameworks_enabled`                 | dict/list   | (all enabled) | Toggle backends: `{ezdxf: true, cadquery: true, ...}` |
| `openscad_executable`                         | string      | `"openscad"` | Path or name of OpenSCAD CLI binary               |
| `geometry_subprocess_timeout_seconds`         | number      | `120`        | Timeout for cadquery/openscad subprocess calls     |
| `geometry_external_bridge_url`                | string      | `""`         | Base URL for external CAD bridge                   |
| `geometry_external_bridge_allow_insecure_localhost` | bool  | `false`      | Allow HTTP bridge to localhost                     |
| `fabrication_assist.enable_subprocess`        | bool        | `false`      | Allow SubprocessJsonRunner in fabrication_assist    |
| `sandbox_root`                                | string      | `$HOME`      | Root directory for sandbox enforcement             |

---

## 12. Data Flow Diagram

```
                                    LLM / Agent Loop
                                         |
                            tool dispatch (geometry_*, cam_*, fabrication_assist_run)
                                         |
                     +-------------------+-------------------+
                     |                   |                   |
              GeometryProgram      CAM Heuristics    fabrication_assist
              (validate/execute)   (feeds, sim)      (variants, runner)
                     |                   |                   |
              +------+------+      lookup_sfm()       parse_intent()
              | Executor    |      simulate_gcode()   propose_variants()
              |  sandbox    |      list_tool_types()  runner.run_build()
              |  dispatch   |                              |
              +------+------+                         DXFBuildRunner
              |      |      |                         (ezdxf output)
         ezdxf  cadquery openscad
        backend  backend  backend
              |      |      |              HTTP CAD Bridge
         .dxf  .step/.stl .stl      <---  cad_bridge_fetch
                                          gencad_generate_toolpath
                                                  |
                                           Operator-hosted
                                            CAD service
```

```
          Machining IR Pipeline
          
  DXF file -> extract_features_from_dxf()
                    |
           [hole, contour, arc, line, open_path]
                    |
           plan_toolpath_order()
                    |
           [ordered feature IDs]
                    |
           build_machine_steps_preview()
                    |
           [drill, profile_cut, engrave, cut_segment, cut_arc]
                    |
           validate_machining_ir_dict()
                    |
           {ok, issues, machine_readiness}
```

---

## 13. Key File Index

| File | Purpose |
|------|---------|
| `agent/layla/geometry/__init__.py` | Package facade; exports core API |
| `agent/layla/geometry/schema.py` | GeometryProgram Pydantic schema |
| `agent/layla/geometry/executor.py` | Program executor with sandbox enforcement |
| `agent/layla/geometry/machining_ir.py` | DXF feature extraction + toolpath ordering + G-code validation |
| `agent/layla/geometry/backends/base.py` | Backend ABC + context/result dataclasses |
| `agent/layla/geometry/backends/ezdxf_backend.py` | 2D DXF generation |
| `agent/layla/geometry/backends/cadquery_backend.py` | 3D box via subprocess |
| `agent/layla/geometry/backends/openscad_backend.py` | OpenSCAD CLI rendering |
| `agent/layla/geometry/backends/mesh_backend.py` | Mesh inspection via trimesh |
| `agent/layla/geometry/bridges/http_cad_bridge.py` | External CAD bridge HTTP client |
| `agent/layla/cam/__init__.py` | CAM facade + machine intent builder |
| `agent/layla/cam/tool_library.py` | Static tool type catalog |
| `agent/layla/cam/feeds_speeds.py` | Hobby-scale feeds/speeds lookup |
| `agent/layla/cam/simulator.py` | G-code path simulator |
| `agent/layla/tools/impl/geometry.py` | Tool implementations for geometry + CAM |
| `agent/layla/tools/domains/geometry.py` | Tool metadata declarations |
| `agent/layla/tools/impl/automation.py` | `fabrication_assist_run` tool |
| `agent/services/toolchain_awareness.py` | Fabrication DAG + policy hints |
| `agent/services/toolchain_graph.py` | Toolchain ordering suggestions |
| `fabrication_assist/assist/layla_lite.py` | Standalone assist orchestration |
| `fabrication_assist/assist/runner.py` | BuildRunner implementations (Stub, Subprocess, DXF) |
| `fabrication_assist/assist/schemas.py` | Pydantic schemas for jobs, operations, results |
| `fabrication_assist/assist/session.py` | JSON session persistence |
| `fabrication_assist/assist/variants.py` | Heuristic variant proposal |
| `fabrication_assist/assist/explain.py` | Markdown comparison output |
| `fabrication_assist/assist/echo_kernel.py` | Test kernel for subprocess runner |
| `fabrication_assist/assist/errors.py` | Typed error hierarchy |
| `fabrication_assist/assist/__main__.py` | CLI entry point |
