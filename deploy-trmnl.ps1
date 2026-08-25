<#
.SYNOPSIS
    Install the TRMNL client on a connected Kobo, pointed at our own
    GitHub-hosted dashboard (BYOS, no server needed).

.DESCRIPTION
    Replaces the old show-dashboard.sh / SIGSTOP-nickel approach, which froze
    the device and needed a power-cycle. The TRMNL client instead:
      fetch image -> paint via its own fbink -> suspend with an RTC wake
      alarm -> wake -> repeat. No touching needed; e-ink keeps the image
      while asleep; battery lasts weeks.

    Steps:
      1. Detect the Kobo drive.
      2. Download trmnl-kobo latest release zip (cached in _downloads/).
      3. If Kobostuff is not yet installed on the device, stage its
         KoboRoot.tgz (provides curl + jq the client needs) -> EJECT ONCE,
         let the Kobo reboot, reconnect, and run this script again.
      4. Copy TRMNL client to .adds\TRMNL with config.json pointing at
         https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard
      5. Append TRMNL entry to NickelMenu config.

    Usage on the Kobo afterwards:
      - Tap  NickelMenu -> TRMNL  (e.g. Friday before Shabbos).
        It takes over the screen and refreshes hourly, sleeping in between.
      - To exit (after Shabbos): press power once to wake, then HOLD power
        until the light blinks rapidly, release. Device reboots into Nickel.

.PARAMETER KoboDrive
    Optional, e.g. "D:". Auto-detected if omitted.
