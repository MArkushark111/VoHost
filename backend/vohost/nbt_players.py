"""Player inventory / enderchest inspection + editing via NBT (nbtlib). Multi-server aware.

Vanilla stores each player in world/playerdata/<uuid>.dat. Usernames are resolved
from usercache.json first (works on vanilla/Fabric/Paper alike), then the NBT
'bukkit.lastKnownName' tag (Bukkit-family servers), then ops/whitelist entries.
"""
from pathlib import Path
from .config import SERVER_DIR

def _base(sdir=None) -> Path:
    return Path(sdir) if sdir else SERVER_DIR

def _uuid_norm(u) -> str:
    return str(u or "").replace("-", "").lower()

def _usercache_map(sdir=None) -> dict:
    """uuid_norm -> name from the server's usercache.json (written on every join)."""
    m = {}
    try:
        import json
        p = _base(sdir) / "usercache.json"
        if p.exists():
            for e in json.loads(p.read_text()):
                u = _uuid_norm(e.get("uuid"))
                nm = e.get("name") or ""
                if u and nm and u not in m:
                    m[u] = nm
    except Exception:
        pass
    return m

def _player_files(sdir=None):
    d = _base(sdir) / "world" / "playerdata"
    return sorted(d.glob("*.dat")) if d.exists() else []

def _name_from_dat(f: Path) -> str:
    """Best-effort username from a player's .dat ('bukkit.lastKnownName')."""
    try:
        import nbtlib
        nbt = nbtlib.load(str(f))
        buk = nbt.get("bukkit")
        nm = (buk or {}).get("lastKnownName")
        if nm:
            return str(nm)
    except Exception:
        pass
    return ""

def list_players_seen(sdir=None):
    """Seen players: playerdata files + usercache.json names + ops/whitelist names."""
    base = _base(sdir)
    uc = _usercache_map(sdir)
    out = []
    d = base / "world" / "playerdata"
    files = sorted(d.glob("*.dat"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []
    for f in files[:150]:
        uuid = f.stem
        nm = uc.get(_uuid_norm(uuid)) or _name_from_dat(f)
        out.append({"uuid": uuid, "name": nm, "file": str(f)})
    current = {o["uuid"]: o for o in out}
    # players known by name but with no .dat yet (never spawned / other world folder)
    for norm, nm in uc.items():
        if norm not in {_uuid_norm(o["uuid"]) for o in out}:
            dashed = f"{norm[0:8]}-{norm[8:12]}-{norm[12:16]}-{norm[16:20]}-{norm[20:32]}" if len(norm) == 32 else norm
            out.append({"uuid": dashed, "name": nm, "file": ""})
            current[dashed] = out[-1]
    import json
    for key in ("ops.json", "whitelist.json"):
        p = base / key
        if not p.exists():
            continue
        try:
            for e in json.loads(p.read_text()):
                u = e.get("uuid") or ""
                nm = e.get("name") or ""
                if u and u in current:
                    if nm and not current[u].get("name"):
                        current[u]["name"] = nm
                    current[u][key] = key
                elif nm:
                    out.append({key: key, "name": nm, "uuid": u, "file": ""})
        except Exception:
            pass
    return out

def _slot_list(tag):
    items = []
    try:
        for it in tag:
            try:
                count = int(it.get("Count", 0))
                if count <= 0:
                    continue  # MC-saved empty slots are noise
                items.append({"id": str(it.get("id", "")), "Count": count,
                              "Slot": int(it.get("Slot", -1))})
            except Exception:
                continue
    except Exception:
        pass
    return items

def read_profile(uuid: str, sdir=None):
    f = _base(sdir) / "world" / "playerdata" / f"{uuid}.dat"
    if not f.exists():
        return {"error": "no data (player never joined or different world name)"}
    try:
        import nbtlib
        nbt = nbtlib.load(str(f))
    except Exception as e:
        return {"error": f"could not read player NBT: {e}"}
    buk = nbt.get("bukkit")
    name = str((buk or {}).get("lastKnownName", "")) or ""
    if not name:
        # vanilla/Fabric files carry no name tag - fall back to usercache.json
        name = _usercache_map(sdir).get(_uuid_norm(uuid), "")
    return {"uuid": uuid, "name": name,
            "Inventory": _slot_list(nbt.get("Inventory", [])),
            "EnderItems": _slot_list(nbt.get("EnderItems", []))}

def delete_slot(uuid: str, slot, sdir=None, which: str = "Inventory"):
    """Remove one item by its Slot from the given list (Inventory or EnderItems)."""
    import nbtlib
    from nbtlib.tag import List, Compound
    if which not in ("Inventory", "EnderItems"):
        raise ValueError("which must be Inventory or EnderItems")
    f = _base(sdir) / "world" / "playerdata" / f"{uuid}.dat"
    if not f.exists():
        raise FileNotFoundError("no player data for " + uuid)
    nbt = nbtlib.load(str(f))
    slot = int(slot)
    lst = nbt.get(which)
    if lst is None:
        raise ValueError(f"no {which} compound in player file")
    keep = [it for it in lst if int(it.get("Slot", -1)) != slot]
    if len(keep) == len(lst):
        raise ValueError("no item at that slot")
    nbt[which] = List[Compound](keep)
    nbt.save(str(f))
    return {"ok": True, "uuid": uuid, "slot": slot, "from": which}

def clear_inv(uuid: str, sdir=None, ender: bool = False):
    """Clear the whole Inventory (or Ender chest) in the player's file."""
    import nbtlib
    from nbtlib.tag import List, Compound
    f = _base(sdir) / "world" / "playerdata" / f"{uuid}.dat"
    if not f.exists():
        raise FileNotFoundError("no player data for " + uuid)
    nbt = nbtlib.load(str(f))
    key = "EnderItems" if ender else "Inventory"
    lst = nbt.get(key)
    count = len([it for it in lst]) if lst is not None else 0
    nbt[key] = List[Compound]([])
    nbt.save(str(f))
    return {"ok": True, "uuid": uuid, "cleared": key, "removed": count}