"""Server process control — multi-server via vohost-mc@<id> template + legacy vohost-mc fallback."""
import subprocess, time
from pathlib import Path
import psutil
from .config import SERVER_DIR, LOGS, load_config
from .rcon import rcon_command

LEGACY_UNIT = "vohost-mc"

def _run(*a, **k):
    return subprocess.run(*a, capture_output=True, text=True, **k)

def _ctx(server_id: str = "", server: dict | None = None):
    """Resolve unit + dir + rcon for a server. server_id='' means default/legacy."""
    sdir, unit, rcon = SERVER_DIR, LEGACY_UNIT, None
    if server is not None:
        from pathlib import Path as _P
        sdir = _P(server.get("dir", str(SERVER_DIR)))
        sid = server.get("id", "")
        unit = f"vohost-mc@{sid}" if sid and sid != "main" else LEGACY_UNIT
        rcon = {"host": "127.0.0.1", "port": int(server.get("rcon_port", 25575)), "password": "vohost-rcon"}
    elif server_id and server_id != "main":
        try:
            from . import servers as _S
            s = _S.get_server(server_id)
            sdir = _S.server_dir(server_id)
            unit = f"vohost-mc@{server_id}"
            rcon = {"host": "127.0.0.1", "port": int(s.get("rcon_port", 25575)), "password": "vohost-rcon"}
        except Exception:
            pass
    return sdir, unit, rcon

def service_active(server_id: str = "", server: dict | None = None) -> bool:
    sdir, unit, _ = _ctx(server_id, server)
    r = _run(["systemctl", "is-active", unit])
    if r.returncode == 0 and "active" in r.stdout:
        return True
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "java" in cmd and str(sdir) in cmd:
                return True
        except Exception:
            pass
    return False

def action(act: str, server_id: str = "", server: dict | None = None) -> dict:
    _, unit, _ = _ctx(server_id, server)
    if act in ("start", "stop", "restart"):
        r = _run(["sudo", "-n", "systemctl", act, unit])
        if r.returncode != 0:
            r = _run(["systemctl", act, unit])
        return {"ok": r.returncode == 0, "unit": unit, "out": (r.stdout + r.stderr)[-2000:]}
    if act == "kill":
        sdir, _, _ = _ctx(server_id, server)
        killed = 0
        for p in psutil.process_iter():
            try:
                cmd = " ".join(p.cmdline())
                if "java" in cmd and str(sdir) in cmd:
                    p.kill()
                    killed += 1
            except Exception:
                pass
        return {"ok": True, "killed": killed}
    return {"ok": False, "error": "unknown action"}

def _rcon_for(server_id="", server=None):
    _, _, r = _ctx(server_id, server)
    if r:
        # allow per-server password override from server.properties
        try:
            sdir, _, _ = _ctx(server_id, server)
            for line in (sdir / "server.properties").read_text(errors="replace").splitlines():
                if line.startswith("rcon.password="):
                    r["password"] = line.split("=", 1)[1]
        except Exception:
            pass
        return r
    cfg = load_config()
    return cfg.get("rcon", {})

def send_command(cmd: str, server_id: str = "", server: dict | None = None) -> dict:
    rc = _rcon_for(server_id, server)
    try:
        out = rcon_command(rc.get("host", "127.0.0.1"), int(rc.get("port", 25575)),
                           rc.get("password", "vohost-rcon"), cmd)
        return {"ok": True, "via": "rcon", "out": out}
    except Exception as e:
        return {"ok": False, "via": "rcon", "error": str(e),
                "hint": "Enable RCON in Options (enable-rcon=true) and restart."}

def tail_log(lines=200, server_id: str = "", server: dict | None = None) -> str:
    sdir, unit, _ = _ctx(server_id, server)
    for cand in (sdir / "logs" / "latest.log", LOGS / "mc.log"):
        if cand.exists():
            try:
                data = cand.read_text(errors="replace").splitlines()
                return "\n".join(data[-lines:])
            except Exception:
                pass
    r = _run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "--no-hostname", "-o", "cat"])
    return r.stdout[-20000:] if r.returncode == 0 else "(no logs yet — start the server)"

def metrics(server_id: str = "", server: dict | None = None) -> dict:
    import time as _t
    sdir, _, _ = _ctx(server_id, server)
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.1)
    try:
        disk = psutil.disk_usage(str(sdir)).percent
    except Exception:
        disk = 0
    java_rss = 0
    for p in psutil.process_iter(["memory_info", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "java" in cmd and str(sdir) in cmd:
                java_rss += p.info["memory_info"].rss
        except Exception:
            pass
    tps = -1.0
    try:
        log = tail_log(50, server_id, server)
        import re
        m = re.findall(r"TPS.*?([\d.]+)", log)
        if m:
            tps = float(m[-1])
    except Exception:
        pass
    return {"cpu": cpu, "ram_pct": vm.percent, "ram_used_mb": vm.used // 1048576,
            "disk_pct": disk, "mc_rss_mb": java_rss // 1048576,
            "online": service_active(server_id, server), "tps": tps, "ts": _t.time()}
