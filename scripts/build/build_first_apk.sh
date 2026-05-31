#!/data/data/com.termux/files/usr/bin/bash
#
# Flutter APK 首次構建腳本
# First-time APK Build Script for Termux
#
# Usage: 在 Flutter 專案目錄中執行
#        ./build_first_apk.sh
#
# 這個腳本會自動：
#   1. 配置專案 (NDK, gradle.properties)
#   2. 執行首次構建（觸發 Gradle 下載）
#   3. 修復 AAPT2 (x86_64 → ARM64)
#   4. 執行正式構建
#

set -e

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

NDK_VERSION="29.0.14206865"
ANDROID_HOME="$PREFIX/opt/android-sdk"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Flutter APK First Build                               ║"
echo "║     自動配置並構建 APK                                    ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ========================================
# 檢查環境
# ========================================
echo -e "${GREEN}[檢查]${NC} 驗證環境..."

# 檢查是否在 Flutter 專案目錄
if [ ! -f "pubspec.yaml" ]; then
    echo -e "${RED}錯誤: 不在 Flutter 專案目錄中${NC}"
    echo "請在 Flutter 專案根目錄執行此腳本"
    echo ""
    echo "例如:"
    echo "  flutter create myapp"
    echo "  cd myapp"
    echo "  bash build_first_apk.sh"
    exit 1
fi

if [ ! -d "android" ]; then
    echo -e "${RED}錯誤: 找不到 android 目錄${NC}"
    echo "請執行 'flutter create .' 生成 Android 檔案"
    exit 1
fi

# 檢查 Flutter
if ! command -v flutter &> /dev/null; then
    echo -e "${RED}錯誤: Flutter 未安裝${NC}"
    echo "請先執行 install_termux_flutter.sh"
    exit 1
fi

# 檢查 Android SDK
if [ ! -d "$ANDROID_HOME" ]; then
    echo -e "${RED}錯誤: Android SDK 未安裝${NC}"
    echo "請先執行 setup_android_sdk.sh"
    exit 1
fi

# 檢查 NDK
if [ ! -d "$ANDROID_HOME/ndk/$NDK_VERSION" ]; then
    echo -e "${YELLOW}警告: NDK $NDK_VERSION 未找到${NC}"
    echo "APK 構建可能會失敗"
    echo ""
fi

echo "  Flutter: $(flutter --version 2>/dev/null | head -1 || echo 'OK')"
echo "  Android SDK: $ANDROID_HOME"
echo "  NDK: $NDK_VERSION"
echo ""

TOTAL_STEPS=4

# ========================================
# Step 1: 配置專案
# ========================================
echo -e "${GREEN}[1/${TOTAL_STEPS}]${NC} 配置專案..."

# 配置 local.properties
LOCAL_PROPS="android/local.properties"
if ! grep -q "ndk.dir" "$LOCAL_PROPS" 2>/dev/null; then
    echo "ndk.dir=$ANDROID_HOME/ndk/$NDK_VERSION" >> "$LOCAL_PROPS"
    echo "  ✓ 已添加 NDK 路徑到 local.properties"
else
    echo "  ✓ NDK 路徑已配置"
fi

# 配置 gradle.properties
GRADLE_PROPS="android/gradle.properties"

if ! grep -q "android.useAndroidX" "$GRADLE_PROPS" 2>/dev/null; then
    echo "android.useAndroidX=true" >> "$GRADLE_PROPS"
fi

if ! grep -q "android.enableJetifier" "$GRADLE_PROPS" 2>/dev/null; then
    echo "android.enableJetifier=true" >> "$GRADLE_PROPS"
fi

# 限制 Gradle 記憶體使用（Termux 環境）
if ! grep -q "org.gradle.jvmargs" "$GRADLE_PROPS" 2>/dev/null; then
    echo "org.gradle.jvmargs=-Xmx768m -XX:MaxMetaspaceSize=384m" >> "$GRADLE_PROPS"
fi

echo "  ✓ gradle.properties 已配置"

# 配置 build.gradle.kts
BUILD_GRADLE="android/app/build.gradle.kts"
BUILD_GRADLE_GROOVY="android/app/build.gradle"

