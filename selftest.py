"""Boot the real app against a temp VOHOST_BASE and exercise every endpoint the UI calls, no MC required."""
import os, tempfile, json, sys
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
tmp = tempfile.mkdtemp(prefix="vh-test-")
os.environ["VOHOST_BASE"] = tmp
from fastapi.testclient import TestClient
import app as A

# point OS-level side effects at temp (create-server hook may apply flood rules)
from vohost import ddos as _DP0
_DP0.SYSCTL_FILE = Path(tempfile.mkdtemp(prefix="vh-ddos-")) / "99-vohost-ddos.conf"

errors = []
def check(label, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + label + (("  " + str(extra)) if extra and not ok else ""))
    if not ok:
        errors.append(label)

c = TestClient(A.app)

# 1. setup flow
r = c.get("/api/setup-state"); check("setup-state", r.status_code == 200 and r.json().get("needs_setup") is True, r.text)
r = c.post("/api/setup", json={"username": "admin", "password": "Vohost123"})
check("setup create", r.status_code == 200 and r.json().get("user", {}).get("role") == "admin", r.text)
tok = c.headers  # cookies set on client via TestClient

# 2. login with the created user
r = c.post("/api/login", json={"username": "admin", "password": "Vohost123"})
check("login good", r.status_code == 200, r.text)
r = c.post("/api/login", json={"username": "admin", "password": "wrong"})
check("login bad rejected", r.status_code == 401, r.text)

# 3. setup now forbidden
r = c.post("/api/setup", json={"username": "x", "password": "xxxxx"})
check("setup locked after users", r.status_code == 403, r.text)

# 4. authed endpoints with token
r = c.get("/api/servers"); check("servers list", r.status_code == 200, r.text)
r = c.get("/api/software/loaders"); check("loaders", r.status_code == 200, r.text)
r = c.get("/api/catalog/installed?kind=mod"); check("installed", r.status_code == 200, r.text)
r = c.get("/api/options"); check("options", r.status_code == 200, r.text)
r = c.get("/api/files?path="); check("files", r.status_code == 200, r.text)
r = c.get("/api/worlds"); check("worlds", r.status_code == 200, r.text)
r = c.get("/api/players/seen"); check("players seen", r.status_code == 200, r.text)
r = c.get("/api/players/online"); check("players online", r.status_code == 200, r.text)
r = c.get("/api/backups"); check("backups", r.status_code == 200, r.text)
r = c.get("/api/users"); check("users", r.status_code == 200, r.text)
r = c.post("/api/servers", json={"name": "test1", "network_mode": "lan", "memory_max": "2G"})
check("create server", r.status_code == 200, r.text)
sid = r.json().get("server", {}).get("id", "")
r = c.get("/api/status?server_id=" + sid); check("status per-server", r.status_code == 200, r.text)

# 4b. new features
r = c.get("/api/players/lists?server_id=" + sid)
check("players lists", r.status_code == 200 and "whitelist" in r.json() and "bans" in r.json(), r.text)
r = c.post("/api/players/lists", json={"server_id": sid, "op": "whitelist-add", "name": "testplayer"})
check("whitelist add", r.status_code == 200 and r.json().get("ok"), r.text)
r = c.get("/api/files/content?path=server.properties&server_id=" + sid)
check("file content", r.status_code == 200 and "server-port" in r.json().get("text", ""), r.text)
r = c.post("/api/files/content", json={"server_id": sid, "path": "server.properties", "text": "motd=selftest motd\n"})
check("file content save", r.status_code == 200, r.text)
from vohost.servers import server_dir as _sdir0
_dd = _sdir0(sid) / "delfolder"; (_dd / "sub").mkdir(parents=True, exist_ok=True)
(_dd / "sub" / "f.txt").write_text("x")
r = c.post("/api/files/delete", json={"server_id": sid, "path": "delfolder"})
check("folder delete recursive", r.status_code == 200 and not _dd.exists(), r.text)
r = c.post("/api/files/delete", json={"server_id": sid, "path": ""})
check("server root delete refused", r.status_code == 400, r.text[:120])
r = c.post("/api/backups", json={"server_id": sid, "label": "selftest"})
check("backup create", r.status_code == 200 and r.json().get("file"), r.text)
r = c.get("/api/backups?server_id=" + sid)
check("backup list per-server", r.status_code == 200 and len(r.json().get("backups", [])) >= 1, r.text)
r = c.put("/api/backups/settings", json={"server_id": sid, "enabled": True, "mode": "daily", "hour": 4, "minute": 0, "keep": 5})
check("backup settings save", r.status_code == 200 and r.json().get("schedule", {}).get("enabled") is True, r.text)
r = c.put("/api/options", json={"server_id": sid, "memory_max": "3G", "cpu_cores": 2, "public_page": True, "props": {}})
check("options memory/cpu", r.status_code == 200, r.text)
r = c.get("/api/options?server_id=" + sid)
check("options memory read", r.status_code == 200 and r.json().get("memory", {}).get("max") == "3G" and r.json().get("cpu_cores") == 2, r.text)
r = c.get("/api/public/" + sid)
check("public api", r.status_code == 200 and r.json().get("id") == sid, r.text)
r = c.get("/public/" + sid)
check("public page html", r.status_code == 200 and sid in r.text, r.text[:80])
r = c.get("/api/catalog/installed?server_id=" + sid)
check("installed (update-aware)", r.status_code == 200 and "installed" in r.json(), r.text)

