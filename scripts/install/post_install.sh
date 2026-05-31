#!/bin/bash
# Flutter Termux Post-Install Script
# 安裝 deb 包後執行此腳本以完成 APK 構建環境配置

set -e

echo "=========================================="
echo "Flutter Termux Post-Install Configuration"
echo "=========================================="

# 路徑定義
FLUTTER_ROOT=/data/data/com.termux/files/usr/opt/flutter
ANDROID_SDK=/data/data/com.termux/files/usr/opt/android-sdk
DART_SDK=$FLUTTER_ROOT/bin/cache/dart-sdk

# Helper function to setup NDK clang wrappers for any NDK version
setup_ndk_clang_wrappers() {
    local NDK_PATH="$1"
    local NDK_NAME=$(basename "$NDK_PATH")

    if [ ! -d "$NDK_PATH/toolchains/llvm" ]; then
        echo "    ⚠ Skipping $NDK_NAME (no toolchains/llvm directory)"
        return
    fi

    local PREBUILT="$NDK_PATH/toolchains/llvm/prebuilt"
    local SYSROOT="$PREBUILT/linux-x86_64/sysroot"
    local CLANG_VERSION=$(ls -1 "$PREBUILT/linux-x86_64/lib/clang/" | sort -V | tail -n 1)
    local CLANG_LIB="$PREBUILT/linux-x86_64/lib/clang/$CLANG_VERSION/lib/linux"

    echo "    Setting up clang wrappers for NDK $NDK_NAME..."

    # Create wrapper script content (using NDK_PATH variable in script)
CLANG_WRAPPER="#!/data/data/com.termux/files/usr/bin/sh
NDK=$NDK_PATH
SYSROOT=\$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot
CLANG_VERSION=\$(ls -1 \$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/ | tail -n 1)
CLANG_LIB=\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\$CLANG_VERSION/lib/linux

ARCH=\"\"
for arg in \"\$@\"; do
    case \"\$arg\" in
        --target=aarch64*) ARCH=\"aarch64\" ;;
        --target=arm*) ARCH=\"arm\" ;;
    esac
done

if [ \"\$ARCH\" = \"aarch64\" ]; then
    LIB_PATH=\$SYSROOT/usr/lib/aarch64-linux-android
    CLANG_LIB_ARCH=\$CLANG_LIB/aarch64
elif [ \"\$ARCH\" = \"arm\" ]; then
    LIB_PATH=\$SYSROOT/usr/lib/arm-linux-androideabi
    CLANG_LIB_ARCH=\$CLANG_LIB/arm
else
    exec /data/data/com.termux/files/usr/bin/clang \"\$@\"
fi

exec /data/data/com.termux/files/usr/bin/clang -L\$LIB_PATH -L\$CLANG_LIB_ARCH \"\$@\""

CLANGPP_WRAPPER="#!/data/data/com.termux/files/usr/bin/sh
NDK=$NDK_PATH
SYSROOT=\$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot
CLANG_VERSION=\$(ls -1 \$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/ | tail -n 1)
CLANG_LIB=\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\$CLANG_VERSION/lib/linux

ARCH=\"\"
for arg in \"\$@\"; do
    case \"\$arg\" in
        --target=aarch64*) ARCH=\"aarch64\" ;;
        --target=arm*) ARCH=\"arm\" ;;
    esac
done

