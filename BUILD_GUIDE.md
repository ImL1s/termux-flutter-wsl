# Flutter Termux 完整構建指南

本文檔說明如何從零開始構建包含 Android gen_snapshot 的 Flutter deb 包。

## 技術架構總覽

### 我們編譯的組件（WSL 交叉編譯）

| 組件 | 檔案 | 大小 | 用途 |
|------|------|------|------|
| **Dart SDK** | `dart-sdk/bin/dart` | ~50MB | Flutter 命令核心 |
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
| `patches/engine.patch` | Bionic TLS 對齊、`-llog -lm` 連結、dynamic linker 路徑 |
| `patches/dart.patch` | Dart SDK Termux 適配 |
| `FlutterPluginConstants.kt` | 預設只編譯 ARM64（其他架構無法交叉編譯） |
| `post_install.sh` | NDK wrapper、sysroot symlinks、下載官方 snapshots |

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

## Termux 使用前設置 (2025-12-28 更新)

### 額外需要編譯的組件

除了基本構建外，`flutter build apk` 還需要以下組件：

1. **dartaotruntime_product** - 用於運行 AOT snapshots
2. **impellerc** - 用於編譯 shaders
3. **const_finder.dart.snapshot** - 用於 icon tree shaking

```bash
# 在 WSL 中編譯額外組件
export PATH="$HOME/depot_tools:$PATH"
cd flutter

# 編譯 impellerc
ninja -C engine/src/out/linux_debug_arm64 flutter/impeller/compiler:impellerc

# 編譯 const_finder
ninja -C engine/src/out/linux_debug_arm64 flutter/tools/const_finder:const_finder

# const_finder 輸出在 gen/ 目錄，複製到正確位置
cp engine/src/out/linux_debug_arm64/gen/const_finder.dart.snapshot engine/src/out/linux_release_arm64/

# 複製 dartaotruntime_product 到 dart-sdk
cp engine/src/out/linux_debug_arm64/dartaotruntime_product engine/src/out/linux_debug_arm64/dart-sdk/bin/dartaotruntime

# 重新打包 deb
cd ..
python3 build.py debuild --arch=arm64
```

### Termux 環境配置

安裝 deb 後，還需要做以下設置才能運行 `flutter build apk`：

#### 1. 安裝 ARM64 NDK
標準 Android NDK 是 x86_64，無法在 Termux 運行。需要使用 lzhiyong 的 ARM64 NDK：

```bash
# 下載 ARM64 NDK（約 550MB）
cd ~
wget https://github.com/lzhiyong/termux-ndk/releases/download/android-ndk/android-ndk-r29-aarch64.7z

# 解壓到 Android SDK 目錄
mkdir -p $ANDROID_HOME/ndk
pkg install p7zip
7z x android-ndk-r29-aarch64.7z -o$ANDROID_HOME/ndk/
mv $ANDROID_HOME/ndk/android-ndk-r29 $ANDROID_HOME/ndk/29.0.14206865
```

#### 2. 配置項目使用 ARM64 NDK
在 Flutter 專案的 `android/local.properties` 中添加：

```properties
ndk.dir=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
```

在 `android/app/build.gradle.kts` 中設置正確的 NDK 版本：

```kotlin
ndkVersion = "29.0.14206865"  // 或你的 NDK 版本
```

#### 3. 修復 CMake
Android SDK 的 CMake 是 x86_64，需要用 Termux 的：

```bash
# 安裝 Termux cmake 和 ninja
pkg install cmake ninja

# 替換 SDK CMake
rm -rf $ANDROID_HOME/cmake/3.22.1/bin
mkdir -p $ANDROID_HOME/cmake/3.22.1/bin
ln -s /data/data/com.termux/files/usr/bin/cmake $ANDROID_HOME/cmake/3.22.1/bin/cmake
ln -s /data/data/com.termux/files/usr/bin/ninja $ANDROID_HOME/cmake/3.22.1/bin/ninja
```

#### 4. 修復 AAPT2
Gradle 下載的 AAPT2 是 x86_64，需要用 SDK build-tools 中的 ARM64 版本：

