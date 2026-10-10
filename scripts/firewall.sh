#!/usr/bin/env bash
# VoHost firewall — UFW: 22, 25565 (MC), 8080 (dashboard)
set -euo pipefail
DASH_PORT="${1:-8080}"
MC_PORT="${2:-25565}"

apt-get install -y ufw
ufw allow 22/tcp comment 'ssh' || true
ufw allow "${MC_PORT}"/tcp comment 'VoHost MC' || true
ufw allow "${MC_PORT}"/udp comment 'VoHost MC udp' || true
ufw allow "${DASH_PORT}"/tcp comment 'VoHost dashboard' || true
ufw --force enable
ufw status verbose
echo ""
echo "[VoHost] If players outside LAN cannot join, forward TCP+UDP ${MC_PORT} on your router to this server."
echo "[VoHost] No tunnel installed (per config). Guide: router NAT -> $(hostname -I | awk '{print $1}'):${MC_PORT}"
