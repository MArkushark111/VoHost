"""VoHost dashboard backend — FastAPI, serves frontend/, WS console with ANSI colors."""
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

FRONT = Path(__file__).resolve().parents[1] / ".." / "frontend"
FRONT = FRONT.resolve()
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

def safe_join(base: Path, rel: str) -> Path:
    p = (base / (rel or "")).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise HTTPException(400, "path escapes server dir")
    return p

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

# ---------- server ----------
@app.get("/api/status")
def status(req: Request):
    need(req, "viewer")
    m = SM.metrics()
    props = OM.read_props()
    soft = {}
    try:
        soft = json.loads((DATA / "software.json").read_text())
    except Exception:
        pass
    return {**m, "props": {k: props.get(k) for k in ("motd", "max-players", "server-port")},
            "software": soft, "base": str(BASE)}

@app.post("/api/server/{act}")
def server_act(req: Request, act: str, body: dict | None = None):
    need(req, "moderator")
    if act == "command":
        cmd = (body or {}).get("command", "")
        if not cmd:
            raise HTTPException(400, "empty command")
        return SM.send_command(cmd)
    return SM.action(act)

@app.get("/api/logs")
def logs(req: Request, lines: int = 300):
    need(req, "viewer")
    return {"log": SM.tail_log(lines)}

@app.get("/api/metrics")
def metrics(req: Request):
    need(req, "viewer")
    return SM.metrics()

# WS console: recv {command}, send log lines + command output. ANSI preserved raw.
@app.websocket("/ws/console")
async def ws_console(ws: WebSocket, token: str = ""):
    u = A.check_token(token)
    if not u:
        await ws.close(code=4401)
        return
    await ws.accept()
    await ws.send_text(f"\x1b[36m[VoHost] connected as {u['username']} ({u['role']})\x1b[0m")
    try:
        while True:
            msg = await ws.receive_text()
            try:
                obj = json.loads(msg)
                cmd = obj.get("command", msg)
            except Exception:
                cmd = msg
            if A.require_role(u, "moderator"):
                r = SM.send_command(cmd)
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
    # Records desired software; actual jar download happens via installer script hook.
    (DATA / "software.json").write_text(json.dumps({**body, "ts": time.time()}, indent=2))
    loader, mc = body.get("loader", "vanilla"), body.get("mc_version", "latest")
    lv = body.get("loader_version", "latest")
    hook = BASE / "scripts" / "install-server.sh"
    note = f"recorded {loader} {mc} build={lv}."
    if hook.exists():
        r = subprocess.run(["bash", str(hook), loader, mc, lv], capture_output=True, text=True, timeout=600)
        note += "\n" + (r.stdout + r.stderr)[-4000:]
    else:
        # minimal vanilla bootstrap so Server tab can start without hook
        note += " (no install-server.sh hook — set jar manually in Files/server.jar)."
    try:
        eula = SERVER_DIR / "eula.txt"
        if body.get("accept_eula") and eula.exists():
            eula.write_text(eula.read_text().replace("eula=false", "eula=true"))
    except Exception:
        pass
    return {"ok": True, "note": note, "java": java_for_mc(mc if mc != "latest" else "1.21", load_config())}

@app.get("/api/eula")
def eula(req: Request):
    need(req, "viewer")
    p = SERVER_DIR / "eula.txt"
    return {"exists": p.exists(), "text": p.read_text() if p.exists() else ""}

@app.post("/api/eula")
def eula_accept(req: Request, body: dict):
    need(req, "admin")
    (SERVER_DIR / "eula.txt").write_text("eula=true\n" if body.get("accept") else "eula=false\n")
    return {"ok": True}

# ---------- mods & plugins ----------
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
    return {"versions": [], "note": "pick file on CurseForge site; paste URL to /api/catalog/install-cf-url"}

@app.post("/api/catalog/install")
def catalog_install(req: Request, body: dict):
    need(req, "moderator")
    import requests as R
    source, kind = body.get("source", "modrinth"), body.get("kind", "mod")
    destdir = SERVER_DIR / ("mods" if kind == "mod" else "plugins")
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
    # curseforge direct file url install
    url = body.get("file_url", "")
    if not url:
        raise HTTPException(400, "file_url required for curseforge")
    fn = url.split("/")[-1].split("?")[0]
    (destdir / fn).write_bytes(R.get(url, timeout=60).content)
    return {"ok": True, "file": fn}

# ---------- files ----------
@app.get("/api/files")
def files(req: Request, path: str = ""):
    need(req, "viewer")
    p = safe_join(SERVER_DIR, path)
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
    p = safe_join(SERVER_DIR, body.get("path", ""))
    p.mkdir(parents=True, exist_ok=True)
    return {"ok": True}

@app.post("/api/files/delete")
def delete(req: Request, body: dict):
    need(req, "admin")
    p = safe_join(SERVER_DIR, body.get("path", ""))
    if p == SERVER_DIR.resolve():
        raise HTTPException(400, "refuse to delete server root")
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)
    return {"ok": True}

@app.post("/api/files/rename")
def rename(req: Request, body: dict):
    need(req, "moderator")
    src = safe_join(SERVER_DIR, body.get("src", ""))
    dst = safe_join(SERVER_DIR, body.get("dst", ""))
    src.rename(dst)
    return {"ok": True}

@app.post("/api/files/upload")
async def upload(req: Request, path: str = "", file: UploadFile = File(...)):
    need(req, "moderator")
    dest = safe_join(SERVER_DIR, path) / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    # auto-extract zips uploaded outside worlds (files tab convenience)
    if dest.suffix == ".zip" and (body_flag := req.query_params.get("extract")) == "1":
        with zipfile.ZipFile(dest) as z:
            z.extractall(dest.parent)
        dest.unlink()
    return {"ok": True, "file": file.filename}

