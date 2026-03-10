param(
  [ValidateSet("full", "minimal")]
  [string]$LicenseProfile = "full"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildScript = Join-Path $scriptDir "build_windows.ps1"
$profileUpper = $LicenseProfile.ToUpperInvariant()

Write-Host "Building CPU variant..."
& $buildScript -Variant cpu -LicenseProfile $LicenseProfile

Write-Host "Building CUDA variant..."
& $buildScript -Variant cuda -LicenseProfile $LicenseProfile

Write-Host "Done. Artifacts:"
Write-Host "  dist_portable\draft2craift-$profileUpper-Portable-CPU.zip"
Write-Host "  dist_portable\draft2craift-$profileUpper-Portable-CUDA.zip"
Write-Host "  dist_installer\draft2craift-$profileUpper-Setup-CPU.exe (if iscc available)"
Write-Host "  dist_installer\draft2craift-$profileUpper-Setup-CUDA.exe (if iscc available)"
