#!/usr/bin/env bash
# VoHost server-jar installer hook — called by dashboard POST /api/software/install
# usage: install-server.sh <loader> <mc_version> <loader_version>
set -euo pipefail
LOADER="${1:-vanilla}"; MC="${2:-1.21}"; BUILD="${3:-latest}"
DEST="${VOHOST_SERVER_DIR:-${VOHOST_BASE:-/opt/vohost}/server}"
mkdir -p "$DEST"; cd "$DEST"

dl() { wget -q -O "$2" "$1" && echo "OK $2"; }
case "$LOADER" in
  vanilla)
    URL="$(curl -fsSL https://piston-meta.mojang.com/mc/game/version_manifest_v2.json | python3 -c "import json,sys; m=json.load(sys.stdin); v=next(x for x in m['versions'] if x['id']=='$MC'); print(v['url'])")"
    JAR="$(curl -fsSL "$URL" | python3 -c "import json,sys; print(json.load(sys.stdin)['downloads']['server']['url'])")"
    dl "$JAR" server.jar ;;
  paper)
    B="${BUILD:-latest}"; [ "$B" = latest ] && B="$(curl -fsSL https://api.papermc.io/v2/projects/paper/versions/$MC | python3 -c "import json,sys; print(max(json.load(sys.stdin)['builds']))")"
    dl "https://api.papermc.io/v2/projects/paper/versions/$MC/builds/$B/downloads/paper-$MC-$B.jar" server.jar ;;
  purpur)
    B="${BUILD:-latest}"; [ "$B" = latest ] && B="$(curl -fsSL https://api.purpurmc.org/v2/purpur/$MC | python3 -c "import json,sys; print(json.load(sys.stdin)['builds']['latest'])")"
    dl "https://api.purpurmc.org/v2/purpur/$MC/$B/download" server.jar ;;
  fabric)
    LV="${BUILD:-latest}"; IV="$(curl -fsSL https://meta.fabricmc.net/v2/versions/installer | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['version'])")"
    dl "https://meta.fabricmc.net/v2/versions/loader/$MC/$LV/$IV/server/jar" server.jar ;;
  quilt)
    LV="${BUILD:-latest}"; IV="$(curl -fsSL https://meta.quiltmc.org/v3/versions/installer | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['version'])")"
    dl "https://meta.quiltmc.org/v3/versions/loader/$MC/$LV/$IV/server/jar" server.jar ;;
  *) echo "loader $LOADER: manual — place server.jar in $DEST (Hytale/modpack: upload zip/jar via Files tab)"; exit 0 ;;
esac
echo "eula=false" > eula.txt
# write mc.env java pick
PY="VOHOST_BASE=${VOHOST_BASE:-/opt/vohost} python3 -c \"from vohost.config import load_config,java_for_mc; c=load_config(); print('JAVA='+java_for_mc('$MC',c))\""
JAVA_LINE="$(cd /opt/vohost/backend 2>/dev/null && eval "$PY" || echo JAVA=/usr/lib/jvm/temurin-21-jdk-amd64/bin/java)"
echo "$JAVA_LINE" > /opt/vohost/data/mc.env 2>/dev/null || echo "$JAVA_LINE" > ./mc.env
echo "installed $LOADER $MC ($BUILD) -> $DEST/server.jar"
