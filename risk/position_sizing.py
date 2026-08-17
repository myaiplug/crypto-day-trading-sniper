from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.35
    max_open_risk_pct: float = 1.2
    daily_loss_limit_pct: float = 1.5
    max_trades_per_day: int = 8
    min_rr: float = 1.5


@dataclass
class PositionSizeResult:
    qty: float
    risk_amount: float
    stop_distance: float
    allowed: bool
    reason: str


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    config: RiskConfig,
    current_open_risk_pct: float = 0.0,
    trades_today: int = 0,
    daily_pnl_pct: float = 0.0,
) -> PositionSizeResult:
    if trades_today >= config.max_trades_per_day:
        return PositionSizeResult(0, 0, 0, False, "max trades reached")

    if daily_pnl_pct <= -config.daily_loss_limit_pct:
        return PositionSizeResult(0, 0, 0, False, "daily loss limit")

    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return PositionSizeResult(0, 0, 0, False, "invalid stop")

    risk_amount = equity * (config.risk_per_trade_pct / 100)
    qty = risk_amount / stop_distance

    new_open_risk = current_open_risk_pct + config.risk_per_trade_pct
    if new_open_risk > config.max_open_risk_pct:
        return PositionSizeResult(0, 0, 0, False, "max open risk")

    return PositionSizeResult(
        qty=qty,
        risk_amount=risk_amount,
        stop_distance=stop_distance,
        allowed=True,
        reason="ok",
    )
