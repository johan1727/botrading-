# MEMORY.md — GeminiTradingBot
# Historial de decisiones técnicas y cambios importantes
# Actualizar cada vez que se modifique algo significativo

---

## v1.0.0 — Creación inicial (3 Mayo 2026)

### Decisiones de arquitectura

**¿Por qué Freqtrade como base?**
- Bot más popular de GitHub (49.7k stars, v2026.4)
- Ya tiene: backtesting, dry-run, Telegram, WebUI, risk management, SQLite
- Nos evita construir toda esa infraestructura desde cero
- Estrategia custom permite inyectar lógica de IA directamente

**¿Por qué Gemini 2.5 Flash-Lite y no Flash o Pro?**
- Flash-Lite: 15 RPM / 1,000 RPD gratis → suficiente para bot de 5 minutos
- Flash: solo 10 RPM / 250 RPD → muy restrictivo para uso continuo
- Pro: solo 5 RPM / 100 RPD → insuficiente para producción
- Flash-Lite tiene buen balance calidad/velocidad para decisiones de trading

**¿Por qué velas de 5 minutos y no 1 minuto?**
- Perfil conservador: menos ruido, señales más limpias
- 1m = demasiadas llamadas a Gemini (riesgo de hit rate limit)
- 5m = ~12 llamadas/hora, dentro del límite de Flash-Lite
- Menos comisiones al operar menos frecuentemente

**¿Por qué Railway.app?**
- Free tier soporta workers de Python (Freqtrade corre como worker)
- Deploy desde GitHub en un click
- Variables de entorno en la UI (seguro para API keys)
- Alternativa: Render.com si Railway se queda sin horas

**¿Por qué Binance Testnet para demo?**
- Balance gratuito de $10,000 USDT para probar
- API idéntica a Binance real (mismo código, diferente endpoint)
- Solo cambiar BINANCE_TESTNET=true/false para switchear

**¿Por qué estrategia standalone sin FreqAI?**
- Mega-prompt ya implementa llamadas Gemini dentro de GeminiStrategy.py
- Añadir GeminiModel.py/FreqAI duplicaría lógica y aumentaría complejidad
- FreqAI obliga a simular entrenamiento ML que no aporta valor al MVP
- Standalone es más simple, más robusto y menos puntos de fallo

### Fixes aplicados a GeminiStrategy.py (vs mega-prompt original)

1. Variables mutable movidas de clase a instancia (`_last_gemini_call`, `_gemini_decisions`, `_gemini_model`)
2. Eliminada variable `last_row` sin usar en `populate_entry_trend()`
3. Validación estricta de respuesta Gemini: solo acepta BUY/SELL/HOLD/CLOSE, clamp confianza 0-100
4. Heurística de backtesting: si dataframe > 500 velas, no llama a Gemini (retorna HOLD)
5. Rate limit guard de 4s entre llamadas a Gemini
6. Cache de decisiones por `{pair}_{timestamp_ultima_vela}`

### Parámetros de riesgo iniciales

| Parámetro | Valor | Razonamiento |
|---|---|---|
| Stop-loss | 1.5% | Conservador, evita pérdidas grandes |
| Take-profit | 2.0% | Risk/reward ratio de 1:1.33 |
| Capital por trade | 10% | Máx 10 trades simultáneos posibles |
| Confianza mínima | 75% | Solo opera cuando Gemini está seguro |
| Max posiciones | 1 | Simplifica el MVP |

### Estado actual
- ✅ Estructura de archivos creada (13 archivos)
- ✅ GeminiStrategy.py implementado con fixes
- ✅ config.json y config_dry_run.json creados y validados
- ✅ Railway deploy configurado (Dockerfile + railway.toml)
- ✅ Documentación completa (.windsurfrules, CONTEXT.md, MEMORY.md)
- ⏳ Pendiente: backtesting con data histórica
- ⏳ Pendiente: optimización de parámetros con HyperOpt
- ⏳ Pendiente: migración a Binance real

---

## v1.1.0 — Bot en producción local (3 Mayo 2026)

### Cambios realizados

**Exchange: Binance → KuCoin**
- Binance bloqueaba conexiones DNS async (aiohttp/Windows bug + geo-restricción)
- KuCoin funciona sin restricciones desde cualquier red
- Config: `ccxt_async_config.family: 4` para forzar IPv4

**SDK Gemini: google-generativeai → google-genai**
- SDK antiguo deprecado; migrado a `google-genai>=1.0.0`
- Nuevo cliente: `genai.Client(api_key=...)` + `client.models.generate_content()`

**Indicadores técnicos: pandas-ta/TA-Lib → pandas puro**
- TA-Lib 0.4.x incompatible con numpy 2.x (error "dtype size changed")
- Reemplazado con `_calc_rsi()` y `_calc_ema()` usando pandas ewm() nativo
- Sin dependencias de compilación, funciona en cualquier OS

