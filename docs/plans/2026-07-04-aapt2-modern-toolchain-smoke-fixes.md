# AAPT2 Modern Toolchain Smoke Verification Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the device smoke gate evaluation order in run_termux_smoke.ps1, clear stale on-device APKs, and align default release version settings to v3.44.2.

**Architecture:** Verify all required markers in the Termux log before executing the adb pull and adb install steps. Add a cleanup command to delete any existing /sdcard/Download/app-release.apk on the tablet prior to the run. Update default parameters in the PowerShell driver script and the GitHub device-smoke workflow to v3.44.2 URL/SHA.

**Tech Stack:** PowerShell, YAML.

---

### Task 1: Update Smoke Gate Verification Order and Add Stale APK Cleanup in `run_termux_smoke.ps1`

**Files:**
- Modify: `scripts/device/run_termux_smoke.ps1`

**Step 1: Write a syntax validation check**
Run: `powershell -Command "$null = [scriptblock]::Create((Get-Content scripts/device/run_termux_smoke.ps1 -Raw))"`
Expected: PASS (exits 0 with no syntax errors)

**Step 2: Modify run_termux_smoke.ps1**
Open `scripts/device/run_termux_smoke.ps1` and apply these changes:
- Before pushing the scripts, run:
  ```powershell
  Write-Host "Cleaning up stale on-device APK if it exists..."
  Invoke-AdbAllowFail -Args @("shell", "rm", "-f", "/sdcard/Download/app-release.apk") | Out-Host
  ```
- Change the tail validation logic and reorder execution:
  Move the `$required` checklist verification block to execute right after reading the log content, but before executing `pm uninstall`, `adb pull`, and `adb install`.
  ```powershell
  $log = (& $Adb @AdbArgs shell "cat $RemoteLog 2>&1") -join "`n"
  Write-Host "===== Full Termux smoke log ====="
  Write-Host $log

  $required = @(
      "INSTALL_STATUS=0",
      "POST_INSTALL_STATUS=0",
      "FLUTTER_VERSION_STATUS=0",
      "DART_VERSION_STATUS=0",
      "DARTVM_VERSION_STATUS=0",
      "DOCTOR_STATUS=0",
      "CREATE_STATUS=0",
      "BUILD_APK_STATUS=0",
      "APK_MANIFEST_STATUS=0",
      "APK_RESOURCES_STATUS=0",
      "APK_COPY_STATUS=0",
      "BUILD_LINUX_STATUS=0",
      "DONE"
  )
  foreach ($marker in $required) {
      if ($log -notmatch [regex]::Escape($marker)) {
          throw "Missing smoke marker: $marker"
      }
  }

  Write-Host "Uninstalling previous package if it exists..."
  Invoke-AdbAllowFail -Args @("shell", "pm", "uninstall", "com.example.flutter_ci_smoke")

  $localApk = "$work/app-release.apk"
  if (Test-Path $localApk) {
      Write-Host "Cleaning up stale host-side APK: $localApk"
      Remove-Item $localApk -Force
  }

  Write-Host "Pulling built APK to host..."
  Invoke-Adb -Args @("pull", "/sdcard/Download/app-release.apk", $localApk)

  Write-Host "Installing pulled APK from host..."
  Invoke-Adb -Args @("install", "-r", $localApk)

  Write-Host "Termux Flutter smoke passed."
  ```

**Step 3: Verify script syntax**
Run: `powershell -Command "$null = [scriptblock]::Create((Get-Content scripts/device/run_termux_smoke.ps1 -Raw))"`
Expected: PASS

**Step 4: Commit**
```bash
git add scripts/device/run_termux_smoke.ps1
git commit -m "fix: validate required markers in run_termux_smoke.ps1 before pulling and installing the APK, and clear stale device APKs"
```

---

### Task 2: Align Default Deb URL and SHA Parameters to v3.44.2

**Files:**
- Modify: `scripts/device/run_termux_smoke.ps1`
- Modify: `.github/workflows/device-smoke.yml`

**Step 1: Verify repository contract status**
Run: `python scripts/ci/check_repo.py`
Expected: PASS

**Step 2: Update default parameters in run_termux_smoke.ps1**
```powershell
# In scripts/device/run_termux_smoke.ps1, update default values in param block:
    [string]$DebUrl = "https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2-termux/flutter_3.44.2_aarch64.deb",
    [string]$ExpectedSha256 = "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000",
```

**Step 3: Update default inputs in device-smoke.yml**
```yaml
# In .github/workflows/device-smoke.yml, update defaults:
      deb_url:
        description: Deb URL to test. Leave default for latest v3.44.2 release asset.
        required: true
        default: https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2-termux/flutter_3.44.2_aarch64.deb
      expected_sha256:
        description: Expected SHA256 for the deb under test
        required: true
        default: 66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000
```

**Step 4: Run repository contract checks**
Run: `python scripts/ci/check_repo.py`
Expected: PASS

**Step 5: Commit**
```bash
git add scripts/device/run_termux_smoke.ps1 .github/workflows/device-smoke.yml
git commit -m "fix: update run_termux_smoke.ps1 and device-smoke.yml defaults to point to v3.44.2 release assets"
```
