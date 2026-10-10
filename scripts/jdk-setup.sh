#!/usr/bin/env bash
# VoHost JDK setup — Temurin 8 / 17 / 21 / 25 on Ubuntu 26.04.1 LTS
set -euo pipefail
echo "[VoHost] Installing Temurin JDKs 8,17,21,25..."

apt-get update -y
apt-get install -y wget apt-transport-https gpg curl

# Adoptium repo
mkdir -p /etc/apt/keyrings
wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor | tee /etc/apt/keyrings/adoptium.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" | tee /etc/apt/sources.list.d/adoptium.list
apt-get update -y

for v in 8 17 21 25; do
  echo "[VoHost] -> temurin-$v-jdk"
  apt-get install -y "temurin-${v}-jdk" || echo "[VoHost] WARN: temurin-$v failed, trying default openjdk"
done

# Fallback mapping for MC -> java (overridden per-version in server_manager)
/usr/lib/jvm/temurin-8-jdk-amd64/bin/java -version 2>&1 | head -1 || true
/usr/lib/jvm/temurin-17-jdk-amd64/bin/java -version 2>&1 | head -1 || true
/usr/lib/jvm/temurin-21-jdk-amd64/bin/java -version 2>&1 | head -1 || true
/usr/lib/jvm/temurin-25-jdk-amd64/bin/java -version 2>&1 | head -1 || true

echo "[VoHost] JDKs done."
echo "8  -> /usr/lib/jvm/temurin-8-jdk-amd64/bin/java"
echo "17 -> /usr/lib/jvm/temurin-17-jdk-amd64/bin/java"
echo "21 -> /usr/lib/jvm/temurin-21-jdk-amd64/bin/java"
echo "25 -> /usr/lib/jvm/temurin-25-jdk-amd64/bin/java (fallback: 21 if 25 missing)"
