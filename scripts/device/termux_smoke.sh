#!/data/data/com.termux/files/usr/bin/bash
# Run inside Termux. Installs a deb copied to /sdcard/Download and performs
# the same release smoke gate used for the Flutter 3.44.0 package.

set -u

LOG=${TERMUX_SMOKE_LOG:-/sdcard/Download/termux_ci_smoke.txt}
DEB=${TERMUX_SMOKE_DEB:-/sdcard/Download/flutter_ci_input.deb}
PROJECT=${TERMUX_SMOKE_PROJECT:-flutter_ci_smoke}

exec > "$LOG" 2>&1
set -x

status=0
record_status() {
    local name="$1"
    local code="$2"
    echo "${name}=${code}"
    # Dynamically set a variable like status_BUILD_APK_STATUS
    eval "status_${name}=\"${code}\""
    if [ "$code" != "0" ]; then
        status=1
    fi
}

export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH="$PREFIX/opt/flutter/bin:$PREFIX/bin:$PATH"
export TMPDIR="$PREFIX/tmp"
export ANDROID_HOME="$PREFIX/opt/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME=$(find "$PREFIX/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' | sort -V | tail -1)

mkdir -p "$TMPDIR"

echo TERMUX_CI_SMOKE
date
echo "DEVICE=$(getprop ro.product.model) SDK=$(getprop ro.build.version.sdk) ABI=$(getprop ro.product.cpu.abi)"
echo "DEB=$DEB"
echo "JAVA_HOME=$JAVA_HOME"

if [ ! -f "$DEB" ]; then
    echo "Missing deb: $DEB"
    echo DONE
    exit 2
fi

echo SECTION=INSTALL_DEB
dpkg -i "$DEB"
record_status INSTALL_STATUS $?
apt --fix-broken install -y || true

echo SECTION=POST_INSTALL
bash "$PREFIX/share/flutter/post_install.sh"
record_status POST_INSTALL_STATUS $?

echo SECTION=POST_INSTALL_MARKERS
grep -n -A8 -B3 'PLATFORM_ABI_LIST\|Flutter Gradle plugin cache' "$PREFIX/share/flutter/post_install.sh" || record_status POST_INSTALL_MARKERS_STATUS $?
grep -n -A8 -B3 'PLATFORM_ABI_LIST' "$PREFIX/opt/flutter/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginConstants.kt" || record_status GRADLE_CONSTANTS_STATUS $?

echo SECTION=VERSIONS
flutter --version
record_status FLUTTER_VERSION_STATUS $?
dart --version
record_status DART_VERSION_STATUS $?
$PREFIX/opt/flutter/bin/cache/dart-sdk/bin/dartvm --version
record_status DARTVM_VERSION_STATUS $?

echo SECTION=DOCTOR
flutter doctor -v
record_status DOCTOR_STATUS $?

echo SECTION=CREATE_PROJECT
cd "$TMPDIR" || exit 3
rm -rf "$PROJECT"
flutter create --platforms=android,linux "$PROJECT"
record_status CREATE_STATUS $?
cd "$PROJECT" || exit 3

echo SECTION=PROJECT_CONFIG
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew
if ! grep -q '^android.aapt2FromMavenOverride=' android/gradle.properties; then
    printf '\nandroid.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2\n' >> android/gradle.properties
fi
if ! grep -q '^android.enableResourceOptimizations=' android/gradle.properties; then
    printf '\nandroid.enableResourceOptimizations=false\n' >> android/gradle.properties
fi
if ! grep -q '^shrink=' android/gradle.properties; then
    printf '\nshrink=false\n' >> android/gradle.properties
fi
if ! grep -q '^org.gradle.jvmargs=' android/gradle.properties; then
    printf '\norg.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8\n' >> android/gradle.properties
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
if 'isMinifyEnabled = false' not in s:
    if 'getByName("release") {' in s:
        s = s.replace('getByName("release") {', 'getByName("release") {\n            isMinifyEnabled = false\n            isShrinkResources = false')
    elif 'release {' in s:
        s = s.replace('release {', 'release {\n            isMinifyEnabled = false\n            isShrinkResources = false')
p.write_text(s)
p = Path('linux/CMakeLists.txt')
s = p.read_text()
if not s.startswith('set(CMAKE_SYSTEM_NAME Linux)'):
    p.write_text('set(CMAKE_SYSTEM_NAME Linux)\n' + s)
PY
grep -R 'compileSdk\|targetSdk\|abiFilters\|aapt2FromMavenOverride\|enableResourceOptimizations\|shrink\|org.gradle.jvmargs\|isMinifyEnabled\|isShrinkResources' android/app/build.gradle.kts android/gradle.properties || true
head -3 linux/CMakeLists.txt

echo SECTION=BUILD_APK_RELEASE
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
record_status BUILD_APK_STATUS $?
ls -lh build/app/outputs/flutter-apk/*.apk 2>/dev/null || true

# Task 2: APK ZIP Layout & Copy checks
APK=build/app/outputs/flutter-apk/app-release.apk
APK_LIST="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/apk_contents.txt"
rm -f "$APK_LIST"
unzip -l "$APK" > "$APK_LIST"
UNZIP_STATUS=$?
if [ "$UNZIP_STATUS" -eq 0 ] && grep -q 'AndroidManifest.xml' "$APK_LIST"; then
    record_status APK_MANIFEST_STATUS 0
else
    record_status APK_MANIFEST_STATUS 1
fi
if [ "$UNZIP_STATUS" -eq 0 ] && grep -q 'resources.arsc' "$APK_LIST"; then
    record_status APK_RESOURCES_STATUS 0
else
    record_status APK_RESOURCES_STATUS 1
fi
rm -f "$APK_LIST"

cp build/app/outputs/flutter-apk/app-release.apk /sdcard/Download/app-release.apk
record_status APK_COPY_STATUS $?

echo SECTION=BUILD_LINUX_RELEASE
flutter build linux --release
record_status BUILD_LINUX_STATUS $?
ls -lh "build/linux/arm64/release/bundle/$PROJECT" build/linux/arm64/release/bundle/lib/libflutter_linux_gtk.so 2>/dev/null || true

echo SECTION=BUILD_AAB_MODE_B
flutter build appbundle --release --target-platform android-arm64 --no-tree-shake-icons 2>/dev/null
record_status BUILD_AAB_STATUS $?

# Generate JSON evidence
EVIDENCE_DIR="$HOME/.termux_smoke"
mkdir -p "$EVIDENCE_DIR"
EVIDENCE_JSON="$EVIDENCE_DIR/evidence.json"

MODE_A_STATUS="failed"
if [ "${status_BUILD_APK_STATUS:-1}" = "0" ] && [ "${status_APK_MANIFEST_STATUS:-1}" = "0" ] && [ "${status_APK_RESOURCES_STATUS:-1}" = "0" ]; then
    MODE_A_STATUS="passed"
fi

MODE_B_STATUS="failed"
if [ "${status_BUILD_AAB_STATUS:-1}" = "0" ]; then
    MODE_B_STATUS="passed"
fi

cat > "$EVIDENCE_JSON" <<EOF
{
  "timestamp": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "device_serial": "$(getprop ro.serialno 2>/dev/null || echo 'unknown')",
  "mode_a_status": "$MODE_A_STATUS",
  "mode_b_status": "$MODE_B_STATUS"
}
EOF
echo "Wrote evidence to $EVIDENCE_JSON"
cat "$EVIDENCE_JSON"

date
echo DONE
exit "$status"
