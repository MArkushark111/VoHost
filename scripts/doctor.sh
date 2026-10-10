#!/usr/bin/env bash
# VoHost doctor — prints everything needed to debug "site can't be reached :8080".
# Run: curl -fsSL https://raw.githubusercontent.com/MArkushark111/VoHost/main/scripts/doctor.sh | sudo bash
set -uo pipefail
PORT="${1:-8080}"
echo "===== VoHost doctor (port $PORT) ====="
echo "--- IPs ---"; hostname -I 2>/dev/null || ip -brief addr 2>/dev/null || true
echo "--- layout ---"; ls /opt/vohost/ 2>&1; ls /opt/vohost/backend/ 2>&1 | head; ls /opt/vohost/frontend/ 2>&1 | head
echo "--- nested-copy bug? ---"; ls -d /opt/vohost/backend/backend /opt/vohost/frontend/frontend 2>&1 || echo "layout OK (no nesting)"
echo "--- venv ---"; /opt/vohost/venv/bin/python -V 2>&1; /opt/vohost/venv/bin/pip list 2>/dev/null | grep -iE "fastapi|uvicorn|psutil|nbtlib|requests|multipart" || echo "DEPS MISSING"
echo "--- import test ---"; cd /opt/vohost/backend && /opt/vohost/venv/bin/python -c "import app; print('import OK, front exists:', (app.FRONT).exists(), app.FRONT)" 2>&1 | tail -5
echo "--- systemd ---"; systemctl is-enabled vohost-dashboard 2>&1; systemctl is-active vohost-dashboard 2>&1
echo "--- listening? ---"; (ss -tlnp 2>/dev/null | grep -E ":$PORT|LISTEN") || netstat -tlnp 2>/dev/null | head -20 || echo "(ss/netstat unavailable)"
echo "--- localhost test ---"; curl -s -o /dev/null -w "localhost:$PORT -> %{http_code}\n" "http://127.0.0.1:$PORT/" 2>&1 || echo "localhost FAILED (service down, see journal below)"
echo "--- ufw ---"; ufw status 2>&1 | head -20 || echo "(ufw unavailable)"
echo "--- journal (last 40) ---"; journalctl -u vohost-dashboard -n 40 --no-pager --no-hostname -o cat 2>&1 || echo "(no journal)"
echo "===== end doctor ====="
echo "Paste ALL output above when asking for help."
