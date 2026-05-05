<#
.SYNOPSIS
    One-shot deploy: stage everything needed on a connected Kobo.

.DESCRIPTION
    Steps:
      1. Detect a mounted Kobo drive (KOBOeReader).
      2. Download NickelMenu's KoboRoot.tgz (latest release) -> .kobo/KoboRoot.tgz.
      3. Download KOReader's release zip and extract the bundled `fbink`
         binary (statically-linked ARM ELF).
      4. Copy fbink + dashboard scripts -> .adds/dashboard/.
      5. Copy NickelMenu config -> .adds/nm/dashboard.
      6. Copy library EPUBs -> Library/{01 Tanakh, 02 Siddur, 03 Shas Bavli}.

    After the script finishes: safely eject the Kobo to apply the install.

.PARAMETER KoboDrive
    Optional. e.g. "D:". Auto-detected if omitted.

.PARAMETER DashboardUrl
    Optional. The published-PNG URL the device fetches. Defaults to:
    https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png
#>
param(
    [string]$KoboDrive,
    [string]$DashboardUrl = "https://raw.githubusercontent.com/codepros100-dev/kobo-shabbos/dashboard/dashboard.png"
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
        Write-Error "Kobo not detected. Plug in & accept USB connection."
        exit 1
    }
} elseif (-not $KoboDrive.EndsWith("\")) { $KoboDrive += "\" }

Write-Host "Kobo at: $KoboDrive"

# 1. NickelMenu
$nmTgz = Join-Path $dl "nickelmenu.tgz"
if (-not (Test-Path $nmTgz)) {
    Write-Host "Fetching NickelMenu latest release..."
    $rel = Invoke-RestMethod -UseBasicParsing `
        -Uri "https://api.github.com/repos/pgaskin/NickelMenu/releases/latest" `
        -Headers @{ "User-Agent" = "kobo-deploy" }
    $url = ($rel.assets | Where-Object { $_.name -eq "KoboRoot.tgz" })[0].browser_download_url
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $nmTgz
}
Copy-Item -Force $nmTgz (Join-Path $KoboDrive ".kobo\KoboRoot.tgz")
Write-Host "  [1/6] dropped NickelMenu KoboRoot.tgz"

# 2. fbink (extracted from KOReader)
$fbink = Join-Path $dl "kor\fbink"
if (-not (Test-Path $fbink)) {
    Write-Host "Fetching KOReader release for bundled fbink..."
    $korRel = Invoke-RestMethod -UseBasicParsing `
        -Uri "https://api.github.com/repos/koreader/koreader/releases/latest" `
        -Headers @{ "User-Agent" = "kobo-deploy" }
    $korUrl = ($korRel.assets |
        Where-Object { $_.name -like "*kobo*.zip" })[0].browser_download_url
    $korZip = Join-Path $dl "koreader-kobo.zip"
    if (-not (Test-Path $korZip)) {
        Invoke-WebRequest -UseBasicParsing -Uri $korUrl -OutFile $korZip
    }
    Add-Type -Assembly System.IO.Compression.FileSystem
    $z = [System.IO.Compression.ZipFile]::OpenRead($korZip)
    $entry = $z.Entries | Where-Object { $_.FullName -eq "koreader/fbink" }
    New-Item -ItemType Directory -Force -Path (Join-Path $dl "kor") | Out-Null
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $fbink, $true)
    $z.Dispose()
}

$dstDash = Join-Path $KoboDrive ".adds\dashboard"
New-Item -ItemType Directory -Force -Path $dstDash | Out-Null
Copy-Item -Force $fbink (Join-Path $dstDash "fbink")
Write-Host "  [2/6] fbink ($(Get-Item (Join-Path $dstDash 'fbink')).Length bytes)"

# 3. shell scripts (LF endings)
foreach ($f in @("update-dashboard.sh","dashboard-loop.sh")) {
    $src = Get-Content (Join-Path $root "kobo\bin\$f") -Raw
    $lf  = $src -replace "`r`n","`n" -replace "`r","`n"
    [IO.File]::WriteAllBytes((Join-Path $dstDash $f), [Text.Encoding]::UTF8.GetBytes($lf))
}
Write-Host "  [3/6] shell scripts (LF endings)"

# 4. dashboard.conf
$conf = "DASHBOARD_URL=`"$DashboardUrl`"`nREFRESH_SECONDS=3600`nWIFI_WAIT_SECONDS=120`n"
[IO.File]::WriteAllBytes((Join-Path $dstDash "dashboard.conf"),
    [Text.Encoding]::UTF8.GetBytes($conf))
Write-Host "  [4/6] dashboard.conf -> $DashboardUrl"

# 5. NickelMenu config
$nmDir = Join-Path $KoboDrive ".adds\nm"
New-Item -ItemType Directory -Force -Path $nmDir | Out-Null
$nmCfg = @"
# NickelMenu config -- Shabbos Dashboard menu items
menu_item :main :Shabbos Dashboard :cmd_spawn :quiet:/bin/sh /mnt/onboard/.adds/dashboard/dashboard-loop.sh
menu_item :main :Refresh Dashboard :cmd_spawn :quiet:/bin/sh /mnt/onboard/.adds/dashboard/update-dashboard.sh
menu_item :main :Stop Dashboard :cmd_spawn :quiet:touch /mnt/onboard/.adds/dashboard/STOP
"@ -replace "`r`n","`n"
[IO.File]::WriteAllBytes((Join-Path $nmDir "dashboard"),
    [Text.Encoding]::UTF8.GetBytes($nmCfg))
Write-Host "  [5/6] NickelMenu config"

# 6. Library
$libSrc = Join-Path $root "library\output"
if (Test-Path $libSrc) {
    $libDst = Join-Path $KoboDrive "Library"
    New-Item -ItemType Directory -Force -Path $libDst | Out-Null
    $map = @{
        "tanakh"     = "01 Tanakh"
        "siddur"     = "02 Siddur"
        "shas_bavli" = "03 Shas Bavli"
    }
    foreach ($k in $map.Keys) {
        $catSrc = Join-Path $libSrc $k
        if (Test-Path $catSrc) {
            $catDst = Join-Path $libDst $map[$k]
            New-Item -ItemType Directory -Force -Path $catDst | Out-Null
            Copy-Item -Force (Join-Path $catSrc "*.epub") $catDst
        }
    }
    $count = (Get-ChildItem $libDst -Recurse -Filter *.epub).Count
    Write-Host "  [6/6] library: $count EPUBs in $libDst"
} else {
    Write-Host "  [6/6] SKIPPED — no library/output. Run library/download_library.py first."
}

Write-Host ""
Write-Host "Done. Safely eject the Kobo:"
Write-Host "  Open File Explorer -> right-click the Kobo drive -> Eject."
Write-Host "On disconnect the Kobo applies KoboRoot.tgz (NickelMenu install)."
Write-Host "Then connect to WiFi in Settings -> Wireless connection,"
Write-Host "and tap 'Shabbos Dashboard' in the main menu."