#>
param(
    [string]$KoboDrive
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dl   = Join-Path $root "_downloads"
New-Item -ItemType Directory -Force -Path $dl | Out-Null

function Find-KoboDrive {
    Get-Volume |
        Where-Object { $_.DriveLetter -and $_.DriveType -eq "Removable" } |
        ForEach-Object {
            $r = "$($_.DriveLetter):\"
            if (Test-Path (Join-Path $r ".kobo")) { return $r }
        } | Select-Object -First 1
}

if (-not $KoboDrive) {
    $KoboDrive = Find-KoboDrive
    if (-not $KoboDrive) {
        Write-Error "Kobo not detected. Plug in & tap Connect on the device."
        exit 1
    }
} elseif (-not $KoboDrive.EndsWith("\")) { $KoboDrive += "\" }
Write-Host "Kobo at: $KoboDrive"

# --- 1. Get the trmnl-kobo release zip (cached) -----------------------------
$rel = Invoke-RestMethod -UseBasicParsing `
    -Uri "https://api.github.com/repos/usetrmnl/trmnl-kobo/releases/latest" `
    -Headers @{ "User-Agent" = "kobo-deploy" }
$asset = $rel.assets | Where-Object { $_.name -like "trmnl-kobo-*.zip" } | Select-Object -First 1
$zip = Join-Path $dl $asset.name
if (-not (Test-Path $zip)) {
    Write-Host "Downloading $($asset.name)..."
    Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $zip
}
$ex = Join-Path $dl "trmnl-extracted"
if (Test-Path $ex) { Remove-Item -Recurse -Force $ex }
Expand-Archive -Path $zip -DestinationPath $ex
# release zip may nest under a top folder; locate src/
$srcDir = Get-ChildItem -Path $ex -Recurse -Directory -Filter "TRMNL" |
    Where-Object { Test-Path (Join-Path $_.FullName "trmnl.sh") } |
    Select-Object -First 1
if (-not $srcDir) { Write-Error "TRMNL folder not found in release zip"; exit 1 }
Write-Host "  [1/4] release $($rel.tag_name) extracted"

# --- 2. Kobostuff (curl + jq) — one-time, needs its own eject/reboot --------
# Kobostuff installs under /usr/local/niluje (not visible over USB), so use a
# marker file on the device to remember that we already staged it.
$marker = Join-Path $KoboDrive ".adds\TRMNL\.kobostuff-staged"
if (-not (Test-Path $marker)) {
    # Kobostuff is not in the release zip — fetch from the trmnl-kobo repo.
    $ksXz = Join-Path $dl "kobo-stuff.tar.xz"
    if (-not (Test-Path $ksXz)) {
        Write-Host "Downloading Kobostuff..."
        Invoke-WebRequest -UseBasicParsing -OutFile $ksXz -Uri `
            "https://raw.githubusercontent.com/usetrmnl/trmnl-kobo/main/doc/distrib/kobostuff/kobo-stuff-1.6.N-r18901.tar.xz"
    }
    $ksArchive = Get-Item $ksXz
    $ksDir = Join-Path $dl "kobostuff"
    New-Item -ItemType Directory -Force -Path $ksDir | Out-Null
    tar -xf $ksArchive.FullName -C $ksDir
    $ksRoot = Get-ChildItem -Path $ksDir -Recurse -Filter "KoboRoot.tgz" | Select-Object -First 1
    if (-not $ksRoot) { Write-Error "KoboRoot.tgz not found inside Kobostuff archive"; exit 1 }
    Copy-Item -Force $ksRoot.FullName (Join-Path $KoboDrive ".kobo\KoboRoot.tgz")
    New-Item -ItemType Directory -Force -Path (Split-Path $marker) | Out-Null
    Set-Content -Path $marker -Value "staged $(Get-Date -Format o)"
    Write-Host ""
    Write-Host "  [2/4] Kobostuff staged as .kobo\KoboRoot.tgz"
    Write-Host ""
    Write-Host "  >>> EJECT the Kobo now. It will show 'Updating...' and reboot. <<<"
    Write-Host "  >>> Then reconnect USB and run this script AGAIN to finish.    <<<"
    exit 0
}
Write-Host "  [2/4] Kobostuff already staged (marker present)"

# --- 3. TRMNL client + config ------------------------------------------------
$dst = Join-Path $KoboDrive ".adds\TRMNL"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force (Join-Path $srcDir.FullName "*") $dst

# BYOS config: our GitHub dashboard branch serves both /display (JSON) and
# the PNG. Id/Token are ignored by a static server but must be present.
# IgnoreCurlErrors=true -> on a bad fetch keep showing the last image
# instead of an error screen (important: unattended all Shabbos).
$config = @"
{
    "TrmnlId": "kobo-shabbos",
    "TrmnlToken": "unused",
    "TrmnlApiUrl": "https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard",
    "DebugToScreen": 0,
    "LoopMaxIteration": 0,
    "ConnectedGracePeriod": 5,
    "ImageFormat": "png",
    "IgnoreCurlErrors": "true",
    "WpaNetworkId": "-1"
}
"@ -replace "`r`n","`n"
[IO.File]::WriteAllBytes((Join-Path $dst "config.json"), [Text.Encoding]::UTF8.GetBytes($config))
Write-Host "  [3/4] TRMNL client -> .adds\TRMNL (BYOS -> GitHub dashboard branch)"

# --- 4. NickelMenu entry ------------------------------------------------------
$nmDir = Join-Path $KoboDrive ".adds\nm"
New-Item -ItemType Directory -Force -Path $nmDir | Out-Null
$nmCfg = @"
# Shabbos dashboard via TRMNL client (fetch -> paint -> RTC-sleep loop).
# Exit: wake with power button, then hold power until the light blinks.
menu_item :main :Shabbos Display :cmd_spawn :sh /mnt/onboard/.adds/TRMNL/trmnl.sh
"@ -replace "`r`n","`n"
[IO.File]::WriteAllBytes((Join-Path $nmDir "trmnl"), [Text.Encoding]::UTF8.GetBytes($nmCfg))

# retire the old SIGSTOP-based menu entries if present
$oldNm = Join-Path $nmDir "dashboard"
if (Test-Path $oldNm) {
    Rename-Item -Force $oldNm "$oldNm.disabled"
    Write-Host "  [4/4] NickelMenu entry added; old 'dashboard' menu disabled"
} else {
    Write-Host "  [4/4] NickelMenu entry added"
}

Write-Host ""
Write-Host "Done. Safely eject the Kobo, then on the device:"
Write-Host "  NickelMenu -> 'Shabbos Display' starts the loop."
Write-Host "  It refreshes hourly and sleeps in between - no touching needed."
