"""
FastAPI control layer for the Crypto Day-Trading Sniper.
Exposes status, positions, setups, risk controls, and start/pause commands.
Serves a responsive mobile-first dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("sniper.web")

ENGINE: Dict[str, Any] = {
    "running": False,
    "paused": True,
    "started_at": None,
    "equity": 10_000.0,
    "starting_cash": 10_000.0,
    "daily_pnl": 0.0,
    "trades_today": 0,
    "open_positions": [],
    "recent_setups": [],
    "risk": {
        "risk_per_trade_pct": 0.35,
        "max_open_risk_pct": 1.2,
        "daily_loss_limit_pct": 1.5,
        "max_trades_per_day": 8,
        "score_threshold": 74.0,
    },
    "use_rl": True,
    "use_wallet": True,
    "last_update": time.time(),
}


def _refresh_engine_snapshot():
    try:
        broker = ENGINE.get("broker")
        manager = ENGINE.get("manager")
        if broker is not None:
            ENGINE["equity"] = broker.get_equity({})
            ENGINE["daily_pnl"] = ENGINE["equity"] - ENGINE.get("starting_cash", 10_000.0)
            positions = []
            for pair, pos in getattr(broker, "positions", {}).items():
                if pos.qty == 0:
                    continue
                positions.append({
                    "symbol": pair,
                    "qty": pos.qty,
                    "avg_price": pos.avg_price,
                    "direction": "long" if pos.qty > 0 else "short",
                    "realized_pnl": pos.realized_pnl,
                })
            ENGINE["open_positions"] = positions
        if manager is not None:
            managed = []
            for pid, p in getattr(manager, "positions", {}).items():
                managed.append({
                    "id": p.id,
                    "symbol": p.pair,
                    "direction": p.direction,
                    "entry": p.entry_price,
                    "stop": p.current_stop,
                    "qty": p.remaining_qty,
                    "score": p.score,
                })
            if managed:
                ENGINE["open_positions"] = managed
    except Exception as e:
        logger.debug("Snapshot refresh: %s", e)
    ENGINE["last_update"] = time.time()


class RiskUpdate(BaseModel):
    risk_per_trade_pct: Optional[float] = Field(None, ge=0.05, le=2.0)
    max_open_risk_pct: Optional[float] = Field(None, ge=0.2, le=5.0)
    daily_loss_limit_pct: Optional[float] = Field(None, ge=0.5, le=10.0)
    max_trades_per_day: Optional[int] = Field(None, ge=1, le=50)
    score_threshold: Optional[float] = Field(None, ge=50.0, le=95.0)


class ControlCommand(BaseModel):
    action: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logger.info("Sniper web control plane starting")
    try:
        from execution.paper_broker import PaperBroker
        from execution.trade_manager import TradeManager
        from data.atr_cache import ATRCache
        from config.settings import STARTING_CASH, RISK, SCORE_THRESHOLD

        broker = PaperBroker(starting_cash=STARTING_CASH)
        atr_cache = ATRCache()
        def atr_provider(p): return atr_cache.get(p)
        manager = TradeManager(broker, atr_provider)
        ENGINE["broker"] = broker
        ENGINE["manager"] = manager
        ENGINE["starting_cash"] = STARTING_CASH
        ENGINE["equity"] = STARTING_CASH
        ENGINE["risk"]["risk_per_trade_pct"] = RISK.risk_per_trade_pct
        ENGINE["risk"]["max_open_risk_pct"] = RISK.max_open_risk_pct
        ENGINE["risk"]["daily_loss_limit_pct"] = RISK.daily_loss_limit_pct
        ENGINE["risk"]["max_trades_per_day"] = RISK.max_trades_per_day
        ENGINE["risk"]["score_threshold"] = SCORE_THRESHOLD
        logger.info("Engine objects attached")
    except Exception as e:
        logger.warning("Running in demo mode: %s", e)
    yield
    logger.info("Sniper web control plane shutting down")


app = FastAPI(title="Crypto Sniper Control", version="1.0", lifespan=lifespan)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/status")
async def status():
    _refresh_engine_snapshot()
    return {
        "running": ENGINE["running"],
        "paused": ENGINE["paused"],
        "equity": round(ENGINE["equity"], 2),
        "daily_pnl": round(ENGINE["daily_pnl"], 2),
        "daily_pnl_pct": round(
            (ENGINE["daily_pnl"] / ENGINE["starting_cash"] * 100) if ENGINE["starting_cash"] else 0, 3
        ),
        "trades_today": ENGINE["trades_today"],
        "open_positions": ENGINE["open_positions"],
        "risk": ENGINE["risk"],
        "use_rl": ENGINE["use_rl"],
        "use_wallet": ENGINE["use_wallet"],
        "last_update": ENGINE["last_update"],
    }


@app.get("/api/setups")
async def setups():
    return {"setups": ENGINE.get("recent_setups", [])[-20:]}


@app.get("/api/performance")
async def performance():
    equity = ENGINE["equity"]
    start = ENGINE["starting_cash"]
    return {
        "starting_cash": start,
        "equity": round(equity, 2),
        "net_pnl": round(equity - start, 2),
        "net_pnl_pct": round((equity - start) / start * 100, 3) if start else 0,
        "trades_today": ENGINE["trades_today"],
        "open_count": len(ENGINE["open_positions"]),
    }


@app.post("/api/control")
async def control(cmd: ControlCommand):
    action = cmd.action.lower().strip()
    if action == "start":
        ENGINE["running"] = True
        ENGINE["paused"] = False
        ENGINE["started_at"] = time.time()
        return {"ok": True, "message": "Sniper started"}
    if action == "pause":
        ENGINE["paused"] = True
        return {"ok": True, "message": "Sniper paused – no new entries"}
    if action == "flatten":
        manager = ENGINE.get("manager")
        closed = 0
        if manager:
            for pid, pos in list(manager.positions.items()):
                try:
                    manager._close_remaining(pos, pos.entry_price, reason="flatten")
                    closed += 1
                except Exception:
                    pass
        ENGINE["open_positions"] = []
        return {"ok": True, "message": f"Flattened {closed} positions"}
    return JSONResponse({"ok": False, "message": "Unknown action"}, status_code=400)


@app.post("/api/risk")
async def update_risk(body: RiskUpdate):
    r = ENGINE["risk"]
    if body.risk_per_trade_pct is not None:
        r["risk_per_trade_pct"] = body.risk_per_trade_pct
    if body.max_open_risk_pct is not None:
        r["max_open_risk_pct"] = body.max_open_risk_pct
    if body.daily_loss_limit_pct is not None:
        r["daily_loss_limit_pct"] = body.daily_loss_limit_pct
    if body.max_trades_per_day is not None:
        r["max_trades_per_day"] = body.max_trades_per_day
    if body.score_threshold is not None:
        r["score_threshold"] = body.score_threshold
    return {"ok": True, "risk": r}


@app.post("/api/toggles")
async def toggles(payload: Dict[str, bool]):
    if "use_rl" in payload:
        ENGINE["use_rl"] = bool(payload["use_rl"])
    if "use_wallet" in payload:
        ENGINE["use_wallet"] = bool(payload["use_wallet"])
    return {"ok": True, "use_rl": ENGINE["use_rl"], "use_wallet": ENGINE["use_wallet"]}


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager_ws = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager_ws.connect(ws)
    try:
        while True:
            _refresh_engine_snapshot()
            await ws.send_json({
                "type": "status",
                "payload": {
                    "equity": round(ENGINE["equity"], 2),
                    "daily_pnl": round(ENGINE["daily_pnl"], 2),
                    "paused": ENGINE["paused"],
                    "running": ENGINE["running"],
                    "open_positions": ENGINE["open_positions"],
                    "trades_today": ENGINE["trades_today"],
                },
            })
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        manager_ws.disconnect(ws)


@app.post("/api/demo/setup")
async def demo_setup():
    setup = {
        "symbol": "BTC/USDT",
        "direction": "long",
        "score": 81.5,
        "pattern": "bullish_engulfing",
        "rl_action": "100%",
        "wallet_align": 1,
        "reasons": {
            "pattern": 22.0, "volume": 16.0, "level": 12.0,
            "htf": 15.0, "rejection": 8.0, "atr": 9.0, "wallet_flow": 9.5,
        },
        "ts": time.time(),
    }
    ENGINE["recent_setups"].append(setup)
    ENGINE["recent_setups"] = ENGINE["recent_setups"][-30:]
    return {"ok": True, "setup": setup}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
