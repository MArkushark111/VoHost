"""VoHost dashboard backend — FastAPI, multi-server, WAN/LAN, installed mods + uninstall."""
import os, json, shutil, zipfile, base64, time, subprocess, socket, threading, re
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vohost.config import BASE, SERVER_DIR, DATA, BACKUPS, load_config, save_config, java_for_mc
from vohost import auth as A
from vohost import mc_versions as V
from vohost import mod_providers as MP
from vohost import server_manager as SM
from vohost import options_manager as OM
from vohost import nbt_players as NP
from vohost import backups_sched as BK
from vohost import duckdns as DD
from vohost import ddos as DP
from vohost import pushlimits as PL
from vohost import voicechat as VC
from vohost import restarts as RT
from vohost import servers as SV
from vohost.auth import ensure_admin, upsert_user, list_users, verify, make_token

FRONT = (Path(__file__).resolve().parent.parent / "frontend").resolve()
app = FastAPI(title="VoHost")

# ---------- helpers ----------
def user_from(req: Request):
    tok = req.cookies.get("vohost") or req.headers.get("x-token", "")
    return A.check_token(tok)

def need(req: Request, minimum="viewer"):
    u = user_from(req)
    if not A.require_role(u, minimum):
        raise HTTPException(401 if not u else 403, "login required / insufficient role")
    return u

def resolve(req: Request, server_id: str = ""):
    """Return (server_dict_or_None, sdir). Falls back to legacy single dir."""
    sid = server_id or req.query_params.get("server_id", "") or ""
    try:
        lst = SV.list_servers()
    except Exception:
        lst = []
    if not lst:
        return None, SERVER_DIR
    if not sid:
        s = lst[0]
        return s, Path(s.get("dir", str(SERVER_DIR)))
    try:
        s = SV.get_server(sid)
        return s, Path(s.get("dir", str(SERVER_DIR)))
    except KeyError:
        raise HTTPException(404, f"server {sid} not found")

def safe_join(base: Path, rel: str) -> Path:
    p = (base / (rel or "")).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise HTTPException(400, "path escapes server dir")
    return p

def sync_server_limits(sid: str):
    """Write per-server env (MC_MIN/MC_MAX, keeping the installed JAVA) + a systemd drop-in
    (CPUQuota/MemoryMax) so each server gets its own RAM/CPU limits. Best-effort."""
    try:
        s = SV.get_server(sid)
    except Exception:
        return
    env_file = DATA / f"mc-{sid}.env"
    if sid == "main":
        env_file = DATA / "mc.env"
    cur = {}
    if env_file.exists():
        for line in env_file.read_text(errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                cur[k.strip()] = v.strip()
    cur["MC_MIN"] = s.get("memory_min", "1G")
    cur["MC_MAX"] = s.get("memory_max", "4G")
    try:
        env_file.write_text("\n".join(f"{k}={v}" for k, v in cur.items()) + "\n")
    except Exception:
        pass
    try:
        if sid != "main":
            cores = int(s.get("cpu_cores") or 4)
            d = Path("/etc/systemd/system") / f"vohost-mc@{sid}.service.d"
            d.mkdir(parents=True, exist_ok=True)
            (d / "limits.conf").write_text(
                f"[Service]\nCPUQuota={cores * 100}%\nMemoryMax={s.get('memory_max', '4G')}\n")
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10)
    except Exception:
        pass

def _read_json_list(p: Path) -> list:
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []

def _write_json_list(p: Path, rows: list):
    p.write_text(json.dumps(rows, indent=2))

TEXT_EDIT_EXTS = {".txt", ".properties", ".json", ".yml", ".yaml", ".toml", ".cfg",
                  ".conf", ".sh", ".xml", ".md", ".log", ".env", ".ini", ".list"}

def _update_check(fn, kind, loader, mc):
    """Returns None (no update) or {slug, number, filename} if a newer Modrinth release exists."""
    try:
        slug = MP.slug_from_filename(fn)
        if not slug:
            return None
        latest = MP.latest_for_slug(slug, loader, mc, kind)
        if not latest or not latest["number"]:
            return None
        num = latest["number"].lower()
        fnl = fn.lower()
        hit = num in fnl
        if not hit and "+" in num:
            hit = num.split("+")[0] in fnl
        if hit:
            return None
        return {"slug": slug, "number": latest["number"], "filename": latest["filename"]}
    except Exception:
        return None

# ---------- machine IP / WAN (background-refreshed) ----------
_WAN = {"ip": "", "ts": 0.0, "busy": False}
_WAN_FILE = DATA / "wan_ip.json"
_WAN_TTL = 6 * 3600

def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _wan_fetch():
    try:
        import requests as R
        _WAN["ip"] = R.get("https://api.ipify.org", timeout=8).text.strip()
        _WAN_FILE.write_text(json.dumps({"ip": _WAN["ip"], "ts": time.time()}))
    except Exception:
        _WAN["ip"] = _WAN.get("ip", "") or ""
    finally:
        _WAN["ts"] = time.time()
        _WAN["busy"] = False

def wan_ip() -> str:
    if _WAN["ip"] and (time.time() - _WAN["ts"]) < _WAN_TTL:
        return _WAN["ip"]
    if not _WAN["busy"]:
        try:
            cached = json.loads(_WAN_FILE.read_text())
            if cached.get("ip") and (time.time() - cached.get("ts", 0)) < _WAN_TTL:
                _WAN.update({"ip": cached["ip"], "ts": cached["ts"]})
                return cached["ip"]
        except Exception:
            pass
        _WAN["busy"] = True
        threading.Thread(target=_wan_fetch, daemon=True).start()
    return _WAN["ip"]

def seed_start_rcon(srv, sdir: Path):
    """Write RCON keys into server.properties only when the file lacks them,
    so the panel's RCON always works (password/port match what the server uses)
    without overruling an explicit user choice (enable-rcon=false in Options)."""
    try:
        pp = sdir / "server.properties"
        raw = pp.read_text(errors="replace") if pp.exists() else ""
        patch = {}
        if "enable-rcon" not in raw:
            patch["enable-rcon"] = "true"
        if "rcon.password" not in raw:
            patch["rcon.password"] = "vohost-rcon"
        if "rcon.port" not in raw:
            patch["rcon.port"] = str((srv or {}).get("rcon_port", 25575))
        else:
            # repair: rcon.port must never equal the game port (the server then
            # cannot bind RCON and the panel ends up talking to the game port,
            # which accepts TCP but never answers RCON -> auth timeout)
            try:
                game = rp = None
                for line in raw.splitlines():
                    if line.startswith("server-port="):
                        game = line.split("=", 1)[1].strip()
                    elif line.startswith("rcon.port="):
                        rp = line.split("=", 1)[1].strip()
                if rp and game and rp == game:
                    patch["rcon.port"] = str((srv or {}).get("rcon_port", 25575))
            except Exception:
                pass
        if patch:
            OM.write_props(patch, sdir)
    except Exception:
        pass

def ensure_server_jar(srv, sdir: Path, sid: str):
    """Download server.jar if missing. Returns ('noop'|'ok', msg|'') or ('err', msg)."""
    jar = sdir / "server.jar"
    if jar.exists():
        return "noop", ""
    soft = {}
    for f in (DATA / f"software-{sid}.json", DATA / "software.json"):
        try:
            soft = json.loads(f.read_text())
            break
        except Exception:
            pass
    loader = (soft.get("loader") or (srv or {}).get("loader") or "vanilla")
    mc = (soft.get("mc_version") or (srv or {}).get("mc_version") or "")
    lv = (soft.get("loader_version") or "latest")
    if not mc or mc == "latest":
        vs = V.mc_versions()
        mc = vs[0] if vs else "1.21.4"
    hook = BASE / "scripts" / "install-server.sh"
    if not hook.exists():
        return "err", "server.jar is missing and the installer script is absent - re-run repair.sh, or upload server.jar via the Files tab."
    env = dict(os.environ, VOHOST_SERVER_DIR=str(sdir), VOHOST_SERVER_ID=sid, VOHOST_BASE=str(BASE))
    try:
        r = subprocess.run(["bash", str(hook), loader, mc, lv], capture_output=True, text=True, timeout=600, env=env)
        out = (r.stdout + r.stderr)[-2500:]
    except Exception as e:
        return "err", f"jar auto-install crashed: {e}"
    if not jar.exists():
        return "err", (f"Auto-install of {loader} {mc} produced no server.jar.\n{out}\n"
                       "For manual loaders (forge/neoforge/spigot/hytale/modpack) upload the jar/zip in the Files tab.")
    return "ok", f"Auto-installed {loader} {mc} -> server.jar"

