"""Modrinth + CurseForge search/install. No key needed for Modrinth; CF key from settings."""
import requests
from .config import load_config

UA = {"User-Agent": "VoHost/1.0"}

def modrinth_search(query, loader=None, mc=None, kind="mod", limit=20):
    facets = []
    if kind in ("mod", "plugin"):
        facets.append(f'["project_type:{kind}"]')
    if loader:
        facets.append(f'["categories:{loader.lower()}"]')
    if mc:
        facets.append(f'["versions:{mc}"]')
    params = {"query": query or "", "limit": limit}
    if facets:
        import json as _j
        params["facets"] = _j.dumps(facets)
    r = requests.get("https://api.modrinth.com/v2/search", params=params, headers=UA, timeout=15)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        out.append({"source": "modrinth", "id": h["project_id"], "slug": h.get("slug"),
                    "title": h.get("title"), "description": h.get("description"),
                    "icon": h.get("icon_url"), "downloads": h.get("downloads"),
                    "categories": h.get("categories")})
    return out

def modrinth_versions(project_id, loader=None, mc=None):
    r = requests.get(f"https://api.modrinth.com/v2/project/{project_id}/version", headers=UA, timeout=15)
    r.raise_for_status()
    vs = r.json()
    if loader:
        vs = [v for v in vs if loader.lower() in [l.lower() for l in v.get("loaders", [])]] or vs
    if mc:
        vs = [v for v in vs if mc in v.get("game_versions", [])] or vs
    return [{"id": v["id"], "number": v["version_number"], "mc": v.get("game_versions"),
             "loaders": v.get("loaders"), "files": v.get("files")} for v in vs[:20]]

def curseforge_search(query, kind="mod", mc=None, loader=None, limit=20):
    cfg = load_config()
    key = cfg.get("curseforge_api_key", "")
    if not key:
        raise RuntimeError("CurseForge API key missing — paste it in Software/Settings (get one at console.curseforge.com).")
    class_map = {"mod": 6, "plugin": 5, "modpack": 4471}
    params = {"gameId": 432, "searchFilter": query or "", "pageSize": limit,
              "classId": class_map.get(kind, 6)}
    if mc:
        params["gameVersion"] = mc
    if loader:
        params["modLoaderType"] = {"fabric": 4, "forge": 1, "quilt": 5, "neoforge": 6}.get(loader.lower(), 0) or None
        params = {k: v for k, v in params.items() if v}
    r = requests.get("https://api.curseforge.com/v1/mods/search", params=params,
                     headers={"x-api-key": key}, timeout=15)
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        logo = (m.get("logo") or {}).get("url")
        out.append({"source": "curseforge", "id": m["id"], "slug": m.get("slug"),
                    "title": m.get("name"), "description": m.get("summary"),
                    "icon": logo, "downloads": m.get("downloadCount")})
    return out
