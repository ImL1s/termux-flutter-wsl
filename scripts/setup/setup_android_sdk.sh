#!/data/data/com.termux/files/usr/bin/bash
#
# Termux Android SDK 安裝腳本
# Android SDK Installation Script for Flutter APK Building
#
# Usage: curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/setup_android_sdk.sh -o ~/setup.sh && bash ~/setup.sh
#
# 這個腳本會安裝和配置 Android SDK，讓 flutter build apk 可以正常運作。
# This script installs and configures Android SDK for flutter build apk to work.
#
# 前置條件 / Prerequisites:
#   - Flutter deb 已安裝 (install_termux_flutter.sh)
#   - ARM64 設備 (aarch64)
#

set -e

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Termux Android SDK Setup                              ║"
echo "║     For Flutter APK Building                              ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# 檢查架構
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo -e "${RED}Error: This script only supports ARM64 (aarch64) devices.${NC}"
    echo "Your architecture: $ARCH"
    exit 1
fi

# 檢查是否在 Termux 中
if [ ! -d "/data/data/com.termux" ]; then
    echo -e "${RED}Error: This script must be run in Termux.${NC}"
    exit 1
fi

# 檢查 Flutter 是否已安裝
if [ ! -d "$PREFIX/opt/flutter" ]; then
    echo -e "${RED}Error: Flutter is not installed.${NC}"
    echo "Please run install_termux_flutter.sh first."
    exit 1
fi

TOTAL_STEPS=7

# ========================================
# Step 1: 安裝依賴
# ========================================
echo -e "${GREEN}[1/${TOTAL_STEPS}]${NC} Installing dependencies..."
pkg update -y
pkg install -y openjdk-21 cmake ninja wget unzip p7zip

# ========================================
# Step 2: 下載並安裝 Android SDK
# ========================================
echo -e "${GREEN}[2/${TOTAL_STEPS}]${NC} Installing Android SDK..."

ANDROID_SDK_DEB_URL="https://github.com/mumumusuc/termux-android-sdk/releases/download/35.0.0/android-sdk_35.0.0_aarch64.deb"
ANDROID_SDK_DEB="$HOME/android-sdk_35.0.0_aarch64.deb"

if [ ! -f "$ANDROID_SDK_DEB" ]; then
    echo "Downloading Android SDK..."
    wget -q --show-progress "$ANDROID_SDK_DEB_URL" -O "$ANDROID_SDK_DEB"
fi

# 安裝 (忽略 openjdk-17 依賴問題)
dpkg -i --force-architecture "$ANDROID_SDK_DEB" 2>/dev/null || true
dpkg --force-depends --configure android-sdk 2>/dev/null || true

# 驗證安裝
if [ ! -d "$PREFIX/opt/android-sdk" ]; then
    echo -e "${RED}Error: Android SDK installation failed.${NC}"
    exit 1
fi
echo "Android SDK installed at $PREFIX/opt/android-sdk"

# ========================================
# Step 3: 檢查/安裝 ARM64 NDK
# ========================================
echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} Checking NDK..."

NDK_VERSION="29.0.14206865"
NDK_PATH="$PREFIX/opt/android-sdk/ndk/$NDK_VERSION"
NDK_ARCHIVE_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-ndk/android-ndk-r29-aarch64.tar.xz"
NDK_ARCHIVE="$HOME/android-ndk-r29-aarch64.tar.xz"

if [ -d "$NDK_PATH" ]; then
    echo "NDK $NDK_VERSION already installed."
else
    echo "Downloading ARM64 NDK r29..."
    if [ ! -f "$NDK_ARCHIVE" ]; then
        wget -q --show-progress "$NDK_ARCHIVE_URL" -O "$NDK_ARCHIVE"
    fi
    mkdir -p "$PREFIX/opt/android-sdk/ndk"
    if [[ "$NDK_ARCHIVE" == *.tar.xz ]]; then
        tar -xf "$NDK_ARCHIVE" -C "$PREFIX/opt/android-sdk/ndk" >/dev/null 2>&1 || 7z x -y "$NDK_ARCHIVE" "-o$PREFIX/opt/android-sdk/ndk" >/dev/null
    else
        7z x -y "$NDK_ARCHIVE" "-o$PREFIX/opt/android-sdk/ndk" >/dev/null || tar -xf "$NDK_ARCHIVE" -C "$PREFIX/opt/android-sdk/ndk" >/dev/null 2>&1
    fi
    rm -rf "$NDK_PATH"
    mv "$PREFIX/opt/android-sdk/ndk/android-ndk-r29" "$NDK_PATH"
    echo "NDK $NDK_VERSION installed."
