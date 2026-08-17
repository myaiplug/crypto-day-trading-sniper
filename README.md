# Crypto Day-Trading Sniper

Low-risk, incremental, probability-filtered day-trading system focused on candlestick patterns + confluence + strict risk management.

**Educational / research framework only.**  
Crypto trading involves substantial risk of loss. This is not financial advice. Paper-trade extensively before considering real capital.

## Features

- Candlestick pattern detectors (engulfing, pin bars)
- Concrete probability scoring (0–100) with confluence factors
- Structure-based stops with ATR fallback + clamps
- Partial take-profits + ATR trailing stops
- Higher-timeframe bias adjustment
- Production-grade paper broker (fees, slippage, positions, PnL)
- Real ATR feature cache
- Telegram + Discord alert hooks
- Daily performance summary writer (JSON + Markdown)
- State persistence (save / restore)
- Live candle feed + scheduler loop (ccxt)

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Optional: set alert credentials in config/settings.py
python run_paper.py
```

## Project Layout

```
crypto-sniper/
├── config/settings.py
├── data/feed.py + atr_cache.py
├── patterns/detectors.py
├── scoring/probability.py
├── analysis/htf_bias.py
├── risk/position_sizing.py + stops.py
├── execution/paper_broker.py + trade_manager.py
├── live/scheduler.py + alerts.py
├── persistence/state.py
├── reporting/daily_summary.py
├── tests/
└── run_paper.py
```

## Risk Defaults

- Risk per trade: 0.35% of equity
- Max open risk: 1.2%
- Daily loss limit: 1.5%
- Score threshold: 74
- Max trades per day: 8

Tune these in `config/settings.py`.

## Tests

```bash
pytest tests/ -v
```

## Disclaimer

This system is a research and paper-trading framework. Most retail day traders lose money. Past simulated results do not guarantee future performance. Never risk capital you cannot afford to lose.
