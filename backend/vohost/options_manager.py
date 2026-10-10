"""server.properties + MOTD/icon/options with toggle support."""
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

def props_path() -> Path:
    return SERVER_DIR / "server.properties"

def read_props() -> dict:
    d = dict(DEFAULT_PROPS)
    p = props_path()
    if p.exists():
        for line in p.read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    # overlay env/timezone + name
    d["_timezone"] = (SERVER_DIR / ".timezone").read_text().strip() if (SERVER_DIR / ".timezone").exists() else "UTC"
    d["_env"] = (SERVER_DIR / ".env_extra").read_text() if (SERVER_DIR / ".env_extra").exists() else ""
    return d

def write_props(patch: dict):
    cur = read_props()
    cur.update({k: str(v) for k, v in patch.items() if not k.startswith("_")})
    lines = ["# VoHost server.properties (managed)"]
    for k, v in cur.items():
        if k.startswith("_"):
            continue
        lines.append(f"{k}={v}")
    props_path().write_text("\n".join(lines) + "\n")
    if "_timezone" in patch:
        (SERVER_DIR / ".timezone").write_text(str(patch["_timezone"]))
    if "_env" in patch:
        (SERVER_DIR / ".env_extra").write_text(str(patch["_env"]))
    # keep RCON in sync note for backend config (actual rcon secret lives in data/config.json too)
    return cur
