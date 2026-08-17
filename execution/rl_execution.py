"""
Ritter-style tabular Q-learning execution layer.

The sniper still decides *whether* a setup is high-probability.
This module decides *how aggressively* to take it (or skip).
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sniper.rl_execution")

SKIP = 0
SIZE_50 = 1
SIZE_100 = 2
SIZE_150 = 3
ACTIONS = [SKIP, SIZE_50, SIZE_100, SIZE_150]
ACTION_NAMES = {0: "skip", 1: "50%", 2: "100%", 3: "150%"}
SIZE_MULTIPLIER = {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.5}


def _bin(value: float, edges: List[float]) -> int:
    for i, e in enumerate(edges):
        if value < e:
            return i
    return len(edges)


@dataclass
class RLState:
    score_bin: int
    inventory_bin: int
    open_risk_bin: int
    daily_pnl_bin: int
    vol_regime_bin: int
    direction: int

    def key(self) -> Tuple:
        return (
            self.score_bin,
            self.inventory_bin,
            self.open_risk_bin,
            self.daily_pnl_bin,
            self.vol_regime_bin,
            self.direction,
        )


def build_state(
    score: float,
    direction: str,
    inventory_pct: float,
    open_risk_pct: float,
    daily_pnl_pct: float,
    atr_pct: float,
) -> RLState:
    score_bin = _bin(score, [70, 75, 80, 85])
    inv_bin = _bin(inventory_pct, [-1.5, -0.5, 0.5, 1.5])
    risk_bin = _bin(open_risk_pct, [0.3, 0.7, 1.1])
    pnl_bin = _bin(daily_pnl_pct, [-1.0, -0.3, 0.3, 1.0])
    vol_bin = _bin(atr_pct * 100, [0.15, 0.35, 0.60])
    dir_bin = 1 if direction == "long" else 0
    return RLState(score_bin, inv_bin, risk_bin, pnl_bin, vol_bin, dir_bin)


class TabularQAgent:
    def __init__(
        self,
        alpha: float = 0.15,
        gamma: float = 0.92,
        epsilon: float = 0.08,
        epsilon_decay: float = 0.9995,
        min_epsilon: float = 0.02,
        path: str = "rl_qtable.json",
    ):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.min_epsilon = min_epsilon
        self.path = path
        self.q: Dict[str, List[float]] = {}
        self.visit: Dict[str, int] = {}
        self.load()

    def _key(self, state: RLState) -> str:
        return str(state.key())

    def _ensure(self, key: str):
        if key not in self.q:
            self.q[key] = [0.0] * len(ACTIONS)
            self.visit[key] = 0

    def act(self, state: RLState, explore: bool = True) -> int:
        key = self._key(state)
        self._ensure(key)
        if explore and random.random() < self.epsilon:
            return random.choice(ACTIONS)
        qvals = self.q[key]
        max_q = max(qvals)
        best = [a for a, q in enumerate(qvals) if q == max_q]
        return random.choice(best)

    def update(
        self,
        state: RLState,
        action: int,
        reward: float,
        next_state: Optional[RLState],
        done: bool,
    ):
        key = self._key(state)
        self._ensure(key)
        self.visit[key] = self.visit.get(key, 0) + 1

        if done or next_state is None:
            target = reward
        else:
            nkey = self._key(next_state)
            self._ensure(nkey)
            target = reward + self.gamma * max(self.q[nkey])

        old = self.q[key][action]
        self.q[key][action] = old + self.alpha * (target - old)
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)

    def size_multiplier(self, action: int) -> float:
        return SIZE_MULTIPLIER.get(action, 0.0)

    def save(self):
        payload = {
            "q": self.q,
            "visit": self.visit,
            "epsilon": self.epsilon,
            "saved_at": time.time(),
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        logger.info("Q-table saved → %s (%d states)", self.path, len(self.q))

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.q = {k: v for k, v in payload.get("q", {}).items()}
            self.visit = {k: int(v) for k, v in payload.get("visit", {}).items()}
            self.epsilon = float(payload.get("epsilon", self.epsilon))
            logger.info("Q-table loaded (%d states, ε=%.3f)", len(self.q), self.epsilon)
        except Exception as e:
            logger.warning("Could not load Q-table: %s", e)


@dataclass
class SetupLogRecord:
    ts: float
    symbol: str
    direction: str
    score: float
    reasons: Dict
    action: int
    size_mult: float
    entry: float
    stop: float
    exit_price: Optional[float] = None
    r_multiple: Optional[float] = None
    pnl: Optional[float] = None
    reward: Optional[float] = None
    done: bool = False


class SetupLogger:
    def __init__(self, path: str = "setup_log.jsonl"):
        self.path = path
        self._pending: Dict[str, SetupLogRecord] = {}

    def log_candidate(
        self,
        symbol: str,
        direction: str,
        score: float,
        reasons: Dict,
        action: int,
        size_mult: float,
        entry: float,
        stop: float,
    ) -> str:
        rid = f"{symbol}_{int(time.time()*1000)}_{random.randint(1000,9999)}"
        rec = SetupLogRecord(
            ts=time.time(),
            symbol=symbol,
            direction=direction,
            score=score,
            reasons=reasons,
            action=action,
            size_mult=size_mult,
            entry=entry,
            stop=stop,
        )
        self._pending[rid] = rec
        self._append(rec)
        return rid

    def resolve(self, rid: str, exit_price: float, pnl: float, r_multiple: float, reward: float):
        rec = self._pending.pop(rid, None)
        if rec is None:
            return
        rec.exit_price = exit_price
        rec.pnl = pnl
        rec.r_multiple = r_multiple
        rec.reward = reward
        rec.done = True
        self._append(rec)

    def _append(self, rec: SetupLogRecord):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec)) + "\n")
