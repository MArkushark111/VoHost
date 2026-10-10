#!/usr/bin/env bash
# VoHost one-shot installer — Ubuntu Server 26.04.1 LTS
# - JDKs (Temurin 8/17/21/25)  - UFW (22,25565,8080)  - systemd startup  - dashboard :8080
# - log window (q closes window only)
set -euo pipefail
DASH_PORT="${DASH_PORT:-8080}"
MC_PORT="${MC_PORT:-25565}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="/opt/vohost"

if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo bash install.sh"; exit 1; fi
echo "=== VoHost installer (Ubuntu 26.04.1) ==="

apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl wget unzip ufw sudo

# JDKs
bash "$SRC_DIR/scripts/jdk-setup.sh"

# layout
mkdir -p "$DEST" /opt/vohost/{backend,data,logs,backups,server,scripts}
cp -r "$SRC_DIR/backend" "$DEST/" 2>/dev/null || cp -r "$SRC_DIR/backend/"* "$DEST/backend/"
cp -r "$SRC_DIR/frontend" "$DEST/" 2>/dev/null || true
cp "$SRC_DIR/scripts/"*.sh "$DEST/scripts/" 2>/dev/null || cp "$SRC_DIR/scripts/"* "$DEST/scripts/" 2>/dev/null || true
[ -f "$SRC_DIR/scripts/install-server.sh" ] && cp "$SRC_DIR/scripts/install-server.sh" "$DEST/scripts/" || true
chmod +x "$DEST/scripts/"*.sh || true

# venv
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --upgrade pip
"$DEST/venv/bin/pip" install -r "$DEST/backend/requirements.txt"

# admin password
ADMIN_PASS="${VOHOST_ADMIN_PASS:-$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)}"
echo "$ADMIN_PASS" > "$DEST/data/.admin-pass"
export VOHOST_ADMIN_PASS="$ADMIN_PASS"

# firewall
DASH_PORT="$DASH_PORT" MC_PORT="$MC_PORT" bash "$DEST/scripts/firewall.sh" "$DASH_PORT" "$MC_PORT" || bash "$SRC_DIR/scripts/firewall.sh" "$DASH_PORT" "$MC_PORT" || true

# systemd units (rewrite port via drop-in env if custom)
sed "s/--port 8080/--port $DASH_PORT/" "$SRC_DIR/systemd/vohost-dashboard.service" > /etc/systemd/system/vohost-dashboard.service
cp "$SRC_DIR/systemd/vohost-mc.service" /etc/systemd/system/vohost-mc.service
cp "$SRC_DIR/systemd/vohost-mc@.service" /etc/systemd/system/vohost-mc@.service
ln -sf "$DEST/scripts/log-window.sh" /usr/local/bin/vohost-logs
ln -sf "$DEST/scripts/vohost.sh" /usr/local/bin/vohost
chmod +x /usr/local/bin/vohost-logs /usr/local/bin/vohost
systemctl daemon-reload
systemctl enable --now vohost-dashboard
systemctl enable vohost-mc || true

# timezone default
timedatectl set-timezone UTC 2>/dev/null || true

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "=== VoHost installed ==="
echo "Dashboard : http://$IP:$DASH_PORT"
echo "Admin     : admin / $ADMIN_PASS  (change in Access tab; saved in $DEST/data/.admin-pass)"
echo "MC port   : $MC_PORT (UFW open; forward it on router for outside LAN)"
echo "Services  : systemctl status vohost-dashboard vohost-mc"
echo "Logs cmd  : vohost (or vohost-logs) — reopens window, press q to close, server keeps running"
echo ""
echo "Opening live log window (q to close)..."
bash "$DEST/scripts/log-window.sh" || true
