#!/usr/bin/env bash
# VoHost one-shot installer — Ubuntu Server 26.04.1 LTS
# - JDKs (Temurin 8/17/21/25)  - UFW (22,25565,8080)  - systemd startup  - dashboard :8080
# - log window (q closes window only)
set -euo pipefail
DASH_PORT="${DASH_PORT:-8080}"
MC_PORT="${MC_PORT:-25565}"
REPO="${VOHOST_REPO:-MArkushark111/VoHost}"
BRANCH="${VOHOST_BRANCH:-main}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo /tmp/vohost-src)"
DEST="/opt/vohost"

if [ "$(id -u)" -ne 0 ]; then echo "Run as root: sudo bash install.sh"; exit 1; fi
echo "=== VoHost installer (Ubuntu 26.04.1) ==="

# Self-bootstrap: supports `curl ... | sudo bash` where $0 has no repo files.
if [ ! -f "$SRC_DIR/scripts/jdk-setup.sh" ]; then
  echo "[VoHost] no local source at $SRC_DIR — fetching $REPO@$BRANCH from GitHub..."
  apt-get update -y
  apt-get install -y curl wget ca-certificates tar
  rm -rf /tmp/vohost-src "/tmp/VoHost-$BRANCH"
  wget -qO /tmp/vohost.tar.gz "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
  tar xzf /tmp/vohost.tar.gz -C /tmp
  SRC_DIR="/tmp/VoHost-$BRANCH"
  [ -f "$SRC_DIR/scripts/jdk-setup.sh" ] || { echo "[VoHost] FATAL: bootstrap failed, $SRC_DIR/scripts/jdk-setup.sh missing"; exit 1; }
  echo "[VoHost] source ready at $SRC_DIR"
fi

apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl wget unzip ufw sudo

# JDKs — non-fatal: dashboard works without Java, MC needs it later.
bash "$SRC_DIR/scripts/jdk-setup.sh" || echo "[VoHost] WARN: JDK setup failed, continuing (install Java later, dashboard still works)"

# layout — idempotent: safe on first install AND reinstall (no backend/backend nesting)
mkdir -p "$DEST" /opt/vohost/{backend,data,logs,backups,server,scripts}
mkdir -p "$DEST/backend" "$DEST/frontend"
cp -r "$SRC_DIR/backend/." "$DEST/backend/"
cp -r "$SRC_DIR/frontend/." "$DEST/frontend/"
cp "$SRC_DIR/scripts/"*.sh "$DEST/scripts/" || true
# repair previous nested copies from older installer revisions
if [ -d "$DEST/backend/backend" ]; then cp -r "$DEST/backend/backend/." "$DEST/backend/"; rm -rf "$DEST/backend/backend"; fi
if [ -d "$DEST/frontend/frontend" ]; then cp -r "$DEST/frontend/frontend/." "$DEST/frontend/"; rm -rf "$DEST/frontend/frontend"; fi
chmod +x "$DEST/scripts/"*.sh || true

# CLI shortcuts FIRST — so `vohost` exists even if a later step fails.
# Link into both /usr/local/bin and /usr/bin (/usr/bin is always in PATH).
for b in /usr/local/bin /usr/bin; do
  [ -d "$b" ] || continue
  ln -sf "$DEST/scripts/vohost.sh" "$b/vohost" || true
  ln -sf "$DEST/scripts/log-window.sh" "$b/vohost-logs" || true
  chmod +x "$b/vohost" "$b/vohost-logs" 2>/dev/null || true
done
hash -r 2>/dev/null || true

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
# re-assert links at the end too (idempotent repair on every reinstall)
for b in /usr/local/bin /usr/bin; do
  [ -d "$b" ] || continue
  ln -sf "$DEST/scripts/vohost.sh" "$b/vohost" || true
  ln -sf "$DEST/scripts/log-window.sh" "$b/vohost-logs" || true
  chmod +x "$b/vohost" "$b/vohost-logs" 2>/dev/null || true
done
systemctl daemon-reload
systemctl enable vohost-dashboard || true
systemctl enable vohost-mc || true
systemctl restart vohost-dashboard || systemctl start vohost-dashboard || true
# self-test: dashboard must answer on localhost, else dump logs for the user
sleep 3
if curl -fs "http://127.0.0.1:$DASH_PORT/" >/dev/null 2>&1; then
  echo "[VoHost] dashboard OK on :$DASH_PORT"
else
  echo "[VoHost] WARN: dashboard not answering on :$DASH_PORT — running doctor:"
  bash "$DEST/scripts/doctor.sh" "$DASH_PORT" || journalctl -u vohost-dashboard -n 30 --no-pager --no-hostname -o cat || true
fi

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
hash -r 2>/dev/null || true
if command -v vohost >/dev/null 2>&1; then
  echo "[VoHost] CLI check OK: $(command -v vohost) -> $(readlink -f $(command -v vohost))"
else
  echo "[VoHost] FATAL: vohost not on PATH (checked /usr/local/bin + /usr/bin). echo \$PATH to debug."
fi
bash "$DEST/scripts/log-window.sh" || true
