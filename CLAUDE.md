# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Flutter Termux 專案指南

Cross-compile Flutter SDK to run natively on Termux (Android/Bionic ARM64), enabling:
- `flutter run -d linux` - Run Linux desktop apps in Termux X11
- `flutter build apk` - Build Android APKs directly in Termux
- Hot Reload support in Termux environment

## Build Commands

```bash
# One-command full build (recommended)
python3 build.py build_all --arch=arm64

# Step-by-step build
python3 build.py clone                           # Clone Flutter repo
python3 build.py sync                            # Sync dependencies (~30GB)
python3 build.py patch_engine                    # Apply Termux patches
python3 build.py sysroot --arch=arm64            # Build sysroot
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug
python3 build.py build_dart --arch=arm64 --mode=debug
python3 build.py build_impellerc --arch=arm64 --mode=debug
python3 build.py build_const_finder --arch=arm64 --mode=debug
python3 build.py configure --arch=arm64 --mode=release    # Linux release engine
python3 build.py build --arch=arm64 --mode=release
python3 build.py configure --arch=arm64 --mode=profile    # Linux profile engine
python3 build.py build --arch=arm64 --mode=profile

# Android gen_snapshot (for flutter build apk)
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release

# Package deb
python3 build.py debuild --arch=arm64
```

## Key Files

| File | Purpose |
|------|---------|
| `build.py` | Main build script with all build commands (uses Fire CLI) |
| `build.toml` | Build configuration (Flutter version, NDK path, jobs) |
| `package.yaml` | Deb package definition and artifact mappings |
| `sysroot.py` | Termux sysroot assembly from apt packages |
| `package.py` | Deb packaging logic |
| `utils.py` | Build utilities and path helpers |
| `patches/{version}/*.patch` | Version-specific Engine/Dart/Skia patches |
| `scripts/install/post_install.sh` | Post-installation setup for APK builds |
| `scripts/build/` | Build helper scripts (profile, gen_snapshot, etc.) |
| `scripts/ci/check_repo.py` | Lightweight repository contract checks for PR CI |
| `scripts/device/` | Windows ADB driver + Termux smoke script |
| `scripts/test/gh_e2e_test.sh` | GitHub Release clean-install E2E smoke script |
| `scripts/setup/` | WSL/NDK/Gradle environment setup scripts |
| `scripts/fix/` | Workaround scripts (aapt2, gradle, SSH) |
| `.github/workflows/` | GitHub-hosted CI and manual self-hosted build/device gates |
| `docs/CI_CD.md` | CI/CD and device-lab operating guide |
| `install_flutter_complete.sh` | One-command Termux installation script |
| `CHANGELOG.md` | Version history and release notes |
| `BUILD_GUIDE.md` | Detailed build guide and troubleshooting |

## Project Structure

```
flutter_termux/
├── build.py                    # Main build script
├── build.toml                  # Build configuration
├── install_flutter_complete.sh # Termux installation script
├── patches/
│   └── 3.44.0/                 # Version-specific patches
│       ├── engine.patch
│       ├── dart.patch
│       └── skia.patch
├── scripts/
│   ├── build/                  # Build helper scripts
│   ├── ci/                     # PR sanity checks
│   ├── device/                 # ADB/Termux smoke automation
│   ├── setup/                  # Environment setup scripts
│   ├── install/                # Installation scripts
│   │   └── post_install.sh
│   ├── fix/                    # Fix/workaround scripts
│   └── test/                   # Test scripts
└── .github/workflows/          # CI/CD (requires self-hosted runner)
```

## CI/CD Notes

