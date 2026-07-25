#!/data/data/com.termux/files/usr/bin/bash
#
# Termux Flutter 完整安裝腳本
# Complete Flutter + Android SDK Installation for Termux
#
# Usage: curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o ~/install.sh && bash ~/install.sh
# Version: 2026-01-06 v14
#
# 這個腳本會自動完成：
#   1. 安裝 Flutter SDK
#   2. 安裝 Android SDK
#   3. 配置環境
#   4. 創建測試專案
#   5. 構建測試 APK
#
# 完成後你可以直接使用 flutter build apk 構建任何專案
#

set -e

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 版本配置
FLUTTER_VERSION="3.44.2"
RELEASE_TAG="v3.44.2-termux"
EXPECTED_SHA256="${EXPECTED_SHA256:-${FLUTTER_DEB_SHA256:-66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000}}"
NDK_VERSION="29.0.14206865"
REPO_BASE="https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                                                           ║"
echo "║     Termux Flutter Complete Installer                     ║"
echo "║     Flutter ${FLUTTER_VERSION} + Android SDK                         ║"
echo "║                                                           ║"
echo "║     世界首個在 ARM64 Termux 原生支援                      ║"
echo "║     flutter build apk 的解決方案                          ║"
echo "║                                                           ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# ========================================
# 環境檢查
# ========================================
echo -e "${GREEN}[檢查]${NC} 驗證環境..."

# 檢查架構
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo -e "${RED}錯誤: 此腳本只支援 ARM64 (aarch64) 設備${NC}"
    echo "你的架構: $ARCH"
    exit 1
fi

# 檢查是否在 Termux 中
if [ ! -d "/data/data/com.termux" ]; then
    echo -e "${RED}錯誤: 此腳本必須在 Termux 中執行${NC}"
    exit 1
fi

echo "  ✓ 架構: ARM64"
echo "  ✓ 環境: Termux"
echo ""

# 詢問是否繼續
echo -e "${YELLOW}此腳本將安裝：${NC}"
echo "  • Flutter SDK (~550MB)"
echo "  • Android SDK (~700MB)"
echo "  • ARM64 NDK (~550MB)"
echo "  • 總共約 1.8GB"
echo ""
echo -e "${YELLOW}預計時間：${NC} 10-30 分鐘（視網速而定）"
echo ""
read -p "是否繼續? [Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "安裝已取消"
    exit 0
fi

TOTAL_STEPS=6

# ========================================
# Step 1: 更新系統
# ========================================
echo ""
echo -e "${GREEN}[1/${TOTAL_STEPS}]${NC} 更新系統套件..."

# 清理可能存在的舊包（避免依賴衝突）
dpkg --purge android-sdk 2>/dev/null || true
dpkg --purge flutter 2>/dev/null || true
apt --fix-broken install -y 2>/dev/null || true

pkg update -y
pkg upgrade -y

# ========================================
# Step 2: 安裝 Flutter
# ========================================
echo ""
echo -e "${GREEN}[2/${TOTAL_STEPS}]${NC} 安裝 Flutter SDK..."

# 安裝依賴
pkg install -y x11-repo
# 安裝基本工具
pkg install -y openjdk-21 git wget curl unzip p7zip cmake ninja binutils

# 安裝 Android build tools（需要繞過 android-sdk 依賴問題）
for pkg in d8 dx aidl apksigner googletest android-tools; do
    apt download $pkg 2>/dev/null && dpkg -i ${pkg}*.deb 2>/dev/null && rm -f ${pkg}*.deb
done

# 下載 Flutter deb
FLUTTER_DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/${RELEASE_TAG}/flutter_${FLUTTER_VERSION}_aarch64.deb"
FLUTTER_DEB="$HOME/flutter_${FLUTTER_VERSION}_aarch64.deb"

if [ ! -f "$FLUTTER_DEB" ]; then
    echo "下載 Flutter SDK..."
    wget -q --show-progress "$FLUTTER_DEB_URL" -O "$FLUTTER_DEB"
