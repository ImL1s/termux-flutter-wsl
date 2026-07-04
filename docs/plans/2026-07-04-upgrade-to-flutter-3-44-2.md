# Upgrade to Flutter 3.44.2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Flutter SDK cross-compilation target to `3.44.2` for Termux ARM64 and verify the build.

**Architecture:** Modify `build.toml` to point to `3.44.2`. Create `patches/3.44.2/` directory by copying `patches/3.44.0/`. Download the source via `build.py clone`, sync dependencies with `build.py sync`, apply patches, verify sysroot, and perform a full build utilizing `build.py build_all`.

**Tech Stack:** Python 3, WSL2 Ubuntu, gclient, GN, Ninja, Android NDK r27d, DPKG/Debian packaging.

---

### Task 1: Update build.toml Configuration

**Files:**
- Modify: `D:/OtherProject/mine/flutter_termux/build.toml:1-5`

**Step 1: Write the verification command**

We will verify that the configuration is updated using the `config` subcommand of `build.py`.

**Step 2: Run verification to check it fails**

Run: `python3 build.py config`
Expected output: Contains `tag\t: 3.44.0` (showing the old version).

**Step 3: Modify build.toml to version 3.44.2**

Change:
```toml
[flutter]
tag = '3.44.0'
```
to:
```toml
[flutter]
tag = '3.44.2'
```

**Step 4: Run verification to check it passes**

Run: `python3 build.py config`
Expected output: Contains `tag\t: 3.44.2`.

**Step 5: Commit**

```bash
git add build.toml
git commit -m "config: update flutter tag to 3.44.2 in build.toml"
```

---

### Task 2: Set up Patches Directory for 3.44.2

**Files:**
- Create: `D:/OtherProject/mine/flutter_termux/patches/3.44.2/dart.patch`
- Create: `D:/OtherProject/mine/flutter_termux/patches/3.44.2/engine.patch`
- Create: `D:/OtherProject/mine/flutter_termux/patches/3.44.2/flutter_sdk_arm64_default.patch`
- Create: `D:/OtherProject/mine/flutter_termux/patches/3.44.2/skia.patch`

**Step 1: Check patches copy exists**

 we will verify that the 3.44.2 patch folder doesn't exist yet.

Run: `ls patches/3.44.2`
Expected: Command fails or shows no files.

**Step 2: Copy the 3.44.0 patches to 3.44.2**

Run the copy command:
```bash
cp -r patches/3.44.0 patches/3.44.2
```

**Step 3: Verify the patches are in place**

Run: `ls -la patches/3.44.2`
Expected: Output showing the 4 patch files (`dart.patch`, `engine.patch`, `flutter_sdk_arm64_default.patch`, `skia.patch`).

**Step 4: Commit**

```bash
git add patches/3.44.2
git commit -m "feat: copy 3.44.0 patches to 3.44.2"
```

---

### Task 3: Clone Flutter 3.44.2 Source

**Files:**
- Create: (Downloads code to `D:/OtherProject/mine/flutter_termux/flutter`)

**Step 1: Check current tag in the flutter repo**

If the flutter directory exists, check the checked out tag.
Run: `git -C flutter describe --tags`
Expected: Failing or outputting `3.44.0`.

**Step 2: Run clone script**

Run: `python3 build.py clone`
Expected: Clones or updates the flutter repository to `3.44.2`.

**Step 3: Verify the cloned version**

Run: `git -C flutter describe --tags`
Expected: Outputs `3.44.2`.

**Step 4: Commit**

Since the `flutter` directory is gitignored, no files need to be committed here. We will record the status.
```bash
git status
```

---

### Task 4: Sync Engine Dependencies

**Files:**
- Create/Modify: (Syncs dependencies inside `flutter/engine/src`)

**Step 1: Run gclient sync via build.py**

Run: `python3 build.py sync`
Expected: `gclient sync` completes successfully and output confirms "Fixed #5: Replaced prebuilt dart-sdk with version 3.12.0" and "Fixed #5: Finished dart pub get".

**Step 2: Verify package config is generated**

Check if the engine checkout folder exists.
Run: `ls -la flutter/engine/src/flutter`
Expected: Contains source files for the engine repository.

---

### Task 5: Apply Patches

**Files:**
- Modify: (Modifies engine, dart, skia, and sdk repository files)

**Step 1: Verify clean state before patching**

Run:
```bash
git -C flutter/engine/src/flutter status
```
Expected: Clean working directory (no local modifications).

**Step 2: Apply patches**

Run:
```bash
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
python3 build.py patch_flutter_sdk
```
Expected: All commands exit with success (status 0). If there are merge conflicts due to minor code differences between 3.44.0 and 3.44.2, resolve the conflicts and regenerate the patch using `git diff > patches/3.44.2/<patch_name>.patch`.

**Step 3: Verify changes are applied**

Run:
```bash
git -C flutter/engine/src/flutter diff --stat
```
Expected: Shows differences in patched files.

---

### Task 6: Build Termux Sysroot

**Files:**
- Modify: (Downloads packages to `sysroot/` and modifies headers)

**Step 1: Run sysroot task**

Run: `python3 build.py sysroot --arch=arm64`
Expected: Downloads apt packages, outputs "Fixed #3: Renamed sysroot c++ headers to c++.bak" and "Fixed #4: Patched glib-typeof.h with extern C++ wrapper".

**Step 2: Verify sysroot layout**

Run: `ls -la sysroot/usr/include/glib-2.0/glib/glib-typeof.h`
Expected: The file exists.

---

### Task 7: Execute Full Compilation and Packaging

**Files:**
- Create: `D:/OtherProject/mine/flutter_termux/release/flutter_3.44.2_aarch64.deb`

**Step 1: Execute build_all command**

Run: `python3 build.py build_all --arch=arm64`
Expected: Configures and compiles all target modes, packaging the output `.deb` and printing "✓ Validated deb runtime artifacts: dart, dartvm, dartaotruntime" and "[12/12] Build complete!".

**Step 2: Verify build output**

Run: `ls -la release/flutter_3.44.2_aarch64.deb`
Expected: The file exists and is approximately 600-700 MB in size.
