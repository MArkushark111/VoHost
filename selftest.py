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
r = c.get("/api/backups"); check("backups", r.status_code == 200, r.text)
r = c.get("/api/users"); check("users", r.status_code == 200, r.text)
r = c.post("/api/servers", json={"name": "test1", "network_mode": "lan", "memory_max": "2G"})
check("create server", r.status_code == 200, r.text)
sid = r.json().get("server", {}).get("id", "")
r = c.get("/api/status?server_id=" + sid); check("status per-server", r.status_code == 200, r.text)
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