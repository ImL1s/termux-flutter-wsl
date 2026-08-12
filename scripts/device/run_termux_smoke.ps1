param(
    [string]$AdbPath = "adb",
    [string]$DeviceSerial = "",
    [string]$DebPath = "",
    [string]$DebUrl = "https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.2-termux/flutter_3.44.2_aarch64.deb",
    [string]$ExpectedSha256 = "66a7099324c0d7094d604aa92abeec87b7a29b8e0bc697b819e0cd91fc706000",
    [int]$TimeoutMinutes = 45,
    [string]$RemoteDeb = "/sdcard/Download/flutter_ci_input.deb",
    [string]$RemoteScript = "/sdcard/Download/termux_ci_smoke.sh",
    [string]$RemoteLog = "/sdcard/Download/termux_ci_smoke.txt",
    [string]$CommitSha = "",
    [string]$ArtifactSourceCommit = "",
    [string]$VerifierCommit = "",
    [string]$EvidencePath = "evidence.json"
)

$ErrorActionPreference = "Stop"

function Resolve-Adb {
    param([string]$Value)
    if (Test-Path -LiteralPath $Value) { return (Resolve-Path -LiteralPath $Value).Path }
    $cmd = Get-Command $Value -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "adb not found. Pass -AdbPath with the full platform-tools adb path."
}

function Write-InitialEvidence {
    param([string]$Status = "failed", [string]$Path = "evidence.json")
    $initObj = [ordered]@{
        status = $Status
        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        apk_launch = $false
        crash_free = $false
        commit_sha = if ($ArtifactSourceCommit) { $ArtifactSourceCommit } elseif ($CommitSha) { $CommitSha } else { "unknown" }
        source_commit = if ($ArtifactSourceCommit) { $ArtifactSourceCommit } elseif ($CommitSha) { $CommitSha } else { "unknown" }
        artifact_source_commit = if ($ArtifactSourceCommit) { $ArtifactSourceCommit } elseif ($CommitSha) { $CommitSha } else { "unknown" }
        verifier_commit = if ($VerifierCommit) { $VerifierCommit } elseif ($CommitSha) { $CommitSha } else { "unknown" }
        device_serial = "[REDACTED]"
        artifacts = [ordered]@{
            deb_sha256 = if (Test-Path $DebPath) { Get-Sha256Hex -Path $DebPath } else { "unknown" }
            deb_size = if (Test-Path $DebPath) { (Get-Item $DebPath).Length } else { 0 }
            apk_sha256 = "unknown"
            apk_size = 0
            aab_sha256 = "unknown"
            aab_size = 0
        }
        verification_details = [ordered]@{
            package_name = "com.example.flutter_ci_smoke"
            component = "com.example.flutter_ci_smoke/.MainActivity"
            initial_pid = ""
            app_pid = ""
            same_pid_observations = 0
            observation_duration_seconds = 0
            scoped_crash_free = $false
        }
        launch_result = "failed"
        exit_status = 1
        mode_a_status = "failed"
        mode_b_status = "failed"
        mode_a = [ordered]@{
            status = "failed"
            apk_build = "failed"
        }
        mode_b = [ordered]@{
            status = "failed"
            aab_build = "failed"
        }
    }
    $initObj | ConvertTo-Json -Depth 5 | Set-Content -Path $Path -Encoding UTF8
}

$Adb = Resolve-Adb $AdbPath

if (-not $DeviceSerial) {
    try {
        $devicesOutput = & $Adb devices 2>$null | Where-Object { $_ -match "\tdevice$" }
        $serials = @($devicesOutput | ForEach-Object { ($_ -split "\s+")[0] })
        if ($serials.Count -eq 1) {
            $DeviceSerial = $serials[0]
        } elseif ($serials.Count -gt 1) {
            $realDevices = @($serials | Where-Object { $_ -notlike "emulator-*" })
            if ($realDevices.Count -ge 1) {
                $DeviceSerial = $realDevices[0]
            } else {
                $DeviceSerial = $serials[0]
            }
        }
    } catch {
        # Fall back if adb devices fails
    }
}

