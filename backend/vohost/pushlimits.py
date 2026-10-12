"""Push Limits mode: give one server (nearly) all machine resources.

Target = total RAM minus a small OS reserve (floored to whole GB) for BOTH
memory_min and memory_max (so the JVM takes it all upfront, no heap
resizing), plus all CPU cores (systemd quota = cores * 100%).
Previous limits are stashed so disabling restores them.
"""
import os

try:
    import psutil as _psutil
except Exception:
    _psutil = None


def machine() -> dict:
    """This machine's resources. Never raises."""
    try:
        total_b = _psutil.virtual_memory().total if _psutil else 0
    except Exception:
        total_b = 0
    if not total_b:
        total_b = 4 * 1024 ** 3
    try:
        # logical count: systemd CPUQuota 100% == one CPU, so full machine needs all of them
        cores = int(_psutil.cpu_count(logical=True) or 0) if _psutil else 0
    except Exception:
        cores = 0
    if not cores:
        try:
            cores = int(os.cpu_count() or 0)
        except Exception:
            cores = 0
    return {"ram_total_gb": max(1, int(total_b // 1024 ** 3)), "cores": max(1, cores)}


def target() -> dict:
    """Aggressive-but-safe allocation. Pure given machine()."""
    m = machine()
    reserve_gb = 1 if m["ram_total_gb"] >= 4 else 0
    alloc = max(1, m["ram_total_gb"] - reserve_gb)
    return {"memory": f"{alloc}G", "cores": m["cores"]}