# 4c. player profile + inventory editing endpoints
r = c.get("/api/players/data?uuid=nobody-0000-0000-0000-000000000000&server_id=" + sid)
check("player profile (missing player handled)", r.status_code == 200 and "error" in r.json(), r.text)
r = c.post("/api/players/item/delete", json={})
check("item delete guards", r.status_code == 400, r.text)
r = c.post("/api/players/item/clear", json={"uuid": "nobody-0000-0000-0000-000000000000", "server_id": sid})
check("item clear missing player 404", r.status_code == 404, r.text)
r = c.put("/api/options", json={"server_id": sid, "props": {"keepInventory": "true", "enable-command-block": "true"}})
check("keepInventory toggle saved", r.status_code == 200, r.text)
r = c.put("/api/options", json={"server_id": sid, "props": {"motd": "&lSmall &c&kAAAA"}})
check("motd save with & codes", r.status_code == 200, r.text)

# 4d. usernames resolve via usercache.json even with no bukkit NBT tag (vanilla/Fabric)
from vohost.servers import server_dir as _sdir
import nbtlib
from nbtlib.tag import Compound, List, Int, String, Byte
sd = _sdir(sid)
_motd_txt = (sd / "server.properties").read_text()
check("motd &->section conversion stored", "\u00a7lSmall \u00a7c\u00a7kAAAA" in _motd_txt and "&lSmall" not in _motd_txt, _motd_txt[:200])
# 4d2. cracked mode: online-mode=false always implies enforce-secure-profile=false
r = c.put("/api/options", json={"server_id": sid, "props": {"online-mode": "false"}})
_pr = (sd / "server.properties").read_text()
check("cracked guard forces secure-profile off",
      r.status_code == 200 and "online-mode=false" in _pr and "enforce-secure-profile=false" in _pr
      and "cracked clients" in r.json().get("note", ""), r.text[:200])
r = c.put("/api/options", json={"server_id": sid, "props": {"online-mode": "false", "enforce-secure-profile": "false"}})
check("full cracked save persists", r.status_code == 200
      and "online-mode=false" in (sd / "server.properties").read_text()
      and "enforce-secure-profile=false" in (sd / "server.properties").read_text(), r.text[:200])
A.seed_start_rcon({"id": sid, "rcon_port": 25575}, sd)
_pr2 = (sd / "server.properties").read_text()
check("server start seed keeps cracked mode",
      "online-mode=false" in _pr2 and "enforce-secure-profile=false" in _pr2, _pr2[:200])
r = c.put("/api/options", json={"server_id": sid, "props": {"online-mode": "true", "enforce-secure-profile": "true"}})
check("premium-only restore ok", r.status_code == 200
      and "online-mode=true" in (sd / "server.properties").read_text(), r.text[:200])

# 4d3. DuckDNS subdomain: normalize/update paths + API round-trip (no live token needed)
from vohost import duckdns as _DD
check("duckdns normalize", _DD.normalize_domain(" VoSMP.duckdns.org ") == "vosmp"
      and _DD.normalize_domain("bad name!") == "" and _DD.fqdn("vosmp") == "vosmp.duckdns.org", "")
_seen = {}
def _fake_ok(u):
    _seen["url"] = u
    return "OK\n1.2.3.4"
def _boom(u):
    raise RuntimeError("down")
ok, _m = _DD.update("vosmp", "tok", "1.2.3.4", http_get=_fake_ok)
check("duckdns update OK path", ok is True and "domains=vosmp" in _seen.get("url", "")
      and "token=tok" in _seen["url"] and "ip=1.2.3.4" in _seen["url"], _seen.get("url", ""))