$AdbArgs = @()
if ($DeviceSerial) {
    Write-Host "Using ADB device serial: $DeviceSerial"
    $AdbArgs += @("-s", $DeviceSerial)
}

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & $Adb @AdbArgs @Args
    if ($LASTEXITCODE -ne 0) { throw "adb $($Args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Invoke-AdbAllowFail {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & $Adb @AdbArgs @Args
}

function Get-Sha256Hex {
    param([Parameter(Mandatory=$true)][string]$Path)

    $cmd = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($cmd) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $hash = $sha256.ComputeHash($stream)
            return -join ($hash | ForEach-Object { $_.ToString("x2") })
        } finally {
            if ($sha256) { $sha256.Dispose() }
        }
    } finally {
        $stream.Dispose()
    }
}

function Get-DisplayState {
    $display = (& $Adb @AdbArgs shell "dumpsys display 2>/dev/null | grep 'Display State=' | head -1") -join "`n"
    if ($display -match "Display State=([A-Z]+)") { return $Matches[1] }
    return "UNKNOWN"
}

function Wake-Device {
    Write-Host "Keeping tablet awake for smoke test"
    Invoke-AdbAllowFail -Args @("shell", "svc", "power", "stayon", "true") | Out-Host
    $script:KeepAwakeEnabled = $true

    for ($i = 0; $i -lt 15; $i++) {
        Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "224") | Out-Null  # KEYCODE_WAKEUP
        Start-Sleep -Seconds 1
        $state = Get-DisplayState
        if ($state -eq "ON") {
            Write-Host "Display is ON"
            break
        }
        if ($i -eq 4) {
            Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "26") | Out-Null  # power-key fallback
        }
    }

    Invoke-AdbAllowFail -Args @("shell", "settings", "put", "system", "accidental_touch_protection", "0") | Out-Null
    Invoke-AdbAllowFail -Args @("shell", "settings", "put", "secure", "block_accidental_touches", "0") | Out-Null
    Invoke-AdbAllowFail -Args @("shell", "wm", "dismiss-keyguard") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "swipe", "540", "1400", "540", "100", "300") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "82") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "swipe", "540", "1400", "540", "100", "300") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "4") | Out-Host
    Start-Sleep -Seconds 2
}

function Assert-DeviceUnlocked {
    $window = (& $Adb @AdbArgs shell "dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mDreamingLockscreen|mShowingLockscreen' | head -20") -join "`n"
    if ($window -match "mDreamingLockscreen=true" -or $window -match "mCurrentFocus=.*NotificationShade") {
        throw "Tablet is still on the lock screen. Unlock it before running device smoke; secure lock screens block ADB text injection into Termux."
    }
}