```bash
# 找到 Gradle 緩存的 aapt2 位置
AAPT2_CACHE=~/.gradle/caches/*/transforms/*/transformed/aapt2-*-linux/aapt2

# 替換為 ARM64 版本
rm -f $AAPT2_CACHE
ln -s $ANDROID_HOME/build-tools/35.0.0/aapt2 $AAPT2_CACHE
```

#### 5. 複製 flutter_patched_sdk_product
`flutter build apk --release` 需要 product SDK：

```bash
mkdir -p $FLUTTER_ROOT/bin/cache/artifacts/engine/common/flutter_patched_sdk_product
cp -r $FLUTTER_ROOT/bin/cache/artifacts/engine/common/flutter_patched_sdk/* \
      $FLUTTER_ROOT/bin/cache/artifacts/engine/common/flutter_patched_sdk_product/
```

### 完整構建命令

```bash
source /data/data/com.termux/files/usr/etc/profile.d/flutter.sh
export ANDROID_HOME=/data/data/com.termux/files/usr/opt/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

cd your_flutter_project
flutter build apk --release
```

### 注意事項

- **無需 `--target-platform` 參數！** Flutter SDK 已修改為預設只編譯 ARM64
- 首次構建需要下載 Gradle 依賴，約需 5-10 分鐘
- APK 輸出在 `build/app/outputs/flutter-apk/app-release.apk`

---

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

### 功能測試結果 (2025-12-29 更新)

| 功能 | 狀態 | 說明 |
|------|------|------|
| `flutter doctor` | ✅ 正常 | Dart, gen_snapshot 版本匹配 |
| `flutter create` | ✅ 正常 | 可創建新專案 |
| `flutter build apk --release` | ✅ 正常 | 需執行 post_install.sh，僅支援 android-arm64 |
| `flutter build apk --debug` | ✅ 正常 | 需執行 post_install.sh |
| `flutter build linux` | ✅ 正常 | 需要 Termux:X11 來運行 |
| `flutter run -d linux` | ✅ 正常 | 需要 Termux:X11 |
| `flutter run` (Android) | ✅ 正常 | **Hot Reload 支援！** 需執行 post_install.sh |

### 已知限制

#### 1. Android APK 僅支援 ARM64

**問題：** `flutter build apk --release` 僅支援 `android-arm64` 平台。

**原因：** 我們只能編譯 ARM64 版本的 gen_snapshot：
- `android-arm` (32-bit): BoringSSL 有 32-bit shift overflow 編譯錯誤
- `android-x64`: ARM64 sysroot 無法用於 x64 交叉編譯

**影響：** 構建的 APK 僅能在 ARM64 設備運行，不支援 ARM32 或 x86 模擬器。

**使用方式：** APK 構建預設只產出 ARM64，無需額外參數：
```bash
flutter build apk --release
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

## Termux APK 構建完整設置指南 (2025-12-29)

> **📌 重要：以下所有步驟已由 `post_install.sh` 自動完成！**
>
> 使用一鍵安裝腳本或執行 `bash $PREFIX/share/flutter/post_install.sh` 後，無需手動執行以下步驟。
> 本節僅供開發者參考或手動排錯使用。

安裝 deb 包後，需要以下額外設置才能使 `flutter build apk` 正常工作。

### 1. 安裝 Android 平台 API 34

Termux 的 aapt2 有 bug，無法處理 API 35/36 的 android.jar（[Issue #22667](https://github.com/termux/termux-packages/issues/22667)）。

```bash
# 下載並安裝 API 34
cd /data/data/com.termux/files/usr/opt/android-sdk/platforms
curl -L -o platform-34.zip 'https://dl.google.com/android/repository/platform-34-ext7_r02.zip'
unzip -q platform-34.zip
rm platform-34.zip
```

### 2. 配置 Flutter 僅構建 ARM64

修改 FlutterPluginConstants.kt 以避免構建 x86_64（Termux 不支援）：

```bash
cat > /data/data/com.termux/files/usr/opt/flutter/packages/flutter_tools/gradle/src/main/kotlin/FlutterPluginConstants.kt << 'EOF'
package com.flutter.gradle

