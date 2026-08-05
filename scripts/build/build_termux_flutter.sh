#!/usr/bin/env bash
# Termux Flutter 自動化構建腳本
# 用途：為 Termux 交叉編譯 Flutter Engine 並打包成 .deb
# 用法：./build_termux_flutter.sh

set -e

# =====================================================
# 配置區域 - 根據你的環境修改
# =====================================================
NDK_PATH="${NDK_PATH:-${ANDROID_NDK:-${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT}}}}"
BUILD_DIR="$(cd "$(dirname "$0")" && pwd)"
ARCH="arm64"
MODE="debug"

# =====================================================
# 主要流程
# =====================================================

cd "$BUILD_DIR"

echo "=== Step 1: 確保依賴已安裝 ==="
pip3 install --user --break-system-packages gitpython pyyaml fire loguru 2>/dev/null || true

echo "=== Step 2: 組裝 Termux Sysroot ==="
python3 build.py sysroot --arch=$ARCH

echo "=== Step 3: 配置 GN ==="
python3 build.py configure --arch=$ARCH --mode=$MODE

echo "=== Step 4: 編譯 ==="
python3 build.py build --arch=$ARCH --mode=$MODE

echo "=== Step 5: 打包 .deb ==="
python3 build.py debuild --arch=$ARCH

echo "=== 完成 ==="
ls -lh $BUILD_DIR/flutter_*.deb

echo ""
echo "在 Termux 上安裝："
echo "  dpkg -i flutter_*.deb"
