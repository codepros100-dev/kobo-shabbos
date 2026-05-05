<#
.SYNOPSIS
  Copies the Shabbos Dashboard files to a connected Kobo.

.DESCRIPTION
  Run after you have:
    1. Installed KFMon on the Kobo (see README.md, Step 2).
    2. Connected the Kobo via USB and accepted the connection on the device.

  This script:
    - Auto-detects the Kobo drive (KOBOeReader / removable volume containing .kobo).
    - Copies the dashboard scripts to /mnt/onboard/.adds/dashboard/ on the device.
    - Copies the KFMon trigger ini and a 1-byte trigger book.
    - Prompts you for your published-PNG URL and writes dashboard.conf.

.PARAMETER KoboDrive
  Optional. e.g. "F:". If omitted, the script will probe drive letters.

.PARAMETER DashboardUrl
  Optional. If omitted, you'll be prompted.
#>
param(
    [string]$KoboDrive,
    [string]$DashboardUrl
)

$ErrorActionPreference = "Stop"

function Find-KoboDrive {
    Get-Volume | Where-Object {
        $_.DriveLetter -and $_.DriveType -eq "Removable"
    } | ForEach-Object {
        $root = "$($_.DriveLetter):\"
        if (Test-Path (Join-Path $root ".kobo")) { return $root }
    } | Select-Object -First 1
}

if (-not $KoboDrive) {
    $KoboDrive = Find-KoboDrive
    if (-not $KoboDrive) {
        Write-Error "No Kobo drive detected. Plug in the device, accept the USB connection, then re-run with -KoboDrive F:\"
        exit 1
    }
} else {
    if (-not $KoboDrive.EndsWith("\")) { $KoboDrive += "\" }
}

Write-Host "Using Kobo drive: $KoboDrive"

if (-not $DashboardUrl) {
    Write-Host ""
    Write-Host "Enter the raw URL of the published dashboard PNG."
    Write-Host "Format: https://raw.githubusercontent.com/<user>/<repo>/dashboard/dashboard.png"
    $DashboardUrl = Read-Host "URL"
}
if ([string]::IsNullOrWhiteSpace($DashboardUrl)) {
    Write-Error "DashboardUrl required."
    exit 1
}

# ---- Paths ----
$srcRoot   = Split-Path -Parent $PSScriptRoot   # ...\kobo\
$srcBin    = Join-Path $srcRoot "bin"
$dstAdds   = Join-Path $KoboDrive ".adds\dashboard"
$dstKfmon  = Join-Path $KoboDrive ".adds\kfmon\config"
$dstTrig   = Join-Path $KoboDrive "Dashboard.png"

New-Item -ItemType Directory -Force -Path $dstAdds  | Out-Null
New-Item -ItemType Directory -Force -Path $dstKfmon | Out-Null

Write-Host "Copying dashboard scripts -> $dstAdds"
Copy-Item -Force (Join-Path $srcBin "update-dashboard.sh") $dstAdds
Copy-Item -Force (Join-Path $srcBin "dashboard-loop.sh")   $dstAdds

# Strip CRLF -> LF on the shell scripts (Kobo runs busybox sh and chokes on \r)
foreach ($f in @("update-dashboard.sh","dashboard-loop.sh")) {
    $p = Join-Path $dstAdds $f
    $bytes = [IO.File]::ReadAllBytes($p)
    $text  = [Text.Encoding]::UTF8.GetString($bytes) -replace "`r`n","`n" -replace "`r","`n"
    [IO.File]::WriteAllBytes($p, [Text.Encoding]::UTF8.GetBytes($text))
}

# Write dashboard.conf
$conf = @"
DASHBOARD_URL="$DashboardUrl"
REFRESH_SECONDS=3600
REPAINT_SECONDS=300
WIFI_WAIT_SECONDS=120
"@
$confPath = Join-Path $dstAdds "dashboard.conf"
[IO.File]::WriteAllBytes($confPath, [Text.Encoding]::UTF8.GetBytes(($conf -replace "`r`n","`n")))
Write-Host "Wrote $confPath"

# Copy KFMon ini
$iniSrc = Join-Path $PSScriptRoot "dashboard.ini"
$iniDst = Join-Path $dstKfmon  "dashboard.ini"
$iniText = (Get-Content $iniSrc -Raw) -replace "`r`n","`n"
[IO.File]::WriteAllBytes($iniDst, [Text.Encoding]::UTF8.GetBytes($iniText))
Write-Host "Wrote $iniDst"

# Trigger book — a 1x1 PNG visible in the Kobo library. Tapping it launches us.
if (-not (Test-Path $dstTrig)) {
    # 1x1 black PNG, base64
    $b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVQYV2NgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
    [IO.File]::WriteAllBytes($dstTrig, [Convert]::FromBase64String($b64))
    Write-Host "Created trigger book: $dstTrig"
}

Write-Host ""
Write-Host "Done. Eject the Kobo, then on the device:"
Write-Host "  1. The library will show a new book named 'Dashboard'."
Write-Host "  2. Tap it once after each reboot to start the loop."
Write-Host "  3. Make sure WiFi is configured in Settings - Connect."
Write-Host ""
Write-Host "Tip: if the dashboard doesn't draw, look at the log on the Kobo:"
Write-Host "  /mnt/onboard/.adds/dashboard/cache/dashboard.log"
Write-Host "It's visible from your PC at $KoboDrive`.adds\dashboard\cache\dashboard.log"
