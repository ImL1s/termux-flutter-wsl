# Flutter Termux 構建流程文檔

本文檔詳細記錄構建 Flutter for Termux 的完整流程，供未來版本升級時參考。

## 目錄

1. [構建環境](#構建環境)
2. [完整構建流程](#完整構建流程)
3. [關鍵修改說明](#關鍵修改說明)
4. [已知問題與解決方案](#已知問題與解決方案)
5. [測試流程](#測試流程)
6. [發布流程](#發布流程)

---

## 構建環境

### WSL 環境要求

```
OS: Windows 11 + WSL2 (Ubuntu 22.04+)
RAM: 16GB+ (建議 32GB)
Disk: 100GB+ 可用空間
CPU: 多核心推薦 (構建時使用 -j24)
```

### 必要工具

```bash
# Ubuntu packages
sudo apt update
sudo apt install -y git curl python3 python3-pip ninja-build pkg-config

# Python packages
pip3 install -r requirements.txt

# depot_tools
cd ~
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$HOME/depot_tools:$PATH"
echo 'export PATH="$HOME/depot_tools:$PATH"' >> ~/.bashrc
```

---

## 完整構建流程

### 階段 1：同步源碼

```bash
cd ~/projects/termux-flutter

# 克隆 Flutter（如果是新環境）
python3 build.py clone

# 同步依賴（約 30GB，需要數小時）
python3 build.py sync
```

### 階段 2：應用補丁

```bash
# 應用 Termux 適配補丁
python3 build.py patch_engine
python3 build.py patch_dart
python3 build.py patch_skia
python3 build.py patch_flutter_sdk
```

補丁文件位於 `patches/3.44.2/` 目錄，主要修改：
- `patches/3.44.2/engine.patch` - Flutter Engine 的 Termux 工具鏈配置
- `patches/3.44.2/dart.patch` - Dart SDK / VM Termux 適配
- `patches/3.44.2/skia.patch` - Skia Android/bionic build 適配
- `patches/3.44.2/flutter_sdk_arm64_default.patch` - Flutter SDK 預設 ARM64 APK target

### 階段 3：構建 Sysroot

```bash
# 組裝 Termux 運行時依賴
python3 build.py sysroot --arch=arm64
```

這會從 Termux 官方 repo 下載必要的庫文件。

### 階段 4：構建 Linux 組件

```bash
# 配置構建
python3 build.py configure --arch=arm64 --mode=debug

# 構建 Flutter Engine
python3 build.py build --arch=arm64 --mode=debug --jobs=24

# 單獨構建 Dart（關鍵！ninja flutter 不會構建 dart）
python3 build.py build_dart --arch=arm64 --mode=debug --jobs=24
```

**重要**：必須單獨運行 `build_dart`，否則 deb 包中會缺少 dart 二進制。

### 階段 5：構建 Android gen_snapshot（可選，用於 APK 構建）

```bash
# 配置 Android 構建
python3 build.py configure_android --arch=arm64 --mode=release

# 構建 gen_snapshot
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release
```

### 階段 6：打包 deb

```bash
python3 build.py debuild --arch=arm64
```

產出：`release/flutter_3.44.2_aarch64.deb`

---

## 關鍵修改說明

### 1. Termux 工具鏈配置

位置：`patches/engine.patch` → `build/config/termux/BUILD.gn`

```gn
config("compiler") {
  # 使用 Android Bionic 目標三元組
  cflags += [ "--target=aarch64-linux-android${termux_api_level}" ]
  ldflags += [ "--target=aarch64-linux-android${termux_api_level}" ]
}

config("executable_ldconfig") {
  # 必須使用 Bionic linker，否則會出現 TLS 對齊錯誤
  ldflags = [
    "-Bdynamic",
    "-Wl,-z,nocopyreloc",
    "-Wl,--dynamic-linker=/system/bin/linker64",  # 關鍵！
  ]
}
```

### 2. Bionic Linker 問題

**問題**：dart 二進制使用 glibc linker 時會出現：
```
error: "dart": executable's TLS segment is underaligned
```

**解決**：在 `executable_ldconfig` 中添加 `--dynamic-linker=/system/bin/linker64`

### 3. 依賴庫問題

**問題**：連結時找不到 `-llog` 和 `-lm`

**解決**：在 `runtime_library` 配置中添加：
```gn
ldflags = [
  "-stdlib=libstdc++",
  "-Wl,--warn-shared-textrel",
  "-llog",   # Android 日誌庫
  "-lm",     # 數學庫
]
```

---

## 已知問題與解決方案

### 問題 1：vpython3 not found

**症狀**：
```
/bin/sh: vpython3: not found
```

**解決**：
```bash
cd flutter/engine/src/flutter/third_party/depot_tools/.cipd_bin
rm -f vpython3
cat > vpython3 << 'EOF'
#!/bin/bash
exec python3 "$@"
EOF
chmod +x vpython3
```

### 問題 2：Release 模式構建失敗（sysroot 衝突）

**症狀**：
```
error: typedef redefinition with different types ('__mbstate_t' vs 'struct mbstate_t')
```

**原因**：sysroot 同時包含 glibc 和 bionic headers

**當前狀態**：使用 debug 模式構建作為 workaround

**未來修復方向**：清理 sysroot，只保留 bionic headers

### 問題 3：flutter build apk 失敗（dedup_instructions 錯誤）

**症狀**：
```
Flag dedup_instructions is false in snapshot, but dedup_instructions is always true in product mode
```

**原因**：
- `dartaotruntime_product` 期望 product 模式的 snapshot
- `frontend_server_aot.dart.snapshot` 是 debug 模式構建的

**未來修復方向**：需要構建 release 模式的 frontend_server_aot.dart.snapshot

### 問題 4：android-arm/android-x64 gen_snapshot 無法構建

**原因**：
- android-arm: BoringSSL 有 32-bit shift overflow 錯誤
- android-x64: ARM64 sysroot 與 x64 編譯不相容

**結論**：只支援 android-arm64 目標

---

## 測試流程

### 測試設備準備

1. ARM64 Android 設備（Android 11+）
2. 安裝 Termux（從 F-Droid）
3. 確保有 SSH 或 ADB 連接

### 測試步驟

```bash
# 1. 傳輸 deb 到設備
# 使用 PowerShell（Git Bash 會損壞路徑）
adb push flutter_3.44.2_aarch64.deb /sdcard/Download/

# 2. 在 Termux 中安裝
pkg install x11-repo
dpkg -i /sdcard/Download/flutter_3.44.2_aarch64.deb
bash $PREFIX/share/flutter/post_install.sh
apt-get install -f

# 3. 載入環境
source /data/data/com.termux/files/usr/etc/profile.d/flutter.sh

# 4. 測試 flutter doctor
flutter doctor -v

# 5. 測試創建專案
flutter create testapp
cd testapp

# 6. 測試構建（可能有問題）
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
flutter build linux --release
```

### 測試結果記錄

| 測試項目 | 預期結果 | 實際結果 | 備註 |
|----------|----------|----------|------|
| flutter doctor | 顯示版本資訊 | | |
| flutter create | 成功創建專案 | | |
| flutter build apk | 成功構建 APK | | |
| flutter build linux | 成功構建 | | |

---

## 發布流程

### 1. 版本檢查

確認以下文件的版本號一致：
- `build.toml` - `tag` 字段
- `install_flutter_complete.sh` - `FLUTTER_VERSION`
- `scripts/install/install_termux_flutter.sh` - `FLUTTER_VERSION`
- `README.md` - 版本徽章和文字
- `package.yaml` - `Version: $tag`

### 2. 構建產物

```bash
# 最終產物位置
release/flutter_3.44.2_aarch64.deb
```

### 3. 上傳到 GitHub Releases

1. 創建新 Release：`v3.44.2`
2. 上傳 deb 檔案：`flutter_3.44.2_aarch64.deb`
3. 填寫 Release Notes

### 4. 驗證一鍵安裝腳本

在新的 Termux 環境測試：
```bash
curl -sL https://raw.githubusercontent.com/ImL1s/termux-flutter-wsl/master/install_flutter_complete.sh -o ~/install.sh && bash ~/install.sh
```

---

## 版本升級指南

當 Flutter 發布新版本時：

### 1. 更新版本配置

編輯 `build.toml`：
```toml
tag = "3.36.0"  # 新版本號
```

### 2. 同步源碼

```bash
python3 build.py sync
```

### 3. 重新應用補丁

```bash
# 可能需要更新補丁以適配新版本
python3 build.py patch_engine
```

如果補丁應用失敗，需要手動更新 `patches/engine.patch`：
1. 查看衝突
2. 手動解決
3. 重新生成補丁

### 4. 完整構建和測試

按照上述流程進行構建和測試。

---

## 文件結構參考

```
termux-flutter-wsl/
├── .github/workflows/    # CI / self-hosted build and device smoke workflows
├── docs/CI_CD.md         # CI/CD 與裝置實驗室說明
├── scripts/
│   ├── ci/               # 輕量 contract checks
│   ├── device/           # ADB → Termux smoke automation
│   ├── install/          # 安裝與 post-install 修補
│   └── test/             # Release E2E smoke scripts
├── patches/3.44.2/       # Flutter Engine / Dart / Skia 補丁
├── build.py              # 主構建腳本
├── build.toml            # 構建配置（版本號等）
├── package.yaml          # deb 包定義
├── sysroot/              # Termux 運行時依賴（構建時生成）
├── flutter/              # Flutter 源碼（構建時克隆）
│   └── engine/src/out/   # 構建產物
└── release/              # 最終 deb 包
```

---

## 更新日誌

### 2026-06-01
- 更新本文檔至 Flutter 3.44.0 / Dart 3.12 狀態
- 補上 `scripts/ci`、`scripts/device`、GitHub Actions 與 release metadata check
- 測試流程改為 ARM64 APK + Linux release smoke

### 2025-12-29
- 創建本文檔
- 記錄 debug/release 模式問題
- 記錄 sysroot 衝突問題

### 2025-12-28
- 首次成功構建 Flutter 3.35.0
- 解決 TLS 對齊問題
- 解決 -llog/-lm 依賴問題
