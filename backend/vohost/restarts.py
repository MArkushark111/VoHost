"""Scheduled shutdown / startup: stop and/or start each opted-in server at set times.

Time is the machine's local clock (same basis as the backup scheduler).
State records the last run day per server per action, so each fires once.
Legacy single-time restarts ({enabled, at}) still work: stop+start that minute.
"24:00" is accepted as midnight ("00:00").
"""
import json
import re
import time as _t
from datetime import datetime

from .config import DATA

STATE = DATA / "restarts.json"
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def norm_time(raw: str) -> str:
    """'4:00' -> '04:00', '24:00' -> '00:00', '' stays '', garbage -> ''."""
    s = (raw or "").strip()
    if s == "24:00":
        return "00:00"
    m = re.fullmatch(r"(\d{1,2}):([0-5]\d)", s)
    if not m:
        return ""
    h = int(m.group(1))
    if h > 24 or (h == 24 and m.group(2) != "00"):
        return ""
    if h == 24:
        return "00:00"
    return f"{h:02d}:{m.group(2)}"


def valid_time(raw: str) -> bool:
    return bool(TIME_RE.fullmatch(norm_time(raw)))


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


def last(sid: str):
    return _state().get(sid)


def _ran_day(st: dict, sid: str, action: str, today: str) -> bool:
    ent = (st or {}).get(sid) or {}
    if isinstance(ent, dict) and "day" in ent and action == "restart":
        return ent.get("day") == today  # legacy flat shape
    sub = ent.get(action) if isinstance(ent, dict) else None
    return isinstance(sub, dict) and sub.get("day") == today


def _wanted(s) -> list:
    """(action, at) pairs from old {enabled,at} or new {enabled,shutdown_at,startup_at} shapes."""
    sc = (s or {}).get("restart") or {}
    if not sc.get("enabled"):
        return []
    out = []
    if sc.get("shutdown_at") or sc.get("startup_at"):
        if norm_time(sc.get("shutdown_at", "")):
            out.append(("shutdown", norm_time(sc.get("shutdown_at", ""))))
        if norm_time(sc.get("startup_at", "")):
            out.append(("startup", norm_time(sc.get("startup_at", ""))))
    elif norm_time(sc.get("at", "")):
        out.append(("restart", norm_time(sc.get("at", ""))))
    return out


def due_servers(servers, now=None) -> list:
    """[{server, action}] due this minute and not yet run today. Pure."""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    hm = f"{now.hour:02d}:{now.minute:02d}"
    st = _state()
    out = []
    for s in servers or []:
        try:
            sid = (s or {}).get("id", "")
            for action, at in _wanted(s):
                if at == hm and not _ran_day(st, sid, action, today):
                    out.append({"server": s, "action": action})
        except Exception:
            pass
    return out


def _record(sid: str, action: str, ok: bool, note: str, now=None):
    st = _state()
    ent = st.get(sid)
    if not isinstance(ent, dict) or "day" in ent:
        ent = {}
    ent[action] = {"day": (now or datetime.now()).strftime("%Y-%m-%d"),
                   "ok": ok, "note": note[:200], "ts": _t.time()}
    st[sid] = ent
    _save(st)


def run_due(sm=None, now=None, warn_seconds=60) -> list:
    """Run due shutdowns/startups/restarts. sm injectable. Never raises."""
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
    for item in due_servers(servers, now):
        s, action = item["server"], item["action"]
        sid = s.get("id", "")
        try:
            try:
                online = bool(sm.service_active(server=s))
            except Exception:
                online = False
            if action == "shutdown":
                if online:
                    try:
                        sm.send_command("say [VoHost] Scheduled shutdown in 60 seconds", server=s)
                    except Exception:
                        pass
                    if warn_seconds > 0:
                        _t.sleep(warn_seconds)
                    r = sm.action("stop", server_id=sid, server=s)
                    ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
                    note = "shut down on schedule"
                else:
                    ok, note = True, "already stopped"
            elif action == "startup":
                if online:
                    ok, note = True, "already running"
                else:
                    r = sm.action("start", server_id=sid, server=s)
                    ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
                    note = "started on schedule"
            else:  # legacy restart
                if online:
                    try:
                        sm.send_command("say [VoHost] Scheduled restart in 60 seconds", server=s)
                    except Exception:
                        pass
                    if warn_seconds > 0:
                        _t.sleep(warn_seconds)
                    r = sm.action("restart", server_id=sid, server=s)
                    ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
                    note = "restarted"
                else:
                    r = sm.action("start", server_id=sid, server=s)
                    ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
                    note = "was stopped - started"
        except Exception as e:
            ok, note = False, f"failed: {e}"[:160]
        _record(sid, action, ok, note, now)
        done.append({"server": sid, "action": action, "ok": ok, "note": note})
    return done
