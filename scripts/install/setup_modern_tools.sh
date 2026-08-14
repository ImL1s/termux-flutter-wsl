#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Pinned releases of lzhiyong's build-tools
SDK_TOOLS_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-sdk/android-sdk-aarch64.7z"
TARGET_DIR="$HOME/Android/Sdk"
BUILD_TOOLS_VER="35.0.0"
EXPECTED_SHA="5b3535d4533fbd788ef976a4ce4c3050f19150fe9d0bb092263045317c46f463"

# Check if 7z command is available
if ! command -v 7z &>/dev/null; then
    echo "Error: '7z' command is required but not found. Please install 'p7zip' first." >&2
    exit 1
fi

# Path discovery for check_toolchain.sh (Pre-run check)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ -f "$SCRIPT_DIR/check_toolchain.sh" ]; then
    CHECK_TOOLCHAIN_PATH="$SCRIPT_DIR/check_toolchain.sh"
elif [ -f "$SCRIPT_DIR/../ci/check_toolchain.sh" ]; then
    CHECK_TOOLCHAIN_PATH="$SCRIPT_DIR/../ci/check_toolchain.sh"
else
    echo "Error: check_toolchain.sh helper script not found. Please run within the standard Termux Flutter install tree." >&2
    exit 1
fi

echo "=== Installing Pinned ARM64 Build-Tools (v$BUILD_TOOLS_VER) ==="
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# Register cleanup trap for sdk_temp.7z
trap 'rm -f "$TARGET_DIR/sdk_temp.7z" 2>/dev/null' EXIT

echo "Downloading SDK package..."
wget -q --tries=3 --show-progress "$SDK_TOOLS_URL" -O sdk_temp.7z

echo "Verifying SHA256 checksum..."
echo "$EXPECTED_SHA  sdk_temp.7z" | sha256sum -c -

echo "Extracting 7z archive..."
7z x -y sdk_temp.7z
rm -f sdk_temp.7z

AAPT2_BIN="$TARGET_DIR/build-tools/$BUILD_TOOLS_VER/aapt2"
SPLIT_SELECT_BIN="$TARGET_DIR/build-tools/$BUILD_TOOLS_VER/split-select"
chmod +x "$AAPT2_BIN" "$SPLIT_SELECT_BIN"

# Invoke Task 3 health check script
echo "=== Running toolchain health checks ==="
bash "$CHECK_TOOLCHAIN_PATH" "$AAPT2_BIN" "$SPLIT_SELECT_BIN"

# Calculate target directory
SYSTEM_BT_DIR="${PREFIX:-/data/data/com.termux/files/usr}/opt/android-sdk/build-tools/$BUILD_TOOLS_VER"
echo "=== Overwriting System SDK build-tools stubs with symlinks ==="
mkdir -p "$SYSTEM_BT_DIR"

for tool in aapt2 split-select; do
    TARGET_TOOL="$SYSTEM_BT_DIR/$tool"
    # Backup existing dynamic binaries or stubs if they are regular files and not symlinks
    if [ -f "$TARGET_TOOL" ] && [ ! -L "$TARGET_TOOL" ]; then
        echo "Backing up existing $tool to ${tool}.bak"
        mv "$TARGET_TOOL" "${TARGET_TOOL}.bak"
    fi
done

ln -sf "$AAPT2_BIN" "$SYSTEM_BT_DIR/aapt2"
ln -sf "$SPLIT_SELECT_BIN" "$SYSTEM_BT_DIR/split-select"
echo "✅ Symlinks successfully registered in $SYSTEM_BT_DIR"

echo "=== Registering Global Gradle Overrides ==="
GRADLE_PROP_DIR="$HOME/.gradle"
mkdir -p "$GRADLE_PROP_DIR"
GRADLE_PROP_FILE="$GRADLE_PROP_DIR/gradle.properties"

# Safely replace any formatted property line
sed -i -E '/^[[:space:]]*android\.aapt2FromMavenOverride[[:space:]]*[=:]/d' "$GRADLE_PROP_FILE" 2>/dev/null || true
echo "android.aapt2FromMavenOverride=${AAPT2_OVERRIDE:-$AAPT2_BIN}" >> "$GRADLE_PROP_FILE"

echo "🎉 Modern toolchain setup successfully. Mode B activated globally for Termux user."

