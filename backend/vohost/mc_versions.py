"""Live version resolvers for all loaders. Cached 1h in data/. Uses only `requests`."""
import time, json, requests
from pathlib import Path
from .config import DATA

CACHE = DATA / "version_cache.json"
TTL = 3600
UA = {"User-Agent": "VoHost/1.0 (+https://github.com/MArkushark111/VoHost)"}

def _cache_get(key):
    try:
        db = json.loads(CACHE.read_text())
        e = db.get(key)
        if e and time.time() - e["ts"] < TTL:
            return e["data"]
    except Exception:
        pass
    return None

def _cache_put(key, data):
    try:
        db = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    except Exception:
        db = {}
    db[key] = {"ts": time.time(), "data": data}
    CACHE.write_text(json.dumps(db))

def _get(url, key):
    hit = _cache_get(key)
    if hit is not None:
        return hit
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    data = r.json()
    _cache_put(key, data)
    return data

LOADERS = [
    {"id": "vanilla", "name": "Vanilla", "supports": "mods:no plugins:no"},
    {"id": "snapshot", "name": "Snapshot", "supports": "mods:no plugins:no"},
    {"id": "paper", "name": "PaperMC", "supports": "mods:no plugins:yes"},
    {"id": "purpur", "name": "Purpur/Bukkit", "supports": "mods:no plugins:yes"},
    {"id": "spigot", "name": "Spigot/Bukkit", "supports": "mods:no plugins:yes"},
    {"id": "fabric", "name": "Fabric", "supports": "mods:yes plugins:no"},
    {"id": "quilt", "name": "Quilt", "supports": "mods:yes plugins:no"},
    {"id": "forge", "name": "Forge", "supports": "mods:yes plugins:no"},
    {"id": "neoforge", "name": "NeoForge", "supports": "mods:yes plugins:no"},
    {"id": "arclight", "name": "Arclight (mods+plugins)", "supports": "mods:yes plugins:yes"},
    {"id": "modpack", "name": "Modpacks (Modrinth/CF)", "supports": "mods:yes plugins:no"},
    {"id": "hytale", "name": "Hytale (bonus, manual jar)", "supports": "mods:no plugins:yes"},
]

def mc_versions() -> list[str]:
    data = _get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", "mojang-manifest")
    return [v["id"] for v in data["versions"] if v["type"] in ("release",)]

def snapshot_versions() -> list[str]:
    data = _get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json", "mojang-manifest")
    return [v["id"] for v in data["versions"] if v["type"] == "snapshot"][:50]

def fabric_loader_versions() -> list[str]:
    d = _get("https://meta.fabricmc.net/v2/versions/loader", "fabric-loader")
    return [x["version"] for x in d][:20]

def quilt_loader_versions() -> list[str]:
    d = _get("https://meta.quiltmc.org/v3/versions/loader", "quilt-loader")
    return [x["version"] for x in d][:20]

def paper_builds(mc: str) -> list[int]:
    """PaperMC build numbers via the Fill service (api.papermc.io/v2 was retired — 410)."""
    try:
        d = _get(f"https://fill.papermc.io/v3/projects/paper/versions/{mc}/builds", "paper-builds-" + mc)
        return [b.get("id") for b in d if isinstance(b, dict)][:20]
    except Exception:
        return []

def purpur_builds(mc: str) -> list[str]:
    try:
        d = _get(f"https://api.purpurmc.org/v2/purpur/{mc}", "purpur-" + mc)
        return d.get("builds", {}).get("all", [])[-20:]
    except Exception:
        return []

def neoforge_versions(mc: str | None = None) -> list[str]:
    # NeoForge has no simple version API; use maven metadata
    try:
        import xml.etree.ElementTree as ET
        r = requests.get("https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml", headers=UA, timeout=15)
        root = ET.fromstring(r.text)
        vs = [v.text for v in root.findall(".//version")][-30:]
        if mc:
            vs = [v for v in vs if v.startswith(mc.split(".")[0] + ".") or mc in v] or vs[-10:]
        return list(reversed(vs))[:20]
    except Exception:
        return []

def forge_versions(mc: str | None = None) -> list[str]:
    try:
        d = _get("https://files.minecraftforge.net/net/minecraftforge/forge/maven-metadata.json", "forge-meta") if False else None
    except Exception:
        pass
    # Use promotions file (reliable, small)
    try:
        d = _get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", "forge-promos")
        promos = d.get("promos", {})
        out = sorted(set(promos.values()))
        if mc:
            out = [v for v in out if v.startswith(mc + "-")] or out[-20:]
        return out[-20:]
    except Exception:
        return []
