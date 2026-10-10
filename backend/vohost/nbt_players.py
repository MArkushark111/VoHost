"""Player inventory / enderchest inspection via NBT (nbtlib). Read-only in v1 + clear option."""
from pathlib import Path
from .config import SERVER_DIR

def _player_files():
    d = SERVER_DIR / "world" / "playerdata"
    return sorted(d.glob("*.dat")) if d.exists() else []

def list_players_seen():
    out = []
    for f in _player_files():
        out.append({"uuid": f.stem, "file": str(f)})
    # also ops / whitelist / bans for names
    import json
    for name, key in (("ops", "ops.json"), ("whitelist", "whitelist.json")):
        p = SERVER_DIR / key
        if p.exists():
            try:
                for e in json.loads(p.read_text()):
                    out.append({key: key, "name": e.get("name"), "uuid": e.get("uuid")})
            except Exception:
                pass
    return out

def read_inventory(uuid: str):
    import nbtlib
    f = SERVER_DIR / "world" / "playerdata" / f"{uuid}.dat"
    if not f.exists():
        return {"error": "no data (player never joined or different world name)"}
    nbt = nbtlib.load(str(f))
    def slot_list(tag):
        items = []
        try:
            for it in tag:
                items.append({"id": str(it.get("id", "")), "Count": int(it.get("Count", 0)),
                              "Slot": int(it.get("Slot", -1))})
        except Exception:
            pass
        return items
    return {"uuid": uuid,
            "Inventory": slot_list(nbt.get("Inventory", [])),
            "EnderItems": slot_list(nbt.get("EnderItems", []))}
