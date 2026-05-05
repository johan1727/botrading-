# start_bot.ps1 — Arranca GeminiBot con 1 click
# Haz doble click en este archivo o ejecuta: powershell -ExecutionPolicy Bypass -File start_bot.ps1

$env:GEMINI_API_KEY    = "AIzaSyCbpd0NdDac1bARkb2L5bofijR3ejigaHw"
$env:GEMINI_MODEL      = "gemini-2.5-flash-lite-preview-06-17"
$env:MIN_CONFIDENCE    = "60"
$env:TELEGRAM_TOKEN    = "8298976121:AAEHcMysV_zX3msnkNu9CHGfLQn6_9FC0rw"
$env:TELEGRAM_CHAT_ID  = "6729779078"

Set-Location $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  GeminiBot v1.1.0 - KuCoin Dry-Run" -ForegroundColor Cyan
Write-Host "  Panel: http://localhost:8080" -ForegroundColor Yellow
Write-Host "  Usuario: admin  |  Password: geminibot2026" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

freqtrade trade --config config_dry_run.json --strategy GeminiStrategy --logfile user_data/logs/freqtrade.log
