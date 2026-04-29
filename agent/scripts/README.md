# Layla Codebase Health — Check Scripts

A comprehensive static analysis and validation system for the Layla agent codebase.
Run before every commit and as part of CI to catch bugs early with confidence scoring.

## Quick Start

```bash
cd agent/
python scripts/run_all_checks.py
```

Exit code: `0` = all green (or warnings only), `1` = hard failures detected.

## Scripts

| Script | Severity | What it checks |
|---|---|---|
| `check_patterns.py` | FAIL | Known bug patterns (mutable defaults, bare except, etc.) |
| `check_config.py` | WARN | Config key validity and type correctness |
| `check_imports.py` | FAIL | All Python imports resolve (no broken/missing modules) |
| `check_security.py` | WARN | Security anti-patterns (secrets, injection, path traversal) |
| `check_api_contracts.py` | WARN | Every HTTP route has ≥1 test + docstring + is registered |
| `check_db_schema.py` | WARN | DB schema idempotency, SQL injection via f-strings |
| `check_ui_symbols.py` | WARN | All onclick/onchange handler targets are defined in JS |
| `run_all_checks.py` | — | Orchestrator: runs all + pytest, produces confidence score |

## Confidence Score

```
confidence = (passing_checks / total_checks) × 100
```

A JSON report is written to `scripts/last_report.json` after each run.

## Individual Scripts

### check_patterns.py — Bug patterns

Detects known production bug patterns using AST-free regex analysis:

- **PAT-01** Mutable default arguments (`def f(x=[])`)
- **PAT-02** Bare `except:` clauses (swallows all errors)
- **PAT-03** `assert` in production code (stripped by `-O`)
- **PAT-04** Unguarded `eval()` / `exec()`
- **PAT-05** `time.sleep()` in async functions
- **PAT-06** `print()` statements left in production code
- **PAT-07** Wildcard imports (`from x import *`)
- **PAT-08** Comparing to `None` with `==` instead of `is`
- **PAT-09** `except Exception as e: pass` (silent failure)

### check_security.py — Security anti-patterns

- **SEC-01** Hardcoded secrets (password/secret/api_key in source)
- **SEC-02** Shell injection risk (`subprocess` with `shell=True`)
- **SEC-03** SQL injection via f-strings (`f"SELECT ... {var}"`)
- **SEC-04** Path traversal (`open(f"...{user_input}"`)
- **SEC-05** Dynamic SQL column construction
- **SEC-06** Unsafe `eval()` / `exec()` / `compile()`
- **SEC-07** Unsafe pickle load (`pickle.loads` / `pickle.load`)
- **SEC-08** Debug mode in production (`DEBUG=True`, `debug=True`)
- **SEC-09** Sensitive data in logs (passwords, keys in logger calls)
- **SEC-10** CORS wildcard (`allow_origins=["*"]`)

### check_imports.py — Import resolution

Validates all top-level imports in the agent package resolve via
`importlib.util.find_spec()`. Optional packages (AI libraries, CAD tools, etc.)
are whitelisted and reported as informational, not failures.

### check_api_contracts.py — API coverage

1. Scans `routers/*.py` for `@router.{get,post,...}` decorators → route list
2. Scans `tests/*.py` for `client.get/post(...)` calls → test reference list
3. Reports uncovered routes as WARN (not FAIL — many routes are intentionally
   tested only via integration tests)
4. Reports unregistered router files (FAIL)
5. Reports routes missing docstrings (info)

### check_db_schema.py — Database safety

- **DB-01** All `CREATE TABLE` statements use `IF NOT EXISTS`
- **DB-02** No raw f-string SQL with user-controlled variables
- **DB-03** SQLite files are readable
- **DB-04** Schema migration order is consistent

### check_ui_symbols.py — UI symbol resolution

Parses all `onclick="..."` and `onchange="..."` attributes in HTML,
extracts called function names, and verifies each is defined in:
- `ui/js/*.js` files
- Inline `<script>` blocks in `*.html` files

Skips built-in browser globals (document, window, fetch, Promise, etc.)

## Configuration

Checks respect these `config.json` keys:

```json
{
  "check_patterns_enabled": true,
  "check_security_enabled": true,
  "check_imports_skip_dirs": ["fabrication_assist", "tests"],
  "check_api_contracts_skip_routes": ["/health", "/metrics"]
}
```

## Adding a New Check

1. Create `scripts/check_YOURNAME.py`
2. Implement `run() -> int` returning `0` (pass) or `1` (fail)
3. Print issues to stdout as `ISSUE: description`
4. Add to `CHECKS` list in `run_all_checks.py`:
   ```python
   ("My check", SCRIPTS_DIR / "check_YOURNAME.py", "WARN"),  # or "FAIL"
   ```

## CI Integration

```yaml
# .github/workflows/health.yml
- name: Codebase health check
  run: |
    cd agent
    python scripts/run_all_checks.py --json > scripts/last_report.json
  continue-on-error: false
```
