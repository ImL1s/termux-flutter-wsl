# Flutter 版本升級指南

本文件說明如何將 Termux Flutter 從目前的 3.44.9 升級到新版本，並列出 3.44.9 之後必須重新檢查的 Dart / Flutter Tools / Gradle plugin 風險點。

---

## 📋 升級檢查清單

```
□ Step 1: 修改 build.toml 版本號
□ Step 2: clone 新版 Flutter
□ Step 3: gclient sync
□ Step 4: 建立新版 patch 目錄並調整 patch
□ Step 5: 套用 patch (engine / dart / skia / flutter_sdk)
□ Step 6: 組裝 sysroot
□ Step 7: configure + build (debug / release / profile)
□ Step 8: build_dart + build_impellerc + build_const_finder
□ Step 9: configure_android + build_android_gen_snapshot
□ Step 10: debuild 打包 .deb
□ Step 11: 推送到設備測試
□ Step 12: 更新 post_install.sh（如有必要）
□ Step 13: 發佈 GitHub Release
```

## 3.44.9 之後的必查項目

| 項目 | 為什麼重要 | 檢查方式 |
|------|------------|----------|
| `dart` / `dartvm` / `dartaotruntime` | Dart 3.10+ 將 CLI 與 VM runtime 拆得更明顯；只打包 `dart` 會讓 snapshots 或 Flutter CLI 其中一邊壞掉 | `python3 build.py debuild --arch=arm64` 必須通過 artifact validator |
| Flutter Tools host platform | Termux 會被 Dart 視為 `android` host；官方 Flutter Tools 通常只處理 macOS/Linux/Windows | 在 Termux 跑 `flutter doctor -v`，不能在 cache/artifact/device discovery 階段 crash |
| Flutter Gradle plugin constants | Flutter 3.44 起 `FlutterPlugin.kt` 直接 import `PLATFORM_ABI_LIST` | `flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons` 不能出現 Kotlin unresolved reference |
| Gradle included-build cache | post-install 會改 Kotlin source；升級時舊 cache 可能混用新舊 source | `post_install.sh` 要清掉 `packages/flutter_tools/gradle/.gradle`, `build`, `bin` |
| Android SDK / aapt2 | 新版模板可能提高 `compileSdk`，Termux aapt2 仍需 API 34 workaround | 新專案固定 `compileSdk = 34`, `targetSdk = 34`, `android.aapt2FromMavenOverride` |

---

## Step 1: 修改版本號

編輯 `build.toml`：

```toml
[flutter]
tag = '3.XX.Y'    # ← 改成新版本號
```

> 其他欄位通常不需要改（NDK 路徑、jobs 等）。
> 如果新版 Flutter 要求更新的 NDK，也需要更新 `[ndk]` 區塊。

---

## Step 2: Clone 新版 Flutter

```bash
# 在 WSL 中執行
cd /root/projects/termux-flutter
python3 build.py clone
```

這會 `git clone` 指定 tag 的 Flutter repo 到 `./flutter/`。

---

## Step 3: gclient sync

```bash
python3 build.py sync
```

這會：
1. 複製 `.gclient` 到 engine 目錄
2. 執行 `gclient sync -DR --no-history`（下載 ~30GB engine + deps）
3. 自動替換 prebuilt dart-sdk 為匹配版本

> ⏱ 耗時約 30-60 分鐘（視網速）

---

## Step 4: 建立新版 Patch 目錄

```bash
mkdir -p patches/3.XX.Y
```

### Patch 來源與目的

| Patch 檔案 | 目標 | 作用 |
|------------|------|------|
| `engine.patch` | Engine BUILD.gn | 加入 `-llog -lm` 連結旗標、`is_termux` GN 變數 |
| `dart.patch` | Dart VM | 修復 bionic TLS 對齊問題 |
| `skia.patch` | Skia 圖形庫 | 修復 ARM64 bionic 編譯問題 |
| `flutter_sdk_arm64_default.patch` | Flutter CLI | 預設只產出 ARM64 APK（停用 arm/x64 gen_snapshot）|

### 如何調整 Patch

**方法 A：直接複製上版 patch，嘗試套用**

```bash
cp patches/3.44.9/*.patch patches/3.XX.Y/
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
```

如果 patch 套用失敗（offset/conflict），需要手動 rebase：

**方法 B：手動 rebase patch**

```bash
cd flutter/engine/src/flutter
# 查看原始 patch 改了哪些檔案
git apply --stat /root/projects/termux-flutter/patches/3.44.9/engine.patch

# 嘗試套用，看哪裡衝突
git apply --check patches/3.44.9/engine.patch

# 手動修改衝突的檔案，然後產生新 patch
git diff > /root/projects/termux-flutter/patches/3.XX.Y/engine.patch
```

### 各 Patch 的關鍵修改點

<details>
<summary><b>engine.patch — 必須改的部分</b></summary>

