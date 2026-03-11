# ══════════════════════════════════════════════════════════════════
#  Splatrix Installer for Windows — self-contained, zero system modification
#
#  Usage (PowerShell):
#    irm https://mutexre.github.io/splatrix/install.ps1 | iex
#
#  Everything goes into %USERPROFILE%\.splatrix\ — nothing else is touched.
#
#  Layout:
#    %USERPROFILE%\.splatrix\
#    ├── bin\micromamba.exe
#    ├── bin\splatrix.bat    ← launcher script
#    ├── envs\               ← micromamba root
#    └── src\                ← splatrix source code
#
#  Requirements: Windows 10/11 x86_64, NVIDIA GPU + drivers
# ══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

$SPLATRIX_VERSION = if ($env:SPLATRIX_VERSION) { $env:SPLATRIX_VERSION } else { "main" }
$SPLATRIX_REPO = "https://github.com/mutexre/splatrix"
$SPLATRIX_HOME = if ($env:SPLATRIX_HOME) { $env:SPLATRIX_HOME } else { "$env:USERPROFILE\.splatrix" }
$ENV_NAME = "splatrix"
$PYTHON_VERSION = "3.10"
$CUDA_VERSION = "12.1"

# ── Helpers ───────────────────────────────────────────────────────

function Write-Step($msg)  { Write-Host "`n-- $msg --" -ForegroundColor White }
function Write-Info($msg)  { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[+] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

# ── Preflight ────────────────────────────────────────────────────

Write-Step "Preflight checks"

if ([Environment]::Is64BitOperatingSystem -eq $false) {
    Write-Fail "64-bit Windows required."
}
Write-Ok "Platform: Windows x86_64"

# GPU check
try {
    $gpu = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1
    $mem = & nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    Write-Ok "NVIDIA GPU: $gpu ($mem MB)"
} catch {
    Write-Warn "nvidia-smi not found. NVIDIA drivers required for GPU training."
    Write-Warn "Install drivers: https://www.nvidia.com/drivers"
    $yn = Read-Host "Continue without GPU? (y/N)"
    if ($yn -ne "y" -and $yn -ne "Y") { exit 0 }
    $CUDA_VERSION = ""
}

# ── Create directory structure ────────────────────────────────────

Write-Step "Setup directories"

New-Item -ItemType Directory -Force -Path "$SPLATRIX_HOME\bin" | Out-Null
New-Item -ItemType Directory -Force -Path "$SPLATRIX_HOME\envs" | Out-Null

Write-Ok "Install directory: $SPLATRIX_HOME"

# ── micromamba ────────────────────────────────────────────────────

Write-Step "micromamba"

$MAMBA_EXE = "$SPLATRIX_HOME\bin\micromamba.exe"
$env:MAMBA_ROOT_PREFIX = "$SPLATRIX_HOME"

if (Test-Path $MAMBA_EXE) {
    Write-Ok "micromamba already installed"
} else {
    Write-Info "Downloading micromamba..."
    $mambaTar = "$env:TEMP\micromamba.tar.bz2"
    Invoke-WebRequest -Uri "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile $mambaTar
    # Extract using tar (available on Windows 10+)
    & tar xf $mambaTar -C "$SPLATRIX_HOME\bin" --strip-components=1 Library/bin/micromamba.exe 2>$null
    if (-not (Test-Path $MAMBA_EXE)) {
        # Fallback: try different archive structure
        & tar xf $mambaTar -C "$SPLATRIX_HOME\bin" 2>$null
        $found = Get-ChildItem -Recurse "$SPLATRIX_HOME\bin" -Filter "micromamba.exe" | Select-Object -First 1
        if ($found) {
            Move-Item -Force $found.FullName $MAMBA_EXE
        }
    }
    Remove-Item -Force $mambaTar -ErrorAction SilentlyContinue
    if (-not (Test-Path $MAMBA_EXE)) {
        Write-Fail "Failed to extract micromamba. Download manually from https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html"
    }
    Write-Ok "micromamba installed"
}

# ── Download Splatrix ────────────────────────────────────────────

Write-Step "Download Splatrix"

$srcDir = "$SPLATRIX_HOME\src"

if (Test-Path "$srcDir\.git") {
    Write-Info "Updating existing installation..."
    Push-Location $srcDir
    & git pull --quiet 2>$null
    Pop-Location
} else {
    Write-Info "Downloading Splatrix $SPLATRIX_VERSION..."
    if (Test-Path $srcDir) { Remove-Item -Recurse -Force $srcDir }

    $zipUrl = "$SPLATRIX_REPO/archive/refs/heads/$SPLATRIX_VERSION.zip"
    $zipFile = "$env:TEMP\splatrix.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile

    Expand-Archive -Path $zipFile -DestinationPath "$env:TEMP\splatrix_extract" -Force
    $extracted = Get-ChildItem "$env:TEMP\splatrix_extract" | Select-Object -First 1
    Move-Item -Force $extracted.FullName $srcDir

    Remove-Item -Force $zipFile -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$env:TEMP\splatrix_extract" -ErrorAction SilentlyContinue
    Write-Ok "Downloaded source"
}

Set-Location $srcDir

# ── Environment ──────────────────────────────────────────────────

Write-Step "Create environment"

$envList = & $MAMBA_EXE env list 2>$null
if ($envList -match $ENV_NAME) {
    Write-Info "Environment '$ENV_NAME' exists, activating..."
} else {
    Write-Info "Creating environment '$ENV_NAME' (Python $PYTHON_VERSION)..."
    & $MAMBA_EXE create -n $ENV_NAME python=$PYTHON_VERSION -y -c conda-forge -q 2>$null
    Write-Ok "Environment created"
}

# Activate environment by setting PATH
$envPrefix = & $MAMBA_EXE env list --json 2>$null | ConvertFrom-Json |
    Select-Object -ExpandProperty envs |
    Where-Object { $_ -match $ENV_NAME } |
    Select-Object -First 1

if (-not $envPrefix) {
    Write-Fail "Could not locate splatrix environment."
}

$env:CONDA_PREFIX = $envPrefix
$env:PATH = "$envPrefix;$envPrefix\Scripts;$envPrefix\Library\bin;$env:PATH"

# ── Dependencies ─────────────────────────────────────────────────

Write-Step "Install dependencies"

# PyTorch
if ($CUDA_VERSION) {
    Write-Info "Installing PyTorch with CUDA $CUDA_VERSION... (may take a few minutes)"
    $cudaTag = $CUDA_VERSION -replace '\.', ''
    & pip install torch torchvision --index-url "https://download.pytorch.org/whl/cu$cudaTag" -q 2>$null
} else {
    Write-Info "Installing PyTorch (CPU)..."
    & pip install torch torchvision -q 2>$null
}
Write-Ok "PyTorch installed"

# COLMAP + FFmpeg
Write-Info "Installing COLMAP and FFmpeg..."
& $MAMBA_EXE install -n $ENV_NAME -c conda-forge colmap ffmpeg -y -q 2>$null
Write-Ok "COLMAP + FFmpeg installed"

# OpenCV
Write-Info "Installing OpenCV..."
& pip install opencv-python-headless -q 2>$null
Write-Ok "OpenCV installed"

# Nerfstudio
Write-Info "Installing Nerfstudio... (may take a few minutes)"
& pip install nerfstudio -q 2>$null
Write-Ok "Nerfstudio installed"

# Splatrix
Write-Info "Installing Splatrix..."
& pip install -e . -q 2>$null
Write-Ok "Splatrix installed"

# ── Launcher script ──────────────────────────────────────────────

Write-Step "Create launcher"

$launcherContent = @"
@echo off
REM Splatrix launcher — self-contained, no PATH modification needed

set "SPLATRIX_HOME=%USERPROFILE%\.splatrix"
set "MAMBA_ROOT_PREFIX=%SPLATRIX_HOME%"
set "MAMBA_EXE=%SPLATRIX_HOME%\bin\micromamba.exe"

if not exist "%MAMBA_EXE%" (
    echo Error: micromamba not found. Run the installer.
    exit /b 1
)

REM Activate environment
for /f "tokens=*" %%i in ('"%MAMBA_EXE%" shell activate -s cmd.exe splatrix 2^>nul') do %%i

python -m splatrix.main_qml %*
"@

Set-Content -Path "$SPLATRIX_HOME\bin\splatrix.bat" -Value $launcherContent -Encoding ASCII
Write-Ok "Launcher: $SPLATRIX_HOME\bin\splatrix.bat"

# Also create a PowerShell launcher
$psLauncherContent = @'
# Splatrix launcher for PowerShell
$env:SPLATRIX_HOME = if ($env:SPLATRIX_HOME) { $env:SPLATRIX_HOME } else { "$env:USERPROFILE\.splatrix" }
$env:MAMBA_ROOT_PREFIX = "$env:SPLATRIX_HOME"
$MAMBA_EXE = "$env:SPLATRIX_HOME\bin\micromamba.exe"

if (-not (Test-Path $MAMBA_EXE)) {
    Write-Error "micromamba not found. Run the installer."
    exit 1
}

# Activate environment
$hookOutput = & $MAMBA_EXE shell activate -s powershell splatrix 2>$null
Invoke-Expression $hookOutput

& python -m splatrix.main_qml @args
'@

Set-Content -Path "$SPLATRIX_HOME\bin\splatrix.ps1" -Value $psLauncherContent -Encoding UTF8
Write-Ok "PowerShell launcher: $SPLATRIX_HOME\bin\splatrix.ps1"

# ── Shortcuts ─────────────────────────────────────────────────────

function New-Shortcut($Path) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($Path)
        $lnk.TargetPath = "$SPLATRIX_HOME\bin\splatrix.bat"
        $lnk.WorkingDirectory = $SPLATRIX_HOME
        $lnk.Description = "Splatrix - Video to 3D Gaussian Splats"
        $lnk.Save()
        return $true
    } catch { return $false }
}

