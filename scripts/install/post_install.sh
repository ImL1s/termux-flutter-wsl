#!/bin/bash
# Flutter Termux Post-Install Script
# 安裝 deb 包後執行此腳本以完成 APK 構建環境配置

set -e

echo "=========================================="
echo "Flutter Termux Post-Install Configuration"
echo "=========================================="

# 路徑定義
FLUTTER_ROOT="${FLUTTER_ROOT:-/data/data/com.termux/files/usr/opt/flutter}"
ANDROID_SDK="${ANDROID_SDK:-/data/data/com.termux/files/usr/opt/android-sdk}"
DART_SDK="${DART_SDK:-$FLUTTER_ROOT/bin/cache/dart-sdk}"

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
PATCH_STATE_FILE="$PREFIX/share/flutter/patch_state.json"
BACKUP_DIR="$PREFIX/share/flutter/backups"

MODE="apply"
if [ "$1" == "--check" ]; then MODE="check"; fi
if [ "$1" == "--apply" ]; then MODE="apply"; fi
if [ "$1" == "--status" ]; then MODE="status"; fi
if [ "$1" == "--rollback" ]; then MODE="rollback"; fi

mkdir -p "$BACKUP_DIR"
if [ ! -f "$PATCH_STATE_FILE" ]; then
    echo "{}" > "$PATCH_STATE_FILE"
fi

declare -A STATE_TARGET
declare -A STATE_PREIMAGE
declare -A STATE_POSTIMAGE
declare -A STATE_STATUS
declare -a PATCH_ORDER
declare -A PATCH_FUNCS

# Parse existing state
regex_start='"([^"]+)"[[:space:]]*:[[:space:]]*\{'
regex_field='"([^"]+)"[[:space:]]*:[[:space:]]*"([^"]+)"'

while read -r line; do
    if [[ "$line" =~ $regex_start ]]; then
        P_NAME="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ $regex_field ]]; then
        P_KEY="${BASH_REMATCH[1]}"
        P_VAL="${BASH_REMATCH[2]}"
        if [ "$P_KEY" = "target" ]; then STATE_TARGET["$P_NAME"]="$P_VAL"; fi
        if [ "$P_KEY" = "preimage" ]; then STATE_PREIMAGE["$P_NAME"]="$P_VAL"; fi
        if [ "$P_KEY" = "postimage" ]; then STATE_POSTIMAGE["$P_NAME"]="$P_VAL"; fi
        if [ "$P_KEY" = "status" ]; then STATE_STATUS["$P_NAME"]="$P_VAL"; fi
    fi
done < "$PATCH_STATE_FILE"

save_state() {
    echo "{" > "$PATCH_STATE_FILE"
    local first=1
    for patch in "${PATCH_ORDER[@]}"; do
        if [ -n "${STATE_STATUS[$patch]}" ]; then
            if [ $first -eq 0 ]; then echo "  ," >> "$PATCH_STATE_FILE"; else first=0; fi
            echo "  \"$patch\": {" >> "$PATCH_STATE_FILE"
            echo "    \"target\": \"${STATE_TARGET[$patch]}\"," >> "$PATCH_STATE_FILE"
            echo "    \"preimage\": \"${STATE_PREIMAGE[$patch]}\"," >> "$PATCH_STATE_FILE"
            echo "    \"postimage\": \"${STATE_POSTIMAGE[$patch]}\"," >> "$PATCH_STATE_FILE"
            echo "    \"status\": \"${STATE_STATUS[$patch]}\"" >> "$PATCH_STATE_FILE"
            echo -n "  }" >> "$PATCH_STATE_FILE"
        fi
    done
    echo "" >> "$PATCH_STATE_FILE"
    echo "}" >> "$PATCH_STATE_FILE"
}

register_patch() {
    local name="$1"
    local target="$2"
    local func="$3"
    PATCH_ORDER+=("$name")
    STATE_TARGET["$name"]="$target"
    PATCH_FUNCS["$name"]="$func"
}

