<p align="center">
  <img src="assets/banner.png" alt="termux-flutter-wsl" width="800"/>
</p>

<h1 align="center">Flutter for Termux ARM64</h1>

<p align="center">
  <strong>🚀 世界首個在手機上完整運行 Flutter 開發環境的解決方案</strong>
</p>

<p align="center">
  <code>flutter build apk</code> ✅ | <code>flutter run</code> + Hot Reload ✅ | 原生速度 ✅ | 一鍵安裝 ✅
</p>

<p align="center">
  <strong>中文</strong> | <a href="README_EN.md">English</a>
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
  <em>📱 在 Termux 中運行 Flutter App，支援 Hot Reload！</em>
</p>

---

## ❓ 為什麼需要這個專案？

**Flutter「支援 arm64」≠「能在任何 arm64 上開發」**

| Flutter 說的 arm64 支援 | 實際意義 |
|------------------------|---------|
| arm64 **Target** | ✅ 你的 App 能跑在 arm64 設備 |
| arm64 **Host** | ⚠️ 只支援 macOS (Apple Silicon)、Linux (glibc) |
| Android/Termux Host | ❌ **從未支援** |

### 為什麼 Termux 不被支援？

Flutter 假設的 Linux host 環境：
- glibc（標準 C 庫）
- 完整 POSIX
- 標準 toolchain

但 **Termux 是**：
- **bionic libc**（Android 的 C 庫，不是 glibc）
- Android sandbox + SELinux 限制
- 不同的動態連結器 (`/system/bin/linker64`)

對 Flutter 官方來說：**這不是他們支援的 OS。**

### 我們做了什麼？

```
Flutter SDK 裡的 engine binaries：
bin/cache/artifacts/engine/
    ├── darwin-arm64/     ← macOS 用
    ├── linux-arm64/      ← Linux (glibc) 用
    └── android-arm64/    ← 這是 TARGET，不是 HOST！

❌ 沒有 Termux/bionic host 版本
```

**我們從源碼交叉編譯了整個 Flutter Engine**，專門為 Termux (Android/bionic) 環境打造：

- 修復 TLS 對齊問題（bionic linker 要求）
- 修復動態連結器路徑
- 編譯 host-side 工具（dart, gen_snapshot, impellerc）
- 讓 Hot Reload、APK 構建在 Termux 上原生運行

> **一句話：Flutter 官方支援 arm64 目標平台，但從不支援 Android 作為開發主機。我們補上了這個缺失。**

---

## 📖 專案簡介

本專案基於 [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter)，實現了在 **WSL (Windows Subsystem for Linux)** 環境下為 Termux 交叉編譯 Flutter Engine 的完整解決方案。

### 🆚 與原專案的差異

| 項目 | 原專案 | 本專案 |
|---|---|---|
| 構建環境 | Linux / Termux 原生 | **WSL (Windows)** |
| Flutter 版本 | 3.29.2 | **3.44.0** |
| Android 兼容性 | ❌ 不支援 Android 14+ | ✅ **支援 Android 16** |
| 額外修復 | - | **`-llog`, `-lm` 依賴** |
| 文檔 | 基礎 | **完整中文指南** |

> ✅ **已驗證**：本專案已在 Android 16 設備上成功運行 Flutter 應用！

### 🏆 世界首個完整 Flutter 開發環境

本專案是**世界首個**在 ARM64 Termux 上實現**完整 Flutter 開發流程**的解決方案！

#### 🎯 我們能做到什麼？

| 功能 | 本專案 | 其他方案 |
|------|--------|----------|
| `flutter build apk` | ✅ **原生支援** | ❌ 無法實現 |
| `flutter run` + Hot Reload | ✅ **完整支援** | ❌ 無法實現 |
| 效能 | ✅ **原生速度** | ⚠️ x86 模擬，慢 3-5 倍 |
| 安裝難度 | ✅ **一鍵安裝** | ⚠️ 複雜配置 |
| APK 產出 | ✅ **原生 ARM64 APK** | ⚠️ proot 增加額外開銷 |

#### 📊 完整功能對比