function Write-InitialEvidence {
    param([string]$Path, [string]$Commit)
    $hostPath = if ([System.IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path (Get-Location) $Path }
    $initObj = [ordered]@{
        status = "failed"
        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        device = "unknown"
        apk_launch = $false
        crash_free = $false
        commit_sha = if ($Commit) { $Commit } else { "unknown" }
        device_serial = "unknown"
        device_info = [ordered]@{
            model = "unknown"
            sdk = "unknown"
            abi = "unknown"
            serial = "unknown"
        }
        launch_result = "failed"
        exit_status = 1
        mode_a_status = "failed"
        mode_b_status = "failed"
        mode_a = [ordered]@{
            status = "failed"
            apk_build = "failed"
        }
        mode_b = [ordered]@{
            status = "failed"
            aab_build = "failed"
        }
    }
    $initObj | ConvertTo-Json -Depth 5 | Set-Content -Path $hostPath -Encoding UTF8
}

Write-InitialEvidence -Path $EvidencePath -Commit $CommitSha

$KeepAwakeEnabled = $false

try {
$work = Join-Path $env:TEMP "termux-flutter-smoke"
New-Item -ItemType Directory -Force -Path $work | Out-Null

if (-not $DebPath) {
    $DebPath = Join-Path $work "flutter_ci_input.deb"
    Write-Host "Downloading deb from $DebUrl"
    Invoke-WebRequest -Uri $DebUrl -OutFile $DebPath
}

if (-not (Test-Path -LiteralPath $DebPath)) { throw "Deb not found: $DebPath" }

if ($ExpectedSha256) {
    $actual = Get-Sha256Hex -Path $DebPath
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA256 mismatch. Expected $ExpectedSha256, got $actual"
    }
    Write-Host "SHA256 OK: $actual"
}

Write-Host "ADB devices:"
$devicesOutput = (& $Adb @AdbArgs devices) -join "`n"
Write-Host $devicesOutput
if ($devicesOutput -notmatch "(?m)^[a-zA-Z0-9_.-]+\s+(device|unauthorized)") {
    throw "No active ADB device connected. Output: $devicesOutput"
}

Wake-Device
Assert-DeviceUnlocked

$scriptLocal = Join-Path $work "termux_ci_smoke.sh"
Copy-Item -LiteralPath (Join-Path (Get-Location) "scripts/device/termux_smoke.sh") -Destination $scriptLocal -Force

Invoke-Adb -Args @("push", $DebPath, $RemoteDeb)
Invoke-Adb -Args @("push", $scriptLocal, $RemoteScript)
Invoke-AdbAllowFail -Args @("shell", "rm", "-f", $RemoteLog) | Out-Host
Invoke-AdbAllowFail -Args @("shell", "rm", "-f", "/sdcard/Download/app-release.apk") | Out-Host

Write-Host "Launching Termux and starting smoke script"
Wake-Device
Invoke-AdbAllowFail -Args @("shell", "am", "force-stop", "com.termux") | Out-Host
Start-Sleep -Seconds 1
Invoke-Adb -Args @("shell", "am", "start", "-n", "com.termux/.app.TermuxActivity") | Out-Host
Start-Sleep -Seconds 3
Invoke-AdbAllowFail -Args @("shell", "wm", "dismiss-keyguard") | Out-Host
Invoke-AdbAllowFail -Args @("shell", "input", "swipe", "500", "1200", "500", "200", "300") | Out-Host
Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "4") | Out-Host

$startDeadline = (Get-Date).AddMinutes(2)
$started = $false
while ((Get-Date) -lt $startDeadline) {
    # Ensure screen is awake, unlocked, and accidental touch protection overlay is dismissed
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "224") | Out-Null
    Invoke-AdbAllowFail -Args @("shell", "wm", "dismiss-keyguard") | Out-Null
    Invoke-AdbAllowFail -Args @("shell", "input", "swipe", "540", "1600", "540", "200", "200") | Out-Null
    Start-Sleep -Milliseconds 500
    # Ensure soft keyboard/popups are closed and focus is on terminal prompt
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "4") | Out-Null
    Start-Sleep -Milliseconds 500
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "66") | Out-Null
    Start-Sleep -Milliseconds 500
    Invoke-Adb -Args @("shell", "input", "text", "sh%s$RemoteScript")
    Start-Sleep -Milliseconds 500
    Invoke-Adb -Args @("shell", "input", "keyevent", "66")
    Start-Sleep -Seconds 5
    
    $probe = (& $Adb @AdbArgs shell "cat $RemoteLog 2>/dev/null || true") -join "`n"
    if ($probe -match "TERMUX_CI_SMOKE") {
        $started = $true
        break
    }
}
if (-not $started) {
    Invoke-AdbAllowFail -Args @("shell", "screencap", "-p", "/sdcard/Download/termux_ci_smoke_start_failed.png") | Out-Null
    throw "Termux smoke did not start within 2 minutes; check /sdcard/Download/termux_ci_smoke_start_failed.png on the device."
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$last = ""
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    $tail = (& $Adb @AdbArgs shell "tail -120 $RemoteLog 2>&1") -join "`n"
    if ($tail -ne $last) {
        Write-Host "----- Termux smoke tail -----"
        Write-Host $tail
        $last = $tail
    }
    if ($tail -match "(?m)^DONE\s*$") { break }
}

$log = (& $Adb @AdbArgs shell "cat $RemoteLog 2>&1") -join "`n"
Write-Host "===== Full Termux smoke log ====="
Write-Host $log