if [ \"\$ARCH\" = \"aarch64\" ]; then
    LIB_PATH=\$SYSROOT/usr/lib/aarch64-linux-android
    CLANG_LIB_ARCH=\$CLANG_LIB/aarch64
elif [ \"\$ARCH\" = \"arm\" ]; then
    LIB_PATH=\$SYSROOT/usr/lib/arm-linux-androideabi
    CLANG_LIB_ARCH=\$CLANG_LIB/arm
else
    exec /data/data/com.termux/files/usr/bin/clang++ \"\$@\"
fi

exec /data/data/com.termux/files/usr/bin/clang++ -L\$LIB_PATH -L\$CLANG_LIB_ARCH \"\$@\""

    # Create wrappers in prebuilt/bin/ (for some toolchain configs)
    mkdir -p "$PREBUILT/bin"
    echo "$CLANG_WRAPPER" > "$PREBUILT/bin/clang"
    chmod +x "$PREBUILT/bin/clang"
    echo "$CLANGPP_WRAPPER" > "$PREBUILT/bin/clang++"
    chmod +x "$PREBUILT/bin/clang++"

    # Create wrappers in prebuilt/linux-x86_64/bin/ (official NDK structure)
    mkdir -p "$PREBUILT/linux-x86_64/bin"
    # Remove symlinks/files first (clang -> clang-18, clang++ -> clang chain causes overwrites)
    # Must use unlink to properly remove symlinks before writing
    for f in clang clang++; do
        if [ -L "$PREBUILT/linux-x86_64/bin/$f" ] || [ -f "$PREBUILT/linux-x86_64/bin/$f" ]; then
            unlink "$PREBUILT/linux-x86_64/bin/$f" 2>/dev/null || rm "$PREBUILT/linux-x86_64/bin/$f" 2>/dev/null || true
        fi
    done
    echo "$CLANG_WRAPPER" > "$PREBUILT/linux-x86_64/bin/clang"
    chmod +x "$PREBUILT/linux-x86_64/bin/clang"
    echo "$CLANGPP_WRAPPER" > "$PREBUILT/linux-x86_64/bin/clang++"
    chmod +x "$PREBUILT/linux-x86_64/bin/clang++"

    # Create linux-aarch64 directory with bin subdirectory (for toolchain configs)
    # Note: Must NOT symlink linux-aarch64 -> bin because access to linux-aarch64/bin
    # would incorrectly resolve to bin/bin (which doesn't exist)
    rm -rf "$PREBUILT/linux-aarch64" 2>/dev/null || true
    mkdir -p "$PREBUILT/linux-aarch64/bin"
    cp "$PREBUILT/bin/clang" "$PREBUILT/linux-aarch64/bin/clang"
    cp "$PREBUILT/bin/clang++" "$PREBUILT/linux-aarch64/bin/clang++"

    # Create all API-level clang wrappers (required by Android Gradle Plugin)
    for api in 21 24 26 28 29 30 31 32 33 34 35; do
        ln -sf clang "$PREBUILT/linux-aarch64/bin/armv7a-linux-androideabi${api}-clang"
        ln -sf clang++ "$PREBUILT/linux-aarch64/bin/armv7a-linux-androideabi${api}-clang++"
        ln -sf clang "$PREBUILT/linux-aarch64/bin/aarch64-linux-android${api}-clang"
        ln -sf clang++ "$PREBUILT/linux-aarch64/bin/aarch64-linux-android${api}-clang++"
        ln -sf clang "$PREBUILT/linux-aarch64/bin/i686-linux-android${api}-clang"
        ln -sf clang++ "$PREBUILT/linux-aarch64/bin/i686-linux-android${api}-clang++"
        ln -sf clang "$PREBUILT/linux-aarch64/bin/x86_64-linux-android${api}-clang"
        ln -sf clang++ "$PREBUILT/linux-aarch64/bin/x86_64-linux-android${api}-clang++"
    done

    # Create sysroot symlink
    ln -sf linux-x86_64/sysroot "$PREBUILT/sysroot" 2>/dev/null || true

    # Patch toolchain cmake: skip compiler test and force ANDROID_HOST_TAG
    # Termux clang wrapper hangs on CMake compiler ID test, and host tag detection
    # returns empty string on Termux, causing sysroot path: prebuilt//sysroot
    local TOOLCHAIN="$NDK_PATH/build/cmake/android-legacy.toolchain.cmake"
    if [ -f "$TOOLCHAIN" ]; then
        if grep -q 'list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")' "$TOOLCHAIN" 2>/dev/null; then
            sed -i 's/list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/# Disabled for Termux: list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/' "$TOOLCHAIN"
        fi
        if ! grep -q 'CMAKE_C_COMPILER_WORKS' "$TOOLCHAIN" 2>/dev/null; then
            sed -i '1a set(ANDROID_HOST_TAG "linux-x86_64")\nset(CMAKE_C_COMPILER_WORKS TRUE)\nset(CMAKE_CXX_COMPILER_WORKS TRUE)' "$TOOLCHAIN"
        fi
    fi
    # Also patch the main android.toolchain.cmake
    local MAIN_TOOLCHAIN="$NDK_PATH/build/cmake/android.toolchain.cmake"
    if [ -f "$MAIN_TOOLCHAIN" ]; then
        if ! grep -q 'CMAKE_C_COMPILER_WORKS' "$MAIN_TOOLCHAIN" 2>/dev/null; then
            sed -i '1a set(ANDROID_HOST_TAG "linux-x86_64")\nset(CMAKE_C_COMPILER_WORKS TRUE)\nset(CMAKE_CXX_COMPILER_WORKS TRUE)' "$MAIN_TOOLCHAIN"
        fi
    fi

    # Replace x86_64 llvm-objcopy/llvm-strip with Termux ARM64 native binaries
    # (Gradle StripDebugSymbolsRunnable fails with x86_64 binaries on ARM64)
    local LLVM_BIN="$PREBUILT/linux-x86_64/bin"
    if [ -f /data/data/com.termux/files/usr/bin/llvm-objcopy ]; then
        cp /data/data/com.termux/files/usr/bin/llvm-objcopy "$LLVM_BIN/llvm-objcopy" 2>/dev/null || true
        cp /data/data/com.termux/files/usr/bin/llvm-strip "$LLVM_BIN/llvm-strip" 2>/dev/null || true
        echo "    ✓ llvm-objcopy/llvm-strip replaced with ARM64 native"
    fi

    echo "    ✓ NDK $NDK_NAME configured"
}

# Get engine version for downloads
ENGINE_VERSION=$(cat $FLUTTER_ROOT/bin/internal/engine.version 2>/dev/null || echo "4c525dac5ebe5971c5708ef73558ed8edcf4a362")

# 0. 下載官方 Dart SDK snapshots (修復 flutter run hot reload)
echo "[0/13] Downloading official Dart SDK snapshots (for hot reload)..."
SNAPSHOTS_URL="https://storage.googleapis.com/flutter_infra_release/flutter/${ENGINE_VERSION}/dart-sdk-linux-arm64.zip"
SNAPSHOTS_DIR=$DART_SDK/bin/snapshots

# Check if key snapshot is missing
if [ ! -f "$SNAPSHOTS_DIR/dds_aot.dart.snapshot" ]; then
    echo "  Downloading dart-sdk-linux-arm64.zip..."
    cd "${TMPDIR:-$PREFIX/tmp}"
    curl -L -o dart-sdk.zip "$SNAPSHOTS_URL"
    echo "  Extracting snapshots..."
    unzip -o -j dart-sdk.zip 'dart-sdk/bin/snapshots/*' -d "$SNAPSHOTS_DIR"
    rm dart-sdk.zip

    # Create symlinks for non-AOT versions
    ln -sf frontend_server_aot.dart.snapshot "$SNAPSHOTS_DIR/frontend_server.dart.snapshot" 2>/dev/null || true

    echo "  ✓ Dart SDK snapshots installed"
else
    echo "  ✓ Dart SDK snapshots already exist"
fi

# 1. 清理 ELF 二進制的 DT_RPATH (修復 flutter run crash)
echo "[1/13] Cleaning ELF binaries (fix flutter run)..."
pkg install -y termux-elf-cleaner 2>/dev/null || true

# Clean dart binaries to remove DT_RPATH warnings that crash flutter run
if command -v termux-elf-cleaner &> /dev/null; then
    echo "  Cleaning dart-sdk binaries..."
    find $DART_SDK/bin -type f -executable 2>/dev/null | xargs -r termux-elf-cleaner 2>/dev/null || true

    echo "  Cleaning engine artifacts..."
    find $FLUTTER_ROOT/bin/cache/artifacts/engine -name "*.so" -o -name "gen_snapshot" -o -name "dart" 2>/dev/null | xargs -r termux-elf-cleaner 2>/dev/null || true

    echo "  ✓ ELF binaries cleaned"
else
    echo "  ⚠ termux-elf-cleaner not found, skipping"
fi

# 1.5a. Fix shebangs in Flutter SDK scripts
# Gradle and other processes may invoke flutter/dart scripts which have #!/usr/bin/env bash
# This fails on Termux since /usr/bin/env doesn't exist
echo "[1.5a/13] Fixing shebangs in Flutter SDK scripts..."
TERMUX_BASH=/data/data/com.termux/files/usr/bin/bash
TERMUX_SH=/data/data/com.termux/files/usr/bin/sh
for f in $FLUTTER_ROOT/bin/flutter $FLUTTER_ROOT/bin/dart $FLUTTER_ROOT/bin/internal/shared.sh $FLUTTER_ROOT/bin/internal/update_dart_sdk.sh $FLUTTER_ROOT/bin/internal/content_aware_hash.sh $FLUTTER_ROOT/bin/internal/last_engine_commit.sh $FLUTTER_ROOT/bin/internal/update_engine_version.sh; do
    if [ -f "$f" ]; then
        sed -i "1s|#!/usr/bin/env bash|#!$TERMUX_BASH|" "$f"
        sed -i "1s|#!/usr/bin/env sh|#!$TERMUX_SH|" "$f"
    fi
done
echo "  ✓ Shebangs fixed"

# 1.5b. Fix engine.stamp and engine.realm (required for Maven artifact resolution)
echo "[1.5b/13] Fixing engine.stamp and engine.realm, and injecting framework version tag..."
cp $FLUTTER_ROOT/bin/internal/engine.version $FLUTTER_ROOT/bin/cache/engine.stamp 2>/dev/null || true
echo -n > $FLUTTER_ROOT/bin/cache/engine.realm 2>/dev/null || true
echo "  ✓ engine.stamp=$(cat $FLUTTER_ROOT/bin/cache/engine.stamp)"
echo "  ✓ engine.realm cleared"

if ! [ -d "$FLUTTER_ROOT/.git" ]; then
    echo "  ! Missing .git, creating dummy repository for version resolution..."
    cd "$FLUTTER_ROOT" || true
    rm -f version
    /data/data/com.termux/files/usr/bin/git init -q >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git config user.email "termux@example.com" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git config user.name "termux" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git add bin/flutter >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git commit -q -m "Init framework" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git tag "3.44.0" >/dev/null 2>&1 || true
    rm -f bin/cache/flutter.version.json 2>/dev/null || true
    echo "  ✓ Dummy tag 3.44.0 created"
fi

# 1.5c. Fix CMakeLists.txt (skip compiler test for NDK cmake)
# CMAKE_C_COMPILER_WORKS=TRUE skips the compiler test that fails on ARM64
echo "[1.5c/13] Fixing CMakeLists.txt for ARM64 compatibility..."
CMAKE_FILE=$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/scripts/CMakeLists.txt
cat > "$CMAKE_FILE" << 'CMAKEOF'
cmake_minimum_required(VERSION 3.6)
set(CMAKE_C_COMPILER_WORKS TRUE)
set(CMAKE_CXX_COMPILER_WORKS TRUE)
project(FlutterNDKTrick C CXX)
CMAKEOF
echo "  ✓ CMakeLists.txt fixed (compiler test skipped)"

# 1.5d. Install Android SDK Platform 36 (Flutter 3.44.0 requirement)
echo "[1.5d/13] Installing Android SDK Platform 36..."
if [ ! -d "$ANDROID_SDK/platforms/android-36" ]; then
    mkdir -p $ANDROID_SDK/platforms
    cd $ANDROID_SDK/platforms
    curl -L -o platform-36.zip 'https://dl.google.com/android/repository/platform-36_r01.zip' 2>/dev/null
    if [ -f platform-36.zip ] && [ -s platform-36.zip ]; then
        unzip -q platform-36.zip 2>/dev/null
        rm -f platform-36.zip
        echo "  ✓ Platform 36 installed"
    else
        echo "  ⚠ Download failed, symlink platform-34 → android-36"
        ln -sf android-34 android-36 2>/dev/null
    fi
else
    echo "  ✓ Platform 36 already exists"
fi

# Replace .deb dart binary with Termux system dart (JIT VM)
# The .deb ships exe.unstripped/dart which is actually dartdev (AOT wrapper)
# that cannot execute .dart files in JIT mode. The flutter CLI (shared.sh)
# needs a full JIT-capable dart VM to run flutter_tools.dart directly.
echo "[1.5e/13] Replacing dart with Termux JIT-capable dart..."
SYSTEM_DART=/data/data/com.termux/files/usr/bin/dart
DEB_DART=$DART_SDK/bin/dart

if ! command -v dart &> /dev/null; then
    echo "  ! Termux dart not found. Installing dart via apt..."
    apt update >/dev/null 2>&1 || true
    apt install -y dart >/dev/null 2>&1 || true
fi

if ! command -v aapt2 &> /dev/null; then
    echo "  ! Termux aapt2 not found. Installing build dependencies via apt..."
    apt update >/dev/null 2>&1 || true
    apt install -y aapt2 libc++ libexpat openssl >/dev/null 2>&1 || true
fi

# Install d8/aidl/apksigner (required by AGP for build-tools validation)
for tool in d8 dx aidl apksigner zipalign; do
    if ! command -v $tool &> /dev/null; then
        echo "  ! $tool not found, installing..."
        apt install -y $tool >/dev/null 2>&1 || true
    fi
done

if [ -f "$SYSTEM_DART" ]; then
    cp "$SYSTEM_DART" "$DEB_DART"
    chmod 755 "$DEB_DART"
    echo "  ✓ Replaced with system dart ($($DEB_DART --version 2>&1))"
else
    echo "  ⚠ Keeping shipped dart wrapper."
fi

# Generate package_config.json for flutter_tools
# The flutter CLI runs flutter_tools.dart in JIT mode (see shared.sh line ~200)
# and requires .dart_tool/package_config.json from pub get.
echo "[1.5f/13] Generating flutter_tools package_config.json..."
FLUTTER_TOOLS_DIR=$FLUTTER_ROOT/packages/flutter_tools
PKG_CONFIG=$FLUTTER_TOOLS_DIR/.dart_tool/package_config.json
if [ ! -f "$PKG_CONFIG" ]; then
    echo "  Running pub get for flutter_tools..."
    cd "$FLUTTER_TOOLS_DIR"
    $DART_SDK/bin/dart pub get --suppress-analytics 2>/dev/null
    if [ -f "$PKG_CONFIG" ]; then
        echo "  ✓ package_config.json generated"
    else
        echo "  ✗ Failed to generate package_config.json!"
    fi
else
    echo "  ✓ package_config.json already exists"
fi

# Downgrade compileSdkVersion to 34 (Termux aapt2 2.19 cannot load android-35/36 android.jar)
echo "[1.5/13] Downgrading compileSdkVersion to 34..."
FLUTTER_EXT="$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt"
if [ -f "$FLUTTER_EXT" ]; then
    sed -i 's/val compileSdkVersion: Int = [0-9]*/val compileSdkVersion: Int = 34/' "$FLUTTER_EXT"
    echo "  ✓ compileSdkVersion set to 34"
fi

# 2. 下載並安裝 Android API 34 (aapt2 bug workaround)
echo "[2/13] Installing Android API 34..."
if [ ! -d "$ANDROID_SDK/platforms/android-34" ]; then
    cd $ANDROID_SDK/platforms
    curl -L -o platform-34.zip 'https://dl.google.com/android/repository/platform-34-ext7_r02.zip'
    unzip -q platform-34.zip
    rm platform-34.zip
    echo "  ✓ API 34 installed"
else
    echo "  ✓ API 34 already exists"
fi

# 2. 修改 FlutterPluginConstants.kt (僅構建 ARM64)
echo "[3/13] Configuring Flutter for ARM64 only..."
cat > $FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginConstants.kt << 'EOF'
package com.flutter.gradle

object FlutterPluginConstants {
    private const val PLATFORM_ARM32 = "android-arm"
    private const val PLATFORM_ARM64 = "android-arm64"
    private const val PLATFORM_X86_64 = "android-x64"

    private const val ARCH_ARM32 = "armeabi-v7a"
    private const val ARCH_ARM64 = "arm64-v8a"
    private const val ARCH_X86_64 = "x86_64"

    const val INTERMEDIATES_DIR = "intermediates"
    const val FLUTTER_STORAGE_BASE_URL = "FLUTTER_STORAGE_BASE_URL"
    const val DEFAULT_MAVEN_HOST = "https://storage.googleapis.com"

    @JvmStatic val PLATFORM_ARCH_MAP =
        mapOf(
            PLATFORM_ARM32 to ARCH_ARM32,
            PLATFORM_ARM64 to ARCH_ARM64,
            PLATFORM_X86_64 to ARCH_X86_64
        )

    @JvmStatic val ABI_VERSION =
        mapOf(
            ARCH_ARM32 to 1,
            ARCH_ARM64 to 2,
            ARCH_X86_64 to 4
        )

    // Modified for Termux: only arm64 supported
    @JvmStatic val DEFAULT_PLATFORMS =
        listOf(
            PLATFORM_ARM64
        )

    // Flutter 3.44 Gradle plugin imports this symbol directly.
    @JvmStatic val PLATFORM_ABI_LIST: List<String> =
        DEFAULT_PLATFORMS.map { platform ->
            PLATFORM_ARCH_MAP[platform] ?: error("Invalid platform: $platform")
        }
}
EOF
echo "  ✓ FlutterPluginConstants.kt updated"

# Clear stale Gradle included-build outputs after changing the Flutter Gradle plugin.
# Without this, upgrades can compile FlutterPlugin.kt against an older cached
# FlutterPluginConstants.kt and fail with unresolved PLATFORM_ABI_LIST.
echo "  Clearing Flutter Gradle plugin build cache..."
rm -rf "$FLUTTER_ROOT/packages/flutter_tools/gradle/.gradle" \
       "$FLUTTER_ROOT/packages/flutter_tools/gradle/build" \
       "$FLUTTER_ROOT/packages/flutter_tools/gradle/bin" 2>/dev/null || true
echo "  ✓ Flutter Gradle plugin cache cleared"

# 3b. Patch Flutter CLI to default to android-arm64 only
# Without this, `flutter build apk` tries to compile for arm, arm64, and x64,
# but we only have gen_snapshot for arm64
echo "[3.5/13] Patching Flutter CLI for ARM64-only APK builds..."
FLUTTER_TOOLS="$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands"

# build_apk.dart: change default architectures
if [ -f "$FLUTTER_TOOLS/build_apk.dart" ]; then
    # Replace the JIT and AOT default arch lists
    sed -i "s/static const _kDefaultJitArchs = <String>\['android-arm', 'android-arm64', 'android-x64'\]/static const _kDefaultJitArchs = <String>['android-arm64']/" "$FLUTTER_TOOLS/build_apk.dart"
    sed -i "s/static const _kDefaultAotArchs = <String>\['android-arm', 'android-arm64', 'android-x64'\]/static const _kDefaultAotArchs = <String>['android-arm64']/" "$FLUTTER_TOOLS/build_apk.dart"
    echo "  ✓ build_apk.dart patched"
fi

# build_aar.dart: change default target-platform
if [ -f "$FLUTTER_TOOLS/build_aar.dart" ]; then
    sed -i "s/defaultsTo: <String>\['android-arm', 'android-arm64', 'android-x64'\]/defaultsTo: <String>['android-arm64']/" "$FLUTTER_TOOLS/build_aar.dart"
    echo "  ✓ build_aar.dart patched"
fi

# build_appbundle.dart: change default target-platform
if [ -f "$FLUTTER_TOOLS/build_appbundle.dart" ]; then
    sed -i "s/defaultsTo: <String>\['android-arm', 'android-arm64', 'android-x64'\]/defaultsTo: <String>['android-arm64']/" "$FLUTTER_TOOLS/build_appbundle.dart"
    echo "  ✓ build_appbundle.dart patched"
fi

# 3c. Disable forceNdkDownload() in Flutter Gradle plugin
# On Termux, NDK is manually installed. The AGP CMake trick that forces NDK download
# triggers a CMake compiler test that fails because Termux ARM64 clang wrappers
# don't support NDK's --resource-dir flag format.
# Fix: Make forceNdkDownload() early return, skipping the CMake configuration entirely.
echo "[3.7/13] Disabling forceNdkDownload CMake trick..."
PLUGIN_UTILS="$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginUtils.kt"
if [ -f "$PLUGIN_UTILS" ]; then
    if ! grep -q "return // Termux: NDK already installed" "$PLUGIN_UTILS" 2>/dev/null; then
        sed -i '/fun forceNdkDownload/,/^    }/ {
            /val forcingNotRequired: Boolean/i\        return // Termux: NDK already installed, skip CMake trick
        }' "$PLUGIN_UTILS"
        echo "  ✓ forceNdkDownload() patched to early return"
    else
        echo "  ✓ forceNdkDownload() already patched"
    fi
