"""
Live scheduler – works with both WebSocket streaming and REST polling.
"""
from __future__ import annotations

import time
import logging
from typing import List

from data.feed import CandleFeed
from data.atr_cache import ATRCache
from execution.paper_broker import PaperBroker
from execution.trade_manager import TradeManager
from risk.position_sizing import calculate_position_size, RiskConfig
from risk.stops import compute_structure_stop
from analysis.htf_bias import compute_htf_bias, bias_score_adjustment
from patterns.detectors import detect_patterns
from scoring.probability import calculate_score
from persistence.state import save_state
from live.alerts import AlertManager
from reporting.daily_summary import DailySummaryWriter

logger = logging.getLogger("sniper.scheduler")


class LiveScheduler:
    def __init__(
        self,
        feed: CandleFeed,
        broker: PaperBroker,
        manager: TradeManager,
        atr_cache: ATRCache,
        risk_config: RiskConfig,
        symbols: List[str],
        score_threshold: float = 74.0,
        primary_tf: str = "1m",
        htf: str = "15m",
        poll_interval: float = 3.0,
        state_path: str = "paper_state.json",
        alerts: AlertManager | None = None,
        summary_writer: DailySummaryWriter | None = None,
        use_websocket: bool = True,
    ):
        self.feed = feed
        self.broker = broker
        self.manager = manager
        self.atr_cache = atr_cache
        self.risk = risk_config
        self.symbols = symbols
        self.score_threshold = score_threshold
        self.primary_tf = primary_tf
        self.htf = htf
        self.poll_interval = poll_interval
        self.state_path = state_path
        self.alerts = alerts or AlertManager()
        self.summary = summary_writer or DailySummaryWriter()
        self.use_websocket = use_websocket
        self.trades_today = 0
        self._last_save = 0.0

        self.feed.subscribe(self.on_closed_candle)

    def start(self):
        logger.info("LiveScheduler starting – backfilling…")
        for sym in self.symbols:
            self.feed.backfill(sym, self.primary_tf, limit=500)
            self.feed.backfill(sym, self.htf, limit=300)
            df = self.feed.get_df(sym, self.primary_tf)
            if df is not None:
                self.atr_cache.update(sym, df)

        if self.use_websocket:
            for sym in self.symbols:
                self.feed.watch(sym, self.primary_tf)
                self.feed.watch(sym, self.htf)
            self.feed.start_streaming()
            logger.info("WebSocket streaming active – resting main loop (persist only)")
            try:
                while True:
                    self._maybe_persist()
                    time.sleep(5.0)
            except KeyboardInterrupt:
                logger.info("Shutting down…")
                self.feed.stop_streaming()
        else:
            logger.info("REST polling mode")
            while True:
                try:
                    for sym in self.symbols:
                        self.feed.poll(sym, self.primary_tf)
                        self.feed.poll(sym, self.htf)
                    self._maybe_persist()
                except Exception as e:
                    logger.exception("Scheduler loop error: %s", e)
                time.sleep(self.poll_interval)

    def on_closed_candle(self, symbol: str, timeframe: str, df):
        if timeframe == self.primary_tf:
            self.atr_cache.update(symbol, df)

        if timeframe != self.primary_tf:
            return

        i = len(df) - 1
        row = df.iloc[i]
        high, low, close = float(row["high"]), float(row["low"]), float(row["close"])

        equity = self.broker.get_equity({symbol: close})
        self.summary.on_new_day(equity)

        self.manager.on_candle(symbol, high, low, close)

        signals = detect_patterns(df, i)
        if not signals:
            return

        htf_df = self.feed.get_df(symbol, self.htf)
        bias = compute_htf_bias(htf_df) if htf_df is not None else "neutral"

        for sig in signals:
            scored = calculate_score(df, sig, i)
            scored.score += bias_score_adjustment(bias, sig.direction)

            logger.info(
                "%s %s score=%.1f bias=%s",
                symbol, sig.pattern, scored.score, bias,
            )

            if scored.score < self.score_threshold:
                continue

            entry = close
            stop_res = compute_structure_stop(df, i, sig.direction, entry)

            sizing = calculate_position_size(
                equity=equity,
                entry_price=entry,
                stop_price=stop_res.stop_price,
                config=self.risk,
                trades_today=self.trades_today,
            )
            if not sizing.allowed:
                logger.info("Risk rejected: %s", sizing.reason)
                continue

            side = "buy" if sig.direction == "long" else "sell"
            order = self.broker.place_order(
                symbol, side, sizing.qty, order_type="market", current_price=entry
            )
            if order.status.value != "filled":
                logger.warning("Order not filled: %s", order.status)
                continue

            self.manager.open_position(
                pair=symbol,
                direction=sig.direction,
                entry_price=entry,
                qty=sizing.qty,
                stop_price=stop_res.stop_price,
                score=scored.score,
            )
            self.trades_today += 1
            self.alerts.trade_opened(
                sig.direction, symbol, sizing.qty, entry, stop_res.stop_price, scored.score
            )
            logger.info(
                "OPENED %s %s qty=%.6f entry=%.4f stop=%.4f score=%.1f",
                sig.direction, symbol, sizing.qty, entry, stop_res.stop_price, scored.score,
            )

    def _maybe_persist(self):
        now = time.time()
        if now - self._last_save > 60:
            save_state(self.broker, self.manager, self.state_path)
            self._last_save = now
