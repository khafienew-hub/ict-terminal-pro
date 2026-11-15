# =====================================================================
# ICT TERMINAL PRO - TERMINAL ONE-CLICK INSTALLER (POWERSHELL)
# =====================================================================
param(
    [string]$Repo = "khafienew-hub/ict-terminal-pro",
    [string]$Version = "2.0.4",
    [string]$InstallDir = "$HOME\ICT-Terminal-Pro"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   ICT TERMINAL PRO v$Version - CLI INSTALLER" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan

$zipUrl = "https://github.com/$Repo/releases/download/v$Version/ICT-Terminal-Pro-$Version-native-win64.zip"
$zipPath = "$env:TEMP\ICT-Terminal-Pro-$Version-native-win64.zip"

Write-Host "[1/3] Mengunduh paket aplikasi dari GitHub..." -ForegroundColor Yellow
Write-Host "      URL: $zipUrl" -ForegroundColor DarkGray

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    Write-Host "      Download selesai!" -ForegroundColor Green
} catch {
    Write-Host "      [Gagal Unduh]: Pastikan link release GitHub sudah aktif!" -ForegroundColor Red
    Write-Host "      Info: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "[2/3] Mengekstrak file ke $InstallDir..." -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force

Write-Host "[3/3] Melepas blokir proteksi Windows (Unblock-File)..." -ForegroundColor Yellow
Get-ChildItem -Path $InstallDir -Recurse | Unblock-File

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   INSTALASI SELESAI!" -ForegroundColor Green
Write-Host "   Folder: $InstallDir" -ForegroundColor White
Write-Host "   Untuk menjalankan:" -ForegroundColor Yellow
Write-Host "   1. Buka MetaTrader 5 Anda" -ForegroundColor White
Write-Host "   2. Klik ganda: $InstallDir\Buka_Aplikasi.bat" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Cyan
