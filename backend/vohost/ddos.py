"""On-box flood hardening (NOT volumetric DDoS protection — no home connection
survives a real volumetric attack; that needs upstream mitigation).

What this does, per game port + machine:
  - sysctl SYN-flood defenses (syncookies, backlog, retries)
  - iptables: max 8 concurrent connections per IP, max ~30 new conn/min per IP
    (packets only DROP over the limit; legit traffic falls through to UFW)
  - UFW SSH rate limit (brute-force bots)
Panel brute-force (login/setup) is guarded separately in app.py middleware.
Rules are re-applied at dashboard boot while enabled (iptables is not persistent).
"""
import re
import subprocess
from pathlib import Path

SYSCTL_FILE = Path("/etc/sysctl.d/99-vohost-ddos.conf")
CHAIN = "VOHOST-DDoS"
SYSCTL_CONF = (
    "net.ipv4.tcp_syncookies = 1\n"
    "net.ipv4.tcp_max_syn_backlog = 4096\n"
    "net.ipv4.tcp_syn_retries = 5\n"
    "net.ipv4.tcp_synack_retries = 3\n"
)


def _run(cmd, timeout=60):
    """Run a command, never raise. Returns (rc, output tail). Patchable in tests."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out[-2000:]
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except Exception as e:
        return 1, f"failed: {e}"[:300]


def build_rules(ports) -> list:
    """Pure: iptables argv lists, one conn-limit + one rate DROP per game port."""
    rules = []
    for p in sorted({int(x) for x in ports if str(x).isdigit()}):
        rules.append(["iptables", "-A", CHAIN, "-p", "tcp", "--dport", str(p),
                      "-m", "connlimit", "--connlimit-above", "8",
                      "--connlimit-mask", "32", "-j", "DROP"])
        rules.append(["iptables", "-A", CHAIN, "-p", "tcp", "--dport", str(p),
                      "-m", "conntrack", "--ctstate", "NEW",
                      "-m", "hashlimit", "--hashlimit-name", f"vohost-{p}",
                      "--hashlimit-mode", "srcip",
                      "--hashlimit-above", "30/min", "--hashlimit-burst", "60",
                      "-j", "DROP"])
    return rules


def apply(ports) -> dict:
    """Enable all layers. Best-effort per step, never raises."""
    log = []
    try:
        SYSCTL_FILE.parent.mkdir(parents=True, exist_ok=True)
        SYSCTL_FILE.write_text(SYSCTL_CONF)
        log.append("sysctl file written")
    except Exception as e:
        log.append(f"sysctl file skipped: {e}")
    rc, _ = _run(["sysctl", "--system"], timeout=60)
    log.append("sysctl applied" if rc == 0 else "sysctl --system unavailable")
    for mod in ("xt_connlimit", "xt_hashlimit", "nf_conntrack"):
        _run(["modprobe", mod], timeout=30)
    _run(["iptables", "-N", CHAIN], timeout=30)
    _run(["iptables", "-F", CHAIN], timeout=30)
    rc, _ = _run(["iptables", "-C", "INPUT", "-j", CHAIN], timeout=30)
    if rc != 0:
        _run(["iptables", "-I", "INPUT", "1", "-j", CHAIN], timeout=30)
        log.append("chain hooked into INPUT")
    else:
        log.append("chain already hooked")
    rules = build_rules(ports)
    for r in rules:
        _run(r, timeout=30)
    log.append(f"{len(rules)} port rules applied")
    rc, _ = _run(["ufw", "limit", "22/tcp"], timeout=60)
    log.append("ufw ssh limit on" if rc == 0 else "ufw ssh limit skipped")
    return {"ok": True, "log": log}


def remove() -> dict:
    """Disable all layers. Best-effort, never raises."""
    log = []
    _run(["iptables", "-D", "INPUT", "-j", CHAIN], timeout=30)
    _run(["iptables", "-F", CHAIN], timeout=30)
    _run(["iptables", "-X", CHAIN], timeout=30)
    log.append("iptables chain removed")
    try:
        SYSCTL_FILE.unlink(missing_ok=True)
        log.append("sysctl file removed")
    except Exception as e:
        log.append(f"sysctl file kept: {e}")
    _run(["sysctl", "--system"], timeout=60)
    _run(["ufw", "--force", "delete", "limit", "22/tcp"], timeout=60)
    return {"ok": True, "log": log}


def status() -> dict:
    """Probe current state. Never raises."""
    try:
        sysctl_on = SYSCTL_FILE.exists()
    except Exception:
        sysctl_on = False
    rc, _ = _run(["iptables", "-C", "INPUT", "-j", CHAIN], timeout=30)
    rc2, out2 = _run(["ufw", "status"], timeout=30)
    return {"sysctl": bool(sysctl_on),
            "chain": rc == 0,
            "ufw_ssh": bool(re.search(r"22/tcp.*LIMIT", out2 or "", re.IGNORECASE)),
            "login_guard": True}
