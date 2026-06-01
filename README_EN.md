<p align="center">
  <img src="assets/banner.png" alt="termux-flutter-wsl" width="800"/>
</p>

<h1 align="center">Flutter for Termux ARM64</h1>

<p align="center">
  <strong>🚀 World's first complete Flutter development environment on mobile devices</strong>
</p>

<p align="center">
  <code>flutter build apk</code> ✅ | <code>flutter run</code> + Hot Reload ✅ | Native Speed ✅ | One-Click Install ✅
</p>

<p align="center">
  <a href="README.md">中文</a> | <strong>English</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Flutter-3.44.0-02569B?logo=flutter" alt="Flutter Version"/>
  <img src="https://img.shields.io/badge/Platform-ARM64-green" alt="Platform"/>
  <img src="https://img.shields.io/badge/Build-WSL-0078D6?logo=windows" alt="WSL"/>
  <a href="https://github.com/ImL1s/termux-flutter-wsl/actions/workflows/ci.yml"><img src="https://github.com/ImL1s/termux-flutter-wsl/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <img src="https://img.shields.io/badge/build_apk-✓-success" alt="Build APK"/>
  <img src="https://img.shields.io/badge/hot_reload-✓-success" alt="Hot Reload"/>
  <img src="https://img.shields.io/badge/License-GPL--3.0-blue" alt="License"/>
</p>

<p align="center">
  <em>🍴 Forked from <a href="https://github.com/mumumusuc/termux-flutter">mumumusuc/termux-flutter</a></em>
</p>

<p align="center">
  <img src="assets/demo_hot_reload.jpg" alt="Flutter running on Termux with Hot Reload" width="600"/>
</p>

<p align="center">
  <em>📱 Flutter App running on Termux with Hot Reload support!</em>
</p>

---

## ❓ Why Does This Project Exist?

**Flutter "supports arm64" ≠ "you can develop on any arm64 device"**

| What Flutter means by arm64 support | Reality |
|-------------------------------------|---------|
| arm64 **Target** | ✅ Your app can run on arm64 devices |
| arm64 **Host** | ⚠️ Only macOS (Apple Silicon), Linux (glibc) |
| Android/Termux as Host | ❌ **Never supported** |

### Why isn't Termux supported?

Flutter assumes a Linux host environment with:
- glibc (standard C library)
- Full POSIX compliance
- Standard toolchain