fi

# 3. 創建 NDK clang wrappers (處理所有已安裝的 NDK 版本)
echo "[4/13] Creating NDK clang wrappers..."

NDK_DIR="$ANDROID_SDK/ndk"
if [ -d "$NDK_DIR" ]; then
    NDK_COUNT=0
    for ndk_path in "$NDK_DIR"/*; do
        if [ -d "$ndk_path" ]; then
            setup_ndk_clang_wrappers "$ndk_path"
            NDK_COUNT=$((NDK_COUNT + 1))
        fi
    done
    if [ $NDK_COUNT -eq 0 ]; then
        echo "  ⚠ No NDK found. Clang wrappers will be created when NDK is installed."
        echo "    Re-run this script after installing NDK: bash $PREFIX/share/flutter/post_install.sh"
    else
        echo "  ✓ $NDK_COUNT NDK(s) configured"
    fi
else
    echo "  ⚠ NDK directory not found. Clang wrappers will be created when NDK is installed."
    echo "    Re-run this script after installing NDK: bash $PREFIX/share/flutter/post_install.sh"
fi

# Helper function to setup build-tools symlinks for any version
setup_build_tools_symlinks() {
    local BUILD_TOOLS="$1"
    local BT_NAME=$(basename "$BUILD_TOOLS")

    mkdir -p "$BUILD_TOOLS/lib"

    # Basic tools
    for tool in aapt aapt2 apksigner d8 dx zipalign aidl; do
        ln -sf /data/data/com.termux/files/usr/bin/$tool "$BUILD_TOOLS/$tool" 2>/dev/null || true
    done

    # dexdump (from ART)
    if [ -f /apex/com.android.art/bin/dexdump ]; then
        ln -sf /apex/com.android.art/bin/dexdump "$BUILD_TOOLS/dexdump" 2>/dev/null || true
    fi

    # split-select stub
    cat > "$BUILD_TOOLS/split-select" << 'SPLITEOF'
#!/bin/sh
echo "split-select is not available on Termux ARM64"
exit 0
SPLITEOF
    chmod +x "$BUILD_TOOLS/split-select"

    # core-lambda-stubs.jar
    if [ ! -f "$BUILD_TOOLS/core-lambda-stubs.jar" ]; then
        MANIFEST_TMP="${TMPDIR:-$PREFIX/tmp}/MANIFEST.MF"
        echo "Manifest-Version: 1.0" > "$MANIFEST_TMP"
        jar cfm "$BUILD_TOOLS/core-lambda-stubs.jar" "$MANIFEST_TMP" 2>/dev/null || true
        rm -f "$MANIFEST_TMP"
    fi

    # d8.jar and dx.jar
    ln -sf /data/data/com.termux/files/usr/share/java/d8.jar "$BUILD_TOOLS/lib/d8.jar" 2>/dev/null || true
    ln -sf /data/data/com.termux/files/usr/share/java/d8.jar "$BUILD_TOOLS/lib/dx.jar" 2>/dev/null || true

    echo "    ✓ build-tools $BT_NAME configured"
}

# 7. 創建 build-tools 符號連結 (for all versions)
echo "[8/13] Creating build-tools symlinks..."
BT_DIR=$ANDROID_SDK/build-tools
mkdir -p "$BT_DIR"

# If a real build-tools version exists (e.g. 35.0.0-2 from Termux),
# copy it as 35.0.0 so AGP can validate it (AGP rejects versions like 35.0.0-2)
BT_REAL=""
for bt in "$BT_DIR"/*/; do
    if [ -f "$bt/package.xml" ]; then
        BT_REAL="$bt"
        break
    fi
