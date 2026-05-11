@echo off
chcp 65001 >nul
echo 🤖 GeminiBot - Panel de Trading Manual
echo ======================================
echo.
echo Abriendo panel en tu navegador...
echo.
start "" "user_data\manual_trading.html"
echo ✅ Panel abierto!
echo.
echo Si no se abre automaticamente, abre este archivo en tu navegador:
echo %CD%\user_data\manual_trading.html
echo.
echo 📝 Datos de acceso:
echo    URL: http://localhost:8080
echo    Usuario: admin
echo    Password: (ver variable FREQTRADE_API_PASSWORD en tu .env)
echo.
pause
