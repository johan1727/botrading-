# start_bot.example.ps1 — Plantilla para arrancar GeminiBot (dry-run)
# INSTRUCCIONES:
#   1. Copia este archivo a start_bot.ps1 (está en .gitignore)
#   2. Rellena las variables con tus API keys reales
#   3. Ejecuta: powershell -ExecutionPolicy Bypass -File start_bot.ps1

# ── Groq (gratis en console.groq.com) ─────────────────────────────────────────
$env:GROQ_KEY_1       = ""   # pegar key de cuenta Groq 1
$env:GROQ_KEY_2       = ""   # pegar key de cuenta Groq 2
$env:GROQ_KEY_3       = ""   # pegar key de cuenta Groq 3 (opcional)
$env:GROQ_KEY_4       = ""   # pegar key de cuenta Groq 4 (opcional)

# ── Gemini (gratis en aistudio.google.com/apikey) ─────────────────────────────
$env:GEMINI_API_KEY   = ""   # pegar API key de Google AI Studio
$env:GEMINI_MODEL     = "gemini-2.5-flash-lite-preview-06-17"

# ── Telegram (crear bot con @BotFather en Telegram) ───────────────────────────
$env:TELEGRAM_TOKEN   = ""   # token del bot ej: 123456789:AAExxxxxxxx
$env:TELEGRAM_CHAT_ID = ""   # tu chat_id (obtener con @userinfobot)

# ── KuCoin (crear API en kucoin.com → My Account → API Management) ────────────
$env:KUCOIN_KEY       = ""   # API Key
$env:KUCOIN_SECRET    = ""   # API Secret
$env:KUCOIN_PASSWORD  = ""   # API Passphrase

# ── Config del bot ─────────────────────────────────────────────────────────────
$env:MIN_CONFIDENCE   = "65"

Set-Location $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  GeminiBot - Dry Run" -ForegroundColor Cyan
Write-Host "  Panel: http://localhost:8080" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

freqtrade trade --config config_dry_run.json --strategy GeminiStrategy --logfile user_data/logs/freqtrade.log