ok, _m = _DD.update("vosmp", "tok", "1.2.3.4", http_get=lambda u: "KO")
check("duckdns update KO path", ok is False, "")
ok, _m = _DD.update("vosmp", "tok", "1.2.3.4", http_get=_boom)
check("duckdns update exception path", ok is False, "")
check("duckdns resolve invalid", _DD.resolve("bad name!") == "", "")
r = c.put("/api/subdomain", json={"server_id": sid, "domain": " TestSub123 ", "token": "tok-bogus"})
j = r.json() if r.status_code == 200 else {}
check("subdomain save normalizes", r.status_code == 200 and j.get("domain") == "testsub123"
      and j.get("hostname") == "testsub123.duckdns.org" and j.get("token_set") is True
      and isinstance(j.get("sync"), dict) and j["sync"].get("ok") is False, r.text[:250])
r = c.get("/api/subdomain?server_id=" + sid)
j = r.json() if r.status_code == 200 else {}
check("subdomain read (no token leak)", r.status_code == 200 and j.get("domain") == "testsub123"
      and j.get("token_set") is True and "tok-bogus" not in r.text, r.text[:200])
r = c.get("/api/status?server_id=" + sid)
check("status carries hostname", r.status_code == 200 and r.json().get("hostname") == "testsub123.duckdns.org", r.text[:150])
r = c.get("/api/public/" + sid)
check("public api carries hostname", r.status_code == 200 and r.json().get("hostname") == "testsub123.duckdns.org", r.text[:150])
r = c.put("/api/subdomain", json={"server_id": sid, "domain": "bad name!"})
check("subdomain invalid rejected", r.status_code == 400, r.text[:120])
r = c.put("/api/subdomain", json={"server_id": sid, "domain": ""})
check("subdomain cleared", r.status_code == 200 and r.json().get("domain") == "" and r.json().get("hostname") == "", r.text[:150])
(pd := sd / "world" / "playerdata").mkdir(parents=True, exist_ok=True)
puuid = "54aaa8c9-aa2e-4d12-be3e-6f7691913855"
_nf = nbtlib.File(Compound({"Health": Int(20)}), gzipped=True)
_nf["Inventory"] = List[Compound]([Compound({"id": String("minecraft:dirt"), "Count": Byte(3), "Slot": Int(0)})])
_nf.save(str(pd / (puuid + ".dat")))
(sd / "usercache.json").write_text(json.dumps([{"name": "Markusha111", "uuid": puuid}]))
r = c.get("/api/players/seen?server_id=" + sid)
names = {p["uuid"]: p.get("name") for p in r.json().get("players", [])}
check("seen resolves usercache name", names.get(puuid) == "Markusha111", r.text)
r = c.get("/api/players/data?uuid=" + puuid + "&server_id=" + sid)
check("profile resolves usercache name", r.json().get("name") == "Markusha111", r.text)

# 4e. fake RCON server: proves the framing fix (used to fail 'auth read failed:
# timed out') and that a leading '/' is stripped before sending
import socket as _s, struct as _st, threading as _th
box = {}
fsrv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
fsrv.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
fsrv.bind(("127.0.0.1", 0)); fsrv.listen(5)
fport = fsrv.getsockname()[1]
def _fake():
    try:
        for _ in range(5):
            try:
                cc, _ = fsrv.accept()
            except Exception:
                return
            cc.settimeout(8)
            try:
                hdr = cc.recv(12)
                if len(hdr) < 12:
                    cc.close()  # tcp probe: connect+close, no data
                    continue
                ln, rid, typ = _st.unpack("<iii", hdr)
                body = b""
                while len(body) < ln - 8:
                    ch = cc.recv(ln - 8 - len(body))
                    if not ch:
                        break
                    body += ch
                cc.sendall(_st.pack("<iii", 10, rid, 2) + b"\x00\x00")
                hdr2 = cc.recv(12)
                ln2, rid2, typ2 = _st.unpack("<iii", hdr2)
                body2 = b""
                while len(body2) < ln2 - 8:
                    ch = cc.recv(ln2 - 8 - len(body2))
                    if not ch:
                        break
                    body2 += ch
                box["cmd"] = body2[:-2].decode()
                out = ("got:" + box["cmd"]).encode() + b"\x00\x00"
                cc.sendall(_st.pack("<iii", len(out) + 8, rid2, 0) + out)
            except Exception as e:
                box.setdefault("err", str(e))
            try:
                cc.close()
            except Exception:
                pass
    finally:
        try:
            fsrv.close()
        except Exception:
            pass
