# autostart_windows.ps1 — Configura el bot para arrancar automaticamente con Windows
# Ejecutar UNA SOLA VEZ como administrador

$botPath = "D:\TODO\botrading\start_bot.ps1"
$taskName = "GeminiTradingBot"

# Eliminar tarea anterior si existe
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Crear la accion: ejecutar start_bot.ps1
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Minimized -File `"$botPath`""

# Disparador: al iniciar sesion
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Configuracion: correr aunque no haya red inmediatamente, reintentar si falla
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

# Registrar la tarea
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "========================================" -ForegroundColor Green
Write-Host "  GeminiBot configurado para arrancar" -ForegroundColor Green
Write-Host "  automaticamente al iniciar Windows!" -ForegroundColor Green
Write-Host "  Tarea: $taskName" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Green
