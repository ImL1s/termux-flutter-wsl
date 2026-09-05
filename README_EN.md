<p align="center">
  <img src="assets/banner.png" alt="termux-flutter-wsl" width="800"/>
</p>

<h1 align="center">Flutter for Termux ARM64</h1>

<p align="center">
  <strong>A packaged Flutter SDK for Android/Termux ARM64 with APK builds, Linux desktop builds, and hot reload.</strong>
</p>

<p align="center">
  <code>flutter build apk</code> ✅ | <code>flutter build linux</code> ✅ | <code>flutter run</code> + Hot Reload ✅ | installable <code>.deb</code> ✅
</p>

<p align="center">
  <a href="README.md">中文</a> | <strong>English</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Flutter-3.44.9-02569B?logo=flutter" alt="Flutter Version"/>
  <img src="https://img.shields.io/badge/Dart-3.12.2-0175C2?logo=dart" alt="Dart Version"/>
  <img src="https://img.shields.io/badge/Target-aarch64-green" alt="Target"/>
  <a href="https://github.com/ImL1s/termux-flutter-wsl/actions/workflows/ci.yml"><img src="https://github.com/ImL1s/termux-flutter-wsl/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <img src="https://img.shields.io/badge/License-GPL--3.0-blue" alt="License"/>
</p>

<p align="center">
  <em>🍴 Forked from <a href="https://github.com/mumumusuc/termux-flutter">mumumusuc/termux-flutter</a></em>
</p>

<p align="center">
  <img src="assets/demo_hot_reload.jpg" alt="Flutter running on Termux with Hot Reload" width="600"/>
</p>

---

## Quick navigation