done

if [ -n "$BT_REAL" ] && [ ! -f "$BT_DIR/35.0.0/package.xml" ]; then
    echo "  Cloning $(basename $BT_REAL) -> 35.0.0 (for AGP validation)..."
    rm -rf "$BT_DIR/35.0.0"
    cp -a "$BT_REAL" "$BT_DIR/35.0.0"
    # Fix version strings in metadata
    BT_REAL_NAME=$(basename "$BT_REAL")
    sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/source.properties" 2>/dev/null || true
    sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/package.xml" 2>/dev/null || true
fi

# Setup default version
setup_build_tools_symlinks "$BT_DIR/35.0.0"

# Create source.properties if missing (required by AGP)
if [ ! -f "$BT_DIR/35.0.0/source.properties" ]; then
    printf "Pkg.Revision=35.0.0\nPkg.Path=build-tools;35.0.0\nPkg.Desc=Android SDK Build-Tools 35\n" > "$BT_DIR/35.0.0/source.properties"
fi

# Also setup any other versions Gradle may have downloaded
for bt_path in "$BT_DIR"/*; do
    if [ -d "$bt_path" ] && [ "$(basename "$bt_path")" != "35.0.0" ]; then
        setup_build_tools_symlinks "$bt_path"
    fi
done

echo "  ✓ Build-tools symlinks created"

# 8. 安裝 cmdline-tools (讓 flutter 檢測 Android 設備)
echo "[9/13] Installing cmdline-tools..."
if [ ! -d "$ANDROID_SDK/cmdline-tools/latest" ]; then
    mkdir -p $ANDROID_SDK/cmdline-tools
    cd $ANDROID_SDK/cmdline-tools
    curl -L -o tools.zip 'https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip'
    unzip -q tools.zip
    mv cmdline-tools latest
    rm tools.zip
    echo "  ✓ cmdline-tools installed"
else
    echo "  ✓ cmdline-tools already exists"
fi

# 9. 創建 platform-tools 符號連結 (adb)
# Note: Gradle may download x86_64 platform-tools, so we force overwrite
echo "[10/13] Creating platform-tools symlinks..."
mkdir -p $ANDROID_SDK/platform-tools
# Remove any x86_64 binaries Gradle may have downloaded
rm -f $ANDROID_SDK/platform-tools/adb $ANDROID_SDK/platform-tools/fastboot 2>/dev/null || true
ln -sf /data/data/com.termux/files/usr/bin/adb $ANDROID_SDK/platform-tools/adb
ln -sf /data/data/com.termux/files/usr/bin/fastboot $ANDROID_SDK/platform-tools/fastboot
echo "  ✓ platform-tools symlinks created"

# 10. 接受 Android licenses
echo "[11/13] Accepting Android licenses..."
mkdir -p $ANDROID_SDK/licenses
echo -e "\n24333f8a63b6825ea9c5514f83c2829b004d1fee" > $ANDROID_SDK/licenses/android-sdk-license
echo -e "\n84831b9409646a918e30573bab4c9c91346d8abd" > $ANDROID_SDK/licenses/android-sdk-preview-license
echo "  ✓ Android licenses accepted"

# 10.5. Configure ANDROID_HOME in flutter config
echo "[11.5/13] Setting Android SDK path in Flutter config..."
$FLUTTER_ROOT/bin/flutter config --android-sdk $ANDROID_SDK --suppress-analytics 2>/dev/null || true
echo "  ✓ ANDROID_HOME=$ANDROID_SDK"

# 11. 複製 VM snapshots (for debug mode)
echo "[12/13] Checking engine artifacts..."
ENGINE_DIR=$FLUTTER_ROOT/bin/cache/artifacts/engine/linux-arm64

if [ ! -f "$ENGINE_DIR/vm_isolate_snapshot.bin" ]; then
    echo "  ⚠ vm_isolate_snapshot.bin not found - debug APK builds may fail"
    echo "    Please copy from WSL build: flutter/engine/src/out/linux_debug_arm64/gen/flutter/lib/snapshot/"
else
    echo "  ✓ VM snapshots present"
fi

# 12. Create linux-x64 -> linux-arm64 symlinks for host platform detection
# Flutter's getCurrentHostPlatform() in build_info.dart doesn't recognize
# Termux as Linux (Platform.operatingSystem returns 'android'), so it falls
# back to HostPlatform.linux_x64, causing gen_snapshot lookup to search
# linux-x64/ instead of linux-arm64/. Create symlinks to resolve this.
echo "[12.5/13] Creating host platform symlinks..."
ENG_ART=$FLUTTER_ROOT/bin/cache/artifacts/engine
for dir in android-arm64-release android-arm64-profile; do
    if [ -d "$ENG_ART/$dir/linux-arm64" ] && [ ! -e "$ENG_ART/$dir/linux-x64" ]; then
        ln -sf linux-arm64 "$ENG_ART/$dir/linux-x64"
        echo "  ✓ $dir/linux-x64 -> linux-arm64"
    fi
done
# Also create top-level linux-x64 -> linux-arm64 symlink for general artifacts
if [ -d "$ENG_ART/linux-arm64" ] && [ ! -e "$ENG_ART/linux-x64" ]; then
    ln -sf linux-arm64 "$ENG_ART/linux-x64"
    echo "  ✓ linux-x64 -> linux-arm64"
fi

# 12.6. Patch Flutter Tools Android-host lookups for Termux
# Dart's Platform.operatingSystem returns 'android' on Termux. Flutter 3.44's
# FontSubsetArtifacts only recognizes macos/linux/windows, so commands that
# verify the cache and discover devices can abort before reaching useful
# diagnostics. Reuse Linux host lookups on Android/Termux hosts.
echo "[12.6/13] Patching Flutter Tools Android-host lookups for Termux..."
FLUTTER_CACHE="$FLUTTER_ROOT/packages/flutter_tools/lib/src/flutter_cache.dart"
if [ -f "$FLUTTER_CACHE" ]; then
    if ! grep -q 'Termux: map Android host to Linux artifacts' "$FLUTTER_CACHE" 2>/dev/null; then
        sed -i "s|final List<String>? binaryDirs = artifacts\[_platform.operatingSystem\];|final List<String>? binaryDirs = artifacts[_platform.isAndroid ? 'linux' : _platform.operatingSystem]; // Termux: map Android host to Linux artifacts|" "$FLUTTER_CACHE"
        echo "  ✓ flutter_cache.dart patched"
    else
        echo "  ✓ Already patched"
    fi
    # Always rebuild flutter_tools after touching source. A previous package
    # install may have left a snapshot compiled before this runtime patch.
    rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.stamp" 2>/dev/null
    rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" 2>/dev/null
    echo "  ✓ Forced flutter_tools rebuild"
else
    echo "  ⚠ flutter_cache.dart not found"
fi

ARTIFACTS_DART="$FLUTTER_ROOT/packages/flutter_tools/lib/src/artifacts.dart"
if [ -f "$ARTIFACTS_DART" ]; then
    if ! grep -q 'Termux: map Android host to Linux artifacts' "$ARTIFACTS_DART" 2>/dev/null; then
        sed -i "s#if (platform.isLinux) {#if (platform.isLinux || platform.isAndroid) { // Termux: map Android host to Linux artifacts.#" "$ARTIFACTS_DART"
        echo "  ✓ artifacts.dart patched"
    else
        echo "  ✓ artifacts.dart already patched"
    fi
else
    echo "  ⚠ artifacts.dart not found"
fi

BUILD_INFO_DART="$FLUTTER_ROOT/packages/flutter_tools/lib/src/build_info.dart"
if [ -f "$BUILD_INFO_DART" ]; then
    if ! grep -q 'Termux: Android host uses Linux artifacts' "$BUILD_INFO_DART" 2>/dev/null; then
        sed -i "s#if (globals.platform.isLinux) {#if (globals.platform.isLinux || globals.platform.isAndroid) { // Termux: Android host uses Linux artifacts.#" "$BUILD_INFO_DART"
        echo "  ✓ build_info.dart patched"
    else
        echo "  ✓ build_info.dart already patched"
    fi
else
    echo "  ⚠ build_info.dart not found"
fi

CHROME_DART="$FLUTTER_ROOT/packages/flutter_tools/lib/src/web/chrome.dart"
if [ -f "$CHROME_DART" ]; then
    if ! grep -q 'Termux: use Linux Chrome lookup on Android host' "$CHROME_DART" 2>/dev/null; then
        sed -i "s#if (platform.isLinux) {#if (platform.isLinux || platform.isAndroid) { // Termux: use Linux Chrome lookup on Android host.#" "$CHROME_DART"
        echo "  ✓ chrome.dart patched"
    else
        echo "  ✓ chrome.dart already patched"
    fi
else
    echo "  ⚠ chrome.dart not found"
fi

# 12.7a. Patch flutter build linux to work on Termux
# Dart's Platform.operatingSystem returns 'android' on Termux, but uname -s returns 'Linux'.
# Patch build_linux.dart to skip the platform check so linux desktop builds work.
echo "[12.7a/13] Patching flutter build linux for Termux..."
BUILD_LINUX="$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands/build_linux.dart"
if [ -f "$BUILD_LINUX" ]; then
    if ! grep -q 'Termux: allow linux build' "$BUILD_LINUX" 2>/dev/null; then
        # Comment out the isLinux check (line: if (!globals.platform.isLinux))
        sed -i "s@if (!globals.platform.isLinux)@if (false /\* Termux: allow linux build \*/)@" "$BUILD_LINUX"
        # Also unhide the command on Termux
        sed -i "s@!featureFlags.isLinuxEnabled || !globals.platform.isLinux@!featureFlags.isLinuxEnabled /\* Termux: visible \*/@" "$BUILD_LINUX"
        
        # NOTE: MUST DELETE SNAPSHOT AND STAMP TO FORCE REBUILD!
        rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.stamp" 2>/dev/null
        rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" 2>/dev/null
        
        echo "  ✓ build_linux.dart patched (forced flutter_tools rebuild)"
    else
        echo "  ✓ Already patched"
    fi