# ---------- setup (first admin) ----------
def setup_needed() -> bool:
    try:
        return len(list_users()) == 0
    except Exception:
        return True

@app.get("/api/setup-state")
def setup_state():
    return {"needs_setup": setup_needed(), "has_users": not setup_needed()}

@app.post("/api/setup", response_model=None)
def do_setup(body: dict):
    """Create the FIRST user (admin). Rejected once any user exists."""
    if not setup_needed():
        raise HTTPException(403, "setup already done — a user exists. Reset via data/.admin-pass + restart.")
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or len(password) < 4:
        raise HTTPException(400, "username + password (min 4 chars) required")
    upsert_user(username, password, "admin")
    try:
        (DATA / ".admin-pass").write_text(password + "\n")
    except Exception:
        pass
    tok = make_token(username, "admin")
    resp = JSONResponse({"ok": True, "user": {"username": username, "role": "admin"}})
    resp.set_cookie("vohost", tok, httponly=True, samesite="lax")
    resp.headers["x-token"] = tok
    return resp

# ---------- auth ----------
@app.post("/api/login")
def login(body: dict):
    u = A.verify(body.get("username", ""), body.get("password", ""))
    if not u:
        raise HTTPException(401, "bad credentials")
    tok = A.make_token(u["username"], u["role"])
    resp = JSONResponse({"ok": True, "user": u})
    resp.set_cookie("vohost", tok, httponly=True, samesite="lax")
    resp.headers["x-token"] = tok
    return resp

@app.post("/api/logout")
def logout(req: Request):
    A.logout(req.cookies.get("vohost", ""))
    return {"ok": True}

@app.get("/api/me")
def me(req: Request):
    return {"user": user_from(req)}

@app.get("/api/users")
def users(req: Request):
    need(req, "admin")
    return {"users": A.list_users()}

@app.post("/api/users")
def upsert(req: Request, body: dict):
    need(req, "admin")
    A.upsert_user(body["username"], body["password"], body.get("role", "viewer"))
    return {"ok": True}

@app.delete("/api/users/{name}")
def deluser(req: Request, name: str):
    need(req, "admin")
    A.delete_user(name)
    return {"ok": True}

# ---------- servers (multi) ----------
@app.get("/api/servers")
def srv_list(req: Request):
    need(req, "viewer")
    out = []
    for s in SV.list_servers():
        try:
            on = SM.service_active(server=s)
        except Exception:
            on = False
        out.append({**s, "online": on})
    return {"servers": out}

@app.post("/api/servers")
def srv_create(req: Request, body: dict):
    need(req, "admin")
    s = SV.create_server(body.get("name", "server"),
                         body.get("network_mode", "wan"),
                         body.get("port"), body.get("memory_max", "4G"),
                         body.get("loader", "vanilla"), body.get("mc_version", "latest"))
    try:
        if load_config().get("ddos_protect"):
            DP.apply([x.get("port") for x in SV.list_servers()])
    except Exception:
        pass
    return {"ok": True, "server": s,
            "note": f"{s['name']} on port {s['port']} ({s['network_mode'].upper()} — {'public, forward port on router' if s['network_mode']=='wan' else 'LAN only, UFW restricted to 192.168/10/172.16'})"}

@app.put("/api/servers/{sid}")
def srv_update(req: Request, sid: str, body: dict):
    need(req, "admin")
    return {"ok": True, "server": SV.update_server(sid, body)}

@app.delete("/api/servers/{sid}")
def srv_delete(req: Request, sid: str, wipe: bool = False):
    need(req, "admin")
    return SV.delete_server(sid, wipe)

