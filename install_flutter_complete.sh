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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo ".")"
if [ -f "$SCRIPT_DIR/scripts/install/lib_common.sh" ]; then
    source "$SCRIPT_DIR/scripts/install/lib_common.sh"
elif [ -f "scripts/install/lib_common.sh" ]; then
    source "scripts/install/lib_common.sh"
else
    echo "Fetching lib_common.sh..."
    mkdir -p scripts/install
    curl -sLO https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/lib_common.sh || true
    if [ -f lib_common.sh ]; then
        mv lib_common.sh scripts/install/
    fi
    if [ -f scripts/install/lib_common.sh ]; then
        source scripts/install/lib_common.sh
    fi
fi

if command -v parse_installer_args >/dev/null 2>&1; then
    parse_installer_args "$@"
fi

backup_ndk_file() {
    local file="$1"
    local backup_dir="${BACKUP_DIR:-${WORK_DIR:-.}/backup}"
    local absent_list="$backup_dir/ndk_absent.list"
    local backup_target=""

    local rel_path=""
    if [ -n "${ANDROID_HOME:-}" ] && [[ "$file" == "$ANDROID_HOME/"* ]]; then
        rel_path="${file#$ANDROID_HOME/}"
    elif [ -n "${NDK_PATH:-}" ] && [[ "$file" == "$NDK_PATH/"* ]]; then
        rel_path="ndk/$(basename "$NDK_PATH")/${file#$NDK_PATH/}"
    else
        rel_path="$(basename "$file")"
    fi

    # If already recorded as absent in this session, do not back it up as existing
    if [ -f "$absent_list" ] && grep -Fxq "$file" "$absent_list" 2>/dev/null; then
        return 0
    fi

    if [ -e "$file" ] || [ -L "$file" ]; then
        if [ -z "$rel_path" ]; then
            return 0
        fi

        backup_target="$backup_dir/ndk_backups/$rel_path"
        if [ ! -e "$backup_target" ] && [ ! -L "$backup_target" ]; then
            local target_dir="$(dirname "$backup_target")"
            if [ -n "$target_dir" ] && [ "$target_dir" != "." ]; then
                mkdir -p "$target_dir"
            fi
            cp -a "$file" "$backup_target" 2>/dev/null || true
        fi
    else
        # File does not pre-exist -> record as absent for clean rollback removal
        local absent_dir="$(dirname "$absent_list")"
        if [ -n "$absent_dir" ] && [ "$absent_dir" != "." ]; then
            mkdir -p "$absent_dir"
        fi
        if ! grep -Fxq "$file" "$absent_list" 2>/dev/null; then
            echo "$file" >> "$absent_list"
        fi
        if command -v record_absent_preimage >/dev/null 2>&1; then
            record_absent_preimage "$file"
        fi
    fi
}

