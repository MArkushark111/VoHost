"""playit.gg tunnel: auto-install the agent, manage its service, claim flow, per-server public address.

Verified against playit docs/repo: APT package `playit`, systemd unit
`playit.service` (runs /opt/playit/playitd as user `playit`, secret in
/etc/playit/playit.toml), `playit setup` prints the claim link.

Automation boundary (honest): install/service/claim-link are automatic.
The playit.gg account login (claim click) and the TCP-tunnel creation on
their site need the user; the panel detects state and stores the pasted
public address, which then becomes THE connect address everywhere.
"""
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from .config import DATA

UNIT = "playit"
SECRET_FILE = Path("/etc/playit/playit.toml")
SERVICE_LOG = Path("/var/log/playit/playit.log")
APT_KEY_URL = "https://playit-cloud.github.io/ppa/key.gpg"
APT_KEY_DST = Path("/etc/apt/trusted.gpg.d/playit.gpg")
APT_SRC_DST = Path("/etc/apt/sources.list.d/playit-cloud.list")
APT_SRC_LINE = "deb [signed-by=/etc/apt/trusted.gpg.d/playit.gpg] https://playit-cloud.github.io/ppa/data ./"
CLAIM_RE = re.compile(r"https://playit\.gg/claim/[A-Za-z0-9_-]+")
URL_RE = re.compile(r"https?://[^\s'\"]*playit\.gg[^\s'\"]*")
SECRET_RE = re.compile(r"secret\s*[=:]\s*[\"']([^\"']+)[\"']")
ADDR_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}(:\d{1,5})?$")
STATE = DATA / "tunnel.json"


def _run(cmd, timeout=60, data=None, env=None):
    """Run a command, never raise. Returns (rc, output tail). Patchable in tests."""
    import os as _os
    try:
        e = dict(_os.environ)
        if env:
            e.update(env)
        kw = {"capture_output": True, "timeout": timeout, "env": e}
        if data is None:
            kw["stdin"] = subprocess.DEVNULL
        else:
            kw["input"] = data
        p = subprocess.run(cmd, **kw)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out[-4000:]
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired as ex:
        tail = ((ex.stdout or b"") + (ex.stderr or b"")).decode("utf-8", "replace")
        return 124, f"timed out after {timeout}s\n{tail[-2000:]}"
    except Exception as ex:
        return 1, f"failed: {ex}"[:500]


