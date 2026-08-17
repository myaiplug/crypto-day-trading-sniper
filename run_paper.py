#!/usr/bin/env python3
"""Paper-trading entry point for the Crypto Day-Trading Sniper."""
from __future__ import annotations
import logging
from data.feed import CandleFeed
from data.atr_cache import ATRCache
from execution.paper_broker import PaperBroker
from execution.trade_manager import TradeManager
from live.scheduler import LiveScheduler
from live.alerts import AlertManager
from reporting.daily_summary import DailySummaryWriter
from risk.position_sizing import RiskConfig
from persistence.state import load_state
from config.settings import (
    RISK, SCORE_THRESHOLD, PAIRS, STARTING_CASH,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL,
    STATE_PATH, SUMMARY_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sniper")


def main():
    feed = CandleFeed(exchange_id="binance", sandbox=True)
    broker = PaperBroker(starting_cash=STARTING_CASH, taker_fee=0.0006, slippage_bps=1.5)
    atr_cache = ATRCache(period=14)

    def atr_provider(pair: str) -> float:
        return atr_cache.get(pair)

    manager = TradeManager(broker, atr_provider)
    load_state(broker, manager, STATE_PATH)

    alerts = AlertManager(
        telegram_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID,
        discord_webhook=DISCORD_WEBHOOK_URL,
    )
    summary = DailySummaryWriter(output_dir=SUMMARY_DIR)

    scheduler = LiveScheduler(
        feed=feed,
        broker=broker,
        manager=manager,
        atr_cache=atr_cache,
        risk_config=RISK,
        symbols=PAIRS,
        score_threshold=SCORE_THRESHOLD,
        state_path=STATE_PATH,
        alerts=alerts,
        summary_writer=summary,
        use_websocket=True,
    )

    logger.info(
        "Paper sniper ready. Equity: %.2f | WebSocket=%s",
        broker.get_equity(),
        scheduler.use_websocket,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
