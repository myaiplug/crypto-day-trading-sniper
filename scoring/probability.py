from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import pandas as pd
from patterns.detectors import PatternSignal


@dataclass
class ScoredSetup:
    pattern: PatternSignal
    score: float
    direction: str
    bar_index: int
    reasons: Dict[str, float]


def calculate_score(
    df: pd.DataFrame,
    signal: PatternSignal,
    i: int,
    avg_volume_period: int = 10,
    key_levels: Optional[list[float]] = None,
    wallet_features: Optional[Any] = None,
) -> ScoredSetup:
    row = df.iloc[i]
    reasons: Dict[str, float] = {}

    pattern_pts = 12 + signal.strength * 13
    reasons["pattern"] = round(pattern_pts, 1)

    vol_ma = df["volume"].iloc[max(0, i - avg_volume_period):i].mean()
    vol_ratio = row["volume"] / (vol_ma + 1e-9)
    if vol_ratio >= 1.8:
        vol_pts = 20.0
    elif vol_ratio >= 1.4:
        vol_pts = 12 + (vol_ratio - 1.4) * 20
    else:
        vol_pts = max(0.0, vol_ratio * 8)
    reasons["volume"] = round(vol_pts, 1)

    level_pts = 0.0
    if key_levels:
        dist = min(abs(row["close"] - lvl) / row["close"] for lvl in key_levels)
        if dist <= 0.0015:
            level_pts = 20.0
        elif dist <= 0.003:
            level_pts = 12.0
        elif dist <= 0.005:
            level_pts = 6.0
    reasons["level"] = level_pts

    htf_pts = 9.0
    reasons["htf"] = htf_pts

    body = abs(row["close"] - row["open"]) + 1e-9
    wick = max(
        row["high"] - max(row["close"], row["open"]),
        min(row["close"], row["open"]) - row["low"],
    )
    rej_pts = min(10.0, (wick / body) * 2.5)
    reasons["rejection"] = round(rej_pts, 1)

    atr = (df["high"] - df["low"]).iloc[max(0, i - 14):i + 1].mean()
    atr_pct = atr / row["close"] if row["close"] else 0
    if 0.0015 <= atr_pct <= 0.006:
        atr_pts = 9.0
    else:
        atr_pts = 3.0
    reasons["atr"] = atr_pts

    flow_pts = 0.0
    if wallet_features is not None:
        z = getattr(wallet_features, "flow_zscore", 0.0)
        align = getattr(wallet_features, "alignment", 0)
        if align > 0:
            flow_pts = min(12.0, 6.0 + 3.0 * abs(z))
        elif align < 0:
            flow_pts = 0.0
        else:
            flow_pts = 3.0
    reasons["wallet_flow"] = round(flow_pts, 1)

    total = (
        pattern_pts + vol_pts + level_pts + htf_pts
        + rej_pts + atr_pts + flow_pts
    )
    total = max(0.0, min(100.0, total))

    return ScoredSetup(
        pattern=signal,
        score=round(total, 1),
        direction=signal.direction,
        bar_index=i,
        reasons=reasons,
    )
