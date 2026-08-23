#!/bin/bash
#
# Complete Flutter deb build script
# Builds everything needed including Android gen_snapshot for APK building
#
# Usage: ./build_complete_deb.sh
#
# Prerequisites:
# - WSL Ubuntu with build dependencies installed
# - depot_tools in PATH
# - Engine source synced (gclient sync completed)
#

set -e

cd /home/iml1s/projects/termux-flutter
export PATH="/home/iml1s/projects/termux-flutter/depot_tools:$PATH"

echo "=========================================="
echo " Flutter deb Complete Build Script"
echo " Includes Android gen_snapshot for APK"
echo "=========================================="
echo ""

ARCH="arm64"
VERSION="3.44.9"

# Step 1: Build Linux debug
echo "[1/6] Building linux_debug_arm64..."
python3 build.py configure --arch=$ARCH --mode=debug
python3 build.py build --arch=$ARCH --mode=debug
echo "✓ linux_debug_arm64 complete"

# Step 2: Build Linux release
echo ""
echo "[2/6] Building linux_release_arm64..."
python3 build.py configure --arch=$ARCH --mode=release
python3 build.py build --arch=$ARCH --mode=release
echo "✓ linux_release_arm64 complete"

# Step 3: Build Linux profile
echo ""
echo "[3/6] Building linux_profile_arm64..."
python3 build.py configure --arch=$ARCH --mode=profile
python3 build.py build --arch=$ARCH --mode=profile
echo "✓ linux_profile_arm64 complete"

# Step 4: Build Android gen_snapshot (for flutter build apk)
echo ""
echo "[4/6] Building Android gen_snapshot..."
python3 build.py configure_android --arch=$ARCH --mode=release
python3 build.py build_android_gen_snapshot --arch=$ARCH --mode=release
echo "✓ android_release_arm64 gen_snapshot complete"

# Step 5: Verify all builds
echo ""
echo "[5/6] Verifying builds..."
ls -la flutter/engine/src/out/linux_debug_arm64/gen_snapshot
ls -la flutter/engine/src/out/linux_release_arm64/gen_snapshot
ls -la flutter/engine/src/out/linux_profile_arm64/gen_snapshot
ls -la flutter/engine/src/out/android_release_arm64/exe.stripped/gen_snapshot
echo "✓ All builds verified"

# Step 6: Package deb
echo ""
echo "[6/6] Packaging deb..."
mkdir -p release
python3 build.py debuild --arch=$ARCH
echo "✓ deb package complete"

# Show result
echo ""
echo "=========================================="
echo " Build Complete!"
echo "=========================================="
ls -la release/*.deb

echo ""
echo "Next steps:"
echo "1. Upload to GitHub Release"
echo "2. Test installation on Termux"
