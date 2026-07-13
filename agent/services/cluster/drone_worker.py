"""Drone Worker — executes tasks received from the QUEEN node.

On DRONE nodes, this module claims tasks from the local queue
(which were submitted via the cluster API) and executes them
using the local engine (LLM, embedder, ingestion pipeline, etc.).

Phase 3B of the distributed infrastructure plan.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable

logger = logging.getLogger("layla")


class DroneWorker:
    """Claims and executes tasks from the local task queue.

    Runs as a background thread, polling the queue for new tasks.
    Used by DRONE nodes to process work dispatched by the QUEEN.
    Can also run on QUEEN for local task processing.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._poll_interval = max(2, self._cfg.get("drone_poll_interval", 5))
        self._max_concurrent = max(1, self._cfg.get("drone_max_concurrent", 2))

        # Get our node ID
        try:
            from services.cluster.mdns_discovery import get_instance_id
            self._node_id = get_instance_id()
        except Exception:
            self._node_id = "local"

        # Task type → handler mapping
        self._handlers: dict[str, Callable] = {}
        self._register_default_handlers()

        # Threading
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active_tasks = 0
        self._active_lock = threading.Lock()

        # Stats
        self._tasks_completed = 0
        self._tasks_failed = 0

    # ── Handler registration ─────────────────────────────────────────

    def _register_default_handlers(self) -> None:
        """Register built-in task handlers."""
        self._handlers = {
            "inference": self._handle_inference,
            "embedding": self._handle_embedding,
            "ingestion": self._handle_ingestion,
            "study": self._handle_study,
            "backup": self._handle_backup,
            "consolidation": self._handle_consolidation,
            "wiki_build": self._handle_wiki_build,
        }

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a custom handler for a task type."""
        self._handlers[task_type] = handler

    # ── Worker lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start the worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._work_loop,
            name="drone-worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Drone worker started (poll=%ds, max_concurrent=%d)",
                     self._poll_interval, self._max_concurrent)

    def stop(self) -> None:
        """Stop the worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
            self._worker_thread = None
        logger.info("Drone worker stopped (completed=%d, failed=%d)",
                     self._tasks_completed, self._tasks_failed)

    def is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    # ── Main loop ────────────────────────────────────────────────────

    def _work_loop(self) -> None:
        """Poll for tasks and execute them."""
        _stuck_check_counter = 0
        while not self._stop_event.is_set():
            try:
                # Periodically reset stuck tasks (every ~10 iterations ≈ 50s at 5s poll)
                _stuck_check_counter += 1
                if _stuck_check_counter >= 10:
                    _stuck_check_counter = 0
                    try:
                        from services.cluster.work_unit import get_task_queue
                        get_task_queue().reset_stuck(300)
                    except Exception:
                        pass

                # Check capacity
                with self._active_lock:
                    if self._active_tasks >= self._max_concurrent:
                        self._stop_event.wait(self._poll_interval)
                        continue

                # Check governor — should we be doing work?
                if not self._should_work():
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Try to claim a task
                task = self._claim_task()
                if task is None:
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Execute in a sub-thread to allow concurrent tasks
                t = threading.Thread(
                    target=self._execute_task,
                    args=(task,),
                    name=f"task-{task.id[:8]}",
                    daemon=True,
                )
                with self._active_lock:
                    self._active_tasks += 1
                t.start()

            except Exception as e:
                logger.debug("Worker loop error: %s", e)
                self._stop_event.wait(self._poll_interval)

    def _should_work(self) -> bool:
        """Check if the resource governor allows background work."""
        try:
            from services.infrastructure.resource_governor import should_run_background
            return should_run_background(priority=1)
        except Exception:
            return True  # If no governor, always work

    def _claim_task(self):
        """Claim the next available task from the queue."""
        try:
            from services.cluster.work_unit import get_task_queue
            queue = get_task_queue()
            return queue.claim(self._node_id)
        except Exception as e:
            logger.debug("Task claim failed: %s", e)
            return None

    def _execute_task(self, task) -> None:
        """Execute a single task."""
        task_type = task.type.value if hasattr(task.type, "value") else str(task.type)
        handler = self._handlers.get(task_type)

        try:
            if handler is None:
                raise ValueError(f"No handler for task type: {task_type}")

            logger.info("Executing task %s (type=%s)", task.id[:8], task_type)
            result = handler(task.payload)

            # Mark done
            from services.cluster.work_unit import get_task_queue
            get_task_queue().complete(task.id, result)
            self._tasks_completed += 1
            logger.info("Task %s completed", task.id[:8])

        except Exception as e:
            logger.warning("Task %s failed: %s", task.id[:8], e)
            try:
                from services.cluster.work_unit import get_task_queue
                get_task_queue().fail(task.id, str(e))
            except Exception:
                pass
            self._tasks_failed += 1

        finally:
            with self._active_lock:
                self._active_tasks = max(0, self._active_tasks - 1)

    # ── Task handlers ────────────────────────────────────────────────

    def _handle_inference(self, payload: dict) -> dict:
        """Run an LLM completion."""
        prompt = payload.get("prompt", "")
        max_tokens = payload.get("max_tokens", 200)
        temperature = payload.get("temperature", 0.7)

        if not prompt:
            return {"error": "empty_prompt"}

        try:
            from services.llm.llm_gateway import run_completion
            result = run_completion(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            return {"output": result, "tokens": len(result.split()) if result else 0}
        except Exception as e:
            return {"error": str(e)}

    def _handle_embedding(self, payload: dict) -> dict:
        """Generate embeddings for text(s)."""
        texts = payload.get("texts", [])
        if isinstance(texts, str):
            texts = [texts]

        if not texts:
            return {"error": "no_texts"}

        try:
            from layla.memory.vector_store import _get_embedder
            embedder = _get_embedder()
            embeddings = embedder.encode(texts).tolist()
            return {"embeddings_count": len(embeddings), "dimensions": len(embeddings[0]) if embeddings else 0}
        except Exception as e:
            return {"error": str(e)}

    def _handle_ingestion(self, payload: dict) -> dict:
        """Process and ingest a document."""
        file_path = payload.get("file_path", "")
        if not file_path:
            return {"error": "no_file_path"}

        try:
            from layla.ingestion.pipeline import process_file
            result = process_file(file_path)
            return {"ingested": True, "chunks": result.get("chunks", 0) if isinstance(result, dict) else 0}
        except ImportError:
            return {"error": "ingestion_pipeline_not_available"}
        except Exception as e:
            return {"error": str(e)}

    def _handle_study(self, payload: dict) -> dict:
        """Execute a study/research task."""
        topic = payload.get("topic", "")
        if not topic:
            return {"error": "no_topic"}

        try:
            from services.llm.llm_gateway import run_completion
            prompt = f"Research and summarize the following topic concisely:\n\n{topic}"
            result = run_completion(prompt, max_tokens=500, temperature=0.5, stream=False)
            return {"summary": result}
        except Exception as e:
            return {"error": str(e)}

    def _handle_backup(self, payload: dict) -> dict:
        """Perform a database backup.

        Delegates to services.infrastructure.db_backup.backup_database so this
        producer of backups/layla_*.db yields the SAME consistent snapshot that
        verify_and_recover_db later restores from: a WAL checkpoint(TRUNCATE)
        followed by SQLite's online .backup() API. A plain shutil.copy2 of the
        live WAL-mode db file would omit uncheckpointed commits (and could copy
        pages mid-write), so a drone backup picked as the newest recovery source
        would silently restore stale-or-torn data.
        """
        try:
            from services.infrastructure.db_backup import backup_database

            result = backup_database()
            if not result.get("ok"):
                return {"error": result.get("reason") or result.get("error") or "backup_failed"}

            backup_path = result["backup_path"]
            from pathlib import Path
            return {
                "backup_path": backup_path,
                "size_bytes": Path(backup_path).stat().st_size,
            }
        except Exception as e:
            return {"error": str(e)}

    def _handle_consolidation(self, payload: dict) -> dict:
        """Run memory consolidation."""
        try:
            from layla.scheduler.jobs import _bg_memory
            _bg_memory()
            return {"consolidated": True}
        except Exception as e:
            return {"error": str(e)}

    def _handle_wiki_build(self, payload: dict) -> dict:
        """Build/update a wiki entry."""
        topic = payload.get("topic", "")
        if not topic:
            return {"error": "no_topic"}

        try:
            from autonomous.wiki import autonomous_wiki_entry
            result = autonomous_wiki_entry(topic)
            return {"wiki_entry": result if isinstance(result, str) else str(result)}
        except ImportError:
            return {"error": "wiki_module_not_available"}
        except Exception as e:
            return {"error": str(e)}

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        with self._active_lock:
            active = self._active_tasks
        return {
            "node_id": self._node_id,
            "running": self.is_running(),
            "active_tasks": active,
            "max_concurrent": self._max_concurrent,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "poll_interval": self._poll_interval,
        }


# ── Module-level singleton ───────────────────────────────────────────────

_worker: DroneWorker | None = None


def get_drone_worker(cfg: dict | None = None) -> DroneWorker:
    """Get or create the singleton DroneWorker."""
    global _worker
    if _worker is None:
        _worker = DroneWorker(cfg)
    return _worker


def start_drone_worker(cfg: dict | None = None) -> DroneWorker:
    """Get and start the drone worker."""
    worker = get_drone_worker(cfg)
    worker.start()
    return worker


def stop_drone_worker() -> None:
    """Stop the drone worker if running."""
    if _worker is not None:
        _worker.stop()


# ── QueenWorker ─────────────────────────────────────────────────────────────

class QueenWorker:
    """Executes queued tasks on the QUEEN node itself.

    The QUEEN dispatches tasks but also needs to run them locally when
    no DRONE nodes are available or when tasks are assigned to the local
    node.  Uses the same handler registry as DroneWorker.

    Only processes tasks when the governor mode is BREATHE or SPRINT
    (not WHISPER) to avoid impacting user interaction.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._poll_interval = max(2, self._cfg.get("queen_poll_interval", 8))
        self._max_concurrent = max(1, self._cfg.get("queen_max_concurrent", 2))

        # Get our node ID
        try:
            from services.cluster.mdns_discovery import get_instance_id
            self._node_id = get_instance_id()
        except Exception:
            self._node_id = "local"

        # Reuse the same handler set as DroneWorker
        self._handlers: dict[str, Callable] = {}
        self._register_default_handlers()

        # Threading
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active_tasks = 0
        self._active_lock = threading.Lock()

        # Stats
        self._tasks_completed = 0
        self._tasks_failed = 0

    def _register_default_handlers(self) -> None:
        """Register built-in task handlers (mirrors DroneWorker)."""
        # Create a temporary DroneWorker just to grab its handlers
        _dw = DroneWorker.__new__(DroneWorker)
        _dw._handlers = {}
        _dw._cfg = {}
        DroneWorker._register_default_handlers(_dw)
        self._handlers = _dw._handlers

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a custom handler for a task type."""
        self._handlers[task_type] = handler

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the queen worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._work_loop,
            name="queen-worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Queen worker started (poll=%ds, max_concurrent=%d)",
                     self._poll_interval, self._max_concurrent)

    def stop(self) -> None:
        """Stop the queen worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
            self._worker_thread = None
        logger.info("Queen worker stopped (completed=%d, failed=%d)",
                     self._tasks_completed, self._tasks_failed)

    def is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    # ── Main loop ────────────────────────────────────────────────────────

    def _work_loop(self) -> None:
        """Poll for tasks and execute them (QUEEN-side)."""
        while not self._stop_event.is_set():
            try:
                # Check capacity
                with self._active_lock:
                    if self._active_tasks >= self._max_concurrent:
                        self._stop_event.wait(self._poll_interval)
                        continue

                # Only work in BREATHE or SPRINT mode (not WHISPER)
                if not self._should_work():
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Try to claim a task (assigned to us or unassigned)
                task = self._claim_task()
                if task is None:
                    self._stop_event.wait(self._poll_interval)
                    continue

                # Execute in a sub-thread
                t = threading.Thread(
                    target=self._execute_task,
                    args=(task,),
                    name=f"qtask-{task.id[:8]}",
                    daemon=True,
                )
                with self._active_lock:
                    self._active_tasks += 1
                t.start()

            except Exception as e:
                logger.debug("Queen worker loop error: %s", e)
                self._stop_event.wait(self._poll_interval)

    def _should_work(self) -> bool:
        """Only run tasks when governor mode is BREATHE or SPRINT."""
        try:
            from services.infrastructure.resource_governor import ResourceMode, get_governor
            mode = get_governor().mode
            return mode in (ResourceMode.BREATHE, ResourceMode.SPRINT)
        except Exception:
            return True  # If no governor, allow work

    def _claim_task(self):
        """Claim a task assigned to us, or any unassigned pending task."""
        try:
            from services.cluster.work_unit import get_task_queue
            queue = get_task_queue()
            return queue.claim(self._node_id)
        except Exception as e:
            logger.debug("Queen task claim failed: %s", e)
            return None

    def _execute_task(self, task) -> None:
        """Execute a single task."""
        task_type = task.type.value if hasattr(task.type, "value") else str(task.type)
        handler = self._handlers.get(task_type)

        try:
            if handler is None:
                raise ValueError(f"No handler for task type: {task_type}")

            logger.info("Queen executing task %s (type=%s)", task.id[:8], task_type)
            result = handler(task.payload)

            from services.cluster.work_unit import get_task_queue
            get_task_queue().complete(task.id, result)
            self._tasks_completed += 1
            logger.info("Queen task %s completed", task.id[:8])

        except Exception as e:
            logger.warning("Queen task %s failed: %s", task.id[:8], e)
            try:
                from services.cluster.work_unit import get_task_queue
                get_task_queue().fail(task.id, str(e))
            except Exception:
                pass
            self._tasks_failed += 1

        finally:
            with self._active_lock:
                self._active_tasks = max(0, self._active_tasks - 1)

    def get_stats(self) -> dict[str, Any]:
        with self._active_lock:
            active = self._active_tasks
        return {
            "node_id": self._node_id,
            "running": self.is_running(),
            "active_tasks": active,
            "max_concurrent": self._max_concurrent,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "poll_interval": self._poll_interval,
        }


# ── Queen worker module-level singleton ──────────────────────────────────

_queen_worker: QueenWorker | None = None


def get_queen_worker(cfg: dict | None = None) -> QueenWorker:
    """Get or create the singleton QueenWorker."""
    global _queen_worker
    if _queen_worker is None:
        _queen_worker = QueenWorker(cfg)
    return _queen_worker


def start_queen_worker(cfg: dict | None = None) -> QueenWorker:
    """Get and start the queen worker."""
    worker = get_queen_worker(cfg)
    worker.start()
    return worker


def stop_queen_worker() -> None:
    """Stop the queen worker if running."""
    if _queen_worker is not None:
        _queen_worker.stop()
