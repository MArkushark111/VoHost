"""Multi-user auth with roles: admin / moderator / viewer. File-backed, stdlib only."""
import json, secrets, hashlib, time
from pathlib import Path
from .config import USERS_FILE

def _hash(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()

def _load():
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            pass
    return {"users": [], "sessions": {}}

def _save(db):
    USERS_FILE.write_text(json.dumps(db, indent=2))

def ensure_admin(username="admin", password=None):
    db = _load()
    if not any(u["username"] == username for u in db["users"]):
        pw = password or secrets.token_urlsafe(10)
        salt = secrets.token_hex(8)
        db["users"].append({"username": username, "role": "admin",
                            "salt": salt, "hash": _hash(pw, salt)})
        _save(db)
        return pw
    return None

def verify(username, password) -> dict | None:
    db = _load()
    for u in db["users"]:
        if u["username"] == username and u["hash"] == _hash(password, u["salt"]):
            return {"username": u["username"], "role": u["role"]}
    return None

def make_token(username, role) -> str:
    db = _load()
    tok = secrets.token_urlsafe(32)
    db["sessions"][tok] = {"username": username, "role": role, "ts": time.time()}
    _save(db)
    return tok

def check_token(tok: str) -> dict | None:
    if not tok:
        return None
    db = _load()
    return db["sessions"].get(tok)

def logout(tok: str):
    db = _load()
    db["sessions"].pop(tok, None)
    _save(db)

def list_users():
    db = _load()
    return [{"username": u["username"], "role": u["role"]} for u in db["users"]]

def upsert_user(username, password, role):
    assert role in ("admin", "moderator", "viewer")
    db = _load()
    salt = secrets.token_hex(8)
    entry = {"username": username, "role": role, "salt": salt, "hash": _hash(password, salt)}
    db["users"] = [u for u in db["users"] if u["username"] != username] + [entry]
    _save(db)

def delete_user(username):
    db = _load()
    db["users"] = [u for u in db["users"] if u["username"] != username]
    _save(db)

ROLE_RANK = {"viewer": 0, "moderator": 1, "admin": 2}
def require_role(user: dict | None, minimum: str) -> bool:
    if not user:
        return False
    return ROLE_RANK.get(user.get("role", ""), -1) >= ROLE_RANK[minimum]