fi

# ========================================
# Step 4: 配置環境變數
# ========================================
echo -e "${GREEN}[4/${TOTAL_STEPS}]${NC} Configuring environment variables..."

export ANDROID_HOME=$PREFIX/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin

# 加入 .bashrc（如果還沒加入）
if ! grep -q "ANDROID_HOME" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << 'EOF'

# Android SDK
export ANDROID_HOME=$PREFIX/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
EOF
    echo "Added ANDROID_HOME to ~/.bashrc"
fi

# 加入 .zshrc（如果存在且還沒加入）
if [ -f ~/.zshrc ]; then
    if ! grep -q "ANDROID_HOME" ~/.zshrc; then
        cat >> ~/.zshrc << 'EOF'

# Android SDK
export ANDROID_HOME=$PREFIX/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
EOF
        echo "Added ANDROID_HOME to ~/.zshrc"
    fi
fi

# ========================================
# Step 5: 配置 Flutter
# ========================================
echo -e "${GREEN}[5/${TOTAL_STEPS}]${NC} Configuring Flutter..."

flutter config --android-sdk $ANDROID_HOME 2>/dev/null || true

# 接受 Android 授權
echo "Accepting Android licenses..."
yes | flutter doctor --android-licenses 2>/dev/null || true

# ========================================
# Step 6: 修復 CMake
# ========================================
echo -e "${GREEN}[6/${TOTAL_STEPS}]${NC} Fixing CMake symlinks..."

# 刪除 x86_64 CMake
rm -rf $ANDROID_HOME/cmake/*/bin 2>/dev/null || true

# 創建 symlinks 到 Termux cmake/ninja
CMAKE_VERSION="3.22.1"
mkdir -p $ANDROID_HOME/cmake/$CMAKE_VERSION/bin
ln -sf $PREFIX/bin/cmake $ANDROID_HOME/cmake/$CMAKE_VERSION/bin/cmake
ln -sf $PREFIX/bin/ninja $ANDROID_HOME/cmake/$CMAKE_VERSION/bin/ninja

echo "CMake fixed: $ANDROID_HOME/cmake/$CMAKE_VERSION/bin/"

# ========================================
# Step 7: 清理
# ========================================
echo -e "${GREEN}[7/${TOTAL_STEPS}]${NC} Cleaning up..."

rm -f "$ANDROID_SDK_DEB"

# ========================================
# 完成
# ========================================
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Android SDK Setup Complete!                           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Restart Termux or run:"
echo -e "   ${BLUE}source ~/.bashrc${NC}"
echo ""
echo "2. Check Flutter doctor:"
echo -e "   ${BLUE}flutter doctor${NC}"
echo ""
echo "3. Create a Flutter project and build APK:"
echo -e "   ${BLUE}flutter create myapp${NC}"
echo -e "   ${BLUE}cd myapp${NC}"
echo ""
echo "4. Configure your project for ARM64 NDK:"
echo -e "   ${BLUE}echo 'ndk.dir=$ANDROID_HOME/ndk/$NDK_VERSION' >> android/local.properties${NC}"
echo -e "   ${BLUE}sed -i 's/ndkVersion = flutter.ndkVersion/ndkVersion = \"$NDK_VERSION\"/g' android/app/build.gradle.kts${NC}"
echo ""
echo "5. Build APK (first build may fail, then fix AAPT2):"
echo -e "   ${BLUE}flutter build apk --release${NC}"
echo ""
echo -e "${YELLOW}If AAPT2 error occurs, run:${NC}"
echo -e "   ${BLUE}find ~/.gradle/caches -name aapt2 -path '*aapt2-*-linux*' -exec rm {} \\;${NC}"
echo -e "   ${BLUE}find ~/.gradle/caches -name aapt2 -path '*aapt2-*-linux*' -type d -exec ln -s \$ANDROID_HOME/build-tools/35.0.0/aapt2 {}/aapt2 \\;${NC}"
echo ""
echo -e "Documentation: ${BLUE}https://github.com/ImL1s/termux-flutter-wsl${NC}"
echo ""
