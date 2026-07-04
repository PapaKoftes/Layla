"""Backward compatibility + subprocess entrypoint.

Implementation moved to services/infrastructure/background_job_worker.py, but this root file
is STILL the subprocess entrypoint: services.infrastructure.background_subprocess runs it as
`python background_job_worker.py` (WORKER_SCRIPT). It must therefore delegate __main__ to the
real worker's main() — a pure `import *` shim would import the module and exit WITHOUT running
the job (the opt-in `background_use_subprocess_workers` path silently did nothing before this).
"""
from services.infrastructure.background_job_worker import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys

    from services.infrastructure.background_job_worker import main

    sys.exit(main())
