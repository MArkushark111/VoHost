#!/usr/bin/env bash
# VoHost log window — shows live logs, 'q' closes window only (services keep running via systemd).
# Used at end of install.sh and via `vohost` / `vohost-logs` commands.
set -uo pipefail
echo "=== VoHost live logs (press 'q' to close window, server keeps running) ==="
echo "Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo "Services : vohost-dashboard + vohost-mc (systemctl status ...)"
echo "----------------------------------------------------------------"

tail_pids=()
cleanup() { for p in "${tail_pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; echo; echo "[VoHost] window closed. Server still running in background (systemd)."; exit 0; }
trap cleanup EXIT INT TERM

journalctl -u vohost-mc -u vohost-dashboard -f --no-hostname -o cat 2>/dev/null &
tail_pids+=($!)
# fallback file logs
for f in /opt/vohost/logs/dashboard.log /opt/vohost/server/logs/latest.log; do
  [ -f "$f" ] && tail -F "$f" 2>/dev/null &
  [ -f "$f" ] && tail_pids+=($!)
done

echo "[q] close window >"
while true; do
  IFS= read -rsn1 key || break
  if [ "$key" = "q" ] || [ "$key" = "Q" ]; then
    cleanup
  fi
done
