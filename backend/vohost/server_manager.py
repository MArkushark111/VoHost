"""Server process control — multi-server via vohost-mc@<id> template + legacy vohost-mc fallback."""
import subprocess, time
from pathlib import Path
import psutil
from .config import SERVER_DIR, LOGS, load_config
from .rcon import rcon_command

LEGACY_UNIT = "vohost-mc"

def _run(*a, **k):
    try:
        return subprocess.run(*a, capture_output=True, text=True, **k)
    except FileNotFoundError:
        return type("R", (), {"returncode": 127, "stdout": "", "stderr": "systemctl not available"})()

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
    # exact match: "activating" also contains "active" and must NOT count as online
    if r.returncode == 0 and r.stdout.strip() in ("active", "reloading"):
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
    if act in ("start", "restart"):
        r = _run(["sudo", "-n", "systemctl", act, unit])
        if r.returncode != 0:
            r = _run(["systemctl", act, unit])
        res = {"ok": r.returncode == 0, "unit": unit, "out": (r.stdout + r.stderr)[-2000:]}
        # if the process dies right away, surface the reason instead of pretending it started
        time.sleep(6)
        if not service_active(server_id, server):
            res["ok"] = False
            res["crashed"] = True
            res["note"] = "Server exited right after start. Last log lines:\n" + tail_log(400, server_id, server)[-20000:]
        return res
    if act == "stop":
        r = _run(["sudo", "-n", "systemctl", "stop", unit])
        if r.returncode != 0:
            r = _run(["systemctl", "stop", unit])
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
        # allow per-server password/port override from server.properties
        try:
            sdir, _, _ = _ctx(server_id, server)
            for line in (sdir / "server.properties").read_text(errors="replace").splitlines():
                if line.startswith("rcon.password="):
                    r["password"] = line.split("=", 1)[1]
                elif line.startswith("rcon.port="):
                    try:
                        r["port"] = int(line.split("=", 1)[1])
                    except Exception:
                        pass
        except Exception:
            pass
        return r
    cfg = load_config()
    return cfg.get("rcon", {})

def send_command(cmd: str, server_id: str = "", server: dict | None = None) -> dict:
    rc = _rcon_for(server_id, server)
    cmd = (cmd or "").strip()
    if cmd.startswith("/"):  # in-game habit; RCON takes the bare command
        cmd = cmd[1:].lstrip()
    if not cmd:
        return {"ok": False, "via": "rcon", "error": "empty command"}
    try:
        out = rcon_command(rc.get("host", "127.0.0.1"), int(rc.get("port", 25575)),
                           rc.get("password", "vohost-rcon"), cmd)
        return {"ok": True, "via": "rcon", "out": out}
    except Exception as e:
        return {"ok": False, "via": "rcon", "error": str(e),
                "hint": "Enable RCON in Options (enable-rcon=true) and restart."}

def rcon_diag(server_id: str = "", server: dict | None = None) -> dict:
    """One-shot RCON health report: what the panel targets vs what the server
    has configured vs what actually answers on TCP. Powers the 'Test RCON'
    button in the Console tab."""
    import socket
    sdir, unit, _ = _ctx(server_id, server)
    props: dict = {}
    perr = ""
    try:
        for line in (sdir / "server.properties").read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    except Exception as e:
        perr = str(e)
    rc = _rcon_for(server_id, server)
    host = rc.get("host", "127.0.0.1")
    try:
        port = int(rc.get("port", 25575))
    except Exception:
        port = 25575
    try:
        game_port = int(props.get("server-port", (server or {}).get("port", 25565)))
    except Exception:
        game_port = 25565

    def tcp_probe(h, p, timeout=3):
        try:
            s = socket.create_connection((h, p), timeout=timeout)
            try:
                s.close()
            except Exception:
                pass
            return {"open": True}
        except Exception as e:
            return {"open": False, "error": str(e)[:150]}

    tcp_r = tcp_probe(host, port)
    tcp_g = tcp_probe(host, game_port)
    auth: dict = {"ok": False, "error": "not attempted"}
    if tcp_r.get("open"):
        try:
            out = rcon_command(host, port, rc.get("password", "vohost-rcon"), "list", timeout=5)
            auth = {"ok": True, "out": out[:300]}
        except Exception as e:
            auth = {"ok": False, "error": str(e)[:300]}

    en = props.get("enable-rcon", "").lower()
    rp = props.get("rcon.port", "")
    pw = props.get("rcon.password", "")
    if perr or "enable-rcon" not in props:
        sug = f"server.properties is not readable ({perr or 'missing'}). Start the server once so it generates the file, then press Restart."
    elif en != "true":
        sug = "RCON is disabled (enable-rcon=false in server.properties). Set enable-rcon=true in Options, then Restart the server."
    elif rp and game_port and rp == str(game_port):
        sug = (f"rcon.port ({rp}) equals the game port - the server cannot run RCON there. "
               f"Press Restart (VoHost auto-repairs this) or set rcon.port={((server or {}).get('rcon_port', 25575))} in Options.")
    elif not tcp_r.get("open"):
        sug = (f"Nothing answers on {host}:{port} ({tcp_r.get('error', '')}). The server is likely still "
               f"starting or runs with older settings - wait for 'Done' in the Log, then press Restart once.")
    elif not auth.get("ok") and "bad rcon password" in str(auth.get("error", "")).lower():
        sug = "RCON answered but rejected the password: server.properties changed while the server was running. Restart the server so it picks up the current file."
    elif not auth.get("ok") and "timed out" in str(auth.get("error", "")).lower():
        sug = (f"Something accepts TCP on {port} but never speaks RCON - usually the game port. "
               f"Check rcon.port in server.properties (now {rp or 'unset?'}) and Restart.")
    elif not auth.get("ok"):
        sug = f"RCON probe failed: {auth.get('error', '')}. Press Restart once, wait for 'Done' in the Log, then Test RCON again."
    elif pw == "":
        sug = ("RCON works, but rcon.password is empty - anyone on this machine could control the server. "
               "Set a password in Options (rcon.password), then Restart.")
    else:
        sug = "RCON is healthy - console commands should work."
    return {"target": {"host": host, "port": port,
                       "password_source": "server.properties" if "rcon.password" in props else "panel default"},
            "props": {k: props.get(k, "") for k in ("enable-rcon", "rcon.port", "rcon.password", "server-port")},
            "props_password_set": pw != "",
            "tcp_rcon": tcp_r, "tcp_game": tcp_g, "auth": auth,
            "service_unit": unit, "suggestion": sug}

def tail_log(lines=200, server_id: str = "", server: dict | None = None) -> str:
    sdir, unit, _ = _ctx(server_id, server)
    # MC's own log first, then the systemd stdout log for this specific server (mc-<id>.log)
    cands = [sdir / "logs" / "latest.log", LOGS / "mc.log"]
    if server_id and server_id != "main":
        cands.append(LOGS / f"mc-{server_id}.log")
    best = None
    for c in cands:
        try:
            if c.exists():
                m = c.stat().st_mtime
                if best is None or m > best[1]:
                    best = (c, m)
        except Exception:
            pass
    if best:
        try:
            data = best[0].read_text(errors="replace").splitlines()
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
