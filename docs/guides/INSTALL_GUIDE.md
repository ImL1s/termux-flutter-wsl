# Termux Flutter 3.44.9 安裝指南

本指南適用於 `flutter_3.44.9-1_aarch64.deb`，目標是在 ARM64 Termux 上執行：

- `flutter doctor -v`
- `flutter create`
- `flutter build apk --release`
- `flutter build linux --release`
- `flutter run` + hot reload（需要 ADB device 連線）

## 已驗證版本

| 項目 | 值 |
|------|----|
| Flutter | 3.44.9 |
| Flutter Tools Dart | 3.12.2 |
| Dart VM (`dartvm`) | post-install `dartvm` resolves to Dart 3.12.2 (`android_arm64`) |

| 測試設備 | Samsung SM-X716B / Android 16 / ARM64 |
| deb size | 177,161,976 bytes（約 169 MiB） |
| SHA256 | `c888b305ac1ddbe06aa0f98ce3b1cfb24f3906e40fbb966ae5a487e122897901` |

## 系統需求

| 項目 | 需求 |
|------|------|
| Android | Android 11 (API 30) 或更高 |
| CPU | ARM64 / aarch64 |
| Termux | 建議 F-Droid 版或官方 GitHub release 版 |
| 儲存空間 | 至少 5GB；完整 Android SDK/NDK + Gradle cache 建議 8GB+ |
| Java | `openjdk-21` |

## 方法一：一鍵安裝（推薦）

```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o ~/install.sh
bash ~/install.sh
```

此腳本會安裝 Flutter、Android SDK/NDK、必要 Termux packages，並執行 post-install。首次執行需要下載大量檔案，請保持螢幕喚醒與網路穩定。

## 方法二：手動安裝 deb

```bash
pkg update -y
pkg install -y x11-repo git wget curl unzip openjdk-21 aapt2 android-tools cmake ninja clang

cd ~
wget https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.9-termux-1/flutter_3.44.9-1_aarch64.deb
sha256sum flutter_3.44.9-1_aarch64.deb
# 確認輸出為：c888b305ac1ddbe06aa0f98ce3b1cfb24f3906e40fbb966ae5a487e122897901

dpkg -i flutter_3.44.9-1_aarch64.deb
apt --fix-broken install -y

# 必跑：dpkg 只安裝檔案；這一步才會修補 Termux runtime。
bash $PREFIX/share/flutter/post_install.sh

source $PREFIX/etc/profile.d/flutter.sh
flutter doctor -v
```

`flutter doctor` 中以下警告通常是預期的：

- unknown channel / unknown upstream source：deb 內的 Flutter SDK 不是官方 git remote checkout。
- no connected device：尚未在 Termux 內連上 ADB device；不影響 `flutter build apk`。

## post_install.sh 做了什麼

| 類別 | 內容 |
|------|------|
| Dart | 用 Termux JIT Dart 跑 Flutter CLI，保留 engine `dartvm` / `dartaotruntime` 給 snapshots |
| Flutter Tools | 修補 Android/Termux host lookup，清掉舊 `flutter_tools` snapshot/cache |
| Gradle plugin | ARM64-only ABI；補 Flutter 3.44 需要的 `PLATFORM_ABI_LIST` |
| Android SDK | 安裝/修補 API 34/36、cmdline-tools、build-tools、licenses |
| NDK | 建立 clang wrappers、修補 CMake host tag、替換 objcopy/strip |
| Linux desktop | 允許 `flutter build linux` 在 Termux host 執行 |

升級後如果還看到舊 Gradle 或 Kotlin 錯誤，重跑：

```bash
bash $PREFIX/share/flutter/post_install.sh
rm -rf ~/.gradle/caches ~/.gradle/daemon
```

## 驗證安裝

```bash
flutter --version
dart --version
dartvm --version
flutter doctor -v
```

預期重點：

- `flutter --version` 顯示 Flutter 3.44.9。
- `dart --version` 顯示 `android_arm64`（Termux JIT Dart）。
- `dartvm --version` 顯示 `linux_arm64`（engine VM）。

## 建立 Android APK 專案 (以模式 A：本地編譯為例)

建立專案並補上 shebang：

```bash
flutter create myapp
cd myapp
sed -i '1s|#!/usr/bin/env bash|#!/data/data/com.termux/files/usr/bin/bash|' android/gradlew
```

1. 設定專案 Gradle 屬性（在 `android/gradle.properties`）：

```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
android.enableResourceOptimizations=false
shrink=false
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8
```

2. 修改 `android/app/build.gradle.kts`（設定 SDK 與關閉混淆縮減）：

```kotlin
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

3. 建置（注意：必須繞過 JIT Dart 限制的 icon tree shaking）：

```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

產物：

```text
build/app/outputs/flutter-apk/app-release.apk
```

## 建立 Linux desktop 專案

```bash
flutter create mylinux --platforms=linux
cd mylinux
sed -i '1i set(CMAKE_SYSTEM_NAME Linux)' linux/CMakeLists.txt
flutter build linux --release
```

產物：

```text
build/linux/arm64/release/bundle/
```

## flutter run / hot reload

`flutter run` 需要 Termux 內的 ADB 能看到 Android device。若是同一台平板/手機，建議使用 Android「無線偵錯」：

```bash
pkg install android-tools
adb pair 127.0.0.1:<pair_port>
adb connect 127.0.0.1:<connect_port>
flutter devices
flutter run -d <device_id>
```

如果 `flutter doctor` 顯示 no connected device，只代表 ADB 尚未連線，不代表 SDK 壞掉。

## 常見問題

### `PLATFORM_ABI_LIST` unresolved

代表 post-install 的 Flutter Gradle plugin 模板或 Gradle cache 是舊的。更新到 v3.44.9 deb 後執行：

```bash
bash $PREFIX/share/flutter/post_install.sh
./android/gradlew --stop || true
rm -rf ~/.gradle/caches .gradle android/.gradle build android/app/build
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

### AAPT2 / compileSdk 錯誤

固定使用 API 34 並指定 Termux ARM64 aapt2：

```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

```kotlin
compileSdk = 34
defaultConfig { targetSdk = 34 }
```

### NDK 或 CMake 找不到 compiler

Gradle 可能下載了新 NDK 或 build-tools。重跑 post-install：

```bash
bash $PREFIX/share/flutter/post_install.sh
```

### 空間不足

```bash
rm -rf ~/.gradle/caches ~/.gradle/wrapper ~/.pub-cache/hosted
pkg clean
```

### 需要 arm / x64 APK

目前不支援。本專案只提供 ARM64 Android target，請使用：

```bash
flutter build apk --release --target-platform android-arm64
```