restore_ndk_backups() {
    local backup_dir="${BACKUP_DIR:-${WORK_DIR:-.}/backup}"

    # 1. Unconditionally remove newly created files recorded as absent
    local absent_list="$backup_dir/ndk_absent.list"
    if [ -f "$absent_list" ]; then
        echo -e "${YELLOW}[ROLLBACK] Removing newly created NDK artifacts...${NC}"
        while IFS= read -r absent_file || [ -n "$absent_file" ]; do
            if [ -n "$absent_file" ] && [ -e "$absent_file" -o -L "$absent_file" ]; then
                rm -f "$absent_file" 2>/dev/null || rm -rf "$absent_file" 2>/dev/null || true
                echo "  ✓ Removed created NDK artifact: $absent_file"
                local parent_dir="$(dirname "$absent_file")"
                while [ -n "$parent_dir" ] && [ "$parent_dir" != "/" ] && [ "$parent_dir" != "." ] && [ "$parent_dir" != "${ANDROID_HOME:-}" ] && [ "$parent_dir" != "${PREFIX:-}" ] && [ "$parent_dir" != "${WORK_DIR:-}" ] && [ -d "$parent_dir" ]; do
                    if [ -z "$(ls -A "$parent_dir" 2>/dev/null)" ]; then
                        rmdir "$parent_dir" 2>/dev/null || break
                        parent_dir="$(dirname "$parent_dir")"
                    else
                        break
                    fi
                done
            fi
        done < "$absent_list"
        rm -f "$absent_list" 2>/dev/null || true
    fi

    # Also clean up any general absent preimages from lib_common if present
    if command -v cleanup_absent_preimages >/dev/null 2>&1; then
        cleanup_absent_preimages
    fi

    # 2. Restore all pre-existing NDK files from backup
    if [ -d "$backup_dir/ndk_backups" ]; then
        echo -e "${YELLOW}[ROLLBACK] Restoring pre-existing NDK files from backup...${NC}"
        (
            cd "$backup_dir/ndk_backups"
            find . \( -type f -o -type l \) | while read -r rel; do
                rel="${rel#./}"
                if [ -z "$rel" ] || [ "$rel" = "." ]; then
                    continue
                fi
                local dest=""
                if [[ "$rel" == ndk/* ]]; then
                    dest="${ANDROID_HOME:-$PREFIX/opt/android-sdk}/$rel"
                else
                    dest="${NDK_PATH:-$ANDROID_HOME/ndk/$NDK_VERSION}/$rel"
                fi
                if [ -n "$dest" ]; then
                    local dest_dir="$(dirname "$dest")"
                    if [ -n "$dest_dir" ] && [ "$dest_dir" != "." ]; then
                        mkdir -p "$dest_dir"
                    fi
                    rm -f "$dest" 2>/dev/null || true
                    cp -a "$rel" "$dest" 2>/dev/null || true
                    echo "  ✓ Restored $dest"
                fi
            done
        )
    fi
}

configure_ndk_clang() {
    local NDK_DIR="$1"
    local PREBUILT="$NDK_DIR/toolchains/llvm/prebuilt"

    # 跳過空的 NDK stub（android-sdk 包帶的空目錄）
    if [ ! -d "$PREBUILT/linux-x86_64/bin" ]; then
        echo "  跳過 NDK stub: $(basename "$NDK_DIR")"
        return
    fi

    echo "  配置 NDK: $(basename "$NDK_DIR")"

    # 創建 sysroot symlink
    backup_ndk_file "$PREBUILT/sysroot"
    ln -sf linux-x86_64/sysroot "$PREBUILT/sysroot" 2>/dev/null || true

    # 創建 bin 目錄 symlinks
    mkdir -p "$PREBUILT/bin"
    backup_ndk_file "$PREBUILT/bin/clang"
    backup_ndk_file "$PREBUILT/bin/clang++"
    ln -sf "$PREBUILT/linux-x86_64/bin/clang" "$PREBUILT/bin/clang" 2>/dev/null || true
    ln -sf "$PREBUILT/linux-x86_64/bin/clang++" "$PREBUILT/bin/clang++" 2>/dev/null || true

    # 確保 clang++ 指向 clang-18（可能被之前的腳本修改過）
    backup_ndk_file "$PREBUILT/linux-x86_64/bin/clang++"
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
            backup_ndk_file "$api_dir/libc++_shared.so"
            rm -f "$api_dir/libc++_shared.so" 2>/dev/null || true
            ln -sf ../libc++_shared.so "$api_dir/libc++_shared.so" 2>/dev/null || true

            # libatomic.a - 創建空的 stub（Android 不需要 libatomic）
            if [ ! -f "$api_dir/libatomic.a" ]; then
                backup_ndk_file "$api_dir/libatomic.a"
                ar rcs "$api_dir/libatomic.a" 2>/dev/null || true
            fi
        fi
    done

    # Patch android-legacy.toolchain.cmake（移除 -static-libstdc++ 避免連結錯誤）
    local TOOLCHAIN="$NDK_DIR/build/cmake/android-legacy.toolchain.cmake"
    if [ -f "$TOOLCHAIN" ]; then
        backup_ndk_file "$TOOLCHAIN"
        if grep -q 'list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")' "$TOOLCHAIN" 2>/dev/null; then
            sed -i 's/list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/# Disabled for Termux: list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/' "$TOOLCHAIN"
            echo "    ✓ Patched android-legacy.toolchain.cmake"
        fi
    fi
}

ROLLBACK_FAILED=false
rollback_packages() {
    echo -e "${RED}[ROLLBACK] Install failed — executing truthful environment rollback...${NC}"
    record_stage rollback triggered

    local flutter_was_installed="${FLUTTER_WAS_INSTALLED:-false}"
    local flutter_old_ver="${FLUTTER_OLD_VER:-}"
    local android_sdk_was_installed="${ANDROID_SDK_WAS_INSTALLED:-false}"
    local android_sdk_old_ver="${ANDROID_SDK_OLD_VER:-}"
    local backup_dir="${BACKUP_DIR:-.}"
    local ndk_preexisting="${NDK_PREEXISTING:-true}"
    local ndk_path="${NDK_PATH:-}"

    # 1. Rollback Flutter
    if [ "$flutter_was_installed" = true ]; then
        echo -e "${YELLOW}[ROLLBACK] Restoring previous Flutter version ($flutter_old_ver)...${NC}"
        local flutter_bak=$(ls "$backup_dir"/flutter*.deb 2>/dev/null | head -n 1 || true)
        if [ -n "$flutter_bak" ] && [ -f "$flutter_bak" ]; then
            if dpkg -i "$flutter_bak"; then
                local restored_ver=$(dpkg-query -W -f='${Version}' flutter 2>/dev/null | tr -d '\r' || true)
                if [ "$restored_ver" = "$flutter_old_ver" ]; then
                    echo -e "${GREEN}[ROLLBACK] Flutter successfully restored to $flutter_old_ver.${NC}"
                else
                    echo -e "${RED}[ROLLBACK ERROR] Flutter restored version mismatch ($restored_ver != $flutter_old_ver).${NC}"
                    ROLLBACK_FAILED=true
                fi
            else
                echo -e "${RED}[ROLLBACK ERROR] Failed to reinstall previous Flutter package from $flutter_bak.${NC}"
                ROLLBACK_FAILED=true
            fi
        else
            echo -e "${RED}[ROLLBACK ERROR] Restorable Flutter package artifact not found in backup.${NC}"
            ROLLBACK_FAILED=true
        fi
    else
        if dpkg-query -W -f='${Status}' flutter 2>/dev/null | grep -q 'ok installed'; then
            echo -e "${YELLOW}[ROLLBACK] Removing newly installed Flutter package...${NC}"
            if ! dpkg -r flutter >/dev/null 2>&1; then
                echo -e "${RED}[ROLLBACK ERROR] Failed to remove newly installed Flutter package.${NC}"
                ROLLBACK_FAILED=true
            fi
            if dpkg-query -W -f='${Status}' flutter 2>/dev/null | grep -q 'ok installed'; then
                echo -e "${RED}[ROLLBACK ERROR] Flutter package is still installed after removal.${NC}"
                ROLLBACK_FAILED=true
            fi
        fi
    fi

    # 2. Rollback Android SDK
    if [ "$android_sdk_was_installed" = true ]; then
        echo -e "${YELLOW}[ROLLBACK] Restoring previous Android SDK version ($android_sdk_old_ver)...${NC}"
        local sdk_bak=$(ls "$backup_dir"/android-sdk*.deb 2>/dev/null | head -n 1 || true)
        if [ -n "$sdk_bak" ] && [ -f "$sdk_bak" ]; then
            if dpkg -i "$sdk_bak" >/dev/null 2>&1; then
                local restored_ver=$(dpkg-query -W -f='${Version}' android-sdk 2>/dev/null | tr -d '\r' || true)
                if [ "$restored_ver" = "$android_sdk_old_ver" ]; then
                    echo -e "${GREEN}[ROLLBACK] Android SDK successfully restored to $android_sdk_old_ver.${NC}"
                else
                    echo -e "${RED}[ROLLBACK ERROR] Android SDK restored version mismatch ($restored_ver != $android_sdk_old_ver).${NC}"
                    ROLLBACK_FAILED=true
                fi
            else
                echo -e "${RED}[ROLLBACK ERROR] Failed to reinstall previous Android SDK package from $sdk_bak.${NC}"
                ROLLBACK_FAILED=true
            fi
        else
            echo -e "${RED}[ROLLBACK ERROR] Restorable Android SDK package artifact not found in backup.${NC}"
            ROLLBACK_FAILED=true
        fi
    else
        if dpkg-query -W -f='${Status}' android-sdk 2>/dev/null | grep -q 'ok installed'; then
            echo -e "${YELLOW}[ROLLBACK] Removing newly installed Android SDK package...${NC}"
            if ! dpkg -r android-sdk >/dev/null 2>&1; then
                echo -e "${RED}[ROLLBACK ERROR] Failed to remove newly installed Android SDK package.${NC}"
                ROLLBACK_FAILED=true
            fi
            if dpkg-query -W -f='${Status}' android-sdk 2>/dev/null | grep -q 'ok installed'; then
                echo -e "${RED}[ROLLBACK ERROR] Android SDK package is still installed after removal.${NC}"
                ROLLBACK_FAILED=true
            fi
        fi
    fi

    # 3. Rollback NDK
    if [ "$ndk_preexisting" = false ]; then
        if [ -n "$ndk_path" ] && [ -d "$ndk_path" ]; then
            echo -e "${YELLOW}[ROLLBACK] Removing newly extracted NDK directory ($ndk_path)...${NC}"
            rm -rf "$ndk_path"
        fi
    fi
    restore_ndk_backups

    if [ "$ROLLBACK_FAILED" = true ]; then
        echo -e "${RED}[ROLLBACK FAILED] Environment restoration could not be fully completed.${NC}"
        record_stage rollback failed
        return 1
    else
        echo -e "${GREEN}[ROLLBACK SUCCESS] Environment successfully restored to original state.${NC}"
        record_stage rollback success
        return 0
    fi
}

MUTATION_STARTED=false
MUTATION_COMMITTED=false

cleanup_and_exit() {
    local orig_code=$?
    trap - EXIT INT TERM HUP
    local exit_code=$orig_code
    local should_rollback=false

    if [ "${MUTATION_COMMITTED:-false}" != true ]; then
        if [ "${MUTATION_STARTED:-false}" = true ] || [ "${INSTALL_FAILED:-false}" = true ]; then
            should_rollback=true
        fi
    elif [ "$orig_code" -ne 0 ] || [ "${INSTALL_FAILED:-false}" = true ]; then
        should_rollback=true
    fi

    if [ "$should_rollback" = true ]; then
        echo -e "${RED}[EXIT HANDLER] Installation failed or interrupted ($orig_code). Triggering package rollback...${NC}"
        if ! rollback_packages; then
            echo -e "${RED}[ERROR] Rollback failed! System may be in an inconsistent state.${NC}"
            exit_code=70
        else
            if [ "$orig_code" -eq 0 ]; then
                exit_code=1
            else
                exit_code=$orig_code
            fi
        fi
    fi

    if [ -n "${WORK_DIR:-}" ] && [ -d "${WORK_DIR:-}" ]; then
        rm -rf "$WORK_DIR"
    fi
    print_summary
    exit $exit_code
}
trap cleanup_and_exit EXIT INT TERM HUP

if [ "${TERMUX_TEST_MODE:-false}" = "true" ]; then
    return 0 2>/dev/null || exit 0
fi

# 版本配置
FLUTTER_VERSION="3.44.2"
EXPECTED_SHA256="f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e"

# 其他版本配置
ANDROID_SDK_EXPECTED_SHA256="fc727c848b8ca4e3011515850702adc1bf98ceae7205d7acc82d026bc94d2601"
NDK_EXPECTED_SHA256="02e10e4ddfe8deaeb0bd0cf29d04c981ed5bc8a5d6b560ebb9e7661f472d684b"
SNAPSHOT_EXPECTED_SHA256="527f074d86660fd3f7c900fc8c1ebd5a2ebc4581e174eb8cf9fe343a1664402d"
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

preflight_check 2000000
echo "  ✓ 架構: ARM64"
echo "  ✓ 環境: Termux"
echo "  ✓ 空間: 充足"

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

# Allocate WORK_DIR early for all staging and downloads (#55)
WORK_DIR=$(mktemp -d "${TMPDIR:-$PREFIX/tmp}/flutter_install.XXXXXX" 2>/dev/null || mktemp -d 2>/dev/null || mktemp -d -t flutter_install.XXXXXX)
INSTALL_FAILED=false

# ========================================
# Step 1: 更新系統
# ========================================
echo ""
echo -e "${GREEN}[1/${TOTAL_STEPS}]${NC} 更新系統套件..."

# 清理可能存在的舊包（避免依賴衝突）

pkg update -y
if [ "${DO_UPGRADE:-false}" = true ]; then pkg upgrade -y; fi

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
mkdir -p "$WORK_DIR/apt_staging"
(
    cd "$WORK_DIR/apt_staging"
    for pkg in d8 dx aidl apksigner googletest android-tools; do
        apt download "$pkg" 2>/dev/null || true
        if ls ${pkg}*.deb 1>/dev/null 2>&1; then
            if ! dpkg -i ${pkg}*.deb 2>/dev/null; then
                dpkg --force-depends --configure "${pkg}" 2>/dev/null || true
            fi
            rm -f ${pkg}*.deb
        fi
    done
)

# 預先下載並驗證所有套件（Staging Phase）
echo "預先下載並驗證所有套件..."
FLUTTER_DEB_URL="https://github.com/ImL1s/termux-flutter-wsl/releases/download/${RELEASE_TAG}/flutter_${FLUTTER_VERSION}_aarch64.deb"
ANDROID_SDK_DEB_URL="https://github.com/mumumusuc/termux-android-sdk/releases/download/35.0.0/android-sdk_35.0.0_aarch64.deb"
NDK_ARCHIVE_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-ndk/android-ndk-r29-aarch64.tar.xz"

# Snapshot existing package state for rollback
FLUTTER_WAS_INSTALLED=false
ANDROID_SDK_WAS_INSTALLED=false
FLUTTER_OLD_VER=""
ANDROID_SDK_OLD_VER=""

if dpkg-query -W -f='${Status} ${Version}' flutter 2>/dev/null | grep -q 'ok installed'; then
    FLUTTER_WAS_INSTALLED=true
    FLUTTER_OLD_VER=$(dpkg-query -W -f='${Version}' flutter 2>/dev/null || true)
fi
if dpkg-query -W -f='${Status} ${Version}' android-sdk 2>/dev/null | grep -q 'ok installed'; then
    ANDROID_SDK_WAS_INSTALLED=true
    ANDROID_SDK_OLD_VER=$(dpkg-query -W -f='${Version}' android-sdk 2>/dev/null || true)
fi

ANDROID_HOME="$PREFIX/opt/android-sdk"
NDK_PATH="$ANDROID_HOME/ndk/$NDK_VERSION"
NDK_PREEXISTING=false
if [ -d "$NDK_PATH" ]; then
    NDK_PREEXISTING=true
fi

BACKUP_DIR="$WORK_DIR/backup"
mkdir -p "$BACKUP_DIR"

if [ "$FLUTTER_WAS_INSTALLED" = true ] || [ "$ANDROID_SDK_WAS_INSTALLED" = true ]; then
    if ! command -v dpkg-repack >/dev/null 2>&1; then
        echo -e "${YELLOW}[SETUP] Installing dpkg-repack prerequisite for rollback backup...${NC}"
        pkg install -y dpkg-repack 2>/dev/null || apt-get install -y dpkg-repack 2>/dev/null || true
    fi
fi

if [ "$FLUTTER_WAS_INSTALLED" = true ]; then
    if command -v dpkg-repack >/dev/null 2>&1; then
        (cd "$BACKUP_DIR" && dpkg-repack flutter 2>/dev/null) || true
    fi
    if ! ls "$BACKUP_DIR"/flutter*.deb 1>/dev/null 2>&1; then
        # Fallback to apt-get download if dpkg-repack did not produce .deb
        (cd "$BACKUP_DIR" && apt-get download "flutter=$FLUTTER_OLD_VER" 2>/dev/null) || true
    fi
    if ! ls "$BACKUP_DIR"/flutter*.deb 1>/dev/null 2>&1; then
        if [ "${ALLOW_NO_ROLLBACK:-false}" != "true" ]; then
            echo -e "${RED}[ERROR] Cannot backup existing Flutter package for rollback restoration.${NC}"
            INSTALL_FAILED=false
            exit 35
        fi
    fi
fi
if [ "$ANDROID_SDK_WAS_INSTALLED" = true ]; then
    if command -v dpkg-repack >/dev/null 2>&1; then
        (cd "$BACKUP_DIR" && dpkg-repack android-sdk 2>/dev/null) || true
    fi
    if ! ls "$BACKUP_DIR"/android-sdk*.deb 1>/dev/null 2>&1; then
        # Fallback to apt-get download if dpkg-repack did not produce .deb
        (cd "$BACKUP_DIR" && apt-get download "android-sdk=$ANDROID_SDK_OLD_VER" 2>/dev/null) || true
    fi
    if ! ls "$BACKUP_DIR"/android-sdk*.deb 1>/dev/null 2>&1; then
        if [ "${ALLOW_NO_ROLLBACK:-false}" != "true" ]; then
            echo -e "${RED}[ERROR] Cannot backup existing Android SDK package for rollback restoration.${NC}"
            INSTALL_FAILED=false
            exit 35
        fi
    fi
fi


FLUTTER_DEB="$WORK_DIR/flutter_${FLUTTER_VERSION}_aarch64.deb"
ANDROID_SDK_DEB="$WORK_DIR/android-sdk_35.0.0_aarch64.deb"
NDK_ARCHIVE="$WORK_DIR/android-ndk-r29-aarch64.tar.xz"

echo "下載 Flutter SDK..."
wget -q --show-progress "$FLUTTER_DEB_URL" -O "$FLUTTER_DEB" || { INSTALL_FAILED=true; record_stage download failed; exit 20; }
record_stage download success

echo "驗證 Flutter SDK SHA256 校驗碼..."
verify_sha256 "$FLUTTER_DEB" "$EXPECTED_SHA256" || { INSTALL_FAILED=true; record_stage integrity failed; exit 30; }
record_stage integrity success

echo "下載 Android SDK..."
wget -q --show-progress "$ANDROID_SDK_DEB_URL" -O "$ANDROID_SDK_DEB" || { INSTALL_FAILED=true; record_stage download failed; exit 20; }
echo "驗證 Android SDK SHA256 校驗碼..."
verify_sha256 "$ANDROID_SDK_DEB" "$ANDROID_SDK_EXPECTED_SHA256" || { INSTALL_FAILED=true; record_stage integrity failed; exit 30; }

ANDROID_HOME="$PREFIX/opt/android-sdk"
NDK_PATH="$ANDROID_HOME/ndk/$NDK_VERSION"
if [ ! -d "$NDK_PATH" ]; then
    echo "下載 ARM64 NDK..."
    wget -q --show-progress "$NDK_ARCHIVE_URL" -O "$NDK_ARCHIVE" || { INSTALL_FAILED=true; record_stage download failed; exit 20; }
    echo "驗證 NDK SHA256 校驗碼..."
    verify_sha256 "$NDK_ARCHIVE" "$NDK_EXPECTED_SHA256" || { INSTALL_FAILED=true; record_stage integrity failed; exit 30; }
fi

# 預先驗證 deb 結構完整性 (hard failure)
echo "驗證 Android SDK deb 結構完整性..."
dpkg-deb --info "$ANDROID_SDK_DEB" >/dev/null 2>&1 || { INSTALL_FAILED=true; record_stage integrity failed; echo "Android SDK deb is corrupt"; exit 30; }

# 所有下載與驗證均已成功完成，開始安裝
echo "所有下載與驗證均已成功完成，開始安裝 SDK..."
MUTATION_STARTED=true

# ========================================
# Step 2: 安裝 Android SDK (install-first, never purge-first)
# ========================================
echo ""
echo -e "${GREEN}[2/${TOTAL_STEPS}]${NC} 安裝 Android SDK..."

# Transactional: install new package directly (dpkg handles upgrade)
echo "安裝 Android SDK..."
dpkg -i --force-architecture "$ANDROID_SDK_DEB" || dpkg --force-depends --configure android-sdk || { INSTALL_FAILED=true; record_stage package failed; exit 40; }
echo "  ✓ Android SDK 已安裝"

# ========================================
# Step 3: 安裝 Flutter SDK
# ========================================
echo ""
echo -e "${GREEN}[3/${TOTAL_STEPS}]${NC} 安裝 Flutter SDK..."

echo "安裝 Flutter SDK..."
apt-get install -f -y "$FLUTTER_DEB" || { INSTALL_FAILED=true; record_stage package failed; exit 40; }
record_stage package success

# 載入環境
source $PREFIX/etc/profile.d/flutter.sh 2>/dev/null || true

# 重新編譯 flutter_tools.snapshot（修復 "Unsupported operating system: android" 問題）
FLUTTER_ROOT=$PREFIX/opt/flutter
DART_SDK=$FLUTTER_ROOT/bin/cache/dart-sdk
if [ ! -x "$DART_SDK/bin/dartvm" ]; then
    echo -e "${RED}錯誤: Dart VM binary missing: $DART_SDK/bin/dartvm${NC}"
    echo "Dart 3.10+ requires dartvm next to dart. Re-download the fixed flutter_${FLUTTER_VERSION}_aarch64.deb release."
    INSTALL_FAILED=true; record_stage integrity failed; exit 30
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
    dart_zip="$WORK_DIR/dart-sdk.zip"
    wget -q --show-progress "$SNAPSHOTS_URL" -O "$dart_zip" || true
    if [ -f "$dart_zip" ]; then
        if [ "$ENGINE_VERSION" = "77e2e94772b6eb43759e34ed1ad7da4674e19cab" ]; then
            verify_sha256 "$dart_zip" "$SNAPSHOT_EXPECTED_SHA256" || { rm -f "$dart_zip"; INSTALL_FAILED=true; record_stage integrity failed; exit 30; }
        else
            echo "  ⚠ 引擎版本不匹配，跳過 Dart SDK snapshots 校驗碼驗證"
        fi
        unzip -o -j "$dart_zip" 'dart-sdk/bin/snapshots/*' -d "$SNAPSHOTS_DIR" 2>/dev/null || true
        rm -f "$dart_zip"
        echo "  ✓ Dart SDK snapshots 已安裝"
    fi
else
    echo "  ✓ Dart SDK snapshots 已存在或無需更新"
fi

# 清理 ELF 二進制文件（移除 DT_RPATH 警告，修復 flutter run JSON 解析問題）
echo "清理 ELF binaries..."
mkdir -p "$WORK_DIR/apt_staging"
(
    cd "$WORK_DIR/apt_staging"
    apt download termux-elf-cleaner 2>/dev/null || true
    if ls termux-elf-cleaner*.deb 1>/dev/null 2>&1; then
        if ! dpkg -i termux-elf-cleaner*.deb 2>/dev/null; then
            dpkg --force-depends --configure termux-elf-cleaner 2>/dev/null || true
        fi
        rm -f termux-elf-cleaner*.deb
    fi
)
if command -v termux-elf-cleaner &> /dev/null; then
    for dart_bin in dart dartvm dartaotruntime; do
        [ -f "$DART_SDK/bin/$dart_bin" ] && termux-elf-cleaner "$DART_SDK/bin/$dart_bin" 2>/dev/null || true
    done
    echo "  ✓ ELF binaries 已清理"
else
    echo "  ⚠ termux-elf-cleaner 未安裝"
fi

# ========================================
# Step 4: 安裝 ARM64 NDK
# ========================================
echo ""
echo -e "${GREEN}[4/${TOTAL_STEPS}]${NC} 安裝 ARM64 NDK..."

if [ -d "$NDK_PATH" ]; then
    echo "  ✓ NDK 已安裝"
else
    echo "解壓 NDK (Staging Isolation)..."
    NDK_STAGE="$WORK_DIR/ndk_stage"
    rm -rf "$NDK_STAGE" 2>/dev/null || true
    mkdir -p "$NDK_STAGE"

    if [[ "$NDK_ARCHIVE" == *.tar.xz ]] || [[ "$NDK_ARCHIVE" == *.txz ]]; then
        if ! tar -xf "$NDK_ARCHIVE" -C "$NDK_STAGE" >/dev/null 2>&1 && ! 7z x -y "$NDK_ARCHIVE" "-o$NDK_STAGE" >/dev/null 2>&1; then
            echo -e "${RED}[ERROR] NDK extraction (tar.xz) failed. Cleaning up stage...${NC}"
            rm -rf "$NDK_STAGE" 2>/dev/null || true
            { INSTALL_FAILED=true; record_stage package failed; exit 40; }
        fi
    elif ! 7z x -y "$NDK_ARCHIVE" "-o$NDK_STAGE" >/dev/null && ! tar -xf "$NDK_ARCHIVE" -C "$NDK_STAGE" >/dev/null 2>&1; then
        echo -e "${RED}[ERROR] NDK extraction failed. Cleaning up stage...${NC}"
        rm -rf "$NDK_STAGE" 2>/dev/null || true
        { INSTALL_FAILED=true; record_stage package failed; exit 40; }
    fi

    EXTRACTED_NDK=""
    if [ -d "$NDK_STAGE/android-ndk-r29" ]; then
        EXTRACTED_NDK="$NDK_STAGE/android-ndk-r29"
    else
        EXTRACTED_NDK=$(find "$NDK_STAGE" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    fi

    if [ -z "$EXTRACTED_NDK" ] || [ ! -d "$EXTRACTED_NDK" ]; then
        echo -e "${RED}[ERROR] Extracted NDK directory not found in stage ($NDK_STAGE).${NC}"
        rm -rf "$NDK_STAGE" 2>/dev/null || true
        { INSTALL_FAILED=true; record_stage package failed; exit 40; }
    fi

    echo "移動 NDK 到目標路徑..."
    mkdir -p "$ANDROID_HOME/ndk"
    rm -rf "$NDK_PATH"
    if ! mv "$EXTRACTED_NDK" "$NDK_PATH"; then
        echo -e "${RED}[ERROR] Failed to move NDK to $NDK_PATH.${NC}"
        rm -rf "$NDK_STAGE" 2>/dev/null || true
        { INSTALL_FAILED=true; record_stage package failed; exit 40; }
    fi
    rm -rf "$NDK_STAGE" 2>/dev/null || true

    echo "  ✓ NDK 已安裝"
fi

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
    bash $PREFIX/share/flutter/post_install.sh || { INSTALL_FAILED=true; record_stage post-install failed; exit 50; }
    record_stage post-install success
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
# removed wildcard deletion
# rm -rf $ANDROID_HOME/cmake/*/bin 2>/dev/null || true
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
if [ ! -f "$BUILD_TOOLS/core-lambda-stubs.jar" ]; then
    manifest_tmp="$WORK_DIR/MANIFEST.MF"
    echo "Manifest-Version: 1.0" > "$manifest_tmp" 2>/dev/null || true
    jar cfm "$BUILD_TOOLS/core-lambda-stubs.jar" "$manifest_tmp" 2>/dev/null || true
    rm -f "$manifest_tmp" 2>/dev/null || true
fi
echo "  ✓ build-tools 已配置"

# 配置 Flutter
flutter config --android-sdk $ANDROID_HOME 2>/dev/null || true

# 接受授權
if command -v handle_android_licenses >/dev/null 2>&1; then
    handle_android_licenses "${OPT_YES:-false}" "${OPT_NON_INTERACTIVE:-false}"
else
    yes | flutter doctor --android-licenses 2>/dev/null || true
fi

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
    (
        mkdir -p "$WORK_DIR/apt_staging"
        cd "$WORK_DIR/apt_staging"
        # 下載依賴包
        apt download libprotobuf fmt libzopfli aapt aapt2 2>/dev/null || true
        # 安裝（使用 dpkg 避免觸發 apt 的依賴解析）
        if ! dpkg -i libprotobuf*.deb fmt*.deb libzopfli*.deb aapt_*.deb aapt2*.deb 2>/dev/null; then
            dpkg --force-depends --configure aapt aapt2 libprotobuf fmt libzopfli 2>/dev/null || true
        fi
        rm -f *.deb 2>/dev/null || true
    )
fi

TEST_APP_DIR="$WORK_DIR/flutter_test_app"

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
build1_log="$WORK_DIR/build1.log"
build2_log="$WORK_DIR/build2.log"
flutter build apk --release --target-platform android-arm64 2>&1 | tee "$build1_log" || true

# Gradle 可能下載了新的 SDK 組件（如 build-tools/35.0.0-2），重新配置
echo "配置 Gradle 下載的 SDK 組件..."
if [ -f "$PREFIX/share/flutter/post_install.sh" ]; then
    bash "$PREFIX/share/flutter/post_install.sh" || { INSTALL_FAILED=true; record_stage post-install failed; exit 50; }
    record_stage post-install success
fi

# 檢查是否因 NDK clang 問題失敗（Gradle 可能下載了新 NDK）
if grep -q "CMAKE_C_COMPILER" "$build1_log" 2>/dev/null || grep -q "compiler identification is unknown" "$build1_log" 2>/dev/null; then
    echo "檢測到 NDK clang 問題，重新配置..."
    # Re-run NDK clang configuration for Gradle-downloaded NDK
    for ndk_dir in "$ANDROID_HOME"/ndk/*/; do
        if [ -d "$ndk_dir/toolchains/llvm" ]; then
            configure_ndk_clang "$ndk_dir"
        fi
    done
    echo "重新構建..."
    flutter build apk --release --target-platform android-arm64 2>&1 | tee "$build2_log" || true
fi

# 檢查 APK 結果
if [ -f "build/app/outputs/flutter-apk/app-release.apk" ]; then
    record_stage smoke success
    APK_SIZE=$(ls -lh build/app/outputs/flutter-apk/app-release.apk | awk '{print $5}')
    APK_BUILD_SUCCESS=true
    echo "  ✓ APK 構建成功 ($APK_SIZE)"
else
    APK_BUILD_SUCCESS=false
    echo "  ✗ APK 構建失敗"
    record_stage smoke failed
    INSTALL_FAILED=true; exit 60
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
MUTATION_COMMITTED=true

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