$required = @(
    "APT_REPAIR_STATUS=0",
    "INSTALL_STATUS=0",
    "POST_INSTALL_STATUS=0",
    "FLUTTER_VERSION_STATUS=0",
    "DART_VERSION_STATUS=0",
    "DARTVM_VERSION_STATUS=0",
    "DOCTOR_STATUS=0",
    "CREATE_STATUS=0",
    "CONFIG_VERIFY_STATUS=0",
    "BUILD_APK_STATUS=0",
    "APK_MANIFEST_STATUS=0",
    "APK_RESOURCES_STATUS=0",
    "APK_COPY_STATUS=0",
    "BUILD_LINUX_STATUS=0",
    "BUILD_AAB_STATUS=0",
    "AAB_COPY_STATUS=0",
    "DONE"
)
foreach ($marker in $required) {
    if ($log -notmatch [regex]::Escape($marker)) {
        throw "Missing smoke marker: $marker"
    }
}

$hasLocalLaunch = ($log -match "APK_LAUNCH_STATUS=0" -and $log -match "APK_CRASH_FREE_STATUS=0")
$hasHostRequired = ($log -match "APK_HOST_VERIFY_REQUIRED=0")
if (-not ($hasLocalLaunch -xor $hasHostRequired)) {
    throw "Smoke log must contain exactly one launch verification marker pair: either (APK_LAUNCH_STATUS=0 AND APK_CRASH_FREE_STATUS=0) OR APK_HOST_VERIFY_REQUIRED=0"
}

Write-Host "Uninstalling previous package if it exists..."
Invoke-AdbAllowFail -Args @("shell", "pm", "uninstall", "com.example.flutter_ci_smoke")

$localApk = "$work/app-release.apk"
$localAab = "$work/app-release.aab"
if (Test-Path $localApk) { Remove-Item $localApk -Force }
if (Test-Path $localAab) { Remove-Item $localAab -Force }

Write-Host "Pulling built APK and AAB to host..."
Invoke-Adb -Args @("pull", "/sdcard/Download/app-release.apk", $localApk)
Invoke-Adb -Args @("pull", "/sdcard/Download/app-release.aab", $localAab)
if (-not (Test-Path $localAab) -or (Get-Item $localAab).Length -eq 0) {
    throw "Failed to pull built AAB from device or AAB file is empty: $localAab"
}

$apkSha256 = if (Test-Path $localApk) { Get-Sha256Hex -Path $localApk } else { "unknown" }
$apkSize = if (Test-Path $localApk) { (Get-Item $localApk).Length } else { 0 }

$aabSha256 = if (Test-Path $localAab) { Get-Sha256Hex -Path $localAab } else { "unknown" }
$aabSize = if (Test-Path $localAab) { (Get-Item $localAab).Length } else { 0 }

Write-Host "Pulled APK SHA-256: $apkSha256, Size: $apkSize bytes"
Write-Host "Pulled AAB SHA-256: $aabSha256, Size: $aabSize bytes"

Write-Host "Removing stale package state..."
Invoke-AdbAllowFail -Args @("shell", "pm", "uninstall", "com.example.flutter_ci_smoke") | Out-Null

Write-Host "Installing pulled APK from host..."
Invoke-Adb -Args @("install", "-r", $localApk)

$pkgList = (& $Adb @AdbArgs shell "pm list packages | grep com.example.flutter_ci_smoke 2>/dev/null || true") -join ""
if (-not ($pkgList -match "com.example.flutter_ci_smoke")) {
    throw "Package com.example.flutter_ci_smoke is not installed on target device."
}
Write-Host "Verified package identity: com.example.flutter_ci_smoke"

Write-Host "Clearing ADB logcat buffer before launch..."
Invoke-AdbAllowFail -Args @("logcat", "-c") | Out-Null

Write-Host "Verifying APK launch and crash-free execution from host ADB..."
Invoke-AdbAllowFail -Args @("shell", "am", "start", "-W", "-n", "com.example.flutter_ci_smoke/.MainActivity") | Out-Host

