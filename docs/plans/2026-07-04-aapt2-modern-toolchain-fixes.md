# AAPT2 Modern Toolchain & GN Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden Mode B toolchain wiring (split-select, p7zip, SHA256 verification), enforce static libprotobuf validation checks, integrate test scripts into CI, and declare unused GN arguments.

**Architecture:** Overwrite stub tools in the active system SDK path with working static build-tools symlinks during Mode B activation. Pin downloads to a verified SHA256 hash and extract using p7zip. Fail check_toolchain.sh on dynamic dependencies unless ALLOW_DYNAMIC_AAPT2=1 is explicitly set. Update the GitHub Action workflows and Python checks to include new files, and declare termux_cross_host inside the engine build config patches.

**Tech Stack:** Bash, YAML, GN, Python.

---

### Task 1: Setup p7zip Extraction & SHA256 Verification in `setup_modern_tools.sh`

**Files:**
- Modify: `scripts/install/setup_modern_tools.sh`
- Modify: `package.yaml`

**Step 1: Write a syntax validation check**
Run: `bash -n scripts/install/setup_modern_tools.sh`
Expected: PASS (exits 0 with no syntax errors)

**Step 2: Modify package.yaml dependencies**
Open `package.yaml` and update the control depends field:
```yaml
# In package.yaml, replace unzip with p7zip
Depends: git, which, gtk3, xorgproto, ninja, cmake, clang, pkg-config, openjdk-21, wget, p7zip
```

**Step 3: Modify setup_modern_tools.sh download and extraction**
Update `setup_modern_tools.sh` to download the `.7z` package, compute its SHA256 checksum, and extract using `7z`:
```bash
# In scripts/install/setup_modern_tools.sh
SDK_TOOLS_URL="https://github.com/lzhiyong/termux-ndk/releases/download/android-sdk/android-sdk-aarch64.7z"
TARGET_DIR="$HOME/Android/Sdk"
BUILD_TOOLS_VER="35.0.0"
EXPECTED_SHA="5b3535d4533fbd788ef976a4ce4c3050f19150fe9d0bb092263045317c46f463"

echo "=== Installing Pinned ARM64 Build-Tools (v$BUILD_TOOLS_VER) ==="
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

echo "Downloading SDK package..."
wget -q --show-progress "$SDK_TOOLS_URL" -O sdk_temp.7z

echo "Verifying SHA256 checksum..."
echo "$EXPECTED_SHA  sdk_temp.7z" | sha256sum -c -

echo "Extracting 7z archive..."
7z x -y sdk_temp.7z
rm -f sdk_temp.7z
```

**Step 4: Verify syntax and repository sanity**
Run: `bash -n scripts/install/setup_modern_tools.sh`
Expected: PASS

**Step 5: Commit**
```bash
git add package.yaml scripts/install/setup_modern_tools.sh
git commit -m "feat: use p7zip download package, pin SHA256 checksum, and use 7z extraction in setup_modern_tools.sh"
```

---

### Task 2: Symlink Real `aapt2` and `split-select` into the System SDK Directory

**Files:**
- Modify: `scripts/install/setup_modern_tools.sh`

**Step 1: Write a syntax check**
Run: `bash -n scripts/install/setup_modern_tools.sh`
Expected: PASS

**Step 2: Add symlinking wiring logic**
Add target system SDK symlinking code to the end of `setup_modern_tools.sh` before writing Gradle properties:
```bash
# In scripts/install/setup_modern_tools.sh
SYSTEM_BT_DIR="/data/data/com.termux/files/usr/opt/android-sdk/build-tools/$BUILD_TOOLS_VER"
echo "=== Overwriting System SDK build-tools stubs with symlinks ==="
mkdir -p "$SYSTEM_BT_DIR"

for tool in aapt2 split-select; do
    TARGET_TOOL="$SYSTEM_BT_DIR/$tool"
    # Backup existing dynamic binaries or stubs if they are regular files
    if [ -f "$TARGET_TOOL" ] && [ ! -L "$TARGET_TOOL" ]; then
        echo "Backing up existing $tool to ${tool}.bak"
        mv "$TARGET_TOOL" "${TARGET_TOOL}.bak"
    fi
done

ln -sf "$AAPT2_BIN" "$SYSTEM_BT_DIR/aapt2"
ln -sf "$SPLIT_SELECT_BIN" "$SYSTEM_BT_DIR/split-select"
echo "✅ Symlinks successfully registered in $SYSTEM_BT_DIR"
```

**Step 3: Run syntax validation**
Run: `bash -n scripts/install/setup_modern_tools.sh`
Expected: PASS

