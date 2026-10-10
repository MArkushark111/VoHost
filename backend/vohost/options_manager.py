"""server.properties + MOTD/icon/options with toggle support. Multi-server aware via sdir param."""
from pathlib import Path
from .config import SERVER_DIR

DEFAULT_PROPS = {
    "server-name": "VoHost Server",
    "motd": "A VoHost Minecraft Server",
    "max-players": "20",
    "gamemode": "survival",
    "difficulty": "easy",
    "white-list": "false",
    "allow-flight": "false",
    "force-gamemode": "false",
    "spawn-protection": "16",
    "pvp": "true",
    "online-mode": "true",
    "enable-rcon": "true",
    "rcon.port": "25575",
    "rcon.password": "vohost-rcon",
    "query.port": "25565",
    "server-port": "25565",
    "resource-pack": "",
    "require-resource-pack": "false",
    "resource-pack-prompt": "",
}

TOGGLES = ["white-list", "allow-flight", "force-gamemode", "pvp", "online-mode",
           "enable-rcon", "require-resource-pack", "enable-whitelist"]

def _dir(sdir=None) -> Path:
    return Path(sdir) if sdir else SERVER_DIR

def props_path(sdir=None) -> Path:
    return _dir(sdir) / "server.properties"

def read_props(sdir=None) -> dict:
    d = dict(DEFAULT_PROPS)
    p = props_path(sdir)
    base = _dir(sdir)
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    d["_timezone"] = (base / ".timezone").read_text().strip() if (base / ".timezone").exists() else "UTC"
    d["_env"] = (base / ".env_extra").read_text() if (base / ".env_extra").exists() else ""
    d["_network_mode"] = (base / ".network_mode").read_text().strip() if (base / ".network_mode").exists() else "wan"
    return d

def write_props(patch: dict, sdir=None):
    base = _dir(sdir)
    cur = read_props(sdir)
    cur.update({k: str(v) for k, v in patch.items() if not k.startswith("_")})
    lines = ["# VoHost server.properties (managed)"]
    for k, v in cur.items():
        if k.startswith("_"):
            continue
        lines.append(f"{k}={v}")
    props_path(sdir).write_text("\n".join(lines) + "\n")
    if "_timezone" in patch:
        (base / ".timezone").write_text(str(patch["_timezone"]))
    if "_env" in patch:
        (base / ".env_extra").write_text(str(patch["_env"]))
    if "_network_mode" in patch:
        (base / ".network_mode").write_text(str(patch["_network_mode"]))
    return cur
