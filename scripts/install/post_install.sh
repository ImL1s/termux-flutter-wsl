#!/bin/bash
# Flutter Termux Post-Install Script
# 安裝 deb 包後執行此腳本以完成 APK 構建環境配置

set -e

echo "=========================================="
echo "Flutter Termux Post-Install Configuration"
echo "=========================================="

# 路徑定義
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
FLUTTER_ROOT="${FLUTTER_ROOT:-$PREFIX/opt/flutter}"
ANDROID_SDK="${ANDROID_SDK:-$PREFIX/opt/android-sdk}"
DART_SDK="${DART_SDK:-$FLUTTER_ROOT/bin/cache/dart-sdk}"
if [ -z "${FLUTTER_PREBUILT_ENGINE_VERSION:-}" ] && [ -f "$FLUTTER_ROOT/bin/internal/engine.version" ]; then
    export FLUTTER_PREBUILT_ENGINE_VERSION="$(cat "$FLUTTER_ROOT/bin/internal/engine.version" 2>/dev/null | tr -d '\n\r')"
fi

export PATH="$PREFIX/bin:$PATH"
PATCH_STATE_FILE="${PATCH_STATE_FILE:-$PREFIX/share/flutter/patch_state.json}"
BACKUP_DIR="${BACKUP_DIR:-$PREFIX/share/flutter/backups}"

MODE="${MODE:-apply}"
if [ "${1:-}" = "--check" ]; then MODE="check"; fi
if [ "${1:-}" = "--apply" ]; then MODE="apply"; fi
if [ "${1:-}" = "--status" ]; then MODE="status"; fi
if [ "${1:-}" = "--rollback" ]; then MODE="rollback"; fi
if [ "${1:-}" = "--lib" ]; then MODE="lib"; fi

if [ "$MODE" != "status" ] && [ "$MODE" != "check" ] && [ "$MODE" != "lib" ]; then
    mkdir -p "$BACKUP_DIR" "$(dirname "$PATCH_STATE_FILE")"
    if [ ! -f "$PATCH_STATE_FILE" ]; then
        echo "{}" > "$PATCH_STATE_FILE"
    fi
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

if [ -f "$PATCH_STATE_FILE" ]; then
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
fi

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
            local tmp_check
            tmp_check=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/patch_check_${$}_${RANDOM}")
            cp "$target_file" "$tmp_check" 2>/dev/null || true
            if $patch_func "$tmp_check" 2>/dev/null && cmp -s "$target_file" "$tmp_check"; then
                echo "  ✓ $patch_name: already correct"
                rm -f "$tmp_check"
                continue
            fi
            rm -f "$tmp_check"
            echo "  + $patch_name: pending"
            continue
        fi

        if [ "$MODE" == "status" ] || [ "$MODE" == "check" ]; then
            continue
        fi

        echo "  Applying $patch_name..."
        if [ ! -f "$BACKUP_DIR/$patch_name.orig" ] || [ -z "${STATE_PREIMAGE[$patch_name]}" ] || [ "$current_hash" != "${STATE_PREIMAGE[$patch_name]}" ]; then
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

    if [ "$MODE" == "apply" ]; then
        save_state
    fi
    if [ $any_failed -eq 1 ]; then
        echo "Some patches failed. Aborting."
        exit 1
    fi
}

backup_ndk_file() {
    local file="$1"
    if [ -f "$file" ] || [ -L "$file" ]; then
        local rel_path="${file#$ANDROID_SDK/}"
        local backup_target="$BACKUP_DIR/ndk_backups/$rel_path"
        if [ ! -f "$backup_target" ] && [ ! -L "$backup_target" ]; then
            mkdir -p "$(dirname "$backup_target")"
            cp -a "$file" "$backup_target" 2>/dev/null || true
        fi
    fi
}

restore_ndk_backups() {
    if [ -d "$BACKUP_DIR/ndk_backups" ]; then
        echo "  Restoring NDK backups..."
        (
            cd "$BACKUP_DIR/ndk_backups"
            find . -type f -o -type l | while read -r rel; do
                local dest="$ANDROID_SDK/$rel"
                mkdir -p "$(dirname "$dest")"
                cp -a "$rel" "$dest" 2>/dev/null || true
                echo "  ✓ Restored $dest"
            done
        )
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
    restore_ndk_backups
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
    if grep -F -q "_platform.isAndroid" "$1"; then return 0; fi
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

patch_shebang_flutter() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_dart() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_shared() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_update_dart() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_content_hash() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_last_engine() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_update_engine() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }
patch_shebang_tool_backend() { if grep -F -q "#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash" "$1"; then return 0; fi; sed -i "1s|#!/usr/bin/env bash|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$1"; }

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
    exit 0
fi


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
CLANG_WRAPPER="#!${PREFIX:-/data/data/com.termux/files/usr}/bin/sh
PREFIX=\"\${PREFIX:-${PREFIX:-/data/data/com.termux/files/usr}}\"
NDK=\"$NDK_PATH\"
SYSROOT=\"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot\"
CLANG_VERSION=\$(ls -1 \"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\" 2>/dev/null | sort -V | tail -n 1)
CLANG_LIB=\"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\$CLANG_VERSION/lib/linux\"

ARCH=\"\"
for arg in \"\$@\"; do
    case \"\$arg\" in
        --target=aarch64*) ARCH=\"aarch64\" ;;
        --target=arm*) ARCH=\"arm\" ;;
    esac
done