**Step 4: Commit**
```bash
git add scripts/install/setup_modern_tools.sh
git commit -m "feat: overwrite system SDK build-tools stubs with working static symlinks in setup_modern_tools.sh"
```

---

### Task 3: Enforce Static Linkage Check in `check_toolchain.sh`

**Files:**
- Modify: `scripts/ci/check_toolchain.sh`

**Step 1: Write a syntax validation check**
Run: `bash -n scripts/ci/check_toolchain.sh`
Expected: PASS

**Step 2: Implement dynamic linkage failure check**
Update `check_toolchain.sh` to enforce static linkage by failing if dynamic dependencies like `libprotobuf` are found unless `ALLOW_DYNAMIC_AAPT2=1` is passed:
```bash
# In scripts/ci/check_toolchain.sh
echo "Checking linkage dependencies..."
if command -v readelf >/dev/null 2>&1; then
    if readelf -d "$AAPT2_PATH" 2>/dev/null | grep -E 'NEEDED' | grep -E 'libprotobuf' >/dev/null 2>&1; then
        if [ "${ALLOW_DYNAMIC_AAPT2:-0}" != "1" ]; then
            echo "❌ Error: AAPT2 is dynamically linked to libprotobuf. Linkage validation failed."
            echo "   Rolling-release updates might break this binary. Set ALLOW_DYNAMIC_AAPT2=1 to bypass."
            exit 1
        fi
        echo "⚠️ Warning: AAPT2 is dynamically linked to libprotobuf (allowed via ALLOW_DYNAMIC_AAPT2=1)."
    else
        echo "✅ AAPT2 is statically linked or protobuf-independent."
    fi
else
    echo "⚠️ Warning: readelf is not installed. Skipping linkage dependency check."
fi
```

**Step 3: Run syntax validation**
Run: `bash -n scripts/ci/check_toolchain.sh`
Expected: PASS

**Step 4: Commit**
```bash
git add scripts/ci/check_toolchain.sh
git commit -m "feat: enforce static linkage validation on AAPT2 in check_toolchain.sh"
```

---

### Task 4: Add New Scripts to CI Workflow Syntax Verification

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: Write a syntax verification check**
Run: `python scripts/ci/check_repo.py`
Expected: PASS

**Step 2: Update workflow configuration**
Update the "Shell syntax check" step in `.github/workflows/ci.yml` to include the two new scripts:
```yaml
# In .github/workflows/ci.yml
      - name: Shell syntax check
        shell: bash
        run: |
          set -euo pipefail
          bash -n install_flutter_complete.sh
          bash -n scripts/install/install.sh
          bash -n scripts/install/install_termux_flutter.sh
          bash -n scripts/install/post_install.sh
          bash -n scripts/test/gh_e2e_test.sh
          bash -n scripts/device/termux_smoke.sh
          bash -n scripts/install/setup_modern_tools.sh
          bash -n scripts/ci/check_toolchain.sh
```

**Step 3: Run validation**
Run: `python scripts/ci/check_repo.py`
Expected: PASS

**Step 4: Commit**
```bash
git add .github/workflows/ci.yml
git commit -m "ci: add setup_modern_tools.sh and check_toolchain.sh to workflow syntax checks"
```

---

### Task 5: Declare `termux_cross_host` in GN Build Configuration Patches

**Files:**
- Modify: `patches/3.44.2/engine.patch`
- Modify: `patches/3.44.0/engine.patch`

**Step 1: Edit patches/3.44.2/engine.patch**
Locate the `termux.gni` block inside `patches/3.44.2/engine.patch` and add `termux_cross_host = false` to the `declare_args()` block:
```diff
# In patches/3.44.2/engine.patch
@@ -301,6 +301,7 @@
+declare_args() {
+  termux_api_level = 26
+
+  is_termux = false
+  is_termux_host = false
+  termux_cross_host = false
+}
```

**Step 2: Edit patches/3.44.0/engine.patch**
Locate the `termux.gni` block inside `patches/3.44.0/engine.patch` and add `termux_cross_host = false` to the `declare_args()` block:
```diff
# In patches/3.44.0/engine.patch
@@ -301,6 +301,7 @@
+declare_args() {
+  termux_api_level = 26
+
+  is_termux = false
+  is_termux_host = false
+  termux_cross_host = false
+}
```

**Step 3: Verify repository contracts**
Run: `python scripts/ci/check_repo.py`
Expected: PASS

**Step 4: Commit**
```bash
git add patches/3.44.2/engine.patch patches/3.44.0/engine.patch
git commit -m "fix: declare termux_cross_host in engine build config patches to resolve GN warnings"
```
