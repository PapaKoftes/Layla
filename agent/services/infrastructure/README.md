# `infrastructure/` — cross-cutting service seam

This package is a **catch-all** for cross-cutting services that don't belong to a
focused, single-purpose package. It is a deliberate seam, not a cohesive module: if
a helper is used across the agent runtime but has no obvious home elsewhere, it tends
to land here. Roughly 70 modules currently live in this directory.

Because it is a catch-all, treat this README as a rough map rather than a contract.
When a cluster of related files grows large enough to stand on its own, prefer
promoting it into a dedicated package over adding more here.

Main sub-areas observed among the current files:

- **Agent-loop plumbing** — `agent_hooks.py`, `agent_loop_formatting.py`,
  `agent_task_runner.py`, `pre_loop_setup.py`, `route_helpers.py`, `session_context.py`,
  `task_context.py`, `task_budget.py`.
- **Background jobs & workers** — `background_job_worker.py`, `background_subprocess.py`,
  `background_intelligence.py`, `worker_pool.py`, `worker_cgroup_linux.py`,
  `worker_os_limits.py`, `ws_manager.py`.
- **Self-improvement / learning** — `auto_tune.py`, `autonomy_optimizer.py`,
  `experience_replay.py`, `rl_feedback.py`, `self_improvement.py`, `reflection_engine.py`,
  `initiative_engine.py`, `outcome_evaluation.py`, `outcome_metrics.py`, `reasoning_*.py`.
- **Health, recovery & diagnostics** — `crash_handler.py`, `degraded.py`,
  `dependency_recovery.py`, `failure_recovery.py`, `system_doctor.py`, `provider_health.py`,
  `resource_governor.py`, `resource_manager.py`, `retry_util.py`, `hardware_detect.py`.
- **Setup, config & updates** — `setup_engine.py`, `config_cache.py`, `config_migrator.py`,
  `auto_updater.py`, `release_updater.py`, `db_backup.py`, `data_paths.py`, `data_importers.py`.
- **Networking, remote & sync** — `mcp_client.py`, `mcp_server.py`, `tailscale_manager.py`,
  `tunnel_manager.py`, `syncthing_sync.py`, `obsidian_sync.py`, `remote_rate_limit.py`,
  `browser.py`, `shell_sessions.py`.
- **Voice, I/O & localization** — `stt.py`, `tts.py`, `german_mode.py`, `language_tutor.py`,
  `output_polish.py`, `output_quality.py`, `system_tray.py`.
