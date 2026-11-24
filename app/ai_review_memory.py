"""Conservative admission checks for optional visual QA on a shared Linux VPS."""
import os
from pathlib import Path

MIB = 1024 * 1024


class ReviewMemoryUnavailable(RuntimeError):
    """No paid request has been sent by the review pipeline."""


def _cgroup_dir(proc=Path("/proc/self/cgroup"), root=Path("/sys/fs/cgroup")):
    for line in proc.read_text().splitlines():
        if line.startswith("0::"):
            return root / line[3:].lstrip("/")
    raise ValueError("No cgroup v2")


def _pairs(path):
    return {line.split()[0]: int(line.split()[1])
            for line in path.read_text().splitlines() if len(line.split()) >= 2}


def _pressure(path):
    for line in path.read_text().splitlines():
        if line.startswith("full "):
            return float(dict(part.split("=") for part in line.split()[1:])["avg10"])
    raise ValueError("No memory PSI")


def check_review_memory(*, meminfo=Path("/proc/meminfo"), group=None):
    """Do not start optional QA if memory is already under pressure.

    The preflight is enabled explicitly by the small shared-host deployment.
    It does not allocate, reclaim or change memory settings. A failed check
    is not a cached paid failure: no request was sent.
    """
    if os.getenv("PROMO_LOW_MEMORY_QA") != "1":
        return
    reason = ("AI-сверка пропущена до платного запроса: недостаточно безопасного "
              "запаса памяти VPS. Плакаты сохранены, требуется ручная проверка.")
    try:
        if _pairs(meminfo)["MemAvailable:"] < 384 * 1024:
            raise ReviewMemoryUnavailable(reason)
        group = group if group is not None else _cgroup_dir()
        if _pressure(group / "memory.pressure") >= 10:
            raise ReviewMemoryUnavailable(reason)
        current = int((group / "memory.current").read_text().strip())
        # Inactive file pages can be reclaimed; anonymous/shmem pages cannot
        # be assumed reclaimable. Keep an explicit 192 MiB working reserve.
        stat = _pairs(group / "memory.stat")
        working = max(0, current - max(0, stat.get("inactive_file", 0)))
        for name in ("memory.high", "memory.max"):
            ceiling = (group / name).read_text().strip()
            if ceiling != "max" and int(ceiling) - working < 192 * MIB:
                raise ReviewMemoryUnavailable(reason)
    except ReviewMemoryUnavailable:
        raise
    except (OSError, ValueError, KeyError, IndexError):
        # On the explicitly memory-constrained host, fail closed if telemetry
        # cannot be read. Do not charge for an unsafe optional operation.
        raise ReviewMemoryUnavailable(
            "AI-сверка пропущена: не удалось проверить запас памяти VPS. "
            "Платный запрос не отправлялся; плакаты сохранены.")
