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

$Adb = Resolve-Adb $AdbPath
$AdbArgs = @()
if ($DeviceSerial) { $AdbArgs += @("-s", $DeviceSerial) }

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

    Invoke-AdbAllowFail -Args @("shell", "wm", "dismiss-keyguard") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "keyevent", "82") | Out-Host
    Invoke-AdbAllowFail -Args @("shell", "input", "swipe", "800", "2200", "800", "300", "300") | Out-Host
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
Start-Sleep -Seconds 5
# Android input text uses %s for spaces.
Invoke-Adb -Args @("shell", "input", "text", "sh%s$RemoteScript")
Start-Sleep -Seconds 3
Invoke-Adb -Args @("shell", "input", "keyevent", "66")
Start-Sleep -Seconds 1
Invoke-Adb -Args @("shell", "input", "keyevent", "66")

$startDeadline = (Get-Date).AddMinutes(2)
$started = $false
while ((Get-Date) -lt $startDeadline) {
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
    "APK_LAUNCH_STATUS=0",
    "APK_CRASH_FREE_STATUS=0",
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

$apkSha256 = Get-Sha256Hex -Path $localApk
Write-Host "Pulled APK SHA-256: $apkSha256"

Write-Host "Clearing ADB logcat buffer before launch..."
Invoke-AdbAllowFail -Args @("logcat", "-c") | Out-Null

Write-Host "Installing pulled APK from host..."
Invoke-Adb -Args @("install", "-r", $localApk)

Write-Host "Verifying APK launch and crash-free execution from host ADB..."
Invoke-AdbAllowFail -Args @("shell", "am", "start", "-n", "com.example.flutter_ci_smoke/.MainActivity") | Out-Host
Start-Sleep -Seconds 3

$appPid = (& $Adb @AdbArgs shell "pidof com.example.flutter_ci_smoke 2>/dev/null || true") -join ""
$appPid = $appPid.Trim()
$crashCheck = (& $Adb @AdbArgs shell "logcat -d -t 1000 2>/dev/null | grep -i 'FATAL EXCEPTION.*com.example.flutter_ci_smoke' || true") -join ""
$crashCheck = $crashCheck.Trim()

$apkLaunchHost = ($appPid -ne "")
$crashFreeHost = ($apkLaunchHost -and ($crashCheck -eq ""))

Write-Host "Host APK launch verification: pid=$appPid, apk_launch=$apkLaunchHost, crash_free=$crashFreeHost"

$hostEvidencePath = if ([System.IO.Path]::IsPathRooted($EvidencePath)) { $EvidencePath } else { Join-Path (Get-Location) $EvidencePath }
$remoteEvidence = "/sdcard/Download/evidence.json"

$model = ((& $Adb @AdbArgs shell "getprop ro.product.model 2>/dev/null || true") -join "").Trim()
$sdk = ((& $Adb @AdbArgs shell "getprop ro.build.version.sdk 2>/dev/null || true") -join "").Trim()
$abi = ((& $Adb @AdbArgs shell "getprop ro.product.cpu.abi 2>/dev/null || true") -join "").Trim()
$serial = if ($DeviceSerial) { $DeviceSerial } else { ((& $Adb @AdbArgs shell "getprop ro.serialno 2>/dev/null || true") -join "").Trim() }
if (-not $serial) { $serial = "unknown" }
if (-not $model) { $model = "unknown" }
if (-not $sdk) { $sdk = "unknown" }
if (-not $abi) { $abi = "unknown" }

if (-not $CommitSha) {
    try {
        $CommitSha = (git rev-parse HEAD 2>$null).Trim()
    } catch {
        $CommitSha = "unknown"
    }
}

$rawEv = $null
try {
    $tempEv = Join-Path $work "evidence_remote.json"
    Invoke-AdbAllowFail -Args @("pull", $remoteEvidence, $tempEv) | Out-Null
    if (Test-Path $tempEv) {
        $rawEv = Get-Content -Raw -Path $tempEv | ConvertFrom-Json
    }
} catch {
    Write-Host "Warning: Could not pull remote evidence.json"
}

$launchPassed = [bool]($apkLaunchHost -and $crashFreeHost)
$exitStatus = if ($launchPassed) { 0 } else { 1 }
$modeA = if ($rawEv -and $rawEv.mode_a_status) { $rawEv.mode_a_status } else { "failed" }
$modeB = if ($rawEv -and $rawEv.mode_b_status) { $rawEv.mode_b_status } else { "failed" }

$modeAApkBuild = if ($rawEv -and $rawEv.mode_a -and $rawEv.mode_a.apk_build) { $rawEv.mode_a.apk_build } else { $modeA }
$modeBAabBuild = if ($rawEv -and $rawEv.mode_b -and $rawEv.mode_b.aab_build) { $rawEv.mode_b.aab_build } else { $modeB }
$overallStatus = if ($launchPassed -and $modeA -eq "passed") { "passed" } else { "failed" }

$evObj = [ordered]@{
    status = $overallStatus
    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    device = if ($model -and $model -ne "unknown") { $model } else { $serial }
    apk_launch = [bool]$apkLaunchHost
    crash_free = [bool]$crashFreeHost
    commit_sha = if ($rawEv -and $rawEv.commit_sha -and $rawEv.commit_sha -ne "unknown") { $rawEv.commit_sha } else { $CommitSha }
    device_serial = if ($rawEv -and $rawEv.device_serial -and $rawEv.device_serial -ne "unknown") { $rawEv.device_serial } else { $serial }
    device_info = [ordered]@{
        model = $model
        sdk = $sdk
        abi = $abi
        serial = $serial
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
