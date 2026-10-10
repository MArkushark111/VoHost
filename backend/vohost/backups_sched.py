"""Backups: zip snapshots + restore + scheduler state (red badge cleared when fresh backup exists)."""
import zipfile, time, json
from pathlib import Path
from datetime import datetime
from .config import SERVER_DIR, BACKUPS

META = BACKUPS / "meta.json"

def _meta():
    try:
        return json.loads(META.read_text())
    except Exception:
        return {"backups": []}

def _save(m):
    META.write_text(json.dumps(m, indent=2))

def create_backup(label="manual") -> dict:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / f"backup-{ts}-{label}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in SERVER_DIR.rglob("*"):
            if "cache" in p.parts or p == dest:
                continue
            try:
                if p.is_file() and p.stat().st_size < 200_000_000:
                    z.write(p, p.relative_to(SERVER_DIR))
            except Exception:
                pass
    m = _meta()
    m["backups"] = ([{"file": dest.name, "ts": time.time(), "label": label}] + m["backups"])[:20]
    _save(m)
    return {"file": dest.name, "size": dest.stat().st_size}

def list_backups():
    m = _meta()
    now = time.time()
    fresh = any(now - b.get("ts", 0) < 7 * 86400 for b in m["backups"])
    return {"backups": m["backups"], "needs_attention": not fresh, "fresh": fresh}

def restore(name: str):
    src = BACKUPS / name
    if not src.exists():
        raise FileNotFoundError(name)
    import shutil
    with zipfile.ZipFile(src) as z:
        z.extractall(SERVER_DIR)
    return {"ok": True, "restored": name}
