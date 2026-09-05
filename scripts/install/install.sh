#!/bin/bash
# Flutter for Termux ARM64 - One-click installer
# https://github.com/ImL1s/termux-flutter-wsl

set -euo pipefail

source "$(dirname "$0")/lib_common.sh" || {
    echo "Fetching lib_common.sh..."
    curl -sLO https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/lib_common.sh
    source ./lib_common.sh
}

parse_installer_args "$@"

trap print_summary EXIT
DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/${RELEASE_TAG}/${ASSET_NAME}"

echo "========================================"
echo "Flutter ${FLUTTER_VERSION} for Termux ARM64"
echo "========================================"
echo ""

preflight_check 1000000

# Install x11-repo first (pre-dependency)
echo "[1/5] Installing x11-repo..."
pkg install -y x11-repo

# Download deb
echo "[2/5] Downloading ${ASSET_NAME}..."

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"; print_summary' EXIT
cd "$WORK_DIR"
curl -L -o flutter.deb "$DEB_URL" || { record_stage download failed; exit 20; }
record_stage download success

echo "Verifying SHA256 checksum..."
verify_sha256 flutter.deb "$EXPECTED_SHA256" || { record_stage integrity failed; exit 30; }
record_stage integrity success

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
[ -f "$PREFIX/etc/profile.d/flutter.sh" ] && source "$PREFIX/etc/profile.d/flutter.sh" 2>/dev/null || true


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