**FastAPI: versión incorrecta → 0.115.12 + pydantic 2.13.3**
- Freqtrade 2025.6 requiere fastapi 0.115.x exacto
- Versión 0.103.x y 0.136.x rompen el api_server con AssertionError

**Telegram: python-telegram-bot → requests directo**
- PTB v21+ incompatible con Python 3.10 (asyncio shutdown race condition)
- PTB v13.x incompatible con Freqtrade 2025.6 (MessageLimit import error)
- Solución: función `_tg()` con `requests.post` en thread daemon
- Notificaciones en: confirm_trade_entry y confirm_trade_exit

**FreqUI instalada**: `freqtrade install-ui` → FreqUI v2.2.5

### Parámetros modificados

| Parámetro | Antes | Después | Razón |
|---|---|---|---|
| Exchange | Binance Testnet | KuCoin | Conectividad |
| stake_amount | 10 USDT | 1 USDT | Capital real del usuario: $50 |
| dry_run_wallet | 100 | 50 | Simula capital real |
| MIN_CONFIDENCE | 75% | 65% | Más operaciones diarias |
| Modelo Gemini | gemini-2.5-flash-lite | gemini-2.5-flash | Mejor calidad |
| Prompt Gemini | Conservador (HOLD default) | Intraday activo (3-8 trades/día) | Más actividad |

### Estado actual v1.1.0
- ✅ Bot corriendo en KuCoin dry-run con $50 virtual
- ✅ FreqUI panel en localhost:8080 (user: admin / pass: geminibot2026)
- ✅ Telegram notificaciones via requests directo (chat_id: 6729779078)
- ✅ Gemini 2.5 Flash llamando cada vela de 5 minutos
- ✅ RSI + EMA20/50 calculados con pandas puro (sin TA-Lib)
- ⏳ Pendiente: configurar inicio automático al arrancar Windows
- ⏳ Pendiente: crear script start_bot.ps1 para arrancar con 1 click
- ⏳ Pendiente: backtesting con data histórica de KuCoin
- ⏳ Pendiente: migración a KuCoin real (agregar API key + secret + password)
- ⏳ Pendiente: deploy en Railway para 24/7 sin dejar PC encendida

---

## v1.2.0 — Debugging y estabilización (3 Mayo 2026)

### Bugs críticos resueltos

**1. Deadlock en _get_active_api_entry**
- Causa: el método adquiría `_api_lock` y luego llamaba a `_rotate_api()` que también intentaba adquirirlo
- Fix: liberar el lock antes de llamar a `_rotate_api()`

**2. Doble llamada Gemini en populate_exit_trend**
- Causa: `populate_exit_trend` hacía una llamada fresca a `_get_gemini_decision` en vez de usar el caché
- Fix: leer de `self._gemini_decisions[cache_key]` en lugar de llamar Gemini de nuevo

**3. Crash scheduler fin de mes**
- Causa: `target.replace(day=target.day + 1)` falla el día 31 (día 32 no existe)
- Fix: usar `target + timedelta(days=1)`

**4. Bot silencioso cuando APIs agotadas**
- Causa: error 429 de Google no se mapeaba correctamente al contador local → bot entraba en HOLD infinito sin avisar
- Fix: al recibir 429, marcar la API actual como agotada en `_api_usage` y notificar Telegram

**5. Reset automático a medianoche UTC**
- Añadido `_api_reset_scheduler` — thread daemon que limpia todos los contadores a las 00:00 UTC
- Notifica por Telegram "APIS RECARGADAS" para confirmar que el bot retomó análisis

**6. Tendencia 1H siempre UNKNOWN al arrancar**
- Causa: primer fetch 1H se hacía en background, llegaba después de la primera llamada a Gemini
- Fix: pre-cargar 5 pares en threads al `__init__` para que el primer ciclo ya tenga datos

**7. UnicodeEncodeError en logger (Windows cp1252)**
- Causa: emojis en `logger.info()` no son compatibles con la consola Windows
- Fix: reemplazar todos los emojis de logger con prefijos ASCII `[ENTRY]`, `[GEMINI]`, etc.

**8. Emojis en prompt de Gemini desperdiciaban tokens**
- Fix: reemplazar todos los emojis del prompt con texto plano

### Optimizaciones de consumo de API

**Problema:** Las APIs se agotaban en minutos durante la sesión de debug (10 reinicios × 5 req = 50 req malgastadas)

| Cambio | Impacto |
|---|---|
| Pool: Flash-Lite primero (1000 RPD × 3 = 3000) | Antes 750 req/día, ahora 3000+ |
| max_output_tokens: 500 → 120 | -76% tokens de salida |
| Prompt compacto (una línea de datos) | -60% tokens de entrada |
| Flash inteligente: solo en señales (RSI<45, BB<30, MACD cruce) | Flash reservado para BUYs reales |
| Pre-fetch 1H en background al arrancar | Sin requests extra en primer ciclo |