| 專案 | build apk | flutter run | hot reload | 原生運行 | 維護狀態 |
|------|-----------|-------------|------------|----------|----------|
| **本專案** | ✅ | ✅ | ✅ | ✅ | ✅ 活躍 |
| Flutter 官方 | ❌ | ❌ | ❌ | ❌ | [Issue #177936](https://github.com/flutter/flutter/issues/177936): 不支援 |
| [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) | ❌ | ⚠️ linux only | ❌ | ✅ | ⚠️ 停更 |
| [Hax4us/flutter_in_termux](https://github.com/Hax4us/flutter_in_termux) | ⚠️ proot | ⚠️ proot | ❌ | ❌ x86 模擬 | ⚠️ 停更 |
| [bdloser404/Fluttermux](https://github.com/bdloser404/Fluttermux) | ❌ | ❌ | ❌ | ❌ | ❌ 已失效 |

> 💡 如果你發現其他能原生支援的專案，歡迎[開 Issue](https://github.com/ImL1s/termux-flutter-wsl/issues) 告訴我們！

#### 🚀 這意味著什麼？

**你可以在手機/平板上完成完整的 Flutter 開發：**

```
📱 你的 Android 設備
    ↓
🖥️ Termux 終端
    ↓
✍️ 編寫程式碼 (vim/nano/code-server)
    ↓
🔥 flutter run → 即時看到變更 (Hot Reload!)
    ↓
📦 flutter build apk → 產出可安裝的 APK
    ↓
📲 直接安裝到設備上測試
```

**不需要電腦、不需要模擬器、不需要雲端服務！**

### 📊 v3.44.0 驗證狀態（2026-06-01）

| 項目 | 結果 | 驗證環境 / 備註 |
|------|------|----------------|
| `flutter --version` | ✅ | Flutter 3.44.0，Tools Dart 3.12.1 |
| `dart --version` | ✅ | Termux JIT Dart 3.12.1 (`android_arm64`) |
| `dartvm --version` | ✅ | post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`) |
| `flutter doctor -v` | ✅ | Android SDK / Java 21 / network resources OK；unknown channel 與未連 ADB device 為預期警告 |
| `flutter create` | ✅ | `--platforms=android,linux` smoke project |
| `flutter build apk --release` | ✅ | Samsung SM-X716B / Android 16 / Termux；ARM64 APK 產出成功 |
| `flutter build linux --release` | ✅ | 產出 ARM64 ELF 與 `libflutter_linux_gtk.so` |
| `.deb` artifact validation | ✅ | `dart` / `dartvm` / `dartaotruntime` executable checks passed |

**目前封包**：`flutter_3.44.0_aarch64.deb`<br>
**大小**：666,366,556 bytes（約 636 MiB）<br>
**SHA256**：`b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846`

> Flutter 3.44 / Dart 3.12 是官方 2026-05 release train。本專案額外處理了 Android/Termux host 在官方 SDK 中不存在的部分。

### ✨ 主要特色

- 🪟 在 Windows WSL 環境下完成 Flutter Engine / Dart / toolchain 交叉編譯
- 🧩 針對 Android/bionic host 修復 TLS alignment、dynamic linker、`-llog` / `-lm`、NDK clang runtime
- 🎯 預設只產出 `android-arm64`，避免 arm/x64 `gen_snapshot` 交叉編譯限制
- 🛠️ `post_install.sh` 自動修補 Flutter Tools 的 Android-host 偵測、Gradle plugin ARM64-only ABI、NDK/build-tools wrappers
- 📦 產出可安裝的 `flutter_3.44.0_aarch64.deb`
- 🤖 完整自動化構建、打包與裝置 smoke test 流程

### 🤖 CI/CD 與裝置實驗室

本專案把「快速 PR 檢查」和「昂貴的引擎/實機驗證」分開：

| Workflow | 觸發 | Runner | 用途 |
|----------|------|--------|------|
| `CI` | PR / push / 手動 | GitHub-hosted Ubuntu | Python、Shell、PowerShell、YAML、package/docs contract sanity |
| `Build deb` | 手動 | self-hosted Linux/WSL | 完整 Flutter Engine build、`.deb` 打包、可選 release publish |
| `Device smoke` | 手動 | self-hosted Windows + ADB | 平板 Termux 安裝 deb、doctor、create、APK/Linux build smoke |
| `Release check` | Release / 手動 | GitHub-hosted Ubuntu | 驗證 release asset 名稱、大小與 SHA256 |

詳細流程、runner 需求與本地等效指令請看 [`docs/CI_CD.md`](docs/CI_CD.md)；完整文件索引在 [`docs/README.md`](docs/README.md)。
> 裝置 smoke 需要平板保持喚醒且已解鎖；安全鎖定畫面會阻止 ADB 將命令輸入到 Termux。

### ⚠️ 系統需求

| 項目 | 最低需求 |
|------|----------|
| Android 版本 | **Android 11 (API 30)** 或更高 |
| 架構 | ARM64 (aarch64) |
| Termux | 從 [F-Droid](https://f-droid.org/packages/com.termux/) 安裝 |

> ⚠️ **重要**：Android SDK 中的 `adb` 需要 Android 11+ 的系統函數 (`pthread_cond_clockwait`)。在 Android 10 或更舊的設備上，需要額外步驟（見下方）。

<details>
<summary><b>🔧 Android 10 或更舊設備的 ADB 修復方法</b></summary>

如果你的設備是 Android 10 或更舊版本，`termux-android-sdk` 的 adb 會出現以下錯誤：
```
CANNOT LINK EXECUTABLE "adb": cannot locate symbol "pthread_cond_clockwait"
```

**解決方案：** 安裝 [MasterDevX/Termux-ADB](https://github.com/MasterDevX/Termux-ADB) 並替換 adb：

```bash
# 1. 安裝舊版相容的 adb
wget https://github.com/MasterDevX/Termux-ADB/raw/master/InstallTools.sh -q && bash InstallTools.sh

# 2. 用相容版本替換 Android SDK 的 adb
cp $PREFIX/bin/adb.bin $PREFIX/opt/android-sdk/platform-tools/adb

# 3. 驗證
flutter doctor
```

這會安裝 adb 1.0.39 (android-8.0.0)，可在 Android 9 及更舊設備上運行。

</details>

---

## 🚀 快速開始

### 完整一鍵安裝（推薦 - 包含 APK 構建）

一個命令安裝 Flutter + Android SDK + NDK，完成後直接可以 `flutter build apk`：

```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o ~/install.sh && bash ~/install.sh
```

> 此腳本會自動安裝 Flutter、Android SDK、ARM64 NDK，並測試 APK 構建。
> 總大小約 1.8GB，需要 10-30 分鐘。

### 只安裝 Flutter（不含 APK 構建）

如果只需要 `flutter run -d linux`，不需要構建 APK：

```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/scripts/install/install_termux_flutter.sh -o ~/install.sh && bash ~/install.sh
```

安裝完成後，**重啟 Termux** 或執行：
```bash
flutter doctor
```

> 此腳本只安裝 Flutter SDK (~550MB)，不含 Android SDK。

### 手動安裝

```bash
# 1. 安裝基礎依賴
pkg update && pkg install x11-repo wget openjdk-21

# 2. 下載安裝包
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.0/flutter_3.44.0_aarch64.deb

# 3. 安裝
dpkg -i flutter_3.44.0_aarch64.deb
apt --fix-broken install -y

# 4. 執行 post-install 腳本（配置 APK 構建和 hot reload）
bash $PREFIX/share/flutter/post_install.sh

# 5. 載入環境並驗證
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor
```

> ⚠️ **重要**：`dpkg -i` 只會安裝檔案；手動安裝後仍要執行 `bash $PREFIX/share/flutter/post_install.sh` 完成 Termux runtime 修補。

### `post_install.sh` 會做什麼（v3.44.0）

| 類別 | 自動處理內容 |
|------|--------------|
| Dart / Flutter Tools | 用 Termux JIT Dart 替換 CLI 用的 `dart`、保留 engine `dartvm`、重新產生 `flutter_tools` package config |
| Android-host 偵測 | 把 Flutter Tools 中的 Android host 映射到 Linux ARM64 artifacts，避免 `flutter doctor` / device discovery 崩潰 |
| APK build | 將 Gradle plugin 預設 ABI 限制為 `arm64-v8a`，補上 Flutter 3.44 需要的 `PLATFORM_ABI_LIST` |
| SDK / build-tools | 安裝 API 34/36、cmdline-tools、build-tools symlinks、AAPT2 override、licenses |
| NDK | 建立 ARM64 可用的 clang/clang++ wrappers，修補 CMake toolchain host tag 與 objcopy/strip |
| Binary hygiene | 執行 `termux-elf-cleaner`、修正 shebang、清掉舊 Gradle / flutter_tools caches |
| Linux desktop | 允許 `flutter build linux` 在 Termux host 執行，並修正 `tool_backend.sh` shebang |

如果你升級後看到舊的 Gradle/Kotlin 錯誤，先重跑：

```bash
bash $PREFIX/share/flutter/post_install.sh
rm -rf ~/.gradle/caches ~/.gradle/daemon
```

### 自行編譯（WSL 環境）

```bash
# 一鍵構建
bash scripts/build/build_termux_flutter.sh

# 或分步驟執行
python3 build.py sysroot --arch=arm64    # 組裝 Termux 運行時依賴
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug
python3 build.py debuild --arch=arm64    # 打包 .deb
```

### 運行 Flutter 應用（使用 Termux:X11）

安裝完成後，你需要 [Termux:X11](https://github.com/termux/termux-x11/releases) 來顯示 GUI 應用。

**安裝 Termux:X11**：從 [GitHub Releases](https://github.com/termux/termux-x11/releases) 或 [F-Droid](https://f-droid.org/packages/com.termux.x11/) 下載 APK 安裝。

```bash
# 1. 在 Termux 中啟動 X11 服務
export DISPLAY=:0
termux-x11 :0 >/dev/null 2>&1 &

# 2. 打開 Termux:X11 App (會顯示黑色畫面，這是正常的)

# 3. 創建並運行 Flutter 專案
flutter create hello_termux
cd hello_termux
flutter run -d linux
```

> 💡 **備選方案**：如果 X11 設置困難，也可以用 Web 模式預覽：
> ```bash
> flutter run -d web-server --web-port=8080
> ```
> 然後在瀏覽器打開 `http://localhost:8080`

### 構建 Android APK

> ✅ **v3.44.0 已驗證**：在 Samsung SM-X716B（Android 16 / ARM64 / Termux）上成功產出 release APK。

安裝後請先確認已跑過 post-install：

```bash
source $PREFIX/etc/profile.d/flutter.sh
bash $PREFIX/share/flutter/post_install.sh
flutter doctor -v
```

#### 每個 Flutter 專案都需要的設定

Flutter 官方模板會追隨最新 Android SDK；Termux 的 `aapt2` 與目前可用工具鏈需要固定在 API 34 / ARM64。建立專案後套用：

```bash
flutter create myapp
cd myapp

# Termux 沒有 /usr/bin/env
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew

# 強制使用 Termux ARM64 aapt2
cat >> android/gradle.properties <<'EOF'
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
EOF
```

`android/app/build.gradle.kts`：

```kotlin
android {
    compileSdk = 34

    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
}
```

然後建置：

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

說明：

- `--target-platform android-arm64`：本專案目前只提供 ARM64 `gen_snapshot`。
- `--no-tree-shake-icons`：Termux runtime 會停用 icon tree shaking；顯式加上可避免舊 cache 誤用 `const_finder`。
- 第一次 build 可能下載 Gradle / Android build-tools，時間會比之後久。

#### Linux desktop build

Termux 上的 Dart 回報 host OS 為 `android`，CMake 仍需明確指定 Linux system name：

```bash
flutter create mylinux --platforms=linux
cd mylinux
sed -i '1i set(CMAKE_SYSTEM_NAME Linux)' linux/CMakeLists.txt
flutter build linux --release
```

產物位於：

```text
build/linux/arm64/release/bundle/
```

### 在本機運行 Flutter App（Hot Reload）

在 Termux 中直接運行 Flutter app 並支援 hot reload：

```bash
# 1. 啟用無線調試
#    設定 → 開發者選項 → 無線調試 → 開啟

# 2. 配對設備（首次需要）
#    點擊「使用配對碼配對設備」，記下配對碼和端口
adb pair 127.0.0.1:<配對端口>
# 輸入配對碼

# 3. 連接設備
adb connect 127.0.0.1:<連接端口>

# 4. 運行 Flutter app
cd your_flutter_project
flutter run
```

> 💡 連接成功後會顯示：
> ```
> Flutter run key commands.
> r Hot reload. 🔥🔥🔥
> R Hot restart.
> ```

### 部署到 Android 設備

#### 連接 ADB 設備

**方法 A：無線 ADB（同一台手機）**

1. 開啟手機的「開發者選項」→「無線偵錯」
2. 點擊「使用配對碼配對裝置」，記下配對碼和端口

```bash
# 配對（只需一次）
adb pair 127.0.0.1:<配對端口>
# 輸入配對碼

# 連接
adb connect 127.0.0.1:<連接端口>
```

**方法 B：連接其他設備**

```bash
# 確保目標設備已開啟 USB 偵錯或無線偵錯
adb connect <設備IP>:5555
```

#### 運行應用

```bash
# 查看已連接設備
flutter devices

# 部署到 Android 設備
flutter run -d <device_id>

# 或直接安裝 APK
adb install build/app/outputs/flutter-apk/app-release.apk
```

> ⚠️ **注意**：`flutter devices` 預設只顯示 `linux`。安裝 `termux-android-sdk` 後才會出現 Android 設備選項。

---

## 📁 目錄結構

```
termux-flutter-wsl/
├── .github/workflows/        # GitHub-hosted CI + self-hosted build/device gates
│   ├── ci.yml                # PR/push 快速檢查
│   ├── build-deb.yml         # 手動完整 .deb build / release publish
│   ├── device-smoke.yml      # 手動平板 Termux smoke test
│   └── release-check.yml     # Release asset metadata 驗證
├── docs/
│   ├── README.md             # 文件索引
│   ├── CI_CD.md              # CI/CD、runner 與裝置實驗室說明
│   ├── guides/               # 安裝、構建、升級指南
│   └── releases/             # Changelog 與 release notes
├── scripts/
│   ├── build/                # WSL/Engine build helper scripts
│   ├── ci/                   # 輕量 repo contract checks
│   ├── device/               # ADB → Termux smoke automation
│   ├── install/              # Termux 安裝與 post-install 修補
│   ├── setup/                # WSL/SDK/Gradle setup scripts
│   ├── fix/                  # 歷史 workaround scripts
│   └── test/                 # GitHub Release / Termux E2E smoke scripts
├── patches/3.44.0/           # Flutter Engine / Dart / Skia patches
├── package.yaml              # .deb artifact mapping
├── build.py                  # 主構建腳本
├── build.toml                # 構建配置
├── install_flutter_complete.sh # Termux 一鍵安裝腳本
├── README.md                 # 中文文檔
└── README_EN.md              # 英文文檔
```

---

## 🔧 技術細節

### 構建環境要求

| 項目 | 版本/配置 |
|---|---|
| Host OS | Windows 11 + WSL (Ubuntu 22.04+) |
| Target | ARM64 Android (Termux) |
| NDK | r27d (API 35) |
| Python | 3.10+ |

### 關鍵修復

我們在原版基礎上做了以下修正以解決 WSL 環境的兼容問題：

```gn
# build/config/termux/BUILD.gn - runtime_library
ldflags = [
  "-stdlib=libstdc++",
  "-Wl,--warn-shared-textrel",
  "-llog",   # 新增：Android 日誌庫
  "-lm",     # 新增：數學庫
]
```

其他 3.44.0 關鍵修復：

| 修復 | 原因 |
|------|------|
| `dart` / `dartvm` 分離 | Flutter CLI 需要 Termux JIT Dart；engine tools 仍需要配套的 `dartvm` / `dartaotruntime` |
| Flutter Tools Android-host mapping | Dart 在 Termux 回報 `Platform.operatingSystem == "android"`，官方工具只認 macOS/Linux/Windows host |
| Gradle `PLATFORM_ABI_LIST` | Flutter 3.44 Gradle plugin 新增直接 import；post-install 的 ARM64-only 模板必須同步提供此 symbol |
| Gradle / flutter_tools cache 清理 | 升級時避免舊 snapshot 或 included-build cache 混用新舊 Kotlin source |

### Android gen_snapshot 交叉編譯

為了支援在 Termux 上執行 `flutter build apk --release`（AOT 編譯），我們交叉編譯了專用的 gen_snapshot：

```bash
# 在 WSL 中構建（開發者使用）
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release
```

這個 gen_snapshot 的特點：
- **運行在** ARM64 Termux 上
- **產生** Android ARM64 AOT 機器碼
- **建置後包含** 在 `flutter_3.44.0_aarch64.deb` 安裝包中

> ✅ **已驗證**：gen_snapshot 在 Termux 上成功運行：
> ```
> $ gen_snapshot --version
> Dart SDK version: 3.12.x on "android_arm64"
> ```

**技術說明**：官方 Flutter SDK 的 gen_snapshot 只能在 x86_64 Linux 上運行。我們使用 NDK 交叉編譯了一個能在 ARM64 Android (Termux) 上原生運行的版本，這是實現 `flutter build apk` 的關鍵。

---

## 🔧 常見問題排解

### NDK Clang 找不到編譯器

**錯誤訊息**：
```
CMake Error: The CMAKE_C_COMPILER is not a full path to an existing compiler tool.
```

**原因**：Gradle 在構建時下載了新的 NDK 版本，但 `post_install.sh` 在 NDK 下載之前已經運行過，導致 clang wrapper 沒有被創建。

**解決方案**：重新運行 post_install.sh 來配置所有 NDK：
```bash
bash $PREFIX/share/flutter/post_install.sh
flutter build apk --release
```

### libflutter_linux_gtk.so 找不到

**錯誤訊息**：
```
Unsupported file type "notFound" for libflutter_linux_gtk.so
```

**原因**：deb 包中缺少 Linux GTK 庫。

**解決方案**：這是構建問題，需要重新構建 deb 包並確保 `flutter_gtk` 目標已啟用。如果你是用戶，請下載最新版本的 deb 包。

### DT_RPATH 警告

**警告訊息**：
```
WARNING: linker: Warning: unused DT entry: DT_RPATH
```

**原因**：ELF 二進制文件包含不必要的 DT_RPATH 條目。

**解決方案**：這個警告不影響功能，但可以通過 `termux-elf-cleaner` 清除：
```bash
pkg install termux-elf-cleaner
termux-elf-cleaner $PREFIX/opt/flutter/bin/cache/dart-sdk/bin/dart
termux-elf-cleaner $PREFIX/opt/flutter/bin/cache/dart-sdk/bin/dartvm
```

### AAPT2 / compileSdk 錯誤

**常見錯誤**：`aapt2` 無法讀取新版 `android.jar`、或 Gradle 下載到 x86_64 `aapt2`。

**解法**：每個專案固定 API 34，並指定 Termux 的 ARM64 `aapt2`：

```bash
cat >> android/gradle.properties <<'EOF'
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
EOF
```

`android/app/build.gradle.kts`：

```kotlin
compileSdk = 34
defaultConfig {
    targetSdk = 34
    ndk { abiFilters += listOf("arm64-v8a") }
}
```

如果 Gradle cache 已經污染，清掉後重建：

```bash
./android/gradlew --stop || true
rm -rf ~/.gradle/caches .gradle android/.gradle build android/app/build
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

---

## 📋 升級到新版本

1. 修改 `build.toml` 中的 `tag` 為新版本號
2. 執行同步與補丁：
   ```bash
   python3 build.py clone
   python3 build.py sync
   python3 build.py patch_engine  # 如失敗需更新補丁文件
   ```
3. 執行完整構建流程

---

## 🔄 同步上游更新

本專案是 [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) 的 Fork。要獲取上游更新：

```bash
git remote add upstream https://github.com/mumumusuc/termux-flutter.git
git fetch upstream
git merge upstream/main
```

**注意**：由於我們為 WSL 修改了部分構建腳本，合併時可能會發生衝突，請手動解決。

---

## 🙏 致謝

- [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter) - 原始構建工具
- [lzhiyong/termux-ndk](https://github.com/lzhiyong/termux-ndk) - ARM64 預編譯 Android NDK
- [Flutter](https://flutter.dev/) - Google 的 UI 框架
- [Termux](https://termux.com/) - Android 終端模擬器

---

## 📄 許可證

本專案基於 [mumumusuc/termux-flutter](https://github.com/mumumusuc/termux-flutter)，採用 **GPL-3.0** 協議開源。

詳見 [LICENSE](LICENSE)
