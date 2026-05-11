@echo off
chcp 65001 >nul
color 0A
echo.
echo  ╔═══════════════════════════════════════════════════════════╗
echo  ║              🤖 GEMINIBOT - PANEL MANUAL                   ║
echo  ╚═══════════════════════════════════════════════════════════╝
echo.
echo  Iniciando servidor del panel...
echo.
echo  📊 Conectando con Freqtrade en localhost:8080
echo  🌐 Tu panel estara en: http://localhost:8090
echo.
echo  ⚠️  NO CIERRES esta ventana mientras uses el panel
echo.
echo  Abriendo navegador automaticamente...
echo.
timeout /t 2 /nobreak >nul
start http://localhost:8090
python iniciar_panel.py