$livenessPassed = $true
$appPid = ""
$initialPid = ""
for ($check = 1; $check -le 3; $check++) {
    Start-Sleep -Seconds 2
    $pidCurrent = ((& $Adb @AdbArgs shell "pidof com.example.flutter_ci_smoke 2>/dev/null || true") -join "").Trim()
    if (-not $pidCurrent) {
        $livenessPassed = $false
        break
    }
    if (-not $initialPid) {
        $initialPid = $pidCurrent
        $appPid = $initialPid
    } elseif ($pidCurrent -ne $initialPid) {
        $livenessPassed = $false
        break
    }
}

$crashLogs = (& $Adb @AdbArgs shell "logcat -d 2>/dev/null | grep -E -i 'FATAL EXCEPTION.*com\.example\.flutter_ci_smoke|AndroidRuntime.*com\.example\.flutter_ci_smoke|SIGSEGV.*com\.example\.flutter_ci_smoke|SIGABRT.*com\.example\.flutter_ci_smoke' || true") -join "`n"
$hasCrash = ($crashLogs -match "FATAL EXCEPTION" -or $crashLogs -match "SIGSEGV" -or $crashLogs -match "SIGABRT")

$apkLaunchHost = [bool]($initialPid -ne "" -and $livenessPassed)
$crashFreeHost = [bool]($apkLaunchHost -and (-not $hasCrash))

Write-Host "Host APK launch verification: initialPid=$initialPid, liveness=$livenessPassed, apk_launch=$apkLaunchHost, crash_free=$crashFreeHost"

$hostEvidencePath = if ([System.IO.Path]::IsPathRooted($EvidencePath)) { $EvidencePath } else { Join-Path (Get-Location) $EvidencePath }
$remoteEvidence = "/sdcard/Download/evidence.json"

$model = ((& $Adb @AdbArgs shell "getprop ro.product.model 2>/dev/null || true") -join "").Trim()
$sdk = ((& $Adb @AdbArgs shell "getprop ro.build.version.sdk 2>/dev/null || true") -join "").Trim()
$abi = ((& $Adb @AdbArgs shell "getprop ro.product.cpu.abi 2>/dev/null || true") -join "").Trim()
$serial = "[REDACTED]"
if (-not $model) { $model = "unknown" }
if (-not $sdk) { $sdk = "unknown" }
if (-not $abi) { $abi = "unknown" }

$verifierCommitMeasured = if ($VerifierCommit) { $VerifierCommit } else {
    try { (git rev-parse HEAD 2>$null).Trim().ToLower() } catch { if ($CommitSha) { $CommitSha } else { "unknown" } }
}

$remoteEvidenceTmp = "/data/local/tmp/evidence.json"
$remoteEvidenceSdcard = "/sdcard/Download/evidence.json"
$rawEv = $null
try {
    $tempEv = Join-Path $work "evidence_remote.json"
    Invoke-AdbAllowFail -Args @("pull", $remoteEvidenceTmp, $tempEv) | Out-Null
    if (-not (Test-Path $tempEv) -or (Get-Item $tempEv).Length -eq 0) {
        Invoke-AdbAllowFail -Args @("pull", $remoteEvidenceSdcard, $tempEv) | Out-Null
    }
    if (-not (Test-Path $tempEv) -or (Get-Item $tempEv).Length -eq 0) {
        $content = (& $Adb @AdbArgs shell "cat $remoteEvidenceTmp 2>/dev/null || cat $remoteEvidenceSdcard 2>/dev/null || cat /data/data/com.termux/files/home/.termux_smoke/evidence.json 2>/dev/null || true") -join "`n"
        if ($content -and $content.Trim().StartsWith("{")) {
            Set-Content -Path $tempEv -Value $content -Encoding UTF8
        }
    }
    if (Test-Path $tempEv) {
        $rawEv = Get-Content -Raw -Path $tempEv | ConvertFrom-Json
    }
} catch {
    Write-Host "Warning: Could not pull remote evidence.json"
}

$artifactCommitMeasured = if ($ArtifactSourceCommit) { $ArtifactSourceCommit } else {
    if ($rawEv -and $rawEv.commit_sha -and $rawEv.commit_sha -ne "unknown") { $rawEv.commit_sha } else { $verifierCommitMeasured }
}