But **Termux is**:
- **bionic libc** (Android's C library, not glibc)
- Android sandbox + SELinux restrictions
- Different dynamic linker (`/system/bin/linker64`)

For Flutter officially: **This is not an OS they support.**

### What did we do?

```
Flutter SDK engine binaries:
bin/cache/artifacts/engine/
    ├── darwin-arm64/     ← for macOS
    ├── linux-arm64/      ← for Linux (glibc)
    └── android-arm64/    ← This is TARGET, not HOST!

❌ No Termux/bionic host version exists
```

**We cross-compiled the entire Flutter Engine from source**, specifically for Termux (Android/bionic):

- Fixed TLS alignment issues (bionic linker requirement)
- Fixed dynamic linker path
- Compiled host-side tools (dart, gen_snapshot, impellerc)
- Enabled Hot Reload and APK builds to run natively on Termux

> **In one sentence: Flutter officially supports arm64 as a target platform, but never supported Android as a development host. We filled that gap.**

---

## 📖 Introduction

This project is based on [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) and provides a complete solution for cross-compiling the Flutter Engine for Termux on a **WSL (Windows Subsystem for Linux)** environment.

### 🆚 Differences from Upstream

| Feature | Upstream | This Project |
|---|---|---|
| Build Env | Linux / Termux Native | **WSL (Windows)** |
| Flutter Ver | 3.29.2 | **3.44.0** |
| Android Compat | ❌ No Android 14+ | ✅ **Android 16 Tested** |
| Fixes | - | **`-llog`, `-lm` deps** |
| Docs | Basic | **Full Guide (EN/ZH)** |

> ✅ **Verified**: Successfully ran Flutter app on Android 16 device!

### 🏆 World's First Complete Flutter Dev Environment

This project is **the world's first** to achieve a **complete Flutter development workflow** on ARM64 Termux!

#### 🎯 What Can We Do?

| Feature | This Project | Other Solutions |
|---------|--------------|-----------------|
| `flutter build apk` | ✅ **Native support** | ❌ Cannot achieve |
| `flutter run` + Hot Reload | ✅ **Full support** | ❌ Cannot achieve |
| Performance | ✅ **Native speed** | ⚠️ x86 emulation, 3-5x slower |
| Installation | ✅ **One-click** | ⚠️ Complex setup |
| APK output | ✅ **Native ARM64 APK** | ⚠️ proot adds overhead |

#### 📊 Full Feature Comparison

| Project | build apk | flutter run | hot reload | Native | Status |
|---------|-----------|-------------|------------|--------|--------|
| **This Project** | ✅ | ✅ | ✅ | ✅ | ✅ Active |
| Flutter Official | ❌ | ❌ | ❌ | ❌ | [Issue #177936](https://github.com/flutter/flutter/issues/177936): Not supported |
| [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) | ❌ | ⚠️ linux only | ❌ | ✅ | ⚠️ Stale |
| [Hax4us/flutter_in_termux](https://github.com/Hax4us/flutter_in_termux) | ⚠️ proot | ⚠️ proot | ❌ | ❌ x86 emu | ⚠️ Stale |
| [bdloser404/Fluttermux](https://github.com/bdloser404/Fluttermux) | ❌ | ❌ | ❌ | ❌ | ❌ Broken |

> 💡 If you find another project that natively supports this, please [open an Issue](https://github.com/ImL1s/termux-flutter-wsl/issues) to let us know!

#### 🚀 What Does This Mean?

**Complete Flutter development on your phone/tablet:**

```
📱 Your Android Device
    ↓
🖥️ Termux Terminal
    ↓
✍️ Write code (vim/nano/code-server)
    ↓
🔥 flutter run → See changes instantly (Hot Reload!)
    ↓
📦 flutter build apk → Get installable APK
    ↓
📲 Install directly on device
```

**No computer, no emulator, no cloud service needed!**

### 📊 v3.44.0 Verification Status (2026-06-01)

| Item | Result | Environment / Notes |
|------|--------|---------------------|
| `flutter --version` | ✅ | Flutter 3.44.0, Tools Dart 3.12.1 |
| `dart --version` | ✅ | Termux JIT Dart 3.12.1 (`android_arm64`) |
| `dartvm --version` | ✅ | post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`) |
| `flutter doctor -v` | ✅ | Android SDK / Java 21 / network resources OK; unknown channel and no ADB device are expected warnings unless ADB is connected |
| `flutter create` | ✅ | Smoke project with `--platforms=android,linux` |
| `flutter build apk --release` | ✅ | Verified on Samsung SM-X716B / Android 16 / Termux; ARM64 APK built successfully |
| `flutter build linux --release` | ✅ | Produces ARM64 ELF and `libflutter_linux_gtk.so` |
| `.deb` artifact validation | ✅ | `dart`, `dartvm`, and `dartaotruntime` executable checks passed |

**Current package**: `flutter_3.44.0_aarch64.deb`<br>
**Size**: 666,366,556 bytes (~636 MiB)<br>
**SHA256**: `b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846`

> Flutter 3.44 / Dart 3.12 is the official May 2026 release train. This project fills the missing Android/Termux host support.

### ✨ Features

- 🪟 Cross-compile Flutter Engine / Dart / toolchain from Windows WSL
- 🧩 Android/bionic host fixes: TLS alignment, dynamic linker, `-llog` / `-lm`, NDK clang runtime
- 🎯 Defaults to `android-arm64` only to avoid unsupported arm/x64 `gen_snapshot` cross-builds
- 🛠️ `post_install.sh` patches Flutter Tools Android-host detection, Gradle plugin ARM64-only ABI, and NDK/build-tools wrappers
- 📦 Produces installable `flutter_3.44.0_aarch64.deb`
- 🤖 Automated build, package, and on-device smoke-test workflow

### 🤖 CI/CD and Device Lab

The repository separates cheap PR checks from expensive engine/device validation:

| Workflow | Trigger | Runner | Purpose |
|----------|---------|--------|---------|
| `CI` | PR / push / manual | GitHub-hosted Ubuntu | Python, Shell, PowerShell, YAML, and package/docs contract sanity |
| `Build deb` | Manual | self-hosted Linux/WSL | Full Flutter Engine build, `.deb` packaging, optional release publishing |
| `Device smoke` | Manual | self-hosted Windows + ADB | Install the deb in Termux, then run doctor/create/APK/Linux smoke tests |
| `Release check` | Release / manual | GitHub-hosted Ubuntu | Verify release asset name, size, and SHA256 |

See [`docs/CI_CD.md`](docs/CI_CD.md) for workflow details, runner requirements, and local equivalents; the full documentation index is [`docs/README.md`](docs/README.md).
> Device smoke requires the tablet to stay awake and unlocked; secure lock screens block ADB text injection into Termux.

### ⚠️ System Requirements

| Item | Minimum |
|------|---------|
| Android Version | **Android 11 (API 30)** or higher |
| Architecture | ARM64 (aarch64) |
| Termux | Install from [F-Droid](https://f-droid.org/packages/com.termux/) |

> ⚠️ **Important**: The `adb` in Android SDK requires Android 11+ system functions (`pthread_cond_clockwait`). On Android 10 or older devices, extra steps are required (see below).

<details>
<summary><b>🔧 ADB Fix for Android 10 or Older Devices</b></summary>

If your device is Android 10 or older, `termux-android-sdk`'s adb will show this error:
```
CANNOT LINK EXECUTABLE "adb": cannot locate symbol "pthread_cond_clockwait"
```

**Solution:** Install [MasterDevX/Termux-ADB](https://github.com/MasterDevX/Termux-ADB) and replace adb:

```bash
# 1. Install compatible adb
wget https://github.com/MasterDevX/Termux-ADB/raw/master/InstallTools.sh -q && bash InstallTools.sh

# 2. Replace Android SDK's adb with compatible version
cp $PREFIX/bin/adb.bin $PREFIX/opt/android-sdk/platform-tools/adb

# 3. Verify
flutter doctor
```

This installs adb 1.0.39 (android-8.0.0), which works on Android 9 and older devices.

</details>

---

## 🚀 Quick Start

### Complete One-Click Install (Recommended - Includes APK Build)

One command installs Flutter + Android SDK + NDK, ready to `flutter build apk`:

```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o ~/install.sh && bash ~/install.sh
```

> This script auto-installs Flutter, Android SDK, ARM64 NDK, and tests APK build.
> Total size ~1.8GB, takes 10-30 minutes.

### Flutter Only (No APK Build)

If you only need `flutter run -d linux`, no APK building:

```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/install_termux_flutter.sh -o ~/install.sh && bash ~/install.sh
```

After install, **restart Termux** then run:
```bash
flutter doctor
```

> This script only installs Flutter SDK (~550MB), no Android SDK.

### Manual Install

```bash
# 1. Install dependencies
pkg update && pkg install x11-repo wget openjdk-21

# 2. Download package
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.0/flutter_3.44.0_aarch64.deb

# 3. Install
dpkg -i flutter_3.44.0_aarch64.deb
apt --fix-broken install -y

# 4. Run post-install script (configures APK build and hot reload)
bash $PREFIX/share/flutter/post_install.sh

# 5. Load environment and verify
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor
```

> ⚠️ **Important**: `dpkg -i` only installs files. Manual installs must still run `bash $PREFIX/share/flutter/post_install.sh` to finish Termux runtime patching.

### What `post_install.sh` does (v3.44.0)

| Area | Automatic setup |
|------|-----------------|
| Dart / Flutter Tools | Replaces CLI `dart` with Termux JIT Dart, keeps engine `dartvm`, regenerates flutter_tools package config |
| Android-host detection | Maps Android/Termux host lookups to Linux ARM64 artifacts to avoid `flutter doctor` / device discovery crashes |
| APK build | Restricts Gradle plugin default ABI to `arm64-v8a` and provides Flutter 3.44's `PLATFORM_ABI_LIST` symbol |
| SDK / build-tools | Installs API 34/36, cmdline-tools, build-tools symlinks, AAPT2 override, and licenses |
| NDK | Creates usable clang/clang++ wrappers, patches CMake host tag, replaces objcopy/strip |
| Binary hygiene | Runs `termux-elf-cleaner`, fixes shebangs, clears stale Gradle / flutter_tools caches |
| Linux desktop | Allows `flutter build linux` on Termux host and fixes `tool_backend.sh` shebang |

If an upgraded install still shows old Gradle/Kotlin errors, rerun:

```bash
bash $PREFIX/share/flutter/post_install.sh
rm -rf ~/.gradle/caches ~/.gradle/daemon
```

### Build from Source (on WSL)

```bash
# Build everything
bash scripts/build/build_termux_flutter.sh

# Or step-by-step
python3 build.py sysroot --arch=arm64    # Assemble Termux sysroot
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug
python3 build.py debuild --arch=arm64    # Package .deb
```

### Run Flutter App (with Termux:X11)

After installation, you need [Termux:X11](https://github.com/termux/termux-x11/releases) to display GUI apps.

**Install Termux:X11**: Download APK from [GitHub Releases](https://github.com/termux/termux-x11/releases) or [F-Droid](https://f-droid.org/packages/com.termux.x11/).

```bash
# 1. Start X11 server in Termux
export DISPLAY=:0
termux-x11 :0 >/dev/null 2>&1 &

# 2. Open Termux:X11 App (black screen is normal initially)

# 3. Create and run Flutter project
flutter create hello_termux
cd hello_termux
flutter run -d linux
```

> 💡 **Alternative**: If X11 is difficult to set up, use Web mode:
> ```bash
> flutter run -d web-server --web-port=8080
> ```
> Then open `http://localhost:8080` in browser.

### Build Android APK

> ✅ **v3.44.0 verified**: release APK builds successfully on Samsung SM-X716B (Android 16 / ARM64 / Termux).

First make sure post-install has been applied:

```bash
source $PREFIX/etc/profile.d/flutter.sh
bash $PREFIX/share/flutter/post_install.sh
flutter doctor -v
```

#### Required per-project settings

Flutter's official templates follow the newest Android SDK. On Termux, keep API 34 and ARM64-only output:

```bash
flutter create myapp
cd myapp

# Termux has no /usr/bin/env
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew

# Force Termux ARM64 aapt2
cat >> android/gradle.properties <<'EOF'
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
EOF
```

`android/app/build.gradle.kts`:

```kotlin
android {
    compileSdk = 34

    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
}
```

Build:

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

Notes:

- `--target-platform android-arm64`: this package currently ships ARM64 `gen_snapshot` only.
- `--no-tree-shake-icons`: the runtime patch disables icon tree shaking; the explicit flag avoids stale cache using `const_finder`.
- The first build can take longer because Gradle / Android build-tools may download.

#### Linux desktop build

Dart reports Termux as Android, so tell CMake this project is a Linux target:

```bash
flutter create mylinux --platforms=linux
cd mylinux
sed -i '1i set(CMAKE_SYSTEM_NAME Linux)' linux/CMakeLists.txt
flutter build linux --release
```

Output:

```text
build/linux/arm64/release/bundle/
```

### Run Flutter App Locally (Hot Reload)

Run Flutter app directly in Termux with hot reload support:

```bash
# 1. Enable Wireless Debugging
#    Settings → Developer Options → Wireless Debugging → ON

# 2. Pair device (first time only)
#    Tap "Pair device with pairing code", note the code and port
adb pair 127.0.0.1:<pairing_port>
# Enter pairing code

# 3. Connect device
adb connect 127.0.0.1:<connect_port>

# 4. Run Flutter app
cd your_flutter_project
flutter run
```

> 💡 When connected, you'll see:
> ```
> Flutter run key commands.
> r Hot reload. 🔥🔥🔥
> R Hot restart.
> ```

### Deploy to Android Device

#### Connect ADB Device

**Method A: Wireless ADB (Same Phone)**

1. Enable "Developer Options" → "Wireless Debugging" on your phone
2. Tap "Pair device with pairing code", note the pairing code and port

```bash
# Pair (only once)
adb pair 127.0.0.1:<pairing_port>
# Enter pairing code

# Connect
adb connect 127.0.0.1:<connect_port>
```

**Method B: Connect to Other Devices**

```bash
# Ensure target device has USB debugging or wireless debugging enabled
adb connect <device_ip>:5555
```

#### Run App

```bash
# List connected devices
flutter devices

# Deploy to Android device
flutter run -d <device_id>

# Or install APK directly
adb install build/app/outputs/flutter-apk/app-release.apk
```

> ⚠️ **Note**: `flutter devices` only shows `linux` by default. Install `termux-android-sdk` to see Android device options.

---

## 📁 Directory Structure

```
termux-flutter-wsl/
├── .github/workflows/        # GitHub-hosted CI + self-hosted build/device gates
│   ├── ci.yml                # Fast PR/push checks
│   ├── build-deb.yml         # Manual full .deb build / release publish
│   ├── device-smoke.yml      # Manual tablet Termux smoke test
│   └── release-check.yml     # Release asset metadata verification
├── docs/
│   ├── README.md             # Documentation index
│   ├── CI_CD.md              # CI/CD, runner, and device-lab guide
│   ├── guides/               # Install, build, and upgrade guides
│   └── releases/             # Changelog and release notes
├── scripts/
│   ├── build/                # WSL/Engine build helper scripts
│   ├── ci/                   # Lightweight repository contract checks
│   ├── device/               # ADB → Termux smoke automation
│   ├── install/              # Termux install and post-install patches
│   ├── setup/                # WSL/SDK/Gradle setup scripts
│   ├── fix/                  # Historical workaround scripts
│   └── test/                 # GitHub Release / Termux E2E smoke scripts
├── patches/3.44.0/           # Flutter Engine / Dart / Skia patches
├── package.yaml              # .deb artifact mapping
├── build.py                  # Main build script
├── build.toml                # Build configuration
├── install_flutter_complete.sh # Termux one-click installer
├── README.md                 # Chinese docs
└── README_EN.md              # English docs
```

---

## 🔧 Technical Details

### Build Requirements

| Item | Version/Config |
|---|---|
| Host OS | Windows 11 + WSL (Ubuntu 22.04+) |
| Target | ARM64 Android (Termux) |
| NDK | r27d (API 35) |
| Python | 3.10+ |

### Key Fixes

We applied the following fixes to ensure WSL compatibility:

```gn
# build/config/termux/BUILD.gn - runtime_library
ldflags = [
  "-stdlib=libstdc++",
  "-Wl,--warn-shared-textrel",
  "-llog",   # Added: Android logging lib
  "-lm",     # Added: Math lib
]
```

### Android gen_snapshot Cross-Compilation

To support `flutter build apk --release` (AOT compilation) on Termux, we cross-compiled a specialized gen_snapshot:

```bash
# Build in WSL (for developers)
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release
```

This gen_snapshot:
- **Runs on** ARM64 Termux
- **Produces** Android ARM64 AOT machine code
- **Included** in the `flutter_3.44.0_aarch64.deb` package

> ✅ **Verified**: gen_snapshot runs successfully on Termux:
> ```
> $ gen_snapshot --version
> Dart SDK version: 3.9.0 on "android_arm64"
> ```

**Technical Note**: The official Flutter SDK's gen_snapshot only runs on x86_64 Linux. We used NDK to cross-compile a version that runs natively on ARM64 Android (Termux), which is essential for `flutter build apk`.

---

## 📋 Upgrading

1. Update `tag` in `build.toml`.
2. Sync and patch:
   ```bash
   python3 build.py clone
   python3 build.py sync
   python3 build.py patch_engine  # Update patches if needed
   ```
3. Run the full build process.

---

## 🔄 Sync with Upstream

This project is a fork of [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter). To sync updates:

```bash
git remote add upstream https://github.com/mumumusuc/termux-flutter.git
git fetch upstream
git merge upstream/main
```

**Note**: Merge conflicts may occur because we customized build scripts for WSL support. Please resolve conflicts manually.

---

## 🙏 Acknowledgements

- [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) - Original build tools
- [lzhiyong/termux-ndk](https://github.com/lzhiyong/termux-ndk) - Prebuilt ARM64 Android NDK
- [Flutter](https://flutter.dev/) - Google's UI Toolkit
- [Termux](https://termux.com/) - Android Terminal Emulator

---

## 📄 License

Based on [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter), licensed under **GPL-3.0**.

See [LICENSE](LICENSE) for details.