# ---------- server status/control (per-server) ----------
@app.get("/api/status")
def status(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, sdir = resolve(req, server_id)
    sid = srv["id"] if srv else ""
    m = SM.metrics(server_id=sid, server=srv)
    props = OM.read_props(sdir)
    soft = {}
    try:
        soft = json.loads((DATA / f"software-{sid}.json").read_text())
    except Exception:
        try:
            soft = json.loads((DATA / "software.json").read_text())
        except Exception:
            pass
    return {**m, "props": {k: props.get(k) for k in ("motd", "max-players", "server-port")},
            "software": soft, "server": srv, "network_mode": props.get("_network_mode", (srv or {}).get("network_mode", "wan")),
            "hostname": DD.fqdn((srv or {}).get("duckdns_domain", "")) if DD.normalize_domain((srv or {}).get("duckdns_domain", "")) else "",
            "ip": {"lan": lan_ip(), "wan": wan_ip()}}

@app.post("/api/server/{act}")
def server_act(req: Request, act: str, server_id: str = "", body: dict | None = None):
    need(req, "moderator")
    srv, sdir = resolve(req, server_id or (body or {}).get("server_id", ""))
    sid = srv["id"] if srv else ""
    if act == "command":
        cmd = (body or {}).get("command", "")
        if not cmd:
            raise HTTPException(400, "empty command")
        return SM.send_command(cmd, server_id=sid, server=srv)
    if act in ("start", "restart"):
        st, msg = ensure_server_jar(srv, sdir, sid)
        if st == "err":
            return {"ok": False, "crashed": True, "note": msg}
        seed_start_rcon(srv, sdir)
        res = SM.action(act, server_id=sid, server=srv)
        if st == "ok":
            extra = msg
            if not res.get("ok"):
                extra += "\n(server still needs fixing - see the log)"
            res["note"] = extra + "\n" + res.get("note", "")
        return res
    return SM.action(act, server_id=sid, server=srv)

@app.get("/api/logs")
def logs(req: Request, lines: int = 300, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return {"log": SM.tail_log(min(lines, 5000), server_id=srv["id"] if srv else "", server=srv)}

@app.get("/api/crash-reports")
def crash_reports(req: Request, server_id: str = "", file: str = ""):
    """List the server's crash-reports/*.txt (newest first) or return one full report."""
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    cr = sdir / "crash-reports"
    if file:
        p = safe_join(cr, file)
        if not p.exists():
            raise HTTPException(404, "crash report not found")
        return {"file": p.name, "text": p.read_text(errors="replace")}
    files = sorted(cr.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if cr.exists() else []
    return {"reports": [f.name for f in files[:20]]}

@app.get("/api/metrics")
def metrics(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return SM.metrics(server_id=srv["id"] if srv else "", server=srv)

@app.get("/api/rcon/diag")
def rcon_diag(req: Request, server_id: str = ""):
    """One-click RCON health report for the Console tab's Test RCON button."""
    need(req, "moderator")
    srv, _ = resolve(req, server_id)
    return SM.rcon_diag(server_id=srv["id"] if srv else "", server=srv)

@app.websocket("/ws/console")
async def ws_console(ws: WebSocket, token: str = "", server_id: str = ""):
    u = A.check_token(token)
    if not u:
        await ws.close(code=4401)
        return
    await ws.accept()
    srv = None
    try:
        srv = SV.get_server(server_id) if server_id else (SV.list_servers()[0] if SV.list_servers() else None)
    except Exception:
        pass
    sid = srv["id"] if srv else ""
    await ws.send_text(f"\x1b[36m[VoHost] connected as {u['username']} ({u['role']}) [{(srv or {}).get('name','?')}]\x1b[0m")
    try:
        while True:
            msg = await ws.receive_text()
            try:
                obj = json.loads(msg)
                cmd = obj.get("command", msg)
            except Exception:
                cmd = msg
            if A.require_role(u, "moderator"):
                r = SM.send_command(cmd, server_id=sid, server=srv)
                out = r.get("out") or r.get("error") or json.dumps(r)
                await ws.send_text(f"\x1b[33m> {cmd}\x1b[0m\n{out}")
            else:
                await ws.send_text("\x1b[31m viewers cannot send commands\x1b[0m")
    except WebSocketDisconnect:
        pass

# ---------- software ----------
@app.get("/api/software/loaders")
def loaders(req: Request):
    need(req, "viewer")
    return {"loaders": V.LOADERS}

@app.get("/api/software/mc")
def mc_list(req: Request, kind: str = "release"):
    need(req, "viewer")
    try:
        if kind == "snapshot":
            return {"versions": V.snapshot_versions()}
        return {"versions": V.mc_versions()}
    except Exception as e:
        raise HTTPException(502, f"version fetch failed: {e}")

@app.get("/api/software/loader-versions")
def loader_versions(req: Request, loader: str, mc: str = ""):
    need(req, "viewer")
    try:
        if loader == "fabric":
            return {"versions": V.fabric_loader_versions(), "mc": V.mc_versions()[:30]}
        if loader == "quilt":
            return {"versions": V.quilt_loader_versions(), "mc": V.mc_versions()[:30]}
        if loader == "paper" and mc:
            return {"versions": V.paper_builds(mc)}
        if loader == "purpur" and mc:
            return {"versions": V.purpur_builds(mc)}
        if loader == "neoforge":
            return {"versions": V.neoforge_versions(mc)}
        if loader == "forge":
            return {"versions": V.forge_versions(mc)}
        if loader in ("vanilla", "snapshot"):
            return {"versions": V.snapshot_versions() if loader == "snapshot" else V.mc_versions()}
        if loader == "hytale":
            return {"versions": [], "note": "Hytale bonus: no public server jar yet — upload jar manually in Files."}
        return {"versions": [], "note": f"live resolver for {loader} not implemented, pick MC version and use installer script"}
    except Exception as e:
        raise HTTPException(502, str(e))

@app.post("/api/software/install")
def sw_install(req: Request, body: dict):
    need(req, "admin")
    srv, sdir = resolve(req, body.get("server_id", ""))
    sid = srv["id"] if srv else "main"
    was_online = SM.service_active(server_id=sid, server=srv)
    (DATA / f"software-{sid}.json").write_text(json.dumps({**body, "ts": time.time()}, indent=2))
    loader, mc = body.get("loader", "vanilla"), body.get("mc_version", "latest")
    lv = body.get("loader_version", "latest")
    note = ""
    if body.get("wipe"):
        # software switch: stop the server, then wipe the folder (world, jar,
        # mods, logs...) while keeping ports + settings; install below is fresh
        if was_online:
            SM.action("stop", server_id=sid, server=srv)
            time.sleep(3)
        removed = SV.wipe_dir(sdir)
        note += (f"Wiped the server folder ({removed} entries removed; kept "
                 f"server.properties/eula.txt). Make sure you downloaded a backup first. ")
    hook = BASE / "scripts" / "install-server.sh"
    note += f"recorded {loader} {mc} build={lv} on {(srv or {}).get('name', sid)}."
    hook_ok = False
    if hook.exists():
        env = dict(os.environ, VOHOST_SERVER_DIR=str(sdir), VOHOST_SERVER_ID=sid,
                   VOHOST_BASE=str(BASE.parent if (BASE.parent / "data").exists() else BASE))
        try:
            r = subprocess.run(["bash", str(hook), loader, mc, lv], capture_output=True, text=True, timeout=600, env=env)
            note += "\n" + (r.stdout + r.stderr)[-4000:]
            hook_ok = r.returncode == 0 and (sdir / "server.jar").exists()
        except Exception as e:
            note += f"\nInstaller could not run: {e}"
    else:
        note += " (no install-server.sh hook — set jar manually in Files/server.jar)."
    if not (sdir / "server.jar").exists():
        note += "\nWARNING: server.jar is missing in the server folder - the server will crash on start until a jar is present."
    # EULA: write the file even if it does not exist yet (fresh server folders have none)
    try:
        if body.get("accept_eula"):
            (sdir / "eula.txt").write_text("eula=true\n")
            note += "\nEULA accepted (eula.txt written)."
    except Exception:
        pass
    if srv:
        SV.update_server(sid, {"loader": loader, "mc_version": mc})
    if hook_ok and was_online:
        note += "\nRestarting server to apply the new jar..."
        time.sleep(1)
        SM.action("restart", server_id=sid, server=srv)
    return {"ok": True, "note": note, "java": java_for_mc(mc if mc != "latest" else "1.21", load_config())}

@app.get("/api/eula")
def eula(req: Request, server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    p = sdir / "eula.txt"
    return {"exists": p.exists(), "text": p.read_text() if p.exists() else ""}

@app.post("/api/eula")
def eula_accept(req: Request, body: dict):
    need(req, "admin")
    _, sdir = resolve(req, body.get("server_id", ""))
    (sdir / "eula.txt").write_text("eula=true\n" if body.get("accept") else "eula=false\n")
    return {"ok": True}

# ---------- mods & plugins (+ installed + uninstall) ----------
@app.get("/api/catalog/search")
def catalog(req: Request, source: str = "modrinth", q: str = "", loader: str = "",
            mc: str = "", kind: str = "mod"):
    need(req, "viewer")
    try:
        if source == "curseforge":
            return {"results": MP.curseforge_search(q, kind, mc or None, loader or None)}
        return {"results": MP.modrinth_search(q, loader or None, mc or None, kind)}
    except Exception as e:
        raise HTTPException(502, str(e))

@app.get("/api/catalog/versions")
def catalog_versions(req: Request, source: str = "modrinth", project: str = "",
                     loader: str = "", mc: str = ""):
    need(req, "viewer")
    if source == "modrinth":
        return {"versions": MP.modrinth_versions(project, loader or None, mc or None)}
    return {"versions": [], "note": "pick file on CurseForge site; paste URL to install"}

@app.get("/api/catalog/installed")
def catalog_installed(req: Request, server_id: str = "", kind: str = ""):
    need(req, "viewer")
    srv, sdir = resolve(req, server_id)
    loader = (srv or {}).get("loader", "")
    mc = (srv or {}).get("mc_version", "") or ""
    try:
        soft = json.loads((DATA / f"software-{srv['id']}.json").read_text())
        loader = soft.get("loader") or loader
        mc = soft.get("mc_version") or mc
    except Exception:
        pass
    out = []
    for k, folder in (("mod", "mods"), ("plugin", "plugins")):
        if kind and kind != k:
            continue
        d = sdir / folder
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    out.append({"kind": k, "file": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    # update badges: check Modrinth for a newer release for each installed file (best-effort)
    if out:
        def _chk(ent):
            try:
                info = _update_check(ent["file"], ent["kind"], loader, mc)
                if info:
                    ent.update(slug=info["slug"], update=True, latest=info["number"], latest_file=info["filename"])
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(_chk, out))
    return {"installed": out}

@app.post("/api/catalog/install")
def catalog_install(req: Request, body: dict):
    need(req, "moderator")
    import requests as R
    _, sdir = resolve(req, body.get("server_id", ""))
    source, kind = body.get("source", "modrinth"), body.get("kind", "mod")
    destdir = sdir / ("mods" if kind == "mod" else "plugins")
    destdir.mkdir(exist_ok=True)
    mc = (body.get("mc") or "").strip()
    if mc in ("", "latest"):
        mc = ""  # unknown server version -> no version constraint
    loader = (body.get("loader") or "").strip()
    note = ""
    if source == "modrinth":
        vs = MP.modrinth_versions(body["project"], loader, mc, strict=True)
        v = next((x for x in vs if x["id"] == body.get("version_id")), vs[0] if vs else None)
        if not v:
            raise HTTPException(404, f"No {kind} version compatible with MC {mc or '?'}"
                                      f"{' / ' + loader if loader else ''} on Modrinth.")
        f0 = v["files"][0]
        data = R.get(f0["url"], timeout=60).content
        (destdir / f0["filename"]).write_bytes(data)
        note = f"auto-picked {v['number']} (MC {', '.join(v['mc'][:5])})"
        return {"ok": True, "file": f0["filename"], "note": note}
    url = (body.get("file_url") or "").strip()
    if not url:
        pick = MP.curseforge_latest_file(body["project"], kind, loader, mc)
        if not pick:
            raise HTTPException(404, f"No CurseForge file for MC {mc or '?'} / loader {loader or 'any'} "
                                     f"(file may be installer-only).")
        url = pick["url"]
        note = f"auto-picked {pick['name']}"
    fn = url.split("/")[-1].split("?")[0]
    (destdir / fn).write_bytes(R.get(url, timeout=60).content)
    return {"ok": True, "file": fn, "note": note}

@app.post("/api/catalog/uninstall")
def catalog_uninstall(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    kind, fn = body.get("kind", "mod"), body.get("file", "")
    if not fn or "/" in fn or ".." in fn:
        raise HTTPException(400, "bad file")
    p = sdir / ("mods" if kind == "mod" else "plugins") / fn
    if not p.exists():
        raise HTTPException(404, "not installed")
    p.unlink()
    return {"ok": True, "removed": fn}

@app.post("/api/catalog/update")
def catalog_update(req: Request, body: dict):
    """Update an installed mod/plugin to the newest version compatible with the server's MC."""
    need(req, "moderator")
    import requests as R
    srv, sdir = resolve(req, body.get("server_id", ""))
    kind, fn = body.get("kind", "mod"), body.get("file", "")
    if not fn or "/" in fn or ".." in fn:
        raise HTTPException(400, "bad file")
    destdir = sdir / ("mods" if kind == "mod" else "plugins")
    old = destdir / fn
    if not old.exists():
        raise HTTPException(404, "not installed")
    slug = MP.slug_from_filename(fn)
    if not slug:
        raise HTTPException(400, "could not identify the project from the file name - uninstall + re-add it instead")
    loader = (srv or {}).get("loader", "")
    mc = (srv or {}).get("mc_version", "") or ""
    try:
        soft = json.loads((DATA / f"software-{srv['id']}.json").read_text())
        loader = soft.get("loader") or loader
        mc = soft.get("mc_version") or mc
    except Exception:
        pass
    vs = MP.modrinth_versions(slug, loader, mc, strict=True)
    if not vs:
        raise HTTPException(404, f"no compatible version on Modrinth for MC {mc or '?'}")
    v = vs[0]
    f0 = v["files"][0]
    data = R.get(f0["url"], timeout=60).content
    new = destdir / f0["filename"]
    if new.exists() and new.name != old.name:
        new.unlink()
    new.write_bytes(data)
    old.unlink(missing_ok=True)
    return {"ok": True, "file": new.name, "note": f"updated to {v['number']} (restart the server to load it)"}

# ---------- files ----------
@app.get("/api/files")
def files(req: Request, path: str = "", server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    p = safe_join(sdir, path)
    if p.is_file():
        return FileResponse(str(p), filename=p.name)
    items = []
    for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        st = c.stat()
        items.append({"name": c.name, "dir": c.is_dir(), "size": st.st_size, "mtime": st.st_mtime})
    return {"path": path, "items": items}

@app.post("/api/files/mkdir")
def mkdir(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    p = safe_join(sdir, body.get("path", ""))
    p.mkdir(parents=True, exist_ok=True)
    return {"ok": True}

@app.post("/api/files/delete")
def delete(req: Request, body: dict):
    need(req, "admin")
    _, sdir = resolve(req, body.get("server_id", ""))
    p = safe_join(sdir, body.get("path", ""))
    if p == sdir.resolve():
        raise HTTPException(400, "refuse to delete server root")
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)
    return {"ok": True}

@app.post("/api/files/rename")
def rename(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    src = safe_join(sdir, body.get("src", ""))
    dst = safe_join(sdir, body.get("dst", ""))
    src.rename(dst)
    return {"ok": True}

@app.get("/api/files/content")
def file_content(req: Request, path: str = "", server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    p = safe_join(sdir, path)
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "not a file")
    if p.stat().st_size > 512 * 1024:
        raise HTTPException(400, "file too large to edit in the browser (max 512 KB)")
    return {"name": p.name, "path": path, "size": p.stat().st_size,
            "editable": p.suffix.lower() in TEXT_EDIT_EXTS,
            "text": p.read_text(errors="replace")}

@app.post("/api/files/content")
def file_content_save(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    p = safe_join(sdir, body.get("path", ""))
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "not a file")
    p.write_text(str(body.get("text", "")))
    return {"ok": True, "name": p.name, "note": "saved (restart the server to apply configs)"}

@app.post("/api/files/upload")
async def upload(req: Request, path: str = "", server_id: str = "", file: UploadFile = File(...)):
    need(req, "moderator")
    _, sdir = resolve(req, server_id)
    dest = safe_join(sdir, path) / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    if dest.suffix == ".zip" and req.query_params.get("extract") == "1":
        with zipfile.ZipFile(dest) as z:
            z.extractall(dest.parent)
        dest.unlink()
    return {"ok": True, "file": file.filename}

# ---------- worlds ----------
@app.get("/api/worlds")
def worlds(req: Request, server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    out = []
    for w in ["world", "world_nether", "world_the_end"]:
        p = sdir / w
        if p.exists():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            out.append({"name": w, "size": size})
    return {"worlds": out}

@app.get("/api/worlds/download")
def world_dl(req: Request, name: str = "world", server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    src = safe_join(sdir, name)
    tmp = DATA / f"{name}.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(sdir))
    return FileResponse(str(tmp), filename=f"{name}.zip")

@app.post("/api/worlds/upload")
async def world_ul(req: Request, server_id: str = "", file: UploadFile = File(...)):
    need(req, "moderator")
    _, sdir = resolve(req, server_id)
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "world import only accepts .zip")
    tmp = DATA / f"world-import-{int(time.time())}.zip"
    tmp.write_bytes(await file.read())
    for w in ["world", "world_nether", "world_the_end"]:
        p = sdir / w
        if p.exists():
            shutil.rmtree(p)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(sdir)
    tmp.unlink(missing_ok=True)
    return {"ok": True, "note": "old world replaced, zip leftover deleted"}

# ---------- players ----------
BANTIME_HELP = "duration like 7d / 2h / 30m or 'forever'"

@app.post("/api/players/action")
def p_action(req: Request, body: dict):
    need(req, "moderator")
    srv, _ = resolve(req, body.get("server_id", ""))
    sid = srv["id"] if srv else ""
    name = body.get("name", "")
    act = body.get("action", "")
    dur = body.get("duration", "")
    if not name or not act:
        raise HTTPException(400, "name+action required")
    mapping = {
        "op": f"op {name}", "deop": f"deop {name}",
        "kick": f"kick {name} {body.get('reason', 'kicked by VoHost')}",
        "kill": f"kill {name}", "feed": f"effect give {name} saturation 10 10",
        "ban": f"ban {name} {body.get('reason', '')}",
        "ban-ip": f"ban-ip {name} {body.get('reason', '')}",
        "pardon": f"pardon {name}", "pardon-ip": f"pardon-ip {name}",
    }
    if act == "tempban":
        bans = {}
        try:
            bans = json.loads((DATA / "tempbans.json").read_text())
        except Exception:
            pass
        bans[name] = {"until": time.time() + _parse_dur(dur), "reason": body.get("reason", "")}
        (DATA / "tempbans.json").write_text(json.dumps(bans, indent=2))
        return SM.send_command(f"ban {name} temp {dur} {body.get('reason', '')}", server_id=sid, server=srv)
    if act not in mapping:
        raise HTTPException(400, f"unknown action {act} ({BANTIME_HELP})")
    return SM.send_command(mapping[act], server_id=sid, server=srv)

def _parse_dur(s: str) -> float:
    import re
    if s == "forever" or not s:
        return 10 * 365 * 86400
    m = re.match(r"(\d+)\s*([smhd])", s)
    if not m:
        return 86400
    n, u = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]

@app.get("/api/players/online")
def p_online(req: Request, server_id: str = ""):
    """Live online players from RCON `list` (shows players even before anyone spawns)."""
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    sid = srv["id"] if srv else ""
    if not SM.service_active(server_id=sid, server=srv):
        return {"error": "server is offline - press Start in the Server tab first."}
    r = SM.send_command("list", server_id=sid, server=srv)
    if not r.get("ok"):
        import re as _re
        err = r.get("error", "")
        if "timeout" in err.lower() or "refused" in err.lower():
            return {"error": "RCON not reachable. The panel re-writes enable-rcon + the correct rcon port at Start; re-press Start once, then keep the port in Options matching the Server tab."}
        return {"error": err}
    out = r.get("out", "")
    import re
    m = re.search(r"There are (\d+) of a max(?: of)? (\d+) players online:?(.*)", out)
    if m:
        names = [n.strip() for n in m.group(3).split(",") if n.strip()]
        return {"count": int(m.group(1)), "max": int(m.group(2)), "online": names}
    m2 = re.search(r"(\d+)/(\d+) players online:?(.*)", out)
    if m2:
        names = [n.strip() for n in m2.group(3).split(",") if n.strip()]
        return {"count": int(m2.group(1)), "max": int(m2.group(2)), "online": names}
    return {"raw": out[:500]}

@app.get("/api/players/seen")
def p_seen(req: Request, server_id: str = ""):
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    return {"players": NP.list_players_seen(sdir)}

@app.get("/api/players/data")
def p_data(req: Request, uuid: str, server_id: str = ""):
    need(req, "moderator")
    _, sdir = resolve(req, server_id)
    return NP.read_profile(uuid, sdir)

@app.post("/api/players/item/delete")
def p_item_delete(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    uuid, slot = str(body.get("uuid", "")), body.get("slot")
    which = str(body.get("list", "Inventory"))
    if not uuid or slot is None:
        raise HTTPException(400, "uuid+slot required")
    try:
        r = NP.delete_slot(uuid, slot, sdir, which=which)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"delete failed: {e}")
    return {**r, "note": "Removed from the saved player file. The player must be offline for it to stick; while online use /clear <name> in the Console."}

@app.post("/api/players/item/clear")
def p_item_clear(req: Request, body: dict):
    need(req, "moderator")
    _, sdir = resolve(req, body.get("server_id", ""))
    uuid, ender = str(body.get("uuid", "")), bool(body.get("ender"))
    if not uuid:
        raise HTTPException(400, "uuid required")
    try:
        r = NP.clear_inv(uuid, sdir, ender=ender)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"clear failed: {e}")
    return {**r, "note": "Cleared in the saved player file (player should be offline)."}

@app.get("/api/players/lists")
def p_lists(req: Request, server_id: str = ""):
    """Whitelist + banned players/ips (from the vanilla json files), no server restart needed."""
    need(req, "viewer")
    _, sdir = resolve(req, server_id)
    props = OM.read_props(sdir)
    return {"whitelist_enabled": (props.get("white-list") or "false") == "true",
            "whitelist": _read_json_list(sdir / "whitelist.json"),
            "bans": _read_json_list(sdir / "banned-players.json"),
            "ban_ips": _read_json_list(sdir / "banned-ips.json")}

@app.post("/api/players/lists")
def p_lists_put(req: Request, body: dict):
    need(req, "moderator")
    srv, sdir = resolve(req, body.get("server_id", ""))
    sid = srv["id"] if srv else ""
    online = SM.service_active(server_id=sid, server=srv)
    op = str(body.get("op", ""))
    name = str(body.get("name", "")).strip()
    reason = str(body.get("reason", "") or "").strip()
    wl = sdir / "whitelist.json"
    bans = sdir / "banned-players.json"
    ips = sdir / "banned-ips.json"
    if op == "toggle-whitelist":
        cur = (OM.read_props(sdir).get("white-list") or "false") == "true"
        OM.write_props({"white-list": "false" if cur else "true"}, sdir)
        if online:
            SM.send_command("whitelist " + ("off" if cur else "on"), server_id=sid, server=srv)
            SM.send_command("whitelist reload", server_id=sid, server=srv)
        return {"ok": True, "enabled": not cur, "note": "whitelist " + ("on" if not cur else "off")}
    if not name:
        raise HTTPException(400, "name required")
    if op == "whitelist-add":
        if online:
            SM.send_command(f"whitelist add {name}", server_id=sid, server=srv)
            SM.send_command("whitelist reload", server_id=sid, server=srv)
        rows = _read_json_list(wl)
        if not any(e.get("name", "").lower() == name.lower() for e in rows):
            rows.append({"uuid": "", "name": name})
            _write_json_list(wl, rows)
        return {"ok": True, "note": "whitelisted " + name + (" (UUID fills on next online start)" if not online else "")}
    if op == "whitelist-remove":
        if online:
            SM.send_command(f"whitelist remove {name}", server_id=sid, server=srv)
            SM.send_command("whitelist reload", server_id=sid, server=srv)
        _write_json_list(wl, [e for e in _read_json_list(wl) if e.get("name", "").lower() != name.lower()])
        return {"ok": True, "note": "removed from whitelist"}
    if op == "ban-add":
        if online:
            r = SM.send_command(f"ban {name} {reason}".strip(), server_id=sid, server=srv)
            if r.get("ok"):
                return {"ok": True, "note": "banned via RCON"}
            return {"ok": False, "error": r.get("error"),
                    "hint": "server online but RCON failed; start the server freshly so RCON is up"}
        rows = _read_json_list(bans)
        if not any(e.get("name", "").lower() == name.lower() for e in rows):
            rows.append({"uuid": "", "name": name, "created": datetime.utcnow().isoformat(),
                         "source": "VoHost", "expires": "forever", "reason": reason})
            _write_json_list(bans, rows)
        return {"ok": True, "note": name + " banned (offline write; start the server so its UUID is set)"}
    if op == "ban-remove":
        if online:
            SM.send_command(f"pardon {name}", server_id=sid, server=srv)
        _write_json_list(bans, [e for e in _read_json_list(bans) if e.get("name", "").lower() != name.lower()])
        _write_json_list(ips, [e for e in _read_json_list(ips) if e.get("ip", "") != name])
        return {"ok": True, "note": "unbanned"}
    if op == "banip-add":
        if online:
            return SM.send_command(f"ban-ip {name} {reason}".strip(), server_id=sid, server=srv)
        rows = _read_json_list(ips)
        rows.append({"ip": name, "created": datetime.utcnow().isoformat(),
                     "source": "VoHost", "expires": "forever", "reason": reason})
        _write_json_list(ips, rows)
        return {"ok": True, "note": "ip banned (offline write)"}
    if op == "banip-remove":
        if online:
            SM.send_command(f"pardon-ip {name}", server_id=sid, server=srv)
        _write_json_list(ips, [e for e in _read_json_list(ips) if e.get("ip", "") != name])
        return {"ok": True, "note": "ip unbanned"}
    raise HTTPException(400, "unknown op " + op)

# ---------- options ----------
@app.get("/api/options")
def opts(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, sdir = resolve(req, server_id)
    props = OM.read_props(sdir)
    icon = sdir / "server-icon.png"
    icon_b64 = base64.b64encode(icon.read_bytes()).decode() if icon.exists() else ""
    cfg = load_config()
    return {"props": props, "toggles": OM.TOGGLES, "icon": icon_b64,
            "timezone": props.get("_timezone", "UTC"), "env": props.get("_env", ""),
            "network_mode": props.get("_network_mode", (srv or {}).get("network_mode", "wan")),
            "server": srv,
            "memory": {"min": (srv or {}).get("memory_min", "1G"), "max": (srv or {}).get("memory_max", "4G")},
            "cpu_cores": (srv or {}).get("cpu_cores", 4),
            "restart": (srv or {}).get("restart", {"enabled": False, "at": ""}),
            "restart_last": RT.last(srv["id"]) if srv else None,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M (UTC%z)"),
            "public_page": bool(cfg.get("public_page", True)),
            "curseforge_key_set": bool(cfg.get("curseforge_api_key")),
            "discord_set": bool(cfg.get("discord_webhook"))}

@app.put("/api/options")
def opts_put(req: Request, body: dict):
    need(req, "moderator")
    srv, sdir = resolve(req, body.get("server_id", ""))
    props = body.get("props", {})
    # cracked-mode invariant: with Mojang auth off, chat keys cannot exist for
    # offline players, so an offline server must not enforce secure profiles —
    # otherwise TLauncher/cracked clients are kicked on join (1.19+).
    cracked_note = ""
    try:
        merged = OM.read_props(sdir)
        merged.update({k: str(v) for k, v in props.items() if not str(k).startswith("_")})
        if str(merged.get("online-mode", "true")).lower() == "false" \
                and str(merged.get("enforce-secure-profile", "true")).lower() != "false":
            props["enforce-secure-profile"] = "false"
            cracked_note = " (enforce-secure-profile forced false: required for cracked clients)"
    except Exception:
        pass
    OM.write_props(props, sdir)
    if srv and "_network_mode" in props:
        SV.update_server(srv["id"], {"network_mode": props["_network_mode"]})
    cfg = load_config()
    for k in ("curseforge_api_key", "discord_webhook", "timezone"):
        if k in body:
            cfg[k] = body[k]
    if "public_page" in body:
        cfg["public_page"] = bool(body["public_page"])
    save_config(cfg)
    if srv:
        mem_patch = {}
        for k, default in (("memory_min", "1G"), ("memory_max", "4G")):
            if k in body and str(body[k] or "").strip():
                mem_patch[k] = str(body[k]).strip()
        if "cpu_cores" in body:
            try:
                mem_patch["cpu_cores"] = min(max(int(body["cpu_cores"] or 4), 1), 32)
            except Exception:
                pass
        if mem_patch:
            SV.update_server(srv["id"], mem_patch)
            sync_server_limits(srv["id"])
        if "restart" in body and isinstance(body["restart"], dict):
            rs = body["restart"]
            # new shape {enabled, shutdown_at, startup_at} + legacy {enabled, at}
            shut = RT.norm_time(rs.get("shutdown_at", "") or "")
            up = RT.norm_time(rs.get("startup_at", "") or "")
            legacy = RT.norm_time(rs.get("at", "") or "")
            if legacy and not shut and not up:
                shut, up = legacy, legacy  # legacy single-time restart
            en = bool(rs.get("enabled", False))
            if en and not shut and not up:
                raise HTTPException(400, "restart enabled but no time set (shutdown and/or startup HH:MM)")
            for v in (shut, up):
                if v and not RT.valid_time(v):
                    raise HTTPException(400, "restart time must be HH:MM (24h, e.g. 04:00, 24:00 = midnight)")
            SV.update_server(srv["id"], {"restart": {"enabled": en,
                                                    "shutdown_at": shut if en else "",
                                                    "startup_at": up if en else ""}})
    if body.get("icon_b64"):
        raw = base64.b64decode(body["icon_b64"])
        w = h = None
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
            import struct
            w, h = struct.unpack(">II", raw[16:24])
        if w != 64 or h != 64:
            raise HTTPException(400, f"server-icon.png must be exactly 64x64 PNG (got {w or '?'}x{h or '?'}) - resize and try again")
        (sdir / "server-icon.png").write_bytes(raw)
    if "rcon.password" in props and srv:
        pass  # per-server rcon password lives in server.properties; server_manager reads it live
    return {"ok": True, "note": "saved live — restart server to apply server.properties" + cracked_note}

# ---------- DuckDNS subdomain (no login page use; token never leaves the server) ----------
@app.get("/api/subdomain")
def dd_get(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    sid = srv["id"] if srv else ""
    domain = DD.normalize_domain((srv or {}).get("duckdns_domain", ""))
    port = (srv or {}).get("port", 25565)
    return {"domain": domain, "hostname": DD.fqdn(domain) if domain else "",
            "port": port, "token_set": bool(load_config().get("duckdns_token", "")),
            "wan": wan_ip(), "resolved": DD.resolve(domain) if domain else "",
            "last": DD.last_status(sid)}

@app.put("/api/subdomain")
def dd_put(req: Request, body: dict):
    need(req, "admin")
    srv, _ = resolve(req, body.get("server_id", ""))
    if not srv:
        raise HTTPException(404, "no server")
    if "token" in body and str(body.get("token") or "").strip():
        cfg = load_config()
        cfg["duckdns_token"] = str(body["token"]).strip()
        save_config(cfg)
    if "domain" in body:
        raw = str(body.get("domain") or "").strip()
        if raw and not DD.normalize_domain(raw):
            raise HTTPException(400, "subdomain must be a-z, 0-9, dash (e.g. vosmp)")
        SV.update_server(srv["id"], {"duckdns_domain": DD.normalize_domain(raw)})
        srv = SV.get_server(srv["id"])
    domain = DD.normalize_domain(srv.get("duckdns_domain", ""))
    sync = DD.sync_server(srv, wan_ip(), load_config().get("duckdns_token", ""), force=True) if domain else {"ok": False, "skipped": True, "message": "subdomain cleared"}
    return {"ok": True, "domain": domain, "hostname": DD.fqdn(domain) if domain else "",
            "token_set": bool(load_config().get("duckdns_token", "")), "sync": sync}

# ---------- DDoS/flood protection (machine-level; see vohost/ddos.py for limits) ----------
@app.get("/api/security")
def sec_get(req: Request):
    need(req, "viewer")
    return {"enabled": bool(load_config().get("ddos_protect", False)), **DP.status()}

@app.put("/api/security")
def sec_put(req: Request, body: dict):
    need(req, "admin")
    on = bool((body or {}).get("enabled", False))
    cfg = load_config()
    cfg["ddos_protect"] = on
    save_config(cfg)
    if on:
        try:
            ports = [x.get("port") for x in SV.list_servers()]
        except Exception:
            ports = []
        res = DP.apply(ports)
    else:
        res = DP.remove()
    return {"ok": True, "enabled": on, **DP.status(), "log": res.get("log", [])}

# ---------- Push Limits mode: full machine resources for one server ----------
@app.get("/api/push-limits")
def push_get(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    if not srv or (server_id and srv.get("id") != server_id):
        raise HTTPException(404, "no server")
    return {"enabled": bool(srv.get("push_limits", False)),
            "machine": PL.machine(), "target": PL.target(),
            "current": {"min": srv.get("memory_min", "1G"), "max": srv.get("memory_max", "4G"),
                        "cores": srv.get("cpu_cores", 4)}}

@app.post("/api/push-limits")
def push_post(req: Request, body: dict):
    need(req, "admin")
    srv, _ = resolve(req, (body or {}).get("server_id", ""))
    if not srv or ((body or {}).get("server_id") and srv.get("id") != (body or {}).get("server_id")):
        raise HTTPException(404, "no server")
    on = bool((body or {}).get("enabled", False))
    if on:
        prev = {"min": srv.get("memory_min", "1G"), "max": srv.get("memory_max", "4G"),
                "cores": srv.get("cpu_cores", 4)}
        t = PL.target()
        srv = SV.update_server(srv["id"], {"push_limits": True, "push_limits_prev": prev,
                                           "memory_min": t["memory"], "memory_max": t["memory"],
                                           "cpu_cores": t["cores"]})
        note = f"pushed to {t['memory']} RAM + {t['cores']} cores — restart the server to apply"
    else:
        prev = srv.get("push_limits_prev") or {"min": "1G", "max": "4G", "cores": 4}
        srv = SV.update_server(srv["id"], {"push_limits": False,
                                           "memory_min": prev.get("min", "1G"),
                                           "memory_max": prev.get("max", "4G"),
                                           "cpu_cores": prev.get("cores", 4)})
        note = "previous limits restored — restart the server to apply"
    sync_server_limits(srv["id"])
    return {"ok": True, "enabled": on, "server": srv, "note": note}

# ---------- Simple Voice Chat one-click (Paper-family only) ----------
@app.post("/api/voicechat/install")
def voicechat_install(req: Request, body: dict):
    need(req, "moderator")
    srv, sdir = resolve(req, (body or {}).get("server_id", ""))
    loader = ((srv or {}).get("loader", "") or "").lower()
    if loader not in VC.PAPER_LOADERS:
        try:
            soft = json.loads((DATA / f"software-{srv['id']}.json").read_text())
            loader = (soft.get("loader") or loader).lower()
        except Exception:
            pass
    if loader not in VC.PAPER_LOADERS:
        raise HTTPException(400, f"Simple Voice Chat plugin needs paper/purpur/spigot (this server: {loader or '?'}).")
    mc = ((srv or {}).get("mc_version", "") or "").strip()
    if mc.lower() == "latest":
        mc = ""
    try:
        fn, data, num, mcs = VC.fetch(mc or None)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Modrinth download failed: {e}")
    plugdir = sdir / "plugins"
    plugdir.mkdir(exist_ok=True)
    (plugdir / fn).write_bytes(data)
    udp_ok = VC.open_udp()
    cfg_ok = VC.ensure_port(sdir)
    bits = [f"installed {fn} (v{num})"]
    bits.append("UFW opened for UDP 24454" if udp_ok else "UFW change skipped - allow UDP 24454 manually if players can't connect voice")
    bits.append("voicechat port pinned to 24454" if cfg_ok else "voice port defaults to 24454 on first start")
    return {"ok": True, "file": fn,
            "note": ". ".join(bits) + ". Restart the server, and forward UDP 24454 on the router."}

@app.post("/api/restart/test")
def restart_test(req: Request, body: dict):
    """Run a shutdown/startup once right now (debugging aid). Never touches the schedule state."""
    need(req, "admin")
    srv, _ = resolve(req, (body or {}).get("server_id", ""))
    if not srv or ((body or {}).get("server_id") and srv.get("id") != (body or {}).get("server_id")):
        raise HTTPException(404, "no server")
    act = str((body or {}).get("action", ""))
    if act not in ("shutdown", "startup"):
        raise HTTPException(400, "action must be shutdown|startup")
    try:
        online = bool(SM.service_active(server=srv))
    except Exception:
        online = False
    try:
        if act == "shutdown":
            if not online:
                return {"ok": True, "note": "server already stopped - nothing to do"}
            try:
                SM.send_command("say [VoHost] Test shutdown starting now", server=srv)
            except Exception:
                pass
            r = SM.action("stop", server_id=srv["id"], server=srv)
            ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
            return {"ok": ok, "note": "stopped (test run, schedule untouched)"}
        if online:
            return {"ok": True, "note": "server already running - nothing to do"}
        r = SM.action("start", server_id=srv["id"], server=srv)
        ok = bool((r or {}).get("ok", True)) if isinstance(r, dict) else True
        return {"ok": ok, "note": "started (test run, schedule untouched)"}
    except Exception as e:
        raise HTTPException(500, f"test run failed: {e}")

# ---------- backups / misc ----------
@app.get("/api/backups")
def bk_list(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return BK.list_backups(srv["id"] if srv else "")

@app.post("/api/backups")
def bk_create(req: Request, body: dict | None = None):
    need(req, "moderator")
    srv, sdir = resolve(req, (body or {}).get("server_id", ""))
    keep = int(((srv or {}).get("backup") or {}).get("keep") or 5)
    return BK.create_backup(sdir, (body or {}).get("label", "manual"), keep)

@app.post("/api/backups/restore")
def bk_restore(req: Request, body: dict):
    need(req, "admin")
    return BK.restore(body.get("file", ""))

@app.get("/api/backups/download")
def bk_download(req: Request, file: str = "", server_id: str = ""):
    need(req, "moderator")
    p = BK.backup_path(file)
    if not p:
        raise HTTPException(404, "backup not found")
    return FileResponse(str(p), filename=p.name)

@app.get("/api/backups/settings")
def bk_settings(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return {"schedule": (srv or {}).get("backup") or {},
            "server_id": srv["id"] if srv else ""}

@app.put("/api/backups/settings")
def bk_settings_put(req: Request, body: dict):
    need(req, "moderator")
    srv, _ = resolve(req, body.get("server_id", ""))
    if not srv:
        raise HTTPException(400, "no server selected")
    sc = {
        "enabled": bool(body.get("enabled")),
        "mode": "hourly" if body.get("mode") == "hourly" else "daily",
        "hour": min(max(int(body.get("hour") or 4), 0), 23),
        "minute": min(max(int(body.get("minute") or 0), 0), 59),
        "keep": min(max(int(body.get("keep") or 5), 1), 30),
    }
    SV.update_server(srv["id"], {"backup": sc})
    return {"ok": True, "schedule": sc}

@app.get("/api/config")
def get_cfg(req: Request):
    need(req, "admin")
    return load_config()

@app.put("/api/config")
def put_cfg(req: Request, body: dict):
    need(req, "admin")
    cfg = load_config()
    cfg.update(body)
    save_config(cfg)
    return {"ok": True}

@app.post("/api/notify")
def notify(req: Request, body: dict):
    need(req, "moderator")
    import requests as R
    url = load_config().get("discord_webhook", "")
    if not url:
        raise HTTPException(400, "discord webhook not set in Options")
    R.post(url, json={"content": body.get("message", "VoHost test")}, timeout=10)
    return {"ok": True}

# ---------- public status page (no login) ----------
def _public_enabled() -> bool:
    return bool(load_config().get("public_page", True))

@app.get("/api/public/{sid}")
def public_api(sid: str):
    if not _public_enabled():
        raise HTTPException(404, "public page disabled")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid):
        raise HTTPException(404, "server not found")
    try:
        s = SV.get_server(sid)
    except Exception:
        raise HTTPException(404, "server not found")
    if s.get("id") != sid:  # get_server falls back to the first server; never leak that
        raise HTTPException(404, "server not found")
    sdir = Path(s.get("dir", ""))
    online = False
    try:
        online = SM.service_active(server=s)
    except Exception:
        pass
    out = {"name": s.get("name"), "id": sid, "online": online,
           "motd": OM.read_props(sdir).get("motd", ""),
           "port": s.get("port", 25565), "network_mode": s.get("network_mode", "wan"),
           "hostname": DD.fqdn(s.get("duckdns_domain", "")) if DD.normalize_domain(s.get("duckdns_domain", "")) else "",
           "ip": {"lan": lan_ip(), "wan": wan_ip()}, "ts": time.time()}
    if online:
        r = SM.send_command("list", server=s)
        if r.get("ok"):
            m = re.search(r"There are (\d+) of a max(?: of)? (\d+) players online:?(.*)", r.get("out", ""))
            if m:
                out["players"] = {"count": int(m.group(1)), "max": int(m.group(2)),
                                  "names": [n.strip() for n in m.group(3).split(",") if n.strip()]}
        try:
            out["tps"] = SM.metrics(server=s).get("tps")
        except Exception:
            pass
    return out

PUBLIC_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__SID__ - VoHost status</title>
<style>body{font-family:system-ui,sans-serif;background:#0f1622;color:#e8eef4;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#1b2634;border:1px solid #314052;border-radius:14px;padding:26px 34px;text-align:center;max-width:520px;width:92%}
.pill{display:inline-block;padding:4px 14px;border-radius:20px;font-weight:600}
.up{background:#1f8a4c;color:#fff}.down{background:#e5484d;color:#fff}
h1{margin:.4em 0 0;font-size:26px}h2{margin:.2em 0 0;color:#93a3b5;font-weight:normal;font-size:15px}
.motd{margin:14px 0;color:#93a3b5;font-style:italic}
.addr{font-family:ui-monospace,Consolas,monospace;background:#0c1219;border-radius:8px;padding:12px;font-size:18px}
.mc-obf{letter-spacing:1px}
.row{display:flex;gap:20px;justify-content:center;margin-top:16px}.row div{font-size:13px;color:#93a3b5}.row b{display:block;color:#e8eef4;font-size:20px;margin-top:2px}
.mut{color:#5b6b7d;font-size:12px;margin-top:18px}</style></head><body><div class="card">
<span class="pill down" id="pill">checking...</span><h1 id="name">...</h1><h2 id="sub"></h2>
<div class="motd" id="motd"></div><div class="addr" id="addr">-</div>
<div class="row"><div>Players<b id="pc">-</b></div><div>TPS<b id="tps">-</b></div></div>
<div class="mut" id="foot"></div></div>
<script>
const sid='__SID__';
const MC_COL={0:"#000000",1:"#0000AA",2:"#00AA00",3:"#00AAAA",4:"#AA0000",5:"#AA00AA",6:"#FFAA00",7:"#AAAAAA",8:"#555555",9:"#5555FF",a:"#55FF55",b:"#55FFFF",c:"#FF5555",d:"#FF55FF",e:"#FFFF55",f:"#FFFFFF"};
const MCH="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$!?";
function mcRnd(t){let o="";for(let i=0;i<t.length;i++)o+=t[i]===" "?" ":MCH[Math.floor(Math.random()*MCH.length)];return o;}
setInterval(()=>{document.querySelectorAll(".mc-obf").forEach(el=>{const t=el.getAttribute("data-t")||"";el.textContent=mcRnd(t);});},80);
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}
function fmt(s){if(!s)return"";s=String(s);const runs=[];let txt="",st={c:"",b:0,i:0,u:0,s:0,k:0};
const push=()=>{if(txt){runs.push({t:txt,st:Object.assign({},st)});txt="";}};
for(let i=0;i<s.length;i++){const ch=s[i];
if(ch==="&"||ch==="\u00A7"){const cd=(s[i+1]||"").toLowerCase();
if(/^[0-9a-f]$/.test(cd)){push();st={c:MC_COL[cd],b:0,i:0,u:0,s:0,k:0};i++;continue;}
if(cd==="k"){push();st.k=1;i++;continue;}if(cd==="l"){push();st.b=1;i++;continue;}if(cd==="m"){push();st.s=1;i++;continue;}if(cd==="n"){push();st.u=1;i++;continue;}if(cd==="o"){push();st.i=1;i++;continue;}if(cd==="r"){push();st={c:"",b:0,i:0,u:0,s:0,k:0};i++;continue;}}
txt+=ch;}push();
return runs.map(r=>{const css=[];
if(r.st.c)css.push("color:"+r.st.c);if(r.st.b)css.push("font-weight:700");if(r.st.i)css.push("font-style:italic");
const dec=[];if(r.st.u)dec.push("underline");if(r.st.s)dec.push("line-through");if(dec.length)css.push("text-decoration:"+dec.join(" "));
const st=css.length?` style="${css.join(";")}"`:"";
if(r.st.k)return `<span class="mc-obf"${st} data-t="${esc(r.t)}">${mcRnd(r.t)}</span>`;
return `<span class="mc"${st}>${esc(r.t)}</span>`;}).join("");}
async function tick(){try{const j=await (await fetch('/api/public/'+sid)).json();
document.getElementById('name').innerHTML=fmt(j.name)||'?';
const pill=document.getElementById('pill');pill.textContent=j.online?'ONLINE':'OFFLINE';pill.className='pill '+(j.online?'up':'down');
document.getElementById('sub').textContent=j.online?('running, '+j.network_mode+' mode'):'server is stopped';
document.getElementById('motd').innerHTML=fmt(j.motd)||'';
const ip=j.network_mode==='lan'?j.ip.lan:j.ip.wan;const host=(j.network_mode!=='lan'&&j.hostname)?j.hostname:ip;document.getElementById('addr').textContent=(host||'-')+':'+j.port;
const p=j.players||{};document.getElementById('pc').textContent=(p.count!==undefined)?(p.count+' / '+p.max):'-';
document.getElementById('tps').textContent=(j.tps!==undefined&&j.tps!==-1)?j.tps:'-';
document.getElementById('foot').textContent='VoHost status page - updated '+new Date(j.ts*1000).toLocaleTimeString();
}catch(e){document.getElementById('pill').textContent='unreachable';document.getElementById('pill').className='pill down';}}
tick();setInterval(tick,10000);
</script></body></html>"""

@app.get("/public/{sid}", response_class=HTMLResponse)
def public_page(sid: str):
    if not _public_enabled():
        return HTMLResponse("<h1>Public status page is disabled</h1><p>Enable it in Options: Settings - Public status page.</p>")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid):
        return HTMLResponse("<h1>not found</h1>")
    try:
        s = SV.get_server(sid)
        if s.get("id") != sid:
            return HTMLResponse("<h1>not found</h1>")
    except Exception:
        return HTMLResponse("<h1>not found</h1>")
    return HTMLResponse(PUBLIC_HTML.replace("__SID__", sid))

# ---------- frontend ----------
if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONT)), name="assets")

@app.middleware("http")
async def no_cache_assets(request, call_next):
    """Browsers can otherwise keep stale cached CSS/JS after a deploy; force revalidate every reload."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# ---------- login brute-force guard (per-IP, in-memory) ----------
_LOGIN_HITS: dict = {}
LG_HIT_WINDOW = 60      # >=30 login/setup attempts in 60s -> 429
LG_HIT_MAX = 30
LG_FAIL_WINDOW = 300    # >=8 failed logins in 5 min -> lock IP 5 min
LG_FAIL_MAX = 8
LG_LOCK_SECS = 300

@app.middleware("http")
async def login_guard(request, call_next):
    if not (request.method == "POST" and request.url.path in ("/api/login", "/api/setup")):
        return await call_next(request)
    ip = request.client.host if request.client else "?"
    now = time.time()
    e = _LOGIN_HITS.get(ip) or {"hit": [], "fail": [], "locked": 0.0}
    e["hit"] = [t for t in e["hit"] if now - t < LG_HIT_WINDOW]
    e["fail"] = [t for t in e["fail"] if now - t < LG_FAIL_WINDOW]
    if e["locked"] > now:
        return JSONResponse({"detail": "too many attempts, try again later"},
                            status_code=429, headers={"Retry-After": str(int(e["locked"] - now))})
    if len(e["hit"]) >= LG_HIT_MAX:
        e["locked"] = now + 60
        _LOGIN_HITS[ip] = e
        return JSONResponse({"detail": "too many attempts, try again later"},
                            status_code=429, headers={"Retry-After": "60"})
    resp = await call_next(request)
    e["hit"].append(now)
    if resp.status_code in (401, 403):
        e["fail"].append(now)
        if len(e["fail"]) >= LG_FAIL_MAX:
            e["locked"] = now + LG_LOCK_SECS
    _LOGIN_HITS[ip] = e
    # prune idle entries so the table stays tiny
    for k in [k for k, v in _LOGIN_HITS.items()
              if k != ip and not v["hit"] and not v["fail"] and v["locked"] <= now]:
        _LOGIN_HITS.pop(k, None)
    return resp

@app.get("/", response_class=HTMLResponse)
def index():
    idx = FRONT / "index.html"
    if idx.exists():
        html = idx.read_bytes().decode("utf-8", "replace")
        # cache-bust: file mtime in the URL so browsers fetch fresh CSS/JS after every deploy
        for asset in ("style.css", "app.js"):
            try:
                v = str(int((FRONT / asset).stat().st_mtime))
            except Exception:
                v = "0"
            html = html.replace(f"/assets/{asset}", f"/assets/{asset}?v={v}")
        return HTMLResponse(html)
    return "<h1>VoHost</h1><p>frontend/ missing</p>"

def ensure_admin_at_boot():
    """No phantom users. Behavior:
    - data/.admin-pass exists  -> sync/upsert that password for 'admin' (deterministic reset).
    - no users at all          -> do NOT create anything; frontend shows Create-admin setup.
    - users exist, no file     -> do nothing (they log in as usual / Access tab)."""
    pw_file = DATA / ".admin-pass"
    if pw_file.exists():
        pw = pw_file.read_text().strip() or None
        if pw:
            try:
                upsert_user("admin", pw, "admin")
                print("[VoHost] admin password synced from data/.admin-pass")
                return
            except Exception as e:
                print(f"[VoHost] sync failed: {e}")
    if not setup_needed():
        print(f"[VoHost] {len(list_users())} user(s) exist, no .admin-pass sync — log in normally.")
    else:
        print("[VoHost] no users — waiting for first-run setup (POST /api/setup from UI)")

try:
    ensure_admin_at_boot()
except Exception as e:
    print(f"[VoHost] admin bootstrap skipped: {e}")

# background scheduler: due backups (daily/hourly per server)
try:
    threading.Thread(target=BK.start_scheduler, daemon=True).start()
    print("[VoHost] backup scheduler running")
except Exception as e:
    print(f"[VoHost] backup scheduler failed to start: {e}")

# background DuckDNS sync: keep <name>.duckdns.org on the current WAN IP
try:
    threading.Thread(target=lambda: DD.start_loop(wan_ip, lambda: load_config().get("duckdns_token", "")), daemon=True).start()
    print("[VoHost] duckdns sync running")
except Exception as e:
    print(f"[VoHost] duckdns sync failed to start: {e}")

# re-apply flood rules at boot (iptables does not survive reboot)
def _ddos_boot():
    try:
        if load_config().get("ddos_protect"):
            ports = [x.get("port") for x in SV.list_servers()]
            DP.apply(ports)
            print("[VoHost] ddos rules re-applied")
    except Exception as e:
        print(f"[VoHost] ddos re-apply skipped: {e}")

try:
    threading.Thread(target=_ddos_boot, daemon=True).start()
except Exception as e:
    print(f"[VoHost] ddos boot hook failed: {e}")
