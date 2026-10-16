"""Simple Voice Chat one-click install (Paper-family servers).

Fetches the newest Modrinth paper build for the server's MC version into
plugins/, opens the UDP voice port in UFW, and pins port=24454 in the
plugin config when it already exists (fresh installs default to 24454).
Router UDP port-forward is still the user's job — the note says so.
"""
import subprocess
from pathlib import Path

from . import mod_providers as MP

SLUG = "simple-voice-chat"
PORT = 24454
PAPER_LOADERS = ("paper", "purpur", "spigot")


def _dl(url: str) -> bytes:
    import requests as R
    r = R.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def fetch(mc, download=None):
    """Newest strict-compatible paper build. Returns (filename, bytes, number, mc_list)."""
    vs = MP.modrinth_versions(SLUG, "paper", mc or None, strict=True)
    if not vs:
        raise LookupError(f"No Simple Voice Chat paper build for MC {mc or '?'} on Modrinth.")
    v = vs[0]
    files = v.get("files") or []
    if not files or not files[0].get("url"):
        raise LookupError("Simple Voice Chat version has no downloadable file.")
    data = (download or _dl)(files[0]["url"])
    return files[0].get("filename", "simple-voice-chat.jar"), data, v.get("number", "?"), v.get("mc") or []


def open_udp(port=PORT, run=None):
    """Allow the voice UDP port in UFW. Never raises; returns True/False."""
    try:
        runner = run or (lambda c: subprocess.run(c, capture_output=True, timeout=30).returncode)
        return runner(["ufw", "allow", f"{port}/udp"]) == 0
    except Exception:
        return False


def ensure_port(sdir, port=PORT) -> bool:
    """Pin port= in plugins/voicechat/voicechat-server.properties if it exists."""
    try:
        cfg = Path(sdir) / "plugins" / "voicechat" / "voicechat-server.properties"
        if not cfg.exists():
            return False
        out = []
        seen = False
        for line in cfg.read_text(errors="replace").splitlines():
            if line.strip().startswith("port="):
                out.append(f"port={port}")
                seen = True
            else:
                out.append(line)
        if not seen:
            out.append(f"port={port}")
        cfg.write_text("\n".join(out) + "\n")
        return True
    except Exception:
        return False
