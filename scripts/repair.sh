#!/usr/bin/env bash
# VoHost repair — fixes every known "can't connect to :8080" cause in one shot.
# Safer two-step run (avoids executing a half-downloaded script):
#   curl -fsSL -o /tmp/repair.sh https://raw.githubusercontent.com/MArkushark111/VoHost/main/scripts/repair.sh && sudo bash /tmp/repair.sh
set -uo pipefail
PORT="${VOHOST_PORT:-8080}"
echo "===== VoHost repair ====="
FAILED=0

fail() { echo "!!! REPAIR FAILED: $1"; echo "!!! Fix the above, then re-run this script."; exit 1; }
warn() { echo "!!! WARNING: $1 (continuing)"; }

echo "[1/8] fetching latest source"
rm -rf /tmp/vohost-src /tmp/VoHost-main /tmp/vohost.tar.gz
ok_dl=0
for i in 1 2 3; do
  if wget -qO /tmp/vohost.tar.gz https://github.com/MArkushark111/VoHost/archive/refs/heads/main.tar.gz && [ -s /tmp/vohost.tar.gz ]; then ok_dl=1; break; fi
  echo "download attempt $i failed, retrying..."; sleep 3
done
[ "$ok_dl" = 1 ] || fail "could not download the VoHost source tarball (network to github.com blocked?)"
tar tzf /tmp/vohost.tar.gz >/dev/null 2>&1 || fail "downloaded tarball is corrupt (proxy/cache issue?) - delete /tmp/vohost.tar.gz and re-run"
tar xzf /tmp/vohost.tar.gz -C /tmp || fail "could not extract the tarball (disk full?)"
SRC=/tmp/VoHost-main
[ -f "$SRC/backend/app.py" ] || fail "extracted source has no backend/app.py - bad download, re-run"
[ -f "$SRC/frontend/index.html" ] || fail "extracted source has no frontend/index.html - bad download, re-run"

echo "[2/8] fixing layout (removes nested backend/backend)"
mkdir -p /opt/vohost/{backend,data,logs,backups,server,scripts,frontend}
cp -r "$SRC/backend/." /opt/vohost/backend/ || fail "copy backend failed (disk full or read-only fs?)"
cp -r "$SRC/frontend/." /opt/vohost/frontend/ || fail "copy frontend failed (disk full or read-only fs?)"
cp "$SRC/scripts/"*.sh /opt/vohost/scripts/ 2>/dev/null || true
cp "$SRC/systemd/"*.service /tmp/ 2>/dev/null || true
rm -rf /opt/vohost/backend/backend /opt/vohost/frontend/frontend
chmod +x /opt/vohost/scripts/*.sh 2>/dev/null || true
[ -f /opt/vohost/backend/app.py ] && [ -f /opt/vohost/frontend/index.html ] || fail "deploy copy incomplete"

echo "[3/8] python venv + deps"
if command -v fuser >/dev/null 2>&1; then
  for i in $(seq 1 24); do
    if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 && ! fuser /var/lib/dpkg/lock >/dev/null 2>&1; then break; fi
    echo "waiting for apt lock ($i/24)..."; sleep 5
  done
fi
df_avail_kb="$(df /opt/vohost 2>/dev/null | awk 'NR==2{print $4}')"
if [ -n "$df_avail_kb" ] && [ "$df_avail_kb" -lt 500000 ]; then warn "disk low (${df_avail_kb}KB free on /opt/vohost) - cleanup backups/worlds if install fails"; fi
apt-get install -y python3 python3-venv python3-pip curl wget unzip >/tmp/vohost-apt.log 2>&1 || warn "apt install had errors - see /tmp/vohost-apt.log"
rm -rf /opt/vohost/venv
python3 -m venv /opt/vohost/venv >/tmp/vohost-venv.log 2>&1 || { tail -15 /tmp/vohost-venv.log; fail "python venv creation failed (run: sudo apt install -y python3-venv)"; }
[ -x /opt/vohost/venv/bin/python ] || fail "venv has no python binary - broken python3-venv, reinstall it"
/opt/vohost/venv/bin/pip install --upgrade pip -q >/tmp/vohost-pip.log 2>&1 || true
/opt/vohost/venv/bin/pip install -r /opt/vohost/backend/requirements.txt >>/tmp/vohost-pip.log 2>&1 || { echo "--- pip failed, last lines: ---"; tail -20 /tmp/vohost-pip.log; fail "pip install failed - full log in /tmp/vohost-pip.log (usually no network to pypi.org)"; }

echo "[4/8] import self-test"
( cd /opt/vohost/backend && /opt/vohost/venv/bin/python -c "import app; print('import OK front=', app.FRONT.exists())" ) || fail "backend import failed - code or dependency problem, output above"

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
# clear any crash-loop lockout on minecraft units so they can start again after the fix
for u in $(systemctl list-units --type=service --all --no-legend 'vohost-mc@*' 2>/dev/null | awk '{print $1}'); do systemctl reset-failed "$u" >/dev/null 2>&1 || true; done
systemctl reset-failed vohost-mc >/dev/null 2>&1 || true
sleep 4
systemctl is-active vohost-dashboard || warn "dashboard service is not active - see step 8 diagnostics"

echo "[7/8] firewall"
ufw allow 22/tcp >/dev/null 2>&1 || true
ufw allow "$PORT"/tcp >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

echo "[8/8] self-test + accounts"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if curl -fs "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
  echo "SUCCESS — open in browser:  http://$IP:$PORT"
  PASS="$(tr -d '\n\r ' < /opt/vohost/data/.admin-pass 2>/dev/null || true)"
  if [ -n "$PASS" ]; then
    CODE="$(curl -s -o /tmp/vh-login.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/api/login" -H 'Content-Type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS\"}")"
    if [ "$CODE" = "200" ]; then
      echo "LOGIN TEST: admin / \$data/.admin-pass  ->  LOGIN OK"
    else
      echo "LOGIN TEST FAILED (HTTP $CODE) — auto-resetting accounts so 'Create admin' shows:"
      reset_accounts=1
    fi
  else
    echo "no .admin-pass — checking for existing users..."
    if [ -s /opt/vohost/data/users.json ] && grep -q '"users"' /opt/vohost/data/users.json; then
      reset_accounts=1
    fi
  fi
else
  echo "STILL DOWN — dashboard not answering; pasting diagnostics:"
  systemctl status vohost-dashboard --no-pager -n 20 || true
  journalctl -u vohost-dashboard -n 60 --no-pager --no-hostname -o cat || true
  ss -tlnp 2>/dev/null | grep LISTEN || true
  reset_accounts=1
fi

if [ "${reset_accounts:-0}" = "1" ]; then
  echo ""
  echo ">>> Resetting accounts so the web UI shows 'Create admin' (this is the fix)..."
  rm -f /opt/vohost/data/users.json /opt/vohost/data/.admin-pass
  systemctl restart vohost-dashboard
  sleep 3
  if curl -fs "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    echo ">>> DONE: open  http://$IP:$PORT  -> button says 'Create admin' -> pick your own user+pass."
  else
    echo ">>> Still down after reset — paste the STILL DOWN diagnostics above."
    FAILED=1
  fi
else
  echo "Accounts kept (working login verified)."
fi
echo "IPs: $(hostname -I)"
if [ "$FAILED" = 1 ]; then echo "===== done WITH ERRORS ====="; else echo "===== done ====="; fi
exit "$FAILED"
