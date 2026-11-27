# Build the Windows desktop executable from Python 3.12+ with Tk support.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $root ".venv-desktop"
$python = Join-Path $venv "Scripts\python.exe"
$icon = Join-Path $root "assets\xino-prism.ico"
$entrypoint = Join-Path $root "xino_prism_desktop.py"
if (-not (Test-Path $python)) {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.12 -m venv $venv
    } else {
        & python -m venv $venv
    }
}
if (-not (Test-Path $icon)) { throw "Logo icon not found: $icon" }
& $python -m pip install --upgrade pip
& $python -m pip install -e ".[desktop]"
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name XinoPrism --icon $icon --paths $root $entrypoint
Write-Host "Built $(Join-Path $root 'dist\XinoPrism.exe')"
