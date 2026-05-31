# GEMINI.md

This file provides guidance to Gemini CLI and Google Antigravity when working with code in this repository.

## What This Is

Cross-compile Flutter SDK for Termux (Android/Bionic ARM64). The build runs on WSL x86-64 and produces ARM64 binaries that run natively on Termux, enabling `flutter run`, `flutter build apk`, and `flutter build linux` inside Termux.

## Build Commands

```bash
# Full build (one command, ~2-4 hours)
python3 build.py build_all --arch=arm64

# Step-by-step
python3 build.py clone                                    # Clone Flutter repo
python3 build.py sync                                     # gclient sync (~30GB)
python3 build.py patch_engine                             # Apply engine.patch
python3 build.py patch_dart                               # Apply dart.patch
python3 build.py patch_skia                               # Apply skia.patch
python3 build.py sysroot --arch=arm64                     # Download & assemble Termux sysroot
python3 build.py configure --arch=arm64 --mode=debug      # GN configure
python3 build.py build --arch=arm64 --mode=debug          # ninja build
python3 build.py build_dart --arch=arm64 --mode=debug     # Build dart binary (NOT built by ninja flutter)
python3 build.py build_impellerc --arch=arm64 --mode=debug  # Shader compiler
python3 build.py build_const_finder --arch=arm64 --mode=debug  # Icon tree shaking

# Android gen_snapshot (for flutter build apk)
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release

# Package as .deb
python3 build.py debuild --arch=arm64
```

## Architecture

```
Windows (edit files)
    │
    ├── build.toml          ← All config (Flutter version, NDK path, jobs, sync paths)
    ├── build.py            ← Main CLI (Fire-based), orchestrates everything
    ├── sysroot.py          ← Downloads Termux apt packages, assembles cross-compile sysroot
    ├── package.py          ← Reads package.yaml, builds data.tar.xz + control.tar.xz → .deb
    ├── package.yaml        ← Declarative: maps build artifacts → deb install paths
    ├── utils.py            ← Arch mapping, output paths, Termux detection
    └── patches/3.44.0/     ← Engine/Dart/Skia patches (version-specific)
    │
    ▼ (sync to WSL via [sync] config in build.toml)
WSL Ubuntu (build)
    │
    ├── flutter/            ← Flutter SDK clone
    │   └── engine/src/     ← Engine source (gclient managed)
    │       └── out/
    │           ├── linux_debug_arm64/     ← Main output (dart, gen_snapshot, libflutter_linux_gtk.so)
    │           ├── linux_release_arm64/   ← Release engine (gen_snapshot, libflutter_linux_gtk.so)
    │           ├── linux_profile_arm64/   ← Profile engine (gen_snapshot, libflutter_linux_gtk.so)
    │           ├── android_release_arm64/ ← Android gen_snapshot (release)
    │           └── android_profile_arm64/ ← Android gen_snapshot (profile)
    │
    ▼ (adb push .deb → dpkg -i on device)
Termux (runtime)
    └── /data/data/com.termux/files/usr/opt/flutter/
```

## CI/CD and Device Lab

| Workflow | Trigger | Runner | Purpose |
|----------|---------|--------|---------|
| `.github/workflows/ci.yml` | PR / push / manual | GitHub-hosted Ubuntu | Python, Shell, PowerShell, YAML, package/docs sanity |
| `.github/workflows/build-deb.yml` | Manual | self-hosted Linux/WSL | Full Flutter Engine build and `.deb` packaging |
| `.github/workflows/device-smoke.yml` | Manual | self-hosted Windows + ADB | Install deb on Termux and run doctor/create/APK/Linux smoke |
| `.github/workflows/release-check.yml` | Release / manual | GitHub-hosted Ubuntu | Verify release asset name, size, and SHA256 |

Supporting scripts:

- `scripts/ci/check_repo.py` — lightweight repository contract checker.
- `scripts/device/run_termux_smoke.ps1` — Windows ADB driver that keeps the tablet awake, pushes the deb/script, and polls the Termux log.
- `scripts/device/termux_smoke.sh` — Termux-side install/doctor/create/build smoke script.
- `scripts/test/gh_e2e_test.sh` — manual GitHub Release clean-install smoke script inside Termux.
- `docs/CI_CD.md` — workflow and runner documentation.

