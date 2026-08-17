from __future__ import annotations
from typing import Dict, Optional
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("sniper.atr_cache")


class ATRCache:
    def __init__(self, period: int = 14, default_atr: float = 0.0):
        self.period = period
        self.default_atr = default_atr
        self._atr: Dict[str, float] = {}
        self._last_df_len: Dict[str, int] = {}

    def update(self, symbol: str, df: pd.DataFrame) -> float:
        if df is None or len(df) < self.period + 1:
            return self._atr.get(symbol, self.default_atr)

        current_len = len(df)
        if self._last_df_len.get(symbol) == current_len and symbol in self._atr:
            return self._atr[symbol]

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(self.period, min_periods=self.period).mean().iloc[-1]

        if np.isnan(atr) or atr <= 0:
            atr = self.default_atr

        self._atr[symbol] = float(atr)
        self._last_df_len[symbol] = current_len
        return self._atr[symbol]

    def get(self, symbol: str) -> float:
        return self._atr.get(symbol, self.default_atr)

    def get_all(self) -> Dict[str, float]:
        return dict(self._atr)

    def clear(self, symbol: Optional[str] = None):
        if symbol:
            self._atr.pop(symbol, None)
            self._last_df_len.pop(symbol, None)
        else:
            self._atr.clear()
            self._last_df_len.clear()