fi

# 驗證 SHA256 校驗碼
echo "驗證 SHA256 校驗碼..."
if command -v sha256sum &> /dev/null; then
    ACTUAL_SHA256=$(sha256sum "$FLUTTER_DEB" | awk '{print $1}')
    if [ -n "$EXPECTED_SHA256" ] && [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
        echo -e "${RED}"
        echo "==========================================================="
        echo " 錯誤: SHA256 校驗碼不符！(Security Alert / Checksum Mismatch)"
        echo " 預期 (Expected): $EXPECTED_SHA256"
        echo " 實際 (Actual)  : $ACTUAL_SHA256"
        echo " 警告: 下載檔案可能已損壞或被篡改！已自動刪除損壞檔案。"
        echo "==========================================================="
        echo -e "${NC}"
        rm -f "$FLUTTER_DEB"
        exit 1
    fi
    echo "  ✓ SHA256 驗證成功 ($ACTUAL_SHA256)"
else
    echo -e "${YELLOW}  ⚠ 未找到 sha256sum 工具，跳過 SHA256 驗證${NC}"
fi

# 安裝
dpkg -i "$FLUTTER_DEB" || true
apt --fix-broken install -y

# 載入環境
source $PREFIX/etc/profile.d/flutter.sh 2>/dev/null || true

# 重新編譯 flutter_tools.snapshot（修復 "Unsupported operating system: android" 問題）
FLUTTER_ROOT=$PREFIX/opt/flutter
DART_SDK=$FLUTTER_ROOT/bin/cache/dart-sdk
if [ ! -x "$DART_SDK/bin/dartvm" ]; then
    echo -e "${RED}錯誤: Dart VM binary missing: $DART_SDK/bin/dartvm${NC}"
    echo "Dart 3.10+ requires dartvm next to dart. Re-download the fixed flutter_${FLUTTER_VERSION}_aarch64.deb release."
    exit 1
fi
if [ -f "$DART_SDK/bin/dart" ] && [ -f "$FLUTTER_ROOT/packages/flutter_tools/bin/flutter_tools.dart" ]; then
    echo "重新編譯 flutter_tools.snapshot..."
    rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" 2>/dev/null || true
    $DART_SDK/bin/dart --snapshot="$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" \
        "$FLUTTER_ROOT/packages/flutter_tools/bin/flutter_tools.dart" 2>/dev/null || true
fi

echo "  ✓ Flutter 已安裝"

# 下載官方 Dart SDK snapshots（用於 hot reload / flutter run）
echo "下載 Dart SDK snapshots..."
ENGINE_VERSION=$(cat $FLUTTER_ROOT/bin/internal/engine.version 2>/dev/null || echo "")
SNAPSHOTS_DIR=$DART_SDK/bin/snapshots
if [ -n "$ENGINE_VERSION" ] && [ ! -f "$SNAPSHOTS_DIR/dds_aot.dart.snapshot" ]; then
    SNAPSHOTS_URL="https://storage.googleapis.com/flutter_infra_release/flutter/${ENGINE_VERSION}/dart-sdk-linux-arm64.zip"
    echo "  從官方 Flutter 儲存下載 snapshots..."
    wget -q --show-progress "$SNAPSHOTS_URL" -O "$HOME/dart-sdk.zip" || true
    if [ -f "$HOME/dart-sdk.zip" ]; then
        unzip -o -j "$HOME/dart-sdk.zip" 'dart-sdk/bin/snapshots/*' -d "$SNAPSHOTS_DIR" 2>/dev/null || true
        rm -f "$HOME/dart-sdk.zip"
        echo "  ✓ Dart SDK snapshots 已安裝"
    fi
else
    echo "  ✓ Dart SDK snapshots 已存在或無需更新"
fi

# 清理 ELF 二進制文件（移除 DT_RPATH 警告，修復 flutter run JSON 解析問題）
echo "清理 ELF binaries..."
apt download termux-elf-cleaner 2>/dev/null || true
if ls termux-elf-cleaner*.deb 1>/dev/null 2>&1; then
    dpkg -i termux-elf-cleaner*.deb 2>/dev/null || true
    rm -f termux-elf-cleaner*.deb
fi
if command -v termux-elf-cleaner &> /dev/null; then
    for dart_bin in dart dartvm dartaotruntime; do
        [ -f "$DART_SDK/bin/$dart_bin" ] && termux-elf-cleaner "$DART_SDK/bin/$dart_bin" 2>/dev/null || true
    done
    echo "  ✓ ELF binaries 已清理"
else
    echo "  ⚠ termux-elf-cleaner 未安裝"
fi

# ========================================
# Step 3: 安裝 Android SDK
# ========================================
echo ""
echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} 安裝 Android SDK..."

