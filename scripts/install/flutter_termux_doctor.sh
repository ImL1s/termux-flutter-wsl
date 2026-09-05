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

CHECK_ONLY=0
for arg in "$@"; do
    if [ "$arg" = "--check" ] || [ "$arg" = "--strict" ]; then
        CHECK_ONLY=1
    fi
done

VALIDATION_FAILED=0

echo -e "${BLUE}[3] Flutter SDK, Dart VM & Provenance Validation:${NC}"
FLUTTER_BASE_DIR="${FLUTTER_ROOT:-${PREFIX}/opt/flutter}"
if command -v flutter >/dev/null 2>&1; then
    FLUTTER_LOC="$(command -v flutter)"
    echo "  Flutter Path    : $FLUTTER_LOC"
    FLUTTER_VER="$(flutter --version 2>&1 | head -n 2 | redact_pii)"
    echo "  Flutter Version : $FLUTTER_VER"
else
    echo -e "  ${RED}Flutter binary not found in PATH${NC}"
fi

# Load Manifest
MANIFEST_PATH="$PREFIX/share/flutter/manifest.json"
if [ ! -f "$MANIFEST_PATH" ] && [ -f "$FLUTTER_BASE_DIR/bin/cache/canonical_manifest.json" ]; then
    MANIFEST_PATH="$FLUTTER_BASE_DIR/bin/cache/canonical_manifest.json"
fi

EXP_VER="3.44.9"
EXP_REV="6b182d2c7585eba26d4edce0f97630effd256c33"
EXP_DART="3.12.2"
if [ -f "$MANIFEST_PATH" ]; then
    m_v="$(grep -o '"flutter_version": *"[^"]*"' "$MANIFEST_PATH" 2>/dev/null | cut -d'"' -f4 || echo "")"
    m_r="$(grep -o '"framework_revision": *"[^"]*"' "$MANIFEST_PATH" 2>/dev/null | cut -d'"' -f4 || echo "")"
    m_d="$(grep -o '"dart_version": *"[^"]*"' "$MANIFEST_PATH" 2>/dev/null | cut -d'"' -f4 || echo "")"
    [ -n "$m_v" ] && EXP_VER="$m_v"
    [ -n "$m_r" ] && EXP_REV="$m_r"
    [ -n "$m_d" ] && EXP_DART="$m_d"
fi

VER_FILE="$FLUTTER_BASE_DIR/bin/cache/flutter.version.json"
if [ -f "$VER_FILE" ]; then
    v_sha="$(sha256sum "$VER_FILE" 2>/dev/null | awk '{print $1}')"
    v_chan="$(grep -o '"channel": *"[^"]*"' "$VER_FILE" 2>/dev/null | cut -d'"' -f4 || echo "unknown")"
    v_rev="$(grep -o '"frameworkRevision": *"[^"]*"' "$VER_FILE" 2>/dev/null | cut -d'"' -f4 || echo "unknown")"
    v_fver="$(grep -o '"frameworkVersion": *"[^"]*"' "$VER_FILE" 2>/dev/null | cut -d'"' -f4 || echo "unknown")"
    v_dver="$(grep -o '"dartSdkVersion": *"[^"]*"' "$VER_FILE" 2>/dev/null | cut -d'"' -f4 || echo "unknown")"

    ver_errs=()
    [ "$v_chan" != "stable" ] && ver_errs+=("channel='$v_chan'(expected 'stable')")
    [ "$v_rev" != "$EXP_REV" ] && ver_errs+=("revision='$v_rev'(expected '$EXP_REV')")
    [ "$v_fver" != "$EXP_VER" ] && ver_errs+=("version='$v_fver'(expected '$EXP_VER')")
    [ "$v_dver" != "$EXP_DART" ] && ver_errs+=("dartSdk='$v_dver'(expected '$EXP_DART')")

    if [ ${#ver_errs[@]} -eq 0 ]; then
        echo -e "  Version JSON    : ${GREEN}PRESENT (channel=$v_chan, version=$v_fver, rev=$v_rev, sha256=$v_sha)${NC}"
        echo -e "  VERSION_JSON_STATUS=${GREEN}PASSED${NC}"
    else
        echo -e "  Version JSON    : ${RED}INVALID (${ver_errs[*]})${NC}"
        echo -e "  VERSION_JSON_STATUS=${RED}FAILED${NC}"
        VALIDATION_FAILED=1
    fi
else
    echo -e "  Version JSON    : ${RED}NOT FOUND${NC}"
    echo -e "  VERSION_JSON_STATUS=${RED}FAILED${NC}"
    VALIDATION_FAILED=1
fi

if [ -d "$FLUTTER_BASE_DIR/.git" ]; then
    is_synth="NO"
    [ -f "$FLUTTER_BASE_DIR/.git/termux_synthetic" ] && is_synth="YES"
    br="$(git --git-dir="$FLUTTER_BASE_DIR/.git" symbolic-ref --short HEAD 2>/dev/null || echo "detached")"
    tag_head="$(git --git-dir="$FLUTTER_BASE_DIR/.git" tag --points-at HEAD 2>/dev/null || echo "none")"
    t_cnt="$(git --git-dir="$FLUTTER_BASE_DIR/.git" tag -l 2>/dev/null | wc -l)"
    fetch_head="NO"
    if [ -f "$FLUTTER_BASE_DIR/.git/FETCH_HEAD" ] && [ -s "$FLUTTER_BASE_DIR/.git/FETCH_HEAD" ]; then
        fetch_head="YES"
    elif [ -f "$FLUTTER_BASE_DIR/.git/FETCH_HEAD" ]; then
        # Empty FETCH_HEAD is leftover noise from git plumbing; treat as absent.
        rm -f "$FLUTTER_BASE_DIR/.git/FETCH_HEAD" 2>/dev/null || true
    fi
    echo "  Git Repo State  : branch=$br, tag_at_head=$tag_head, total_tags=$t_cnt, synthetic=$is_synth, FETCH_HEAD=$fetch_head"

    if [ "$is_synth" = "YES" ]; then
        synth_errs=()
        [ "$br" != "stable" ] && synth_errs+=("branch='$br'(expected 'stable')")
        ! echo "$tag_head" | grep -qx "$EXP_VER" && synth_errs+=("tag_at_head='$tag_head'(expected '$EXP_VER')")
        [ "$t_cnt" -ne 1 ] && synth_errs+=("tag_count=$t_cnt(expected 1)")
        [ "$fetch_head" = "YES" ] && synth_errs+=("FETCH_HEAD present")

        if [ ${#synth_errs[@]} -eq 0 ]; then
            echo -e "  SYNTHETIC_REPO_STATUS=${GREEN}PASSED${NC}"
        else
            echo -e "  SYNTHETIC_REPO_STATUS=${RED}FAILED (${synth_errs[*]})${NC}"
            VALIDATION_FAILED=1
        fi
    else
        echo -e "  SYNTHETIC_REPO_STATUS=${YELLOW}SKIPPED (non-synthetic user repository)${NC}"
    fi
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

if [ "$CHECK_ONLY" -eq 1 ] && [ "$VALIDATION_FAILED" -ne 0 ]; then
    exit 1
fi
exit 0
