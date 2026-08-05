#!/bin/bash
# Flutter for Termux ARM64 - One-click installer
# https://github.com/ImL1s/termux-flutter-wsl

set -euo pipefail

DO_UPGRADE=false
for arg in "$@"; do
    if [ "$arg" == "--upgrade" ]; then
        DO_UPGRADE=true
    fi
done

declare -A STAGE_STATUS
record_stage() {
    STAGE_STATUS[$1]=$2
}
print_summary() {
    echo "{"
    local first=1
    for stage in "${!STAGE_STATUS[@]}"; do
        if [ $first -eq 0 ]; then echo ","; fi
        echo -n "  \"$stage\": \"${STAGE_STATUS[$stage]}\""
        first=0
    done
    echo ""
    echo "}"
}
trap print_summary EXIT

FLUTTER_VERSION="3.44.2"
RELEASE_TAG="v3.44.2-termux"
EXPECTED_SHA256="${EXPECTED_SHA256:-${FLUTTER_DEB_SHA256:-66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000}}"
DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/${RELEASE_TAG}/flutter_${FLUTTER_VERSION}_aarch64.deb"

echo "========================================"
echo "Flutter ${FLUTTER_VERSION} for Termux ARM64"
echo "========================================"
echo ""

# Check architecture
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "Error: This package only supports ARM64 (aarch64)"
    echo "Your architecture: $ARCH"
    record_stage preflight failed; exit 10
fi

# Check if running in Termux
if [ ! -d "/data/data/com.termux" ]; then
    echo "Error: This script must be run in Termux"
    record_stage preflight failed; exit 10
fi

FREE_SPACE=$(df -k /data | awk \'NR==2 {print $4}\')
if [ "$FREE_SPACE" -lt 1000000 ]; then
    echo "Error: Not enough disk space. Need at least 1GB."
    record_stage preflight failed
    exit 10
fi
record_stage preflight success

# Install x11-repo first (pre-dependency)
echo "[1/5] Installing x11-repo..."
pkg install -y x11-repo

# Download deb
echo "[2/5] Downloading flutter_${FLUTTER_VERSION}_aarch64.deb..."

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"; print_summary' EXIT
cd "$WORK_DIR"
curl -L -o flutter.deb "$DEB_URL" || { record_stage download failed; exit 20; }
record_stage download success

# Verify SHA256 checksum
echo "Verifying SHA256 checksum..."
if command -v sha256sum &> /dev/null; then
    ACTUAL_SHA256=$(sha256sum flutter.deb | awk '{print $1}')
    if [ -n "$EXPECTED_SHA256" ] && [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
        echo "==========================================================="
        echo " ERROR: SHA256 checksum mismatch!"
        echo " Expected: $EXPECTED_SHA256"
        echo " Actual  : $ACTUAL_SHA256"
        echo " Security Alert: Downloaded file may be corrupted or tampered!"
        echo "==========================================================="
        rm -f flutter.deb
        record_stage integrity failed; exit 30
    fi
    echo "  ✓ SHA256 verified ($ACTUAL_SHA256)"
    record_stage integrity success
else
    echo "  Warning: sha256sum not found, skipping checksum verification"
fi

# Install deb
echo "[3/5] Installing deb package..."
apt-get install -f -y ./flutter.deb || { record_stage package failed; exit 40; }
record_stage package success

# Run post-install script
echo "[4/5] Running post-install configuration..."
if [ -f "$PREFIX/share/flutter/post_install.sh" ]; then
    bash "$PREFIX/share/flutter/post_install.sh" || { record_stage post-install failed; exit 50; }
    record_stage post-install success
else
    echo "Warning: post_install.sh not found"
fi

# Source profile
echo "[5/5] Setting up environment..."
source "$PREFIX/etc/profile.d/flutter.sh"

echo ""
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "To start using Flutter:"
echo "  source \$PREFIX/etc/profile.d/flutter.sh"
echo "  flutter doctor"
echo ""
echo "To create a new project:"
echo "  flutter create myapp && cd myapp"
echo ""
echo "To build APK:"
echo "  flutter build apk --release"
echo ""
