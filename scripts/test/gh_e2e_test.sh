#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Termux Flutter release E2E test
# Downloads the GitHub Release deb, installs it, runs post_install,
# then verifies doctor/create/build apk/build linux on-device.
# ============================================================
set -u

export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PREFIX/opt/flutter/bin:$PATH
export HOME=/data/data/com.termux/files/home
export TMPDIR=$PREFIX/tmp
export FLUTTER_VERSION=${FLUTTER_VERSION:-3.44.0}
export EXPECTED_SHA256=${EXPECTED_SHA256:-b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846}
export DEB_NAME="flutter_${FLUTTER_VERSION}_aarch64.deb"
export DEB_URL=${DEB_URL:-"https://github.com/ImL1s/termux-flutter-wsl/releases/download/v${FLUTTER_VERSION}/${DEB_NAME}"}

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
FAILED=0

pass() { echo -e "${GREEN}✅ PASS: $1${NC}"; }
fail() { echo -e "${RED}❌ FAIL: $1${NC}"; FAILED=1; }
run_step() {
    local name="$1"
    shift
    echo ""
    echo "=== $name ==="
    "$@"
    local code=$?
    if [ $code -eq 0 ]; then pass "$name"; else fail "$name (exit $code)"; fi
    return $code
}

patch_project() {
    sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew
    if ! grep -q '^android.aapt2FromMavenOverride=' android/gradle.properties; then
        printf '\nandroid.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2\n' >> android/gradle.properties
    fi
    python - <<'PY'
from pathlib import Path
p = Path('android/app/build.gradle.kts')
s = p.read_text()
s = s.replace('compileSdk = flutter.compileSdkVersion', 'compileSdk = 34')
s = s.replace('compileSdk = flutter.compileSdkVersion.toInteger()', 'compileSdk = 34')
s = s.replace('targetSdk = flutter.targetSdkVersion', 'targetSdk = 34')
s = s.replace('targetSdk = flutter.targetSdkVersion.toInteger()', 'targetSdk = 34')
if 'abiFilters += listOf("arm64-v8a")' not in s:
    s = s.replace('targetSdk = 34\n', 'targetSdk = 34\n        ndk { abiFilters += listOf("arm64-v8a") }\n')
p.write_text(s)
p = Path('linux/CMakeLists.txt')
s = p.read_text()
if not s.startswith('set(CMAKE_SYSTEM_NAME Linux)'):
    p.write_text('set(CMAKE_SYSTEM_NAME Linux)\n' + s)
PY
}

echo "╔═══════════════════════════════════════════╗"
echo "║  Termux Flutter Release E2E Test          ║"
echo "╚═══════════════════════════════════════════╝"
echo "Version: $FLUTTER_VERSION"
echo "URL: $DEB_URL"

mkdir -p "$TMPDIR"
cd "$HOME" || exit 1

run_step "Install prerequisites" pkg install -y wget openjdk-21 git >/dev/null 2>&1 || true

echo ""
echo "=== Download release deb ==="
rm -f "$DEB_NAME"
wget -q --show-progress "$DEB_URL" -O "$DEB_NAME"
if [ -n "$EXPECTED_SHA256" ]; then
    actual=$(sha256sum "$DEB_NAME" | awk '{print $1}')
    if [ "$actual" = "$EXPECTED_SHA256" ]; then pass "SHA256 $actual"; else fail "SHA256 mismatch: $actual"; fi
fi
ls -lh "$DEB_NAME"

run_step "Install deb" dpkg -i "$DEB_NAME" || true
apt --fix-broken install -y >/dev/null 2>&1 || true
[ -x "$PREFIX/opt/flutter/bin/flutter" ] && pass "Flutter binary installed" || fail "Flutter binary missing"

run_step "Run post_install.sh" bash "$PREFIX/share/flutter/post_install.sh"

source "$PREFIX/etc/profile.d/flutter.sh" 2>/dev/null || true
export PATH=$PREFIX/opt/flutter/bin:$PATH
export ANDROID_HOME=$PREFIX/opt/android-sdk
export JAVA_HOME=$(find $PREFIX/lib/jvm -maxdepth 1 -type d -name 'java-*-openjdk' | sort -V | tail -1)

run_step "flutter --version" flutter --version
run_step "dart --version" dart --version
run_step "dartvm --version" dartvm --version
run_step "flutter doctor -v" flutter doctor -v

echo ""
echo "=== Create and build smoke project ==="
rm -rf gh_e2e_test
flutter create --platforms=android,linux gh_e2e_test || fail "flutter create"
cd gh_e2e_test || exit 1
patch_project
run_step "flutter build apk" flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
run_step "flutter build linux" flutter build linux --release

APK=$(find build/app/outputs/flutter-apk -name '*.apk' -type f 2>/dev/null | head -1)
if [ -n "$APK" ]; then ls -lh "$APK"; pass "APK artifact exists"; else fail "APK artifact missing"; fi
LINUX_BIN="build/linux/arm64/release/bundle/gh_e2e_test"
if [ -f "$LINUX_BIN" ]; then ls -lh "$LINUX_BIN"; pass "Linux artifact exists"; else fail "Linux artifact missing"; fi

echo ""
if [ "$FAILED" = "0" ]; then
    echo "🎉 ALL TESTS PASSED"
else
    echo "⚠️ SOME TESTS FAILED"
fi
exit "$FAILED"