# ---------- worlds ----------
@app.get("/api/worlds")
def worlds(req: Request):
    need(req, "viewer")
    out = []
    for w in ["world", "world_nether", "world_the_end"]:
        p = SERVER_DIR / w
        if p.exists():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            out.append({"name": w, "size": size})
    return {"worlds": out}

@app.get("/api/worlds/download")
def world_dl(req: Request, name: str = "world"):
    need(req, "viewer")
    src = safe_join(SERVER_DIR, name)
    tmp = DATA / f"{name}.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(SERVER_DIR))
    return FileResponse(str(tmp), filename=f"{name}.zip")

@app.post("/api/worlds/upload")
async def world_ul(req: Request, file: UploadFile = File(...)):
    need(req, "moderator")
    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "world import only accepts .zip")
    tmp = DATA / f"world-import-{int(time.time())}.zip"
    tmp.write_bytes(await file.read())
    # delete old world, extract new, delete leftover zip
    for w in ["world", "world_nether", "world_the_end"]:
        p = SERVER_DIR / w
        if p.exists():
            shutil.rmtree(p)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(SERVER_DIR)
    tmp.unlink(missing_ok=True)
    return {"ok": True, "note": "old world replaced, zip leftover deleted"}

# ---------- players ----------
BANTIME_HELP = "duration like 7d / 2h / 30m or 'forever'"

@app.post("/api/players/action")
def p_action(req: Request, body: dict):
    need(req, "moderator")
    name = body.get("name", "")
    act = body.get("action", "")
    dur = body.get("duration", "")
    if not name or not act:
        raise HTTPException(400, "name+action required")
    # map feed/kill which have no vanilla cmd: feed=saturate via effect/give, kill=kill
    mapping = {
        "op": f"op {name}", "deop": f"deop {name}",
        "kick": f"kick {name} {body.get('reason', 'kicked by VoHost')}",
        "kill": f"kill {name}", "feed": f"effect give {name} saturation 10 10",
        "ban": f"ban {name} {body.get('reason', '')}",
        "ban-ip": f"ban-ip {name} {body.get('reason', '')}",
        "pardon": f"pardon {name}", "pardon-ip": f"pardon-ip {name}",
    }
    if act == "tempban":
        # vanilla has no tempban; record expiry and ban now (unban via scheduler check)
        bans = {}
        try:
            bans = json.loads((DATA / "tempbans.json").read_text())
        except Exception:
            pass
        bans[name] = {"until": time.time() + _parse_dur(dur), "reason": body.get("reason", "")}
        (DATA / "tempbans.json").write_text(json.dumps(bans, indent=2))
        return SM.send_command(f"ban {name} temp {dur} {body.get('reason', '')}")
    if act not in mapping:
        raise HTTPException(400, f"unknown action {act} ({BANTIME_HELP})")
    return SM.send_command(mapping[act])

def _parse_dur(s: str) -> float:
    import re
    if s == "forever" or not s:
        return 10 * 365 * 86400
    m = re.match(r"(\d+)\s*([smhd])", s)
    if not m:
        return 86400
    n, u = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]

@app.get("/api/players/seen")
def p_seen(req: Request):
    need(req, "viewer")
    return {"players": NP.list_players_seen()}

@app.get("/api/players/data")
def p_data(req: Request, uuid: str):
    need(req, "moderator")
    return NP.read_inventory(uuid)

# ---------- options ----------
@app.get("/api/options")
def opts(req: Request):
    need(req, "viewer")
    props = OM.read_props()
    icon = SERVER_DIR / "server-icon.png"
    icon_b64 = base64.b64encode(icon.read_bytes()).decode() if icon.exists() else ""
    cfg = load_config()
    return {"props": props, "toggles": OM.TOGGLES, "icon": icon_b64,
            "timezone": props.get("_timezone", "UTC"), "env": props.get("_env", ""),
            "curseforge_key_set": bool(cfg.get("curseforge_api_key")),
            "discord_set": bool(cfg.get("discord_webhook"))}

@app.put("/api/options")
def opts_put(req: Request, body: dict):
    need(req, "moderator")
    props = body.get("props", {})
    OM.write_props(props)
    cfg = load_config()
    for k in ("curseforge_api_key", "discord_webhook", "timezone"):
        if k in body:
            cfg[k] = body[k]
    if "timezone" in (body.get("props", {}) or {}):
        pass
    save_config(cfg)
    if body.get("icon_b64"):
        (SERVER_DIR / "server-icon.png").write_bytes(base64.b64decode(body["icon_b64"]))
    # sync rcon password live
    if "rcon.password" in props:
        cfg["rcon"] = {"host": "127.0.0.1", "port": int(props.get("rcon.port", 25575)),
                       "password": props["rcon.password"]}
        save_config(cfg)
    return {"ok": True, "note": "saved live — restart server to apply server.properties (icon/MOTD apply on refresh)"}

# ---------- backups / scheduler / misc ----------
@app.get("/api/backups")
def bk_list(req: Request):
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
        return idx.read_text()
    return "<h1>VoHost</h1><p>frontend/ missing</p>"

def ensure_default_admin():
    pw = A.ensure_admin("admin", os.environ.get("VOHOST_ADMIN_PASS"))
    if pw:
        print(f"[VoHost] default admin created — user=admin pass={pw} (change in Access tab)")