apply_patches() {
    local any_failed=0
    for patch_name in "${PATCH_ORDER[@]}"; do
        local target_file="${STATE_TARGET[$patch_name]}"
        local patch_func="${PATCH_FUNCS[$patch_name]}"

        if [ ! -f "$target_file" ]; then
            echo "  ⚠ $patch_name: target missing ($target_file)"
            continue
        fi

        local current_hash
        current_hash=$(sha256sum "$target_file" | awk '{print $1}')
        local state_status="${STATE_STATUS[$patch_name]}"
        local state_post="${STATE_POSTIMAGE[$patch_name]}"

        if [ "$state_status" == "applied" ] && [ "$current_hash" == "$state_post" ]; then
            if [ "$MODE" == "status" ] || [ "$MODE" == "check" ]; then echo "  ✓ $patch_name: already applied"; fi
            continue
        fi

        if [ "$MODE" == "status" ] || [ "$MODE" == "check" ]; then
            cp "$target_file" "$target_file.tmp" 2>/dev/null || true
            if $patch_func "$target_file.tmp" 2>/dev/null && cmp -s "$target_file" "$target_file.tmp"; then
                echo "  ✓ $patch_name: already correct"
                rm -f "$target_file.tmp"
                continue
            fi
            rm -f "$target_file.tmp"
            echo "  + $patch_name: pending"
            continue
        fi

        echo "  Applying $patch_name..."
        if [ ! -f "$BACKUP_DIR/$patch_name.orig" ]; then
            cp "$target_file" "$BACKUP_DIR/$patch_name.orig"
        fi

        STATE_PREIMAGE["$patch_name"]="$current_hash"
        cp "$target_file" "$target_file.tmp"

        if ! $patch_func "$target_file.tmp"; then
            echo "  ✗ $patch_name: unknown upstream content (patch failed)"
            rm -f "$target_file.tmp"
            any_failed=1
            continue
        fi

        if cmp -s "$target_file" "$target_file.tmp"; then
            echo "  ✓ $patch_name: already correct"
            rm -f "$target_file.tmp"
            STATE_POSTIMAGE["$patch_name"]="$current_hash"
            STATE_STATUS["$patch_name"]="applied"
            continue
        fi

        mv "$target_file.tmp" "$target_file"
        local new_hash
        new_hash=$(sha256sum "$target_file" | awk '{print $1}')
        STATE_POSTIMAGE["$patch_name"]="$new_hash"
        STATE_STATUS["$patch_name"]="applied"
        echo "  ✓ $patch_name: successful"
    done

    save_state
    if [ $any_failed -eq 1 ]; then
        echo "Some patches failed. Aborting."
        exit 1
    fi
}

rollback_patches() {
    for patch_name in "${PATCH_ORDER[@]}"; do
        local target_file="${STATE_TARGET[$patch_name]}"
        if [ "${STATE_STATUS[$patch_name]}" == "applied" ]; then
            if [ -f "$BACKUP_DIR/$patch_name.orig" ]; then
                cp "$BACKUP_DIR/$patch_name.orig" "$target_file"
                echo "  ✓ $patch_name: rolled back"
                STATE_STATUS["$patch_name"]="rolled_back"
            else
                echo "  ✗ $patch_name: backup not found!"
            fi
        fi
    done
    save_state
}

# --- Register Patches ---

patch_compile_sdk() {
    if grep -F -q "val compileSdkVersion: Int = 34" "$1"; then return 0; fi
    grep -q "val compileSdkVersion: Int =" "$1" || return 1
    sed -i 's/val compileSdkVersion: Int = [0-9]*/val compileSdkVersion: Int = 34/' "$1"
}
register_patch "compile_sdk" "$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterExtension.kt" patch_compile_sdk