- [What this is](#what-this-is)
- [Current release and validation](#current-release-and-validation)
- [Quick install](#quick-install)
- [Create a project and build an APK](#create-a-project-and-build-an-apk)
- [Linux desktop / Termux:X11](#linux-desktop--termuxx11)
- [Build the `.deb` yourself](#build-the-deb-yourself)
- [CI/CD and release validation](#cicd-and-release-validation)
- [Documentation map](#documentation-map)
- [Limitations and notes](#limitations-and-notes)

## What this is

Flutter's ARM64 target support does not mean the official SDK can be used as an **Android/Termux host** SDK. Termux uses Android bionic, Android linker paths, and a different toolchain layout; the official Linux SDK assumes a glibc host.

This repository packages a Flutter SDK for Termux ARM64:

- Cross-compiles Flutter Engine, Dart runtime, and required host tools from WSL/Linux.
- Assembles an installable `flutter_3.44.9-1_aarch64.deb` package for Termux.
- Runs `post_install.sh` to patch Flutter Tools, the Gradle plugin, NDK/build-tools wrappers, Android SDK constraints, and Termux shebangs.
- Enables `flutter doctor`, `flutter create`, `flutter build apk`, `flutter build linux`, and hot reload through Termux:X11.

## Current release and validation

| Item | Value |
| --- | --- |
| Flutter | `3.44.9` |
| Dart | `3.12.2` |
| Architecture | `aarch64` / `arm64-v8a` |
| Release asset | [`flutter_3.44.9-1_aarch64.deb`](https://github.com/ImL1s/termux-flutter-wsl/releases/tag/v3.44.9-termux-1) |
| Size | `178,482,192` bytes (~170 MiB) |
| SHA256 | `d8fec711e71e471566c6bf1f0cad5be510cdda133cdafb829ec594ab3aff62ae` |

### Device smoke test

Last full device validation: **2026-08-23**, Samsung SM-X716B / Android 16 / Termux.

| Check | Result |
| --- | --- |
| `dpkg -i` + `post_install.sh` | ✅ |
| `flutter --version` / `dart --version` / `dartvm --version` | ✅ |
| `flutter doctor -v` | ✅ expected channel/device warnings only |
| `flutter create --platforms=android,linux` | ✅ |
| `flutter build apk --release --target-platform android-arm64` | ✅ |
| `flutter build linux --release` | ✅ |

## Quick install

### Requirements

| Item | Requirement |
| --- | --- |
| Device | Android ARM64 / aarch64 |
| Android | Android 11+ recommended |
| App | F-Droid Termux; Termux:X11 for Linux GUI |
| Storage | At least 8GB free space recommended |

### One-click install (recommended)

```bash
pkg update && pkg upgrade -y
pkg install -y curl
curl -L https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o install_flutter_complete.sh
bash install_flutter_complete.sh
```

### Manual release `.deb` install

```bash
pkg update && pkg install -y wget
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux-1/flutter_3.44.9-1_aarch64.deb
sha256sum flutter_3.44.9-1_aarch64.deb

dpkg -i flutter_3.44.9-1_aarch64.deb
apt --fix-broken install -y
bash $PREFIX/share/flutter/post_install.sh
source ~/.bashrc
flutter --version
```

Do not install the file if its SHA256 differs from the value in the release table above.

## Create a project and build an APK

This project supports two different compilation modes:

### Mode A: Verified Termux Local APK Build (Recommended Default)
This is the most stable path for local developer testing, side-loading, and fast iterations.

1. Configure the project to override AAPT2, disable resource optimizations, and disable shrinking:
```properties
# android/gradle.properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
android.enableResourceOptimizations=false
shrink=false
```

2. Pin the compilation SDK target to API 34 and explicitly disable code shrinking:
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

3. Run the release build command (bypassing JIT Dart icon tree-shaking limits):
```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

---

### Mode B: Experimental Google Play Publish Toolchain (API 35+ / AAB)
This mode is **experimental**. Google Play requires new uploads to target Android 15 (API 35) or newer, which causes the default Termux `aapt2` package to crash. This mode requires installing native static ARM64 Android Build-Tools (see [AAPT2_RELEASE_BUILD_BUG_ANALYSIS.md](docs/guides/AAPT2_RELEASE_BUILD_BUG_ANALYSIS.md) for details).

> `post_install.sh` patches Flutter Tools defaults for Termux, but keeping the project-level Gradle settings above makes different templates and plugins more predictable.

## Linux desktop / Termux:X11

```bash
pkg install -y x11-repo termux-x11-nightly
termux-x11 :0 &
export DISPLAY=:0

flutter create --platforms=linux linux_demo
cd linux_demo
flutter run -d linux
```

You can also build only:

```bash
flutter build linux --release
```

## Build the `.deb` yourself

A full build requires WSL/Linux, Android NDK, depot_tools, a Flutter Engine checkout, and usually takes multiple hours.

```bash
python3 build.py build_all --arch=arm64
```

Common step-by-step commands:

```bash
python3 build.py clone
python3 build.py sync
python3 build.py patch_engine && python3 build.py patch_dart && python3 build.py patch_skia
python3 build.py sysroot --arch=arm64
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug
python3 build.py build_dart --arch=arm64 --mode=debug
python3 build.py debuild --arch=arm64
```

See [`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md) for the full build process, mode matrix, and troubleshooting.

## CI/CD and release validation

| Workflow | Trigger | Runner | Purpose |
| --- | --- | --- | --- |
| `CI` | PR / push / manual | GitHub-hosted Ubuntu | Python, Shell, PowerShell, YAML, and package/docs contract sanity |
| `Build deb` | Manual | self-hosted Linux/WSL | Full Flutter Engine build, `.deb` packaging, optional release publishing |
| `Device smoke` | Manual | self-hosted Windows + ADB | Install the deb in Termux, then run doctor/create/APK/Linux smoke tests |
| `Release check` | Release / manual | GitHub-hosted Ubuntu | Verify release asset name, size, and SHA256 |

See [`docs/CI_CD.md`](docs/CI_CD.md) for runner requirements and local equivalents.

> Device smoke requires the tablet to stay awake and unlocked; secure lock screens block ADB text injection into Termux.

## Project layout

```text
termux-flutter-wsl/
├── .github/workflows/        # GitHub-hosted CI + self-hosted build/device gates
├── docs/                     # Long-form documentation, guides, and release notes
│   ├── README.md             # Documentation index
│   ├── CI_CD.md              # CI/CD, runner, and device-lab guide
│   ├── guides/               # Install, build, and upgrade guides
│   └── releases/             # Changelog and release notes
├── scripts/
│   ├── ci/                   # Lightweight repository contract checks
│   ├── device/               # ADB → Termux smoke automation
│   ├── install/              # Termux install and post-install patches
│   └── test/                 # Release / Termux E2E smoke scripts
├── patches/3.44.9/           # Flutter Engine / Dart / Skia patches
├── build.py                  # Main build CLI
├── build.toml                # Version, NDK, sysroot, and patch configuration
├── package.yaml              # .deb artifact mapping
└── install_flutter_complete.sh
```

## Documentation map

| Document | Purpose |
| --- | --- |
| [`docs/README.md`](docs/README.md) | Full documentation index |
| [`docs/guides/INSTALL_GUIDE.md`](docs/guides/INSTALL_GUIDE.md) | Install flow and Termux runtime prerequisites |
| [`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md) | WSL/Engine build, packaging, and troubleshooting |
| [`docs/guides/UPGRADE_GUIDE.md`](docs/guides/UPGRADE_GUIDE.md) | Checklist for upgrading to a new Flutter release |
| [`docs/CI_CD.md`](docs/CI_CD.md) | CI/CD, self-hosted runners, and device smoke |
| [`docs/releases/CHANGELOG.md`](docs/releases/CHANGELOG.md) | Version history |
| [`docs/releases/RELEASE_NOTES.md`](docs/releases/RELEASE_NOTES.md) | Current GitHub release body |

## Limitations and notes

- The supported target is **ARM64 / arm64-v8a**. 32-bit ARM and x64 Android gen_snapshot builds are out of scope.
- Android APK builds should use `compileSdk = 34` / `targetSdk = 34` to avoid Termux `aapt2` compatibility problems with newer `android.jar` files.
- `flutter doctor` reports custom channel / upstream remote warnings for the packaged SDK. These are expected and do not mean the smoke test failed.
- `ninja flutter` does not produce a usable `dart` binary; source builds must run `build_dart()` separately.
- The release `.deb` is large, so install and first `post_install.sh` runs can take time.

## Troubleshooting entry points

- APK build / `aapt2` / compileSdk issues: [`docs/guides/INSTALL_GUIDE.md`](docs/guides/INSTALL_GUIDE.md)
- Engine / Dart / Skia patch or WSL build issues: [`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md)
- CI/CD, release assets, and device smoke: [`docs/CI_CD.md`](docs/CI_CD.md)
- Upgrading Flutter versions: [`docs/guides/UPGRADE_GUIDE.md`](docs/guides/UPGRADE_GUIDE.md)

## Acknowledgements

- Original project: [`mumumusuc/termux-flutter`](https://github.com/mumumusuc/termux-flutter)
- Termux community for the Android userspace, packages, and X11 ecosystem
- Flutter / Dart / Skia / Chromium Engine upstreams

## License

This project is licensed under [GPL-3.0](LICENSE).