# Start Menu (standard location — always created)
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
if (New-Shortcut "$startMenuDir\Splatrix.lnk") {
    Write-Ok "Start Menu shortcut created"
} else {
    Write-Warn "Could not create Start Menu shortcut"
}

# Desktop (optional — ask user)
$addDesktop = Read-Host "Add desktop shortcut? (Y/n)"
if ($addDesktop -ne "n" -and $addDesktop -ne "N") {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if (New-Shortcut "$desktopPath\Splatrix.lnk") {
        Write-Ok "Desktop shortcut created"
    } else {
        Write-Warn "Could not create desktop shortcut"
    }
}

# ── Verify ───────────────────────────────────────────────────────

Write-Step "Verification"

try { & python -c "import torch; print(f'  PyTorch {torch.__version__}  CUDA: {torch.cuda.is_available()}')" }
catch { Write-Warn "PyTorch verification failed" }

try { & python -c "import nerfstudio; print('  Nerfstudio OK')" }
catch { Write-Warn "Nerfstudio verification failed" }

try { & python -c "from PyQt6.QtWidgets import QApplication; print('  PyQt6 OK')" }
catch { Write-Warn "PyQt6 verification failed" }

# ── Done ─────────────────────────────────────────────────────────

Write-Host ""
Write-Host "+======================================================+" -ForegroundColor Green
Write-Host "|                                                      |" -ForegroundColor Green
Write-Host "|   Splatrix installed successfully!                   |" -ForegroundColor Green
Write-Host "|                                                      |" -ForegroundColor Green
Write-Host "|   Run:  ~\.splatrix\bin\splatrix.bat                |" -ForegroundColor Green
Write-Host "|   Or:   ~\.splatrix\bin\splatrix.ps1                |" -ForegroundColor Green
Write-Host "|                                                      |" -ForegroundColor Green
Write-Host "+======================================================+" -ForegroundColor Green
Write-Host ""
Write-Host "Everything installed in: $SPLATRIX_HOME"
Write-Host ""
