#!/usr/bin/env bash
# VoHost server-jar installer hook — called by dashboard POST /api/software/install
# usage: install-server.sh <loader> <mc_version> <loader_version>
# env:   VOHOST_SERVER_DIR (target dir), VOHOST_SERVER_ID (per-server env file)
set -uo pipefail
LOADER="${1:-vanilla}"; MC="${2:-1.21}"; BUILD="${3:-latest}"
DEST="${VOHOST_SERVER_DIR:-${VOHOST_BASE:-/opt/vohost}/server}"
SID="${VOHOST_SERVER_ID:-}"
mkdir -p "$DEST"; cd "$DEST" || exit 1

have() { command -v "$1" >/dev/null 2>&1; }
ureq() { if have curl; then curl -fsSL "$1"; elif have wget; then wget -q -O - "$1"; else echo "ERROR: neither curl nor wget installed" >&2; return 1; fi; }
dl()   { if have curl; then curl -fsSL "$1" -o "$2"; elif have wget; then wget -q -O "$2" "$1"; else echo "ERROR: neither curl nor wget installed" >&2; return 1; fi; }

OK=0
case "$LOADER" in
  vanilla)
    URL="$(ureq https://piston-meta.mojang.com/mc/game/version_manifest_v2.json | python3 -c "import json,sys;m=json.load(sys.stdin);v=next((x for x in m['versions'] if x['id']=='$MC'),None);print(v['url'] if v else '')" 2>/dev/null)"
    if [ -z "$URL" ]; then echo "ERROR: MC version '$MC' not found in Mojang manifest." >&2
    else
      JAR="$(ureq "$URL" | python3 -c "import json,sys;print(json.load(sys.stdin)['downloads']['server']['url'])" 2>/dev/null)"
      dl "$JAR" server.jar && { echo "OK server.jar ($MC vanilla)"; OK=1; }
    fi ;;
  paper)
    B="$BUILD"; [ "$B" = latest ] && B="$(ureq https://api.papermc.io/v2/projects/paper/versions/$MC | python3 -c "import json,sys;print(max(json.load(sys.stdin)['builds']))" 2>/dev/null)"
    if [ -n "${B:-}" ]; then dl "https://api.papermc.io/v2/projects/paper/versions/$MC/builds/$B/downloads/paper-$MC-$B.jar" server.jar && { echo "OK server.jar (paper $MC build $B)"; OK=1; }; fi ;;
  purpur)
    B="$BUILD"; [ "$B" = latest ] && B="$(ureq https://api.purpurmc.org/v2/purpur/$MC | python3 -c "import json,sys;print(json.load(sys.stdin)['builds']['latest'])" 2>/dev/null)"
    if [ -n "${B:-}" ]; then dl "https://api.purpurmc.org/v2/purpur/$MC/$B/download" server.jar && { echo "OK server.jar (purpur $MC build $B)"; OK=1; }; fi ;;
  fabric)
    IV="$(ureq https://meta.fabricmc.net/v2/versions/installer | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['version'])" 2>/dev/null)"
    if [ -n "$IV" ]; then dl "https://meta.fabricmc.net/v2/versions/loader/$MC/$BUILD/$IV/server/jar" server.jar && { echo "OK server.jar (fabric $MC $BUILD)"; OK=1; }; fi ;;
  quilt)
    IV="$(ureq https://meta.quiltmc.org/v3/versions/installer | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['version'])" 2>/dev/null)"
    if [ -n "$IV" ]; then dl "https://meta.quiltmc.org/v3/versions/loader/$MC/$BUILD/$IV/server/jar" server.jar && { echo "OK server.jar (quilt $MC $BUILD)"; OK=1; }; fi ;;
  *)
    echo "loader $LOADER: manual install — put server.jar in $DEST (Hytale/modpack/forge/neoforge: upload the jar/zip via Files, or use the official installer)."
    OK=2 ;;
esac

if [ "$OK" = 0 ]; then
  echo "ERROR: could not download the server jar for $LOADER $MC (build=$BUILD)." >&2
  echo "Check the Minecraft version, or upload server.jar in the Files tab." >&2
fi

echo "eula=false" > eula.txt

# per-server Java pick -> /opt/vohost/data/mc-<id>.env (the systemd unit reads exactly this)
JAVA="$(VOHOST_BASE="${VOHOST_BASE:-/opt/vohost}" python3 -c "import sys; sys.path.insert(0,'/opt/vohost/backend'); from vohost.config import load_config,java_for_mc; print(java_for_mc('$MC', load_config()))" 2>/dev/null)"
[ -z "$JAVA" ] && JAVA=/usr/lib/jvm/temurin-21-jdk-amd64/bin/java
mkdir -p /opt/vohost/data 2>/dev/null
if [ -n "$SID" ]; then ENVF="/opt/vohost/data/mc-$SID.env"; else ENVF="/opt/vohost/data/mc.env"; fi
echo "JAVA=$JAVA" > "$ENVF" 2>/dev/null || echo "JAVA=$JAVA" > ./mc.env
echo "JAVA=$JAVA -> $ENVF"

[ "$OK" = 1 ] && echo "installed $LOADER $MC (build=$BUILD) -> $DEST/server.jar"
exit 0