**Consumo real estabilizado:** ~80 tokens/llamada × 60 req/hora = 4,800 tokens/hora vs 24,000 antes

### Cambios de configuración

| Parámetro | Antes | Después | Razón |
|---|---|---|---|
| Pool orden | Flash primero | Lite primero | Flash-Lite tiene 4x más cuota diaria |
| max_output_tokens | 500 | 120 | JSON solo necesita ~50 tokens |
| MIN_CONFIDENCE | 65% | 50% (demo) | Ver primer trade en demo más fácilmente |
| RATE_LIMIT_SECONDS | 5.0 | 2.0 | Ciclo 5 pares = 10s vs 25s |
| max_open_trades (config) | 3 | 1 | Coincidir con estrategia |
| Pairlists | VolumePairList + filtros | StaticPairList (5 pares fijos) | Sin bloqueos al arrancar |
| Telegram | disabled | enabled | Notificaciones activas |

### Nuevas funcionalidades añadidas

- **Auto-aprendizaje**: `_trade_memory` guarda últimos 20 resultados reales, incluidos en el prompt como contexto
- **Noticias crypto**: CryptoPanic API gratis con caché 15 min
- **Fear & Greed Index**: api.alternative.me con caché 1 hora
- **Resumen diario**: Telegram a las 23:59 UTC con stats del día

### Estado actual v1.2.0
- ✅ Primer trade ejecutado en demo: XRP/USDT a 1.40418 USDT (3 Mayo 2026)
- ✅ FreqUI en localhost:8080 — balance 45 USDT demo visible
- ✅ Telegram recibe: entry, exit, rotación API, resumen diario
- ✅ Reset automático de APIs a medianoche UTC
- ✅ Prompt compacto: 75% menos tokens por llamada
- ⏳ Pendiente: primer ciclo completo (trade abierto → cerrado con ganancia/pérdida)
- ⏳ Pendiente: subir MIN_CONFIDENCE a 60-65 cuando se confirme que el bot gana en demo
- ⏳ Pendiente: deploy en Railway para 24/7 sin dejar PC encendida
- ⏳ Pendiente: migración a KuCoin real (ya tiene API key configurada)

### Notas importantes para próxima sesión
- Las APIs Gemini se resetean a **medianoche UTC = 18:00 hora México**
- El bot necesita la PC encendida (aún no está en Railway)
- Para mañana: revisar si el trade de XRP se cerró con ganancia o pérdida
- MIN_CONFIDENCE=50 es temporal para demo; subir a 60 antes de dinero real

---

## v1.3.0 — Indicadores avanzados + pares expandidos (3 Mayo 2026)

### Cambios realizados

**Indicadores nuevos en populate_indicators:**
- Stochastic RSI (14,3,3) — momentum sobrecompra/sobreventa mas sensible que RSI
- OBV (On Balance Volume) — confirma si el volumen respalda el movimiento
- Williams %R (14) — oscilador de sobreventa/sobrecompra
- CCI (20) — Commodity Channel Index, detecta impulsos fuertes
- Patrones de velas (Hammer, Doji, Engulf, Shooting Star) — señales visuales
- Fibonacci retracement (38.2%, 50%, 61.8%) sobre los ultimos 50 periodos
- Numeros redondos psicologicos (distancia al multiplo de 100/1000 mas cercano)
- Soporte/Resistencia 20 velas (swing), 50 velas (institucional), 100 velas (largo plazo)
- EMA200 — soporte/resistencia institucional de referencia

**Pares expandidos: 5 → 10**
- Agregados: DOGE, ADA, AVAX, LINK, TRX

**max_open_trades: 1 → 5**
- Permite hasta 5 posiciones simultaneas
- Capital maximo expuesto: 5 × 20% = 100% del balance

**MIN_CONFIDENCE bajado a 45** para capturar mas oportunidades en dry-run

### Estado
- ✅ Bot corriendo con 10 pares y 5 trades simultaneos
- ✅ Todos los indicadores avanzados calculados en pandas puro

---

## v1.4.0 — Q-Learning + Regimen de mercado + Autopausa (4 Mayo 2026)

### Cambios realizados

**Q-Learning tabular:**
- 100 estados (trend × volatility × momentum)
- 4 acciones: HOLD, BUY, SELL, CLOSE
- Epsilon-greedy con decay 0.3 → 0.05
- Bellman update: alpha=0.1, gamma=0.9
- Experience replay buffer 500 experiencias, batches de 32
- Q-table persistida en `user_data/qtable.json`
- Q-Learning hint incluido en prompt de Gemini

