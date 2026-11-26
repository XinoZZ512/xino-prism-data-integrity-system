# Build the Windows desktop executable from Python 3.12+ with Tk support.
$ErrorActionPreference = "Stop"
$venv = Join-Path (Get-Location) ".venv-desktop"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.12 -m venv $venv
    } else {
        & python -m venv $venv
    }
}
& $python -m pip install --upgrade pip
& $python -m pip install -e ".[desktop]"
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name XinoPrism --paths . xino_prism_desktop.py
Write-Host "Built dist\XinoPrism.exe"
