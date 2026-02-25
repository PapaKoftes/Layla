# DevOps lens — principles

**Maintenance and operations.** DevOps emphasizes reliability, observability, and sustainable operation. Principles:

- **Automate the path to production.** Build, test, and deploy via repeatable pipelines. Manual steps drift and break.
- **Fail fast and visibly.** Errors should surface immediately and clearly. Hiding failure delays repair and compounds cost.
- **Idempotency and convergence.** Operations that can be run repeatedly without corrupting state are safer and easier to reason about.
- **Observability over hope.** Logs, metrics, and traces answer “what is happening?” and “what happened?” Design for being observed.
- **Document runbooks.** When things break at 3 a.m., written procedures beat tribal knowledge. Keep them next to the system they describe.
- **Dependencies and upgrades.** Track dependencies explicitly. Plan for upgrades; unmaintained stacks become liabilities.

**Will future-us resent this?** The DevOps lens asks whether the system is operable, maintainable, and documented—not just working today.
