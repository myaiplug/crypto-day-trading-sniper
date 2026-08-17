from __future__ import annotations
from typing import Literal
import pandas as pd

Bias = Literal["bullish", "bearish", "neutral"]


def compute_htf_bias(
    htf_df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 50,
    structure_lookback: int = 5,
) -> Bias:
    if htf_df is None or len(htf_df) < ema_slow + structure_lookback + 2:
        return "neutral"

    close = htf_df["close"]
    ema_f = close.ewm(span=ema_fast, adjust=False).mean()
    ema_s = close.ewm(span=ema_slow, adjust=False).mean()

    last_f, last_s = ema_f.iloc[-1], ema_s.iloc[-1]
    prev_f, prev_s = ema_f.iloc[-2], ema_s.iloc[-2]

    ema_bull = last_f > last_s and last_f > prev_f
    ema_bear = last_f < last_s and last_f < prev_f

    recent = htf_df.iloc[-structure_lookback:]
    hh = recent["high"].iloc[-1] > recent["high"].iloc[:-1].max()
    ll = recent["low"].iloc[-1] < recent["low"].iloc[:-1].min()

    if ema_bull and not ll:
        return "bullish"
    if ema_bear and not hh:
        return "bearish"
    return "neutral"


def bias_score_adjustment(bias: Bias, direction: str) -> int:
    if bias == "bullish" and direction == "long":
        return 15
    if bias == "bearish" and direction == "short":
        return 15
    if bias == "neutral":
        return 8
    return 2