- `.github/workflows/ci.yml` is the only workflow that runs automatically on PRs; it uses GitHub-hosted Ubuntu and must stay lightweight.
- `.github/workflows/build-deb.yml` and `.github/workflows/device-smoke.yml` are manual self-hosted workflows because the full engine build is multi-hour and the device smoke needs an attached ADB tablet.
- `.github/workflows/release-check.yml` verifies the public release asset metadata and SHA256.
- Keep the release/device contracts in sync with `scripts/ci/check_repo.py` and `docs/CI_CD.md`.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                   WSL Build Environment                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Dart SDK    │  │ Flutter     │  │ gen_snapshot            │  │
│  │ (ARM64)     │  │ Engine      │  │ ├─ Linux ARM64          │  │
│  │             │  │ (ARM64)     │  │ └─ Android ARM64        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                         │                                        │
│                    [Package deb]                                 │
└─────────────────────────┼────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Termux Runtime Environment                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Our deb     │  │ Android SDK │  │ ARM64 NDK               │  │
│  │ (compiled)  │  │ (download)  │  │ (download)              │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                         │                                        │
│              [post_install.sh integration]                       │
│                         ▼                                        │
│  flutter doctor ✅  flutter build apk ✅  flutter run ✅         │
└─────────────────────────────────────────────────────────────────┘
```

## Build Artifacts Location

```
flutter/engine/src/out/
├── linux_debug_arm64/
│   ├── dart-sdk/bin/dart          # Dart binary
│   ├── gen_snapshot               # Linux gen_snapshot (release mode VM)
│   └── libflutter_linux_gtk.so    # Linux GTK library (~106MB)
├── linux_release_arm64/
│   ├── gen_snapshot               # Release gen_snapshot
│   └── libflutter_linux_gtk.so    # Release GTK library
├── linux_profile_arm64/
│   ├── gen_snapshot               # Profile gen_snapshot
│   └── libflutter_linux_gtk.so    # Profile GTK library
├── android_release_arm64/
│   └── clang_arm64/gen_snapshot   # Android release gen_snapshot
└── android_profile_arm64/
    └── exe.stripped/gen_snapshot  # Android profile gen_snapshot
```

## Ninja Build Targets

In `build.py` `build()` method:
- `flutter` - Core Flutter engine
- `flutter/shell/platform/linux:flutter_gtk` - Linux desktop support (libflutter_linux_gtk.so)

**Important**: `flutter_gtk` target must be enabled, otherwise `flutter build linux` fails.

## Internal Patterns

- **`@utils.record` / `@utils.recordm`**: Decorators that auto-log all method calls with args. Set `NO_RECORD=1` to disable.
- **`Build.sync()`**: Detects Windows vs WSL via `platform.system()`. On Windows, wraps `cp` in `wsl -e bash -c`; on WSL, runs directly.
- **`Package.__format__()`**: Uses `string.Template.safe_substitute()` for `$variable` expansion in `package.yaml`.
- **`package.yaml` `define` blocks**: Use `eval()` with globals (`root`, `arch`, `output`, `version`) — never put untrusted strings here.

## Known Limitations

1. **APK only supports ARM64**: android-arm and android-x64 gen_snapshot cannot be cross-compiled (BoringSSL 32-bit issues, sysroot incompatibility)
2. **`utils.py __MODE__` must be `('debug', 'release', 'profile')`**: debug first! `Output.any` picks the first existing directory. If release comes first, product mode dart-sdk snapshots break the entire Flutter CLI.
3. See `BUILD_GUIDE.md` for detailed troubleshooting

## Common Issues

### NDK Clang Wrapper Not Found
**Error**: `CMAKE_C_COMPILER is not a full path to an existing compiler tool`

**Cause**: Gradle downloaded a new NDK version not configured by `post_install.sh`.

**Prevention**: The profile script auto-sets `ANDROID_NDK_HOME` to use pre-configured NDK.

**Manual Fix** (if needed): Re-run post_install to configure all NDKs:
```bash
bash $PREFIX/share/flutter/post_install.sh
```

### libflutter_linux_gtk.so Not Found
**Error**: `Unsupported file type "notFound" for libflutter_linux_gtk.so`

**Cause**: The deb package may be missing the Linux GTK library.

**Fix**: Rebuild with `flutter_gtk` target enabled in `build.py`.

## WSL Build Environment

```
Host: Windows + WSL2 Ubuntu
Build dir: /home/iml1s/projects/termux-flutter-3.44-src/
Engine src: /home/iml1s/projects/termux-flutter-3.44-src/flutter/engine/src/
Output: /home/iml1s/projects/termux-flutter-3.44-src/flutter/engine/src/out/
Recommended jobs: -j24
```

### Windows PATH Pollution Fix

When calling `wsl` from Windows, Windows PATH leaks into WSL causing shell errors.

1. Create `/etc/wsl.conf` in WSL:
```ini
[interop]
appendWindowsPath = false
```

2. Create vpython3 wrapper in depot_tools:
```bash
echo '#!/bin/bash
exec python3 "$@"' > depot_tools/vpython3
chmod +x depot_tools/vpython3
```

3. Use PowerShell (not Git Bash) for WSL commands to avoid path conversion issues

## Deployment to Termux

**Important**: Use PowerShell for adb push (Git Bash mangles paths):

```powershell
# Transfer deb to device
powershell -Command "adb push 'flutter_3.44.0_aarch64.deb' '/data/local/tmp/'"

