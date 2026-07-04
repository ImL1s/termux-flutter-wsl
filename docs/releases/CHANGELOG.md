# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.44.2-termux] - 2026-07-04

### Added
- Upgraded Flutter SDK cross-compilation target to `3.44.2`.
- Added support for disabling resource optimizations and shrinking during APK builds in smoke tests due to compatibility issues with Termux's native `aapt2`.

### Fixed
- Fixed Dart detection in `post_install.sh` to check for `$SYSTEM_DART` directly, avoiding path shadowing by the SDK's local CLI wrapper.
- Fixed a resource packaging failure (missing `AndroidManifest.xml`) during Termux release APK builds by updating the `termux_smoke.sh` configuration and documentation.


### Added
- GitHub-hosted `CI` workflow for lightweight PR/push checks: Python compile, shell syntax, PowerShell parse, workflow/package/docs sanity, and whitespace guard.
- Manual self-hosted workflows for full `.deb` builds, Windows+ADB tablet smoke tests, and release asset metadata verification.
- `docs/CI_CD.md` documenting workflow boundaries, runner requirements, security model, and local equivalents.
- `scripts/ci/check_repo.py` to keep release/docs/package contracts from silently regressing.
- `scripts/device/run_termux_smoke.ps1` and `scripts/device/termux_smoke.sh` for repeatable Termux tablet smoke testing.

### Changed
- Moved the GitHub Release E2E script from repository root to `scripts/test/gh_e2e_test.sh`.
- Removed the stale `.agent/workflows/build-termux-flutter.md` workflow in favor of maintained GitHub Actions and `docs/CI_CD.md`.
- Updated README/README_EN directory maps and CI/CD guidance to match the organized `scripts/{ci,device,test}` layout.
- Ignored local OMX/OMC runtime state and normalized line-ending rules for workflows, Python, Markdown, shell, and PowerShell files.

## [3.44.0-termux] - 2026-06-01

### Added
- Flutter 3.44.0 / Dart 3.12 package refresh for Termux ARM64.
- Packaged `dartvm` alongside `dart` and `dartaotruntime` so Dart 3.10+ VM/tool split works on Termux.
- Release artifact metadata in docs: size `666,366,556` bytes and SHA256 `b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846`.

### Fixed
- Flutter Tools Android-host crashes by mapping Termux/Android host lookups to Linux ARM64 artifacts.
- Flutter 3.44 Gradle plugin failure by adding `PLATFORM_ABI_LIST` to the ARM64-only `FlutterPluginConstants.kt` post-install template.
- Stale Gradle included-build cache after post-install source rewrites.
- NDK clang runtime path handling for the 3.44 Android gen_snapshot build.

### Verified
- `python3 build.py debuild --arch=arm64` with artifact validator for `dart`, `dartvm`, and `dartaotruntime`.
- On-device smoke on Samsung SM-X716B / Android 16 / Termux: `flutter --version`, `dart --version`, `dartvm --version`, `flutter doctor -v`, `flutter create`, `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons`, and `flutter build linux --release`.

### Known Limitations
- APK target remains ARM64-only.
- Per-project Android settings still need API 34 + `android.aapt2FromMavenOverride`.
- `flutter run` requires ADB pairing/connection inside Termux.

---

## [3.41.5-termux-2] - 2026-04-13

### Fixed
- **`flutter build linux` on device**: `post_install.sh` sed command used `|` delimiter which collided with `||` in Dart source code, silently failing. Changed to `@` delimiter
- **`build.py` sync duplicating directories**: `cp -r` caused nested `scripts/scripts/` dirs. Fixed to use `cp -a {src}/. {dst}/`
- **flutter_tools snapshot not rebuilt**: Added `rm -f flutter_tools.stamp` and `rm -f flutter_tools.snapshot` after patching `build_linux.dart` to force Dart VM to pick up changes

### Added
- `docs/guides/UPGRADE_GUIDE.md` — complete step-by-step guide for upgrading to new Flutter versions
- `.gitignore` patterns for temp scripts (`fix_*.sh`, `test_*.sh`, etc.)
- E2E test script `gh_e2e_test.sh` for automated clean-install verification from GitHub Release

### Verified (E2E from GitHub Release)
- Download .deb → dpkg install → post_install.sh → flutter create → build apk → build linux: **ALL PASS**

---

## [3.41.5-termux] - 2026-03-25

### Added
- Flutter version upgrade: 3.35.0 → 3.41.5 (Dart 3.11.3)
- **Linux release/profile engine builds**: `build_all()` now compiles all three Linux modes (debug, release, profile)
- Full build matrix verified on device (6/6): Linux debug/release/profile + APK debug/release/profile

### Fixed
- **`flutter build linux` (release/profile) failure**: `build_all()` was only building debug mode engine for Linux, leaving `linux_release_arm64/` and `linux_profile_arm64/` empty in the deb package
- **`utils.py __MODE__` ordering bug**: Original order `('release', 'debug', 'profile')` caused `Output.any` to select release (product mode) dart-sdk snapshots when release directory exists, breaking the entire Flutter CLI. Fixed to `('debug', 'release', 'profile')`

### Technical Details
- Build output now includes 5 directories: `linux_debug_arm64/`, `linux_release_arm64/`, `linux_profile_arm64/`, `android_release_arm64/`, `android_profile_arm64/`
- `build_all()` expanded from 8 to 12 steps to include Linux release/profile configure+build
- Deb package size increased from ~541MB to ~662MB due to additional engine artifacts

---

## [3.35.0-termux] - 2026-01-07

### Added
- Full Flutter 3.35.0 support for Termux ARM64
- `flutter build apk` support (ARM64 only, debug/profile/release modes)
- `flutter build linux` support
- `flutter run` with Hot Reload support (all modes: debug/profile/release)
- Linux desktop app support via Termux X11
- One-command installation script (`install_flutter_complete.sh`)
- Automatic NDK clang wrapper configuration
- Android SDK integration with API 34
- VM snapshots for Linux profile mode

### Fixed
- libc++_shared.so symlink issue (was pointing to linker script instead of ELF)
- NDK clang wrapper detection for multiple NDK versions
- Dependency conflicts during package upgrades (openjdk-17 vs openjdk-21)
- Missing Android build tools (d8, dx, aidl, apksigner)
- libatomic.a stubs for CMake compatibility
- **Linux profile mode crash** (`_NetworkProfiling` type not found in dart.io)
  - Root cause: `PropagateIfError()` crashes when no Dart stack frames
  - Fix: Made network profiling initialization optional in `dart_runtime_hooks.cc`
- **Gradle auto-downloading new NDK versions** causing build failures
  - Fix: Auto-set `ANDROID_NDK_HOME` in profile script to use pre-configured NDK

### Known Limitations
- APK builds only support ARM64 (android-arm64-v8a)
- ARMv7 (android-arm) not supported due to BoringSSL 32-bit issues
- x86/x64 Android targets not supported

### Technical Details
- Cross-compiled from x86_64 Linux (WSL) to ARM64 Bionic
- Uses NDK r27d with API level 35
- Patches applied to Flutter Engine, Dart VM, and Skia
- TLS alignment fixed for Bionic linker compatibility

---

## Version Naming Convention

`{flutter_version}-termux` - e.g., `3.35.0-termux`

- `flutter_version`: Upstream Flutter SDK version
- `termux`: Indicates this is a Termux-compatible build

## Upgrading

See [UPGRADE_GUIDE.md](../guides/UPGRADE_GUIDE.md) for upgrade instructions.
