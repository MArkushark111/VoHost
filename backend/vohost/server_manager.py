"""Server process control via systemd + direct fallback. Log tail + command send via RCON/stdin."""
import subprocess, os, time
from pathlib import Path
import psutil
from .config import SERVER_DIR, LOGS, load_config
from .rcon import rcon_command

UNIT = "vohost-mc"

def _run(*a, **k):
    return subprocess.run(*a, capture_output=True, text=True, **k)

def service_active() -> bool:
    r = _run(["systemctl", "is-active", UNIT])
    if r.returncode == 0 and "active" in r.stdout:
        return True
    # fallback: java process with server dir?
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "java" in cmd and str(SERVER_DIR) in cmd:
                return True
        except Exception:
            pass
    return False

def action(act: str) -> dict:
    if act in ("start", "stop", "restart"):
        r = _run(["sudo", "-n", "systemctl", act, UNIT])
        if r.returncode != 0:  # try without sudo (dev machines)
            r = _run(["systemctl", act, UNIT])
        return {"ok": r.returncode == 0, "out": (r.stdout + r.stderr)[-2000:]}
    if act == "kill":
        killed = 0
        for p in psutil.process_iter():
            try:
                cmd = " ".join(p.cmdline())
                if "java" in cmd and str(SERVER_DIR) in cmd:
                    p.kill()
                    killed += 1
            except Exception:
                pass
        return {"ok": True, "killed": killed}
    return {"ok": False, "error": "unknown action"}

def send_command(cmd: str) -> dict:
    cfg = load_config()
    rc = cfg.get("rcon", {})
    try:
        out = rcon_command(rc.get("host", "127.0.0.1"), int(rc.get("port", 25575)),
                           rc.get("password", "vohost-rcon"), cmd)
        return {"ok": True, "via": "rcon", "out": out}
    except Exception as e:
        # fallback: systemd stdin not available -> report clearly
        return {"ok": False, "via": "rcon", "error": str(e),
                "hint": "Enable RCON in Options (enable-rcon=true) and restart."}

def tail_log(lines=200) -> str:
    for cand in (SERVER_DIR / "logs" / "latest.log", LOGS / "mc.log"):
        if cand.exists():
            try:
                data = cand.read_text(errors="replace").splitlines()
                return "\n".join(data[-lines:])
            except Exception:
                pass
    # journalctl fallback
    r = _run(["journalctl", "-u", UNIT, "-n", str(lines), "--no-pager", "--no-hostname", "-o", "cat"])
    return r.stdout[-20000:] if r.returncode == 0 else "(no logs yet — start the server)"

def metrics() -> dict:
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    disk = psutil.disk_usage(str(SERVER_DIR)).percent
    java_rss = 0
    for p in psutil.process_iter(["memory_info", "cmdline"]):
        try:
            if "java" in " ".join(p.info["cmdline"] or []):
                java_rss += p.info["memory_info"].rss
        except Exception:
            pass
    # TPS approx from latest.log (Paper/Purpur) else -1
    tps = -1.0
    try:
        log = tail_log(50)
        import re
        m = re.findall(r"TPS.*?([\d.]+)", log)
        if m:
            tps = float(m[-1])
    except Exception:
        pass
    return {"cpu": cpu, "ram_pct": vm.percent, "ram_used_mb": vm.used // 1048576,
            "disk_pct": disk, "mc_rss_mb": java_rss // 1048576,
            "online": service_active(), "tps": tps, "ts": time.time()}
