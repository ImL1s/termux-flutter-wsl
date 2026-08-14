# Flutter 3.44.2 for Termux ARM64

**Flutter 3.44.2 / Dart 3.12 for Android-bionic ARM64 hosts.**

This release updates the Termux Flutter SDK package to Flutter 3.44.2. It resolves an NDK resource compilation issue with `aapt2` during release builds and fixes system Dart VM JIT engine mapping logic.

## Package

| Item | Value |
|------|-------|
| Package | `flutter_3.44.2_aarch64.deb` |
| Size | 177,161,976 bytes (~169 MiB) |
| SHA256 | `f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e` |
| Flutter | 3.44.2 |
| Flutter Tools Dart | 3.12.1 |
| Dart VM | post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`) |
| Target host | Termux / Android bionic / ARM64 |

## Install

```bash
pkg update -y
pkg install -y x11-repo wget openjdk-21
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2-termux/flutter_3.44.2_aarch64.deb
dpkg -i flutter_3.44.2_aarch64.deb
apt --fix-broken install -y
bash $PREFIX/share/flutter/post_install.sh
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

## Verified

Device smoke on Samsung SM-X716B / Android 16 / ARM64 Termux:

| Command | Result |
|---------|--------|
| `flutter --version` | ✅ Flutter 3.44.2 |
| `dart --version` | ✅ Dart 3.12.1 on `android_arm64` |
| `dartvm --version` | ✅ Dart 3.12.1 on `linux_arm64` |
| `flutter doctor -v` | ✅ completes; unknown channel / no connected device are expected warnings |
| `flutter create --platforms=android,linux` | ✅ |
| `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons` | ✅ ARM64 APK produced |
| `flutter build linux --release` | ✅ ARM64 Linux bundle produced |
| deb artifact validator | ✅ `dart`, `dartvm`, `dartaotruntime` executable |

## Highlights

### Flutter 3.44.2 update

- Updated package metadata, NDK configurations, and patches to target Flutter 3.44.2.
- Keeps Flutter CLI on Termux JIT Dart while preserving engine VM tools for snapshots.

### APK build resource fixes

Building release APKs on device with native Termux `aapt2` can result in empty resources or a missing `AndroidManifest.xml` due to incompatibilities during the R8 shrinking/resource optimization tasks. This release:
- Updates the automated `termux_smoke.sh` script to disable resource optimizations and R8 resource shrinking.
- Updates developer instructions for per-project configurations.

### Post-install Dart VM detection fix

- Fixed the `post_install.sh` system Dart VM replacement logic to directly inspect the target path (`/data/data/com.termux/files/usr/bin/dart`) rather than using `command -v`, preventing path shadowing issues.

### Technical Details

- Build output directories: `linux_debug_arm64/`, `linux_release_arm64/`, `linux_profile_arm64/`, `android_release_arm64/`, `android_profile_arm64/`
- Deb package size is ~169MB.

## Required per-project Android settings

To build APKs successfully on Termux, you must configure the following project properties:

```properties
# android/gradle.properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
android.enableResourceOptimizations=false
```

```kotlin
// android/app/build.gradle.kts
android {
    compileSdk = 34
    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}
```

Build with:

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

## Known limitations

- Android APK targets are ARM64-only (`android-arm64` / `arm64-v8a`).
- `flutter run` for Android requires ADB pairing/connection from inside Termux.
- Some Flutter doctor warnings about unknown channel/source are expected for this repackaged SDK.
- Termux aapt2 currently requires projects to compile against API 34 even though Android SDK Platform 36 is installed for Flutter metadata compatibility.

## Previous releases

### v3.41.5 (2026-04-13)

- Flutter SDK upgraded to 3.41.5 (Dart 3.11.3).
- Added `flutter build linux` support.
- Fixed post-install sed delimiter and flutter_tools snapshot invalidation.

### v3.35.0 (2026-01-07)

- First public release.
- APK build and hot reload support for ARM64 Termux.