ANDROID_SDK_DEB_URL="https://github.com/mumumusuc/termux-android-sdk/releases/download/35.0.0/android-sdk_35.0.0_aarch64.deb"
ANDROID_SDK_DEB="$HOME/android-sdk_35.0.0_aarch64.deb"

if [ ! -f "$ANDROID_SDK_DEB" ]; then
    echo "下載 Android SDK..."
    wget -q --show-progress "$ANDROID_SDK_DEB_URL" -O "$ANDROID_SDK_DEB"
fi

# 安裝 (忽略 openjdk-17 依賴)
dpkg -i --force-architecture "$ANDROID_SDK_DEB" 2>/dev/null || true
dpkg --force-depends --configure android-sdk 2>/dev/null || true

echo "  ✓ Android SDK 已安裝"

# ========================================
# Step 4: 安裝 ARM64 NDK
# ========================================
echo ""
echo -e "${GREEN}[4/${TOTAL_STEPS}]${NC} 安裝 ARM64 NDK..."

ANDROID_HOME="$PREFIX/opt/android-sdk"
NDK_PATH="$ANDROID_HOME/ndk/$NDK_VERSION"

if [ -d "$NDK_PATH" ]; then
    echo "  ✓ NDK 已安裝"
else
    NDK_ARCHIVE_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-ndk/android-ndk-r29-aarch64.7z"
    NDK_ARCHIVE="$HOME/android-ndk-r29-aarch64.7z"

    if [ ! -f "$NDK_ARCHIVE" ]; then
        echo "下載 ARM64 NDK (約 350MB)..."
        wget -q --show-progress "$NDK_ARCHIVE_URL" -O "$NDK_ARCHIVE"
    fi

    echo "解壓 NDK..."
    mkdir -p "$ANDROID_HOME/ndk"
    7z x -y "$NDK_ARCHIVE" "-o$ANDROID_HOME/ndk" >/dev/null
    rm -rf "$NDK_PATH"
    mv "$ANDROID_HOME/ndk/android-ndk-r29" "$NDK_PATH"

    echo "  ✓ NDK 已安裝"
fi

