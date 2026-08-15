#!/data/data/com.termux/files/usr/bin/bash
# scripts/install/flutter_termux_doctor.sh
# Comprehensive diagnostic tool for Flutter on Termux with PII redaction

set -u

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_DIR="${HOME:-/data/data/com.termux/files/home}"
USER_NAME="$(whoami 2>/dev/null || echo "u0_a0")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

redact_pii() {
    # Redact IPv4 addresses, serial patterns, and user specifics
    sed -E \
        -e "s/[0-9a-fA-F]{8,16}/[REDACTED_HEX]/g" \
        -e "s/[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[REDACTED_IP]/g" \
        -e "s|/data/data/com.termux/files/home/[^/ ]+|[REDACTED_USER_HOME]|g" \
        -e "s|${USER_NAME}|[REDACTED_USER]|g" \
        -e "s/[A-Z0-9]{10,20}/[REDACTED_SERIAL]/g"
}

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}          Flutter Termux Diagnostic Report             ${NC}"
echo -e "${CYAN}======================================================${NC}"
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

echo -e "${BLUE}[1] Architecture & Host OS:${NC}"
ARCH="$(uname -m 2>/dev/null || echo "unknown")"
KERNEL="$(uname -r 2>/dev/null | redact_pii || echo "unknown")"
echo "  CPU Architecture : $ARCH"
echo "  Kernel Version   : $KERNEL"
if [ "$ARCH" = "aarch64" ]; then
    echo -e "  Status           : ${GREEN}PASS (Supported ARM64)${NC}"
else
    echo -e "  Status           : ${RED}FAIL (Unsupported arch: $ARCH)${NC}"
fi
echo ""

echo -e "${BLUE}[2] Core Toolchain & Commands:${NC}"
for cmd in git java javac clang clang++ pkg-config cmake ninja aapt2; do
    if command -v "$cmd" >/dev/null 2>&1; then
        loc="$(command -v "$cmd")"
        echo -e "  ✓ $cmd : ${GREEN}$loc${NC}"
    else
        echo -e "  ✗ $cmd : ${YELLOW}NOT FOUND${NC}"
    fi
done
echo ""

echo -e "${BLUE}[3] Flutter SDK & Dart VM:${NC}"
if command -v flutter >/dev/null 2>&1; then
    FLUTTER_LOC="$(command -v flutter)"
    echo "  Flutter Path    : $FLUTTER_LOC"
    FLUTTER_VER="$(flutter --version 2>&1 | head -n 2 | redact_pii)"
    echo "  Flutter Version : $FLUTTER_VER"
else
    echo -e "  ${RED}Flutter binary not found in PATH${NC}"
fi

if command -v dart >/dev/null 2>&1; then
    DART_LOC="$(command -v dart)"
    echo "  Dart Path       : $DART_LOC"
    DART_VER="$(dart --version 2>&1 | redact_pii)"
    echo "  Dart Version    : $DART_VER"
else
    echo -e "  ${RED}Dart binary not found in PATH${NC}"
fi
echo ""

echo -e "${BLUE}[4] Android SDK & NDK Environment:${NC}"
echo "  ANDROID_HOME    : ${ANDROID_HOME:-[NOT SET]}"
echo "  ANDROID_SDK_ROOT: ${ANDROID_SDK_ROOT:-[NOT SET]}"
echo "  NDK_PATH        : ${NDK_PATH:-[NOT SET]}"

if [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME" ]; then
    echo -e "  Android SDK Dir : ${GREEN}EXISTS ($ANDROID_HOME)${NC}"
    if [ -d "$ANDROID_HOME/build-tools" ]; then
        BT_VERS="$(ls "$ANDROID_HOME/build-tools" 2>/dev/null | tr '\n' ' ')"
        echo "  Build Tools     : $BT_VERS"
    fi
    if [ -d "$ANDROID_HOME/platforms" ]; then
        PLAT_VERS="$(ls "$ANDROID_HOME/platforms" 2>/dev/null | tr '\n' ' ')"
        echo "  Platforms       : $PLAT_VERS"
    fi
else
    echo -e "  Android SDK Dir : ${YELLOW}NOT CONFIGURED${NC}"
fi
echo ""

echo -e "${BLUE}[5] Flutter Doctor Standard Output:${NC}"
if command -v flutter >/dev/null 2>&1; then
    flutter doctor -v 2>&1 | redact_pii
else
    echo "Skipped: flutter not found"
fi
echo ""
echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}             End of Diagnostic Report                 ${NC}"
echo -e "${CYAN}======================================================${NC}"
