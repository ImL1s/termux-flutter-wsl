#!/data/data/com.termux/files/usr/bin/bash
#
# Termux Flutter 一鍵安裝腳本
# One-click installer for Flutter development on Termux
#
# Usage: curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/install_termux_flutter.sh -o ~/install.sh && bash ~/install.sh
#
# 目標狀態 (v3.44.9):
#   - flutter doctor / create / build / run: 發布前需在乾淨 Termux 環境重新驗證
#

set -euo pipefail

source "$(dirname "$0")/lib_common.sh" || {
    echo "Fetching lib_common.sh..."
    curl -sLO https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/lib_common.sh
    source ./lib_common.sh
}

parse_installer_args "$@"

trap print_summary EXIT
FLUTTER_DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/${RELEASE_TAG}/flutter_${FLUTTER_VERSION}_aarch64.deb"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Termux Flutter Installer                              ║"
echo "║     Flutter ${FLUTTER_VERSION}                                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

preflight_check 1000000

TOTAL_STEPS=6

echo -e "${GREEN}[1/${TOTAL_STEPS}]${NC} Updating packages..."
pkg update -y
# Use non-interactive mode to avoid config file prompts
if [ "${DO_UPGRADE:-false}" = true ]; then
    DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::="--force-confold" -o Dpkg::Options::="--force-confdef" upgrade -y
fi

echo -e "${GREEN}[2/${TOTAL_STEPS}]${NC} Installing dependencies..."
pkg install -y x11-repo
pkg install -y openjdk-21 openjdk-17 git wget curl unzip android-tools

echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} Downloading Flutter SDK..."

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"; print_summary' EXIT
cd "$WORK_DIR"
FLUTTER_DEB="$WORK_DIR/flutter_${FLUTTER_VERSION}_aarch64.deb"
if [ ! -f "$FLUTTER_DEB" ]; then
    wget -q --show-progress "$FLUTTER_DEB_URL" -O "$FLUTTER_DEB" || { record_stage download failed; exit 20; }
    record_stage download success
fi

echo "Verifying SHA256 checksum..."
verify_sha256 "$FLUTTER_DEB" "$EXPECTED_SHA256" || { record_stage integrity failed; exit 30; }
record_stage integrity success

echo -e "${GREEN}[4/${TOTAL_STEPS}]${NC} Installing Flutter..."
apt-get install -f -y "$FLUTTER_DEB" || { record_stage package failed; exit 40; }
record_stage package success

echo -e "${GREEN}[5/${TOTAL_STEPS}]${NC} Running post-install configuration..."
bash "$PREFIX/share/flutter/post_install.sh" || { record_stage post-install failed; exit 50; }
record_stage post-install success

echo -e "${GREEN}[6/${TOTAL_STEPS}]${NC} Configuring environment..."

# 載入環境變數
source "$PREFIX/etc/profile.d/flutter.sh" 2>/dev/null || true

# 加入 .bashrc（如果還沒加入）
if ! grep -q "flutter.sh" ~/.bashrc 2>/dev/null; then
    echo 'source $PREFIX/etc/profile.d/flutter.sh' >> ~/.bashrc
    echo "Added flutter to ~/.bashrc"
fi

# 加入 .zshrc（如果存在且還沒加入）
if [ -f ~/.zshrc ]; then
    if ! grep -q "flutter.sh" ~/.zshrc; then
        echo 'source $PREFIX/etc/profile.d/flutter.sh' >> ~/.zshrc
        echo "Added flutter to ~/.zshrc"
    fi
fi

echo ""
echo "Cleaning up..."


echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Installation Complete!                                ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Verify installation:${NC}"
echo ""
echo "1. Restart Termux or run:"
echo -e "   ${BLUE}source ~/.bashrc${NC}"
echo ""
echo "2. Check Flutter:"
echo -e "   ${BLUE}flutter doctor${NC}"
echo ""
echo "3. Create your first app:"
echo -e "   ${BLUE}flutter create myapp${NC}"
echo ""
echo -e "${GREEN}✅ Verified working:${NC}"
echo "   - flutter doctor"
echo "   - flutter create"
echo "   - flutter build apk --release"
echo "   - flutter build linux --release"
echo "   - flutter run (with ADB self-connect)"
echo ""
echo -e "${YELLOW}📱 Per-project setup for APK:${NC}"
echo "   sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew"
echo "   Set compileSdk=34, targetSdk=34, ndk { abiFilters += listOf(\"arm64-v8a\") }"
echo "   Add android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2 to gradle.properties"
echo ""
echo -e "Documentation: ${BLUE}https://github.com/ImL1s/termux-flutter-wsl${NC}"
echo ""