1. **`build/config/termux/BUILD.gn`** — 加入 Termux runtime library flags:
   ```gn
   ldflags = ["-stdlib=libstdc++", "-Wl,--warn-shared-textrel", "-llog", "-lm"]
   ```

2. **`build/toolchain/custom/BUILD.gn`** — 定義 `is_termux` 旗標

3. **`flutter/BUILD.gn`** — 在 termux 條件下加入 `-llog -lm`

4. **`shell/platform/linux/`** — GTK embedding fixes for bionic

</details>

<details>
<summary><b>dart.patch — TLS 修復</b></summary>

修復 Dart VM 的 Thread-Local Storage 對齊問題，Android bionic linker 要求 TLS 段必須正確對齊。

</details>

<details>
<summary><b>skia.patch — 編譯修復</b></summary>

修復 Skia 在 ARM64 bionic 環境下的編譯錯誤。

</details>

<details>
<summary><b>flutter_sdk_arm64_default.patch — CLI 修改</b></summary>

修改 Flutter CLI 的 `build_apk.dart` / `build_aar.dart` / `build_appbundle.dart`，
將預設 `targetPlatform` 從 `[arm, arm64, x64]` 改為只有 `[arm64]`。

> ⚠️ 這個 patch 應用在 Flutter SDK（`./flutter/`），不是 engine。
> 每個新版本的 build_apk.dart 可能有不同結構。

</details>

---

## Step 5: 套用 Patch

```bash
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
```

> `flutter_sdk_arm64_default.patch` 在 `patch_engine` 裡不會自動套用。
> 它會在 `debuild` 時透過 `package.yaml` 的設定處理，或者手動執行：
> ```bash
> cd flutter && git apply ../patches/3.XX.Y/flutter_sdk_arm64_default.patch
> ```

---

## Step 6: 組裝 Sysroot

```bash
python3 build.py sysroot --arch=arm64
```

從 Termux apt repo 下載 `.deb` 套件並解壓到 sysroot 目錄。

> 通常不需要修改 `build.toml` 的 sysroot 套件列表，
> 除非新版 Flutter 引入了新的系統依賴（例如新增 GTK4）。

---

## Step 7: Configure + Build (三種模式)

```bash
# Debug (主要模式 — 包含 dart-sdk, gen_snapshot 等)
python3 build.py configure --arch=arm64 --mode=debug
python3 build.py build --arch=arm64 --mode=debug

# Release (Linux release engine)
python3 build.py configure --arch=arm64 --mode=release
python3 build.py build --arch=arm64 --mode=release

# Profile (Linux profile engine)
python3 build.py configure --arch=arm64 --mode=profile
python3 build.py build --arch=arm64 --mode=profile
```

> ⏱ 每個模式約 30-60 分鐘（24 threads）
>
> ⚠️ **重要**：`utils.py` 裡的 `__MODE__` 元組必須是 `('debug', 'release', 'profile')`，
> debug 一定要在第一個位置！`Output.any` 會挑第一個存在的目錄。
> 如果 release 先找到，會指向 product mode 的 dart-sdk snapshots，導致所有 CLI 壞掉。

---

## Step 8: 額外工具編譯

```bash
# Dart binary（ninja flutter 不會編譯 dart）
python3 build.py build_dart --arch=arm64 --mode=debug

# Impeller shader compiler
python3 build.py build_impellerc --arch=arm64 --mode=debug

# Const finder（icon tree shaking 用）
python3 build.py build_const_finder --arch=arm64 --mode=debug
```

> ⚠️ `build_dart` 是**必須**的！`ninja flutter` 目標不包含 dart binary。

---

## Step 9: Android gen_snapshot

```bash
# Release
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release

# Profile
python3 build.py configure_android --arch=arm64 --mode=profile
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=profile
```

> 這會產出在 Termux ARM64 上運行的 gen_snapshot，用於 `flutter build apk --release`。
> 只有 ARM64 → ARM64 可以成功，ARM32 和 x64 target 無法編譯（見 README）。

---

## Step 10: 打包 .deb

```bash
python3 build.py debuild --arch=arm64
```

這會：
1. 從 Windows 同步最新的 `scripts/`, `patches/`, `package.yaml`, `build.toml` 到 WSL
2. 根據 `package.yaml` 收集所有 build output
3. 打包成 `flutter_3.XX.Y_aarch64.deb`

> 產出路徑：`/root/projects/termux-flutter/flutter_3.XX.Y_aarch64.deb`

---

## Step 11: 設備測試

```powershell
# 從 WSL 複製到 Windows
Copy-Item "\\wsl.localhost\Ubuntu\root\projects\termux-flutter\flutter_3.XX.Y_aarch64.deb" .

# 推送到設備
adb push flutter_3.XX.Y_aarch64.deb /data/local/tmp/

# 在 Termux 中安裝
dpkg -i /data/local/tmp/flutter_3.XX.Y_aarch64.deb
apt-get install -f
bash $PREFIX/share/flutter/post_install.sh
source $PREFIX/etc/profile.d/flutter.sh

# 驗證
flutter doctor -v
flutter create testapp && cd testapp
flutter build apk --release --target-platform android-arm64
flutter build linux --release
```

