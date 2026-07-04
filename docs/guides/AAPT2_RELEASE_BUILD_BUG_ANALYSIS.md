# AAPT2 Release Build Resource Stripping Bug & Static Compilation Plan

This document records the technical investigation, root cause analysis, workarounds, and long-term follow-up plans regarding the `aapt2 optimize` resource stripping issue on Android/Termux hosts.

---

## 1. Background & Symptom

When building a release APK natively inside Termux using the cross-compiled Flutter SDK 3.44.2, the compilation completes successfully (exit code `0`), producing an APK of around 18MB. 

However, attempting to install the resulting APK using `adb install` fails immediately with:
```text
Failure [INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION: Failed to parse /data/local/tmp/app-release.apk:
AndroidResourceParser: Failed to read manifest]
```

### Diagnostic Findings
Decompressing the corrupted APK reveals:
*   The `AndroidManifest.xml` is **completely missing**.
*   The `resources.arsc` table is **completely missing**.
*   The `res/` folder is empty or lacks all referenced drawables and layouts.
*   *Note:* Debug APK builds do not undergo shrinking/resource optimization tasks and install successfully.

---

## 2. Root Cause Analysis

The bug is triggered when building a release APK natively inside Termux. During release builds, the Android Gradle Plugin (AGP) runs R8 resource shrinking (`isShrinkResources = true`) and resource optimization (`android.enableResourceOptimizations = true`) to rebuild the resource package (`.ap_`).

In the Termux environment, we override AGP's bundled `aapt2` with the native Termux package (`/data/data/com.termux/files/usr/bin/aapt2`). This configuration triggers critical toolchain compatibility issues:

### A. AGP's Architecture-Agnostic Classifier Resolution
Google does not publish an ARM64 host binary of `aapt2` on Google Maven (see [Google Issue 227219818](https://issuetracker.google.com/issues/227219818)). Furthermore, AGP maps host platforms solely by OS (`SdkConstants.currentPlatform()`), ignoring the CPU architecture. On any Linux host, AGP unconditionally requests:
`com.android.tools.build:aapt2:<version>:linux` (which resolves strictly to the `x86_64` glibc ELF binary). Running this binary on ARM64 Bionic libc inside Termux immediately fails.

### B. Toolchain Packaging Bug (Modern R8 Shrinking)
In AGP 8.0+, R8 performs **Optimized Resource Shrinking** where code and resource shrinking are unified. The missing `AndroidManifest.xml` and corrupted resource tables are **not** caused by static analysis pruning (R8 labeling active resources as unused). Instead, it is a **low-level toolchain packaging bug** where the overridden, mismatched native `aapt2` crashes or fails to process command-line arguments and ZIP stream formats during the re-zipping/linking phases.
*Note: Because this is a toolchain packaging crash rather than a pruning issue, custom keep rules (`keep.xml` or Proguard rules) have **no effect**.*

### C. Missing `split-select` Toolchain
During resource optimization, AGP invokes `split-select` to generate configuration split APKs. Google does not publish an ARM64 version of `split-select`, and Termux does not package it. This step fails silently or corrupts the intermediate `.ap_` archive which `aapt2` is then unable to parse.

### D. Rolling-Release Protobuf Instability
The native Termux `aapt2` is dynamically linked to the system's `libprotobuf.so`. Because Termux is a rolling-release environment, `pkg upgrade` often bumps the `libprotobuf.so.XX` version. When this occurs, `aapt2` immediately crashes with dynamic linker errors, causing resource compile/link steps to silently exit and write truncated/empty assets.

### E. Android 15/16+ Binary Format Incompatibility
Android 15 (API 35) and 16 (API 36) updated the binary structure of `resources.arsc` resource tables. Native Termux `aapt2` packages (often based on older AOSP Build-Tools sources) throw validation errors (`RES_TABLE_TYPE_TYPE entry offsets overlap actual entry data`) when parsing updated structures, stripping out resources they cannot parse.

---

## 3. Comparison of Solutions

| Solution Strategy | Implementation Details | Pros | Cons / Risks |
|:---|:---|:---|:---|
| **Strategy 1: Disable Optimizations via properties (Current Workaround)** | Add `android.enableResourceOptimizations=false` and `shrink=false` to `gradle.properties`. | *   **100% stable and reliable**.<br>*   Avoids dynamic library crashes.<br>*   **No build script edits**: FGP's property check skips enabling R8/shrinking automatically. | *   Larger release APK size (adds ~3-5MB of unused classes/layouts).<br>*   Uses deprecated AGP optimization flags. |
| **Strategy 2: Stub `split-select` & Allocate Swap** | Write a mock `split-select` script that exits with `0` in `build-tools/` and allocate a swapfile on device for JVM memory. | *   Allows R8 shrinking to compile. | *   **Highly fragile**.<br>*   Does not solve protobuf dynamic linker crashes.<br>*   Prone to JVM OOM crashes on lower-end devices. |
| **Strategy 3: Bundle Static ARM64 AAPT2 in `.deb` (Long-Term Solution)** | Cross-compile a **statically linked** native ARM64 `aapt2` from AOSP, bundle it, and automate injection via a global Gradle init script. | *   **No dynamic dependencies** (immune to protobuf updates).<br>*   Version-matched with AGP, enabling full shrinking safely.<br>*   Out-of-the-box support for API 35/36. | *   High maintenance overhead to compile and match new AGP/AOSP releases. |

### Note on Emulation & Container Workarounds (Box64 / PRoot)
*   **Box64 / QEMU User-Mode:** Ruled out. Android's kernel blocks user-space configuration of `/proc/sys/fs/binfmt_misc` (set as read-only), preventing the JVM from transparently wrapping and executing x86_64 binaries through the emulator without root access.
*   **PRoot Distro (Ubuntu Container):** Ruled out as a general workflow. While it stabilizes dynamic library dependencies, it does not bypass the CPU architecture gap (requires manual `aapt2` overrides/emulators). It introduces a **2x to 5x compile slowdown** due to `ptrace` system call interception, consumes massive storage (5GB+), and complicates ADB wireless port forwarding for on-device execution.

---

## 4. Current Developer Workaround

For projects built inside Termux, apply the following configurations to ensure release APKs compile, install, and run successfully:

### 1. `android/gradle.properties`
```properties
# Force Gradle to use native Termux AAPT2
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2

# Disable R8 code & resource shrinking automatically via Flutter Gradle Plugin check
shrink=false

# Turn off R8 resource optimizations to bypass AAPT2 repackaging failures
android.enableResourceOptimizations=false

# Optimize JVM heap to prevent OOM compilation crashes in Termux
org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8
```

### 2. `android/app/build.gradle.kts`
No modifications to the `buildTypes` block are required as the `shrink=false` property handles it. Simply configure SDK constraints and target architectures:
```kotlin
android {
    compileSdk = 34 // Pin to API 34 to match Termux AAPT2 version support

    defaultConfig {
        targetSdk = 34
        ndk {
            abiFilters += listOf("arm64-v8a") // Pin to ARM64 target only
        }
    }
}
```

### 3. Flutter Release Compile Command
Because the Termux Dart VM runs strictly in JIT mode, it is unable to execute Flutter's AOT icon tree-shaker snapshot (`const_finder.dart.snapshot`). Release builds must bypass icon tree shaking:
```bash
flutter build apk --release --target-platform android-arm64 --no-tree-shake-icons
```

---

## 5. Follow-Up Plan: Static AAPT2 Packaging

To completely remove the manual configuration burden from developers, we plan to package our own static ARM64 `aapt2` binary with the Flutter SDK.

### Task List
1.  **Set up AOSP Build Host:** Set up a Linux host capable of cross-compiling AOSP tools.
2.  **Cross-Compile Static `aapt2`:** 
    *   Build `aapt2` statically (`-static` / `-static-libstdc++`) for the `aarch64-linux-android` target.
    *   Ensure the binary includes no dynamic linkages to `libprotobuf.so` or `libc++_shared.so`, preventing rolling-release breakages.
3.  **Bundle in Package:** Add the compiled binary to `package.yaml` to install at `$PREFIX/opt/flutter/bin/cache/termux/aapt2`.
4.  **Auto-Configuration via Global Init Script:** Update the post-install script (`post_install.sh`) to automatically generate a global Gradle initialization script at `~/.gradle/init.d/aapt2.gradle` during installation:
    ```groovy
    // init.gradle automatic injection
    settingsEvaluated { settings ->
        settings.gradle.projectsLoaded { gradle ->
            gradle.rootProject {
                ext["android.aapt2FromMavenOverride"] = "${System.getenv('PREFIX')}/opt/flutter/bin/cache/termux/aapt2"
            }
        }
    }
    ```
    This removes the need for project-level `gradle.properties` overrides entirely, enabling a zero-configuration developer experience.