_th.Thread(target=_fake, daemon=True).start()
(sd / "server.properties").write_text(
    f"enable-rcon=true\nrcon.port={fport}\nrcon.password=vohost-rcon\nserver-port=25565\n")
import vohost.server_manager as _SM
r = _SM.send_command("/gamemode creative Markusha111", server_id=sid)
check("rcon roundtrip + slash stripped", r.get("ok") is True and box.get("cmd") == "gamemode creative Markusha111",
      json.dumps(r) + " " + json.dumps(box))
r = c.get("/api/rcon/diag?server_id=" + sid)
check("rcon diag healthy", r.status_code == 200 and r.json().get("auth", {}).get("ok") is True
      and "healthy" in r.json().get("suggestion", ""), r.text)

# 4f. software switch: backup -> download -> wipe (world/mods/jar gone, config kept)
(sd / "world").mkdir(exist_ok=True)
(sd / "world" / "level.dat").write_bytes(b"fake-level")
(sd / "mods").mkdir(exist_ok=True)
(sd / "mods" / "a.jar").write_bytes(b"fake-mod")
(sd / "server.jar").write_bytes(b"fake-jar")
(sd / "eula.txt").write_text("eula=true\n")
r = c.post("/api/backups", json={"server_id": sid, "label": "pre-switch"})
bkfile = r.json().get("file", "")
check("pre-switch backup created", r.status_code == 200 and bkfile.endswith(".zip"), r.text)
r = c.get("/api/backups/download?file=" + bkfile + "&server_id=" + sid)
check("backup downloads as zip", r.status_code == 200 and "zip" in r.headers.get("content-type", ""), ascii(r.text[:200]))
r = c.get("/api/backups/download?file=../app.py&server_id=" + sid)
check("backup download traversal rejected", r.status_code == 404, r.text[:200])
r = c.post("/api/software/install", json={"server_id": sid, "loader": "fabric", "mc_version": "1.21.4",
                                           "loader_version": "latest", "wipe": True})
check("software switch with wipe ok", r.status_code == 200 and "Wiped the server folder" in r.json().get("note", ""), r.text[:300])
check("wipe removed world/mods/jar", not (sd / "world").exists() and not (sd / "mods").exists()
      and not (sd / "server.jar").exists(), "leftovers present")
check("wipe kept server.properties+eula", (sd / "server.properties").exists() and (sd / "eula.txt").exists(),
      "config files missing")

r = c.get("/"); check("index page", r.status_code == 200 and "VoHost" in r.text, r.text[:100])
check("index cache-busts assets", "/assets/style.css?v=" in r.text and "/assets/app.js?v=" in r.text, r.text[:200])
r = c.get("/assets/style.css?v=123"); check("assets with query still served", r.status_code == 200, str(r.status_code))
r = c.get("/assets/app.js"); check("assets js", r.status_code == 200, r.text[:60])
r = c.get("/assets/style.css"); check("assets css", r.status_code == 200, r.text[:40])
check("assets served no-cache", "no-cache" in c.get("/assets/style.css").headers.get("cache-control", "").lower(),
      c.get("/assets/style.css").headers.get("cache-control", ""))
_theme = c.get("/assets/style.css").text
check("theme dark gray (no blue bg)", "#151619" in _theme and "#1b2634" not in _theme, _theme[:120])

# 4g. Minecraft legacy formatting (&c &l &k ...) wired into name/MOTD renders
_js = A.FRONT.joinpath("app.js").read_text() if A.FRONT.joinpath("app.js").exists() else ""
check("mcFmt helper + obf slot present", "function mcFmt(" in _js and "mc-obf" in _js and "data-t=" in _js, "")
check("server name/MOTD rendered via mcFmt",
      "mcFmt(CURSRV.name" in _js and "mcFmt((s.props" in _js and "mcFmt(s.name)" in _js, "")
check("public page formats name/motd", "function fmt(" in A.PUBLIC_HTML and "mc-obf" in A.PUBLIC_HTML
      and A.PUBLIC_HTML.count("innerHTML=fmt(") >= 2, "")

# 5. unauth guards
c2 = TestClient(A.app)
r = c2.get("/api/servers"); check("unauth 401", r.status_code == 401, r.text)