def _fetch(url, timeout=30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "VoHost/1.0 (+https://github.com/MArkushark111/VoHost)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save_state(st: dict):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=2))
    except Exception:
        pass


def valid_addr(raw: str) -> str:
    """Normalize a pasted tunnel address ('host:port'); '' when invalid/empty."""
    a = (raw or "").strip()
    if not a:
        return ""
    return a if ADDR_RE.fullmatch(a) else ""


def installed() -> bool:
    try:
        import shutil as _sh
        if _sh.which("playit") or Path("/opt/playit/playitd").exists():
            return True
        rc, _ = _run(["systemctl", "cat", UNIT], timeout=15)
        return rc == 0
    except Exception:
        return False


def service() -> dict:
    rc, out = _run(["systemctl", "is-active", UNIT], timeout=15)
    active = out.strip().splitlines()[0].strip() if out.strip() else "unknown"
    rc2, out2 = _run(["systemctl", "is-enabled", UNIT], timeout=15)
    enabled = out2.strip().splitlines()[0].strip() if out2.strip() else "unknown"
    return {"active": active, "enabled": enabled, "running": active == "active"}


def claimed() -> bool:
    """True once the agent holds a secret (claim completed). Never raises."""
    try:
        raw = SECRET_FILE.read_text(errors="replace")
        m = SECRET_RE.search(raw)
        if m and len(m.group(1).strip()) >= 8:
            return True
        return len(raw.strip()) > 100 and "secret" in raw.lower()
    except Exception:
        return False


def _scrape_claim(text: str) -> str:
    m = CLAIM_RE.search(text or "")
    if m:
        return m.group(0)
    m = URL_RE.search(text or "")
    return m.group(0) if m else ""


def claim_flow() -> dict:
    """Ensure the agent runs, then hunt the claim link (setup output + logs)."""
    _run(["systemctl", "start", UNIT], timeout=60)
    blob = ""
    rc, out = _run(["playit", "setup"], timeout=25)
    blob += out + "\n"
    rc, out = _run(["journalctl", "-u", UNIT, "--no-pager", "-n", "100"], timeout=20)
    blob += out + "\n"
    try:
        if SERVICE_LOG.exists():
            tail = SERVICE_LOG.read_bytes()[-6000:].decode("utf-8", "replace")
            blob += tail
    except Exception:
        pass
    url = _scrape_claim(blob)
    done = claimed()
    if done:
        return {"ok": True, "claimed": True, "claim_url": "",
                "message": "agent is claimed and linked to your playit.gg account"}
    if url:
        return {"ok": True, "claimed": False, "claim_url": url,
                "message": "open the claim link, log in to playit.gg — then press Get claim link again to verify"}
    return {"ok": False, "claimed": False, "claim_url": "",
            "message": "no claim link found — is the agent installed and started? (Install, then Start, then try again)"}


def _dearmor(key: bytes) -> bytes:
    """GPG-dearmor the APT key, binary-safe. Patchable in tests."""
    import subprocess as _sp
    p = _sp.run(["gpg", "--dearmor"], input=key, capture_output=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("gpg --dearmor failed: " + (p.stderr or b"")[-300:].decode("utf-8", "replace"))
    return p.stdout


def _log(msg: str):
    st = _state()
    ins = st.get("install") or {}
    lines = ins.get("log", [])
    lines.append(msg)
    ins.update({"log": lines[-40:]})
    st["install"] = ins
    _save_state(st)


def _do_install():
    """Blocking APT install worker. Records progress to the state file."""
    st = _state()
    st["install"] = {"running": True, "ok": False, "log": [], "ts": time.time()}
    _save_state(st)
    try:
        _log("$ fetch playit APT key")
        try:
            key = _fetch(APT_KEY_URL)
        except Exception as e:
            _log(f"key download failed: {e}")
            raise RuntimeError("could not download the playit APT key (no network?)")
        _log("$ gpg --dearmor key")
        rc, out = _run(["gpg", "--version"], timeout=30)
        if rc != 0:
            _log("$ gpg missing — installing gnupg first")
            _run(["apt-get", "update"], timeout=240)
            rc2, out2 = _run(["apt-get", "install", "-y", "gnupg"], timeout=300,
                              env={"DEBIAN_FRONTEND": "noninteractive"})
            _log(out2[-300:])
        # binary-safe dearmor (the armored key must not pass through text decoding)
        try:
            APT_KEY_DST.parent.mkdir(parents=True, exist_ok=True)
            APT_KEY_DST.write_bytes(_dearmor(key))
        except FileNotFoundError:
            raise RuntimeError("gpg is not installed and could not be installed")
        _log("$ add APT source")
        APT_SRC_DST.parent.mkdir(parents=True, exist_ok=True)
        APT_SRC_DST.write_text(APT_SRC_LINE + "\n")
        _log("$ apt-get update")
        rc, out = _run(["apt-get", "update"], timeout=300)
        _log(out[-500:])
        if rc != 0:
            raise RuntimeError("apt-get update failed")
        _log("$ apt-get install -y playit  (takes a minute)")
        rc, out = _run(["apt-get", "install", "-y", "playit"], timeout=600,
                       env={"DEBIAN_FRONTEND": "noninteractive"})
        _log(out[-800:])
        if rc != 0:
            raise RuntimeError("apt-get install playit failed")
        _log("$ systemctl enable --now playit")
        _run(["systemctl", "enable", UNIT], timeout=60)
        rc, out = _run(["systemctl", "start", UNIT], timeout=60)
        _log(out[-300:] or "service start issued")
        st = _state()
        st["install"] = {"running": False, "ok": True, "log": (st.get("install") or {}).get("log", [])[-40:],
                         "ts": time.time()}
        _save_state(st)
    except Exception as e:
        _log(f"INSTALL FAILED: {e}")
        st = _state()
        ins = st.get("install") or {}
        ins.update({"running": False, "ok": False, "ts": time.time()})
        st["install"] = ins
        _save_state(st)


def start_install() -> dict:
    st = _state()
    if (st.get("install") or {}).get("running"):
        return {"ok": True, "started": False, "note": "install already running"}
    threading.Thread(target=_do_install, daemon=True).start()
    return {"ok": True, "started": True, "note": "installing playit agent in the background — watch status here"}


def status(server: dict | None = None) -> dict:
    srv = server or {}
    return {"installed": installed(), "service": service(), "claimed": claimed(),
            "addr": (srv.get("playit_addr") or "").strip(),
            "mc_port": srv.get("port", 25565),
            "install": _state().get("install") or {"running": False, "ok": False, "log": []}}
