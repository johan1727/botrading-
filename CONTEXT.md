# CONTEXT.md — GeminiTradingBot

## ¿Qué es este proyecto?
Bot de trading crypto automatizado que usa Gemini 2.5 Flash-Lite (Google AI,
gratis) como cerebro de decisión. Está construido como una estrategia custom
sobre Freqtrade v2026.4, el bot open source más popular de GitHub (49k+ stars).

Opera 24/7 en Railway.app (gratis), usa Binance como exchange, y notifica
cada trade por Telegram. Capital inicial: <$100 USD. Perfil: conservador.

## Arquitectura

```
Freqtrade Core (NO modificar)
    ├── Exchange Layer (CCXT → Binance)
    ├── Data Layer (OHLCV, indicators)
    ├── Risk Management (SL, TP, position sizing)
    ├── Persistence (SQLite)
    ├── Telegram Bot (built-in)
    └── WebUI (built-in)

user_data/ (AQUÍ trabajamos nosotros)
    ├── strategies/
    │   └── GeminiStrategy.py    ← Entry/exit signals via Gemini API
```

## Flujo de decisión cada 5 minutos

```
1. Freqtrade descarga velas 5m de Binance (automático)
2. GeminiStrategy.populate_indicators() → calcula RSI, EMA20, EMA50, volumen
3. GeminiStrategy.populate_entry_trend() → llama a Gemini API con contexto
4. Gemini responde: {accion, confianza, razon}
5. Si confianza >= 75 y accion == BUY → Freqtrade abre posición
6. GeminiStrategy.populate_exit_trend() → decide cuándo salir
7. Freqtrade ejecuta la orden en Binance + notifica por Telegram
```

## Selección dinámica de pares (cada 1 hora)

```
1. Freqtrade DynamicPairlist obtiene top 10 pares USDT por volumen 24h
2. GeminiStrategy.bot_loop_start() llama a Gemini para elegir el mejor par
3. Gemini analiza volatilidad + tendencia + volumen de cada par
4. Freqtrade actualiza la whitelist con el par elegido
5. El bot opera exclusivamente ese par hasta el próximo refresh
```

## Variables de entorno requeridas

| Variable | Descripción | Dónde obtenerla |
|---|---|---|
| GEMINI_API_KEY | API key de Google AI Studio | aistudio.google.com/apikey |
| BINANCE_API_KEY | API key de Binance | testnet.binance.vision (demo) |
| BINANCE_API_SECRET | Secret de Binance | testnet.binance.vision (demo) |
| TELEGRAM_TOKEN | Token del bot de Telegram | @BotFather en Telegram |
| TELEGRAM_CHAT_ID | Tu Chat ID de Telegram | @userinfobot en Telegram |
| MIN_CONFIDENCE | Confianza mínima (default 75) | Variable de entorno |

## Rate Limits importantes

| Servicio | Límite free tier | Impacto en el bot |
|---|---|---|
| Gemini 2.5 Flash-Lite | 15 RPM / 1,000 RPD | Bot hace ~12 calls/hora = OK |
| Binance Testnet | Sin límite práctico | OK |
| Binance Real | 1,200 requests/min | OK |
| Railway free tier | 500 horas/mes | ~20 días continuos |

## Troubleshooting

### Gemini devuelve error 429 (rate limit)
→ El bot hace fallback a HOLD automáticamente
→ Verifica que no haya otras apps usando la misma API key
→ Considera usar gemini-2.5-flash-lite (más requests por día)

### Freqtrade no abre trades en dry-run
→ Verifica que `dry_run: true` esté en config_dry_run.json
→ Revisa logs: `freqtrade trade --config config_dry_run.json --logfile logs/` 
→ El par debe estar en la whitelist activa

### Railway detiene el bot después de ~500 horas
→ Railway free tier tiene límite mensual
→ Solución: upgrade a $5/mes Developer plan o usar Render.com free tier
→ Alternativa: correr en PC local con ngrok para demos

### Binance Testnet se resetea periódicamente
→ Binance Testnet hace reset de balances ocasionalmente
→ Cuando pase: volver a crear API keys en testnet.binance.vision
→ No afecta al código, solo actualiza las keys en Railway

## Comandos Telegram disponibles (Freqtrade built-in)

```
/start          - Inicia el bot
/stop           - Detiene el bot
/status         - Estado de trades abiertos
/profit         - P&L total
/balance        - Balance actual
/trades         - Historial de trades
/performance    - Performance por par
/daily          - P&L por día
/reload_config  - Recarga configuración sin reiniciar
```

## Próximos pasos

- [ ] Obtener API keys (ver tabla en sección Variables de entorno)
- [ ] Crear `.env` local desde `.env.example`
- [ ] Probar localmente con docker-compose up
- [ ] Subir a GitHub
- [ ] Deploy en Railway con variables de entorno
- [ ] Verificar que llega mensaje de inicio en Telegram
- [ ] Correr dry-run 2-3 semanas antes de pasar a real
