#!/usr/bin/env bash
# VoHost repair — fixes every known "can't connect to :8080" cause in one shot.
# Run: curl -fsSL https://raw.githubusercontent.com/MArkushark111/VoHost/main/scripts/repair.sh | sudo bash
set -uo pipefail
PORT="${VOHOST_PORT:-8080}"
echo "===== VoHost repair ====="

echo "[1/8] fetching latest source"
rm -rf /tmp/vohost-src /tmp/VoHost-main
wget -qO /tmp/vohost.tar.gz https://github.com/MArkushark111/VoHost/archive/refs/heads/main.tar.gz
tar xzf /tmp/vohost.tar.gz -C /tmp
SRC=/tmp/VoHost-main

echo "[2/8] fixing layout (removes nested backend/backend)"
mkdir -p /opt/vohost/{backend,data,logs,backups,server,scripts,frontend}
cp -r "$SRC/backend/." /opt/vohost/backend/
cp -r "$SRC/frontend/." /opt/vohost/frontend/
cp "$SRC/scripts/"*.sh /opt/vohost/scripts/ 2>/dev/null || true
cp "$SRC/systemd/"*.service /tmp/ 2>/dev/null || true
rm -rf /opt/vohost/backend/backend /opt/vohost/frontend/frontend
chmod +x /opt/vohost/scripts/*.sh 2>/dev/null || true
ls /opt/vohost/backend/app.py && ls /opt/vohost/frontend/index.html

echo "[3/8] python venv + deps"
apt-get install -y python3 python3-venv python3-pip curl wget unzip >/dev/null 2>&1 || true
rm -rf /opt/vohost/venv
python3 -m venv /opt/vohost/venv
/opt/vohost/venv/bin/pip install --upgrade pip -q
/opt/vohost/venv/bin/pip install -r /opt/vohost/backend/requirements.txt -q

echo "[4/8] import self-test"
( cd /opt/vohost/backend && /opt/vohost/venv/bin/python -c "import app; print('import OK front=', app.FRONT.exists())" ) || { echo "IMPORT FAILED — paste below:"; cd /opt/vohost/backend && /opt/vohost/venv/bin/python -c "import app"; }

echo "[5/8] systemd unit (port $PORT)"
cat > /etc/systemd/system/vohost-dashboard.service <<EOF
[Unit]
Description=VoHost Dashboard
After=network.target
[Service]
Type=simple
User=root
Environment=VOHOST_BASE=/opt/vohost
WorkingDirectory=/opt/vohost/backend
ExecStart=/opt/vohost/venv/bin/uvicorn app:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
cp "$SRC/systemd/vohost-mc.service" /etc/systemd/system/ 2>/dev/null || true
cp "$SRC/systemd/vohost-mc@.service" /etc/systemd/system/ 2>/dev/null || true

echo "[6/8] restart dashboard"
systemctl daemon-reload
systemctl enable vohost-dashboard >/dev/null 2>&1 || true
systemctl restart vohost-dashboard
sleep 4
systemctl is-active vohost-dashboard

echo "[7/8] firewall"
ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow "$PORT"/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

echo "[8/8] self-test"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if curl -fs "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
  echo "SUCCESS — open in browser:  http://$IP:$PORT"
else
  echo "STILL DOWN — paste this output:"
  systemctl status vohost-dashboard --no-pager -n 20 || true
  journalctl -u vohost-dashboard -n 60 --no-pager --no-hostname -o cat || true
  ss -tlnp 2>/dev/null | grep LISTEN || true
fi
echo "IPs: $(hostname -I)"
echo "===== done ====="
