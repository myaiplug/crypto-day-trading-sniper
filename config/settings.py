from risk.position_sizing import RiskConfig

RISK = RiskConfig(
    risk_per_trade_pct=0.35,
    max_open_risk_pct=1.2,
    daily_loss_limit_pct=1.5,
    max_trades_per_day=8,
    min_rr=1.5,
)

SCORE_THRESHOLD = 74.0
PAIRS = ["BTC/USDT", "ETH/USDT"]
STARTING_CASH = 10_000.0

# Alerts (leave empty to disable)
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
DISCORD_WEBHOOK_URL = ""

# Persistence
STATE_PATH = "paper_state.json"
SUMMARY_DIR = "daily_summaries"
