"""
GeminiStrategy.py
Estrategia custom para Freqtrade que usa Google Gemini AI
como motor de decisión de trading.

Autor: GeminiTradingBot
Version: 1.0.0
"""

import json
import logging
import math
import os
import random
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

# from google import genai  # Eliminado - solo usamos Groq
# from google.genai import types as genai_types  # Eliminado - solo usamos Groq
try:
    from groq import Groq as GroqClient
except ImportError:
    GroqClient = None
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter

logger = logging.getLogger(__name__)

# Configuración de IA - Solo Groq
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "50"))
RATE_LIMIT_SECONDS = 5.0

# Pool de APIs - Solo Groq para evitar bloqueos
GROQ_API_POOL = [
    {"key": os.getenv("GROQ_KEY_1", ""), "model": "llama-3.1-8b-instant", "daily_limit": 14400, "label": "Groq-1"},
    {"key": os.getenv("GROQ_KEY_2", ""), "model": "llama-3.1-8b-instant", "daily_limit": 14400, "label": "Groq-2"},
    {"key": os.getenv("GROQ_KEY_3", ""), "model": "llama-3.1-8b-instant", "daily_limit": 14400, "label": "Groq-3"},
]

# Telegram directo (sin python-telegram-bot)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# CryptoPanic — noticias crypto en tiempo real (tier gratuito, sin API key)
CRYPTO_NEWS_CACHE: dict = {"data": [], "sentiment": 50, "ts": 0.0}
CRYPTO_NEWS_TTL = 900  # refrescar cada 15 minutos

FEAR_GREED_CACHE: dict = {"value": 50, "label": "Neutral", "ts": 0.0}
FEAR_GREED_TTL = 3600  # refrescar cada hora

# Reddit sentiment — menciones en r/cryptocurrency (gratis, sin auth)
REDDIT_SENTIMENT_CACHE: dict = {}  # {coin: {"score": 50, "mentions": 0, "ts": 0.0}}
REDDIT_SENTIMENT_TTL = 1800  # refrescar cada 30 minutos

# CoinGecko trending — coins trending socialmente (gratis)
TRENDING_CACHE: dict = {"coins": [], "ts": 0.0}
TRENDING_TTL = 3600  # refrescar cada hora


def _fetch_fear_greed() -> tuple:
    """Obtiene el Fear & Greed Index actual. Caché 1 hora. Retorna (valor, label)."""
    global FEAR_GREED_CACHE
    now = time.time()
    if now - FEAR_GREED_CACHE["ts"] > FEAR_GREED_TTL:
        try:
            resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            if resp.status_code == 200:
                data = resp.json()["data"][0]
                FEAR_GREED_CACHE["value"] = int(data["value"])
                FEAR_GREED_CACHE["label"] = data["value_classification"]
                FEAR_GREED_CACHE["ts"] = now
        except Exception:
            pass
    return FEAR_GREED_CACHE["value"], FEAR_GREED_CACHE["label"]


def _fetch_crypto_news(coin: str) -> tuple:
    """Obtiene titulares + sentiment de noticias. Caché 15 min. Retorna (headlines_str, sentiment_score)."""
    global CRYPTO_NEWS_CACHE
    now = time.time()
    if now - CRYPTO_NEWS_CACHE["ts"] > CRYPTO_NEWS_TTL:
        try:
            coin_symbol = coin.split("/")[0].lower()
            url = f"https://cryptopanic.com/api/free/v1/posts/?auth_token=anonymous&currencies={coin_symbol}&kind=news&public=true"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                items = resp.json().get("results", [])[:5]
                CRYPTO_NEWS_CACHE["data"] = [i.get("title", "") for i in items]
                # Calcular sentiment de votos bullish/bearish
                bullish = sum(i.get("votes", {}).get("positive", 0) for i in items)
                bearish = sum(i.get("votes", {}).get("negative", 0) for i in items)
                total_votes = bullish + bearish
                if total_votes > 0:
                    CRYPTO_NEWS_CACHE["sentiment"] = int(bullish / total_votes * 100)
                else:
                    CRYPTO_NEWS_CACHE["sentiment"] = 50
                CRYPTO_NEWS_CACHE["ts"] = now
        except Exception:
            pass
    headlines = CRYPTO_NEWS_CACHE["data"]
    headline_str = " | ".join(f"• {h}" for h in headlines[:3]) if headlines else "Sin noticias recientes."
    return headline_str, CRYPTO_NEWS_CACHE["sentiment"]


def _fetch_reddit_sentiment(coin: str) -> tuple:
    """Scraping Reddit r/cryptocurrency para sentiment. Caché 30 min. Retorna (score 0-100, menciones)."""
    global REDDIT_SENTIMENT_CACHE
    coin_symbol = coin.split("/")[0].upper()
    now = time.time()
    cached = REDDIT_SENTIMENT_CACHE.get(coin_symbol, {"score": 50, "mentions": 0, "ts": 0.0})
    if now - cached["ts"] > REDDIT_SENTIMENT_TTL:
        try:
            url = f"https://www.reddit.com/r/cryptocurrency/search.json?q={coin_symbol}&sort=new&t=day&limit=15"
            headers = {"User-Agent": "GeminiTradingBot/1.0"}
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                posts = resp.json().get("data", {}).get("children", [])
                mentions = len(posts)
                if mentions > 0:
                    # Score basado en upvote ratio y score de posts
                    total_score = sum(p["data"].get("score", 0) for p in posts)
                    avg_upvote = sum(p["data"].get("upvote_ratio", 0.5) for p in posts) / mentions
                    # Normalizar: >0 score promedio = bullish, ratio > 0.6 = bullish
                    sentiment = int(avg_upvote * 100)
                    sentiment = max(10, min(90, sentiment))  # clamp 10-90
                else:
                    sentiment = 50
                REDDIT_SENTIMENT_CACHE[coin_symbol] = {"score": sentiment, "mentions": mentions, "ts": now}
            else:
                REDDIT_SENTIMENT_CACHE[coin_symbol] = {"score": 50, "mentions": 0, "ts": now}
        except Exception:
            REDDIT_SENTIMENT_CACHE[coin_symbol] = {"score": cached.get("score", 50), "mentions": cached.get("mentions", 0), "ts": now}
    cached = REDDIT_SENTIMENT_CACHE.get(coin_symbol, {"score": 50, "mentions": 0})
    return cached["score"], cached["mentions"]


def _fetch_trending_coins() -> list:
    """Obtiene lista de coins trending en CoinGecko. Caché 1 hora. Retorna lista de símbolos."""
    global TRENDING_CACHE
    now = time.time()
    if now - TRENDING_CACHE["ts"] > TRENDING_TTL:
        try:
            resp = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=8)
            if resp.status_code == 200:
                items = resp.json().get("coins", [])
                TRENDING_CACHE["coins"] = [i["item"]["symbol"].upper() for i in items[:10]]
                TRENDING_CACHE["ts"] = now
        except Exception:
            pass
    return TRENDING_CACHE["coins"]


def _tg(msg: str) -> None:
    """Envía mensaje a Telegram en background, sin bloquear el bot."""
    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