patch_plugin_constants() {
    if grep -F -q "PLATFORM_ARM64" "$1" && ! grep -F -q "PLATFORM_ARM32 = \"android-arm\"" "$1"; then return 0; fi
    cat > "$1" << 'INNER_EOF'
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

    @JvmStatic val DEFAULT_PLATFORMS =
        listOf(
            PLATFORM_ARM64
        )

    @JvmStatic val PLATFORM_ABI_LIST: List<String> =
        DEFAULT_PLATFORMS.map { platform ->
            PLATFORM_ARCH_MAP[platform] ?: error("Invalid platform: $platform")
        }
}
INNER_EOF
}
register_patch "plugin_constants" "$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginConstants.kt" patch_plugin_constants

patch_build_apk() {
    if grep -F -q "['android-arm64']" "$1"; then return 0; fi
    grep -q "_kDefaultJitArchs" "$1" || return 1
    sed -i "s/static const _kDefaultJitArchs = <String>\['android-arm', 'android-arm64', 'android-x64'\]/static const _kDefaultJitArchs = <String>['android-arm64']/" "$1"
    sed -i "s/static const _kDefaultAotArchs = <String>\['android-arm', 'android-arm64', 'android-x64'\]/static const _kDefaultAotArchs = <String>['android-arm64']/" "$1"
}
register_patch "build_apk" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands/build_apk.dart" patch_build_apk

patch_build_aar() {
    if grep -F -q "defaultsTo: <String>['android-arm64']" "$1"; then return 0; fi
    grep -q "defaultsTo: <String>" "$1" || return 1
    sed -i "s/defaultsTo: <String>\['android-arm', 'android-arm64', 'android-x64'\]/defaultsTo: <String>['android-arm64']/" "$1"
}
register_patch "build_aar" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands/build_aar.dart" patch_build_aar

patch_build_appbundle() {
    if grep -F -q "defaultsTo: <String>['android-arm64']" "$1"; then return 0; fi
    grep -q "defaultsTo: <String>" "$1" || return 1
    sed -i "s/defaultsTo: <String>\['android-arm', 'android-arm64', 'android-x64'\]/defaultsTo: <String>['android-arm64']/" "$1"
}
register_patch "build_appbundle" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands/build_appbundle.dart" patch_build_appbundle

patch_plugin_utils() {
    # forceNdkDownload() patched to early return
    if grep -F -q "return // Termux" "$1"; then return 0; fi
    grep -q "fun forceNdkDownload" "$1" || return 1
    sed -i '/fun forceNdkDownload/,/^    }/ {
        /val forcingNotRequired: Boolean/i\        return // Termux: NDK already installed, skip CMake trick
    }' "$1"
}
register_patch "plugin_utils" "$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginUtils.kt" patch_plugin_utils

patch_flutter_cache() {
    if grep -F -q "_platform.isAndroid ? 'linux'" "$1"; then return 0; fi
    grep -q "artifacts\[_platform.operatingSystem\]" "$1" || return 1
    sed -i "s|final List<String>? binaryDirs = artifacts\[_platform.operatingSystem\];|final List<String>? binaryDirs = artifacts[_platform.isAndroid ? 'linux' : _platform.operatingSystem]; // Termux: map Android host to Linux artifacts|" "$1"
}
register_patch "flutter_cache" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/flutter_cache.dart" patch_flutter_cache

patch_artifacts() {
    if grep -F -q "platform.isAndroid" "$1"; then return 0; fi
    grep -q "if (platform.isLinux)" "$1" || return 1
    sed -i "s#if (platform.isLinux) {#if (platform.isLinux || platform.isAndroid) { // Termux: map Android host to Linux artifacts.#" "$1"
}
register_patch "artifacts" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/artifacts.dart" patch_artifacts

patch_build_info() {
    if grep -F -q "globals.platform.isAndroid" "$1"; then return 0; fi
    grep -q "if (globals.platform.isLinux)" "$1" || return 1
    sed -i "s#if (globals.platform.isLinux) {#if (globals.platform.isLinux || globals.platform.isAndroid) { // Termux: Android host uses Linux artifacts.#" "$1"
}
register_patch "build_info" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/build_info.dart" patch_build_info

