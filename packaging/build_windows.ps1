param(
  [ValidateSet("cpu", "cuda")]
  [string]$Variant = "cpu",
  [ValidateSet("full", "minimal")]
  [string]$LicenseProfile = "full"
)

$ErrorActionPreference = "Stop"

# Build script for Windows:
# - Creates/uses a variant-specific venv (.venv-cpu / .venv-cuda)
# - Builds a PyInstaller onedir bundle into dist/draft2craift
# - Supports build profiles:
#     full     = all features, AGPL-3.0 distribution (default)
#                bundles pymupdf4llm (AGPL), html2text (GPL)
#     minimal  = reduced extras: no AGPL/GPL import stack, no Speech/NLI add-ons
#                suitable if downstream consumers require a non-copyleft binary
# - Produces variant/profile-labeled artifacts: portable ZIP + optional installer

$variantUpper = $Variant.ToUpperInvariant()
$profileUpper = $LicenseProfile.ToUpperInvariant()
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$venvPath = ".venv-$Variant"
if (-not (Test-Path $venvPath)) {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3.11 -m venv $venvPath
  } else {
    python -m venv $venvPath
  }
}

& (Join-Path $repoRoot "$venvPath\Scripts\Activate.ps1")

python -m pip install -U pip
python -m pip install -U pyinstaller

$coreReq = Join-Path $repoRoot "requirements-core.txt"
if (-not (Test-Path $coreReq)) {
  $coreReq = Join-Path $repoRoot "requirements.txt"
}

$tmpReq = Join-Path ([System.IO.Path]::GetTempPath()) "draft2craift-requirements-no-llama.txt"
Get-Content $coreReq |
  Where-Object { $_ -notmatch "^\s*llama-cpp-python" } |
  Set-Content -Path $tmpReq -Encoding UTF8
python -m pip install -r $tmpReq
Remove-Item -Force $tmpReq -ErrorAction SilentlyContinue

Write-Host "Using build profile: $LicenseProfile"
$optionalReq = Join-Path $repoRoot "packaging\requirements-optional-$LicenseProfile.txt"
if (Test-Path $optionalReq) {
  python -m pip install -r $optionalReq
} else {
  Write-Host "Optional requirements file not found: $optionalReq"
}

if ($LicenseProfile -eq "minimal") {
  # Defensive cleanup: ensure no AGPL/GPL packages are in the venv
  $blocked = @("pymupdf", "pymupdf4llm", "html2text")
  foreach ($pkg in $blocked) {
    python -m pip uninstall -y $pkg | Out-Null
  }
}

if ($Variant -eq "cuda") {
  $env:CMAKE_ARGS = "-DGGML_CUDA=on"
  python -m pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python
  Remove-Item Env:CMAKE_ARGS -ErrorAction SilentlyContinue
} else {
  python -m pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python
}

$pyiArgs = @("--noconfirm", "--clean")
if ($LicenseProfile -eq "minimal") {
  $pyiArgs += @(
    "--exclude-module=fitz",
    "--exclude-module=pymupdf",
    "--exclude-module=pymupdf4llm",
    "--exclude-module=html2text"
  )
}
$pyiArgs += "packaging\draft2craift.spec"
& pyinstaller @pyiArgs
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$distDir = Join-Path $repoRoot "dist\draft2craift"
if (-not (Test-Path $distDir)) {
  throw "PyInstaller output not found: $distDir"
}

$portableOutDir = Join-Path $repoRoot "dist_portable"
New-Item -ItemType Directory -Force -Path $portableOutDir | Out-Null
$zipPath = Join-Path $portableOutDir "draft2craift-$profileUpper-Portable-$variantUpper.zip"
if (Test-Path $zipPath) {
  Remove-Item -Force $zipPath
}
Compress-Archive -Path $distDir -DestinationPath $zipPath -Force
Write-Host "Portable ZIP built at $zipPath"

if (Get-Command iscc -ErrorAction SilentlyContinue) {
  iscc "/DMyOutputBaseFilename=draft2craift-$profileUpper-Setup-$variantUpper" packaging\installer.iss
  Write-Host "Installer built in dist_installer\ as draft2craift-$profileUpper-Setup-$variantUpper.exe"
} else {
  Write-Host "Inno Setup compiler (iscc) not found on PATH; skipping installer build."
}
