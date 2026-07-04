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

The bug is triggered when the Android Gradle Plugin (AGP) runs R8 resource shrinking (`isShrinkResources = true`) and resource optimization (`android.enableResourceOptimizations = true`) in the release pipeline. These tasks invoke `aapt2 optimize` to rebuild the resource package (`.ap_`).

In the Termux build environment, we override AGP's bundled `aapt2` (which is a `glibc` Linux x86_64 binary) with the native Termux `aapt2` package (`/data/data/com.termux/files/usr/bin/aapt2`). This override exposes three critical compatibility limitations:

### A. Missing `split-select` Toolchain
During resource optimization, AGP invokes the SDK `build-tools` binary `split-select` to generate configuration split APKs. Since Google does not publish an ARM64 version of `split-select`, and Termux does not provide it, this step either fails silently or outputs a corrupted zip stream that native `aapt2` fails to link correctly.

### B. Rolling-Release Protobuf Instability
The native Termux `aapt2` binary is dynamically linked to the system's `libprotobuf.so`. As Termux is a rolling-release environment, system package updates (`pkg upgrade`) regularly change the `libprotobuf.so.XX` version. When this happens, `aapt2` crashes instantly at runtime with linker errors, causing resource-linking tasks to output empty/truncated asset files silently.

### C. Android 15+ Binary Format Incompatibility
Android 15+ (API 35/36) introduced a new binary format for the `resources.arsc` resource tables. The native Termux `aapt2` package (built on older Build-Tools sources) throws validation errors (`RES_TABLE_TYPE_TYPE entry offsets overlap actual entry data`) when linking against newer `android-35.jar` structures, stripping resources it cannot parse.

---

## 3. Comparison of Solutions

| Solution Strategy | Implementation Details | Pros | Cons / Risks |
|:---|:---|:---|:---|
| **Strategy 1: Disable Resource Optimizations (Current Workaround)** | Add `android.enableResourceOptimizations=false` to `gradle.properties` and set `isMinifyEnabled=false`/`isShrinkResources=false` in `build.gradle.kts`. | *   **100% stable and reliable.**<br>*   Avoids dynamic library crashes.<br>*   Reduces JVM memory usage during Termux compilation (prevents JVM OOM crashes on mobile devices). | *   Slightly larger release APK size (adds ~3-5MB of unused layout definitions).<br>*   Uses deprecated AGP optimization flags. |
| **Strategy 2: Stub `split-select` & Allocate Swap** | Write a mock `split-select` script that exits with `0` in `build-tools/` and allocate a swapfile on device for JVM memory. | *   Allows R8 shrinking to complete. | *   **Highly fragile.**<br>*   Does not solve protobuf dynamic linker crashes.<br>*   Prone to random OOM compilation crashes on lower-end devices. |
| **Strategy 3: Bundle Static ARM64 AAPT2 in `.deb` (Long-Term Solution)** | Cross-compile a **statically linked** native ARM64 `aapt2` binary from AOSP, include it in our `.deb` package, and let `post_install.sh` automatically map Gradle to use it. | *   **No dynamic library dependencies** (immune to protobuf updates).<br>*   Version-matched with AGP, allowing full optimization and shrinking to run safely.<br>*   Out-of-the-box support for API 35/36. | *   High maintenance and compilation overhead to package and rebuild the static binary for new Flutter releases. |

---

## 4. Current Developer Workaround

For projects built inside Termux, apply the following project configurations to ensure release APKs compile, install, and run correctly:

### 1. `android/gradle.properties`
```properties
# Force Gradle to use native Termux AAPT2
android.aapt2FromMavenOverride=/data/data/com.termux/files/usr/bin/aapt2

# Turn off R8 resource optimizations to bypass AAPT2 repackaging failures
android.enableResourceOptimizations=false
```

### 2. `android/app/build.gradle.kts`
```kotlin
android {
    compileSdk = 34 // Pin to API 34 to match Termux AAPT2 compiler limitations

    defaultConfig {
        targetSdk = 34
        ndk {
            abiFilters += listOf("arm64-v8a") // Keep ARM64 target only
        }
    }

    buildTypes {
        release {
            // Disable code minification and resource shrinking to avoid AAPT2 linking failures and OOM
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}
```

---

## 5. Follow-Up Plan: Static AAPT2 Packaging

To completely remove the manual configuration burden from developers, we plan to package our own static ARM64 `aapt2` binary with the Flutter SDK.

### Task List
1.  **Set up AOSP Build Host:** Set up a Linux host capable of cross-compiling AOSP tools.
2.  **Cross-Compile Static `aapt2`:** 
    *   Build `aapt2` statically (`-static` / `-static-libstdc++`) for the `aarch64-linux-android` target.
    *   Ensure the binary includes no dynamic linkages to `libprotobuf.so` or `libc++_shared.so`.
3.  **Bundle in Package:** Add the compiled binary to `package.yaml` to install at `$PREFIX/opt/flutter/bin/cache/termux/aapt2`.
4.  **Auto-Configuration in `post_install.sh`:** Update the post-install script to automatically rewrite or inject the `aapt2` path into gradle configurations, removing the need for manual developer overrides.