# 6. DDoS/flood protection: rules, API, login brute-force guard
rules = _DP0.build_rules([25565, "abc", 25565])
flat = [" ".join(r) for r in rules]
check("ddos rules pure", len(rules) == 2 and any("--connlimit-above 8" in f for f in flat)
      and any("--hashlimit-above 30/min" in f for f in flat)
      and all("--dport 25565" in f for f in flat)
      and any("-j RETURN" in f or "-j DROP" in f for f in flat)
      and not any("-j ACCEPT" in f for f in flat), json.dumps(rules)[:200])
_seen_cmds = []
_orig_run = _DP0._run
def _fake_run(cmd, timeout=60):
    _seen_cmds.append(cmd)
    if cmd[:2] == ["ufw", "status"]:
        return 0, "22/tcp LIMIT Anywhere"
    return 0, "ok"
_DP0._run = _fake_run
res = _DP0.apply([25565])
check("ddos apply faked", res.get("ok") is True and _DP0.SYSCTL_FILE.exists()
      and "syncookies" in _DP0.SYSCTL_FILE.read_text()
      and any(c[:3] == ["iptables", "-N", _DP0.CHAIN] for c in _seen_cmds)
      and sum(1 for c in _seen_cmds if c[:2] == ["iptables", "-A"]) == 2, json.dumps(res)[:200])
st = _DP0.status()
check("ddos status faked", st.get("sysctl") is True and st.get("chain") is True and st.get("ufw_ssh") is True, json.dumps(st))
r = c.put("/api/security", json={"enabled": True})
check("security enable", r.status_code == 200 and r.json().get("enabled") is True, r.text[:200])
r = c.get("/api/security")
check("security read", r.status_code == 200 and r.json().get("enabled") is True and "sysctl" in r.json(), r.text[:200])
r = c.put("/api/security", json={"enabled": False})
check("security disable", r.status_code == 200 and r.json().get("enabled") is False
      and not _DP0.SYSCTL_FILE.exists(), r.text[:200])
_DP0._run = _orig_run

# 7. login brute-force guard: hammer bad passwords -> 429, normal traffic unaffected
codes = []
for _ in range(12):
    rr = c.post("/api/login", json={"username": "admin", "password": "wrong-spam"})
    codes.append(rr.status_code)
check("login spam locked out", codes[-1] == 429 and 401 in codes, json.dumps(codes))
r = c.get("/api/servers"); check("guard spares normal endpoints", r.status_code == 200, r.text[:80])

# 8. push limits mode: machine-derived max resources, prev stash + restore
r = c.get("/api/push-limits?server_id=" + sid)
j = r.json() if r.status_code == 200 else {}
check("push-limits read", r.status_code == 200 and j.get("enabled") is False
      and j.get("machine", {}).get("cores", 0) >= 1 and j.get("target", {}).get("memory", "").endswith("G")
      and j.get("current", {}).get("max") == "3G", r.text[:200])
_tmem = j["target"]["memory"]
_tc = j["target"]["cores"]
r = c.post("/api/push-limits", json={"server_id": sid, "enabled": True})
j = r.json() if r.status_code == 200 else {}
_sv = j.get("server", {})
check("push-limits enable", r.status_code == 200 and j.get("enabled") is True
      and _sv.get("memory_min") == _tmem and _sv.get("memory_max") == _tmem
      and _sv.get("cpu_cores") == _tc and _sv.get("push_limits") is True
      and _sv.get("push_limits_prev") == {"min": "1G", "max": "3G", "cores": 2}, r.text[:250])
r = c.get("/api/push-limits?server_id=" + sid)
check("push-limits stays on", r.status_code == 200 and r.json().get("enabled") is True, r.text[:120])
r = c.post("/api/push-limits", json={"server_id": sid, "enabled": False})
_sv = r.json().get("server", {}) if r.status_code == 200 else {}
check("push-limits disable restores", r.status_code == 200 and r.json().get("enabled") is False
      and _sv.get("memory_min") == "1G" and _sv.get("memory_max") == "3G"
      and _sv.get("cpu_cores") == 2 and _sv.get("push_limits") is False, r.text[:250])
r = c.post("/api/push-limits", json={"server_id": "nope", "enabled": True})
check("push-limits bad server 404", r.status_code == 404, r.text[:80])
r = c2.post("/api/push-limits", json={"server_id": sid, "enabled": True})
check("push-limits unauth 401", r.status_code == 401, r.text[:80])

