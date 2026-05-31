# Flutter 3.44.0 for Termux ARM64

**Flutter 3.44.0 / Dart 3.12 for Android-bionic ARM64 hosts.**

This release updates the Termux Flutter SDK package to Flutter 3.44.0 and fixes the new Dart/Flutter Tools/Gradle assumptions that broke Android-as-host environments.

## Package

| Item | Value |
|------|-------|
| Package | `flutter_3.44.0_aarch64.deb` |
| Size | 666,366,556 bytes (~636 MiB) |
| SHA256 | `b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846` |
| Flutter | 3.44.0 |
| Flutter Tools Dart | 3.12.1 |
| Dart VM | post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`) |
| Target host | Termux / Android bionic / ARM64 |

## Install

```bash
pkg update -y
pkg install -y x11-repo wget openjdk-21
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.0/flutter_3.44.0_aarch64.deb
dpkg -i flutter_3.44.0_aarch64.deb
apt --fix-broken install -y
bash $PREFIX/share/flutter/post_install.sh
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

## Verified

Device smoke on Samsung SM-X716B / Android 16 / ARM64 Termux:

| Command | Result |
|---------|--------|
| `flutter --version` | ✅ Flutter 3.44.0 |
| `dart --version` | ✅ Dart 3.12.1 on `android_arm64` |
| `dartvm --version` | ✅ Dart 3.12.0 on `linux_arm64` |
| `flutter doctor -v` | ✅ completes; unknown channel / no connected device are expected warnings |
| `flutter create --platforms=android,linux` | ✅ |
| `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons` | ✅ ARM64 APK produced |
| `flutter build linux --release` | ✅ ARM64 Linux bundle produced |
| deb artifact validator | ✅ `dart`, `dartvm`, `dartaotruntime` executable |

## Highlights

### Flutter 3.44 / Dart 3.12 update

- Updated package metadata and patches for Flutter 3.44.0.
- Handles Dart 3.10+ tool split by packaging both CLI `dart` and engine `dartvm`/`dartaotruntime`.
- Keeps Flutter CLI on Termux JIT Dart while preserving engine VM tools for snapshots.

### Android/Termux host fixes

Flutter Tools still assumes host OS is macOS/Linux/Windows. On Termux, Dart reports `Platform.operatingSystem == "android"`. This release maps Android host lookups to Linux ARM64 artifacts for:

- font-subset artifacts
- engine artifact host platform lookup
- current host platform detection
- Chrome/device-discovery lookup paths

### APK build fixes

- ARM64-only APK default remains enforced.
- `post_install.sh` now provides Flutter 3.44's `PLATFORM_ABI_LIST` in the ARM64-only Gradle plugin template.
- Stale Flutter Gradle included-build caches are cleared after plugin source changes.
- NDK wrapper setup detects current clang runtime paths and patches CMake host-tag assumptions.

### Linux desktop build fixes

- `flutter build linux` is allowed on Termux host.
- `tool_backend.sh` shebang is rewritten for Termux.
- Projects should add `set(CMAKE_SYSTEM_NAME Linux)` at the top of `linux/CMakeLists.txt`.

## Required per-project Android settings

```properties
# android/gradle.properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

```kotlin
// android/app/build.gradle.kts
android {
    compileSdk = 34
    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
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
