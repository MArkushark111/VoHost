#!/usr/bin/env bash
# VoHost CLI — `vohost` reopens the log window closed with Q.
# Usage: vohost [logs|status|start|stop|restart|dashboard|help]
set -uo pipefail
CMD="${1:-logs}"

case "$CMD" in
  logs|"")
    exec bash /opt/vohost/scripts/log-window.sh
    ;;
  status)
    systemctl status vohost-dashboard vohost-mc --no-pager
    ;;
  start|stop|restart)
    systemctl "$CMD" vohost-mc
    systemctl status vohost-mc --no-pager -n 20
    ;;
  dashboard)
    systemctl status vohost-dashboard --no-pager -n 20
    ;;
  help|-h|--help)
    echo "VoHost commands:"
    echo "  vohost           reopen log window (same as vohost logs, q closes window only)"
    echo "  vohost logs      live logs (mc + dashboard)"
    echo "  vohost status    systemd status of dashboard + mc"
    echo "  vohost start|stop|restart   control MC server"
    echo "  vohost dashboard status of dashboard service"
    ;;
  *)
    echo "Unknown: $CMD (try: vohost help)"
    exit 1
    ;;
esac