object FlutterPluginConstants {
    private const val PLATFORM_ARM32 = "android-arm"
    private const val PLATFORM_ARM64 = "android-arm64"
    private const val PLATFORM_X86_64 = "android-x64"

    private const val ARCH_ARM32 = "armeabi-v7a"
    private const val ARCH_ARM64 = "arm64-v8a"
    private const val ARCH_X86_64 = "x86_64"

    const val INTERMEDIATES_DIR = "intermediates"
    const val FLUTTER_STORAGE_BASE_URL = "FLUTTER_STORAGE_BASE_URL"
    const val DEFAULT_MAVEN_HOST = "https://storage.googleapis.com"

    @JvmStatic val PLATFORM_ARCH_MAP =
        mapOf(
            PLATFORM_ARM32 to ARCH_ARM32,
            PLATFORM_ARM64 to ARCH_ARM64,
            PLATFORM_X86_64 to ARCH_X86_64
        )

    @JvmStatic val ABI_VERSION =
        mapOf(
            ARCH_ARM32 to 1,
            ARCH_ARM64 to 2,
            ARCH_X86_64 to 4
        )

    // Modified for Termux: only arm64 supported
    @JvmStatic val DEFAULT_PLATFORMS =
        listOf(
            PLATFORM_ARM64
        )
}
EOF
```

### 3. 配置 NDK clang wrapper

Termux 的 clang 需要正確的庫路徑，創建 wrapper script：

```bash
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
mkdir -p $NDK/toolchains/llvm/prebuilt/bin

# 備份原始 clang（如果存在）
mv $NDK/toolchains/llvm/prebuilt/bin/clang $NDK/toolchains/llvm/prebuilt/bin/clang.orig 2>/dev/null

# 創建 clang wrapper
cat > $NDK/toolchains/llvm/prebuilt/bin/clang << 'EOF'
#!/bin/sh
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
SYSROOT=$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot
CLANG_VERSION=$(ls -1 $NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/ | sort -V | tail -n 1)
CLANG_LIB=$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/$CLANG_VERSION/lib/linux

ARCH=""
for arg in "$@"; do
    case "$arg" in
        --target=aarch64*) ARCH="aarch64" ;;
        --target=arm*) ARCH="arm" ;;
    esac
done

if [ "$ARCH" = "aarch64" ]; then
    LIB_PATH=$SYSROOT/usr/lib/aarch64-linux-android
    CLANG_LIB_ARCH=$CLANG_LIB/aarch64
elif [ "$ARCH" = "arm" ]; then
    LIB_PATH=$SYSROOT/usr/lib/arm-linux-androideabi
    CLANG_LIB_ARCH=$CLANG_LIB/arm
else
    exec /data/data/com.termux/files/usr/bin/clang "$@"
fi

exec /data/data/com.termux/files/usr/bin/clang -L$LIB_PATH -L$CLANG_LIB_ARCH "$@"
EOF

chmod +x $NDK/toolchains/llvm/prebuilt/bin/clang

# 創建 clang++ wrapper
cat > $NDK/toolchains/llvm/prebuilt/bin/clang++ << 'EOF'
#!/bin/sh
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
SYSROOT=$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot
CLANG_VERSION=$(ls -1 $NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/ | sort -V | tail -n 1)
CLANG_LIB=$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/$CLANG_VERSION/lib/linux

ARCH=""
for arg in "$@"; do
    case "$arg" in
        --target=aarch64*) ARCH="aarch64" ;;
        --target=arm*) ARCH="arm" ;;
    esac
done

if [ "$ARCH" = "aarch64" ]; then
    LIB_PATH=$SYSROOT/usr/lib/aarch64-linux-android
    CLANG_LIB_ARCH=$CLANG_LIB/aarch64
elif [ "$ARCH" = "arm" ]; then
    LIB_PATH=$SYSROOT/usr/lib/arm-linux-androideabi
    CLANG_LIB_ARCH=$CLANG_LIB/arm
else
    exec /data/data/com.termux/files/usr/bin/clang++ "$@"
fi

exec /data/data/com.termux/files/usr/bin/clang++ -L$LIB_PATH -L$CLANG_LIB_ARCH "$@"
EOF

