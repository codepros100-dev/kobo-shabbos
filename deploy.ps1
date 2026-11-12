<#
Installs everything onto the Kobo (plugged in, "Connect" tapped, shows up as a drive).

  .adds\shabbos\   Shabbos display: script, binaries, offline pages
  .adds\koreader\  KOReader (the Hebrew-capable reader) + fonts + defaults
  .adds\sefarim\   The Hebrew library (hidden from the stock reader on purpose)
  .adds\nm\shabbos NickelMenu entries for both

Prerequisites already on the device: NickelMenu, and (optional) Kobostuff for curl.
Re-run any time; it only replaces this project's own files.

  .\deploy.ps1               everything
  .\deploy.ps1 -Skip library,koreader
  .\deploy.ps1 -KeepAwake    display never sleeps, Wi-Fi stays on (testing over telnet)
#>
param(
    [string[]]$Skip = @(),
    [switch]$KeepAwake
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dl = Join-Path $root '_downloads'

$kobo = (Get-Volume | Where-Object FileSystemLabel -eq 'KOBOeReader' | Select-Object -First 1).DriveLetter
if (-not $kobo) { throw 'Kobo not found. Plug it in and tap Connect.' }
$K = "${kobo}:"
Write-Host "Kobo at $K"

function Write-LF([string]$src, [string]$dst) {
    $text = [IO.File]::ReadAllText($src) -replace "`r`n", "`n"
    [IO.File]::WriteAllText($dst, $text, [Text.UTF8Encoding]::new($false))
}
function Mirror([string]$src, [string]$dst) {
    robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $src -> $dst" }
}

# --- Shabbos display ---------------------------------------------------------
if ('display' -notin $Skip) {
    Write-Host 'Shabbos display...'
    $dst = "$K\.adds\shabbos"
    New-Item -ItemType Directory -Force "$dst\bin" | Out-Null
    Write-LF "$root\device\shabbos\shabbos.sh" "$dst\shabbos.sh"
    Copy-Item "$root\device\shabbos\exit.png" $dst -Force
    $trmnl = "$dl\trmnl-extracted\src\TRMNL\bin"
    Copy-Item "$trmnl\fbink\fbink", "$trmnl\fbink\fbdepth", "$trmnl\busybox_kobo" "$dst\bin" -Force
    if (-not (Test-Path "$root\build\pages")) {
        python "$root\generator\generate_dashboard.py" pack --out-dir "$root\build\pages" --days 400
    }
    Mirror "$root\build\pages" "$dst\pages"
    if ($KeepAwake) { Set-Content "$dst\DEBUG" 'remove this file for normal (sleeping) operation' }
    else { Remove-Item "$dst\DEBUG" -ErrorAction SilentlyContinue }
}

# --- KOReader ----------------------------------------------------------------
if ('koreader' -notin $Skip) {
    Write-Host 'KOReader...'
    $zip = Get-ChildItem "$dl\koreader-kobo-v*.zip" | Sort-Object Name | Select-Object -Last 1
    if (-not $zip) { throw "No KOReader zip in $dl" }
    $stage = "$root\build\koreader-stage"
    if (-not (Test-Path "$stage\koreader\koreader.sh")) {
        Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force $stage | Out-Null
        tar -xf $zip.FullName -C $stage
    }
    # /E not /MIR: never delete the reader's own settings, history or bookmarks.
    robocopy "$stage\koreader" "$K\.adds\koreader" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw 'robocopy failed: koreader' }

    $fonts = "$K\.adds\koreader\fonts\hebrew"
    New-Item -ItemType Directory -Force $fonts | Out-Null
    $fstage = "$root\build\fonts"
    if (-not (Test-Path "$fstage\TaameyFrankCLM-Medium.ttf")) {
        New-Item -ItemType Directory -Force $fstage | Out-Null
        foreach ($z in 'TaameyFrankCLM.zip', 'EzraSIL.zip') {
            $tmp = "$fstage\_$z"; Expand-Archive "$dl\fonts\$z" $tmp -Force
            Get-ChildItem $tmp -Recurse -Filter *.ttf | Copy-Item -Destination $fstage -Force
            Remove-Item $tmp -Recurse -Force
        }
        Copy-Item "$dl\fonts\FrankRuhlLibre.ttf" $fstage -Force
    }
    Copy-Item "$fstage\*.ttf" $fonts -Force

    # First-run defaults only; never overwrite the user's own settings.
    $settings = "$K\.adds\koreader\settings.reader.lua"
    if (-not (Test-Path $settings)) {
        Write-LF "$root\device\koreader\settings.reader.lua" $settings
    }
}

# --- Library -----------------------------------------------------------------
if ('library' -notin $Skip) {
    Write-Host 'Library...'
    if (-not (Test-Path "$root\library\output")) { python "$root\library\download_library.py" all }
    Mirror "$root\library\output" "$K\.adds\sefarim"
}

# --- NickelMenu + cleanup of the retired setups --------------------------------
New-Item -ItemType Directory -Force "$K\.adds\nm" | Out-Null
Write-LF "$root\device\nm\shabbos" "$K\.adds\nm\shabbos"
foreach ($old in "$K\.adds\nm\trmnl", "$K\.adds\nm\dashboard", "$K\.adds\TRMNL", "$K\.adds\dashboard",
                 "$K\Library\01 Tanakh", "$K\Library\02 Siddur", "$K\Library\03 Shas Bavli",
                 "$K\fonts\NotoSansHebrew-Regular.ttf", "$K\fonts\NotoSansHebrew-Bold.ttf") {
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force; Write-Host "  removed old $old" }
}
foreach ($dir in "$K\Library", "$K\fonts") {
    if ((Test-Path $dir) -and -not (Get-ChildItem $dir -Force)) { Remove-Item $dir }
}

Write-Host 'Done. Eject the Kobo; the menu (bottom right of the home screen) has both entries.'

# robocopy leaves a non-zero "files copied" code behind; that is success.
exit 0
