"""VoHost shared config + paths."""
import os, json
from pathlib import Path

BASE = Path(os.environ.get("VOHOST_BASE", "/opt/vohost"))
SERVER_DIR = Path(os.environ.get("VOHOST_SERVER", BASE / "server"))
DATA = BASE / "data"
LOGS = BASE / "logs"
BACKUPS = BASE / "backups"
WORLDS_STAGING = BASE / "worlds_staging"

for p in (BASE, SERVER_DIR, DATA, LOGS, BACKUPS):
    p.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA / "config.json"
USERS_FILE = DATA / "users.json"

DEFAULTS = {
    "dashboard_port": 8080,
    "mc_port": 25565,
    "mc_memory_min": "1G",
    "mc_memory_max": "4G",
    "java_map": {
        "8": "/usr/lib/jvm/temurin-8-jdk-amd64/bin/java",
        "17": "/usr/lib/jvm/temurin-17-jdk-amd64/bin/java",
        "21": "/usr/lib/jvm/temurin-21-jdk-amd64/bin/java",
        "25": "/usr/lib/jvm/temurin-21-jdk-amd64/bin/java"
    },
    "timezone": "UTC",
    "curseforge_api_key": "",
    "discord_webhook": "",
    "public_page": True,
    "scheduler": {"auto_restart": "", "auto_backup": "0 4 * * *"},
    "rcon": {"host": "127.0.0.1", "port": 25575, "password": "vohost-rcon"},
}

def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except Exception:
            pass
    # allow env override for CF key
    if os.environ.get("CURSEFORGE_API_KEY"):
        cfg["curseforge_api_key"] = os.environ["CURSEFORGE_API_KEY"]
    # java 25 fallback: if binary missing, fall back to 21
    jm = cfg.get("java_map", {})
    if not Path(jm.get("25", "")).exists() and Path(jm.get("21", "")).exists():
        jm["25"] = jm["21"]
    return cfg

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def java_for_mc(mc_version: str, cfg: dict) -> str:
    """MC -> Java mapping: <=1.16 = 8/17, 1.17-1.20.3 = 17, >=1.20.4 = 17/21, >=1.21 = 21."""
    try:
        parts = [int(x) for x in mc_version.split(".")[:2]]
        major, minor = (parts + [0])[:2]
    except Exception:
        return cfg["java_map"]["21"]
    jm = cfg["java_map"]
    def pick(*keys):
        for k in keys:
            p = jm.get(str(k), "")
            if p and Path(p).exists():
                return p
        return "java"
    if major == 1 and minor <= 16:
        return pick(17, 8, 21)
    if major == 1 and minor <= 20:
        return pick(17, 21)
    return pick(21, 25, 17)