# 配置 NDK clang wrappers（支援 ARM64 Termux 編譯 Android 代碼）
configure_ndk_clang() {
    local NDK_DIR="$1"
    local PREBUILT="$NDK_DIR/toolchains/llvm/prebuilt"

    # 跳過空的 NDK stub（android-sdk 包帶的空目錄）
    if [ ! -d "$PREBUILT/linux-x86_64/bin" ]; then
        echo "  跳過 NDK stub: $(basename $NDK_DIR)"
        return
    fi

    echo "  配置 NDK: $(basename $NDK_DIR)"

    # 創建 sysroot symlink
    ln -sf linux-x86_64/sysroot "$PREBUILT/sysroot" 2>/dev/null || true

    # 創建 bin 目錄 symlinks
    mkdir -p "$PREBUILT/bin"
    ln -sf "$PREBUILT/linux-x86_64/bin/clang" "$PREBUILT/bin/clang" 2>/dev/null || true
    ln -sf "$PREBUILT/linux-x86_64/bin/clang++" "$PREBUILT/bin/clang++" 2>/dev/null || true

    # 確保 clang++ 指向 clang-18（可能被之前的腳本修改過）
    if [ -L "$PREBUILT/linux-x86_64/bin/clang++" ]; then
        local target=$(readlink "$PREBUILT/linux-x86_64/bin/clang++")
        if [ "$target" = "clang++" ]; then
            # 修復循環 symlink
            rm -f "$PREBUILT/linux-x86_64/bin/clang++"
            ln -sf clang-18 "$PREBUILT/linux-x86_64/bin/clang++"
        fi
    fi

    local LIB_DIR="$PREBUILT/linux-x86_64/sysroot/usr/lib/aarch64-linux-android"

    # 為每個 API level 創建正確的符號連結
    # 重要：libc++_shared.so 必須指向父目錄的真實庫文件，而不是 linker script
    for api_dir in "$LIB_DIR"/*; do
        if [ -d "$api_dir" ]; then
            # libc++_shared.so - 指向父目錄的真實庫文件
            rm -f "$api_dir/libc++_shared.so" 2>/dev/null || true
            ln -sf ../libc++_shared.so "$api_dir/libc++_shared.so" 2>/dev/null || true

            # libatomic.a - 創建空的 stub（Android 不需要 libatomic）
            if [ ! -f "$api_dir/libatomic.a" ]; then
                ar rcs "$api_dir/libatomic.a" 2>/dev/null || true
            fi
        fi
    done

    # Patch android-legacy.toolchain.cmake（移除 -static-libstdc++ 避免連結錯誤）
    local TOOLCHAIN="$NDK_DIR/build/cmake/android-legacy.toolchain.cmake"
    if [ -f "$TOOLCHAIN" ]; then
        if grep -q 'list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")' "$TOOLCHAIN" 2>/dev/null; then
            sed -i 's/list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/# Disabled for Termux: list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/' "$TOOLCHAIN"
            echo "    ✓ Patched android-legacy.toolchain.cmake"
        fi
    fi
}

# 配置所有已安裝的 NDK
echo "配置 NDK clang wrappers..."
for ndk_dir in $ANDROID_HOME/ndk/*/; do
    if [ -d "$ndk_dir/toolchains/llvm" ]; then
        configure_ndk_clang "$ndk_dir"
    fi
done

# 也運行 post_install.sh（如果存在）
if [ -f "$PREFIX/share/flutter/post_install.sh" ]; then
    echo "執行 post_install.sh..."
    bash $PREFIX/share/flutter/post_install.sh 2>/dev/null || true
fi

# ========================================
# Step 5: 配置環境
# ========================================
echo ""
echo -e "${GREEN}[5/${TOTAL_STEPS}]${NC} 配置環境..."

# 設置環境變數
export ANDROID_HOME=$PREFIX/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin

# 加入 .bashrc
if ! grep -q "ANDROID_HOME" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << 'EOF'

# Flutter
source $PREFIX/etc/profile.d/flutter.sh

# Android SDK
export ANDROID_HOME=$PREFIX/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
EOF
fi

# 修復 CMake
rm -rf $ANDROID_HOME/cmake/*/bin 2>/dev/null || true
mkdir -p $ANDROID_HOME/cmake/3.22.1/bin
ln -sf $PREFIX/bin/cmake $ANDROID_HOME/cmake/3.22.1/bin/cmake
ln -sf $PREFIX/bin/ninja $ANDROID_HOME/cmake/3.22.1/bin/ninja

# 創建 build-tools symlinks（修復 "Build Tools is corrupted" 錯誤）
BUILD_TOOLS=$ANDROID_HOME/build-tools/35.0.0
mkdir -p $BUILD_TOOLS/lib
for tool in aapt aapt2 apksigner d8 dx zipalign aidl; do
    ln -sf $PREFIX/bin/$tool $BUILD_TOOLS/$tool 2>/dev/null || true
done
# d8.jar and dx.jar
ln -sf $PREFIX/share/java/d8.jar $BUILD_TOOLS/lib/d8.jar 2>/dev/null || true
ln -sf $PREFIX/share/java/d8.jar $BUILD_TOOLS/lib/dx.jar 2>/dev/null || true
# core-lambda-stubs.jar (create empty if missing)
if [ ! -f $BUILD_TOOLS/core-lambda-stubs.jar ]; then
    echo "Manifest-Version: 1.0" > /tmp/MANIFEST.MF 2>/dev/null || true
    jar cfm $BUILD_TOOLS/core-lambda-stubs.jar /tmp/MANIFEST.MF 2>/dev/null || true
    rm -f /tmp/MANIFEST.MF 2>/dev/null || true
fi
echo "  ✓ build-tools 已配置"

# 配置 Flutter
flutter config --android-sdk $ANDROID_HOME 2>/dev/null || true

# 接受授權
yes | flutter doctor --android-licenses 2>/dev/null || true

echo "  ✓ 環境已配置"

# ========================================
# Step 6: 測試構建
# ========================================
echo ""
echo -e "${GREEN}[6/${TOTAL_STEPS}]${NC} 測試 APK 構建..."

# 安裝 aapt2（手動安裝以避免 openjdk-17 依賴衝突）
echo "檢查 aapt2..."
if ! command -v aapt2 &> /dev/null; then
    echo "安裝 aapt2 及其依賴..."
    cd $HOME
    # 下載依賴包
    apt download libprotobuf fmt libzopfli aapt aapt2 2>/dev/null || true
    # 安裝（使用 dpkg 避免觸發 apt 的依賴解析）
    dpkg -i libprotobuf*.deb 2>/dev/null || true
    dpkg -i fmt*.deb libzopfli*.deb 2>/dev/null || true
    dpkg -i aapt_*.deb 2>/dev/null || true
    dpkg -i aapt2*.deb 2>/dev/null || true
    rm -f *.deb 2>/dev/null || true
fi

TEST_APP_DIR="$HOME/flutter_test_app"

# 創建測試專案
if [ -d "$TEST_APP_DIR" ]; then
    rm -rf "$TEST_APP_DIR"
fi

echo "創建測試專案..."
# 創建包含 Android 和 Linux 支持的專案
if command -v pkg-config &> /dev/null && pkg-config --exists gtk+-3.0 2>/dev/null; then
    flutter create --platforms android,linux "$TEST_APP_DIR" 2>/dev/null
else
    flutter create --platforms android "$TEST_APP_DIR" 2>/dev/null
fi

cd "$TEST_APP_DIR"

# 配置專案（ARM64 only + compileSdk 34）
echo "配置專案..."
echo "ndk.dir=$ANDROID_HOME/ndk/$NDK_VERSION" >> android/local.properties

# 配置 gradle.properties
cat >> android/gradle.properties << 'PROPS'
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
PROPS

# 更新 build.gradle.kts（設置 compileSdk=34，targetSdk=34，abiFilters=arm64-v8a）
cat > android/app/build.gradle.kts << 'GRADLE'
plugins {
    id("com.android.application")
    id("kotlin-android")
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.flutter_test_app"
    compileSdk = 34
    ndkVersion = "29.0.14206865"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        applicationId = "com.example.flutter_test_app"
        minSdk = flutter.minSdkVersion
        targetSdk = 34
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        ndk {
            abiFilters += "arm64-v8a"
        }
        externalNativeBuild {
            cmake {
                abiFilters("arm64-v8a")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    splits {
        abi {
            isEnable = false
        }
    }
}

flutter {
    source = "../.."
}
GRADLE

# 構建 APK
echo "構建 APK（這可能需要幾分鐘）..."
flutter build apk --release --target-platform android-arm64 2>&1 | tee /tmp/build1.log || true

# Gradle 可能下載了新的 SDK 組件（如 build-tools/35.0.0-2），重新配置
echo "配置 Gradle 下載的 SDK 組件..."
if [ -f "$PREFIX/share/flutter/post_install.sh" ]; then
    bash $PREFIX/share/flutter/post_install.sh 2>/dev/null || true
fi

# 檢查是否因 NDK clang 問題失敗（Gradle 可能下載了新 NDK）
if grep -q "CMAKE_C_COMPILER" /tmp/build1.log 2>/dev/null || grep -q "compiler identification is unknown" /tmp/build1.log 2>/dev/null; then
    echo "檢測到 NDK clang 問題，重新配置..."
    # Re-run NDK clang configuration for Gradle-downloaded NDK
    for ndk_dir in $ANDROID_HOME/ndk/*/; do
        if [ -d "$ndk_dir/toolchains/llvm" ]; then
            configure_ndk_clang "$ndk_dir"
        fi
    done
    echo "重新構建..."
    flutter build apk --release --target-platform android-arm64 2>&1 | tee /tmp/build2.log || true
fi

# 檢查 APK 結果
if [ -f "build/app/outputs/flutter-apk/app-release.apk" ]; then
    APK_SIZE=$(ls -lh build/app/outputs/flutter-apk/app-release.apk | awk '{print $5}')
    APK_BUILD_SUCCESS=true
    echo "  ✓ APK 構建成功 ($APK_SIZE)"
else
    APK_BUILD_SUCCESS=false
    echo "  ✗ APK 構建失敗"
fi

# 測試 Linux 構建（如果已安裝 gtk3）
LINUX_BUILD_SUCCESS=false
if command -v pkg-config &> /dev/null && pkg-config --exists gtk+-3.0 2>/dev/null; then
    echo "構建 Linux 應用（需要 gtk3）..."
    flutter build linux 2>&1 | tail -5 || true
    if [ -f "build/linux/arm64/release/bundle/flutter_test_app" ]; then
        LINUX_BUILD_SUCCESS=true
        echo "  ✓ Linux 構建成功"
    else
        echo "  ⚠ Linux 構建跳過（可安裝 gtk3 啟用）"
    fi
else
    echo "  ⚠ Linux 構建跳過（需要 pkg install gtk3）"
fi

BUILD_SUCCESS=$APK_BUILD_SUCCESS

cd $HOME

# ========================================
# 清理
# ========================================
echo ""
echo "清理臨時檔案..."
rm -f "$FLUTTER_DEB" "$ANDROID_SDK_DEB" "$NDK_ARCHIVE" 2>/dev/null || true

# ========================================
# 完成
# ========================================
echo ""
echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
if [ "$BUILD_SUCCESS" = true ]; then
    echo -e "${CYAN}║     ${GREEN}安裝完成！APK 構建測試成功！${CYAN}                        ║${NC}"
else
    echo -e "${CYAN}║     ${YELLOW}安裝完成！APK 構建測試需要手動檢查${CYAN}                  ║${NC}"
fi
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$BUILD_SUCCESS" = true ]; then
    echo -e "${GREEN}測試 APK:${NC} $TEST_APP_DIR/build/app/outputs/flutter-apk/app-release.apk ($APK_SIZE)"
    echo ""
fi

echo -e "${YELLOW}開始使用：${NC}"
echo ""
echo -e "${GREEN}環境已自動配置！重啟 Termux 後直接可用。${NC}"
echo ""
echo "1. 檢查 Flutter："
echo -e "   ${BLUE}flutter doctor${NC}"
echo ""
echo "2. 創建你的專案："
echo -e "   ${BLUE}flutter create myapp${NC}"
echo -e "   ${BLUE}cd myapp${NC}"
echo ""
echo "3. 構建 APK："
echo -e "   ${BLUE}flutter build apk --release${NC}"
echo ""
echo "4. Hot Reload 開發："
echo -e "   ${BLUE}adb connect 127.0.0.1:<端口>${NC}"
echo -e "   ${BLUE}flutter run${NC}"
echo ""
echo -e "文檔: ${BLUE}https://github.com/ImL1s/termux-flutter-wsl${NC}"
echo ""
