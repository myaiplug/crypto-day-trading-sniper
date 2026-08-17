#!/usr/bin/env python3
"""
Paper-trading entry point for the Crypto Day-Trading Sniper.
Includes wallet-flow scoring + Ritter-style tabular Q execution layer.
"""
from __future__ import annotations
import logging
from data.feed import CandleFeed
from data.atr_cache import ATRCache
from data.wallet_flow import WalletFlowCache
from execution.paper_broker import PaperBroker
from execution.trade_manager import TradeManager
from execution.rl_execution import TabularQAgent, SetupLogger
from live.scheduler import LiveScheduler
from live.alerts import AlertManager
from reporting.daily_summary import DailySummaryWriter
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
    wallet_cache = WalletFlowCache()
    rl_agent = TabularQAgent(path="rl_qtable.json")
    setup_logger = SetupLogger(path="setup_log.jsonl")

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
        wallet_cache=wallet_cache,
        rl_agent=rl_agent,
        setup_logger=setup_logger,
        use_rl=True,
    )

    logger.info(
        "Paper sniper ready. Equity: %.2f | WebSocket=%s | RL=%s | WalletFlow=on",
        broker.get_equity(),
        scheduler.use_websocket,
        scheduler.use_rl,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
