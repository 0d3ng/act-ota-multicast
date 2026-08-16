#!/bin/bash
set -e   # stop kalau ada step yang gagal, jangan lanjut diam-diam

# ============================================================
# KONFIGURASI — sesuaikan path ini
# ============================================================
FIRMWARE_PROJECT_DIR="$HOME/IotProjects/firmware-ota-rolling-key"   # ganti sesuai lokasi elo
ESP_IDF_DIR="$HOME/esp-idf"
OTA_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # folder act-ota-multicast, auto-detect

# ============================================================
# STEP 1: Load env vars buat OTA script
# ============================================================
echo "==> Loading .env.test..."
set -a
source "$OTA_SCRIPT_DIR/.env.test"
set +a

# Generate TARGET_VERSION unik tiap run (biar nggak collision di DB testing)
export TARGET_VERSION="test-$(git -C "$FIRMWARE_PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo local)-$(date +%s)"
echo "TARGET_VERSION=$TARGET_VERSION"

# ============================================================
# STEP 2: Build firmware pakai ESP-IDF
# ============================================================
echo "==> Loading ESP-IDF environment..."
. "$ESP_IDF_DIR/export.sh"

echo "==> Building firmware..."
cd "$FIRMWARE_PROJECT_DIR"
idf.py fullclean
idf.py set-target esp32
idf.py build -D FIRMWARE_VERSION="$TARGET_VERSION" -D FIRMWARE_ALGORITHM="ED25519" -D FIRMWARE_TLS=1

# ============================================================
# STEP 3: Copy hasil build ke folder OTA script
# ============================================================
echo "==> Copying built firmware to OTA script directory..."
mkdir -p "$OTA_SCRIPT_DIR/build"
cp "$FIRMWARE_PROJECT_DIR/build/firmware-ota-rolling-key.bin" "$OTA_SCRIPT_DIR/build/firmware-ota-rolling-key.bin"

# ============================================================
# STEP 4: Jalanin OTA release script (sign + upload ke SEMAR)
# ============================================================
echo "==> Running OTA release process..."
cd "$OTA_SCRIPT_DIR"
"$OTA_SCRIPT_DIR/venv/bin/python3" main.py

echo "==> Pipeline complete!"