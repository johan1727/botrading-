"""
GeminiBacktest — versión sin API para backtesting rápido.
Replica la lógica de entrada/salida de GeminiStrategy usando solo indicadores técnicos.
Usa las mismas reglas que Gemini aplica en producción: RSI, EMA, MACD, BB, volumen.
"""
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy, IntParameter


def _calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


class GeminiBacktest(IStrategy):
    """
    Replica las reglas de GeminiStrategy sin llamadas a API.
    Útil para backtesting rápido con datos históricos reales.
    """

    INTERFACE_VERSION = 3
    timeframe = "5m"
    can_short = False
    max_open_trades = 5
    stoploss = -0.015
    minimal_roi = {"0": 0.04, "30": 0.025, "60": 0.02, "120": 0.01}
    trailing_stop = True
    trailing_stop_positive = 0.006
    trailing_stop_positive_offset = 0.015
    trailing_only_offset_is_reached = True
    startup_candle_count: int = 210

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = dataframe["close"].diff().pipe(
            lambda d: pd.concat([
                d.clip(lower=0).rolling(14).mean(),
                (-d.clip(upper=0)).rolling(14).mean()
            ], axis=1).apply(lambda r: 100 - 100 / (1 + r.iloc[0] / r.iloc[1]) if r.iloc[1] != 0 else 50, axis=1)
        )
        dataframe["ema20"] = _calc_ema(dataframe["close"], 20)
        dataframe["ema50"] = _calc_ema(dataframe["close"], 50)
        dataframe["ema200"] = _calc_ema(dataframe["close"], 200)
        ema12 = _calc_ema(dataframe["close"], 12)
        ema26 = _calc_ema(dataframe["close"], 26)
        dataframe["macd"] = ema12 - ema26
        dataframe["macd_signal"] = _calc_ema(dataframe["macd"], 9)
        dataframe["macd_hist"] = dataframe["macd"] - dataframe["macd_signal"]
        bb_mid = dataframe["close"].rolling(20).mean()
        bb_std = dataframe["close"].rolling(20).std()
        dataframe["bb_upper"] = bb_mid + 2 * bb_std
        dataframe["bb_lower"] = bb_mid - 2 * bb_std
        dataframe["bb_pct"] = (dataframe["close"] - dataframe["bb_lower"]) / (dataframe["bb_upper"] - dataframe["bb_lower"]) * 100
        vol_ma = dataframe["volume"].rolling(20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / vol_ma

        high_low = dataframe["high"] - dataframe["low"]
        high_close = (dataframe["high"] - dataframe["close"].shift()).abs()
        low_close = (dataframe["low"] - dataframe["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        dataframe["atr"] = true_range.ewm(span=14, adjust=False).mean()
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"] * 100

        # ADX (14)
        high_diff = dataframe["high"].diff()
        low_diff = dataframe["low"].diff()
        plus_dm = high_diff.where((high_diff > 0) & (high_diff > -low_diff), 0.0)
        minus_dm = (-low_diff).where((-low_diff > 0) & (-low_diff > high_diff), 0.0)
        atr14 = dataframe["atr"]
        plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr14.replace(0, 1e-10))
        minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr14.replace(0, 1e-10))
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
        dataframe["adx"] = dx.ewm(span=14, adjust=False).mean()

        # MFI (14)
        typical_price = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3
        money_flow = typical_price * dataframe["volume"]
        tp_prev = typical_price.shift(1)
        pos_flow = money_flow.where(typical_price > tp_prev, 0.0).rolling(14).sum()
        neg_flow = money_flow.where(typical_price < tp_prev, 0.0).rolling(14).sum()
        mfi_ratio = pos_flow / neg_flow.replace(0, 1e-10)
        dataframe["mfi"] = 100 - (100 / (1 + mfi_ratio))

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Reglas de entrada que replica lo que Gemini decide:
        - Señal principal: tendencia alcista en todos los indicadores
        - Señal oportunista: RSI sobreventa + BB bajo
        """
        above_ema200 = dataframe["close"] > dataframe["ema200"]
        ema_bull = dataframe["ema20"] > dataframe["ema50"]
        macd_bull = dataframe["macd_hist"] > 0
        rsi_ok = dataframe["rsi"] < 50
        vol_ok = dataframe["volume_ratio"] > 1.0
        bb_mid_zone = dataframe["bb_pct"] < 70

        adx_ok = dataframe["adx"] > 25
        señal_principal = above_ema200 & ema_bull & macd_bull & rsi_ok & vol_ok & bb_mid_zone & adx_ok

        rsi_oversold = dataframe["rsi"] < 35
        bb_low = dataframe["bb_pct"] < 25
        vol_min = dataframe["volume_ratio"] > 0.8
        mfi_oversold = dataframe["mfi"] < 25
        señal_oportunista = rsi_oversold & bb_low & vol_min & mfi_oversold & adx_ok

        dataframe.loc[señal_principal | señal_oportunista, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Reglas de salida:
        - RSI sobrecomprado + MACD bajando
        - Divergencia RSI (precio sube, RSI baja)
        """
        rsi_high = dataframe["rsi"] > 70
        macd_bear = dataframe["macd_hist"] < 0

        rsi_prev = dataframe["rsi"].shift(3)
        close_prev = dataframe["close"].shift(3)
        rsi_divergence = (dataframe["close"] > close_prev) & (dataframe["rsi"] < rsi_prev - 5)

        dataframe.loc[(rsi_high & macd_bear) | rsi_divergence, "exit_long"] = 1
        return dataframe
