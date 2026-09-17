#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "Установка зависимостей Python..."
python -m pip install -r requirements.txt

if (-not (Get-Command ffplay -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg не найден. Пробую установить через winget..."
    winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

if (Get-Command ffplay -ErrorAction SilentlyContinue) {
    Write-Host "ffplay: $(Get-Command ffplay | Select-Object -ExpandProperty Source)"
} else {
    Write-Host "Внимание: ffplay всё ещё не в PATH. Перезагрузите ПК или добавьте FFmpeg в PATH вручную." -ForegroundColor Yellow
}

$startup = Read-Host "Добавить автозапуск при входе в Windows? (y/N)"
if ($startup -match '^[yY]') {
    $bat = Join-Path $Root "run.vbs"
    $lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\VideoHoverPreview.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($lnk)
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$(Join-Path $Root 'run.vbs')`""
    $shortcut.WorkingDirectory = $Root
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Video hover preview in Explorer"
    $shortcut.Save()
    Write-Host "Автозапуск: $lnk"
}

Write-Host ""
Write-Host "Готово. Запуск: $Root\run.bat"
Write-Host "Настройки: $env:USERPROFILE\.video-hover-preview\config.json"
