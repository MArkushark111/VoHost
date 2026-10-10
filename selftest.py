"""Boot the real app against a temp VOHOST_BASE and exercise every endpoint the UI calls, no MC required."""
import os, tempfile, json, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
tmp = tempfile.mkdtemp(prefix="vh-test-")
os.environ["VOHOST_BASE"] = tmp
from fastapi.testclient import TestClient
import app as A

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

r = c.get("/"); check("index page", r.status_code == 200 and "VoHost" in r.text, r.text[:100])
r = c.get("/assets/app.js"); check("assets js", r.status_code == 200, r.text[:60])
r = c.get("/assets/style.css"); check("assets css", r.status_code == 200, r.text[:40])

# 5. unauth guards
c2 = TestClient(A.app)
r = c2.get("/api/servers"); check("unauth 401", r.status_code == 401, r.text)

print()
print("ERRORS:", len(errors))
for e in errors: print("  -", e)
sys.exit(1 if errors else 0)