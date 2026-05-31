# Flutter Termux 完整構建指南

本文檔說明如何從零開始構建包含 Android gen_snapshot 的 Flutter deb 包。

## 目前版本狀態（3.44.0 / 2026-06-01）

| 項目 | 值 |
|------|----|
| Flutter tag | `3.44.0` |
| Engine revision | `4c525dac5ebe5971c5708ef73558ed8edcf4a362` |
| Package | `flutter_3.44.0_aarch64.deb` |
| Package size | 666,366,556 bytes（約 636 MiB） |
| SHA256 | `b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846` |
| Device smoke | Samsung SM-X716B / Android 16 / Termux |

3.44.0 需要特別注意三個新點：

1. **Dart VM/tool split**：Flutter CLI 使用 Termux JIT `dart`，但 engine snapshots 仍需要配套 `dartvm` / `dartaotruntime`，所以 `build_dart()` 與 deb validator 必須檢查三者。
2. **Flutter Tools Android host**：Termux 上 Dart 回報 `Platform.operatingSystem == "android"`，必須把 host artifact lookup 映射到 Linux ARM64。
3. **Flutter Gradle plugin**：3.44 的 `FlutterPlugin.kt` 會直接 import `PLATFORM_ABI_LIST`，post-install 的 ARM64-only `FlutterPluginConstants.kt` 模板必須保留這個 symbol，並清理 Gradle included-build cache。

`debuild` 會重新打包整個 SDK（約 6-8 分鐘），但不會重新編譯 engine；不要把它和 `ninja` build 混在一起判斷耗時。

## CI/CD 與裝置驗證

完整引擎 build 仍然應在 WSL/self-hosted runner 執行，但 PR 可以先跑輕量檢查：

```bash
python -m py_compile build.py package.py sysroot.py utils.py scripts/ci/check_repo.py
bash -n scripts/install/post_install.sh scripts/test/gh_e2e_test.sh scripts/device/termux_smoke.sh
python scripts/ci/check_repo.py
git diff --check
```

GitHub Actions 目前拆成四條線：

- `.github/workflows/ci.yml`：PR/push 的 GitHub-hosted sanity checks。
- `.github/workflows/build-deb.yml`：手動 self-hosted Linux/WSL 完整 `.deb` build，可選 release publish。
- `.github/workflows/device-smoke.yml`：手動 self-hosted Windows + ADB 平板 smoke test。
- `.github/workflows/release-check.yml`：Release asset metadata / SHA256 檢查。

細節見 [`docs/CI_CD.md`](docs/CI_CD.md)。

## 技術架構總覽

### 我們編譯的組件（WSL 交叉編譯）

| 組件 | 檔案 | 大小 | 用途 |
|------|------|------|------|
| **Dart CLI** | `dart-sdk/bin/dart` | ~50MB | Flutter CLI；post-install 會替換成 Termux JIT Dart |
| **Dart VM** | `dart-sdk/bin/dartvm`, `dartaotruntime` | ~50MB | 執行 engine snapshots / AOT runtime |
| **Flutter Engine** | `libflutter_linux_gtk.so` | ~106MB | Linux 桌面運行時 |
| **gen_snapshot (Linux)** | `linux-arm64/gen_snapshot` | ~30MB | `flutter build linux` |
| **gen_snapshot (Android)** | `android-arm64-release/.../gen_snapshot` | ~30MB | `flutter build apk` |
| **impellerc** | `impellerc` | ~20MB | Shader 編譯器 |
| **const_finder** | `const_finder.dart.snapshot` | ~1MB | Icon tree shaking |

### 下載的預編譯組件（第三方）