class GeminiStrategy(IStrategy):
    """
    Estrategia de trading basada en Gemini AI.

    Usa indicadores técnicos (RSI, EMA20, EMA50, volumen) como contexto
    y llama a Gemini API cada vela para obtener la decisión de trading.

    Timeframe: 5m
    Exchange: KuCoin | 5 pares: BTC, ETH, XRP, SOL, BNB
    """

    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False
    max_open_trades = 7
    stoploss = -0.015
    minimal_roi = {"0": 0.020, "30": 0.015, "60": 0.010, "90": 0.008}
    # ROI para alta confianza — se aplica dinámicamente en custom_exit
    _roi_high_confidence = {"0": 0.035, "60": 0.025, "120": 0.015}
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True
    use_custom_stoploss = True
    startup_candle_count: int = 210

    rsi_buy_threshold = IntParameter(30, 60, default=55, space="buy")
    rsi_sell_threshold = IntParameter(65, 85, default=70, space="sell")
    ema_fast = IntParameter(10, 30, default=20, space="buy")
    ema_slow = IntParameter(30, 70, default=50, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._last_gemini_call = 0.0
        self._gemini_decisions = {}
        self._last_pair_refresh = 0.0
        self._selected_pair = None
        # Tracking diario
        self._daily_trades = []  # lista de {pair, profit_usd, profit_pct, won}
        self._last_summary_date = None
        self._daily_loss_usd = 0.0        # pérdida acumulada hoy en USD
        self._daily_loss_date = None      # fecha del último reset de pérdidas
        self._stoploss_cooldown: dict = {}  # par -> timestamp del último stop-loss
        self._loss_cooldown: dict = {}    # par -> timestamp hasta el que no reentrar (2h)
        self._daily_losses: dict = {}     # par -> [timestamps] de losses en 24h
        self._MAX_DAILY_LOSSES = 3        # max losses por par antes de bloquearlo el dia
        # Memoria de aprendizaje: últimos 50 resultados de trades
        self._trade_memory: list = []  # {pair, accion, confianza, rsi, profit_usd, won, razon}
        self._daily_trades_lock = threading.Lock()

        # Cache de datos 1h por par — instancia, no clase
        self._cache_1h: dict = {}
        self._cache_1h_ttl: float = 3600.0
        self._cache_1h_lock = threading.Lock()

        # ── Q-Learning Tabular ──────────────────────────────────────────────
        self._qtable_path = Path(__file__).parent / "qtable.json"
        self._q_actions = ["HOLD", "BUY", "SELL", "CLOSE"]  # índices 0-3
        self._q_states = 100          # estados del mercado (tendencia×volatilidad×momentum)
        self._q_alpha = 0.1           # tasa de aprendizaje
        self._q_gamma = 0.9           # descuento de recompensa futura
        self._q_epsilon = 0.3         # exploración inicial (30% aleatorio)
        self._q_epsilon_min = 0.05    # exploración mínima (5%)
        self._q_epsilon_decay = 0.995 # decaimiento por episodio
        self._q_episodes = 0          # operaciones totales realizadas
        self._experience_replay: list = []  # buffer de hasta 500 experiencias
        self._q_table: list = self._load_qtable()
        self._q_lock = threading.Lock()

        # ── Régimen de Mercado ──────────────────────────────────────────────
        self._market_regime = "UNKNOWN"  # estado actual del mercado
        self._regime_stake_mult = 1.0    # multiplicador de stake según régimen
        self._regime_sl_mult = 1.0       # multiplicador de stop-loss según régimen

        # ── Autopausa ───────────────────────────────────────────────────────
        self._autopause_until: float = 0.0   # timestamp hasta el que está pausado
        self._autopause_reason: str = ""
        self._trades_since_check: int = 0    # contador para evaluar métricas cada N trades

        # ── Checklist demo → live ───────────────────────────────────────────
        self._live_ready_notified: bool = False  # evitar repetir notificación

        # Sistema de rotación de APIs
        # Gemini free-trial expirado: arrancar directamente en Groq
        _today = datetime.now(timezone.utc).date()
        self._api_usage = {entry["label"]: {"count": 0, "date": datetime.now(timezone.utc).date()} for entry in GROQ_API_POOL}
        self._gemini_decisions = {}
        self._gemini_client = None
        self._gemini_model_active = None
        self._api_index = 0  # índice del pool de APIs activo
        self._api_lock = threading.Lock()
        self._last_gemini_call = 0
        self._init_gemini_client()  # inicializar cliente Groq al arrancar

        # Arrancar scheduler de resumen diario en background
        threading.Thread(target=self._daily_summary_scheduler, daemon=True).start()

        # Thread que resetea contadores de API a medianoche UTC (cuando Google las recarga)
        threading.Thread(target=self._api_reset_scheduler, daemon=True).start()

        # Pre-cargar datos 1h de los pares fijos al arrancar
        # Los pares dinámicos (VolumePairList) se cargan cuando entran
        static_pairs = [
            "BTC/USDT", "ETH/USDT",
        ]
        for p in static_pairs:
            threading.Thread(target=self._refresh_1h_background, args=(p,), daemon=True).start()

    def _api_reset_scheduler(self) -> None:
        """Resetea contadores de API a medianoche UTC cuando Google los recarga."""
        from datetime import timedelta
        while True:
            now = datetime.now(timezone.utc)
            # Siguiente medianoche UTC
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
            time.sleep((midnight - now).total_seconds())
            # Resetear todos los contadores
            today = datetime.now(timezone.utc).date()
            with self._api_lock:
                for entry in GROQ_API_POOL:
                    self._api_usage[entry["label"]]["count"] = 0
                    self._api_usage[entry["label"]]["date"] = today
                self._api_index = 0
                first = GROQ_API_POOL[0]
                self._gemini_client = GroqClient(api_key=first["key"])
            logger.info("[RESET] Contadores de API reseteados a medianoche UTC (reset diario)")
            _tg(
                "APIS RECARGADAS\n"
                "Nueva cuota diaria disponible (medianoche UTC).\n"
                "El bot retoma el analisis con Gemini normalmente."
            )

    def _init_gemini_client(self) -> None:
        """Inicializa el cliente de Groq."""
        entry = GROQ_API_POOL[self._api_index]
        self._gemini_client = GroqClient(api_key=entry["key"])
        self._gemini_model_active = entry["model"]
        logger.info(f"[OK] API activa: {entry['label']} | proveedor: Groq | modelo: {entry['model']}")

    def _call_llm(self, entry: dict, prompt: str) -> str:
        """Llama siempre a Groq. Retorna texto crudo."""
        if GroqClient is None:
            raise RuntimeError("groq SDK no instalado")
        gc = GroqClient(api_key=entry["key"])
        r = gc.chat.completions.create(
            model=entry["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.1,
        )
        return r.choices[0].message.content.strip()

    # ── Q-Learning ─────────────────────────────────────────────────────────

    def _load_qtable(self) -> list:
        """Carga la Q-table desde disco o crea una nueva con ceros."""
        if self._qtable_path.exists():
            try:
                data = json.loads(self._qtable_path.read_text())
                self._q_epsilon = data.get("epsilon", 0.3)
                self._q_episodes = data.get("episodes", 0)
                logger.info(f"[QLEARN] Q-table cargada: {self._q_episodes} episodios, epsilon={self._q_epsilon:.3f}")
                return data["qtable"]
            except Exception as e:
                logger.warning(f"[QLEARN] Error cargando Q-table: {e}, creando nueva")
        return [[0.0] * 4 for _ in range(self._q_states)]

    def _save_qtable(self) -> None:
        """Guarda Q-table, epsilon y episodios en disco."""
        try:
            with self._q_lock:
                data = {"qtable": self._q_table, "epsilon": self._q_epsilon, "episodes": self._q_episodes}
            self._qtable_path.write_text(json.dumps(data))
        except Exception as e:
            logger.warning(f"[QLEARN] Error guardando Q-table: {e}")

    def _encode_state(self, dataframe: DataFrame) -> int:
        """Codifica el estado del mercado en un número 0-99 basado en tendencia, volatilidad y momentum."""
        last = dataframe.iloc[-1]
        # Tendencia: 0-4 basado en EMA cruce y posición vs EMA200
        if last.get("ema200_signal") == "ABOVE" and last.get("ema_signal") == "BULL":
            trend = 4
        elif last.get("ema_signal") == "BULL":
            trend = 3
        elif last.get("ema200_signal") == "ABOVE":
            trend = 2
        elif last.get("ema_signal") == "BEAR":
            trend = 1
        else:
            trend = 0
        # Volatilidad: 0-3 basado en ATR normalizado
        atr_pct = last.get("atr_pct", 0.5)
        if atr_pct < 0.3:
            vol = 0
        elif atr_pct < 0.6:
            vol = 1
        elif atr_pct < 1.2:
            vol = 2
        else:
            vol = 3
        # Momentum: 0-4 basado en RSI
        rsi = last.get("rsi", 50)
        if rsi < 30:
            mom = 0
        elif rsi < 45:
            mom = 1
        elif rsi < 55:
            mom = 2
        elif rsi < 70:
            mom = 3
        else:
            mom = 4
        # Combinar en estado 0-99: trend(5) × vol(4) × mom(5) = 100
        state = (trend * 20) + (vol * 5) + mom
        return min(state, 99)

    def _q_get_action(self, state: int, force_exploit: bool = False) -> int:
        """Selecciona acción por epsilon-greedy. Retorna índice de acción (0=HOLD,1=BUY,2=SELL,3=CLOSE)."""
        with self._q_lock:
            if not force_exploit and random.random() < self._q_epsilon:
                return random.randint(0, 3)
            return int(max(range(4), key=lambda a: self._q_table[state][a]))

    def _q_update(self, state: int, action: int, reward: float, next_state: int) -> None:
        """Actualiza Q-table con la fórmula de Bellman."""
        with self._q_lock:
            best_next = max(self._q_table[next_state])
            old_q = self._q_table[state][action]
            self._q_table[state][action] = old_q + self._q_alpha * (reward + self._q_gamma * best_next - old_q)
            self._q_epsilon = max(self._q_epsilon_min, self._q_epsilon * self._q_epsilon_decay)
            self._q_episodes += 1

    def _q_reward(self, profit_pct: float, stake: float) -> float:
        """Calcula recompensa: positiva si gana (suavizada por raíz), negativa si pierde (penalización 1.5×)."""
        if profit_pct > 0:
            reward = math.sqrt(abs(profit_pct) * 100)
            rr = abs(profit_pct) / 0.015  # ratio vs stop-loss
            if rr > 1.5:
                reward += 1.0  # bonus de calidad por buen RR
        else:
            reward = -math.sqrt(abs(profit_pct) * 100) * 1.5
        return round(reward, 4)

    def _experience_replay_train(self) -> None:
        """Repasa 32 experiencias aleatorias del buffer para acelerar el aprendizaje."""
        if len(self._experience_replay) < 32:
            return
        batch = random.sample(self._experience_replay, 32)
        for exp in batch:
            self._q_update(exp["state"], exp["action"], exp["reward"], exp["next_state"])

    # ── Régimen de Mercado ────────────────────────────────────────────────

    def _detect_regime(self, dataframe: DataFrame) -> str:
        """Clasifica el mercado en uno de 10 regímenes usando ADX real, ATR y EMAs."""
        if len(dataframe) < 30:
            return "UNKNOWN"
        last = dataframe.iloc[-1]
        # Usar ADX real calculado en populate_indicators (mas preciso que ema_diff)
        adx_val = float(last.get("adx", 0)) if not pd.isna(last.get("adx", float('nan'))) else 0.0
        atr_pct = last.get("atr_pct", 0.5)
        rsi = last.get("rsi", 50)
        ema_bull = last.get("ema_signal") == "BULL"
        ema200 = last.get("ema200_signal") == "ABOVE"
        # Determinar tendencia, volatilidad y régimen usando ADX real
        strong_trend = adx_val > 20
        volatile = atr_pct > 1.0
        very_volatile = atr_pct > 2.0
        if very_volatile and not strong_trend:
            regime = "CAOS_VOLATIL"
        elif strong_trend and ema_bull and ema200 and volatile:
            regime = "TENDENCIA_ALCISTA_VOLATIL"
        elif strong_trend and ema_bull and ema200:
            regime = "TENDENCIA_ALCISTA_NORMAL" if atr_pct > 0.4 else "TENDENCIA_ALCISTA_CALMADA"
        elif strong_trend and not ema_bull and volatile:
            regime = "TENDENCIA_BAJISTA_VOLATIL"
        elif strong_trend and not ema_bull:
            regime = "TENDENCIA_BAJISTA_NORMAL" if atr_pct > 0.4 else "TENDENCIA_BAJISTA_CALMADA"
        elif not strong_trend and volatile:
            regime = "RANGO_VOLATIL"
        elif not strong_trend:
            regime = "RANGO_TRANQUILO"
        else:
            regime = "TRANSICION"
        # Ajustar multiplicadores de stake y stop segun regimen
        regime_params = {
            "TENDENCIA_ALCISTA_CALMADA":  (1.0,  1.0),
            "TENDENCIA_ALCISTA_NORMAL":   (1.0,  1.2),
            "TENDENCIA_ALCISTA_VOLATIL":  (0.7,  1.8),
            "TENDENCIA_BAJISTA_CALMADA":  (0.5,  1.0),
            "TENDENCIA_BAJISTA_NORMAL":   (0.3,  1.5),
            "TENDENCIA_BAJISTA_VOLATIL":  (0.0,  2.0),
            "RANGO_TRANQUILO":            (0.8,  0.8),
            "RANGO_VOLATIL":              (0.5,  1.2),
            "CAOS_VOLATIL":               (0.0,  2.5),
            "TRANSICION":                 (0.7,  1.3),
            "UNKNOWN":                    (0.5,  1.0),
        }
        self._regime_stake_mult, self._regime_sl_mult = regime_params.get(regime, (0.5, 1.0))
        if regime != self._market_regime:
            logger.info(f"[REGIME] Cambio de regimen: {self._market_regime} -> {regime} | stake_mult={self._regime_stake_mult} sl_mult={self._regime_sl_mult}")
            self._market_regime = regime
        return regime

    # ── Autopausa ─────────────────────────────────────────────────────────

    def _check_autopause(self) -> None:
        """Evalúa métricas y activa autopausa si el bot está rindiendo mal."""
        recent = self._trade_memory[-20:] if len(self._trade_memory) >= 3 else []
        if not recent:
            return
        wins = sum(1 for t in recent if t["won"])
        losses = len(recent) - wins
        winrate = wins / len(recent)
        total_profit = sum(t["profit_usd"] for t in recent if t["won"])
        total_loss = abs(sum(t["profit_usd"] for t in recent if not t["won"]))
        profit_factor = total_profit / total_loss if total_loss > 0 else 99.0
        drawdown_pct = self._daily_loss_usd / max(self._daily_loss_usd + 50, 50) * 100
        pause_duration = 0
        reason = ""
        if drawdown_pct > 5.0:
            pause_duration = 7200  # 2 horas
            reason = f"Drawdown diario {drawdown_pct:.1f}% > 5%"
        elif winrate < 0.35 and len(recent) >= 10:
            pause_duration = 3600  # 1 hora
            reason = f"Winrate {winrate*100:.0f}% < 35% en últimos {len(recent)} trades"
        elif profit_factor < 0.7 and len(recent) >= 15:
            pause_duration = 1800  # 30 min
            reason = f"Profit factor {profit_factor:.2f} < 0.7"
        if pause_duration > 0:
            self._autopause_until = time.time() + pause_duration
            self._autopause_reason = reason
            mins = pause_duration // 60
            logger.warning(f"[AUTOPAUSA] Bot pausado {mins}min | Razón: {reason}")
            _tg(
                f"AUTOPAUSA ACTIVADA\n"
                f"Razon: {reason}\n"
                f"WinRate: {winrate*100:.0f}% | PF: {profit_factor:.2f} | DD: {drawdown_pct:.1f}%\n"
                f"Bot pausado {mins} minutos. Se reanuda automaticamente."
            )


    def _check_live_readiness(self) -> None:
        """Evalúa si el bot está listo para operar con dinero real y avisa por Telegram."""
        if self._live_ready_notified:
            return
        mem = self._trade_memory
        if len(mem) < 15:
            return
        wins = [t for t in mem if t["won"]]
        losses = [t for t in mem if not t["won"]]
        win_rate = len(wins) / len(mem)
        total_profit = sum(t["profit_usd"] for t in wins)
        total_loss = abs(sum(t["profit_usd"] for t in losses)) if losses else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else 99.0
        max_dd = self._daily_loss_usd
        balance_approx = 1000.0  # wallet demo base
        max_dd_pct = (max_dd / balance_approx) * 100 if balance_approx > 0 else 0
        # Criterios acelerados: 15 trades, WR≥55%, PF≥1.2, DD<12%
        ready = (win_rate >= 0.55 and profit_factor >= 1.2 and max_dd_pct < 12.0)
        logger.info(
            f"[LIVE-CHECK] trades={len(mem)} WR={win_rate*100:.0f}% PF={profit_factor:.2f} "
            f"DD={max_dd_pct:.1f}% | READY={ready}"
        )
        if ready:
            self._live_ready_notified = True
            _tg(
                f"🟢 BOT LISTO PARA LIVE\n"
                f"---\n"
                f"Trades demo: {len(mem)} | WR: {win_rate*100:.0f}% | PF: {profit_factor:.2f}\n"
                f"Max DD: {max_dd_pct:.1f}% | Episodios Q: {self._q_episodes}\n"
                f"---\n"
                f"Para activar: cambiar dry_run=false en config.json\n"
                f"RECUERDA: solo capital que puedes perder"
            )

    def _fetch_1h_trend(self, pair: str) -> tuple:
        """Devuelve tendencia 1h desde caché. El refresco ocurre en background."""
        cached = self._cache_1h.get(pair)
        if cached:
            return cached["trend"], cached["rsi"]
        # Primera vez: lanzar fetch en background y retornar UNKNOWN
        threading.Thread(target=self._refresh_1h_background, args=(pair,), daemon=True).start()
        return "UNKNOWN", 50.0

    def _refresh_1h_background(self, pair: str) -> None:
        """Refresca datos 1h en un thread daemon para no bloquear el hilo principal."""
        now = time.time()
        with self._cache_1h_lock:
            cached = self._cache_1h.get(pair)
            if cached and now - cached["ts"] < self._cache_1h_ttl:
                return
        try:
            symbol = pair.replace("/", "-") if "-" not in pair else pair
            url = f"https://api.kucoin.com/api/v1/market/candles?type=1hour&symbol={symbol}&startAt={int(now)-7200*100}&endAt={int(now)}"
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                candles = resp.json().get("data", [])
                if len(candles) >= 50:
                    closes = pd.Series([float(c[2]) for c in reversed(candles)])
                    ema50 = float(self._calc_ema(closes, 50).iloc[-1])
                    rsi_val = float(self._calc_rsi(closes, 14).iloc[-1])
                    trend = "BULL" if closes.iloc[-1] > ema50 else "BEAR"
                    with self._cache_1h_lock:
                        self._cache_1h[pair] = {"trend": trend, "rsi": rsi_val, "ts": now}
        except Exception as e:
            logger.debug(f"1h fetch fallido para {pair}: {e}")

    def _rotate_api(self) -> bool:
        """Rota a la siguiente API disponible. Retorna False si todas agotadas."""
        today = datetime.now(timezone.utc).date()
        with self._api_lock:
            for _ in range(len(GROQ_API_POOL)):
                self._api_index = (self._api_index + 1) % len(GROQ_API_POOL)
                entry = GROQ_API_POOL[self._api_index]
                label = entry["label"]
                usage = self._api_usage[label]
                # Reset conteo si es nuevo día
                if usage["date"] != today:
                    usage["count"] = 0
                    usage["date"] = today
                if usage["count"] < entry["daily_limit"] and entry["key"]:
                    self._gemini_client = GroqClient(api_key=entry["key"])
                    self._gemini_model_active = entry["model"]
                    logger.info(f"[ROTATE] Rotando a {label} ({usage['count']}/{entry['daily_limit']} usadas)")
                    _tg(f"API rotada a {label}\nModelo: {entry['model']}\nUso: {usage['count']}/{entry['daily_limit']}")
                    return True
        logger.warning("[WARN] Todas las APIs agotadas por hoy. Bot en modo HOLD hasta manana.")
        _tg("TODAS LAS APIS AGOTADAS\nEl bot esta en HOLD hasta la medianoche (reset diario).")
        return False

    def _get_active_api_entry(self) -> Optional[dict]:
        """Devuelve la entrada activa del pool, rotando si está agotada."""
        today = datetime.now(timezone.utc).date()
        with self._api_lock:
            entry = GROQ_API_POOL[self._api_index]
            label = entry["label"]
            usage = self._api_usage[label]
            if usage["date"] != today:
                usage["count"] = 0
                usage["date"] = today
            if usage["count"] < entry["daily_limit"] and entry["key"]:
                usage["count"] += 1
                return entry
            needs_rotate = True
        # Lock liberado antes de llamar a _rotate_api para evitar deadlock
        if needs_rotate:
            if self._rotate_api():
                return GROQ_API_POOL[self._api_index]
        return None

    def _daily_summary_scheduler(self) -> None:
        """Envía resumen diario a las 11:59 PM cada día."""
        from datetime import timedelta
        while True:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            sleep_secs = (target - now).total_seconds()
            time.sleep(sleep_secs)
            self._send_daily_summary()

    def _send_daily_summary(self) -> None:
        """Construye y envía el resumen del día por Telegram."""
        today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
        with self._daily_trades_lock:
            trades = self._daily_trades[:]
            self._daily_trades.clear()

        if not trades:
            _tg(
                f"Resumen del dia {today}\n"
                f"Sin operaciones hoy.\n"
                f"El bot siguio analizando 10 pares."
            )
            return

        total_usd = sum(t["profit_usd"] for t in trades)
        ganadas = sum(1 for t in trades if t["won"])
        perdidas = len(trades) - ganadas
        mejor = max(trades, key=lambda t: t["profit_usd"])
        peor = min(trades, key=lambda t: t["profit_usd"])
        winrate = (ganadas / len(trades)) * 100

        # Stats de Q-Learning para el reporte
        with self._q_lock:
            q_vals_buy = [(i, self._q_table[i][1]) for i in range(self._q_states)]
        top_estados = sorted(q_vals_buy, key=lambda x: x[1], reverse=True)[:3]
        top_str = " | ".join([f"E{e[0]}={e[1]:.2f}" for e in top_estados if e[1] > 0])
        if not top_str:
            top_str = "aun aprendiendo..."

        # Mejor par por win rate en memoria
        pares_mem = {}
        for t in self._trade_memory:
            p = t["pair"]
            pares_mem.setdefault(p, {"w": 0, "l": 0})
            if t["won"]:
                pares_mem[p]["w"] += 1
            else:
                pares_mem[p]["l"] += 1
        mejor_par_wr = max(pares_mem.items(), key=lambda x: x[1]["w"] / max(x[1]["w"] + x[1]["l"], 1), default=None)
        mejor_par_str = f"{mejor_par_wr[0]} ({mejor_par_wr[1]['w']}W/{mejor_par_wr[1]['l']}L)" if mejor_par_wr else "sin datos"

        signo_total = "+" if total_usd >= 0 else ""

        # Pedir a Groq un análisis del día en lenguaje natural (Opción C)
        analisis_ia = self._get_daily_analysis_from_groq(trades, total_usd, winrate, ganadas, perdidas)

        msg = (
            f"Resumen del dia {today}\n"
            f"Resultado total: {signo_total}${total_usd:.2f}\n"
            f"Operaciones: {len(trades)} ({ganadas} ganadoras {perdidas} perdedoras)\n"
            f"Winrate: {winrate:.0f}%\n"
            f"Mejor trade: {mejor['pair']} +${mejor['profit_usd']:.2f}\n"
            f"Peor trade: {peor['pair']} ${peor['profit_usd']:.2f}\n"
            f"\nAprendizaje Q-Learning:\n"
            f"  Episodios: {self._q_episodes} | Epsilon: {self._q_epsilon:.3f}\n"
            f"  Top estados rentables: {top_str}\n"
            f"  Mejor par historico: {mejor_par_str}"
        )
        if analisis_ia:
            msg += f"\n\nAnalisis IA:\n{analisis_ia}"
        msg += "\nEl bot sigue operando"
        _tg(msg)

    def _get_daily_analysis_from_groq(self, trades: list, total_usd: float, winrate: float, ganadas: int, perdidas: int) -> Optional[str]:
        """Pide a Groq un análisis del día en lenguaje natural. 1 llamada/día."""
        if not self._gemini_client or not trades:
            return None
        try:
            pairs_won = [t["pair"] for t in trades if t["won"]]
            pairs_lost = [t["pair"] for t in trades if not t["won"]]
            signo = "+" if total_usd >= 0 else ""
            prompt = f"""Eres el analista de un bot de trading crypto. Resume el dia en 3 frases cortas y directas en español.

DATOS DEL DIA:
- Trades totales: {len(trades)} ({ganadas} ganados, {perdidas} perdidos)
- Win rate: {winrate:.0f}%
- Resultado: {signo}${total_usd:.2f} USDT
- Pares ganadores: {', '.join(pairs_won[:5]) if pairs_won else 'ninguno'}
- Pares perdedores: {', '.join(pairs_lost[:5]) if pairs_lost else 'ninguno'}
- Regimen de mercado predominante: {self._market_regime}

INSTRUCCIONES: 3 frases maximo. Frase 1: resultado general. Frase 2: que funcionó. Frase 3: que mejorar mañana. Sin emojis. Sin formato especial."""

            api_entry = self._get_active_api_entry()
            if not api_entry:
                return None
            raw = self._call_llm(api_entry, prompt)
            self._last_gemini_call = time.time()
            return raw.strip()[:400]
        except Exception as e:
            logger.debug(f"[DAILY-IA] Error en analisis diario: {e}")
            return None

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """RSI calculado con pandas puro, sin TA-Lib."""
        delta = series.diff()
        gain = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_ema(series: pd.Series, period: int) -> pd.Series:
        """EMA calculada con pandas puro."""
        return series.ewm(span=period, adjust=False).mean()

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Calcula indicadores técnicos que se pasan a Gemini como contexto."""
        dataframe["rsi"] = self._calc_rsi(dataframe["close"], 14)
        dataframe["ema20"] = self._calc_ema(dataframe["close"], self.ema_fast.value)
        dataframe["ema50"] = self._calc_ema(dataframe["close"], self.ema_slow.value)
        dataframe["ema_signal"] = (
            dataframe["ema20"] > dataframe["ema50"]
        ).map({True: "BULL", False: "BEAR"})
        dataframe["volume_ratio"] = (
            dataframe["volume"] / dataframe["volume"].rolling(20).mean()
        )
        dataframe["price_vs_ema20"] = (
            (dataframe["close"] - dataframe["ema20"]) / dataframe["ema20"] * 100
        )
        # MACD (12, 26, 9)
        ema12 = self._calc_ema(dataframe["close"], 12)
        ema26 = self._calc_ema(dataframe["close"], 26)
        dataframe["macd"] = ema12 - ema26
        dataframe["macd_signal"] = self._calc_ema(dataframe["macd"], 9)
        dataframe["macd_hist"] = dataframe["macd"] - dataframe["macd_signal"]
        # Bollinger Bands (20, 2)
        bb_mid = dataframe["close"].rolling(20).mean()
        bb_std = dataframe["close"].rolling(20).std()
        dataframe["bb_upper"] = bb_mid + 2 * bb_std
        dataframe["bb_lower"] = bb_mid - 2 * bb_std
        dataframe["bb_mid"] = bb_mid
        dataframe["bb_pct"] = (dataframe["close"] - dataframe["bb_lower"]) / (dataframe["bb_upper"] - dataframe["bb_lower"]) * 100
        # EMA200 — soporte/resistencia institucional
        dataframe["ema200"] = self._calc_ema(dataframe["close"], 200)
        dataframe["ema200_signal"] = (
            dataframe["close"] > dataframe["ema200"]
        ).map({True: "ABOVE", False: "BELOW"})
        # ATR(14) — volatilidad real para stop-loss dinámico
        high_low = dataframe["high"] - dataframe["low"]
        high_close = (dataframe["high"] - dataframe["close"].shift()).abs()
        low_close = (dataframe["low"] - dataframe["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        dataframe["atr"] = true_range.ewm(span=14, adjust=False).mean()
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"] * 100
        # Divergencia RSI: precio sube pero RSI baja = señal de salida
        rsi_prev = dataframe["rsi"].shift(3)
        close_prev = dataframe["close"].shift(3)
        dataframe["rsi_divergence"] = (
            (dataframe["close"] > close_prev) & (dataframe["rsi"] < rsi_prev - 5)
        ).map({True: "BEARISH_DIV", False: "OK"})

        # Stochastic RSI (14,3,3) — momentum sobrecompra/sobreventa más sensible que RSI
        rsi_min = dataframe["rsi"].rolling(14).min()
        rsi_max = dataframe["rsi"].rolling(14).max()
        stoch_rsi_k = (dataframe["rsi"] - rsi_min) / (rsi_max - rsi_min + 1e-10) * 100
        dataframe["stoch_rsi_k"] = stoch_rsi_k.rolling(3).mean()
        dataframe["stoch_rsi_d"] = dataframe["stoch_rsi_k"].rolling(3).mean()

        # OBV (On Balance Volume) — confirma si el volumen apoya la tendencia
        obv = (pd.Series(
            [0] + [v if c > p else (-v if c < p else 0)
                   for c, p, v in zip(dataframe["close"][1:], dataframe["close"][:-1], dataframe["volume"][1:])],
            index=dataframe.index
        )).cumsum()
        dataframe["obv"] = obv
        dataframe["obv_signal"] = (obv > obv.rolling(10).mean()).map({True: "BULL", False: "BEAR"})

        # Williams %R (14) — otro oscilador de sobrecompra/sobreventa
        highest_high = dataframe["high"].rolling(14).max()
        lowest_low = dataframe["low"].rolling(14).min()
        dataframe["williams_r"] = (highest_high - dataframe["close"]) / (highest_high - lowest_low + 1e-10) * -100

        # CCI (20) — Commodity Channel Index, detecta reversiones
        tp = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        tp_ma = tp.rolling(20).mean()
        tp_std = tp.rolling(20).std()
        dataframe["cci"] = (tp - tp_ma) / (0.015 * tp_std + 1e-10)

        # Soporte y Resistencia multicapa: 20, 50 (swing) y 100 velas (institucional)
        dataframe["support_20"] = dataframe["low"].rolling(20).min()
        dataframe["resistance_20"] = dataframe["high"].rolling(20).max()
        dataframe["support_50"] = dataframe["low"].rolling(50).min()
        dataframe["resistance_50"] = dataframe["high"].rolling(50).max()
        dataframe["support_100"] = dataframe["low"].rolling(100).min()
        dataframe["resistance_100"] = dataframe["high"].rolling(100).max()
        # Usar el soporte/resistencia más cercano al precio actual
        dataframe["support"] = dataframe[["support_20", "support_50"]].max(axis=1)
        dataframe["resistance"] = dataframe[["resistance_20", "resistance_50"]].min(axis=1)
        dataframe["dist_support_pct"] = (dataframe["close"] - dataframe["support"]) / dataframe["close"] * 100
        dataframe["dist_resistance_pct"] = (dataframe["resistance"] - dataframe["close"]) / dataframe["close"] * 100
        # Niveles institucionales (100 velas) para referencia en el prompt
        dataframe["dist_support_100_pct"] = (dataframe["close"] - dataframe["support_100"]) / dataframe["close"] * 100
        dataframe["dist_resistance_100_pct"] = (dataframe["resistance_100"] - dataframe["close"]) / dataframe["close"] * 100

        # Número redondo más cercano (psicología del mercado)
        def nearest_round(price):
            if price <= 0:
                return 0.0
            if price < 1.0:
                # Para precios < 1 usar multiplos de 0.1, 0.01 según magnitud
                magnitude = 10 ** (math.floor(math.log10(price)))
            else:
                magnitude = 10 ** (len(str(int(price))) - 1)
            rounded = round(price / magnitude) * magnitude
            dist_pct = abs(price - rounded) / price * 100
            return round(dist_pct, 2)
        dataframe["dist_round_number_pct"] = dataframe["close"].apply(nearest_round)

        # Patrones de velas japonesas (últimas 3 velas)
        def detect_candle_pattern(df):
            patterns = []
            for i in range(len(df)):
                if i < 2:
                    patterns.append("NEUTRAL")
                    continue
                o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
                po, ph, pl, pc = df["open"].iloc[i-1], df["high"].iloc[i-1], df["low"].iloc[i-1], df["close"].iloc[i-1]
                po2, pc2 = df["open"].iloc[i-2], df["close"].iloc[i-2]
                body = abs(c - o)
                prev_body = abs(pc - po)
                body2 = abs(pc2 - po2)
                upper_wick = h - max(o, c)
                lower_wick = min(o, c) - l
                # Morning Star — suelo de 3 velas (bajista + pequeña + alcista)
                if (pc2 < po2 and body2 > 0 and
                        body < (h - l) * 0.35 and
                        c > o and
                        c > (po2 + pc2) / 2):
                    patterns.append("MORNING_STAR")
                # Evening Star — techo de 3 velas (alcista + pequeña + bajista)
                elif (pc2 > po2 and body2 > 0 and
                        body < (h - l) * 0.35 and
                        c < o and
                        c < (po2 + pc2) / 2):
                    patterns.append("EVENING_STAR")
                # Hammer (martillo) — reversión alcista
                elif lower_wick > body * 2 and upper_wick < body * 0.5 and c > o:
                    patterns.append("HAMMER")
                # Shooting star — reversión bajista
                elif upper_wick > body * 2 and lower_wick < body * 0.5 and c < o:
                    patterns.append("SHOOTING_STAR")
                # Engulfing alcista
                elif c > o and pc < po and c > po and o < pc:
                    patterns.append("BULL_ENGULF")
                # Engulfing bajista
                elif c < o and pc > po and c < po and o > pc:
                    patterns.append("BEAR_ENGULF")
                # Doji (indecisión)
                elif body < (h - l) * 0.1:
                    patterns.append("DOJI")
                else:
                    patterns.append("NEUTRAL")
            return patterns
        dataframe["candle_pattern"] = detect_candle_pattern(dataframe)

        # Fibonacci retracement — niveles 38.2%, 50%, 61.8% de las últimas 50 velas
        high50 = dataframe["high"].rolling(50).max()
        low50 = dataframe["low"].rolling(50).min()
        fib_range = high50 - low50
        dataframe["fib_382"] = high50 - fib_range * 0.382
        dataframe["fib_500"] = high50 - fib_range * 0.500
        dataframe["fib_618"] = high50 - fib_range * 0.618
        # ¿Está el precio cerca de algún nivel Fibonacci? (<0.5%)
        def fib_zone(row):
            price = row["close"]
            for level, name in [(row["fib_382"], "FIB38"), (row["fib_500"], "FIB50"), (row["fib_618"], "FIB61")]:
                if abs(price - level) / price < 0.005:
                    return name
            return "NONE"
        dataframe["fib_zone"] = dataframe.apply(fib_zone, axis=1)

        # ADX (14) — fuerza de la tendencia (no dirección)
        # +DI y -DI para el cálculo completo de ADX
        high_diff = dataframe["high"].diff()
        low_diff = dataframe["low"].diff()
        plus_dm = high_diff.where((high_diff > 0) & (high_diff > -low_diff), 0.0)
        minus_dm = (-low_diff).where((-low_diff > 0) & (-low_diff > high_diff), 0.0)
        atr14 = dataframe["atr"]
        plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr14.replace(0, 1e-10))
        minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr14.replace(0, 1e-10))
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
        dataframe["adx"] = dx.ewm(span=14, adjust=False).mean()
        dataframe["adx_trend"] = dataframe["adx"].apply(
            lambda x: "FUERTE" if x > 25 else "LATERAL"
        )

        # MFI (14) — Money Flow Index: RSI ponderado por volumen
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        money_flow = typical_price * dataframe["volume"]
        tp_prev = typical_price.shift(1)
        pos_flow = money_flow.where(typical_price > tp_prev, 0.0).rolling(14).sum()
        neg_flow = money_flow.where(typical_price < tp_prev, 0.0).rolling(14).sum()
        mfi_ratio = pos_flow / neg_flow.replace(0, 1e-10)
        dataframe["mfi"] = 100 - (100 / (1 + mfi_ratio))
        dataframe["mfi_signal"] = dataframe["mfi"].apply(
            lambda x: "SOBREVENTA" if x < 20 else ("SOBRECOMPRA" if x > 80 else "NEUTRO")
        )

        # VWAP — indicador institucional (precio ponderado por volumen)
        # Ventana rodante 288 velas = 1 día en 5m (evita lookahead bias del cumsum total)
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        tp_vol = (typical_price * dataframe["volume"]).rolling(288, min_periods=1).sum()
        vol_sum = dataframe["volume"].rolling(288, min_periods=1).sum()
        dataframe["vwap"] = tp_vol / vol_sum.replace(0, 1e-10)
        dataframe["dist_vwap_pct"] = (dataframe["close"] - dataframe["vwap"]) / dataframe["vwap"] * 100

        # Bollinger Band Squeeze — bandas comprimidas = explosion inminente
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_mid"] * 100
        dataframe["bb_squeeze"] = dataframe["bb_width"] < dataframe["bb_width"].rolling(20).mean() * 0.6

        # Divergencia alcista RSI — precio hace minimo mas bajo pero RSI no = suelo proximo
        dataframe["rsi_bull_div"] = (
            (dataframe["close"] < dataframe["close"].shift(3)) &
            (dataframe["rsi"] > dataframe["rsi"].shift(3) + 3)
        ).map({True: "BULL_DIV", False: "OK"})

        # EMA200 — tendencia macro institucional (usada en _detect_regime)
        dataframe["ema200"] = self._calc_ema(dataframe["close"], 200)
        dataframe["ema200_signal"] = (dataframe["close"] > dataframe["ema200"]).map({True: "ABOVE", False: "BELOW"})

        dataframe["gemini_buy"] = 0
        dataframe["gemini_sell"] = 0
        dataframe["gemini_confidence"] = 0.0
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Llama a Gemini para la última vela y guarda la decisión."""
        pair = metadata["pair"]
        logger.info(f"[ENTRY] populate_entry_trend | {pair} | velas={len(dataframe)}")
        if len(dataframe) == 0:
            return dataframe

        # Autopausa: si el bot está en pausa, no abrir nuevos trades
        if time.time() < self._autopause_until:
            mins_left = (self._autopause_until - time.time()) / 60
            logger.info(f"[AUTOPAUSA] Bot en pausa, faltan {mins_left:.0f} min | {self._autopause_reason}")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # Detectar régimen de mercado y actualizar multiplicadores
        regime = self._detect_regime(dataframe)

        # Régimen CAOS o BAJISTA_VOLATIL: no abrir nuevas posiciones
        if self._regime_stake_mult == 0.0:
            logger.info(f"[REGIME] {regime} — no se abren trades en este régimen")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 3: blacklist dinámica (3 losses en 24h = bloqueado) ────────
        now_ts = time.time()
        pair_losses_24h = [t for t in self._daily_losses.get(pair, []) if now_ts - t < 86400]
        self._daily_losses[pair] = pair_losses_24h
        if len(pair_losses_24h) >= self._MAX_DAILY_LOSSES:
            logger.debug(f"[BLACKLIST-DIN] {pair} bloqueado: {len(pair_losses_24h)} losses en 24h")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 2: cooldown 2h tras pérdida ───────────────────────────────
        loss_cooldown_until = self._loss_cooldown.get(pair, 0)
        if now_ts < loss_cooldown_until:
            mins_left = (loss_cooldown_until - now_ts) / 60
            logger.debug(f"[LOSS-COOLDOWN] {pair} en cooldown, faltan {mins_left:.0f} min")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Umbrales adaptativos según régimen (estilo NostalgiaForInfinityX7) ──
        # Mercado alcista calmado → más permisivo (RSI<65)
        # Transición / rango    → equilibrado   (RSI<55)
        # Bajista / volátil     → estricto       (RSI<40, solo capitulaciones)
        if regime in ("TENDENCIA_ALCISTA_CALMADA", "TENDENCIA_ALCISTA_NORMAL"):
            rsi_umbral, macd_req, f2_score_min = 60, False, 2
        elif regime in ("TENDENCIA_ALCISTA_VOLATIL", "TRANSICION", "RANGO_ESTRECHO"):
            rsi_umbral, macd_req, f2_score_min = 55, True, 3
        else:  # BAJISTA_*, CAOS, UNKNOWN
            rsi_umbral, macd_req, f2_score_min = 50, True, 4

        # ── NIVEL 1: prefiltro open source (RSI + MACD alcista + EMA) ─────────
        # Basado en EnhancedIndicatorStrategy y NostalgiaForInfinityX7 (GitHub)
        last = dataframe.iloc[-1]
        prev = dataframe.iloc[-2]
        macd_alcista = last['macd_hist'] > 0 or (last['macd_hist'] > prev['macd_hist'] and last['macd_hist'] > -0.0001)
        ema_ok = (last['ema20'] > last['ema50']) or (last['rsi'] < rsi_umbral * 0.85)
        macd_ok = macd_alcista if macd_req else True
        pass_l1 = (last['rsi'] < rsi_umbral) and macd_ok and ema_ok
        logger.info(f"[NIVEL1] {pair} | RSI={last['rsi']:.1f}(umbral={rsi_umbral},{regime}) | MACD_ok={macd_alcista}(req={macd_req}) | EMA_ok={ema_ok} | PASS={pass_l1}")
        if not pass_l1:
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 1: volumen vela actual ─────────────────────────────────
        vol_mean_20 = dataframe['volume'].rolling(20).mean().iloc[-1]
        if vol_mean_20 > 0 and last['volume'] < vol_mean_20 * 0.2:
            logger.debug(f"[VOL-FILTER] {pair} vela sin volumen ({last['volume']:.0f} < {vol_mean_20*0.2:.0f})")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 2: confirmacion RSI (umbral dinámico según régimen) ───────
        prev = dataframe.iloc[-2]
        rsi_confirma = last['rsi'] < (rsi_umbral * 0.7) or last['rsi'] < prev['rsi']
        score_previo = sum([
            int(last['rsi'] < 48),
            int(last['stoch_rsi_k'] < 40),
            int(last['bb_pct'] < 35),
            int(last['macd_hist'] > 0),
            int(last['volume_ratio'] > 1.2),
        ])
        if not rsi_confirma and score_previo < f2_score_min:
            logger.debug(f"[F2-RSI] {pair} RSI no confirma y score bajo ({score_previo}/{f2_score_min}) regimen={regime} — skip")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 3: no entrar tras vela bajista grande ───────────────────────
        # En mercado alcista calmado se omite — NFI permite entradas post-rechazo
        prev_body = abs(prev['close'] - prev['open'])
        prev_range = (prev['high'] - prev['low']) if (prev['high'] - prev['low']) > 0 else 1e-10
        f3_activo = regime not in ("TENDENCIA_ALCISTA_CALMADA", "TENDENCIA_ALCISTA_NORMAL")
        if f3_activo and prev['close'] < prev['open'] and prev_body > prev_range * 0.6:
            logger.debug(f"[F3-CANDLE] {pair} vela bajista grande ({prev_body/prev_range*100:.0f}%) regimen={regime} — esperando confirmacion")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 4: soporte real bajo SL — buffer contra wicks ────────────
        dist_to_support_pct = (last['close'] - last['support_20']) / last['close'] * 100
        if dist_to_support_pct < 0.3:
            logger.debug(f"[F4-SL] {pair} soporte demasiado cerca {dist_to_support_pct:.2f}% — riesgo wick al SL")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── Filtro 5: momentum rebote proxima vela ────────────────────────────
        v1 = dataframe.iloc[-4]  # 3 velas atras
        v2 = dataframe.iloc[-3]  # 2 velas atras
        v3 = dataframe.iloc[-2]  # vela anterior
        momentum_rebote = sum([
            int(v3['close'] > v2['close']),                            # v_anterior cerro arriba
            int(v3['volume'] > v2['volume']),                          # volumen creciendo
            int(v2['low'] < v1['low']),                                # nuevo minimo (capitulacion)
            int(float(last['rsi']) > float(v3['rsi'])),                # RSI subiendo (last vs v_anterior)
            int(float(last['macd_hist']) > float(v3['macd_hist'])),    # MACD mejorando
        ])
        # En mercado alcista calmado basta 0/5 (cualquier vela es válida) — NFI
        f5_min = 0 if regime in ("TENDENCIA_ALCISTA_CALMADA", "TENDENCIA_ALCISTA_NORMAL") else 1
        if momentum_rebote < f5_min:
            logger.debug(f"[F5-MOMENTUM] {pair} sin senales de rebote ({momentum_rebote}/5) regimen={regime} — skip")
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # ── NIVEL 2: scoring técnico (gratis, local) ────────────────────────
        # Suma puntos — máximo ~13 pts
        score = 0
        score += 2 if last['rsi'] < 40 else (1 if last['rsi'] < 48 else 0)
        score += 2 if last['stoch_rsi_k'] < 30 else (1 if last['stoch_rsi_k'] < 40 else 0)
        score += 2 if last['bb_pct'] < 25 else (1 if last['bb_pct'] < 35 else 0)
        score += 2 if (last['macd_hist'] > 0 and last['volume_ratio'] > 1.0) else (1 if last['macd_hist'] > 0 else 0)
        score += 1 if last['volume_ratio'] > 1.5 else 0
        score += 1 if last['rsi'] > 35 else 0
        score += 2 if last['candle_pattern'] in ['HAMMER', 'BULL_ENGULF', 'MORNING_STAR'] else 0
        score += 2 if dist_to_support_pct < 0.5 else (1 if dist_to_support_pct < 1.5 else 0)
        score += 1 if momentum_rebote >= 3 else 0
        score += 1 if last.get('ema_signal') == 'ABOVE' else 0
        score += 2 if last.get('rsi_bull_div') == 'BULL_DIV' else 0
        score += 1 if last.get('dist_vwap_pct', 0) < -1.0 else 0
        score += 1 if (last.get('bb_squeeze', False) and last['macd_hist'] > 0) else 0

        logger.debug(f"[SCORE] {pair} | score={score}/17")

        if score < 2:
            # Sin señal suficiente: skip
            dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
            return dataframe

        # Codificar estado para Q-Learning
        q_state = self._encode_state(dataframe)

        # Score hint dinámico: la IA recibe contexto según la fuerza del setup
        if score >= 8:
            score_hint = f"SCORE_LOCAL={score}/17 -> SETUP MUY FUERTE. Entra salvo peligro claro (DivRSI=BEARISH o HoraBaja=SI o vela bajista o CAOS)."
        elif score >= 5:
            score_hint = f"SCORE_LOCAL={score}/17 -> Setup moderado-fuerte. Entra si la mayoria de indicadores son alcistas."
        else:
            score_hint = f"SCORE_LOCAL={score}/17 -> Setup debil. Solo entra si hay señal clara de rebote."

        logger.info(f"[GROQ-CALL] {pair} | score={score}/17 — llamando a Groq")
        decision = self._get_gemini_decision(pair, dataframe, score_hint=score_hint)

        if decision:
            logger.info(f"[GROQ-RESP] {pair} | accion={decision.get('accion')} | confianza={decision.get('confianza')} | razon={decision.get('razon','N/A')[:60]}")

        if decision and decision.get("accion") == "BUY":
            confidence = decision.get("confianza", 0)
            # Guardar el RSI actual en la decisión para la memoria de aprendizaje
            decision["rsi"] = float(dataframe["rsi"].iloc[-1])
            decision["q_state"] = q_state
            if confidence >= MIN_CONFIDENCE:
                dataframe.loc[dataframe.index[-1], "gemini_buy"] = 1
                dataframe.loc[dataframe.index[-1], "gemini_confidence"] = confidence
                logger.info(
                    f"[BUY] GEMINI BUY | {pair} | "
                    f"Confianza: {confidence}% | Régimen: {regime} | "
                    f"Q-estado: {q_state} | Razon: {decision.get('razon', 'N/A')}"
                )

        dataframe.loc[dataframe["gemini_buy"] == 1, "enter_long"] = 1
        return dataframe

    def custom_stake_amount(
        self, current_time, current_rate, proposed_stake,
        min_stake, max_stake, leverage, entry_tag, side, **kwargs
    ) -> float:
        """Escala el capital según la confianza de Gemini.
        Incluye protección drawdown diario y cooldown tras stop-loss.
        """
        pair = kwargs.get("pair", "")

        # Reset diario de pérdidas
        today = datetime.now(timezone.utc).date()
        if self._daily_loss_date != today:
            self._daily_loss_usd = 0.0
            self._daily_loss_date = today

        # Protección drawdown diario: si se perdió >5% del balance, no operar más hoy
        try:
            balance = self.wallets.get_available_capital()
        except Exception:
            balance = 45.0  # fallback demo
        max_daily_loss = balance * 0.05
        if self._daily_loss_usd >= max_daily_loss:
            logger.warning(
                f"[RISK] Drawdown diario ${self._daily_loss_usd:.2f} >= limite ${max_daily_loss:.2f}. "
                f"Sin nuevas entradas hasta mañana."
            )
            _tg(
                f"PROTECCION ACTIVADA\n"
                f"Perdida del dia: ${self._daily_loss_usd:.2f}\n"
                f"Limite 5% alcanzado. Sin nuevas entradas hasta mañana."
            )
            return 0.0

        # Cooldown tras stop-loss: esperar 15 min antes de reentrar al mismo par
        cooldown_ts = self._stoploss_cooldown.get(pair, 0)
        mins_restantes = (900 - (time.time() - cooldown_ts)) / 60
        if time.time() - cooldown_ts < 900:
            logger.info(f"[COOLDOWN] {pair} en cooldown, faltan {mins_restantes:.0f} min")
            return 0.0

        # Capital escalado por nivel de confianza de Groq/Gemini
        cache_key = next((k for k in self._gemini_decisions if k.startswith(pair + "_")), None)
        confidence = self._gemini_decisions[cache_key].get("confianza", 0) if cache_key else 0

        if confidence >= 85:
            base_pct = 0.18   # excelente — 18% (compound agresivo)
            nivel_txt = "[EXCELENTE]"
        elif confidence >= 65:
            base_pct = 0.15   # buena/normal — 15% fijo (tu lógica: SL limita pérdida real)
            nivel_txt = "[BUENA]"
        else:
            base_pct = 0.10   # débil — 10% reducido
            nivel_txt = "[NORMAL]"

        stake = min(max(balance * base_pct, min_stake), max_stake)
        # Ajustar stake según régimen de mercado
        stake = round(stake * self._regime_stake_mult, 2)
        stake = max(stake, min_stake) if stake > 0 else 0.0
        logger.info(f"[STAKE] {nivel_txt} {stake:.2f}$ ({base_pct*100:.0f}% balance) | {pair} | conf={confidence}% | mult={self._regime_stake_mult}")
        return stake

    def custom_stoploss(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, after_fill: bool, **kwargs
    ) -> float:
        """Stop loss dinámico basado en ATR × multiplicador según volatilidad y régimen."""
        # Obtener ATR% real del par desde decisión cacheada (guardado en _get_gemini_decision)
        last_decision = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        atr_pct = last_decision.get("atr_pct", 1.0)  # % de ATR real, default 1%
        regime = self._market_regime
        if "CALMADA" in regime or regime == "RANGO_TRANQUILO":
            multiplier = 1.2  # stop más ajustado en calma
        elif "VOLATIL" in regime or "CAOS" in regime:
            multiplier = 2.0  # stop más amplio en volatilidad
        elif "TRANSICION" in regime:
            multiplier = 1.5
        else:
            multiplier = 1.5  # default neutro

        # Calcular stop distance: ATR% * multiplicador + buffer 0.3% anti-wick
        stop_distance = max(0.012, min(0.030, (atr_pct / 100) * multiplier + 0.003))
        # Si ya estamos en profit > 2%, activar trailing más ajustado
        if current_profit > 0.02:
            return -0.005  # trailing muy ajustado una vez en ganancia
        return -stop_distance

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Señal de salida basada en RSI sobrecomprado o decisión cacheada de Gemini."""
        pair = metadata["pair"]
        cache_key = f"{pair}_{dataframe.index[-1]}"
        decision = self._gemini_decisions.get(cache_key)

        # Bug fix: limpiar decisiones viejas >2h para evitar fuga de memoria
        now_ts = time.time()
        cutoff = now_ts - 7200
        stale = [k for k, v in self._gemini_decisions.items()
                 if v.get("_ts", now_ts) < cutoff]
        for k in stale:
            del self._gemini_decisions[k]

        # Bug fix: RSI sobrecomprado SOLO en la última vela, no en todas las históricas
        last_rsi = float(dataframe["rsi"].iloc[-1])
        if last_rsi > self.rsi_sell_threshold.value:
            dataframe.loc[dataframe.index[-1], "gemini_sell"] = 1

        # Evening Star — techo de 3 velas detectado = salir antes de la caida
        last_candle = dataframe["candle_pattern"].iloc[-1]
        if last_candle == "EVENING_STAR":
            dataframe.loc[dataframe.index[-1], "gemini_sell"] = 1
            logger.info(f"[SELL] EVENING_STAR detectado en {pair} — salida por techo")

        if decision and decision.get("accion") in ["SELL", "CLOSE"]:
            dataframe.loc[dataframe.index[-1], "gemini_sell"] = 1
            logger.info(
                f"[SELL] GEMINI SELL | {pair} | "
                f"Razon: {decision.get('razon', 'N/A')}"
            )

        dataframe.loc[dataframe["gemini_sell"] == 1, "exit_long"] = 1
        return dataframe

    def _get_gemini_exit_decision(self, pair: str, current_profit: float, trade_duration_min: float) -> Optional[str]:
        """Pregunta a Groq si conviene cerrar el trade ahora o esperar más.
        Solo se llama cuando hay profit >0.5% o pérdida >0.8% para ahorrar llamadas.
        Retorna 'cerrar' si la IA recomienda salir, None si recomienda esperar.
        """
        if not self._gemini_client:
            return None

        elapsed = time.time() - self._last_gemini_call
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

        try:
            last_decision = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
            atr_pct = last_decision.get("atr_pct", 1.0)
            regime = self._market_regime
            profit_pct = round(current_profit * 100, 2)
            signo = "+" if profit_pct >= 0 else ""

            prompt = f"""Eres un trader crypto. Trade abierto en {pair}. RESPONDE SOLO JSON.

ESTADO DEL TRADE:
- Profit actual: {signo}{profit_pct}%
- Duracion: {trade_duration_min:.0f} minutos
- ATR (volatilidad): {atr_pct:.2f}%
- Regimen actual: {regime}

PREGUNTA: ¿Cierro el trade ahora o espero más?

REGLAS:
- Cierra si: profit > ATR*1.5 y hay señal de reversión
- Cierra si: perdida > 0.8% y regime BAJISTA
- Cierra si: duracion > 90min y profit < 0.5%
- Espera si: profit creciendo y regime ALCISTA
- Espera si: profit < 1.0% y trade < 30min

JSON: {{"accion":"CERRAR","razon":"max8palabras"}} o {{"accion":"ESPERAR","razon":"max8palabras"}}"""

            api_entry = self._get_active_api_entry()
            if not api_entry:
                return None

            raw = self._call_llm(api_entry, prompt)
            self._last_gemini_call = time.time()
            raw = raw.replace("```json", "").replace("```", "").strip()
            decision = json.loads(raw)
            accion = decision.get("accion", "ESPERAR").upper()
            razon = decision.get("razon", "")[:50]
            logger.info(f"[EXIT-IA] {pair} | {accion} | profit={signo}{profit_pct}% | razon={razon}")
            return "ia_exit" if accion == "CERRAR" else None

        except Exception as e:
            logger.debug(f"[EXIT-IA] Error en decision de salida: {e}")
            return None

    def custom_exit(self, pair: str, trade, current_time, current_rate: float,
                    current_profit: float, **kwargs) -> Optional[str]:
        """TP dinamico + IA decide salida cuando hay señal clara."""
        last_decision = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        confidence = last_decision.get("confianza", 0)
        trade_duration = (current_time - trade.open_date_utc).total_seconds() / 60

        # TP alto para trades de alta confianza
        if confidence >= 85:
            if trade_duration <= 60 and current_profit >= 0.035:
                logger.info(f"[TP-ALTO] {pair} | conf={confidence}% | profit={current_profit*100:.2f}% >= 3.5%")
                return "tp_alta_confianza"
            elif trade_duration <= 120 and current_profit >= 0.025:
                return None  # dejar que minimal_roi normal lo cierre

        # IA decide salida: solo consultar si hay profit relevante o pérdida creciente
        # Umbral bajo para no desperdiciar llamadas en trades neutros
        profit_pct = current_profit * 100
        consultar_ia = (
            (profit_pct >= 0.8 and trade_duration >= 15) or   # profit >0.8% y ya lleva 15min
            (profit_pct <= -0.7 and trade_duration >= 10)      # perdida >0.7% tras 10min
        )
        if consultar_ia:
            exit_signal = self._get_gemini_exit_decision(pair, current_profit, trade_duration)
            if exit_signal:
                return exit_signal

        return None

    def _get_gemini_decision(
        self, pair: str, dataframe: DataFrame, score_hint: str = ""
    ) -> Optional[dict]:
        """
        Llama a Gemini API con el contexto del mercado.
        Respeta rate limit: máx 1 llamada por vela por par.
        Fallback: retorna HOLD si hay cualquier error.
        """
        if not self._gemini_client:
            return {"accion": "HOLD", "confianza": 0, "razon": "Gemini no configurado"}

        cache_key = f"{pair}_{dataframe.index[-1]}"
        if cache_key in self._gemini_decisions:
            return self._gemini_decisions[cache_key]

        elapsed = time.time() - self._last_gemini_call
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

        try:
            last = dataframe.iloc[-1]

            # Detectar momentum: precio de las últimas 3 velas
            closes = dataframe['close'].tail(4).values
            momentum = "SUBIENDO" if closes[-1] > closes[-2] > closes[-3] else ("BAJANDO" if closes[-1] < closes[-2] < closes[-3] else "LATERAL")

            macd_trend = "ALCISTA" if last['macd_hist'] > 0 else "BAJISTA"
            bb_pos = "SOBRECOMPRA" if last['bb_pct'] > 80 else ("SOBREVENTA" if last['bb_pct'] < 20 else "MEDIO")
            news, news_sentiment = _fetch_crypto_news(pair)
            fg_value, fg_label = _fetch_fear_greed()
            trend_1h, rsi_1h = self._fetch_1h_trend(pair)
            reddit_score, reddit_mentions = _fetch_reddit_sentiment(pair)
            trending_coins = _fetch_trending_coins()
            coin_symbol = pair.split("/")[0]
            is_trending = "SI" if coin_symbol in trending_coins else "NO"
            # Sentiment compuesto: promedio de FG, noticias y reddit
            social_avg = int((news_sentiment + reddit_score) / 2)
            social_label = "BULLISH" if social_avg > 60 else ("BEARISH" if social_avg < 40 else "NEUTRAL")

            # Hora UTC — evitar operar entre 23:00-04:00 UTC (caída nocturna ampliada)
            hora_utc = datetime.now(timezone.utc).hour
            hora_peligro = "SI" if (hora_utc >= 23 or hora_utc < 4) else "NO"

            # Memoria activa: aprender de errores por par específico
            pair_trades = [t for t in self._trade_memory if t["pair"] == pair]
            losses = [t for t in pair_trades if not t["won"]]
            wins = [t for t in pair_trades if t["won"]]
            memory_ctx = ""
            if pair_trades:
                win_rate = len(wins) / len(pair_trades) * 100
                memory_ctx = f" Historial {pair}: {len(wins)}W/{len(losses)}L ({win_rate:.0f}% WR)"
                if losses:
                    last_loss = losses[-1]
                    memory_ctx += f" UltimaLoss: RSI={last_loss.get('rsi', '?')} conf={last_loss.get('confianza', '?')}%"
                    if len(losses) >= 2 and losses[-2].get('rsi'):
                        memory_ctx += f" PATRON_PERDIDA: evitar RSI>{min(l.get('rsi',99) for l in losses[-3:] if l.get('rsi'))}"

            rsi_status = "SOBRECOMPRADO" if last['rsi'] > 70 else ("SOBREVENTA" if last['rsi'] < 30 else "OK")
            stoch_status = "SOBRECOMPRADO" if last['stoch_rsi_k'] > 80 else ("SOBREVENTA" if last['stoch_rsi_k'] < 20 else "OK")
            cci_status = "SOBRECOMPRADO" if last['cci'] > 100 else ("SOBREVENTA" if last['cci'] < -100 else "NEUTRO")
            wr_status = "SOBRECOMPRADO" if last['williams_r'] > -20 else ("SOBREVENTA" if last['williams_r'] < -80 else "NEUTRO")

            # Q-Learning hint: acción preferida según experiencia acumulada
            q_state_now = self._encode_state(dataframe)
            with self._q_lock:
                q_vals = self._q_table[q_state_now]
            q_best_action = self._q_actions[q_vals.index(max(q_vals))]
            q_confidence = max(q_vals)
            q_hint = f"Q-Learning recomienda {q_best_action} (valor={q_confidence:.2f}, episodios={self._q_episodes})"

            adx_status = "FUERTE" if last['adx'] > 40 else ("TENDENCIA" if last['adx'] > 25 else "LATERAL")
            mfi_status = last['mfi_signal']

            prompt = f"""Eres un trader crypto. Par: {pair}. RESPONDE SOLO JSON, sin texto adicional.

{score_hint}
INDICADORES: RSI={last['rsi']:.0f} MACD={macd_trend} StochRSI={last['stoch_rsi_k']:.0f} Vol={last['volume_ratio']:.1f}x BB={last['bb_pct']:.0f}% Vela={last['candle_pattern']}
TENDENCIA: Regimen={self._market_regime} EMA50={last['ema_signal']} EMA200={last['ema200_signal']} 1H={trend_1h} RSI1H={rsi_1h:.0f}
NIVELES: Soporte={last['dist_support_pct']:.1f}%abajo Resistencia={last['dist_resistance_pct']:.1f}%arriba ATR={last['atr_pct']:.2f}%
MERCADO: FG={fg_value}[{fg_label}] Social={social_label} Trending={is_trending}
PELIGRO: DivRSI={last['rsi_divergence']} HoraBaja={hora_peligro}{' | ' + memory_ctx if memory_ctx else ''}

VETO_OBLIGATORIO (responde HOLD si cualquiera): DivRSI=BEARISH_DIV | HoraBaja=SI | Vela=SHOOTING_STAR o BEAR_ENGULF | Regimen=CAOS_VOLATIL | Vol<0.3x
VENTA (responde SELL si): RSI>75 y MACD=BAJISTA | StochRSI>85 y MFI>80

Sigue el SCORE_LOCAL como guia principal. Si no hay VETO activo, prioriza BUY.
JSON: {{"accion":"BUY","confianza":65,"razon":"max10palabras"}}"""

            api_entry = self._get_active_api_entry()
            if not api_entry:
                return {"accion": "HOLD", "confianza": 0, "razon": "Todas las APIs agotadas"}

            raw = self._call_llm(api_entry, prompt)
            self._last_gemini_call = time.time()
            raw = raw.replace("```json", "").replace("```", "").strip()
            # Intentar parsear JSON, si falla intentar extraer con regex
            try:
                decision = json.loads(raw)
            except json.JSONDecodeError:
                import re
                accion_m = re.search(r'"accion"\s*:\s*"(BUY|SELL|HOLD|CLOSE)"', raw, re.IGNORECASE)
                conf_m = re.search(r'"confianza"\s*:\s*(\d+)', raw)
                razon_m = re.search(r'"razon"\s*:\s*"([^"]{1,80})', raw)
                if accion_m:
                    decision = {
                        "accion": accion_m.group(1).upper(),
                        "confianza": int(conf_m.group(1)) if conf_m else 50,
                        "razon": razon_m.group(1) if razon_m else "parsed",
                    }
                else:
                    raise

            if "accion" not in decision:
                raise ValueError("Respuesta inválida de Gemini")

            valid_actions = {"BUY", "SELL", "HOLD", "CLOSE"}
            if decision["accion"] not in valid_actions:
                decision["accion"] = "HOLD"

            decision["confianza"] = max(0, min(100, int(decision.get("confianza", 0))))

            logger.info(
                f"[GEMINI] {pair} | "
                f"{decision['accion']} ({decision.get('confianza', 0)}%) | "
                f"{decision.get('razon', '')}"
            )

            decision["_ts"] = time.time()
            decision["atr_pct"] = float(last.get("atr_pct", 1.0))
            decision["adx"] = float(last.get("adx", 0))
            decision["mfi"] = float(last.get("mfi", 50))
            self._gemini_decisions[cache_key] = decision
            if len(self._gemini_decisions) > 100:
                oldest = list(self._gemini_decisions.keys())[0]
                del self._gemini_decisions[oldest]

            return decision

        except json.JSONDecodeError as e:
            logger.warning(f"[WARN] Gemini JSON invalido: {e} | Raw: {raw}")
            return {"accion": "HOLD", "confianza": 0, "razon": "JSON parse error"}

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "exhausted" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                # Marcar la API actual como agotada en el contador local
                # para que _rotate_api la salte y no siga intentando
                with self._api_lock:
                    label = GROQ_API_POOL[self._api_index]["label"]
                    limit = GROQ_API_POOL[self._api_index]["daily_limit"]
                    self._api_usage[label]["count"] = limit
                logger.warning(f"[WARN] API {label} agotada en Google, marcando como usada y rotando...")
                if not self._rotate_api():
                    _tg(
                        "APIS AGOTADAS\n"
                        "Todas las APIs de Gemini llegaron al limite diario de Google.\n"
                        "El bot seguira analizando pero en modo HOLD hasta medianoche UTC.\n"
                        "Reset automatico a las 00:00 UTC."
                    )
            elif "503" in err_str or "UNAVAILABLE" in err_str or "ServiceUnavailable" in err_str:
                logger.warning("[WARN] Gemini 503, esperando 5s y rotando API...")
                time.sleep(5)
                self._rotate_api()
            else:
                logger.error(f"[ERROR] Llamada a IA: {e}")
            return {"accion": "HOLD", "confianza": 0, "razon": f"Error: {str(e)[:50]}"}

    def confirm_trade_entry(
        self, pair, order_type, amount, rate, time_in_force,
        current_time, entry_tag, side, **kwargs
    ) -> bool:
        """Última verificación antes de abrir trade — notifica por Telegram."""
        total_cost = amount * rate
        confidence = 0
        razon = ""
        for k, v in self._gemini_decisions.items():
            if k.startswith(pair + "_"):
                confidence = v.get("confianza", 0)
                razon = v.get("razon", "")[:60]
                break
        nivel = "[EXCELENTE]" if confidence >= 85 else ("[BUENA]" if confidence >= 75 else "[NORMAL]")
        moneda = pair.split("/")[0]
        last_dec_e = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        atr_e = last_dec_e.get("atr_pct", 1.0)
        reg = self._market_regime
        sl_m = 1.2 if ("CALMADA" in reg or reg == "RANGO_TRANQUILO") else (2.0 if ("VOLATIL" in reg or "CAOS" in reg) else 1.5)
        stop_pct = max(0.8, min(3.0, atr_e * sl_m))
        ganancia_esperada = total_cost * 0.02
        perdida_max = total_cost * (stop_pct / 100)
        rr = ganancia_esperada / perdida_max if perdida_max > 0 else 0
        adx_e = last_dec_e.get("adx", 0)
        mfi_e = last_dec_e.get("mfi", 50)
        logger.info(
            f"[ENTRY_OK] {pair} | Precio: {rate:.6f} | Capital: ${total_cost:.2f} | ADX={adx_e:.0f} | Stop={stop_pct:.1f}%"
        )
        _tg(
            f"[COMPRA] {moneda}/USDT\n"
            f"---------------------------\n"
            f"Precio:   {rate:.4f} USDT\n"
            f"Capital:  ${total_cost:.2f}\n"
            f"TP:       +2.5%  (+${ganancia_esperada:.2f})\n"
            f"SL:       -{stop_pct:.1f}%  (-${perdida_max:.2f})\n"
            f"---------------------------\n"
            f"IA:       {confidence}% {nivel}\n"
            f"Mercado:  {self._market_regime}\n"
            f"Razon:    {razon}"
        )
        return True

    def confirm_trade_exit(
        self, pair, trade, order_type, amount, rate,
        time_in_force, exit_reason, current_time, **kwargs
    ) -> bool:
        """Log y notificación Telegram cuando se cierra un trade."""
        profit_pct = trade.calc_profit_ratio(rate) * 100
        ganó = profit_pct > 0
        profit_usd = trade.stake_amount * (profit_pct / 100)
        resultado = "GANANCIA" if ganó else "PERDIDA"
        signo = "+" if ganó else ""
        moneda = pair.split("/")[0]
        logger.info(
            f"[{'WIN' if ganó else 'LOSS'}] Trade cerrado | {pair} | "
            f"P&L: {profit_pct:.2f}% | Razon: {exit_reason}"
        )
        with self._daily_trades_lock:
          self._daily_trades.append({
            "pair": pair, "profit_usd": profit_usd,
            "profit_pct": profit_pct, "won": ganó
          })
        # Activar cooldown si fue stop-loss para evitar reentrar inmediatamente
        if exit_reason in ("stop_loss", "stoploss", "trailing_stop_loss") and not ganó:
            self._stoploss_cooldown[pair] = time.time()
            self._daily_loss_usd += abs(profit_usd)
            logger.info(f"[COOLDOWN] {pair} en cooldown 15min tras stop-loss. Perdida hoy: ${self._daily_loss_usd:.2f}")

        # Filtro 2: cooldown 2h si cualquier pérdida (no solo stop-loss)
        if not ganó:
            self._loss_cooldown[pair] = time.time() + 1800
            logger.info(f"[LOSS-COOLDOWN] {pair} en cooldown 30min tras perdida {profit_pct:.2f}%")
            # Filtro 3: registrar para blacklist dinámica
            self._daily_losses.setdefault(pair, []).append(time.time())
            recent = [t for t in self._daily_losses[pair] if time.time() - t < 86400]
            self._daily_losses[pair] = recent
            if len(recent) >= self._MAX_DAILY_LOSSES:
                logger.warning(f"[BLACKLIST-DIN] {pair} bloqueado automaticamente: {len(recent)} losses en 24h")

        # Guardar en memoria de aprendizaje con RSI y contexto para detección de patrones
        last_decision = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        self._trade_memory.append({
            "pair": pair,
            "accion": last_decision.get("accion", "BUY"),
            "confianza": last_decision.get("confianza", 0),
            "rsi": last_decision.get("rsi", None),
            "razon": last_decision.get("razon", ""),
            "exit_reason": exit_reason,
            "profit_usd": round(profit_usd, 3),
            "profit_pct": round(profit_pct, 2),
            "won": ganó,
        })
        if len(self._trade_memory) > 50:
            self._trade_memory.pop(0)

        # ── Q-Learning: actualizar tabla con resultado del trade ──
        last_decision = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        q_state = last_decision.get("q_state", 50)
        q_action = 1  # BUY=1 (la acción que tomamos fue comprar)
        reward = self._q_reward(profit_pct / 100, trade.stake_amount)
        next_state = q_state  # aproximación conservadora
        with self._q_lock:
            q_val_antes = self._q_table[q_state][q_action]
        self._q_update(q_state, q_action, reward, next_state)
        with self._q_lock:
            q_val_despues = self._q_table[q_state][q_action]
        # Guardar experiencia en buffer de replay
        exp = {"state": q_state, "action": q_action, "reward": reward, "next_state": next_state}
        self._experience_replay.append(exp)
        if len(self._experience_replay) > 500:
            self._experience_replay.pop(0)
        # Experience Replay: repasar 32 experiencias pasadas
        self._experience_replay_train()

        # ── Epsilon dinámico: ajustar exploración según racha ──────────────
        recientes = self._trade_memory[-5:] if len(self._trade_memory) >= 3 else []
        if recientes:
            racha_wins = sum(1 for t in recientes[-3:] if t["won"])
            racha_losses = sum(1 for t in recientes[-3:] if not t["won"])
            if racha_wins >= 3:
                # 3 wins seguidos: confiar más en lo aprendido (bajar exploración)
                self._q_epsilon = max(self._q_epsilon_min, self._q_epsilon * 0.92)
                logger.info(f"[EPSILON] Racha de 3 WINS — epsilon reducido a {self._q_epsilon:.3f} (más explotación)")
            elif racha_losses >= 2:
                # 2 losses seguidos: explorar más para salir del patrón
                self._q_epsilon = min(0.4, self._q_epsilon * 1.15)
                logger.info(f"[EPSILON] Racha de 2 LOSSES — epsilon subido a {self._q_epsilon:.3f} (más exploración)")

        # Guardar Q-table en disco
        self._save_qtable()

        # ── Log de aprendizaje visible ──────────────────────────────────────
        resultado_emoji = "✅ WIN" if ganó else "❌ LOSS"
        patron_rsi = last_decision.get("rsi", "?")
        confianza_ia = last_decision.get("confianza", "?")
        logger.info(
            f"[APRENDIZAJE] {resultado_emoji} | {pair} | {profit_pct:+.2f}% | "
            f"RSI_entrada={patron_rsi} | IA_conf={confianza_ia}% | "
            f"Q-estado={q_state} | Q-val: {q_val_antes:.3f} → {q_val_despues:.3f} | "
            f"reward={reward:.3f} | epsilon={self._q_epsilon:.3f} | episodios={self._q_episodes}"
        )
        # Detectar y loguear patrón aprendido si hay suficiente historial
        pair_hist = [t for t in self._trade_memory if t["pair"] == pair]
        if len(pair_hist) >= 3:
            wins_par = [t for t in pair_hist if t["won"]]
            wr_par = len(wins_par) / len(pair_hist) * 100
            logger.info(f"[PATRON] {pair} | Historial: {len(wins_par)}W/{len(pair_hist)-len(wins_par)}L ({wr_par:.0f}% WR) | episodios_totales={self._q_episodes}")

        # ── Autopausa + Checklist live: evaluar métricas cada 5 trades ──
        self._trades_since_check += 1
        if self._trades_since_check >= 5:
            self._trades_since_check = 0
            self._check_autopause()
        self._check_live_readiness()

        razones = {
            "roi": "Objetivo de ganancia alcanzado",
            "stop_loss": "Stop loss activado",
            "trailing_stop_loss": "Stop loss dinamico activado",
            "stoploss": "Stop loss activado",
            "force_sell": "Venta manual",
            "sell_signal": "Senal de venta de Gemini",
            "exit_signal": "Senal de salida de Gemini",
        }
        razon_es = razones.get(exit_reason, exit_reason)
        last_dec_x = next((v for k, v in self._gemini_decisions.items() if k.startswith(pair + "_")), {})
        adx_x = last_dec_x.get("adx", 0)
        mfi_x = last_dec_x.get("mfi", 50)
        resultado_txt = "[WIN]" if ganó else "[LOSS]"
        _tg(
            f"{resultado_txt} {moneda}/USDT\n"
            f"---------------------------\n"
            f"Resultado: {signo}{profit_pct:.2f}%  ({signo}${abs(profit_usd):.2f})\n"
            f"Capital:   ${trade.stake_amount:.2f}\n"
            f"Motivo:    {razon_es}\n"
            f"---------------------------\n"
            f"Mercado:   {self._market_regime}"
        )
        return True
