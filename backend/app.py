"""VoHost dashboard backend — FastAPI, multi-server, WAN/LAN, installed mods + uninstall."""
import os, json, shutil, zipfile, base64, time, subprocess
from pathlib import Path
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
            "software": soft, "server": srv, "network_mode": props.get("_network_mode", (srv or {}).get("network_mode", "wan"))}

@app.post("/api/server/{act}")
def server_act(req: Request, act: str, server_id: str = "", body: dict | None = None):
    need(req, "moderator")
    srv, _ = resolve(req, server_id or (body or {}).get("server_id", ""))
    sid = srv["id"] if srv else ""
    if act == "command":
        cmd = (body or {}).get("command", "")
        if not cmd:
            raise HTTPException(400, "empty command")
        return SM.send_command(cmd, server_id=sid, server=srv)
    return SM.action(act, server_id=sid, server=srv)

@app.get("/api/logs")
def logs(req: Request, lines: int = 300, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return {"log": SM.tail_log(lines, server_id=srv["id"] if srv else "", server=srv)}

@app.get("/api/metrics")
def metrics(req: Request, server_id: str = ""):
    need(req, "viewer")
    srv, _ = resolve(req, server_id)
    return SM.metrics(server_id=srv["id"] if srv else "", server=srv)

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
    hook = BASE / "scripts" / "install-server.sh"
    note = f"recorded {loader} {mc} build={lv} on {(srv or {}).get('name', sid)}."
    hook_ok = False
    if hook.exists():
        env = dict(os.environ, VOHOST_SERVER_DIR=str(sdir))
        r = subprocess.run(["bash", str(hook), loader, mc, lv], capture_output=True, text=True, timeout=600, env=env)
        note += "\n" + (r.stdout + r.stderr)[-4000:]
        hook_ok = r.returncode == 0 and ("OK" in r.stdout or "installed" in r.stdout)
    else:
        note += " (no install-server.sh hook — set jar manually in Files/server.jar)."
    try:
        eula = sdir / "eula.txt"
        if body.get("accept_eula") and eula.exists():
            eula.write_text(eula.read_text().replace("eula=false", "eula=true"))
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
    _, sdir = resolve(req, server_id)
    out = []
    for k, folder in (("mod", "mods"), ("plugin", "plugins")):
        if kind and kind != k:
            continue
        d = sdir / folder
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file():
                    out.append({"kind": k, "file": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return {"installed": out}

@app.post("/api/catalog/install")
def catalog_install(req: Request, body: dict):
    need(req, "moderator")
    import requests as R
    _, sdir = resolve(req, body.get("server_id", ""))
    source, kind = body.get("source", "modrinth"), body.get("kind", "mod")
    destdir = sdir / ("mods" if kind == "mod" else "plugins")
    destdir.mkdir(exist_ok=True)
    if source == "modrinth":
        vs = MP.modrinth_versions(body["project"], body.get("loader"), body.get("mc"))
        v = next((x for x in vs if x["id"] == body.get("version_id")), vs[0] if vs else None)
        if not v:
            raise HTTPException(404, "version not found")
        f0 = v["files"][0]
        data = R.get(f0["url"], timeout=60).content
        (destdir / f0["filename"]).write_bytes(data)
        return {"ok": True, "file": f0["filename"]}
    url = body.get("file_url", "")
    if not url:
        raise HTTPException(400, "file_url required for curseforge")
    fn = url.split("/")[-1].split("?")[0]
    (destdir / fn).write_bytes(R.get(url, timeout=60).content)
    return {"ok": True, "file": fn}

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
    r = SM.send_command("list", server_id=sid, server=srv)
    if not r.get("ok"):
        return {"error": "server offline or RCON disabled (enable-rcon=true in Options, then restart)"}
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
    return NP.read_inventory(uuid, sdir)

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
            "curseforge_key_set": bool(cfg.get("curseforge_api_key")),
            "discord_set": bool(cfg.get("discord_webhook"))}

@app.put("/api/options")
def opts_put(req: Request, body: dict):
    need(req, "moderator")
    srv, sdir = resolve(req, body.get("server_id", ""))
    props = body.get("props", {})
    OM.write_props(props, sdir)
    if srv and "_network_mode" in props:
        SV.update_server(srv["id"], {"network_mode": props["_network_mode"]})
    cfg = load_config()
    for k in ("curseforge_api_key", "discord_webhook", "timezone"):
        if k in body:
            cfg[k] = body[k]
    save_config(cfg)
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
    return {"ok": True, "note": "saved live — restart server to apply server.properties"}

# ---------- backups / misc ----------
@app.get("/api/backups")
def bk_list(req: Request, server_id: str = ""):
    need(req, "viewer")
    return BK.list_backups()

@app.post("/api/backups")
def bk_create(req: Request, body: dict | None = None):
    need(req, "moderator")
    return BK.create_backup((body or {}).get("label", "manual"))

@app.post("/api/backups/restore")
def bk_restore(req: Request, body: dict):
    need(req, "admin")
    return BK.restore(body.get("file", ""))

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

# ---------- frontend ----------
if FRONT.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONT)), name="assets")

@app.get("/", response_class=HTMLResponse)
def index():
    idx = FRONT / "index.html"
    if idx.exists():
        return HTMLResponse(idx.read_bytes().decode("utf-8", "replace"))
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
