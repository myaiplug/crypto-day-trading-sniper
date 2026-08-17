from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal
import pandas as pd
import numpy as np

Direction = Literal["long", "short"]


@dataclass
class StopResult:
    stop_price: float
    method: str
    atr_distance: float
    structure_level: Optional[float]


def find_swing_low(df: pd.DataFrame, i: int, lookback: int = 8) -> Optional[float]:
    if i < lookback + 2:
        return None
    window = df.iloc[i - lookback - 1 : i]
    lows = window["low"].values
    for j in range(1, len(lows) - 1):
        if lows[j] < lows[j - 1] and lows[j] < lows[j + 1]:
            return float(lows[j])
    return float(window["low"].min())


def find_swing_high(df: pd.DataFrame, i: int, lookback: int = 8) -> Optional[float]:
    if i < lookback + 2:
        return None
    window = df.iloc[i - lookback - 1 : i]
    highs = window["high"].values
    for j in range(1, len(highs) - 1):
        if highs[j] > highs[j - 1] and highs[j] > highs[j + 1]:
            return float(highs[j])
    return float(window["high"].max())


def compute_structure_stop(
    df: pd.DataFrame,
    i: int,
    direction: Direction,
    entry_price: float,
    atr_mult: float = 1.15,
    min_stop_pct: float = 0.0012,
    max_stop_pct: float = 0.0060,
    swing_lookback: int = 10,
) -> StopResult:
    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[i]
    atr = float(atr) if not np.isnan(atr) else entry_price * 0.002

    swing = None
    if direction == "long":
        swing = find_swing_low(df, i, lookback=swing_lookback)
        if swing is not None and swing < entry_price:
            structure_stop = swing - atr * 0.15
            method = "swing_low"
        else:
            structure_stop = entry_price - atr * atr_mult
            method = "atr_fallback"
    else:
        swing = find_swing_high(df, i, lookback=swing_lookback)
        if swing is not None and swing > entry_price:
            structure_stop = swing + atr * 0.15
            method = "swing_high"
        else:
            structure_stop = entry_price + atr * atr_mult
            method = "atr_fallback"

    raw_dist = abs(entry_price - structure_stop)
    min_dist = entry_price * min_stop_pct
    max_dist = entry_price * max_stop_pct

    if raw_dist < min_dist:
        structure_stop = entry_price - min_dist if direction == "long" else entry_price + min_dist
        method += "+min_clamp"
    elif raw_dist > max_dist:
        structure_stop = entry_price - max_dist if direction == "long" else entry_price + max_dist
        method += "+max_clamp"

    return StopResult(
        stop_price=round(structure_stop, 8),
        method=method,
        atr_distance=atr,
        structure_level=swing,
    )
