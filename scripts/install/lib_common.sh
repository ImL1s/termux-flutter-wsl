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
export EXPECTED_SHA256="${EXPECTED_SHA256:-${FLUTTER_DEB_SHA256:-66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000}}"

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