chmod +x $NDK/toolchains/llvm/prebuilt/bin/clang++
```

### 4. 修補 NDK toolchain cmake

移除 `-static-libstdc++`，否則會導致 `-lc++_shared` 連結錯誤：

```bash
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
TOOLCHAIN=$NDK/build/cmake/android-legacy.toolchain.cmake

# 備份
cp $TOOLCHAIN ${TOOLCHAIN}.bak

# 移除 -static-libstdc++
sed -i 's/list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/# Disabled for Termux: list(APPEND ANDROID_LINKER_FLAGS "-static-libstdc++")/' $TOOLCHAIN
```

### 5. 創建 NDK sysroot 符號連結

```bash
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
PREBUILT=$NDK/toolchains/llvm/prebuilt

# sysroot 符號連結
ln -sf linux-x86_64/sysroot $PREBUILT/sysroot 2>/dev/null

# clang lib 版本由 wrapper 動態偵測（r29 是 clang/21；不要硬編碼 18/21）
CLANG_VERSION=$(ls -1 $PREBUILT/linux-x86_64/lib/clang/ | sort -V | tail -n 1)

# 目標三元組符號連結
SYSROOT=$PREBUILT/linux-x86_64/sysroot/usr/lib
ln -sf aarch64-linux-android $SYSROOT/aarch64-none-linux-android 2>/dev/null
ln -sf aarch64-linux-android/24 $SYSROOT/aarch64-none-linux-android24 2>/dev/null
```

### 6. 複製運行時庫到 sysroot

```bash
NDK=/data/data/com.termux/files/usr/opt/android-sdk/ndk/29.0.14206865
CLANG_VERSION=$(ls -1 $NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/ | sort -V | tail -n 1)
CLANG_LIB=$NDK/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/$CLANG_VERSION/lib/linux
SYSROOT=$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib

# ARM64 庫
for f in libunwind.a libatomic.a; do
    ln -sf $CLANG_LIB/aarch64/$f $SYSROOT/aarch64-linux-android/$f 2>/dev/null
    ln -sf $CLANG_LIB/aarch64/$f $SYSROOT/aarch64-linux-android/24/$f 2>/dev/null
done

# ARM32 庫
for f in libunwind.a libatomic.a; do
    ln -sf $CLANG_LIB/arm/$f $SYSROOT/arm-linux-androideabi/$f 2>/dev/null
    ln -sf $CLANG_LIB/arm/$f $SYSROOT/arm-linux-androideabi/24/$f 2>/dev/null
done
```

### 7. 配置 Flutter 專案 (每個專案都需要)

在 `android/app/build.gradle.kts` 中：

```kotlin
android {
    compileSdk = 34  // 使用 API 34，不是 flutter.compileSdkVersion

    defaultConfig {
        targetSdk = 34  // 使用 API 34
        ndk {
            abiFilters += listOf("arm64-v8a")  // 僅 ARM64
        }
    }
}
```

在 `android/gradle.properties` 中：

```properties
org.gradle.jvmargs=-Xmx8G -XX:MaxMetaspaceSize=4G -XX:ReservedCodeCacheSize=512m -XX:+HeapDumpOnOutOfMemoryError
android.useAndroidX=true
android.enableJetifier=true
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

**注意：** `android.aapt2FromMavenOverride` 是必須的！Gradle 下載的 aapt2 是 x86_64 版本，無法在 ARM64 Termux 運行。

### 8. 完整驗證清單

```bash
# 所有模式都應該成功
flutter build apk --release   # ✅ 151MB
flutter build apk --debug     # ✅ 591MB
flutter build apk --profile   # ✅ 165MB

# 安裝 APK（需要從外部 ADB）
# 在 PC 上執行：
# scp -P 8022 <device_ip>:~/your_app/build/app/outputs/flutter-apk/app-release.apk .
# adb install app-release.apk
```

---

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
- ✅ 修復 `flutter build apk --release` 不再需要 `--target-platform android-arm64`
- ✅ 新增 flutter_gtk 構建支援 `flutter build linux`
- ✅ 新增構建常見問題與解決方案
- ✅ 更新依賴從 openjdk-17 到 openjdk-21
