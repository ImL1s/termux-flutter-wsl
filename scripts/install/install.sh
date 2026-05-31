#!/bin/bash
# Flutter for Termux ARM64 - One-click installer
# https://github.com/ImL1s/termux-flutter-wsl

set -e

FLUTTER_VERSION="3.44.0"
DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/v${FLUTTER_VERSION}/flutter_${FLUTTER_VERSION}_aarch64.deb"

echo "========================================"
echo "Flutter ${FLUTTER_VERSION} for Termux ARM64"
echo "========================================"
echo ""

# Check architecture
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "Error: This package only supports ARM64 (aarch64)"
    echo "Your architecture: $ARCH"
    exit 1
fi

# Check if running in Termux
if [ ! -d "/data/data/com.termux" ]; then
    echo "Error: This script must be run in Termux"
    exit 1
fi

# Install x11-repo first (pre-dependency)
echo "[1/5] Installing x11-repo..."
pkg install -y x11-repo

# Download deb
echo "[2/5] Downloading flutter_${FLUTTER_VERSION}_aarch64.deb..."
cd ~
curl -L -o flutter.deb "$DEB_URL"

# Install deb
echo "[3/5] Installing deb package..."
dpkg -i flutter.deb || true
apt --fix-broken install -y
rm flutter.deb

# Run post-install script
echo "[4/5] Running post-install configuration..."
if [ -f "$PREFIX/share/flutter/post_install.sh" ]; then
    bash "$PREFIX/share/flutter/post_install.sh"
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
