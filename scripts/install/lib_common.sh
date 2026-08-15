#!/bin/bash
# Shared library for Termux Flutter installers

# Colors
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export NC='\033[0m'

# Version info
export FLUTTER_VERSION="3.44.2"
export RELEASE_TAG="v3.44.2-termux"
export EXPECTED_SHA256="${EXPECTED_SHA256:-${FLUTTER_DEB_SHA256:-f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e}}"

declare -A STAGE_STATUS

record_stage() {
    STAGE_STATUS[$1]=$2
}

print_summary() {
    echo "{"
    local first=1
    for stage in "${!STAGE_STATUS[@]}"; do
        if [ $first -eq 0 ]; then echo ","; fi
        echo -n "  \"$stage\": \"${STAGE_STATUS[$stage]}\""
        first=0
    done
    echo ""
    echo "}"
}

verify_sha256() {
    local file=$1
    local expected=$2
    local hasher=""

    if [ ! -f "$file" ]; then
        echo -e "${RED}Error: File not found: $file${NC}"
        return 1
    fi

    if command -v sha256sum &> /dev/null; then
        hasher="sha256sum"
    elif command -v shasum &> /dev/null; then
        hasher="shasum -a 256"
    fi

    if [ -z "$hasher" ]; then
        echo -e "${RED}Error: Neither sha256sum nor shasum is available. Cannot verify checksum.${NC}"
        rm -f "$file" 2>/dev/null || true
        return 1
    fi

    if [ -z "$expected" ]; then
        echo -e "${RED}Error: Expected SHA256 checksum is empty or missing.${NC}"
        rm -f "$file" 2>/dev/null || true
        return 1
    fi

    local actual=$($hasher "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        echo -e "${RED}"
        echo "==========================================================="
        echo " ERROR: SHA256 checksum mismatch!"
        echo " File: $(basename "$file")"
        echo " Expected: $expected"
        echo " Actual  : $actual"
        echo "==========================================================="
        echo -e "${NC}"
        rm -f "$file" 2>/dev/null || true
        return 1
    fi
    echo "  ✓ SHA256 verified ($actual)"
    return 0
}

preflight_check() {
    local required_space_kb=$1

    if [ "${TERMUX_TEST_MODE:-false}" = "true" ]; then
        record_stage preflight success
        return 0
    fi

    # Check architecture
    local arch=$(uname -m)
    if [ "$arch" != "aarch64" ]; then
        echo -e "${RED}Error: This script only supports ARM64 (aarch64) devices.${NC}"
        echo "Your architecture: $arch"
        record_stage preflight failed
        exit 10
    fi

    # Check if running in Termux
    if [ ! -d "/data/data/com.termux" ] && [ "${TERMUX_TEST_MODE:-false}" != "true" ]; then
        echo -e "${RED}Error: This script must be run in Termux.${NC}"
        record_stage preflight failed
        exit 10
    fi

    # Check disk space
    if [ "${TERMUX_TEST_MODE:-false}" != "true" ]; then
        local free_space=$(df -k /data 2>/dev/null | awk 'NR==2 {print $4}' || echo "99999999")
        if [ "${free_space:-0}" -lt "$required_space_kb" ]; then
            echo -e "${RED}Error: Not enough disk space. Need at least $((required_space_kb/1000))MB.${NC}"
            record_stage preflight failed
            exit 10
        fi
    fi

    record_stage preflight success
}

# Preimage & Absent Tracking Utilities
record_absent_preimage() {
    local target="$1"
    local absent_manifest="${ABSENT_MANIFEST:-${WORK_DIR:-.}/absent_preimages.txt}"
    local target_dir="$(dirname "$absent_manifest")"
    if [ -n "$target_dir" ] && [ "$target_dir" != "." ]; then
        mkdir -p "$target_dir"
    fi
    if ! grep -Fxq "$target" "$absent_manifest" 2>/dev/null; then
        echo "$target" >> "$absent_manifest"
    fi
}

cleanup_absent_preimages() {
    local absent_manifest="${ABSENT_MANIFEST:-${WORK_DIR:-.}/absent_preimages.txt}"
    if [ -f "$absent_manifest" ]; then
        echo -e "${YELLOW}[ROLLBACK] Removing newly created absent files...${NC}"
        while IFS= read -r target || [ -n "$target" ]; do
            if [ -n "$target" ] && [ -e "$target" -o -L "$target" ]; then
                rm -f "$target" 2>/dev/null || rm -rf "$target" 2>/dev/null || true
                echo "  ✓ Removed created artifact: $target"
                # Prune empty parent directory if inside ANDROID_HOME, WORK_DIR, or PREFIX
                local parent="$(dirname "$target")"
                while [ -n "$parent" ] && [ "$parent" != "/" ] && [ "$parent" != "." ] && [ "$parent" != "${ANDROID_HOME:-}" ] && [ "$parent" != "${PREFIX:-}" ] && [ "$parent" != "${WORK_DIR:-}" ] && [ -d "$parent" ]; do
                    if [ -z "$(ls -A "$parent" 2>/dev/null)" ]; then
                        rmdir "$parent" 2>/dev/null || break
                        parent="$(dirname "$parent")"
                    else
                        break
                    fi
                done
            fi
        done < "$absent_manifest"
        rm -f "$absent_manifest" 2>/dev/null || true
    fi
}

# Global installer options with defaults
export OPT_YES=false
export OPT_NON_INTERACTIVE=false
export OPT_UPGRADE=false
export OPT_SKIP_SMOKE=false
export DO_UPGRADE=false
export NON_INTERACTIVE=false

parse_installer_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --yes|-y)
                export OPT_YES=true
                export NON_INTERACTIVE=true
                shift
                ;;
            --non-interactive)
                export OPT_NON_INTERACTIVE=true
                export NON_INTERACTIVE=true
                shift
                ;;
            --upgrade)
                export OPT_UPGRADE=true
                export DO_UPGRADE=true
                shift
                ;;
            --skip-smoke)
                export OPT_SKIP_SMOKE=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [--yes|-y] [--non-interactive] [--upgrade] [--skip-smoke] [--help|-h] [--version]"
                echo "  --yes, -y          Automatically confirm prompts and accept licenses"
                echo "  --non-interactive  Run non-interactively"
                echo "  --upgrade          Upgrade existing packages"
                echo "  --skip-smoke       Skip smoke test verification"
                echo "  --version          Print version information"
                exit 0
                ;;
            --version)
                echo "Flutter Termux Installer v${FLUTTER_VERSION} (${RELEASE_TAG})"
                exit 0
                ;;
            *)
                echo "Unknown option: $1" >&2
                echo "Run '$0 --help' for usage." >&2
                shift
                ;;
        esac
    done
}

handle_android_licenses() {
    local auto_accept="${1:-${OPT_YES:-false}}"
    local non_interactive="${2:-${OPT_NON_INTERACTIVE:-false}}"

    if [ "$auto_accept" = "true" ]; then
        echo -e "${BLUE}Auto-accepting Android SDK licenses...${NC}"
        if command -v flutter >/dev/null 2>&1; then
            yes 2>/dev/null | flutter doctor --android-licenses 2>/dev/null || true
        fi
    elif [ -t 0 ] && [ "$non_interactive" != "true" ]; then
        echo -e "${BLUE}Accepting Android SDK licenses...${NC}"
        if command -v flutter >/dev/null 2>&1; then
            flutter doctor --android-licenses || true
        fi
    else
        echo -e "${YELLOW}Non-interactive mode without --yes: skipping interactive license agreement.${NC}"
        echo -e "${YELLOW}Run 'flutter doctor --android-licenses' manually if needed.${NC}"
    fi
}
