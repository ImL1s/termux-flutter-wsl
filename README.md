<p align="center">
  <img src="assets/banner.png" alt="termux-flutter-wsl" width="800"/>
</p>

<h1 align="center">Flutter for Termux ARM64</h1>

<p align="center">
  <strong>在 Android/Termux ARM64 上安裝可用的 Flutter SDK，支援 APK build、Linux desktop build 與 hot reload。</strong>
</p>

<p align="center">
  <code>flutter build apk</code> ✅ | <code>flutter build linux</code> ✅ | <code>flutter run</code> + Hot Reload ✅ | <code>.deb</code> 一鍵安裝 ✅
</p>

<p align="center">
  <strong>中文</strong> | <a href="README_EN.md">English</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Flutter-3.44.2-02569B?logo=flutter" alt="Flutter Version"/>
  <img src="https://img.shields.io/badge/Dart-3.12.1-0175C2?logo=dart" alt="Dart Version"/>
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

## 快速導覽

- [這是什麼](#這是什麼)
- [目前版本與驗證狀態](#目前版本與驗證狀態)
- [快速安裝](#快速安裝)
- [建立專案與 build APK](#建立專案與-build-apk)
- [Linux desktop / Termux:X11](#linux-desktop--termuxx11)
- [自行編譯 `.deb`](#自行編譯-deb)
- [CI/CD 與 release 驗證](#cicd-與-release-驗證)
- [文件地圖](#文件地圖)
- [限制與注意事項](#限制與注意事項)

## 這是什麼

Flutter 官方 SDK 支援 ARM64 target，不代表可以直接把 Flutter SDK 當成 **Android/Termux host** 使用。Termux 使用 Android bionic、不同的 linker 路徑與工具鏈佈局；官方 Linux SDK 假設的是 glibc host。

本專案提供一套針對 Termux ARM64 的 Flutter SDK 打包流程：

- 從 WSL/Linux 交叉編譯 Flutter Engine、Dart runtime 與必要工具。
- 將產物整理成 Termux 可安裝的 `flutter_3.44.2_aarch64.deb`。
- 安裝後透過 `post_install.sh` 修補 Flutter Tools、Gradle plugin、NDK/build-tools wrappers、Android SDK 限制與 Termux shebang。
- 讓 Termux 內可以執行 `flutter doctor`、`flutter create`、`flutter build apk`、`flutter build linux`，並可搭配 Termux:X11 進行 hot reload。

## 目前版本與驗證狀態

| 項目 | 狀態 |
| --- | --- |
| Flutter | `3.44.2` |
| Dart | `3.12.1` |
| 架構 | `aarch64` / `arm64-v8a` |
| Release asset | [`flutter_3.44.2_aarch64.deb`](https://github.com/ImL1s/termux-flutter-wsl/releases/tag/v3.44.2-termux) |
| Size | `669,484,232` bytes |
| SHA256 | `f706406253586a5586f8a1e7ff0a09b5a7f029a8ea9f2e1225ce682f10550c9e` |

### 實機 smoke test

最後一次完整實機驗證：**2026-07-04**，Samsung SM-X716B / Android 16 / Termux。

| 驗證項目 | 結果 |
| --- | --- |
| `dpkg -i` + `post_install.sh` | ✅ |
| `flutter --version` / `dart --version` / `dartvm --version` | ✅ |
| `flutter doctor -v` | ✅（僅保留預期 channel/device warning） |
| `flutter create --platforms=android,linux` | ✅ |
| `flutter build apk --release --target-platform android-arm64` | ✅ |
| `flutter build linux --release` | ✅ |

## 快速安裝

### 系統需求

| 項目 | 需求 |
| --- | --- |
| 裝置 | Android ARM64 / aarch64 |
| Android | 建議 Android 11+ |
| App | F-Droid 版 Termux；Linux GUI 需 Termux:X11 |
| 空間 | 建議至少 8GB 可用空間 |

### 一鍵安裝（推薦）

```bash
pkg update && pkg upgrade -y
pkg install -y curl
curl -L https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o install_flutter_complete.sh
bash install_flutter_complete.sh
```

### 手動安裝 release `.deb`

```bash
pkg update && pkg install -y wget
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2-termux/flutter_3.44.2_aarch64.deb
sha256sum flutter_3.44.2_aarch64.deb

dpkg -i flutter_3.44.2_aarch64.deb
apt --fix-broken install -y
bash $PREFIX/share/flutter/post_install.sh
source ~/.bashrc
flutter --version
```

若 SHA256 與上方版本表不一致，請不要安裝該檔案。

## 建立專案與 build APK

本專案支援兩種不同的建置模式：

### 模式 A：已驗證的 Termux 本地編譯與 sideload（推薦預設）
這是目前經過實機測試、最穩定的本地開發路徑。適用於 sideload 測試。

1. 在專案中設定使用 Termux 本地 `aapt2`、關閉混淆縮減（避免 JVM 記憶體崩潰）及關閉資源優化：
```properties
# android/gradle.properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
android.enableResourceOptimizations=false
shrink=false
```

2. 限制專案的 SDK 為 API 34 並明確關閉混淆：
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

3. 執行 Release 編譯（注意：必須繞過 JIT Dart 限制的 icon tree shaking）：
```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

---

### 模式 B：實驗性 Google Play 發版編譯（API 35+ / AAB）
此模式目前為 **實驗性**。由於 Google Play 規定新 App 必須 target API 35+，本地舊版 `aapt2` 會因此崩潰。此模式需手動接入原生靜態 ARM64 Android Build-Tools（詳情請參閱 [AAPT2_RELEASE_BUILD_BUG_ANALYSIS.md](docs/guides/AAPT2_RELEASE_BUILD_BUG_ANALYSIS.md)）。

> `post_install.sh` 已經會盡量把 Flutter Tools 預設值修成 Termux 友善，但專案層級仍建議保留上面的 Gradle 設定，讓不同 template / plugin 組合更穩。

## Linux desktop / Termux:X11

```bash
pkg install -y x11-repo termux-x11-nightly
termux-x11 :0 &
export DISPLAY=:0

flutter create --platforms=linux linux_demo
cd linux_demo
flutter run -d linux
```

也可以先只 build：

```bash
flutter build linux --release
```

## 自行編譯 `.deb`

完整 build 需要 WSL/Linux、Android NDK、depot_tools、Flutter Engine checkout，耗時通常是數小時。

```bash
python3 build.py build_all --arch=arm64
```

常用分段指令：

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

完整 build 流程、模式矩陣與排錯請看 [`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md)。

## CI/CD 與 release 驗證

| Workflow | 觸發 | Runner | 用途 |
| --- | --- | --- | --- |
| `CI` | PR / push / 手動 | GitHub-hosted Ubuntu | Python、Shell、PowerShell、YAML、package/docs contract sanity |
| `Build deb` | 手動 | self-hosted Linux/WSL | 完整 Flutter Engine build、`.deb` 打包、可選 release publish |
| `Device smoke` | 手動 | self-hosted Windows + ADB | 平板 Termux 安裝 deb、doctor、create、APK/Linux build smoke |
| `Release check` | Release / 手動 | GitHub-hosted Ubuntu | 驗證 release asset 名稱、大小與 SHA256 |

詳細 runner 需求與本地等效指令請看 [`docs/CI_CD.md`](docs/CI_CD.md)。

> 裝置 smoke 需要平板保持喚醒且已解鎖；安全鎖定畫面會阻止 ADB 將命令輸入到 Termux。

## 專案結構

```text
termux-flutter-wsl/
├── .github/workflows/        # GitHub-hosted CI + self-hosted build/device gates
├── docs/                     # 長篇文件、指南、release notes
│   ├── README.md             # 文件索引
│   ├── CI_CD.md              # CI/CD、runner 與裝置實驗室說明
│   ├── guides/               # 安裝、構建、升級指南
│   └── releases/             # Changelog 與 release notes
├── scripts/
│   ├── ci/                   # 輕量 repo contract checks
│   ├── device/               # ADB → Termux smoke automation
│   ├── install/              # Termux 安裝與 post-install 修補
│   └── test/                 # Release / Termux E2E smoke scripts
├── patches/3.44.2/           # Flutter Engine / Dart / Skia patches
├── build.py                  # 主構建 CLI
├── build.toml                # 版本、NDK、sysroot、patch 設定
├── package.yaml              # .deb artifact mapping
└── install_flutter_complete.sh
```

## 文件地圖

| 文件 | 用途 |
| --- | --- |
| [`docs/README.md`](docs/README.md) | 完整文件索引 |
| [`docs/guides/INSTALL_GUIDE.md`](docs/guides/INSTALL_GUIDE.md) | 安裝流程與 Termux runtime 前置需求 |
| [`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md) | WSL/Engine build、打包與排錯 |
| [`docs/guides/UPGRADE_GUIDE.md`](docs/guides/UPGRADE_GUIDE.md) | 升級到新版 Flutter 的 checklist |
| [`docs/CI_CD.md`](docs/CI_CD.md) | CI/CD、self-hosted runner、device smoke |
| [`docs/releases/CHANGELOG.md`](docs/releases/CHANGELOG.md) | 版本變更記錄 |
| [`docs/releases/RELEASE_NOTES.md`](docs/releases/RELEASE_NOTES.md) | 目前 release body |

## 限制與注意事項

- 目前主要支援 **ARM64 / arm64-v8a**；32-bit ARM 與 x64 Android gen_snapshot 不是本專案目標。
- Android APK build 建議使用 `compileSdk = 34` / `targetSdk = 34`，避開 Termux `aapt2` 對新 `android.jar` 的相容性問題。
- `flutter doctor` 會顯示自訂 channel / upstream remote warning，這是打包後 SDK 的預期狀態，不代表 runtime smoke 失敗。
- `ninja flutter` 不會產出可用的 `dart` binary；自行編譯時必須另外跑 `build_dart()`。
- Release `.deb` 很大，安裝與第一次 `post_install.sh` 需要耐心等待。

## 常見問題入口

- APK build / `aapt2` / compileSdk 問題：[`docs/guides/INSTALL_GUIDE.md`](docs/guides/INSTALL_GUIDE.md)
- Engine / Dart / Skia patch 或 WSL build 問題：[`docs/guides/BUILD_GUIDE.md`](docs/guides/BUILD_GUIDE.md)
- CI/CD、release asset、device smoke 問題：[`docs/CI_CD.md`](docs/CI_CD.md)
- 升級 Flutter 版本：[`docs/guides/UPGRADE_GUIDE.md`](docs/guides/UPGRADE_GUIDE.md)

## 致謝

- 原始專案：[`mumumusuc/termux-flutter`](https://github.com/mumumusuc/termux-flutter)
- Termux 社群提供 Android userspace、packages 與 X11 生態
- Flutter / Dart / Skia / Chromium Engine upstream

## 許可證

本專案依照 [GPL-3.0](LICENSE) 授權。
