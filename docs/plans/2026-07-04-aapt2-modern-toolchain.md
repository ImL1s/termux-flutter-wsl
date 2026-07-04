# AAPT2 Modern Toolchain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable safe, modular, and Play Store compliant (API 35+) compilation on Termux via decoupled static toolchains, keeping the local verified build (API 34, no-shrink) as the stable default.

**Architecture:** Maintain Mode A (Verified Local Build) as the stable default using Termux's system dynamic `aapt2` and disabling R8 shrinking. Add Mode B (Experimental Publish Toolchain) as an opt-in experimental track that installs community-maintained native static Android SDK build-tools, dynamically checked via verification scripts and globally configured via `~/.gradle/gradle.properties`.

**Tech Stack:** Bash, Gradle, Android SDK Build-Tools, Python, ADB.

---

### Task 1: Align `termux_smoke.sh` with Mode A & Mode B Matrix

**Files:**
- Modify: `scripts/device/termux_smoke.sh`

**Step 1: Write a syntax validation test**
Run: `bash -n scripts/device/termux_smoke.sh`
Expected: PASS (exits 0 with no syntax errors)

**Step 2: Update the project patching phase in `termux_smoke.sh`**
Modify `scripts/device/termux_smoke.sh` to configure the test project matching **Mode A** requirements (writing `shrink=false` to properties and explicitly disabling minification in `build.gradle.kts` release buildType).

Modify the script block around project setup:
```bash
# In scripts/device/termux_smoke.sh, update project patching:
echo "patching android project..."
cat >> android/gradle.properties <<'EOF'
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
android.enableResourceOptimizations=false
shrink=false
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8
EOF

python3 - <<'PY'
from pathlib import Path
p = Path('android/app/build.gradle.kts')
s = p.read_text()
s = s.replace("compileSdk = flutter.compileSdkVersion", "compileSdk = 34")
s = s.replace("targetSdk = flutter.targetSdkVersion", "targetSdk = 34")
# Inject Mode A buildTypes release overrides
if "buildTypes {" in s:
    s = s.replace(
        'buildTypes {\n        release {',
        'buildTypes {\n        release {\n            isMinifyEnabled = false\n            isShrinkResources = false'
    )
p.write_text(s)
PY
```

**Step 3: Run the syntax check**
Run: `bash -n scripts/device/termux_smoke.sh`
Expected: PASS

**Step 4: Commit**
```bash
git add scripts/device/termux_smoke.sh
git commit -m "test: align termux_smoke.sh with Mode A release properties and buildTypes overrides"
```

---

### Task 2: Implement ZIP Layout and ADB Installation Checks in `termux_smoke.sh`

**Files:**
- Modify: `scripts/device/termux_smoke.sh`

**Step 1: Write the validation checks into `termux_smoke.sh`**
Add post-build ZIP inspections and an ADB deployment test inside the compile check block of `scripts/device/termux_smoke.sh`.

Add the following code block:
```bash
# In scripts/device/termux_smoke.sh, after compile release APK:
APK_PATH="build/app/outputs/flutter-apk/app-release.apk"

echo "=== Verifying APK ZIP layout ==="
if unzip -l "$APK_PATH" | grep -E 'AndroidManifest.xml' && unzip -l "$APK_PATH" | grep -E 'resources.arsc'; then
    echo "✅ APK layout check passed."
else
    echo "❌ APK layout check failed: AndroidManifest.xml or resources.arsc missing."
    exit 1
fi

echo "=== Deploying and testing APK installation ==="
if adb install -r "$APK_PATH"; then
    echo "✅ APK installation passed."
else
    echo "❌ APK installation failed."
    exit 1
fi
```

**Step 2: Run syntax validation**
Run: `bash -n scripts/device/termux_smoke.sh`
Expected: PASS

**Step 3: Commit**
```bash
git add scripts/device/termux_smoke.sh
git commit -m "feat: add APK ZIP validation and ADB install deployment checks to termux_smoke.sh"
```