else
    echo "  ⚠ build_linux.dart not found"
fi

# 12.7b. Fix tool_backend.sh shebang for Termux
# CMake invokes this via shebang, and #!/usr/bin/env bash doesn't work on Termux
echo "[12.7b/13] Fixing tool_backend.sh shebang..."
TOOL_BACKEND="$FLUTTER_ROOT/packages/flutter_tools/bin/tool_backend.sh"
if [ -f "$TOOL_BACKEND" ]; then
    sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' "$TOOL_BACKEND"
    echo "  ✓ tool_backend.sh shebang fixed"
fi

# 12.7c. Create api-level.h for CMake system detection
# CMake's CMakeDetermineSystem.cmake reads $PREFIX/include/android/api-level.h
# Without this file, cmake fails with "file failed to open for reading"
echo "[12.7c/13] Creating api-level.h for CMake..."
mkdir -p "$PREFIX/include/android" 2>/dev/null
if [ ! -f "$PREFIX/include/android/api-level.h" ]; then
    cat > "$PREFIX/include/android/api-level.h" << 'HEADER'
#ifndef __ANDROID_API_LEVEL_H__
#define __ANDROID_API_LEVEL_H__
#define __ANDROID_API__ 35
#endif
HEADER
    echo "  ✓ api-level.h created"
