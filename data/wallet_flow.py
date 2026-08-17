"""
Smart-wallet / top-wallet flow feature provider.

Maintains a short rolling window of net flows for a curated set of wallets
and exposes features that the probability scorer can consume.

In production you would replace the synthetic updater with real on-chain
data (Bitquery, Dune, Arkham-labeled wallets, etc.).
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Deque, Optional, List
import random

logger = logging.getLogger("sniper.wallet_flow")


@dataclass
class FlowSnapshot:
    ts: float
    net_usd: float
    exchange_ratio: float
    buyers: int
    sellers: int


@dataclass
class WalletFeatures:
    net_flow: float
    flow_zscore: float
    exchange_deposit_ratio: float
    accumulation_score: float
    alignment: int
    raw: Dict = field(default_factory=dict)


class WalletFlowCache:
    def __init__(
        self,
        window_seconds: float = 4 * 3600,
        min_samples: int = 3,
        zscore_clip: float = 3.0,
    ):
        self.window_seconds = window_seconds
        self.min_samples = min_samples
        self.zscore_clip = zscore_clip
        self._history: Dict[str, Deque[FlowSnapshot]] = defaultdict(
            lambda: deque(maxlen=500)
        )
        self.watched_wallets: List[str] = [
            f"smart_wallet_{i}" for i in range(1, 51)
        ]

    def update(self, symbol: str, snapshot: FlowSnapshot):
        hist = self._history[symbol]
        hist.append(snapshot)
        self._prune(symbol)

    def _prune(self, symbol: str):
        cutoff = time.time() - self.window_seconds
        hist = self._history[symbol]
        while hist and hist[0].ts < cutoff:
            hist.popleft()

    def get_features(self, symbol: str, direction: str = "long") -> WalletFeatures:
        self._prune(symbol)
        hist = list(self._history[symbol])

        if len(hist) < self.min_samples:
            return WalletFeatures(
                net_flow=0.0,
                flow_zscore=0.0,
                exchange_deposit_ratio=0.0,
                accumulation_score=0.0,
                alignment=0,
                raw={"samples": len(hist)},
            )

        nets = [s.net_usd for s in hist]
        mean_net = sum(nets) / len(nets)
        var = sum((x - mean_net) ** 2 for x in nets) / max(len(nets) - 1, 1)
        std = var ** 0.5 or 1e-9
        latest = hist[-1]
        z = max(-self.zscore_clip, min(self.zscore_clip, (latest.net_usd - mean_net) / std))

        total_actors = latest.buyers + latest.sellers
        accum = (latest.buyers - latest.sellers) / max(total_actors, 1)

        if direction == "long":
            alignment = 1 if (z > 0.4 or accum > 0.2) else (-1 if (z < -0.4 or accum < -0.2) else 0)
        else:
            alignment = 1 if (z < -0.4 or accum < -0.2) else (-1 if (z > 0.4 or accum > 0.2) else 0)

        return WalletFeatures(
            net_flow=latest.net_usd,
            flow_zscore=z,
            exchange_deposit_ratio=latest.exchange_ratio,
            accumulation_score=accum,
            alignment=alignment,
            raw={
                "samples": len(hist),
                "mean_net": mean_net,
                "latest_buyers": latest.buyers,
                "latest_sellers": latest.sellers,
            },
        )

    def simulate_tick(self, symbol: str):
        snap = FlowSnapshot(
            ts=time.time(),
            net_usd=random.gauss(0, 250_000),
            exchange_ratio=random.uniform(0.1, 0.7),
            buyers=random.randint(5, 30),
            sellers=random.randint(5, 30),
        )
        self.update(symbol, snap)
        return snap
