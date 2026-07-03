param(
    [string]$AdbPath = "adb",
    [string]$DeviceSerial = "",
    [string]$DebPath = "",
    [string]$DebUrl = "https://github.com/ImL1s/termux-flutter-wsl/releases/download/v3.44.0/flutter_3.44.0_aarch64.deb",
    [string]$ExpectedSha256 = "b8af08d26ee4ae4b3dcf1aab4ee6b05965529587ddf1bc9b936b48b5f01f9846",
    [int]$TimeoutMinutes = 45,
    [string]$RemoteDeb = "/sdcard/Download/flutter_ci_input.deb",
    [string]$RemoteScript = "/sdcard/Download/termux_ci_smoke.sh",
    [string]$RemoteLog = "/sdcard/Download/termux_ci_smoke.txt"
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
Invoke-Adb -Args @("devices")

Wake-Device
Assert-DeviceUnlocked

$scriptLocal = Join-Path $work "termux_ci_smoke.sh"
Copy-Item -LiteralPath (Join-Path (Get-Location) "scripts/device/termux_smoke.sh") -Destination $scriptLocal -Force

Invoke-Adb -Args @("push", $DebPath, $RemoteDeb)
Invoke-Adb -Args @("push", $scriptLocal, $RemoteScript)
Invoke-AdbAllowFail -Args @("shell", "rm", "-f", $RemoteLog) | Out-Host

Write-Host "Launching Termux and starting smoke script"
Wake-Device
Invoke-AdbAllowFail -Args @("shell", "am", "force-stop", "com.termux") | Out-Host
Start-Sleep -Seconds 1
Invoke-Adb -Args @("shell", "am", "start", "-n", "com.termux/.app.TermuxActivity") | Out-Host
Start-Sleep -Seconds 5
# Tap near the center of the screen to focus Termux terminal reliably on all screen sizes
Invoke-AdbAllowFail -Args @("shell", "input", "tap", "500", "500") | Out-Host
Start-Sleep -Seconds 1
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
    "BUILD_APK_STATUS=0",
    "BUILD_LINUX_STATUS=0",
    "DONE"
)
foreach ($marker in $required) {
    if ($log -notmatch [regex]::Escape($marker)) {
        throw "Missing smoke marker: $marker"
    }
}

Write-Host "Termux Flutter smoke passed."
} finally {
    if ($KeepAwakeEnabled) {
        Write-Host "Restoring tablet stay-awake setting"
        Invoke-AdbAllowFail -Args @("shell", "svc", "power", "stayon", "false") | Out-Host
    }
}