patch_chrome() {
    if grep -F -q "platform.isAndroid" "$1"; then return 0; fi
    grep -q "if (platform.isLinux)" "$1" || return 1
    sed -i "s#if (platform.isLinux) {#if (platform.isLinux || platform.isAndroid) { // Termux: use Linux Chrome lookup on Android host.#" "$1"
}
register_patch "chrome" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/web/chrome.dart" patch_chrome

patch_build_linux() {
    if grep -F -q "false /* Termux" "$1"; then return 0; fi
    grep -q "if (!globals.platform.isLinux)" "$1" || return 1
    sed -i "s@if (!globals.platform.isLinux)@if (false /* Termux: allow linux build */)@" "$1"
    sed -i "s@!featureFlags.isLinuxEnabled || !globals.platform.isLinux@!featureFlags.isLinuxEnabled /* Termux: visible */@" "$1"
}
register_patch "build_linux" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/commands/build_linux.dart" patch_build_linux

patch_icon_tree_shaker() {
    if grep -F -q "false /* Termux" "$1"; then return 0; fi
    grep -q "kIconTreeShakerFlag" "$1" || return 1
    sed -i "s|_environment.defines\[kIconTreeShakerFlag\] == 'true'|false /* Termux: const_finder unavailable */|g" "$1"
}
register_patch "icon_tree_shaker" "$FLUTTER_ROOT/packages/flutter_tools/lib/src/build_system/targets/icon_tree_shaker.dart" patch_icon_tree_shaker

patch_cmake_lists() {
    if grep -F -q "FlutterNDKTrick" "$1"; then return 0; fi
    cat > "$1" << 'CMAKEOF'
cmake_minimum_required(VERSION 3.6)
project(FlutterNDKTrick C CXX)
CMAKEOF
}
register_patch "cmake_lists" "$FLUTTER_ROOT/packages/flutter_tools/gradle/src/main/scripts/CMakeLists.txt" patch_cmake_lists

patch_shebang_flutter() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_dart() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_shared() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_update_dart() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_content_hash() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_last_engine() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_update_engine() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }
patch_shebang_tool_backend() { if grep -F -q "#!/data/data/com.termux/files/usr/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|" "$1"; }

register_patch "shebang_flutter" "$FLUTTER_ROOT/bin/flutter" patch_shebang_flutter
register_patch "shebang_dart" "$FLUTTER_ROOT/bin/dart" patch_shebang_dart
register_patch "shebang_shared" "$FLUTTER_ROOT/bin/internal/shared.sh" patch_shebang_shared
register_patch "shebang_update_dart" "$FLUTTER_ROOT/bin/internal/update_dart_sdk.sh" patch_shebang_update_dart
register_patch "shebang_content_hash" "$FLUTTER_ROOT/bin/internal/content_aware_hash.sh" patch_shebang_content_hash
register_patch "shebang_last_engine" "$FLUTTER_ROOT/bin/internal/last_engine_commit.sh" patch_shebang_last_engine
register_patch "shebang_update_engine" "$FLUTTER_ROOT/bin/internal/update_engine_version.sh" patch_shebang_update_engine
register_patch "shebang_tool_backend" "$FLUTTER_ROOT/packages/flutter_tools/bin/tool_backend.sh" patch_shebang_tool_backend

if [ "$MODE" == "rollback" ]; then
    echo "Rolling back patches..."
    rollback_patches
    exit 0
fi

if [ "$MODE" == "status" ] || [ "$MODE" == "check" ]; then
    echo "Checking patch status..."
    apply_patches
    if [ "$MODE" == "check" ]; then exit 0; fi
fi

