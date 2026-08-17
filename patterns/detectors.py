from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import pandas as pd


@dataclass
class PatternSignal:
    pattern: str
    direction: str
    bar_index: int
    strength: float


def is_bullish_engulfing(df: pd.DataFrame, i: int) -> Optional[PatternSignal]:
    if i < 1:
        return None
    prev, curr = df.iloc[i - 1], df.iloc[i]
    if (curr["close"] > curr["open"] and
        prev["close"] < prev["open"] and
        curr["close"] >= prev["open"] and
        curr["open"] <= prev["close"] and
        curr["close"] > prev["high"]):
        body_ratio = (curr["close"] - curr["open"]) / (prev["open"] - prev["close"] + 1e-9)
        strength = min(1.0, 0.6 + body_ratio * 0.25)
        return PatternSignal("bullish_engulfing", "long", i, strength)
    return None


def is_bearish_engulfing(df: pd.DataFrame, i: int) -> Optional[PatternSignal]:
    if i < 1:
        return None
    prev, curr = df.iloc[i - 1], df.iloc[i]
    if (curr["close"] < curr["open"] and
        prev["close"] > prev["open"] and
        curr["close"] <= prev["open"] and
        curr["open"] >= prev["close"] and
        curr["close"] < prev["low"]):
        body_ratio = (curr["open"] - curr["close"]) / (prev["close"] - prev["open"] + 1e-9)
        strength = min(1.0, 0.6 + body_ratio * 0.25)
        return PatternSignal("bearish_engulfing", "short", i, strength)
    return None


def is_pin_bar(df: pd.DataFrame, i: int, min_wick_ratio: float = 2.0) -> Optional[PatternSignal]:
    row = df.iloc[i]
    body = abs(row["close"] - row["open"])
    upper_wick = row["high"] - max(row["close"], row["open"])
    lower_wick = min(row["close"], row["open"]) - row["low"]
    total_range = row["high"] - row["low"] + 1e-9

    if body / total_range > 0.35:
        return None

    if lower_wick >= min_wick_ratio * body and lower_wick > upper_wick:
        strength = min(1.0, lower_wick / (body + 1e-9) / 4)
        return PatternSignal("bullish_pin", "long", i, strength)

    if upper_wick >= min_wick_ratio * body and upper_wick > lower_wick:
        strength = min(1.0, upper_wick / (body + 1e-9) / 4)
        return PatternSignal("bearish_pin", "short", i, strength)

    return None


def detect_patterns(df: pd.DataFrame, i: int) -> List[PatternSignal]:
    signals = []
    for fn in (is_bullish_engulfing, is_bearish_engulfing, is_pin_bar):
        sig = fn(df, i)
        if sig:
            signals.append(sig)
    return signals