else
    echo "  ✓ api-level.h already exists"
fi

# 12.7. Disable icon tree shaking (const_finder not available on ARM64)
# The Termux JIT dart cannot run kernel snapshots (const_finder.dart.snapshot),
# and the engine's dartaotruntime can't run them either.
# Patch the icon_tree_shaker to always skip, equivalent to --no-tree-shake-icons.
echo "[12.7/13] Disabling icon tree shaking (const_finder unavailable)..."
ICON_SHAKER="$FLUTTER_ROOT/packages/flutter_tools/lib/src/build_system/targets/icon_tree_shaker.dart"
if [ -f "$ICON_SHAKER" ]; then
    if ! grep -q 'Termux: const_finder unavailable' "$ICON_SHAKER" 2>/dev/null; then
        # Replace the tree-shake flag check with false in both locations
        sed -i "s|_environment.defines\[kIconTreeShakerFlag\] == 'true'|false /\* Termux: const_finder unavailable \*/|g" "$ICON_SHAKER"
        echo "  ✓ Icon tree shaking disabled"
    else
        echo "  ✓ Already disabled"
    fi
else
    echo "  ⚠ icon_tree_shaker.dart not found"
fi

echo ""
echo "=========================================="
echo "Post-install configuration complete!"
echo "=========================================="
echo ""
echo "=== Quick Start ==="
echo "  source /data/data/com.termux/files/usr/etc/profile.d/flutter.sh"
echo "  flutter create myapp && cd myapp"
echo ""
echo "=== IMPORTANT: Project Setup (REQUIRED for each Flutter project) ==="
echo "  1. Fix gradlew shebang:"
echo "     sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew"
echo ""
echo "  2. Edit android/app/build.gradle.kts:"
echo "     compileSdk = 34"
echo "     targetSdk = 34"
echo "     ndk { abiFilters += listOf(\"arm64-v8a\") }"
echo ""
echo "  3. Add to android/gradle.properties:"
echo "     android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2"
echo ""
echo "  4. Set JAVA_HOME before building:"
echo "     export JAVA_HOME=\$(find /data/data/com.termux/files/usr/lib/jvm -maxdepth 1 -type d -name 'java-*-openjdk' | sort -V | tail -1)"
echo ""
echo ""
echo "  5. Build APK:"
echo "     flutter build apk --release --target-platform android-arm64"
echo ""
echo "=== Linux Desktop Build (optional) ==="
echo "  1. Add to linux/CMakeLists.txt (first line, before cmake_minimum_required):"
echo "     set(CMAKE_SYSTEM_NAME Linux)"
echo ""
echo "  2. Build:"
echo "     flutter build linux --release"
echo ""
echo "=== Flutter Run (hot reload on device) ==="
echo "  1. Install android-tools:  pkg install android-tools"
echo "  2. Enable ADB TCP (from PC):  adb tcpip 5555"
echo "  3. Connect in Termux:  adb connect localhost:5555"
echo "     (Accept the 'Allow USB debugging?' dialog on screen)"
echo "  4. Run:  flutter run -d emulator-5554"
echo ""
