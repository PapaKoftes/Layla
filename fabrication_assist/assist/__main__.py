"""CLI: `python -m fabrication_assist.assist` — does not start FastAPI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from fabrication_assist.assist.errors import (
    AssistError,
    InputValidationError,
    RunnerError,
    SchemaValidationError,
    SessionIOError,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _setup_logging(verbose: bool, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _exit_code(exc: BaseException) -> int:
    if isinstance(exc, InputValidationError):
        return 2
    if isinstance(exc, RunnerError):
        return 3
    if isinstance(exc, SchemaValidationError):
        return 4
    if isinstance(exc, SessionIOError):
        return 5
    if isinstance(exc, AssistError):
        return 3
    return 3


def main() -> int:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    parser = argparse.ArgumentParser(description="Fabrication assist (lite)")
    parser.add_argument(
        "message",
        nargs="*",
        help="User message (or omit and read stdin)",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Session JSON path (default: fabrication_assist/.assist_sessions/default.json)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result on stdout")
    parser.add_argument("--dry-run", action="store_true", help="Intent + variants only; no kernel; no session write")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Same as --dry-run (human-readable plan)",
    )
    parser.add_argument(
        "--runner",
        choices=("stub", "subprocess"),
        default="stub",
        help="stub (default) or subprocess echo kernel",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="INFO logs")
    parser.add_argument("--debug", action="store_true", help="DEBUG logs (includes subprocess details)")
    args = parser.parse_args()

    _setup_logging(args.verbose, args.debug)

    if args.message:
        text = " ".join(args.message).strip()
    else:
        text = sys.stdin.read().strip()
    if not text:
        print('Usage: python -m fabrication_assist.assist "your design question"', file=sys.stderr)
        return 1

    dry_run = bool(args.dry_run or args.explain)

    from fabrication_assist.assist.layla_lite import assist
    from fabrication_assist.assist.runner import StubRunner, SubprocessJsonRunner

    runner: Any = None
    if not dry_run:
        runner = SubprocessJsonRunner() if args.runner == "subprocess" else StubRunner()

    try:
        out = assist(
            text,
            session_path=args.session,
            runner=runner,
            dry_run=dry_run,
        )
    except (InputValidationError, RunnerError, SchemaValidationError, SessionIOError) as e:
        print(str(e), file=sys.stderr)
        if args.json:
            err_payload: dict[str, Any] = {
                "ok": False,
                "error": str(e),
                "kind": getattr(e, "kind", "assist"),
                "variant_id": getattr(e, "variant_id", None),
                "details": getattr(e, "details", {}),
            }
            print(json.dumps(err_payload, indent=2))
        return _exit_code(e)
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "error": str(e), "kind": "unexpected"}, indent=2))
        return 3

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        sys.stdout.write(out["markdown"])
        if not out["markdown"].endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
