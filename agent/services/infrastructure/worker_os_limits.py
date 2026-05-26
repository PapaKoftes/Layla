"""
Best-effort OS limits for background_job_worker (subprocess mode).

POSIX: RLIMIT_AS / optional RLIMIT_CPU before llama_cpp import — mmap may ignore AS; prefer cgroups/containers.
Windows: optional Job Object memory cap + optional CPU hard cap (ctypes, no pywin32 required).
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger("layla")

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JobObjectCpuRateControlInformation = 13
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004


def apply_background_worker_posix_rlimits(cfg: dict[str, Any]) -> None:
    """Apply RLIMIT_AS and optional RLIMIT_CPU in the worker before loading llama_cpp. Linux/macOS only."""
    if os.name == "nt":
        return
    try:
        import resource
    except ImportError:
        return

    if bool(cfg.get("background_worker_rlimits_enabled")):
        raw = cfg.get("background_worker_rlimit_as_bytes")
        try:
            limit = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            limit = 0
        if limit > 0:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
                logger.info(
                    "background worker: set RLIMIT_AS to %s bytes (best-effort; mmap may not respect cap)",
                    limit,
                )
            except (OSError, ValueError) as e:
                logger.warning("background worker: could not set RLIMIT_AS: %s", e)
        else:
            logger.warning(
                "background_worker_rlimits_enabled=true but background_worker_rlimit_as_bytes invalid or <= 0; skipping AS"
            )

    cpu_raw = cfg.get("background_worker_rlimit_cpu_seconds")
    try:
        cpu_soft = int(cpu_raw) if cpu_raw is not None else 0
    except (TypeError, ValueError):
        cpu_soft = 0
    if cpu_soft > 0:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_soft + 1))
            logger.info("background worker: set RLIMIT_CPU soft=%s (best-effort)", cpu_soft)
        except (OSError, ValueError) as e:
            logger.warning("background worker: could not set RLIMIT_CPU: %s", e)


def attach_windows_job_memory_limit(proc: subprocess.Popen[Any], cfg: dict[str, Any]) -> None:
    """
    Assign worker to a Job Object: optional JobMemoryLimit + optional CPU hard cap (Windows only).
    Kept name attach_windows_job_memory_limit for call-site compatibility.
    """
    if os.name != "nt":
        return
    if not bool(cfg.get("background_worker_windows_job_limits_enabled")):
        return
    raw_mb = cfg.get("background_worker_windows_job_memory_mb")
    try:
        mb = int(raw_mb) if raw_mb is not None else 0
    except (TypeError, ValueError):
        mb = 0
    raw_cpu = cfg.get("background_worker_windows_job_cpu_percent")
    try:
        cpu_pct = int(raw_cpu) if raw_cpu is not None else 0
    except (TypeError, ValueError):
        cpu_pct = 0
    if mb <= 0 and not (0 < cpu_pct <= 100):
        logger.warning(
            "background_worker_windows_job_limits_enabled=true but set memory_mb and/or cpu_percent (1-100)"
        )
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", wintypes.ULARGE_INTEGER),
                ("WriteOperationCount", wintypes.ULARGE_INTEGER),
                ("OtherOperationCount", wintypes.ULARGE_INTEGER),
                ("ReadTransferCount", wintypes.ULARGE_INTEGER),
                ("WriteTransferCount", wintypes.ULARGE_INTEGER),
                ("OtherTransferCount", wintypes.ULARGE_INTEGER),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("ControlFlags", wintypes.DWORD),
                ("Rate", wintypes.DWORD),
            ]

        CreateJobObjectW = kernel32.CreateJobObjectW
        CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        CreateJobObjectW.restype = wintypes.HANDLE

        SetInformationJobObject = kernel32.SetInformationJobObject
        SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        SetInformationJobObject.restype = wintypes.BOOL

        AssignProcessToJobObject = kernel32.AssignProcessToJobObject
        AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        AssignProcessToJobObject.restype = wintypes.BOOL

        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [wintypes.HANDLE]
        CloseHandle.restype = wintypes.BOOL

        phandle = getattr(proc, "_handle", None)
        if phandle is None:
            logger.warning("background worker: no process handle for Job Object")
            return

        job = CreateJobObjectW(None, None)
        if not job:
            logger.warning("background worker: CreateJobObjectW failed: %s", ctypes.get_last_error())
            return

        if mb > 0:
            memory_bytes = mb * 1024 * 1024
            ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            ext.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_JOB_MEMORY
            ext.JobMemoryLimit = memory_bytes
            ok = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(ext),
                ctypes.sizeof(ext),
            )
            if not ok:
                err = ctypes.get_last_error()
                CloseHandle(job)
                logger.warning("background worker: SetInformationJobObject memory failed: %s", err)
                return
            logger.info(
                "background worker: Job JobMemoryLimit=%s bytes (%s MiB)",
                memory_bytes,
                mb,
            )

        if 0 < cpu_pct <= 100:
            cpuinfo = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
            cpuinfo.ControlFlags = JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
            cpuinfo.Rate = wintypes.DWORD(cpu_pct * 100)
            okc = SetInformationJobObject(
                job,
                JobObjectCpuRateControlInformation,
                ctypes.byref(cpuinfo),
                ctypes.sizeof(cpuinfo),
            )
            if not okc:
                err = ctypes.get_last_error()
                CloseHandle(job)
                logger.warning("background worker: SetInformationJobObject CPU failed: %s", err)
                return
            logger.info("background worker: Job CPU hard cap ~%s%%", cpu_pct)

        ok2 = AssignProcessToJobObject(job, phandle)
        if not ok2:
            err = ctypes.get_last_error()
            CloseHandle(job)
            logger.warning("background worker: AssignProcessToJobObject failed: %s", err)
            return
        CloseHandle(job)
    except Exception as e:
        logger.warning("background worker: Windows Job Object setup failed: %s", e)