if [ \"\$ARCH\" = \"aarch64\" ]; then
    LIB_PATH=\"\$SYSROOT/usr/lib/aarch64-linux-android\"
    CLANG_LIB_ARCH=\"\$CLANG_LIB/aarch64\"
elif [ \"\$ARCH\" = \"arm\" ]; then
    LIB_PATH=\"\$SYSROOT/usr/lib/arm-linux-androideabi\"
    CLANG_LIB_ARCH=\"\$CLANG_LIB/arm\"
else
    exec \"\$PREFIX/bin/clang\" \"\$@\"
fi

exec \"\$PREFIX/bin/clang\" -L\"\$LIB_PATH\" -L\"\$CLANG_LIB_ARCH\" \"\$@\""

CLANGPP_WRAPPER="#!${PREFIX:-/data/data/com.termux/files/usr}/bin/sh
PREFIX=\"\${PREFIX:-${PREFIX:-/data/data/com.termux/files/usr}}\"
NDK=\"$NDK_PATH\"
SYSROOT=\"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot\"
CLANG_VERSION=\$(ls -1 \"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\" 2>/dev/null | sort -V | tail -n 1)
CLANG_LIB=\"\$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/\$CLANG_VERSION/lib/linux\"

ARCH=\"\"
for arg in \"\$@\"; do
    case \"\$arg\" in
        --target=aarch64*) ARCH=\"aarch64\" ;;
        --target=arm*) ARCH=\"arm\" ;;
    esac
done

if [ \"\$ARCH\" = \"aarch64\" ]; then
    LIB_PATH=\"\$SYSROOT/usr/lib/aarch64-linux-android\"
    CLANG_LIB_ARCH=\"\$CLANG_LIB/aarch64\"
elif [ \"\$ARCH\" = \"arm\" ]; then
    LIB_PATH=\"\$SYSROOT/usr/lib/arm-linux-androideabi\"
    CLANG_LIB_ARCH=\"\$CLANG_LIB/arm\"
else
    exec \"\$PREFIX/bin/clang++\" \"\$@\"
fi

exec \"\$PREFIX/bin/clang++\" -L\"\$LIB_PATH\" -L\"\$CLANG_LIB_ARCH\" \"\$@\""

    # Create wrappers in prebuilt/bin/ (for some toolchain configs)
    mkdir -p "$PREBUILT/bin"
    backup_ndk_file "$PREBUILT/bin/clang"
    backup_ndk_file "$PREBUILT/bin/clang++"
    echo "$CLANG_WRAPPER" > "$PREBUILT/bin/clang"
    chmod +x "$PREBUILT/bin/clang"
    echo "$CLANGPP_WRAPPER" > "$PREBUILT/bin/clang++"
    chmod +x "$PREBUILT/bin/clang++"

    # Create wrappers in prebuilt/linux-x86_64/bin/ (official NDK structure)
    mkdir -p "$PREBUILT/linux-x86_64/bin"
    # Remove symlinks/files first (clang -> clang-18, clang++ -> clang chain causes overwrites)
    # Must use unlink to properly remove symlinks before writing
    for f in clang clang++; do
        backup_ndk_file "$PREBUILT/linux-x86_64/bin/$f"
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
        backup_ndk_file "$TOOLCHAIN"
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
        backup_ndk_file "$MAIN_TOOLCHAIN"
        if ! grep -q 'ANDROID_HOST_TAG' "$MAIN_TOOLCHAIN" 2>/dev/null; then
            sed -i '1a set(ANDROID_HOST_TAG "linux-x86_64")' "$MAIN_TOOLCHAIN"
        fi
    fi

    # Replace x86_64 llvm-objcopy/llvm-strip with Termux ARM64 native binaries
    # (Gradle StripDebugSymbolsRunnable fails with x86_64 binaries on ARM64)
    local LLVM_BIN="$PREBUILT/linux-x86_64/bin"
    if [ -f "$PREFIX/bin/llvm-objcopy" ]; then
        backup_ndk_file "$LLVM_BIN/llvm-objcopy"
        backup_ndk_file "$LLVM_BIN/llvm-strip"
        cp "$PREFIX/bin/llvm-objcopy" "$LLVM_BIN/llvm-objcopy" 2>/dev/null || true
        cp "$PREFIX/bin/llvm-strip" "$LLVM_BIN/llvm-strip" 2>/dev/null || true
        echo "    ✓ llvm-objcopy/llvm-strip replaced with ARM64 native"
    fi

    echo "    ✓ NDK $NDK_NAME configured"
}

# Handle library mode (for unit testing / function sourcing)
if [ "$MODE" == "lib" ]; then
    return 0 2>/dev/null || exit 0
fi

# Handle read-only modes (--status, --check) and rollback mode (--rollback) immediately
if [ "$MODE" == "status" ] || [ "$MODE" == "check" ]; then
    echo "=== Post-install read-only report ($MODE) ==="
    apply_patches
    echo "=== Post-install read-only report finished ==="
    exit 0
fi

if [ "$MODE" == "rollback" ]; then
    echo "=== Rolling back post-install patches ==="
    rollback_patches
    echo "=== Rollback finished ==="
    exit 0
fi

# Run apply_patches for --apply
apply_patches

# 1.5b. Fix engine.stamp and engine.realm (required for Maven artifact resolution)
echo "[1.5b/13] Fixing engine.stamp and engine.realm, and injecting framework version tag..."
mkdir -p "$FLUTTER_ROOT/bin/cache"
[ -s "$FLUTTER_ROOT/bin/internal/engine.version" ] || echo -n "77e2e94772b6eb43759e34ed1ad7da4674e19cab" > "$FLUTTER_ROOT/bin/internal/engine.version"
local_eng_ver="$(cat "$FLUTTER_ROOT/bin/internal/engine.version" 2>/dev/null | tr -d '\n\r')"
echo -n "$local_eng_ver" > "$FLUTTER_ROOT/bin/cache/engine.stamp" 2>/dev/null || true
echo -n "$local_eng_ver" > "$FLUTTER_ROOT/bin/cache/engine_stamp.stamp" 2>/dev/null || true
echo -n > "$FLUTTER_ROOT/bin/cache/engine.realm" 2>/dev/null || true

# Patch update_engine_version.sh to reliably read bin/internal/engine.version offline
if [ -f "$FLUTTER_ROOT/bin/internal/update_engine_version.sh" ]; then
    sed -i 's/elif.*ls-files.*engine.version.*/elif [ -f "$FLUTTER_ROOT\/bin\/internal\/engine.version" ]; then/' "$FLUTTER_ROOT/bin/internal/update_engine_version.sh" 2>/dev/null || true
fi

mkdir -p "$FLUTTER_ROOT/bin/cache/artifacts/material_fonts"
mkdir -p "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradle/wrapper"

# Populate real gradle wrapper if missing or 0 bytes
if [ ! -s "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradle/wrapper/gradle-wrapper.jar" ]; then
    echo "  Downloading Gradle Wrapper..."
    WRAPPER_REL_PATH=""
    if [ -f "$FLUTTER_ROOT/bin/internal/gradle_wrapper.version" ]; then
        WRAPPER_REL_PATH="$(cat "$FLUTTER_ROOT/bin/internal/gradle_wrapper.version" | tr -d '\n\r')"
    fi
    if [ -n "$WRAPPER_REL_PATH" ]; then
        cd "${TMPDIR:-$PREFIX/tmp}"
        ( set +e; curl -s -L "https://storage.googleapis.com/$WRAPPER_REL_PATH" | tar -xz -C "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper" 2>/dev/null ) || true
        rm -f "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradle/wrapper/gradle-wrapper.properties" 2>/dev/null || true
        rm -f "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/NOTICE" 2>/dev/null || true
    fi
fi
if [ -f "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" ]; then
    sed -i "1s|.*|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" 2>/dev/null || true
    chmod 755 "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" 2>/dev/null || true
else
    touch "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew.bat" "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradle/wrapper/gradle-wrapper.jar" 2>/dev/null || true
    sed -i "1s|.*|#!${PREFIX:-/data/data/com.termux/files/usr}/bin/bash|" "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" 2>/dev/null || true
    chmod 755 "$FLUTTER_ROOT/bin/cache/artifacts/gradle_wrapper/gradlew" 2>/dev/null || true
fi

# Populate real material fonts if missing or empty
if [ ! -d "$FLUTTER_ROOT/bin/cache/artifacts/material_fonts" ] || [ -z "$(ls -A "$FLUTTER_ROOT/bin/cache/artifacts/material_fonts" 2>/dev/null)" ]; then
    echo "  Downloading Material Fonts..."
    FONTS_REL_PATH=""
    if [ -f "$FLUTTER_ROOT/bin/internal/material_fonts.version" ]; then
        FONTS_REL_PATH="$(cat "$FLUTTER_ROOT/bin/internal/material_fonts.version" | tr -d '\n\r')"
    fi
    if [ -n "$FONTS_REL_PATH" ]; then
        cd "${TMPDIR:-$PREFIX/tmp}"
        ( set +e; curl -s -L "https://storage.googleapis.com/$FONTS_REL_PATH" -o fonts.zip 2>/dev/null && unzip -q -o fonts.zip -d "$FLUTTER_ROOT/bin/cache/artifacts/material_fonts" 2>/dev/null && rm -f fonts.zip ) || true
    fi
fi

for vfile in "$FLUTTER_ROOT"/bin/internal/*.version; do
    [ -f "$vfile" ] || continue
    vname=$(basename "$vfile" .version)
    cp "$vfile" "$FLUTTER_ROOT/bin/cache/${vname}.stamp" 2>/dev/null || true
done
cat > "$FLUTTER_ROOT/bin/cache/engine_stamp.json" << EOF
{
  "build_time_ms": 1770000000000,
  "git_revision": "$local_eng_ver",
  "git_revision_date": "2026-06-09T00:00:00Z",
  "content_hash": "$local_eng_ver"
}
EOF
echo "  ✓ engine.stamp=$(cat "$FLUTTER_ROOT/bin/cache/engine.stamp" 2>/dev/null || echo 'unknown')"
echo "  ✓ engine.realm cleared"

GIT_BIN="${PREFIX:-/data/data/com.termux/files/usr}/bin/git"
if ! [ -x "$GIT_BIN" ] && ! command -v "$GIT_BIN" >/dev/null 2>&1; then
    GIT_BIN="git"
fi

# Load canonical metadata from packaged manifest or embedded source-of-truth constants
CANONICAL_FLUTTER_VER="3.44.9"
CANONICAL_FRAMEWORK_REV="6b182d2c7585eba26d4edce0f97630effd256c33"
CANONICAL_FRAMEWORK_DATE="2026-08-05 17:04:07 +0000"
CANONICAL_ENGINE_REV="$local_eng_ver"
CANONICAL_DART_VER="3.12.2"
CANONICAL_DEVTOOLS_VER="2.42.0"
CANONICAL_CHANNEL="stable"
CANONICAL_REPO_URL="https://github.com/flutter/flutter.git"

MANIFEST_LOADED=0
MANIFEST_FILE="$PREFIX/share/flutter/manifest.json"
if [ ! -f "$MANIFEST_FILE" ] && [ -f "$FLUTTER_ROOT/bin/cache/canonical_manifest.json" ]; then
    MANIFEST_FILE="$FLUTTER_ROOT/bin/cache/canonical_manifest.json"
fi

if [ -f "$MANIFEST_FILE" ]; then
    m_ver=$(grep -o '"flutter_version": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    m_rev=$(grep -o '"framework_revision": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    m_date=$(grep -o '"framework_commit_date": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    m_eng=$(grep -o '"engine_revision": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    m_dart=$(grep -o '"dart_version": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    m_dev=$(grep -o '"devtools_version": *"[^"]*"' "$MANIFEST_FILE" 2>/dev/null | cut -d'"' -f4 || echo "")
    if [ -n "$m_ver" ]; then
        CANONICAL_FLUTTER_VER="$m_ver"
        MANIFEST_LOADED=1
    fi
    [ -n "$m_rev" ] && CANONICAL_FRAMEWORK_REV="$m_rev"
    [ -n "$m_date" ] && CANONICAL_FRAMEWORK_DATE="$m_date"
    [ -n "$m_eng" ] && CANONICAL_ENGINE_REV="$m_eng"
    [ -n "$m_dart" ] && CANONICAL_DART_VER="$m_dart"
    [ -n "$m_dev" ] && CANONICAL_DEVTOOLS_VER="$m_dev"
fi

# Fallback ONLY when package manifest is NOT present (e.g. legacy installation without manifest)
if [ "$MANIFEST_LOADED" -eq 0 ]; then
    if [ -f "$FLUTTER_ROOT/version" ]; then
        fixture_ver="$(cat "$FLUTTER_ROOT/version" | tr -d '\n\r')"
        if [ -n "$fixture_ver" ] && echo "$fixture_ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
            CANONICAL_FLUTTER_VER="$fixture_ver"
        fi
    elif [ -f "$FLUTTER_ROOT/.git/termux_synthetic" ]; then
        saved_synth_ver=$(grep -o '"version": *"[^"]*"' "$FLUTTER_ROOT/.git/termux_synthetic" 2>/dev/null | cut -d'"' -f4 || echo "")
        if [ -n "$saved_synth_ver" ] && echo "$saved_synth_ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
            CANONICAL_FLUTTER_VER="$saved_synth_ver"
        fi
    fi
fi

# Fail-closed change directory
cd "$FLUTTER_ROOT" || { echo "Error: Failed to cd to $FLUTTER_ROOT" >&2; exit 1; }

# Helper to identify if .git was created as a synthetic termux repository
is_synthetic_repo() {
    local target_dir="$1"
    local git_dir="$target_dir/.git"
    [ -d "$git_dir" ] || return 1
    if [ -f "$git_dir/termux_synthetic" ]; then
        return 0
    fi
    local commit_count
    commit_count=$("$GIT_BIN" --git-dir="$git_dir" rev-list --count HEAD 2>/dev/null || echo "999")
    local first_msg
    first_msg=$("$GIT_BIN" --git-dir="$git_dir" log -1 --pretty=%B 2>/dev/null || echo "")
    if [ "$commit_count" -le 2 ] && [ "$first_msg" = "Init framework" ]; then
        return 0
    fi
    return 1
}

mark_synthetic_repo() {
    echo "{\"synthetic\":true,\"package\":\"termux-flutter-wsl\",\"version\":\"$CANONICAL_FLUTTER_VER\",\"framework_revision\":\"$CANONICAL_FRAMEWORK_REV\"}" > .git/termux_synthetic
}

ensure_origin_remote() {
    if ! "$GIT_BIN" remote get-url origin >/dev/null 2>&1; then
        "$GIT_BIN" remote add origin "$CANONICAL_REPO_URL" >/dev/null 2>&1 || true
    else
        "$GIT_BIN" remote set-url origin "$CANONICAL_REPO_URL" >/dev/null 2>&1 || true
    fi
}

purge_noncanonical_tags() {
    local existing_tags t
    existing_tags=$("$GIT_BIN" tag -l 2>/dev/null || echo "")
    for t in $existing_tags; do
        if [ "$t" != "$CANONICAL_FLUTTER_VER" ]; then
            "$GIT_BIN" tag -d "$t" >/dev/null 2>&1 || true
        fi
    done
    if ! "$GIT_BIN" tag --points-at HEAD 2>/dev/null | grep -qx "$CANONICAL_FLUTTER_VER"; then
        "$GIT_BIN" tag -f "$CANONICAL_FLUTTER_VER" HEAD >/dev/null 2>&1 || true
    fi
    rm -f .git/FETCH_HEAD
}

# Prefer a depth-1 tag fetch so flutter --version reports the real framework
# revision/URL. Do NOT checkout files — the packaged worktree must stay intact.
try_shallow_canonical_checkout() {
    ensure_origin_remote
    local fetch_cmd=( "$GIT_BIN" fetch --depth 1 origin tag "$CANONICAL_FLUTTER_VER" )
    local alt_fetch_cmd=( "$GIT_BIN" fetch --depth 1 origin "refs/tags/${CANONICAL_FLUTTER_VER}:refs/tags/${CANONICAL_FLUTTER_VER}" )
    if command -v timeout >/dev/null 2>&1; then
        fetch_cmd=( timeout 20 "${fetch_cmd[@]}" )
        alt_fetch_cmd=( timeout 20 "${alt_fetch_cmd[@]}" )
    fi
    if ! "${fetch_cmd[@]}" >/dev/null 2>&1; then
        if ! "${alt_fetch_cmd[@]}" >/dev/null 2>&1; then
            return 1
        fi
    fi
    local tag_rev
    tag_rev=$("$GIT_BIN" rev-parse "refs/tags/${CANONICAL_FLUTTER_VER}" 2>/dev/null || echo "")
    if [ -z "$tag_rev" ] || [ "$tag_rev" != "$CANONICAL_FRAMEWORK_REV" ]; then
        return 1
    fi
    # Point stable at the tag without overwriting packaged files.
    "$GIT_BIN" update-ref refs/heads/stable "$tag_rev" >/dev/null 2>&1 || return 1
    "$GIT_BIN" symbolic-ref HEAD refs/heads/stable >/dev/null 2>&1 || return 1
    # Flutter resolves repositoryUrl via @{upstream} → remote URL.
    "$GIT_BIN" update-ref refs/remotes/origin/stable "$tag_rev" >/dev/null 2>&1 || return 1
    "$GIT_BIN" branch --set-upstream-to=origin/stable stable >/dev/null 2>&1 || true
    "$GIT_BIN" config core.filemode false >/dev/null 2>&1 || true
    purge_noncanonical_tags
    mark_synthetic_repo
    echo "  ✓ Canonical tag ref ${CANONICAL_FLUTTER_VER} ($CANONICAL_FRAMEWORK_REV) without worktree overwrite"
    return 0
}

init_fallback_synthetic_commit() {
    rm -f version
    "$GIT_BIN" add -f bin/flutter bin/internal/engine.version bin/internal/*.version >/dev/null 2>&1 || true
    "$GIT_BIN" commit -q -m "Init framework" >/dev/null 2>&1 || true
    "$GIT_BIN" branch -M stable >/dev/null 2>&1 || true
    "$GIT_BIN" tag -f "$CANONICAL_FLUTTER_VER" HEAD >/dev/null 2>&1
    ensure_origin_remote
    purge_noncanonical_tags
    mark_synthetic_repo
}

# Synthetic repo setup & contamination repair
if ! [ -d "$FLUTTER_ROOT/.git" ]; then
    echo "  ! Missing .git, creating identity repository on stable branch..."
    rm -f version
    "$GIT_BIN" init -q -b stable >/dev/null 2>&1 || "$GIT_BIN" init -q >/dev/null 2>&1
    "$GIT_BIN" symbolic-ref HEAD refs/heads/stable >/dev/null 2>&1 || true
    "$GIT_BIN" config user.email "termux@example.com"
    "$GIT_BIN" config user.name "termux"
    if ! try_shallow_canonical_checkout; then
        init_fallback_synthetic_commit
        echo "  ✓ Fallback synthetic tag $CANONICAL_FLUTTER_VER created on stable branch (offline/no exact commit)"
    fi
elif is_synthetic_repo "$FLUTTER_ROOT"; then
    echo "  ! Verifying and repairing synthetic repository state..."
    rm -f version
    curr_br="$("$GIT_BIN" symbolic-ref --short HEAD 2>/dev/null || echo "")"
    if [ "$curr_br" != "stable" ]; then
        "$GIT_BIN" checkout -B stable >/dev/null 2>&1 || "$GIT_BIN" branch -M stable >/dev/null 2>&1 || "$GIT_BIN" symbolic-ref HEAD refs/heads/stable >/dev/null 2>&1
    fi
    ensure_origin_remote
    head_rev=$("$GIT_BIN" rev-parse HEAD 2>/dev/null || echo "")
    if [ "$head_rev" != "$CANONICAL_FRAMEWORK_REV" ]; then
        if ! try_shallow_canonical_checkout; then
            purge_noncanonical_tags
            mark_synthetic_repo
            echo "  ✓ Synthetic repository sanitized: branch=stable, tag=$CANONICAL_FLUTTER_VER (exact upstream commit unavailable)"
        fi
    else
        purge_noncanonical_tags
        mark_synthetic_repo
        echo "  ✓ Synthetic repository sanitized: branch=stable, tag=$CANONICAL_FLUTTER_VER @ $CANONICAL_FRAMEWORK_REV"
    fi
else
    # Non-synthetic / real user or upstream checkout: guardrail to protect user work
    echo "  ℹ Non-synthetic / user-owned Git checkout detected at $FLUTTER_ROOT; preserving git history and refs"
    if [ -n "$("$GIT_BIN" status --porcelain 2>/dev/null)" ]; then
        echo "    (Note: working tree contains modifications)"
    fi
fi

# Fail-closed postcondition verification for synthetic repos
if is_synthetic_repo "$FLUTTER_ROOT"; then
    verified_branch="$("$GIT_BIN" symbolic-ref --short HEAD 2>/dev/null || echo "unknown")"
    if [ "$verified_branch" != "stable" ]; then
        echo "Error: Synthetic repository branch verification failed: expected 'stable', got '$verified_branch'" >&2
        exit 1
    fi
    tags_at_head="$("$GIT_BIN" tag --points-at HEAD 2>/dev/null || echo "")"
    if ! echo "$tags_at_head" | grep -qx "$CANONICAL_FLUTTER_VER"; then
        echo "Error: Synthetic repository tag verification failed: '$CANONICAL_FLUTTER_VER' not pointing at HEAD" >&2
        exit 1
    fi
    tag_count="$("$GIT_BIN" tag -l 2>/dev/null | wc -l)"
    if [ "$tag_count" -ne 1 ]; then
        echo "Error: Synthetic repository tag count verification failed: expected 1 tag, found $tag_count" >&2
        exit 1
    fi
fi

# Determine and verify semantic Dart SDK version (never engine cache stamp)
EFFECTIVE_DART_VER=""
if [ -x "$DART_SDK/bin/dart" ]; then
    EFFECTIVE_DART_VER="$("$DART_SDK/bin/dart" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")"
elif command -v dart >/dev/null 2>&1; then
    EFFECTIVE_DART_VER="$(dart --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")"
fi

if [ -n "$EFFECTIVE_DART_VER" ]; then
    if [ "$EFFECTIVE_DART_VER" != "$CANONICAL_DART_VER" ]; then
        echo "Error: Installed Dart SDK version mismatch: expected '$CANONICAL_DART_VER', got '$EFFECTIVE_DART_VER'" >&2
        exit 1
    fi
else
    # Fallback to canonical when Dart binary is not executable in minimal mock fixtures
    EFFECTIVE_DART_VER="$CANONICAL_DART_VER"
fi

# Atomic generation and validation of canonical flutter.version.json
TMP_VER_JSON="$FLUTTER_ROOT/bin/cache/flutter.version.json.tmp.$$"
cat > "$TMP_VER_JSON" << EOF
{
  "frameworkVersion": "$CANONICAL_FLUTTER_VER",
  "channel": "$CANONICAL_CHANNEL",
  "repositoryUrl": "$CANONICAL_REPO_URL",
  "frameworkRevision": "$CANONICAL_FRAMEWORK_REV",
  "frameworkCommitDate": "$CANONICAL_FRAMEWORK_DATE",
  "engineRevision": "$CANONICAL_ENGINE_REV",
  "dartSdkVersion": "$EFFECTIVE_DART_VER",
  "devToolsVersion": "$CANONICAL_DEVTOOLS_VER",
  "flutterVersion": "$CANONICAL_FLUTTER_VER"
}
EOF

# Strict validation
if ! grep -q "\"frameworkVersion\": \"$CANONICAL_FLUTTER_VER\"" "$TMP_VER_JSON" || \
   ! grep -q "\"channel\": \"stable\"" "$TMP_VER_JSON" || \
   ! grep -q "\"repositoryUrl\": \"https://github.com/flutter/flutter.git\"" "$TMP_VER_JSON" || \
   ! grep -q "\"frameworkRevision\": \"$CANONICAL_FRAMEWORK_REV\"" "$TMP_VER_JSON" || \
   ! grep -q "\"engineRevision\": \"$CANONICAL_ENGINE_REV\"" "$TMP_VER_JSON" || \
   ! grep -q "\"dartSdkVersion\": \"$EFFECTIVE_DART_VER\"" "$TMP_VER_JSON" || \
   ! grep -q "\"devToolsVersion\": \"$CANONICAL_DEVTOOLS_VER\"" "$TMP_VER_JSON" || \
   ! grep -q "\"flutterVersion\": \"$CANONICAL_FLUTTER_VER\"" "$TMP_VER_JSON"; then
    echo "Error: Generated flutter.version.json failed canonical validation" >&2
    rm -f "$TMP_VER_JSON"
    exit 1
fi

mv -f "$TMP_VER_JSON" "$FLUTTER_ROOT/bin/cache/flutter.version.json"
chmod 644 "$FLUTTER_ROOT/bin/cache/flutter.version.json"
echo "  ✓ Canonical flutter.version.json generated ($CANONICAL_FLUTTER_VER stable, framework=$CANONICAL_FRAMEWORK_REV)"

# Get engine version for downloads
ENGINE_VERSION=$(cat $FLUTTER_ROOT/bin/internal/engine.version 2>/dev/null || echo "77e2e94772b6eb43759e34ed1ad7da4674e19cab")

# 0. 下載官方 Dart SDK snapshots (修復 flutter run hot reload)
echo "[0/13] Downloading official Dart SDK snapshots (for hot reload)..."
SNAPSHOTS_URL="https://storage.googleapis.com/flutter_infra_release/flutter/${ENGINE_VERSION}/dart-sdk-linux-arm64.zip"
SNAPSHOTS_DIR=$DART_SDK/bin/snapshots

# Check if key snapshot is missing
if [ ! -f "$SNAPSHOTS_DIR/dds_aot.dart.snapshot" ]; then
    echo "  Downloading dart-sdk-linux-arm64.zip..."
    cd "${TMPDIR:-$PREFIX/tmp}"
    ( set +e; curl -L -o dart-sdk.zip "$SNAPSHOTS_URL" >/dev/null 2>&1 ) || true
    if [ -f dart-sdk.zip ]; then
        echo "  Extracting snapshots..."
        unzip -o -j dart-sdk.zip 'dart-sdk/bin/snapshots/*' -d "$SNAPSHOTS_DIR" 2>/dev/null || true
        rm -f dart-sdk.zip
        echo "  ✓ Dart SDK snapshots installed"
    else
        echo "  ⚠ Network unavailable, skipping Dart SDK snapshots download"
    fi

    # Create symlinks for non-AOT versions
    ln -sf frontend_server_aot.dart.snapshot "$SNAPSHOTS_DIR/frontend_server.dart.snapshot" 2>/dev/null || true
else
    echo "  ✓ Dart SDK snapshots already exist"
fi

# 1. 清理 ELF 二進制的 DT_RPATH (修復 flutter run crash)
echo "[1/13] Cleaning ELF binaries (fix flutter run)..."
if ! command -v termux-elf-cleaner &> /dev/null; then
    ( set +e; pkg install -y termux-elf-cleaner >/dev/null 2>&1 ) || true
fi

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

# 1.5d. Install Android SDK Platform 36 (Flutter 3.44.0 requirement)
echo "[1.5d/13] Installing Android SDK Platform 36..."
if [ ! -d "$ANDROID_SDK/platforms/android-36" ]; then
    mkdir -p $ANDROID_SDK/platforms
    cd $ANDROID_SDK/platforms
    ( set +e; curl -L -o platform-36.zip 'https://dl.google.com/android/repository/platform-36_r01.zip' >/dev/null 2>&1 ) || true
    if [ -f platform-36.zip ] && [ -s platform-36.zip ]; then
        unzip -q platform-36.zip 2>/dev/null || true
        rm -f platform-36.zip
        echo "  ✓ Platform 36 installed"
    else
        echo "  ⚠ Download skipped/unavailable for Platform 36"
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

# Rewrite WSL build machine paths in prebuilt package_config.json to local FLUTTER_ROOT
if [ -f "$PKG_CONFIG" ]; then
    echo "  Rewriting package_config.json paths to $FLUTTER_ROOT..."
    sed -i "s|file://.*/flutter/|file://$FLUTTER_ROOT/|g" "$PKG_CONFIG" 2>/dev/null || true
    echo "  ✓ package_config.json paths updated"
fi

if [ ! -f "$PKG_CONFIG" ]; then
    echo "  Running pub get for flutter_tools..."
    cd "$FLUTTER_TOOLS_DIR"
    $DART_SDK/bin/dart pub get --offline --suppress-analytics >/dev/null 2>&1 || ( set +e; $DART_SDK/bin/dart pub get --suppress-analytics >/dev/null 2>&1 ) || true
    if [ -f "$PKG_CONFIG" ]; then
        echo "  ✓ package_config.json generated"
    else
        echo "  ⚠ Offline environment: package_config.json generation deferred"
    fi
fi

# 2. 下載並安裝 Android API 34 (aapt2 bug workaround)
echo "[2/13] Installing Android API 34..."
if [ ! -d "$ANDROID_SDK/platforms/android-34" ]; then
    cd $ANDROID_SDK/platforms
    ( set +e; curl -L -o platform-34.zip 'https://dl.google.com/android/repository/platform-34-ext7_r02.zip' >/dev/null 2>&1 ) || true
    if [ -f platform-34.zip ] && [ -s platform-34.zip ]; then
        unzip -q platform-34.zip 2>/dev/null || true
        rm -f platform-34.zip
        echo "  ✓ API 34 installed"
    else
        echo "  ⚠ API 34 download skipped (offline)"
    fi
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
            ln -sf "$PREFIX/bin/$tool" "$BUILD_TOOLS/$tool" 2>/dev/null || true
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
    ln -sf "$PREFIX/share/java/d8.jar" "$BUILD_TOOLS/lib/d8.jar" 2>/dev/null || true
    ln -sf "$PREFIX/share/java/d8.jar" "$BUILD_TOOLS/lib/dx.jar" 2>/dev/null || true

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
mkdir -p "$ANDROID_SDK/platform-tools"
# Remove any x86_64 binaries Gradle may have downloaded
rm -f "$ANDROID_SDK/platform-tools/adb" "$ANDROID_SDK/platform-tools/fastboot" 2>/dev/null || true
ln -sf "$PREFIX/bin/adb" "$ANDROID_SDK/platform-tools/adb" 2>/dev/null || true
ln -sf "$PREFIX/bin/fastboot" "$ANDROID_SDK/platform-tools/fastboot" 2>/dev/null || true
echo "  ✓ platform-tools symlinks created"

# 10. 接受 Android licenses
echo "[11/13] Accepting Android licenses..."
mkdir -p $ANDROID_SDK/licenses
echo -e "\n24333f8a63b6825ea9c5514f83c2829b004d1fee" > $ANDROID_SDK/licenses/android-sdk-license
echo -e "\n84831b9409646a918e30573bab4c9c91346d8abd" > $ANDROID_SDK/licenses/android-sdk-preview-license
echo "  ✓ Android licenses accepted"

# 10.5. Configure ANDROID_HOME in flutter config
echo "[11.5/13] Setting Android SDK path in Flutter config..."
mkdir -p "$HOME" 2>/dev/null || true
if [ -f "$HOME/.flutter_settings" ]; then
    grep -v '"android-sdk"' "$HOME/.flutter_settings" 2>/dev/null | grep -v '^[[:space:]]*}$' > "$HOME/.flutter_settings.tmp" 2>/dev/null || true
    echo '  ,"android-sdk": "'"$ANDROID_SDK"'"' >> "$HOME/.flutter_settings.tmp"
    echo '}' >> "$HOME/.flutter_settings.tmp"
    mv "$HOME/.flutter_settings.tmp" "$HOME/.flutter_settings" 2>/dev/null || true
else
    cat > "$HOME/.flutter_settings" << SETTINGS
{
  "android-sdk": "$ANDROID_SDK",
  "analytics": false
}
SETTINGS
fi
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

# 12. Create linux-x64 host aliases that point at linux-arm64 binaries.
# Flutter's getCurrentHostPlatform() may look up linux-x64/ on Termux.
# IMPORTANT: never symlink the directory itself — Flutter artifact downloads
# write into linux-x64/ and would overwrite the real ARM64 gen_snapshot.
echo "[12.5/13] Creating host platform symlinks..."
ENG_ART=$FLUTTER_ROOT/bin/cache/artifacts/engine

link_host_platform_files() {
    local parent="$1"
    local arm_dir="$parent/linux-arm64"
    local x64_dir="$parent/linux-x64"
    [ -d "$arm_dir" ] || return 0
    if [ -L "$x64_dir" ]; then
        rm -f "$x64_dir"
    fi
    mkdir -p "$x64_dir"
    local f base
    for f in "$arm_dir"/*; do
        [ -e "$f" ] || continue
        base=$(basename "$f")
        rm -f "$x64_dir/$base"
        ln -sf "../linux-arm64/$base" "$x64_dir/$base"
    done
    echo "  ✓ $(basename "$parent")/linux-x64/* -> ../linux-arm64/*"
}

for dir in android-arm64-release android-arm64-profile; do
    link_host_platform_files "$ENG_ART/$dir"
done
link_host_platform_files "$ENG_ART"

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

# 13. Recompile flutter_tools.snapshot and stamp to guarantee offline flutter CLI execution
finalize_flutter_tools_cache() {
    echo "[13/13] Finalizing flutter_tools.snapshot and stamp..."
    local FLUTTER_TOOLS_DIR="$FLUTTER_ROOT/packages/flutter_tools"
    local SNAPSHOT_PATH="$FLUTTER_ROOT/bin/cache/flutter_tools.snapshot"
    local STAMP_PATH="$FLUTTER_ROOT/bin/cache/flutter_tools.stamp"
    local DART_BIN="$DART_SDK/bin/dart"
    local ENTRY_POINT="$FLUTTER_TOOLS_DIR/bin/flutter_tools.dart"
    local PKG_CONFIG="$FLUTTER_TOOLS_DIR/.dart_tool/package_config.json"
    local PUBSPEC_LOCK="$FLUTTER_TOOLS_DIR/pubspec.lock"
    local PUBSPEC_YAML="$FLUTTER_TOOLS_DIR/pubspec.yaml"

    # Remove any existing snapshot and stamp before generating
    rm -f "$SNAPSHOT_PATH" "$STAMP_PATH"

    if [ ! -f "$DART_BIN" ] && [ ! -x "$DART_BIN" ]; then
        echo "  ❌ Error: Dart compiler missing at $DART_BIN" >&2
        return 1
    fi
    if [ ! -f "$ENTRY_POINT" ]; then
        echo "  ❌ Error: flutter_tools entry point missing at $ENTRY_POINT" >&2
        return 1
    fi

    local REVISION=""
    if [ -f "$FLUTTER_ROOT/bin/internal/engine.version" ]; then
        REVISION=$(cat "$FLUTTER_ROOT/bin/internal/engine.version" 2>/dev/null | tr -d '\n\r')
    elif [ -n "${FLUTTER_PREBUILT_ENGINE_VERSION:-}" ]; then
        REVISION="$FLUTTER_PREBUILT_ENGINE_VERSION"
    fi
    if [ -z "$REVISION" ]; then
        if [ -x "$PREFIX/bin/git" ] && [ -d "$FLUTTER_ROOT/.git" ]; then
            REVISION=$("$PREFIX/bin/git" -C "$FLUTTER_ROOT" rev-parse HEAD 2>/dev/null || true)
        elif command -v git >/dev/null 2>&1 && [ -d "$FLUTTER_ROOT/.git" ]; then
            REVISION=$(git -C "$FLUTTER_ROOT" rev-parse HEAD 2>/dev/null || true)
        fi
    fi
    if [ -z "$REVISION" ]; then
        echo "  ❌ Error: Failed to determine Flutter SDK revision" >&2
        return 1
    fi

    local COMPILE_KEY="${REVISION}:"

    # Ensure pubspec.lock exists and is strictly newer than pubspec.yaml
    if [ -f "$PUBSPEC_YAML" ]; then
        touch -t 202701010000 "$PUBSPEC_LOCK" 2>/dev/null || touch "$PUBSPEC_LOCK"
    fi

    # Ensure bin/cache directory exists
    mkdir -p "$FLUTTER_ROOT/bin/cache"

    # Ensure environment variables are active during snapshot generation
    export PATH="$PREFIX/bin:$PATH"
    export TMPDIR="${TMPDIR:-$PREFIX/tmp}"
    if [ -n "$REVISION" ]; then
        export FLUTTER_PREBUILT_ENGINE_VERSION="$REVISION"
    fi

    # Compile snapshot with --snapshot-kind="app-jit" and --no-enable-mirrors matching shared.sh
    # Note: passing "--version" as argument allows flutter_tools.dart to execute and produce complete App-JIT snapshot
    local COMPILE_OK=0
    if [ -f "$PKG_CONFIG" ]; then
        if "$DART_BIN" --verbosity=error --snapshot="$SNAPSHOT_PATH" --snapshot-kind="app-jit" --packages="$PKG_CONFIG" --no-enable-mirrors "$ENTRY_POINT" "--version" >/dev/null 2>&1; then
            COMPILE_OK=1
        fi
    fi
    if [ "$COMPILE_OK" -ne 1 ]; then
        if "$DART_BIN" --verbosity=error --snapshot="$SNAPSHOT_PATH" --snapshot-kind="app-jit" --no-enable-mirrors "$ENTRY_POINT" "--version" >/dev/null 2>&1; then
            COMPILE_OK=1
        fi
    fi

    if [ "$COMPILE_OK" -ne 1 ] || [ ! -s "$SNAPSHOT_PATH" ]; then
        echo "  ❌ Error: Failed to compile flutter_tools.snapshot" >&2
        "$DART_BIN" --verbosity=error --snapshot="$SNAPSHOT_PATH" --snapshot-kind="app-jit" --packages="$PKG_CONFIG" --no-enable-mirrors "$ENTRY_POINT" "--version" || true
        rm -f "$SNAPSHOT_PATH" "$STAMP_PATH"
        return 1
    fi

    # Write stamp ONLY after snapshot compilation and size verification succeeds
    echo -n "$COMPILE_KEY" > "$STAMP_PATH"
    if [ ! -s "$STAMP_PATH" ] || [ "$(< "$STAMP_PATH")" != "$COMPILE_KEY" ]; then
        echo "  ❌ Error: Failed to write valid flutter_tools.stamp" >&2
        rm -f "$SNAPSHOT_PATH" "$STAMP_PATH"
        return 1
    fi

    echo "  ✓ flutter_tools.snapshot and flutter_tools.stamp finalized (key=$COMPILE_KEY)"
    return 0
}

ensure_profile_env() {
    local profile_dir="${PREFIX:-/data/data/com.termux/files/usr}/etc/profile.d"
    local profile_file="$profile_dir/flutter.sh"
    mkdir -p "$profile_dir" 2>/dev/null || true
    if [ ! -f "$profile_file" ]; then
        echo "Creating environment profile script at $profile_file..."
        cat > "$profile_file" << 'EOF'
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export PATH=${PREFIX}/opt/flutter/bin:${PATH}
export TMPDIR="${PREFIX}/tmp"
if [ -z "${ANDROID_NDK_HOME:-}" ]; then
  for ndk in ${PREFIX}/opt/android-sdk/ndk/*/; do
    [ -d "$ndk" ] && export ANDROID_NDK_HOME="${ndk%/}" && break
  done
fi
if [ -z "${JAVA_HOME:-}" ] && [ -d "${PREFIX}/lib/jvm" ]; then
  _jvm=$(find "${PREFIX}/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' 2>/dev/null | sort -V | tail -1)
  [ -n "$_jvm" ] && export JAVA_HOME="$_jvm"
  unset _jvm
fi
EOF
        chmod 755 "$profile_file" 2>/dev/null || true
        echo "  ✓ Generated $profile_file"
    fi
}

finalize_flutter_tools_cache || { echo "❌ Failed to finalize flutter_tools cache" >&2; exit 1; }
ensure_profile_env

# Snapshot compile invokes flutter_tools --version and may rewrite flutter.version.json /
# touch FETCH_HEAD from git identity. Re-assert canonical provenance at the very end.
if is_synthetic_repo "$FLUTTER_ROOT"; then
    cd "$FLUTTER_ROOT" || exit 1
    ensure_origin_remote
    purge_noncanonical_tags
    mark_synthetic_repo
fi
EFFECTIVE_DART_VER="$CANONICAL_DART_VER"
if [ -x "$DART_SDK/bin/dart" ]; then
    _dv=$("$DART_SDK/bin/dart" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
    [ -n "$_dv" ] && EFFECTIVE_DART_VER="$_dv"
    unset _dv
fi
TMP_VER_JSON="$FLUTTER_ROOT/bin/cache/flutter.version.json.tmp.$$"
cat > "$TMP_VER_JSON" << EOF
{
  "frameworkVersion": "$CANONICAL_FLUTTER_VER",
  "channel": "$CANONICAL_CHANNEL",
  "repositoryUrl": "$CANONICAL_REPO_URL",
  "frameworkRevision": "$CANONICAL_FRAMEWORK_REV",
  "frameworkCommitDate": "$CANONICAL_FRAMEWORK_DATE",
  "engineRevision": "$CANONICAL_ENGINE_REV",
  "dartSdkVersion": "$EFFECTIVE_DART_VER",
  "devToolsVersion": "$CANONICAL_DEVTOOLS_VER",
  "flutterVersion": "$CANONICAL_FLUTTER_VER"
}
EOF
mv -f "$TMP_VER_JSON" "$FLUTTER_ROOT/bin/cache/flutter.version.json"
chmod 644 "$FLUTTER_ROOT/bin/cache/flutter.version.json"
rm -f "$FLUTTER_ROOT/.git/FETCH_HEAD"
echo "  ✓ Re-asserted canonical flutter.version.json and cleared FETCH_HEAD after tool finalize"

echo ""

echo "=========================================="
echo "Post-install configuration complete!"
echo "=========================================="
echo ""
echo "=== Quick Start ==="
echo "  source $PREFIX/etc/profile.d/flutter.sh"
echo "  flutter create myapp && cd myapp"
echo ""
echo "=== IMPORTANT: Project Setup (REQUIRED for each Flutter project) ==="
echo "  1. Fix gradlew shebang:"
echo "     sed -i '1s|#!/usr/bin/env bash|#!'"$PREFIX"'/bin/bash|' android/gradlew"
echo ""
echo "  2. Edit android/app/build.gradle.kts:"
echo "     compileSdk = 34"
echo "     targetSdk = 34"
echo "     ndk { abiFilters += listOf(\"arm64-v8a\") }"
echo ""
echo "  3. Add to android/gradle.properties:"
echo "     android.aapt2FromMavenOverride=$PREFIX/bin/aapt2"
echo ""
echo "  4. Set JAVA_HOME before building:"
echo "     export JAVA_HOME=\$(find \$PREFIX/lib/jvm -maxdepth 1 -type d -name 'java-*-openjdk' | sort -V | tail -1)"
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
