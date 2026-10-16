"""Backups: per-server zip snapshots + restore (zip-slip safe) + scheduler thread (daily/hourly, retention).

Schedule lives per-server in servers.json under entry["backup"]:
    {"enabled": bool, "mode": "daily"|"hourly", "hour": int, "minute": int, "keep": int}
Legacy single-server mode falls back to config scheduler.auto_backup ("min hour * * *").
"""
import zipfile, time, json, shutil
from pathlib import Path
from datetime import datetime
from .config import SERVER_DIR, BACKUPS

META = BACKUPS / "meta.json"

def _meta() -> dict:
    try:
        return json.loads(META.read_text())
    except Exception:
        return {"backups": []}

def _save(m: dict):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    META.write_text(json.dumps(m, indent=2))

def _prune(server: str, keep: int):
    """Keep only the `keep` newest entries for this server, deleting the old zips."""
    m = _meta()
    rows = [b for b in m["backups"] if b.get("server") == server]
    rows.sort(key=lambda b: b.get("ts", 0), reverse=True)
    for old in rows[keep:]:
        try:
            (BACKUPS / old["file"]).unlink(missing_ok=True)
        except Exception:
            pass
    keep_ids = {old["file"] for old in rows[:keep]}
    m["backups"] = [b for b in m["backups"] if b.get("server") != server or b["file"] in keep_ids]
    _save(m)

def create_backup(sdir=None, label="manual", keep=5) -> dict:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    src = Path(sdir) if sdir else SERVER_DIR
    sid = src.name  # "srv-xxxx" for managed servers, "server" for the legacy dir
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / (f"backup-{ts}-{label}.zip" if sid == "server" else f"backup-{sid}-{ts}-{label}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in src.rglob("*"):
            rel = p.relative_to(src)
            if "cache" in p.parts or p == dest or rel.name.lower().endswith(".zip"):
                continue
            try:
                if p.is_file() and p.stat().st_size < 200_000_000:
                    z.write(p, rel.as_posix())
            except Exception:
                pass
    st = dest.stat()
    m = _meta()
    m["backups"] = [{"file": dest.name, "server": sid, "ts": time.time(), "label": label, "size": st.st_size}] + m["backups"]
    _save(m)
    if keep > 0:
        _prune(sid, keep)
    return {"file": dest.name, "size": st.st_size}

def list_backups(server_id: str = "") -> dict:
    m = _meta()
    rows = [b for b in m["backups"] if (not server_id) or b.get("server") == server_id]
    now = time.time()
    fresh = any(now - b.get("ts", 0) < 7 * 86400 for b in m["backups"])
    return {"backups": rows[:50], "needs_attention": not fresh, "fresh": fresh}

def find_backup(name: str) -> dict | None:
    """Return the meta entry for a known backup file, else None."""
    for b in _meta().get("backups", []):
        if b.get("file") == name:
            return b
    return None

def backup_path(name: str) -> Path | None:
    """Resolve a known backup file inside BACKUPS (None if unknown/escaping/missing)."""
    if not name or "/" in name or "\\" in name or not name.endswith(".zip"):
        return None
    if not find_backup(name):
        return None
    p = (BACKUPS / name).resolve()
    try:
        if BACKUPS.resolve() not in p.parents and p != BACKUPS.resolve():
            return None
    except Exception:
        return None
    return p if p.exists() else None

def restore(name: str) -> dict:
    src = BACKUPS / name
    if not src.exists():
        raise FileNotFoundError(name)
    m = _meta()
    sid = next((b.get("server") for b in m["backups"] if b.get("file") == name), None)
    if sid and sid != "server":
        try:
            from . import servers as SV
            s = SV.get_server(sid)
            target = Path(s.get("dir", str(SERVER_DIR)))
        except Exception:
            target = SERVER_DIR
    else:
        target = SERVER_DIR
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            dest = (target / info.filename).resolve()
            if target.resolve() not in dest.parents and dest != target.resolve():
                continue  # zip-slip guard
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as fi, open(dest, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
    return {"ok": True, "restored": name, "server": sid or "legacy"}

# ---------------- scheduler ----------------
def last_scheduled(server: str) -> float:
    m = _meta()
    rows = [b for b in m["backups"] if b.get("server") == server and b.get("label") == "scheduled"]
    return max((b.get("ts", 0) for b in rows), default=0.0)

def run_due():
    """Trigger any due scheduled backups for every server with backup.enabled=true."""
    from . import servers as SV
    now = datetime.now()
    servers = SV.list_servers()
    for s in servers:
        try:
            sc = s.get("backup") or {}
            if not sc.get("enabled"):
                continue
            sdir = Path(s.get("dir", ""))
            if not sdir.exists():
                continue
            keep = int(sc.get("keep") or 5)
            mode = sc.get("mode") or "daily"
            hour = int(sc.get("hour") or 4)
            minute = int(sc.get("minute") or 0)
            last = last_scheduled(s.get("id"))
            if mode == "hourly":
                if now.minute == minute and (now.timestamp() - last) > 55 * 60:
                    create_backup(sdir, "scheduled", keep)
            else:
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if now.hour == hour and now.minute == minute and last < start_of_day:
                    create_backup(sdir, "scheduled", keep)
        except Exception:
            pass
    # legacy fallback: no servers configured yet, use the old config cron "min hour * * *"
    if not servers:
        try:
            from .config import load_config
            cron = (load_config().get("scheduler") or {}).get("auto_backup") or ""
            parts = cron.strip().split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                minute, hour = int(parts[0]), int(parts[1])
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if now.hour == hour and now.minute == minute and last_scheduled("server") < start_of_day:
                    create_backup(None, "scheduled", 5)
        except Exception:
            pass

def start_scheduler():
    """Background loop the dashboard runs at boot. Checks every 30s."""
    import time as _t
    while True:
        try:
            run_due()
        except Exception:
            pass
        try:
            from . import restarts as _RT
            _RT.run_due()
        except Exception:
            pass
        _t.sleep(30)