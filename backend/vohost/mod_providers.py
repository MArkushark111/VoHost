"""Modrinth + CurseForge search/install. No key needed for Modrinth; CF key from settings."""
import requests
from .config import load_config

UA = {"User-Agent": "VoHost/1.0"}

def modrinth_search(query, loader=None, mc=None, kind="mod", limit=20):
    """Search Modrinth. NOTE: never filters by mc-version on the API — unknown/snapshot
    versions make Modrinth return 400; we filter versions at install time instead."""
    facets = []
    if kind in ("mod", "plugin"):
        facets.append(["project_type:" + kind])
    if loader and loader.lower() in ("fabric", "forge", "quilt", "neoforge", "paper", "purpur", "spigot", "bukkit", "arclight", "modloader"):
        facets.append(["categories:" + loader.lower()])
    params = {"query": query or "", "limit": limit}
    if facets:
        import json as _j
        params["facets"] = _j.dumps(facets)
    r = requests.get("https://api.modrinth.com/v2/search", params=params, headers=UA, timeout=15)
    if r.status_code == 400:
        # retry without facets (e.g. bogus loader value)
        r = requests.get("https://api.modrinth.com/v2/search",
                         params={"query": query or "", "limit": limit}, headers=UA, timeout=15)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        out.append({"source": "modrinth", "id": h["project_id"], "slug": h.get("slug"),
                    "title": h.get("title"), "description": h.get("description"),
                    "icon": h.get("icon_url"), "downloads": h.get("downloads"),
                    "categories": h.get("categories")})
    return out

def _mc_pick(vs, mc):
    """Keep versions (newest-first) that match mc: exact game-version match first, then major.minor prefix."""
    if not mc:
        return vs
    exact = [v for v in vs if mc in v.get("game_versions", [])]
    if exact:
        return exact
    prefix = ".".join(mc.split(".")[:2])
    if prefix != mc:
        pre = [v for v in vs if prefix in v.get("game_versions", [])]
        if pre:
            return pre
    return []

def modrinth_versions(project_id, loader=None, mc=None, strict=False):
    r = requests.get(f"https://api.modrinth.com/v2/project/{project_id}/version", headers=UA, timeout=15)
    r.raise_for_status()
    vs = r.json()
    if loader:
        vs = [v for v in vs if loader.lower() in [l.lower() for l in v.get("loaders", [])]] or vs
    good = _mc_pick(vs, mc)
    if strict:
        vs = good
    else:
        vs = good or vs
    return [{"id": v["id"], "number": v["version_number"], "mc": v.get("game_versions"),
             "loaders": v.get("loaders"), "files": v.get("files")} for v in vs[:20]]

def curseforge_latest_file(mod_id, kind="mod", loader=None, mc=None):
    """Pick the newest CurseForge file for this mod that matches loader + game version."""
    cfg = load_config()
    key = cfg.get("curseforge_api_key", "")
    if not key:
        raise RuntimeError("CurseForge API key missing - paste it in Options (get one at console.curseforge.com).")
    ml_map = {"fabric": 4, "forge": 1, "quilt": 5, "neoforge": 6}
    headers = {"x-api-key": key}
    url = f"https://api.curseforge.com/v1/mods/{mod_id}/files"
    params = {"pageSize": 50}
    if loader and loader.lower() in ml_map:
        params["modLoaderType"] = ml_map[loader.lower()]
    if mc:
        params["gameVersion"] = mc
    r = requests.get(url, params=params, headers=headers, timeout=15)
    if r.status_code in (400, 403, 404) and "gameVersion" in params:
        params.pop("gameVersion", None)  # snapshot/unknown versions -> retry without
        r = requests.get(url, params=params, headers=headers, timeout=15)
    if r.status_code == 403:
        raise RuntimeError("CurseForge rejected the API key (403). Check the key in Options; keys look like $2a$10$...")
    r.raise_for_status()
    files = r.json().get("data", [])
    if not files:
        return None
    files.sort(key=lambda f: f.get("fileDate", ""), reverse=True)  # newest first
    f = files[0]
    dl = f.get("downloadUrl") or f.get("fileUrl")
    if not dl:
        return None  # files without direct download URLs need the CF installer app
    return {"fileId": f["id"], "name": f.get("displayName") or f.get("fileName"),
            "url": dl, "mc": f.get("gameVersions"), "loaders": f.get("modLoaders")}

def curseforge_search(query, kind="mod", mc=None, loader=None, limit=20):
    cfg = load_config()
    key = cfg.get("curseforge_api_key", "")
    if not key:
        raise RuntimeError("CurseForge API key missing — paste it in Options (get one at console.curseforge.com).")
    class_map = {"mod": 6, "plugin": 5, "modpack": 4471}
    ml_map = {"fabric": 4, "forge": 1, "quilt": 5, "neoforge": 6}
    params = {"gameId": 432, "searchFilter": query or "", "pageSize": limit,
              "classId": class_map.get(kind, 6)}
    # never pass a gameVersion: unknown versions (snapshots) cause 400 and we filter at install
    if loader and loader.lower() in ml_map:
        params["modLoaderType"] = ml_map[loader.lower()]
    headers = {"x-api-key": key}
    r = requests.get("https://api.curseforge.com/v1/mods/search", params=params, headers=headers, timeout=15)
    if r.status_code == 400 or r.status_code == 403:
        r = requests.get("https://api.curseforge.com/v1/mods/search",
                         params={"gameId": 432, "searchFilter": query or "", "pageSize": limit,
                                 "classId": class_map.get(kind, 6)}, headers=headers, timeout=15)
    if r.status_code == 403:
        raise RuntimeError("CurseForge rejected the API key (403). Check the key in Options; keys look like $2a$10$...")
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        logo = (m.get("logo") or {}).get("url")
        out.append({"source": "curseforge", "id": m["id"], "slug": m.get("slug"),
                    "title": m.get("name"), "description": m.get("summary"),
                    "icon": logo, "downloads": m.get("downloadCount")})
    return out