echo "Applying patches..."
apply_patches
# Force flutter_tools rebuild after patching
rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.stamp" 2>/dev/null
rm -f "$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot" 2>/dev/null



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
        if ! grep -q 'ANDROID_HOST_TAG' "$TOOLCHAIN" 2>/dev/null; then
            sed -i '1a set(ANDROID_HOST_TAG "linux-x86_64")' "$TOOLCHAIN"
        fi
    fi
    # Also patch the main android.toolchain.cmake
    local MAIN_TOOLCHAIN="$NDK_PATH/build/cmake/android.toolchain.cmake"
    if [ -f "$MAIN_TOOLCHAIN" ]; then
        if ! grep -q 'ANDROID_HOST_TAG' "$MAIN_TOOLCHAIN" 2>/dev/null; then
            sed -i '1a set(ANDROID_HOST_TAG "linux-x86_64")' "$MAIN_TOOLCHAIN"
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

# 1.5b. Fix engine.stamp and engine.realm (required for Maven artifact resolution)
echo "[1.5b/13] Fixing engine.stamp and engine.realm, and injecting framework version tag..."
cp $FLUTTER_ROOT/bin/internal/engine.version $FLUTTER_ROOT/bin/cache/engine.stamp 2>/dev/null || true
echo -n > $FLUTTER_ROOT/bin/cache/engine.realm 2>/dev/null || true
echo "  ✓ engine.stamp=$(cat $FLUTTER_ROOT/bin/cache/engine.stamp)"
echo "  ✓ engine.realm cleared"

if ! [ -d "$FLUTTER_ROOT/.git" ]; then
    echo "  ! Missing .git, creating dummy repository for version resolution..."
    cd "$FLUTTER_ROOT" || true

    # Extract actual version before removing the file
    FLUTTER_VER="3.44.2"
    if [ -f "version" ]; then
        FLUTTER_VER=$(cat version | tr -d '\n\r')
    fi

    rm -f version
    /data/data/com.termux/files/usr/bin/git init -q >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git config user.email "termux@example.com" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git config user.name "termux" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git add bin/flutter >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git commit -q -m "Init framework" >/dev/null 2>&1 || true
    /data/data/com.termux/files/usr/bin/git tag "$FLUTTER_VER" >/dev/null 2>&1 || true
    rm -f bin/cache/flutter.version.json 2>/dev/null || true
    echo "  ✓ Dummy tag $FLUTTER_VER created"
fi

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
        echo "  ✗ Download failed for Platform 36. Aborting."
        exit 1
    fi
    # Ensure no fake symlinks remain
    if [ -L "$ANDROID_SDK/platforms/android-36" ]; then
        rm -f "$ANDROID_SDK/platforms/android-36"
    fi
else
    echo "  ✓ Platform 36 already exists"
fi

# Install required Termux build dependencies
echo "[1.5e/13] Checking and installing Termux build dependencies..."

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

# Clear stale Gradle included-build outputs after changing the Flutter Gradle plugin.
# Without this, upgrades can compile FlutterPlugin.kt against an older cached
# FlutterPluginConstants.kt and fail with unresolved PLATFORM_ABI_LIST.
echo "  Clearing Flutter Gradle plugin build cache..."
rm -rf "$FLUTTER_ROOT/packages/flutter_tools/gradle/.gradle" \
       "$FLUTTER_ROOT/packages/flutter_tools/gradle/build" \
       "$FLUTTER_ROOT/packages/flutter_tools/gradle/bin" 2>/dev/null || true
echo "  ✓ Flutter Gradle plugin cache cleared"

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
        if [ "$tool" = "aapt2" ] && [ -L "$BUILD_TOOLS/aapt2" ] && readlink "$BUILD_TOOLS/aapt2" | grep -q "Android/Sdk"; then
            echo "    ✓ Retaining Mode B custom static aapt2 symlink"
        else
            ln -sf /data/data/com.termux/files/usr/bin/$tool "$BUILD_TOOLS/$tool" 2>/dev/null || true
        fi
    done

    # dexdump (from ART)
    if [ -f /apex/com.android.art/bin/dexdump ]; then
        ln -sf /apex/com.android.art/bin/dexdump "$BUILD_TOOLS/dexdump" 2>/dev/null || true
    fi

    # split-select stub
    if [ -L "$BUILD_TOOLS/split-select" ] && readlink "$BUILD_TOOLS/split-select" | grep -q "Android/Sdk"; then
        echo "    ✓ Retaining Mode B custom static split-select symlink"
    else
        cat > "$BUILD_TOOLS/split-select" << 'SPLITEOF'
