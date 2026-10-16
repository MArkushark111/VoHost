"""Scheduled daily restart: stop + start each opted-in server at HH:MM.

Time is the machine's local clock (same basis as the backup scheduler).
State file records the last restart day per server so a match fires once.
"""
import json
import time as _t
from datetime import datetime
from pathlib import Path

from .config import DATA

STATE = DATA / "restarts.json"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(st: dict):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=2))
    except Exception:
        pass


def last(sid: str) -> dict | None:
    return _state().get(sid)


def due_servers(servers, now=None) -> list:
    """Servers whose restart time matches this minute and haven't run today. Pure."""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = f"{now.hour:02d}:{now.minute:02d}"
    st = _state()
    out = []
    for s in servers or []:
        try:
            sc = (s or {}).get("restart") or {}
            if not sc.get("enabled"):
                continue
            at = str(sc.get("at", ""))
            if at != hm:
                continue
            if (st.get((s or {}).get("id", "")) or {}).get("day") == today:
                continue
            out.append(s)
        except Exception:
            pass
    return out


def run_due(sm=None, now=None, warn_seconds=60) -> list:
    """Run due restarts. sm injectable (defaults to server_manager). Never raises."""
    if sm is None:
        try:
            from . import server_manager as sm
        except Exception:
            return []
    try:
        from . import servers as SV
        servers = SV.list_servers()
    except Exception:
        return []
    done = []
    for s in due_servers(servers, now):
        sid = s.get("id", "")
        try:
            online = bool(sm.service_active(server=s))
        except Exception:
            online = False
        try:
            if online:
                try:
                    sm.send_command("say [VoHost] Scheduled restart in 60 seconds", server=s)
                except Exception:
                    pass
                if warn_seconds > 0:
                    _t.sleep(warn_seconds)
                r = sm.action("restart", server_id=sid, server=s)
                note = "restarted"
            else:
                r = sm.action("start", server_id=sid, server=s)
                note = "was stopped - started"
            ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
        except Exception as e:
            ok, note = False, f"failed: {e}"[:160]
        st = _state()
        st[sid] = {"day": (now or datetime.now()).strftime("%Y-%m-%d"),
                   "ok": ok, "note": note, "ts": _t.time()}
        _save(st)
        done.append({"server": sid, "ok": ok, "note": note})
    return done
