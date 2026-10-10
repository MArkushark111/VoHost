"""Multi-server registry: /opt/vohost/servers/<id>/ + servers.json. Legacy /opt/vohost/server migrates to id=main."""
import json, time, secrets, shutil, subprocess
from pathlib import Path
from .config import BASE, DATA, SERVER_DIR

SERVERS_ROOT = BASE / "servers"
SERVERS_FILE = DATA / "servers.json"
LEGACY = SERVER_DIR  # /opt/vohost/server

def _load() -> dict:
    if SERVERS_FILE.exists():
        try:
            return json.loads(SERVERS_FILE.read_text())
        except Exception:
            pass
    return {"servers": []}

def _save(db: dict):
    SERVERS_FILE.write_text(json.dumps(db, indent=2))

def _next_ports(used):
    port, rcon = 25565, 25575
    ups = {s.get("port") for s in used}
    urs = {s.get("rcon_port") for s in used}
    while port in ups or rcon in urs:
        port += 1
        rcon += 1
    return port, rcon

def migrate_legacy():
    db = _load()
    if db["servers"]:
        return db
    if LEGACY.exists() and any(LEGACY.iterdir()):
        db["servers"] = [{"id": "main", "name": "mx101", "network_mode": "wan",
                          "port": 25565, "rcon_port": 25575,
                          "memory_min": "1G", "memory_max": "4G",
                          "loader": "vanilla", "mc_version": "latest",
                          "dir": str(LEGACY), "created": time.time()}]
        _save(db)
    return db

def list_servers():
    db = migrate_legacy()
    # enrich with live online state lazily by caller
    return db["servers"]

def get_server(sid: str) -> dict:
    db = migrate_legacy()
    for s in db["servers"]:
        if s["id"] == sid:
            return s
    # default fallback: first server or legacy
    if db["servers"]:
        return db["servers"][0]
    raise KeyError(f"no servers (id={sid}) — create one via POST /api/servers)")

def server_dir(sid: str) -> Path:
    s = get_server(sid)
    d = Path(s.get("dir", str(SERVERS_ROOT / sid)))
    d.mkdir(parents=True, exist_ok=True)
    return d

def create_server(name: str, network_mode: str = "wan", port: int | None = None,
                  memory_max: str = "4G", loader: str = "vanilla", mc_version: str = "latest") -> dict:
    assert network_mode in ("wan", "lan"), "network_mode must be wan|lan"
    db = migrate_legacy()
    sid = "srv-" + secrets.token_hex(3)
    p, r = _next_ports(db["servers"])
    entry = {"id": sid, "name": name or sid, "network_mode": network_mode,
             "port": port or p, "rcon_port": r,
             "memory_min": "1G", "memory_max": memory_max,
             "loader": loader, "mc_version": mc_version,
             "dir": str(SERVERS_ROOT / sid), "created": time.time()}
    Path(entry["dir"]).mkdir(parents=True, exist_ok=True)
    # seed server.properties ports so MC + RCON don't clash
    try:
        (Path(entry["dir"]) / "server.properties").write_text(
            f"server-port={entry['port']}\nrcon.port={entry['rcon_port']}\nenable-rcon=true\n")
        (Path(entry["dir"]) / ".network_mode").write_text(network_mode)
    except Exception:
        pass
    db["servers"].append(entry)
    _save(db)
    apply_network_mode(entry)
    return entry

def update_server(sid: str, patch: dict) -> dict:
    db = _load()
    for s in db["servers"]:
        if s["id"] == sid:
            for k in ("name", "network_mode", "memory_max", "memory_min", "loader", "mc_version", "port", "rcon_port"):
                if k in patch:
                    s[k] = patch[k]
            _save(db)
            if "network_mode" in patch or "port" in patch:
                apply_network_mode(s)
            return s
    raise KeyError(sid)

def delete_server(sid: str, wipe: bool = False):
    db = _load()
    tgt = next((s for s in db["servers"] if s["id"] == sid), None)
    db["servers"] = [s for s in db["servers"] if s["id"] != sid]
    _save(db)
    if tgt and wipe:
        shutil.rmtree(tgt.get("dir", ""), ignore_errors=True)
    # stop unit best-effort
    try:
        subprocess.run(["systemctl", "stop", f"vohost-mc@{sid}"], capture_output=True, timeout=10)
    except Exception:
        pass
    return {"ok": True}

def apply_network_mode(s: dict):
    """WAN = public UFW allow <port>; LAN = allow only from private subnets."""
    port = int(s.get("port", 25565))
    mode = s.get("network_mode", "wan")
    cmds = []
    try:
        if mode == "wan":
            cmds = [["ufw", "allow", f"{port}/tcp"], ["ufw", "allow", f"{port}/udp"]]
        else:
            # remove public rule, allow LAN subnets only
            cmds = [[ "ufw", "delete", "allow", f"{port}/tcp"],
                    ["ufw", "delete", "allow", f"{port}/udp"]]
            for net in ("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"):
                cmds += [[ "ufw", "allow", "from", net, "to", "any", "port", str(port)]]
        for c in cmds:
            subprocess.run(c, capture_output=True, timeout=15)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "mode": mode, "port": port}
