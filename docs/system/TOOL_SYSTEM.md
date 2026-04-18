# Tool system (as implemented)

Sources: [`agent/layla/tools/registry.py`](../../agent/layla/tools/registry.py), [`agent/layla/tools/domains/*.py`](../../agent/layla/tools/domains/), [`agent/runtime_safety.py`](../../agent/runtime_safety.py), [`agent/tests/test_registered_tools_count.py`](../../agent/tests/test_registered_tools_count.py).

## Registry assembly

- **`TOOLS`** is built by **`_build_tools_from_domains`** merging domain dicts **`FILE_TOOLS`**, **`GIT_TOOLS`**, … **`GEOMETRY_TOOLS`** ([`registry.py`](../../agent/layla/tools/registry.py)).
- Each entry: **`fn`** from **`registry_body`** / **`impl`** modules, metadata keys including **`category`**, **`risk_level`**, optional **`require_approval`**.

## Validation at startup

- **`validate_tools_registry()`** requires **`len(TOOLS) >= TOOL_COUNT_THRESHOLD`** where **`TOOL_COUNT_THRESHOLD = 50`** ([`registry.py`](../../agent/layla/tools/registry.py)). Failure raises **`RuntimeError`**; [`main.py`](../../agent/main.py) logs a warning if validation fails.

## Distinct count invariant (tests)

- **`EXPECTED_TOOL_COUNT`** in [`test_registered_tools_count.py`](../../agent/tests/test_registered_tools_count.py) asserts exact **`len(registry.TOOLS)`** (currently **195**). This is **separate** from the **50** minimum registry integrity check.

## SAFE vs DANGEROUS (runtime_safety)

- **`SAFE_TOOLS`**, **`DANGEROUS_TOOLS`** lists in [`runtime_safety.py`](../../agent/runtime_safety.py) drive **`is_tool_allowed`** semantics for approval file vs admin bypass.

## Tier-0 autonomous allowlist

- Default tools in [`agent/autonomous/policy.py`](../../agent/autonomous/policy.py) **`_DEFAULT_TIER0`**; override via config **`autonomous_tool_allowlist`**.