---

## Step 12: 更新 post_install.sh（如有必要）

`scripts/install/post_install.sh` 包含大量針對 Flutter 原始碼的 `sed` 修改。
如果新版 Flutter 改變了這些位置，需要更新：

| 修改目標 | 用途 | 可能需要更新的情況 |
|---------|------|-------------------|
| `build_apk.dart` | 停用 arm/x64 platform | Flutter 重構了 APK build 邏輯 |
| `build_linux.dart` | 繞過 `isLinux` 檢查 | Flutter 改了 platform 檢查方式 |
| `FlutterPluginConstants.kt` | ARM64-only NDK filter | Gradle plugin 結構改變 |
| `compileSdkVersion` 降級 | Termux aapt2 限制 | aapt2 版本更新支援新 API |
| `tool_backend.sh` | shebang 修正 | Flutter 重新產生了此腳本 |
| NDK clang wrapper | Termux ARM64 clang | NDK 版本更新 |

**測試方法**：在設備上跑 `post_install.sh`，觀察輸出是否有 `⚠` 或錯誤。

---

## Step 13: 發佈 GitHub Release

```powershell
# 更新版本號
$VER = "3.XX.Y"

# 建立 Release
gh release create "v$VER" `
  --title "Flutter $VER for Termux ARM64" `
  --notes-file docs/releases/RELEASE_NOTES.md `
  "flutter_${VER}_aarch64.deb"
```

記得更新：
- `README.md` 中的版本號
- `docs/releases/CHANGELOG.md`
- `docs/releases/RELEASE_NOTES.md`
- `scripts/install/install_termux_flutter.sh` 中的 `FLUTTER_VERSION`
- `install_flutter_complete.sh` 中的版本號

---

## 🔄 一鍵升級（如果 patch 無衝突）

如果 patch 可以直接套用，整個過程可以用一個命令：

```bash
python3 build.py build_all --arch=arm64
```

`build_all` 會依序執行：
1. configure + build (debug → release → profile)
2. build_dart
3. build_impellerc  
4. build_const_finder
5. configure_android + build_android_gen_snapshot (release + profile)
6. debuild

> ⏱ 全程約 2-4 小時

---

## ⚠️ 常見升級問題

### 1. Patch 衝突

**症狀**：`git apply` 失敗

**原因**：上游改了 patch 涉及的檔案

**解決**：手動修改原始碼後重新產生 patch（見 Step 4）

### 2. 新增系統依賴

**症狀**：編譯時缺少 header 或 library

**解決**：在 `build.toml` 的 `[sysroot.termux-main]` 或 `[sysroot.termux-x11]` 加入新套件

### 3. GN 旗標變更

**症狀**：`gn gen` 報錯未知變數

**原因**：Flutter 重構了 BUILD.gn

**解決**：檢查新版 engine 的 `build/config/` 結構，調整 `engine.patch`

### 4. Dart SDK 版本不匹配

**症狀**：`package_config.json` language version 錯誤

**解決**：`build.py sync` 會自動處理，但如果版本號改了需檢查下載 URL

### 5. post_install.sh sed 失敗

**症狀**：`sed` 找不到目標字串

**原因**：新版 Flutter 改了要修改的 Dart 原始碼

**解決**：在設備上手動檢查目標檔案，更新 `sed` 的搜尋模式

---

## 📁 專案結構參考

```
termux-flutter-wsl/
├── build.py                  # 主 CLI（Python Fire）
├── build.toml                # 所有配置：版本、NDK、sync 路徑
├── package.py                # .deb 打包邏輯
├── package.yaml              # 宣告式：build output → deb 安裝路徑
├── sysroot.py                # 下載 Termux apt 套件組裝 sysroot
├── utils.py                  # arch 映射、output 路徑
├── .gclient                  # gclient sync 配置
│
├── patches/
│   ├── 3.44.9/               # 3.44.9 專用 patch
│   │   ├── engine.patch
│   │   ├── dart.patch
│   │   ├── skia.patch
│   │   └── flutter_sdk_arm64_default.patch
│   └── 3.XX.Y/               # ← 新版本的 patch 放這裡
│
├── scripts/
│   ├── install/
│   │   ├── post_install.sh   # 設備端 post-install 配置
│   │   └── install_termux_flutter.sh  # 一鍵安裝腳本
│   ├── ci/check_repo.py      # 輕量 repo contract check
│   ├── device/               # ADB → Termux smoke automation
│   ├── test/gh_e2e_test.sh   # GitHub Release E2E 測試腳本
│   └── ...
│
├── install_flutter_complete.sh # 完整安裝腳本（含 Android SDK）
│
├── README.md                 # 中文文檔
├── README_EN.md              # 英文文檔
├── docs/guides/UPGRADE_GUIDE.md # ← 本文件
├── docs/releases/CHANGELOG.md   # 版本變更記錄
└── docs/releases/RELEASE_NOTES.md # 發佈說明
```
