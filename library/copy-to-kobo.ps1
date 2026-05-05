<#
Copies generated EPUBs to a connected Kobo, organized into category folders.
Run after `python download_library.py all`.
#>
param(
    [string]$KoboDrive,
    [string]$Subfolder = "Library"
)

$ErrorActionPreference = "Stop"

if (-not $KoboDrive) {
    $KoboDrive = (Get-Volume | Where-Object {
        $_.DriveLetter -and $_.DriveType -eq "Removable" -and
        (Test-Path "$($_.DriveLetter):\.kobo")
    } | Select-Object -First 1).DriveLetter
    if (-not $KoboDrive) {
        Write-Error "Kobo not detected. Plug in & accept USB connection, or pass -KoboDrive F:"
        exit 1
    }
    $KoboDrive = "${KoboDrive}:\"
} elseif (-not $KoboDrive.EndsWith("\")) {
    $KoboDrive += "\"
}

$src = Join-Path $PSScriptRoot "output"
if (-not (Test-Path $src)) {
    Write-Error "No output found at $src. Run download_library.py first."
    exit 1
}

$dst = Join-Path $KoboDrive $Subfolder
New-Item -ItemType Directory -Force -Path $dst | Out-Null

Get-ChildItem -Path $src -Directory | ForEach-Object {
    $catName = $_.Name
    $pretty = switch ($catName) {
        "tanakh"     { "01 Tanakh" }
        "siddur"     { "02 Siddur" }
        "shas_bavli" { "03 Shas Bavli" }
        default      { $catName }
    }
    $catDst = Join-Path $dst $pretty
    New-Item -ItemType Directory -Force -Path $catDst | Out-Null
    Get-ChildItem $_.FullName -Filter *.epub | ForEach-Object {
        Write-Host "  $catName / $($_.Name)"
        Copy-Item -Force $_.FullName $catDst
    }
}

Write-Host ""
Write-Host "Done. Eject the Kobo. Files appear under your library on the device."
Write-Host "Organized as: $dst"