#!/bin/sh
echo "split-select is not available on Termux ARM64"
exit 1
SPLITEOF
        chmod +x "$BUILD_TOOLS/split-select"
    fi

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

is_mode_b=false
if [ -L "$BT_DIR/35.0.0/aapt2" ] && readlink "$BT_DIR/35.0.0/aapt2" | grep -q "Android/Sdk"; then
    is_mode_b=true
fi

if [ "$is_mode_b" = "true" ]; then
    echo "  Validating Mode B toolchain (API 35+ / AAB)..."
    AAPT2_EXE="$BT_DIR/35.0.0/aapt2"
    TMP_DIR=$(mktemp -d "${TMPDIR:-$PREFIX/tmp}/mode_b_test.XXXXXX")
    TMP_RES_DIR="$TMP_DIR/res/values"
    mkdir -p "$TMP_RES_DIR"
    echo '<resources><string name="test">test</string></resources>' > "$TMP_RES_DIR/strings.xml"
    TMP_FLAT_DIR="$TMP_DIR/flat"
    mkdir -p "$TMP_FLAT_DIR"
    TMP_APK="$TMP_DIR/test.apk"

    mode_b_valid=false
    if "$AAPT2_EXE" compile "$TMP_RES_DIR/strings.xml" -o "$TMP_FLAT_DIR/" >/dev/null 2>&1; then
        FLAT_FILE=$(find "$TMP_FLAT_DIR" -name "*.flat" 2>/dev/null | head -n 1)
        if [ -n "$FLAT_FILE" ]; then
            if "$AAPT2_EXE" link "$FLAT_FILE" -o "$TMP_APK" >/dev/null 2>&1 || [ -f "$TMP_APK" ]; then
                mode_b_valid=true
            fi
        fi
    fi
    rm -rf "$TMP_DIR"

    if [ "$mode_b_valid" = "false" ]; then
        echo "  ❌ Error: Mode B toolchain validation failed (aapt2 compile/link failed)."
        echo "  Reverting Mode B activation to Mode A..."

        # Reversible activation: Revert back to Mode A
        rm -rf "$BT_DIR/35.0.0" 2>/dev/null || true
        sed -i '/android.aapt2FromMavenOverride/d' "$HOME/.gradle/gradle.properties" 2>/dev/null || true

        echo "  Mode B reverted. Please install a working NDK (e.g. lzhiyong/termux-ndk) to use Mode B."
        is_mode_b=false
    else
        echo "  ✓ Mode B toolchain validation passed (aapt2 compile/link works)."
    fi
fi

if [ -n "$BT_REAL" ]; then
    if [ "$is_mode_b" = "false" ] && [ ! -f "$BT_DIR/35.0.0/package.xml" ]; then
        echo "  Cloning $(basename $BT_REAL) -> 35.0.0 (for AGP validation)..."
        rm -rf "$BT_DIR/35.0.0"
        cp -a "$BT_REAL" "$BT_DIR/35.0.0"
        BT_REAL_NAME=$(basename "$BT_REAL")
        sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/source.properties" 2>/dev/null || true
        sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/package.xml" 2>/dev/null || true
    elif [ "$is_mode_b" = "true" ] && [ ! -f "$BT_DIR/35.0.0/package.xml" ]; then
        echo "  Re-aligning package metadata for Mode B build-tools..."
        cp "$BT_REAL/package.xml" "$BT_DIR/35.0.0/" 2>/dev/null || true
        cp "$BT_REAL/source.properties" "$BT_DIR/35.0.0/" 2>/dev/null || true
        BT_REAL_NAME=$(basename "$BT_REAL")
        sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/source.properties" 2>/dev/null || true
        sed -i "s/$BT_REAL_NAME/35.0.0/g" "$BT_DIR/35.0.0/package.xml" 2>/dev/null || true
    fi
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