---

### Task 3: Implement Toolchain Health Check Validator

**Files:**
- Create: `scripts/ci/check_toolchain.sh`

**Step 1: Write the health check script**
Create a new file `scripts/ci/check_toolchain.sh` containing validations for dynamic linkage (`readelf -d`), `aapt2` execution, and `split-select` permissions.

```bash
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

AAPT2_PATH="${1:-/data/data/com.termux/files/usr/bin/aapt2}"
SPLIT_SELECT_PATH="${2:-}"

echo "=== Checking AAPT2 Binary: $AAPT2_PATH ==="
if [ ! -f "$AAPT2_PATH" ]; then
    echo "❌ AAPT2 binary not found."
    exit 1
fi

# Check static linkage or dynamic library dependencies
echo "Checking linkage dependencies..."
if readelf -d "$AAPT2_PATH" | grep -E 'NEEDED' | grep -E 'libprotobuf'; then
    echo "⚠️ Warning: AAPT2 is dynamically linked to libprotobuf. Vulnerable to rolling updates."
else
    echo "✅ AAPT2 is statically linked or protobuf-independent."
fi

# Test runtime execution
echo "Executing version command..."
if "$AAPT2_PATH" version; then
    echo "✅ AAPT2 runtime execution passed."
else
    echo "❌ AAPT2 runtime execution failed."
    exit 1
fi

# Verify split-select if path provided
if [ -n "$SPLIT_SELECT_PATH" ]; then
    echo "=== Checking split-select Binary: $SPLIT_SELECT_PATH ==="
    if [ ! -x "$SPLIT_SELECT_PATH" ]; then
        echo "❌ split-select is not executable or missing."
        exit 1
    fi
    echo "✅ split-select is executable."
fi
```

**Step 2: Test the validator against native Termux aapt2**
Run syntax check: `bash -n scripts/ci/check_toolchain.sh`
Expected: PASS

**Step 3: Commit**
```bash
git add scripts/ci/check_toolchain.sh
git commit -m "feat: add check_toolchain.sh helper to verify aapt2 and split-select health"
```

---

### Task 4: Implement Decoupled Modern Build-Tools Installer (Mode B)

**Files:**
- Create: `scripts/install/setup_modern_tools.sh`

**Step 1: Write the setup installer**
Create `scripts/install/setup_modern_tools.sh` to download the pinned community NDK toolchain release from `lzhiyong/termux-ndk`, extract Build-Tools, verify it using `check_toolchain.sh`, and set up the global Gradle properties override.

```bash
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
bash "$PREFIX/opt/flutter/scripts/ci/check_toolchain.sh" "$AAPT2_BIN" "$SPLIT_SELECT_BIN"

echo "=== Registering Global Gradle Overrides ==="
GRADLE_PROP_DIR="$HOME/.gradle"
mkdir -p "$GRADLE_PROP_DIR"
GRADLE_PROP_FILE="$GRADLE_PROP_DIR/gradle.properties"

# Safely append/replace global property
if grep -q "android.aapt2FromMavenOverride" "$GRADLE_PROP_FILE" 2>/dev/null; then
    sed -i "s|android.aapt2FromMavenOverride=.*|android.aapt2FromMavenOverride=$AAPT2_BIN|g" "$GRADLE_PROP_FILE"
else
    echo "" >> "$GRADLE_PROP_FILE"
    echo "android.aapt2FromMavenOverride=$AAPT2_BIN" >> "$GRADLE_PROP_FILE"
fi

echo "🎉 Modern toolchain setup successfully. Mode B activated globally for Termux user."
```

**Step 2: Run syntax validation**
Run: `bash -n scripts/install/setup_modern_tools.sh`
Expected: PASS

**Step 3: Commit**
```bash
git add scripts/install/setup_modern_tools.sh
git commit -m "feat: add setup_modern_tools.sh to install community ARM64 build-tools and inject global gradle.properties overrides"
```
