"""Host resource metrics for the dashboard (Section 21: CPU and memory information)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import psutil


class SystemMetrics:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._proc = psutil.Process(os.getpid())
        # Prime the CPU counters so the first non-blocking read is meaningful.
        psutil.cpu_percent(interval=None)
        self._proc.cpu_percent(interval=None)

    def snapshot(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self._data_dir))
        with self._proc.oneshot():
            rss = self._proc.memory_info().rss
            proc_cpu = self._proc.cpu_percent(interval=None)
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(logical=True) or 1,
            "memory_total_bytes": vm.total,
            "memory_used_bytes": vm.total - vm.available,
            "memory_percent": vm.percent,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "disk_percent": disk.percent,
            "service_rss_bytes": rss,
            "service_cpu_percent": proc_cpu,
            "uptime_s": round(time.time() - psutil.boot_time()),
        }
