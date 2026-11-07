<#
  Builds the standalone Windows app and installer for FiveQThoughts.

    1. Native host   native\windows  (WinForms + WebView2, .NET Framework 4.8)  -> build\app\FiveQThoughts.exe
    2. Backend       app.py + static (PyInstaller, bundled Python)            -> build\app\backend\
    3. Portable ZIP                                                          -> dist\FiveQThoughts-<ver>-win-x64-portable.zip
    4. Installer     Inno Setup 6                                             -> dist\FiveQThoughts-Setup-<ver>.exe

  Requirements (build machine only – end users need nothing):
    - .NET SDK 8+            (dotnet)
    - Python 3.9+            (python on PATH, or -Python <path>)
    - Inno Setup 6           (ISCC.exe; optional – without it only the portable ZIP is built)

  Usage:  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-SkipInstaller] [-Python C:\path\python.exe]
#>
param(
    [string]$Python = "python",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Build = Join-Path $Root "build"
$Dist = Join-Path $Root "dist"
$AppOut = Join-Path $Build "app"
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')" }
}

Write-Host "FiveQThoughts v$Version – Windows build" -ForegroundColor Green
if (Test-Path $AppOut) { Remove-Item $AppOut -Recurse -Force }
New-Item -ItemType Directory -Force -Path $AppOut, $Dist | Out-Null

# ---------------------------------------------------------------- 1. native host
Step "Native host (WebView2) bauen"
Invoke-Checked dotnet @("publish", (Join-Path $Root "native\windows\FiveQThoughts.csproj"),
    "-c", "Release", "-nologo", "-o", $AppOut, "-p:Version=$Version")
# Only x64 is shipped: drop unused loaders / WPF assembly
Remove-Item (Join-Path $AppOut "runtimes") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $AppOut "Microsoft.Web.WebView2.Wpf.dll") -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- 2. backend
Step "Python-Backend mit PyInstaller bündeln"
$Venv = Join-Path $Build ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Invoke-Checked $Python @("-m", "venv", $Venv)
}
Invoke-Checked $VenvPy @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "pyinstaller")

$PyWork = Join-Path $Build "pyinstaller"
Invoke-Checked $VenvPy @("-m", "PyInstaller", (Join-Path $Root "app.py"),
    "--name", "FiveQThoughts-backend",
    "--onedir", "--console", "--noconfirm", "--clean", "--log-level", "WARN",
    "--icon", (Join-Path $Root "native\windows\FiveQThoughts.ico"),
    "--add-data", "$(Join-Path $Root 'static');static",
    "--add-data", "$(Join-Path $Root 'VERSION');.",
    "--distpath", $PyWork, "--workpath", (Join-Path $PyWork "work"), "--specpath", $PyWork)
Copy-Item (Join-Path $PyWork "FiveQThoughts-backend") (Join-Path $AppOut "backend") -Recurse

Copy-Item (Join-Path $Root "README.md") $AppOut
Copy-Item (Join-Path $Root "VERSION") $AppOut

# ---------------------------------------------------------------- 3. portable zip
Step "Portable ZIP erstellen"
$Zip = Join-Path $Dist "FiveQThoughts-$Version-win-x64-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $AppOut "*") -DestinationPath $Zip
Write-Host "  $Zip"

# ---------------------------------------------------------------- 4. installer
if ($SkipInstaller) { Write-Host "`nInstaller übersprungen."; exit 0 }
Step "Installer mit Inno Setup bauen"
$Iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Iscc) {
    Write-Warning "Inno Setup 6 (ISCC.exe) nicht gefunden – nur die portable ZIP wurde erstellt. Download: https://jrsoftware.org/isdl.php"
    exit 0
}
Invoke-Checked $Iscc @("/Q", "/DAppVersion=$Version", "/DSourceDir=$AppOut", "/DOutputDir=$Dist",
    "/DIconFile=$(Join-Path $Root 'native\windows\FiveQThoughts.ico')",
    (Join-Path $PSScriptRoot "FiveQThoughts.iss"))
Write-Host "  $(Join-Path $Dist "FiveQThoughts-Setup-$Version.exe")"
Write-Host "`nFertig." -ForegroundColor Green
