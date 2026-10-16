VoHost — Minecraft Hosting Panel for Ubuntu Server
================================================

Browser dashboard + systemd background hosting. `q` only closes the log window.

Quick install (Ubuntu Server 26.04.1 LTS):
  curl -fsSL https://raw.githubusercontent.com/YOU/VoHost/main/install.sh | sudo bash
  # or:
  # sudo bash install.sh

Dashboard: http://SERVER-IP:8080  (default admin created at install, then multi-user via Access tab)

Layout:
  backend/    FastAPI dashboard (port 8080)
  frontend/   Single-page UI (served by backend, no build step)
  systemd/    vohost-dashboard.service + vohost-mc.service
  scripts/    jdk-setup.sh, firewall.sh, log-window.sh
  install.sh  One-shot installer (JDKs, UFW, systemd, venv, startup)

Features:
- Software: vanilla / snapshot / fabric / quilt / forge / neoforge / paper / purpur / spigot-bukkit / arclight / modpacks / hytale(bonus-manual)
- Mods / Plugins: Modrinth + CurseForge (own API key in settings) with icon, desc, version picker
- Files: tree, mkdir, upload files/folders, download, delete, rename
- Worlds: download zip, upload zip (auto-extract + cleanup)
- Players: op/deop, kick, kill, feed, ban/ban-ip (perm + timed), pardon, inventory + enderchest view (NBT)
- Options: name, icon, MOTD, slots, gamemode, difficulty, whitelist, fly, force-gamemode, spawn-protection, resource-pack + require + prompt, timezone/env toggles
- Server: start/stop/restart/kill + CPU/RAM/TPS graphs
- Console: WS terminal with ANSI colors. Log: tail with colors.
- Backups: manual + cron scheduler + restore (fixes red-warning state)
- Access: multi-user + roles (admin / moderator / viewer)
- Scheduler + Discord webhook, EULA prompt, UFW guide, DuckDNS auto-subdomain, flood protection (SYN hardening, per-IP conn limits, SSH limit, login brute-force lockout), push limits mode (full machine resources for one server), Simple Voice Chat one-click (UDP 24454), scheduled shutdown/startup times