| 來源 | 組件 | 用途 |
|------|------|------|
| [mumumusuc/termux-android-sdk](https://github.com/mumumusuc/termux-android-sdk) | aapt2, d8, build-tools | Android 構建工具 |
| [lzhiyong/termux-ndk](https://github.com/lzhiyong/termux-ndk) | ARM64 NDK (clang, linker) | Native 編譯 |
| Google Storage | Dart snapshots (dds_aot, etc.) | Hot reload 支援 |

### 應用的補丁

| 補丁檔案 | 解決的問題 |
|----------|-----------|
| `patches/3.44.0/engine.patch` | Bionic TLS 對齊、`-llog -lm` 連結、dynamic linker 路徑、NDK clang runtime 偵測 |
| `patches/3.44.0/dart.patch` | Dart VM / profiler shutdown Termux 適配 |
| `post_install.sh` → `FlutterPluginConstants.kt` | 預設只編譯 ARM64，且保留 Flutter 3.44 `PLATFORM_ABI_LIST` |
| `post_install.sh` | NDK wrapper、sysroot symlinks、官方 snapshots、Flutter Tools Android-host patches、cache cleanup |

### 架構圖

```
┌─────────────────────────────────────────────────────────────────┐
│                        WSL 構建環境                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Dart SDK    │  │ Flutter     │  │ gen_snapshot            │  │
│  │ (ARM64)     │  │ Engine      │  │ ├─ Linux ARM64          │  │
│  │             │  │ (ARM64)     │  │ └─ Android ARM64        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         │               │                    │                   │
│         └───────────────┴────────────────────┘                   │
│                         │                                        │
│                    [打包 deb]                                    │
│                         │                                        │
└─────────────────────────┼────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Termux 運行環境                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ 我們的 deb  │  │ Android SDK │  │ ARM64 NDK               │  │
│  │ (編譯產物)  │  │ (下載)      │  │ (下載)                  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         │               │                    │                   │
│         └───────────────┴────────────────────┘                   │
│                         │                                        │
│              [post_install.sh 整合]                              │
│                         │                                        │
│                         ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ flutter doctor ✅  flutter build apk ✅  flutter run ✅  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 構建環境需求

- Windows 11 + WSL2 (Ubuntu 22.04+)
- 至少 100GB 可用磁碟空間
- 至少 16GB RAM
- 穩定的網路連接

## 完整構建流程

### 1. 安裝 WSL 依賴

```bash
# 在 Ubuntu WSL 中執行
sudo apt update
sudo apt install -y git curl python3 python3-pip ninja-build pkg-config
pip3 install fire loguru toml pyyaml
```

### 2. 設置 depot_tools

```bash
cd ~
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$HOME/depot_tools:$PATH"
echo 'export PATH="$HOME/depot_tools:$PATH"' >> ~/.bashrc
```

### 3. 克隆專案

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/ImL1s/termux-flutter-wsl.git termux-flutter
cd termux-flutter
```

### 4. 同步 Flutter Engine 源碼

```bash
python3 build.py clone   # 克隆 Flutter
python3 build.py sync    # 同步依賴（約 30GB，需要數小時）
```

### 5. 應用補丁

```bash
python3 build.py patch_engine
```

### 6. 構建 Sysroot

```bash
python3 build.py sysroot --arch=arm64
```

### 7. 一鍵構建（推薦）

```bash
# 新增：一個命令構建所有組件
python3 build.py build_all --arch=arm64
```

這個命令會自動完成：
1. 配置 Linux debug 構建
2. 編譯 Flutter engine
3. 編譯 dart 二進制（關鍵！）
4. 配置 Android gen_snapshot 構建
5. 編譯 Android gen_snapshot
6. 打包 deb

或手動分步構建：

```bash
# Linux debug (用於 flutter run -d linux)
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug
python3 build.py build_dart --arch=arm64 --mode=debug  # 重要：單獨編譯 dart

# Android gen_snapshot (用於 flutter build apk)
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release

# 打包 deb
python3 build.py debuild --arch=arm64
```

### 8. 產出檔案

構建完成後，deb 包位於：
```
release/flutter_3.44.0_aarch64.deb
```

## deb 包內容

| 組件 | 路徑 | 用途 |
|------|------|------|
| Flutter SDK | /data/data/com.termux/files/usr/opt/flutter | 主程式 |
| dart 二進制 | .../dart-sdk/bin/dart | flutter 命令核心 |
| Linux gen_snapshot | .../engine/linux-arm64/gen_snapshot | flutter run -d linux |
| Android gen_snapshot | .../engine/android-arm64-release/linux-arm64/gen_snapshot | flutter build apk |

## 驗證構建

```bash
# 檢查所有必要檔案
ls -la flutter/engine/src/out/linux_debug_arm64/dart-sdk/bin/dart  # 關鍵！
ls -la flutter/engine/src/out/linux_debug_arm64/gen_snapshot
ls -la flutter/engine/src/out/android_release_arm64/clang_arm64/gen_snapshot
```

## 問題分析與解決 (2025-12-28)

### 原始問題
- `flutter run -d linux` ✓ 可以運行
- `flutter build apk --release` ✗ 失敗（dart 版本問題）

### 根本原因
**`ninja flutter` 不會編譯 dart 二進制！**

deb 包中 `bin/cache/dart-sdk/bin/dart` 二進制文件缺失，導致：
- flutter 命令無法正確執行
- gen_snapshot 版本不匹配錯誤

### 解決方案
新增 `build_dart` 方法，單獨編譯 dart 二進制並複製到 dart-sdk/bin/：

```bash
python3 build.py build_dart --arch=arm64 --mode=debug
```

或使用一鍵構建：

```bash
python3 build.py build_all --arch=arm64
```

### deb 包內容確認（修復後）
```
✓ bin/cache/dart-sdk/bin/dart (102MB)
✓ bin/cache/artifacts/engine/linux-arm64/gen_snapshot (6.9MB)
✓ bin/cache/artifacts/engine/android-arm64-release/linux-arm64/gen_snapshot (6.4MB)
```

## 常見問題

### 編譯失敗：ninja 錯誤
確保補丁已正確應用：
```bash
cd flutter/engine/src/flutter
git diff shell/platform/embedder/BUILD.gn
```

### 缺少依賴
```bash
python3 build.py sysroot --arch=arm64
```

### vpython3 not found
確保 depot_tools 在 PATH 中：
```bash
export PATH="$HOME/depot_tools:$PATH"
```

### 磁碟空間不足
Flutter Engine 源碼約 30GB，編譯產物約 20GB，至少需要 60GB 空間。

## Termux 使用前設置（3.44.0）

deb 安裝後要在 Termux 內執行：

```bash
dpkg -i flutter_3.44.0_aarch64.deb
apt --fix-broken install -y
bash $PREFIX/share/flutter/post_install.sh
source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

`post_install.sh` 會處理舊版文件中需要手動做的大多數事情：Android API 34/36、cmdline-tools、build-tools symlinks、NDK clang wrappers、CMake host tag、Dart snapshots、Flutter Tools Android-host patches、Gradle plugin ARM64-only ABI、ELF cleaner、shebang 修正與 cache cleanup。

### 每個 APK 專案仍需手動設定

```bash
flutter create myapp
cd myapp
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew
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

建置：

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

### 每個 Linux desktop 專案仍需手動設定

```bash
flutter create mylinux --platforms=linux
cd mylinux
sed -i '1i set(CMAKE_SYSTEM_NAME Linux)' linux/CMakeLists.txt
flutter build linux --release
```

## 構建常見問題與解決方案 (坑) 🔥

這一節記錄構建過程中遇到的各種問題及解決方案，避免重複踩坑。

### 1. vpython3 not found (depot_tools 問題)

**問題描述：**
```
/bin/sh: vpython3: not found
```

ninja 編譯時找不到 vpython3。這是因為 depot_tools 的 vpython3 是一個指向 vpython 的 symlink，而 vpython 也是壞的。

**解決方案：**
手動創建 vpython3 wrapper script：

```bash
cd flutter/engine/src/flutter/third_party/depot_tools/.cipd_bin

# 刪除壞的 symlink
rm -f vpython3

# 創建 wrapper script
cat > vpython3 << 'EOF'
#!/bin/bash
exec python3 "$@"
EOF

chmod +x vpython3
```

**注意：** 如果在 Windows/WSL 環境，確保 script 是 LF 換行，不是 CRLF：
```bash
# 修復 CRLF 問題
cat vpython3 | tr -d '\r' > vpython3.tmp && mv vpython3.tmp vpython3
chmod +x vpython3
```

### 2. openjdk-17 不存在 (Termux 套件問題)

**問題描述：**
```
android-sdk depends on openjdk-17; however:
  Package openjdk-17 is not installed.
```

android-sdk 包依賴 openjdk-17，但 Termux 只有 openjdk-21。

**解決方案：**
```bash
# 安裝 openjdk-21
pkg install openjdk-21

# 強制配置 android-sdk（忽略依賴）
dpkg --force-depends --configure android-sdk
```

**永久修復：** package.yaml 已更新，依賴改為 openjdk-21：
```yaml
Depends: git, which, gtk3, xorgproto, ninja, cmake, clang, pkg-config, openjdk-21
```

### 3. libflutter_linux_gtk.so 缺失 (Linux 桌面支援)

**問題描述：**
```
flutter build linux --debug
Error: Could not find libflutter_linux_gtk.so
```

`flutter build linux` 需要 `libflutter_linux_gtk.so`，但預設構建不會編譯這個目標。

**解決方案：**
在 `build.py` 的 `build()` 方法中啟用 flutter_gtk 目標：

```python
cmd = [
    'ninja', '-C', utils.target_output(root, arch, mode),
    'flutter',
    # 必須啟用這一行來構建 Linux 桌面支援
    'flutter/shell/platform/linux:flutter_gtk',
]
```

然後重新構建：
```bash
python3 build.py build --arch=arm64 --mode=debug
```

### 4. dartaotruntime 缺失

**問題描述：**
```
Error: dartaotruntime not found
```

`flutter build apk --release` 需要 dartaotruntime。

**解決方案：**
```bash
# 複製 dartaotruntime_product 到 dart-sdk/bin
cp flutter/engine/src/out/linux_debug_arm64/dartaotruntime_product \
   flutter/engine/src/out/linux_debug_arm64/dart-sdk/bin/dartaotruntime
```

### 5. CRLF 換行符問題 (Windows/WSL)

**問題描述：**
```
C:/Program: No such file or directory
```

在 Windows 創建的 shell script 可能有 CRLF 換行符，導致執行失敗。

**解決方案：**
```bash
# 轉換為 LF
cat script.sh | tr -d '\r' > script.tmp && mv script.tmp script.sh
chmod +x script.sh

# 或使用 dos2unix
dos2unix script.sh
```

### 6. ADB 遠程安裝失敗

**問題描述：**
使用 `am broadcast` 發送命令到 Termux 但命令不執行。

**解決方案：**
需要在 Termux 中啟用外部應用執行權限：

```bash
# 在 Termux 中執行
echo "allow-external-apps=true" >> ~/.termux/termux.properties
termux-reload-settings
```

或直接在 Termux 中手動執行安裝命令。

### 7. X11 相關依賴

**問題描述：**
`flutter run -d linux` 需要 X11 環境。

**解決方案：**
在 Termux 中安裝 X11 repo 和相關套件：
```bash
pkg install x11-repo
pkg install termux-x11-nightly

# 啟動 Termux:X11
termux-x11 &

# 設置 DISPLAY
export DISPLAY=:0

# 然後運行 Flutter 應用
flutter run -d linux
```

### 8. gen_snapshot 版本不匹配

**問題描述：**
```
version differs from vm's version
```

dart 和 gen_snapshot 版本不一致。

**解決方案：**
確保使用 `build_all` 一次構建所有組件：
```bash
python3 build.py build_all --arch=arm64
```

或者手動確保 dart 和 gen_snapshot 來自同一次構建：
```bash
python3 build.py build_dart --arch=arm64 --mode=debug
```

### 9. ninja: error: 'xxx' does not exist

**問題描述：**
配置後立即構建出現文件不存在錯誤。

**解決方案：**
確保配置完成後再構建：
```bash
# 先配置
python3 build.py configure --arch=arm64 --mode=debug

# 等配置完成，再構建
python3 build.py build --arch=arm64 --mode=debug
```

### 10. TLS segment underaligned (Bionic linker 問題)

**問題描述：**
```
error: "dart": executable's TLS segment is underaligned: alignment is 8 (skew 0), needs to be at least 64 for ARM64 Bionic
```

在 Termux 運行 `flutter doctor` 或任何 dart 命令時出現此錯誤。

**原因：**
dart 二進制編譯時使用了 glibc 的動態連結器 (`/lib/ld-linux-aarch64.so.1`)，而非 Android Bionic (`/system/bin/linker64`)。Android Bionic 要求 TLS (Thread Local Storage) 段對齊到 64 字節。

**解決方案：**
在 `build/config/termux/BUILD.gn` 的 `executable_ldconfig` 配置中添加 bionic linker：

```gn
config("executable_ldconfig") {
  if (current_toolchain == "//build/toolchain/termux:${current_cpu}") {
    ldflags = [
      "-Bdynamic",
      "-Wl,-z,nocopyreloc",
      "-Wl,--dynamic-linker=/system/bin/linker64",  # 必須添加！
    ]
  } else {
    configs = ["//build/config/gcc:executable_ldconfig"]
  }
}
```

然後重新配置和構建 dart：
```bash
python3 build.py configure --arch=arm64 --mode=debug
ninja -C flutter/engine/src/out/linux_debug_arm64 exe.unstripped/dart -j24
```

---

## 測試驗證清單

構建完成後，使用以下清單驗證：

```bash
# 1. 檢查必要文件存在
ls -la flutter/engine/src/out/linux_debug_arm64/dart-sdk/bin/dart
ls -la flutter/engine/src/out/linux_debug_arm64/gen_snapshot
ls -la flutter/engine/src/out/linux_debug_arm64/libflutter_linux_gtk.so
ls -la flutter/engine/src/out/android_release_arm64/clang_arm64/gen_snapshot

# 2. 部署到 Termux 後測試（執行 post_install.sh 後）
flutter doctor -v               # ✅ 已驗證
flutter create test_app         # ✅ 已驗證
cd test_app
flutter build apk --release     # ✅ 已驗證
flutter build apk --debug       # ✅ 已驗證
flutter build linux --debug     # ✅ 已驗證（需要 Termux:X11）
flutter run                     # ✅ 已驗證（Hot Reload 支援）
```

## 目標版本狀態 (v3.44.0)

### 功能測試結果（2026-06-01 更新）

| 功能 | 狀態 | 說明 |
|------|------|------|
| `flutter --version` | ✅ 正常 | Flutter 3.44.0 / Tools Dart 3.12.1 |
| `dart --version` | ✅ 正常 | Termux JIT Dart 3.12.1 (`android_arm64`) |
| `dartvm --version` | ✅ 正常 | post-install `dartvm` resolves to Dart 3.12.1 (`android_arm64`) |
| `flutter doctor -v` | ✅ 正常 | unknown channel / no device 是預期警告 |
| `flutter create` | ✅ 正常 | 可創建 Android + Linux 專案 |
| `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons` | ✅ 正常 | 需執行 post_install.sh，僅支援 android-arm64 |
| `flutter build linux --release` | ✅ 正常 | 產出 ARM64 ELF bundle |
| `flutter run` (Android) | ✅ 支援 | 需要 Termux 內 ADB 連線後才會顯示 device |

### 已知限制

#### 1. Android APK 僅支援 ARM64

**問題：** `flutter build apk --release` 僅支援 `android-arm64` 平台。

**原因：** 我們只能編譯 ARM64 版本的 gen_snapshot：
- `android-arm` (32-bit): BoringSSL 有 32-bit shift overflow 編譯錯誤
- `android-x64`: ARM64 sysroot 無法用於 x64 交叉編譯

**影響：** 構建的 APK 僅能在 ARM64 設備運行，不支援 ARM32 或 x86 模擬器。

**使用方式：** 明確指定 ARM64，避免舊 cache 或專案設定誤判：
```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

#### 2. Debug vs Release 模式不匹配 (技術背景)

當前 deb 包使用 **debug 模式** 構建的二進制：
- `dart` - debug 模式
- `dartaotruntime` - debug 模式
- `frontend_server_aot.dart.snapshot` - debug 模式
- `gen_snapshot` - debug 模式

這是因為 release 模式構建在 WSL 環境遇到 sysroot 衝突問題（glibc vs bionic headers）。

**對用戶的影響：**
- `flutter doctor` ✅ 正常運行
- `flutter build apk --release` ✅ 正常運行（使用 android gen_snapshot）
- `flutter run -d linux` ⚠️ 僅能使用 debug 模式

### Release 模式構建問題 (開發者參考)

如果嘗試構建 release 模式，可能遇到：

#### sysroot header 衝突
```
error: typedef redefinition with different types ('__mbstate_t' vs 'struct mbstate_t')
```

**原因：** sysroot 同時包含 glibc 和 bionic headers：
- `/sysroot/usr/include/` - glibc headers
- `/sysroot/data/data/com.termux/files/usr/include/` - Termux/bionic headers

**解決方向：** 需要清理 sysroot，只保留 bionic headers。

#### BoringSSL getrandom syscall 問題
```
error: This system call is not available on Android
```

**原因：** BoringSSL 偵測到 getrandom() syscall 不可用。

**解決方向：** 需要添加 `__ANDROID__` define 或修補 BoringSSL。

---

## Termux APK 構建完整設置指南（3.44.0）

> **📌 重要：runtime 層級由 `post_install.sh` 自動完成；本節只列每個 Flutter project 必須保留的設定。**

### 1. 固定 Android API / ABI

```kotlin
android {
    compileSdk = 34

    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
}
```

### 2. 指定 Termux aapt2

```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

### 3. 修正 Gradle wrapper shebang

```bash
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew
```

### 4. 建置與驗證

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
ls -lh build/app/outputs/flutter-apk/app-release.apk
```

若遇到 Flutter 3.44 Gradle plugin 的 Kotlin 錯誤（例如 `PLATFORM_ABI_LIST` unresolved），表示 post-install 模板或 Gradle cache 是舊的：

```bash
bash $PREFIX/share/flutter/post_install.sh
./android/gradlew --stop || true
rm -rf ~/.gradle/caches .gradle android/.gradle build android/app/build
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

### 5. Linux desktop build

```bash
sed -i '1i set(CMAKE_SYSTEM_NAME Linux)' linux/CMakeLists.txt
flutter build linux --release
```

## 升級 Flutter 版本

當 Flutter 發布新版本時，按以下步驟升級：

### 1. 準備新版本目錄

```bash
# 複製現有 patches 作為起點
cp -r patches/3.44.0 patches/3.45.0
```

### 2. 更新 build.toml

```toml
[flutter]
tag = '3.45.0'  # 更新版本號
```

### 3. 同步新版本

```bash
python3 build.py clone
python3 build.py sync  # 這會下載新版本的 engine
```

### 4. 嘗試套用 patches

```bash
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
python3 build.py patch_flutter_sdk
```

**如果 patch 失敗：**

1. 查看錯誤訊息，找出衝突的位置
2. 手動修復 `patches/3.45.0/` 中的 patch 檔案
3. 重新執行 patch 命令

### 5. 建置新版本

```bash
python3 build.py sysroot --arch=arm64
python3 build.py build_all --arch=arm64
python3 build.py debuild --arch=arm64
```

### 6. 測試

在乾淨的 Termux 環境測試所有功能：

```bash
# 安裝
dpkg -i flutter_3.45.0_aarch64.deb
apt-get install -f
bash $PREFIX/share/flutter/post_install.sh

# 測試
flutter doctor -v
flutter create test_app && cd test_app
flutter build apk --release
flutter build linux
```

### 7. 發布

```bash
# 提交變更
git add -A
git commit -m "feat: Support Flutter 3.45.0"

# 打 tag
git tag -a v3.45.0-termux -m "Flutter 3.45.0 for Termux ARM64"
git push origin master --tags

# 建立 GitHub Release
gh release create v3.45.0-termux \
  --title "Flutter 3.45.0 for Termux" \
  --notes "See CHANGELOG.md" \
  flutter_3.45.0_aarch64.deb
```

### Patch 維護技巧

1. **保持 patch 最小化**：只修改必要的部分
2. **加上註解**：在 patch 中說明為什麼需要這個修改
3. **版本隔離**：每個 Flutter 版本有獨立的 patch 目錄
4. **記錄變更**：更新 CHANGELOG.md

---

## 更新日誌

### 2026-06-01 v3.44.0
- ✅ Flutter 3.44.0 / Dart 3.12 deb 打包完成並通過 artifact validator
- ✅ Termux smoke：doctor / create / build apk / build linux
- ✅ 補上 Flutter Gradle plugin `PLATFORM_ABI_LIST` 與 cache cleanup
- ✅ 補上 GitHub-hosted PR CI、self-hosted full build / tablet smoke workflow、release metadata check
- 🧹 將 GitHub Release E2E 與裝置 smoke 腳本整理到 `scripts/test/`、`scripts/device/`
- 📝 重新整理 README、INSTALL、RELEASE_NOTES、CHANGELOG 的 3.44.0 狀態

### 2025-12-29 v5
- ✅ `flutter run` + Hot Reload 完整支援
- ✅ `post_install.sh` 自動下載官方 Dart SDK snapshots（hot reload 必需）
- ✅ `post_install.sh` 自動執行 termux-elf-cleaner（修復 linker warning）
- 📝 修正文檔中的 NDK 版本和路徑
- 📝 更新功能狀態表

### 2025-12-29 v4
- ✅ `flutter build apk --release` 完全正常
- ✅ `flutter build apk --debug` 完全正常
- ✅ `flutter build apk --profile` 完全正常
- ✅ APK 安裝並運行正常
- 📝 完整記錄 APK 構建的所有必要步驟

### 2025-12-29 v3
- ✅ `flutter doctor` 完全正常
- ✅ `flutter build apk --release` 正常（僅 android-arm64）
- ⚠️ 文檔化當前 debug/release 模式限制
- ⚠️ 文檔化 sysroot 衝突問題供未來修復參考

### 2025-12-28 v2
- ✅ 舊版記錄：曾將 `flutter build apk --release` 預設改為 ARM64；3.44.0 起仍建議顯式加 `--target-platform android-arm64`
- ✅ 新增 flutter_gtk 構建支援 `flutter build linux`
- ✅ 新增構建常見問題與解決方案
- ✅ 更新依賴從 openjdk-17 到 openjdk-21