# Install in Termux
pkg install x11-repo
dpkg -i /data/local/tmp/flutter_3.44.0_aarch64.deb
apt-get install -f
bash $PREFIX/share/flutter/post_install.sh  # Required for APK builds!

# Test
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

## Test Device

- Device ID: `R52Y100VWGM`
- Model: Samsung SM-X716B / Android 16
- ADB: `adb -s R52Y100VWGM shell`

## Version Info

- Flutter: 3.44.0
- Flutter Tools Dart: 3.12.1
- Dart VM: post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`)
- Target: aarch64 (ARM64)

## Verified Feature Status (2026-06-01)

| Feature | Status | Requirements |
|---------|--------|--------------|
| `flutter doctor` | ✅ | deb install only |
| `flutter create` | ✅ | deb install only |
| `flutter build linux --debug` | ✅ | gtk3, x11-repo |
| `flutter build linux --release` | ✅ | gtk3, x11-repo |
| `flutter build linux --profile` | ✅ | gtk3, x11-repo |
| `flutter build apk --debug` | ✅ | post_install.sh + project config |
| `flutter build apk --profile` | ✅ | post_install.sh + project config |
| `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons` | ✅ | post_install.sh + project config |
| `flutter run -d linux` | ✅ | termux-x11-nightly, DISPLAY=:0 |
| `flutter run --debug` | ✅ | Wireless debugging enabled |
| `flutter run --profile` | ✅ | Wireless debugging enabled |
| `flutter run --release` | ✅ | Wireless debugging enabled |
| Hot Reload (r) | ✅ | During `flutter run --debug` |
| Hot Restart (R) | ✅ | During `flutter run --debug` |
| DevTools | ✅ | During `flutter run` |
| APK install | ✅ | Use `adb install` from PC |

### Linux Desktop Run Status
| Mode | Status | Notes |
|------|--------|-------|
| `flutter run -d linux --debug` | ✅ | Hot Reload/Restart/DevTools work |
| `flutter run -d linux --profile` | ✅ | Requires Termux X11 running |
| `flutter run -d linux --release` | ✅ | Works correctly |

## Flutter Run on Android (Wireless Debugging)

To use `flutter run` on Termux:

1. Enable Wireless Debugging on your device:
   - Settings → Developer Options → Wireless Debugging → ON

2. Pair device (one-time):
   ```bash
   adb pair 127.0.0.1:<PAIR_PORT> <PAIRING_CODE>
   ```

3. Connect:
   ```bash
   adb connect 127.0.0.1:<CONNECT_PORT>
   ```

4. Run:
   ```bash
   flutter run -d <device_id>
   ```

**Note:** The profile script auto-sets `ANDROID_NDK_HOME` to prevent Gradle from downloading new NDK versions.

## APK Build Project Configuration

Each Flutter project needs in `android/app/build.gradle.kts`:
```kotlin
android {
    compileSdk = 34  // Must use API 34 (aapt2 bug with 35/36)
    defaultConfig {
        targetSdk = 34
        ndk {
            abiFilters += listOf("arm64-v8a")  // ARM64 only
        }
    }
}
```

In `android/gradle.properties`:
```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

## Upgrading Flutter Version

1. Update `tag` in `build.toml`
2. Run sync and apply patches:
```bash
python3 build.py clone
python3 build.py sync
python3 build.py patch_engine  # May need patch updates if fails
```
3. Run full build
