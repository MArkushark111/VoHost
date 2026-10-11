"""DuckDNS auto-subdomain: keep <name>.duckdns.org pointed at the home WAN IP.

Free names from https://www.duckdns.org (log in, copy the token). The first
successful update registers the name if nobody else took it.
Update API: GET https://www.duckdns.org/update?domains=D&token=T&ip=I -> "OK"|"KO".
"""
import json
import re
import socket
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import DATA

STATE_FILE = DATA / "duckdns.json"
UPDATE_URL = "https://www.duckdns.org/update"
SYNC_EVERY = 600  # background re-check interval, seconds
RESOLVE_TIMEOUT = 10

DOMAIN_RE = re.compile(r"^[a-z0-9-]{1,63}$")


def normalize_domain(raw: str) -> str:
    """'VoSMP ' / 'vosmp.duckdns.org' -> 'vosmp'; '' when invalid."""
    d = (raw or "").strip().lower()
    if d.endswith(".duckdns.org"):
        d = d[: -len(".duckdns.org")]
    d = d.strip().strip(".")
    return d if DOMAIN_RE.fullmatch(d) else ""


def fqdn(domain: str) -> str:
    return (domain or "").strip().lower() + ".duckdns.org"


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "VoHost/1.0 (+https://github.com/MArkushark111/VoHost)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace").strip()


def update(domain: str, token: str, ip: str, http_get=None) -> tuple:
    """Push one DuckDNS name at an IP. Returns (ok: bool, message: str)."""
    domain = normalize_domain(domain)
    if not domain:
        return False, "invalid subdomain (a-z, 0-9, dash)"
    if not (token or "").strip():
        return False, "missing DuckDNS token"
    if not (ip or "").strip():
        return False, "no WAN IP known yet"
    q = urllib.parse.urlencode({"domains": domain, "token": token.strip(), "ip": ip.strip(), "verbose": "true"})
    try:
        body = (http_get or _http_get)(UPDATE_URL + "?" + q)
    except Exception as e:
        return False, f"update request failed: {e}"[:160]
    if body.startswith("OK"):
        return True, f"{fqdn(domain)} now points at {ip.strip()}"
    return False, f"DuckDNS refused (KO — bad token or name taken): {body[:80]}"


def resolve(domain: str) -> str:
    """Current DNS answer for the name, '' on any failure. Bounded, never raises."""
    domain = normalize_domain(domain)
    if not domain:
        return ""
    try:
        fut = ThreadPoolExecutor(max_workers=1).submit(socket.gethostbyname, fqdn(domain))
        return fut.result(timeout=RESOLVE_TIMEOUT)
    except Exception:
        return ""


def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(st: dict):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st, indent=2))
    except Exception:
        pass


def last_status(sid: str) -> dict | None:
    return _state().get(sid)


def record(sid: str, domain: str, ok: bool, ip: str, message: str) -> dict:
    st = _state()
    st[sid] = {"domain": domain, "ok": bool(ok), "ip": ip, "message": message[:200], "ts": time.time()}
    _save_state(st)
    return st[sid]


def sync_server(server: dict, wan_ip: str, token: str, force: bool = False) -> dict:
    """Bring one server's DuckDNS name up to date. Never raises."""
    sid = (server or {}).get("id", "")
    domain = normalize_domain((server or {}).get("duckdns_domain", ""))
    if not domain:
        return {"ok": False, "skipped": True, "message": "no subdomain set"}
    if not (token or "").strip():
        rec = record(sid, domain, False, wan_ip or "", "missing DuckDNS token")
        rec["skipped"] = True
        return rec
    if not (wan_ip or "").strip():
        rec = record(sid, domain, False, "", "no WAN IP known yet")
        rec["skipped"] = True
        return rec
    prev = _state().get(sid) or {}
    if not force and prev.get("ok") and prev.get("ip") == wan_ip and prev.get("domain") == domain:
        if resolve(domain) == wan_ip:
            return dict(prev, skipped=True, message=f"{fqdn(domain)} already points at {wan_ip}")
    ok, msg = update(domain, token, wan_ip)
    rec = record(sid, domain, ok, wan_ip, msg)
    return rec


def run_due(get_wan, get_token):
    """Sync every server that has a subdomain configured. Never raises."""
    try:
        from . import servers as SV
        servers = SV.list_servers()
    except Exception:
        return
    if not any(normalize_domain((s or {}).get("duckdns_domain", "")) for s in servers):
        return
    try:
        token = get_token()
    except Exception:
        token = ""
    if not (token or "").strip():
        return
    try:
        wan = get_wan()
    except Exception:
        wan = ""
    for s in servers:
        try:
            if normalize_domain((s or {}).get("duckdns_domain", "")):
                sync_server(s, wan or "", token)
        except Exception:
            pass


def start_loop(get_wan, get_token):
    """Background loop the dashboard runs at boot. Re-checks every 10 min."""
    import time as _t
    while True:
        try:
            run_due(get_wan, get_token)
        except Exception:
            pass
        _t.sleep(SYNC_EVERY)