if [ -f "$BUILD_GRADLE" ]; then
    if grep -q "flutter.ndkVersion" "$BUILD_GRADLE" 2>/dev/null; then
        sed -i 's/ndkVersion = flutter.ndkVersion/ndkVersion = "'"$NDK_VERSION"'"/g' "$BUILD_GRADLE"
        echo "  ✓ build.gradle.kts NDK 版本已更新"
    elif ! grep -q "ndkVersion" "$BUILD_GRADLE" 2>/dev/null; then
        sed -i 's/android {/android {\n    ndkVersion = "'"$NDK_VERSION"'"/' "$BUILD_GRADLE"
        echo "  ✓ build.gradle.kts NDK 版本已添加"
    else
        echo "  ✓ build.gradle.kts NDK 已配置"
    fi
elif [ -f "$BUILD_GRADLE_GROOVY" ]; then
    if grep -q "flutter.ndkVersion" "$BUILD_GRADLE_GROOVY" 2>/dev/null; then
        sed -i 's/ndkVersion flutter.ndkVersion/ndkVersion "'"$NDK_VERSION"'"/g' "$BUILD_GRADLE_GROOVY"
        echo "  ✓ build.gradle NDK 版本已更新"
    elif ! grep -q "ndkVersion" "$BUILD_GRADLE_GROOVY" 2>/dev/null; then
        sed -i 's/android {/android {\n    ndkVersion "'"$NDK_VERSION"'"/' "$BUILD_GRADLE_GROOVY"
        echo "  ✓ build.gradle NDK 版本已添加"
    else
        echo "  ✓ build.gradle NDK 已配置"
    fi
fi

echo ""

# ========================================
# Step 2: 首次構建（觸發 Gradle 下載）
# ========================================
echo -e "${GREEN}[2/${TOTAL_STEPS}]${NC} 首次構建（下載 Gradle 依賴）..."
echo "  這可能需要幾分鐘，請耐心等待..."
echo ""

# 執行構建，預期可能失敗（AAPT2 問題）
flutter build apk --release 2>&1 | tee /tmp/flutter_build.log || true

# 檢查是否有 AAPT2 錯誤
if grep -q "EM_X86_64" /tmp/flutter_build.log 2>/dev/null; then
    echo ""
    echo -e "${YELLOW}  檢測到 AAPT2 架構問題，正在修復...${NC}"
    NEED_AAPT2_FIX=true
elif grep -q "Built build/app/outputs" /tmp/flutter_build.log 2>/dev/null; then
    echo ""
    echo -e "${GREEN}  首次構建成功！${NC}"
    NEED_AAPT2_FIX=false
else
    echo ""
    echo -e "${YELLOW}  構建可能失敗，嘗試修復 AAPT2...${NC}"
    NEED_AAPT2_FIX=true
fi

echo ""

# ========================================
# Step 3: 修復 AAPT2
# ========================================
if [ "$NEED_AAPT2_FIX" = true ]; then
    echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} 修復 AAPT2..."

    # 找到並替換 AAPT2
    AAPT2_FIXED=false
    while IFS= read -r aapt2_path; do
        if [ -n "$aapt2_path" ]; then
            rm -f "$aapt2_path"
            ln -s "$ANDROID_HOME/build-tools/35.0.0/aapt2" "$aapt2_path"
            echo "  ✓ 已修復: $aapt2_path"
            AAPT2_FIXED=true
        fi
    done < <(find ~/.gradle/caches -name "aapt2" -path "*aapt2-*-linux*" 2>/dev/null)

    if [ "$AAPT2_FIXED" = false ]; then
        echo "  沒有找到需要修復的 AAPT2"
    fi

    echo ""
else
    echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} AAPT2 無需修復"
    echo ""
fi

# ========================================
# Step 4: 正式構建
# ========================================
echo -e "${GREEN}[4/${TOTAL_STEPS}]${NC} 正式構建 APK..."
echo ""

if flutter build apk --release; then
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     APK 構建成功！                                        ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    APK_PATH="build/app/outputs/flutter-apk/app-release.apk"
    if [ -f "$APK_PATH" ]; then
        APK_SIZE=$(ls -lh "$APK_PATH" | awk '{print $5}')
        echo -e "APK 位置: ${BLUE}$APK_PATH${NC}"
        echo -e "APK 大小: ${BLUE}$APK_SIZE${NC}"
        echo ""
        echo "安裝到設備:"
        echo -e "  ${BLUE}adb install $APK_PATH${NC}"
    fi
else
    echo ""
    echo -e "${RED}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║     APK 構建失敗                                          ║${NC}"
    echo -e "${RED}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "請檢查錯誤訊息並參考文檔:"
    echo "  https://github.com/ImL1s/termux-flutter-wsl#構建-android-apk"
    exit 1
fi

echo ""