**Deteccion de regimen de mercado (10 estados):**
- TENDENCIA_ALCISTA_CALMADA / NORMAL / VOLATIL
- TENDENCIA_BAJISTA_CALMADA / NORMAL / VOLATIL
- RANGO_TRANQUILO / VOLATIL
- CAOS_VOLATIL
- TRANSICION
- Cada regimen ajusta: stake_mult y sl_mult
- BAJISTA_VOLATIL y CAOS: stake_mult=0.0 (no abrir trades)

**Autopausa inteligente:**
- Drawdown diario >5% → pausa 2h
- Winrate <35% en ultimos 10 trades → pausa 1h
- Profit factor <0.7 en ultimos 15 trades → pausa 30min
- Evaluacion cada 5 trades cerrados

**Memoria activa ampliada:**
- 20 → 50 trades en memoria
- Incluye: RSI de entrada, razon de salida, patron de perdida

### Parametros de riesgo

| Parametro | Antes | Despues | Razon |
|---|---|---|---|
| max_open_trades | 1 | 5 | Mas oportunidades simultaneas |
| Memoria trades | 20 | 50 | Mejor deteccion de patrones |
| Soporte/Resistencia | 20 velas | 20+50+100 velas | Niveles institucionales reales |

---

## v1.5.0 — ADX + MFI + Stop loss dinamico ATR + Dashboard (4 Mayo 2026)

### Cambios realizados

**ADX (Average Directional Index, periodo 14):**
- Calcula +DI, -DI y ADX con pandas puro
- Si ADX < 25: mercado lateral → HOLD directo sin llamar a Gemini
- Ahorra ~30-40% de llamadas API en mercados sin tendencia
- ADX incluido en prompt: `FUERZA: ADX=31[FUERTE]`
- Regla nueva: NUNCA COMPRAR si ADX<25

**MFI (Money Flow Index, periodo 14):**
- RSI ponderado por volumen real
- Detecta sobrecompra/sobreventa con confirmacion de dinero
- MFI<25 requerido para senales oportunistas (antes solo RSI<35)
- MFI>75 bloquea entradas (sobrecompra con volumen)

**Stop loss dinamico ATR:**
- `stop = ATR% x multiplicador` (floor 0.8%, ceiling 3.0%)
- Mercado CALMADA: mult=1.2 (stop ajustado)
- Mercado VOLATIL/CAOS: mult=2.0 (stop amplio)
- Si profit >2%: trailing de 0.5% para asegurar ganancia
- ATR real del par guardado en decision cacheada y usado en notificaciones

**Capital por trade: 10% → 20%**
- stake_amount: 2 fijo → "unlimited" con tradable_balance_ratio=0.75
- 20% del balance por trade (max 5 trades = 100% exposicion)
- dry_run_wallet: 50 → 1000 (simulacion mas realista)

**Alertas Telegram mejoradas:**
- Entrada incluye: ADX, MFI, regimen, stop ATR real, ratio riesgo/ganancia
- Salida incluye: ADX y MFI al momento del cierre, regimen

**GeminiBacktest.py actualizado:**
- ADX > 25 como filtro obligatorio en señal principal
- MFI < 25 requerido en señal oportunista
- max_open_trades: 3 → 5

**Dashboard web** (`user_data/dashboard.html`):
- Abre en navegador → http://localhost:8080/dashboard o abrir el HTML directamente
- Muestra: balance, P&L, trades abiertos y cerrados
- Actualizacion automatica cada 15 segundos
- Conecta a la API de Freqtrade (user: admin / pass: geminibot2026)

### Observaciones del dashboard (4 Mayo 2026, 07:12)
- 2 trades abiertos en verde: BTC/USDT +0.56%, ETH/USDT +0.41%
- 5 trades cerrados: W/L = 4/3 (57% winrate inicial)
- BTC y SOL cerraron por trailing_stop_loss con -1.7% y -1.04%
- El trailing stop de 0.5% era demasiado ajustado para volatilidad crypto 5m
- ADX de todos los pares < 25 en este momento (mercado lateral, bot en HOLD)

### Notas para proxima sesion
- El mercado estaba lateral al implementar ADX (todos < 25) — esperar tendencia
- Stop loss dinamico ATR ya activo — monitorear si reduce stops prematuros
- Considerar subir trailing_stop_positive_offset de 0.01 a 0.015 si hay muchos trailing_stop_loss

---

## TEMPLATE para futuras entradas (copiar cuando hagas cambios)

## vX.X.X — [Descripción] (Fecha)

### Cambio realizado
[Qué se modificó]

### Razonamiento
[Por qué se tomó esta decisión]

### Impacto
[Qué mejoró o cambió]

### Parámetros modificados (si aplica)
| Parámetro | Antes | Después | Razón |
|---|---|---|---|
| nombre | valor_viejo | valor_nuevo | razón |

---
