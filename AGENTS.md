# AGENTS.md

This file provides guidance to AI coding agents (Codex CLI, etc.) when working with code in this repository.

## What This Is

Cross-compile Flutter SDK for Termux (Android/Bionic ARM64). Produces a `.deb` package installable on Termux that enables `flutter run`, `flutter build apk`, and `flutter build linux`.

## Build Commands

```bash
# Full build (~2-4 hours on 24-thread machine)
python3 build.py build_all --arch=arm64

# Individual steps
python3 build.py clone                                    # Clone Flutter 3.44.2
python3 build.py sync                                     # gclient sync (~30GB)
python3 build.py patch_engine && python3 build.py patch_dart && python3 build.py patch_skia
python3 build.py sysroot --arch=arm64                     # Assemble Termux sysroot from apt
python3 build.py configure --arch=arm64 --mode=debug      # GN configure
python3 build.py build --arch=arm64 --mode=debug          # ninja build
python3 build.py build_dart --arch=arm64 --mode=debug     # dart binary (separate!)
python3 build.py build_impellerc --arch=arm64 --mode=debug
python3 build.py build_const_finder --arch=arm64 --mode=debug
python3 build.py configure --arch=arm64 --mode=release    # Linux release engine
python3 build.py build --arch=arm64 --mode=release
python3 build.py configure --arch=arm64 --mode=profile    # Linux profile engine
python3 build.py build --arch=arm64 --mode=profile
python3 build.py configure_android --arch=arm64 --mode=release
python3 build.py build_android_gen_snapshot --arch=arm64 --mode=release
python3 build.py debuild --arch=arm64                     # Package .deb
```

## Code Architecture

| File | Role |
|------|------|
| `build.py` | CLI entry point (Python Fire). `Build` class holds all commands. |
| `build.toml` | Config: Flutter version, NDK path, sync paths, sysroot packages, patch locations |
| `sysroot.py` | `Sysroot` class downloads Termux `.deb` packages async (aiohttp) and extracts into sysroot |
| `package.py` | `Package` class reads `package.yaml`, resolves variable substitution, creates `.deb` |
| `package.yaml` | Declarative artifact mapping: build output paths → Termux install paths |
| `utils.py` | Helpers: arch mapping (`arm64→aarch64`), output path resolution, Termux detection |
| `patches/{version}/` | Git patches for Engine, Dart VM, Skia (version-specific) |
| `.github/workflows/ci.yml` | GitHub-hosted PR/push sanity checks |
| `.github/workflows/build-deb.yml` | Manual self-hosted full `.deb` build / optional release publish |
| `.github/workflows/device-smoke.yml` | Manual Windows+ADB Termux tablet smoke workflow |
| `.github/workflows/release-check.yml` | Release asset metadata / SHA256 verifier |
| `scripts/ci/check_repo.py` | Lightweight repo contract checker used by CI |
| `scripts/device/` | Windows ADB driver and Termux-side smoke script |
| `scripts/test/gh_e2e_test.sh` | GitHub Release clean-install E2E smoke script |
| `docs/CI_CD.md` | CI/CD, runner, and device-lab guide |

## Lightweight Verification

```bash
python -m py_compile build.py package.py sysroot.py utils.py scripts/ci/check_repo.py
bash -n scripts/install/post_install.sh scripts/test/gh_e2e_test.sh scripts/device/termux_smoke.sh
python scripts/ci/check_repo.py
git diff --check
```

Self-hosted workflows are manual-only. Do not run expensive full build or tablet smoke automatically on PRs.

## Critical Implementation Details

1. **`ninja flutter` does NOT build `dart` binary**. Must run `build_dart()` separately.
2. **Only ARM64 APK gen_snapshot works**. 32-bit ARM fails (BoringSSL), x64 fails (sysroot mismatch).
3. **Linux target builds all three modes** (debug, release, profile). `build_all()` runs configure+build for each mode.
4. **`package.yaml` uses `safe_eval()`** for variable resolution — constrained evaluation with recursion limits, be careful with template strings.
5. **`debuild()` auto-syncs** from Windows to WSL via `[sync]` config before packaging.
6. **GN flag `is_termux=true`** activates custom BUILD.gn rules that add `-llog -lm` for Android logging symbols.
7. **`utils.py __MODE__` must be `('debug', 'release', 'profile')`** — debug first! `Output.any` picks the first existing directory. If release comes first, `output.any` points to release (product mode) dart-sdk snapshots, breaking the entire Flutter CLI.

## Termux Runtime: post_install.sh Auto-Fixes

`post_install.sh` automatically handles these ARM64 compatibility issues:
- **compileSdkVersion 36→34**: Termux aapt2 (v2.19) cannot load android-35/36 `android.jar`
- **NDK clang wrappers**: Replaces x86_64 clang/clang++ with Termux ARM64 native wrappers (dynamic clang lib version)
- **NDK llvm-objcopy**: Replaces x86_64 `llvm-objcopy`/`llvm-strip` with Termux ARM64 native binaries
- **Shebang fix**: All generated wrapper scripts use `#!/data/data/com.termux/files/usr/bin/sh`

## Termux Runtime: Per-Project Configuration

Each Flutter project needs in `android/gradle.properties`:
```properties
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2
```

And in `android/app/build.gradle.kts`:
```kotlin
android {
    compileSdk = 34  // Must use API 34 (Termux aapt2 limitation)
    defaultConfig {
        targetSdk = 34
        ndk { abiFilters += listOf("arm64-v8a") }
    }
}
```

## Build Output

```
flutter/engine/src/out/
├── linux_debug_arm64/          # Main: dart-sdk, gen_snapshot, libflutter_linux_gtk.so
├── linux_release_arm64/        # Release: gen_snapshot, libflutter_linux_gtk.so
├── linux_profile_arm64/        # Profile: gen_snapshot, libflutter_linux_gtk.so
├── android_release_arm64/      # Android gen_snapshot (release APK)
└── android_profile_arm64/      # Android gen_snapshot (profile APK)
```

## Environment

- Build: WSL2 Ubuntu on Windows, NDK r27d at `/opt/android-ndk-r27d`
- WSL path: `<workspace-root>/`
- Target: aarch64, Flutter 3.44.2
- Test device: `[REDACTED]` (Samsung SM-X716B / Android 16)
- Use PowerShell (not Git Bash) for `adb push` to avoid path mangling