# 9. Simple Voice Chat one-click (Paper-family only)
r = c.post("/api/voicechat/install", json={"server_id": sid})
check("voicechat rejects vanilla", r.status_code == 400 and "paper" in r.text.lower(), r.text[:150])
r = c.put("/api/servers/" + sid, json={"loader": "paper"})
check("test server to paper", r.status_code == 200, r.text[:120])
_orig_fetch = A.VC.fetch
A.VC.fetch = lambda mc, download=None: ("voicechat-paper-2.5.jar", b"fake-vc-jar", "2.5.0", ["1.21"])
r = c.post("/api/voicechat/install", json={"server_id": sid})
check("voicechat installs", r.status_code == 200 and (sd / "plugins" / "voicechat-paper-2.5.jar").exists()
      and "24454" in r.json().get("note", ""), r.text[:250])
A.VC.fetch = _orig_fetch
_vc_cfg = sd / "plugins" / "voicechat"
_vc_cfg.mkdir(exist_ok=True)
(_vc_cfg / "voicechat-server.properties").write_text("port=12345\nfoo=bar\n")
check("voicechat port pinned", A.VC.ensure_port(sd) is True
      and "port=24454" in (_vc_cfg / "voicechat-server.properties").read_text()
      and "foo=bar" in (_vc_cfg / "voicechat-server.properties").read_text(), "")
check("voicechat udp fail-safe", A.VC.open_udp(run=lambda c: (_ for _ in ()).throw(OSError("no"))) is False
      and isinstance(A.VC.open_udp(), bool), "")

# 10. scheduled daily restart in Options + runner
r = c.put("/api/options", json={"server_id": sid, "props": {}, "restart": {"enabled": True, "at": "4pm"}})
check("restart bad time 400", r.status_code == 400, r.text[:120])
r = c.put("/api/options", json={"server_id": sid, "props": {}, "restart": {"enabled": True, "at": "04:00"}})
check("restart schedule save", r.status_code == 200, r.text[:150])
r = c.get("/api/options?server_id=" + sid)
check("restart schedule read", r.status_code == 200 and r.json().get("restart") == {"enabled": True, "at": "04:00"}, r.text[:200])
from vohost import restarts as _RT
from datetime import datetime as _dt
_now = _dt(2026, 5, 1, 4, 0)
check("restart due pure", _RT.due_servers([{"id": "x1", "restart": {"enabled": True, "at": "04:00"}},
                                          {"id": "x2", "restart": {"enabled": True, "at": "05:00"}},
                                          {"id": "x3", "restart": {"enabled": False, "at": "04:00"}}], _now)
      == [{"id": "x1", "restart": {"enabled": True, "at": "04:00"}}], "")
import time as _tmod
_hm = _tmod.strftime("%H:%M")
r = c.put("/api/options", json={"server_id": sid, "props": {}, "restart": {"enabled": True, "at": _hm}})
check("restart schedule set to now", r.status_code == 200, r.text[:120])
class _FakeSM:
    def __init__(self, online):
        self.online = online
        self.calls = []
    def service_active(self, server=None):
        return self.online
    def send_command(self, cmd, server_id="", server=None):
        self.calls.append(("say", cmd))
        return {"ok": True}
    def action(self, act, server_id="", server=None):
        self.calls.append((act, server_id))
        return {"ok": True}
_fon = _FakeSM(True)
done = _RT.run_due(sm=_fon, warn_seconds=0)
check("restart runs once online", len(done) == 1 and done[0].get("ok") is True
      and ("say", "say [VoHost] Scheduled restart in 60 seconds") in _fon.calls
      and ("restart", sid) in _fon.calls, json.dumps(done) + json.dumps(_fon.calls)[:200])
done = _RT.run_due(sm=_fon, warn_seconds=0)
check("restart no double-fire", done == [], json.dumps(done))
_st = _RT._state(); _st.pop(sid, None); _RT._save(_st)
_foff = _FakeSM(False)
done = _RT.run_due(sm=_foff, warn_seconds=0)
check("stopped server gets started", len(done) == 1 and ("start", sid) in _foff.calls
      and not any(k == "say" for k, _ in _foff.calls), json.dumps(done) + json.dumps(_foff.calls)[:200])
r = c.get("/api/options?server_id=" + sid)
check("restart last recorded", r.status_code == 200 and (r.json().get("restart_last") or {}).get("ok") is True, r.text[:200])

print()
print("ERRORS:", len(errors))
for e in errors: print("  -", e)
sys.exit(1 if errors else 0)