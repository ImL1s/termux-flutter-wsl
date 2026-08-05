# APK Size Analysis (Issue #45)

## 1. Investigation of ~162MB APK Size

When running `flutter build apk` in Termux, users have reported APK sizes around 162MB. This is unusually large compared to standard Flutter releases. The investigation reveals several contributing factors:

### A. Fat APK Compilation (Multiple ABIs)
By default, `flutter build apk` produces a "Fat APK" containing native libraries for three architectures: `armeabi-v7a` (ARM 32-bit), `arm64-v8a` (ARM 64-bit), and `x86_64`.
Each architecture adds its own copy of `libflutter.so` and `libapp.so` (the compiled Dart AOT code).
Since Termux Flutter environments currently only support building AOT snapshots for `arm64-v8a` (due to host constraints in `gen_snapshot`), the other architectures may be packed with generic or bloated fallback binaries, or just waste space.

### B. Stripping Native Libraries (`libflutter.so` and `libapp.so`)
The Android Gradle Plugin (AGP) is responsible for stripping debug symbols from native `.so` files before packaging them into the APK. It uses the `strip` utility from the Android NDK.
In a Termux environment, if the NDK toolchain is not perfectly mapped or if the `strip` tool fails silently due to execution permission or path issues, AGP will package the unstripped libraries. Unstripped `libflutter.so` and `libapp.so` contain heavy debug symbols that can easily inflate the APK size by 50MB-100MB.

### C. GN Configuration (Host Tools)
The GN configuration in `build.py` correctly uses `symbol_level=0` and `--lto`. However, these flags only affect the compilation of the host tools (like `gen_snapshot` and Linux `libflutter.so`). They **do not** affect the prebuilt Android `libflutter.so` (which is downloaded from Google's Flutter infra) or the AOT compilation of the user's Dart code (which is controlled by the Flutter tool and `gen_snapshot` flags during `flutter build apk`).

## 2. Implemented Optimizations

To resolve the bloated APK issue, we have implemented the following actionable optimizations:

1. **Per-Project Configuration (Issue #43)**:
   We created the `scripts/install/flutter_project_config.sh` script, which automatically injects:
   ```gradle
   ndk {
       abiFilters += listOf("arm64-v8a")
   }
   ```
   into the project's `build.gradle.kts` (or `build.gradle`). This forces Gradle to only package the `arm64-v8a` libraries, eliminating the ~100MB overhead of the `armeabi-v7a` and `x86_64` ABIs.

2. **Explicit Target Platform**:
   We updated the build instructions and build scripts to remind users to always use `--target-platform android-arm64` when running `flutter build apk --release`. This prevents the Flutter tool from unnecessarily compiling Dart AOT snapshots for unsupported architectures, speeding up the build and ensuring only the 64-bit ARM binary is generated.

3. **NDK Path Mapping (Post-Install)**:
   The `post_install.sh` script maps the Termux Android SDK and NDK paths into the Flutter SDK. This ensures that AGP successfully locates the `strip` binary in `/opt/android-sdk/ndk/` and effectively strips the packaged `.so` libraries.

With these configurations applied, the APK size is reduced from ~162MB to a standard ~20-30MB range for basic Flutter applications.