## Key Design Decisions

1. **Linux target builds all three modes** (debug, release, profile). `build_all()` runs configure+build for each mode.

2. **`ninja flutter` does NOT build dart binary**: Must call `build_dart()` separately — it builds `exe.unstripped/dart` and copies to `dart-sdk/bin/dart`.

3. **ARM64-only APK**: android-arm (32-bit BoringSSL shift overflow) and android-x64 (sysroot arch mismatch) are unsupported. Users must use `--target-platform android-arm64`.

4. **Sysroot = Termux apt packages**: `sysroot.py` downloads real `.deb` packages from Termux repos and extracts them into a sysroot directory with a symlink `usr/` → `data/data/com.termux/files/usr`.

5. **`package.yaml` is declarative**: Describes source→output mappings with variable substitution (`$root`, `$any`, `$eng`). The `Package` class evaluates these with `eval()` and generates tar entries.

6. **Windows↔WSL sync**: `build.toml [sync]` section defines paths to copy from Windows mount to WSL native fs before `debuild`, preventing stale-file issues.

7. **`utils.py __MODE__` must be `('debug', 'release', 'profile')`**: `Output.any` picks the first existing build directory. If `release` is first and `linux_release_arm64/` exists, `output.any` selects it — its `product` mode dart-sdk snapshots will break the entire Flutter CLI. Debug must always be first.

## Termux Runtime: post_install.sh Auto-Fixes

`post_install.sh` automatically handles these ARM64 compatibility issues:
- **compileSdkVersion 36→34**: Termux aapt2 (v2.19) cannot load android-35/36 `android.jar`
- **NDK clang wrappers**: Replaces x86_64 clang/clang++ with Termux ARM64 native wrappers (dynamic clang lib version)
- **NDK llvm-objcopy**: Replaces x86_64 `llvm-objcopy`/`llvm-strip` with Termux ARM64 native binaries
- **Shebang fix**: All generated wrapper scripts use `#!/data/data/com.termux/files/usr/bin/sh`
- **Flutter Tools Android-host mapping**: maps Termux Android host lookups to Linux ARM64 artifacts
- **Gradle plugin ABI list**: ARM64-only `FlutterPluginConstants.kt` keeps Flutter 3.44 `PLATFORM_ABI_LIST`

## Termux Runtime: Per-Project Configuration

Each Flutter project needs in `android/gradle.properties`:
```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

And in `android/app/build.gradle.kts`:
```kotlin
android {
    compileSdk = 34  // Must use API 34 (Termux aapt2 limitation)
    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
}
```

## GN Flags That Matter

- `is_termux=true` — Activates Termux-specific BUILD.gn rules (adds `-llog -lm`)
- `is_termux_host` — Auto-detected: `true` when running on Termux, `false` when cross-compiling
- `termux_cross_host=true` — For Android gen_snapshot: builds host tool that runs on ARM64 Termux
- `custom_sysroot` — Points to assembled Termux sysroot
- `is_desktop_linux=false` — Prevents desktop-specific code paths incompatible with Termux
- `use_default_linux_sysroot=false` — Don't use Chromium's bundled sysroot

## Build Environment

- Host: Windows + WSL2 Ubuntu, Ryzen 9950X3D (24 threads allocated)
- NDK: r27d at `/opt/android-ndk-r27d`
- WSL build dir: `/home/iml1s/projects/termux-flutter-3.44-src/`
- Flutter: 3.44.0
- Target: aarch64 (ARM64)
- Test device: `R52Y100VWGM` (Samsung SM-X716B / Android 16)

## Deployment

```powershell
# From Windows (use PowerShell, NOT Git Bash — path mangling)
adb push flutter_3.44.0_aarch64.deb /data/local/tmp/

# In Termux
dpkg -i /data/local/tmp/flutter_3.44.0_aarch64.deb
apt-get install -f
bash $PREFIX/share/flutter/post_install.sh  # Required for APK builds
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

## Upgrading Flutter Version

1. Change `tag` in `build.toml`
2. `python3 build.py clone` → `python3 build.py sync`
3. Patches may need manual rebasing if they fail to apply
4. Run full `build_all`