$launchPassed = [bool]($apkLaunchHost -and $crashFreeHost)
$exitStatus = if ($launchPassed) { 0 } else { 1 }
$modeA = if ($rawEv -and $rawEv.mode_a_status) { $rawEv.mode_a_status } else { "failed" }
$modeB = if ($rawEv -and $rawEv.mode_b_status) { $rawEv.mode_b_status } else { "failed" }

$modeAApkBuild = if ($rawEv -and $rawEv.mode_a -and $rawEv.mode_a.apk_build) { $rawEv.mode_a.apk_build } else { $modeA }
$modeBAabBuild = if ($rawEv -and $rawEv.mode_b -and $rawEv.mode_b.aab_build) { $rawEv.mode_b.aab_build } else { $modeB }
$overallStatus = if ($launchPassed -and $modeA -eq "passed" -and $modeB -eq "passed") { "passed" } else { "failed" }

$apkSha256 = if ($rawEv -and $rawEv.artifacts -and $rawEv.artifacts.apk_sha256) { $rawEv.artifacts.apk_sha256 } else { "unknown" }
$apkSize = if ($rawEv -and $rawEv.artifacts -and $rawEv.artifacts.apk_size) { $rawEv.artifacts.apk_size } else { 0 }
$aabSha256 = if ($rawEv -and $rawEv.artifacts -and $rawEv.artifacts.aab_sha256) { $rawEv.artifacts.aab_sha256 } else { "unknown" }
$aabSize = if ($rawEv -and $rawEv.artifacts -and $rawEv.artifacts.aab_size) { $rawEv.artifacts.aab_size } else { 0 }

$evObj = [ordered]@{
    status = $overallStatus
    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    device = $model
    apk_launch = [bool]$apkLaunchHost
    crash_free = [bool]$crashFreeHost
    commit_sha = $artifactCommitMeasured
    source_commit = $artifactCommitMeasured
    artifact_source_commit = $artifactCommitMeasured
    verifier_commit = $verifierCommitMeasured
    device_serial = "[REDACTED]"
    device_info = [ordered]@{
        model = $model
        sdk = $sdk
        abi = $abi
        serial = "[REDACTED]"
    }
    artifacts = [ordered]@{
        deb_sha256 = if (Test-Path $DebPath) { Get-Sha256Hex -Path $DebPath } else { "unknown" }
        deb_size = if (Test-Path $DebPath) { (Get-Item $DebPath).Length } else { 0 }
        apk_sha256 = $apkSha256
        apk_size = $apkSize
        aab_sha256 = $aabSha256
        aab_size = $aabSize
    }
    verification_details = [ordered]@{
        package_name = "com.example.flutter_ci_smoke"
        component = "com.example.flutter_ci_smoke/.MainActivity"
        initial_pid = $initialPid
        app_pid = $initialPid
        same_pid_observations = 3
        observation_duration_seconds = 6
        scoped_crash_free = [bool](-not $hasCrash)
    }
    launch_result = if ($launchPassed) { "passed" } else { "failed" }
    exit_status = $exitStatus
    mode_a_status = $modeA
    mode_b_status = $modeB
    mode_a = [ordered]@{
        status = $modeA
        apk_build = $modeAApkBuild
    }
    mode_b = [ordered]@{
        status = $modeB
        aab_build = $modeBAabBuild
    }
}


$evObj | ConvertTo-Json -Depth 5 | Set-Content -Path $hostEvidencePath -Encoding UTF8
Write-Host "Wrote evidence artifact to $hostEvidencePath"

if (-not $apkLaunchHost) {
    throw "APK launch verification failed on host"
}
if (-not $crashFreeHost) {
    throw "APK crash-free verification failed on host"
}

Write-Host "Termux Flutter smoke passed."
} finally {
    if ($KeepAwakeEnabled) {
        Write-Host "Restoring tablet stay-awake setting"
        Invoke-AdbAllowFail -Args @("shell", "svc", "power", "stayon", "false") | Out-Host
    }
}
