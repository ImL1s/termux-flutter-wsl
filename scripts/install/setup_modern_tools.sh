#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Pinned releases of lzhiyong's build-tools
SDK_TOOLS_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-sdk/android-sdk-aarch64.zip"
TARGET_DIR="$HOME/Android/Sdk"
BUILD_TOOLS_VER="35.0.0"

echo "=== Installing Pinned ARM64 Build-Tools (v$BUILD_TOOLS_VER) ==="
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

echo "Downloading SDK package..."
wget -q --show-progress "$SDK_TOOLS_URL" -O sdk_temp.zip

echo "Extracting..."
unzip -o sdk_temp.zip
rm -f sdk_temp.zip

AAPT2_BIN="$TARGET_DIR/build-tools/$BUILD_TOOLS_VER/aapt2"
SPLIT_SELECT_BIN="$TARGET_DIR/build-tools/$BUILD_TOOLS_VER/split-select"

# Invoke Task 3 health check script
echo "=== Running toolchain health checks ==="
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$SCRIPT_DIR/check_toolchain.sh" ]; then
    CHECK_TOOLCHAIN_PATH="$SCRIPT_DIR/check_toolchain.sh"
else
    CHECK_TOOLCHAIN_PATH="$SCRIPT_DIR/../ci/check_toolchain.sh"
fi
bash "$CHECK_TOOLCHAIN_PATH" "$AAPT2_BIN" "$SPLIT_SELECT_BIN"

echo "=== Registering Global Gradle Overrides ==="
GRADLE_PROP_DIR="$HOME/.gradle"
mkdir -p "$GRADLE_PROP_DIR"
GRADLE_PROP_FILE="$GRADLE_PROP_DIR/gradle.properties"

# Safely append/replace global property
AAPT2_OVERRIDE="$HOME/Android/Sdk/build-tools/35.0.0/aapt2"

if grep -q "android.aapt2FromMavenOverride" "$GRADLE_PROP_FILE" 2>/dev/null; then
    sed -i "s|android.aapt2FromMavenOverride=.*|android.aapt2FromMavenOverride=$AAPT2_OVERRIDE|g" "$GRADLE_PROP_FILE"
else
    echo "" >> "$GRADLE_PROP_FILE"
    echo "android.aapt2FromMavenOverride=$AAPT2_OVERRIDE" >> "$GRADLE_PROP_FILE"
fi

echo "🎉 Modern toolchain setup successfully. Mode B activated globally for Termux user."

