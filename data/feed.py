"""
Production candle feed with WebSocket streaming + REST fallback.

Uses ccxt.pro-style watch_ohlcv when available (true WebSocket).
Falls back to efficient REST polling if the exchange or environment
does not support streaming.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger("sniper.feed")


class CandleFeed:
    """
    Hybrid candle feed.

    - backfill()          → REST historical load
    - start_streaming()   → WebSocket watch_ohlcv loops (preferred)
    - poll()              → REST fallback (still available)
    - subscribe()         → closed-candle callbacks (same interface either way)
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        sandbox: bool = True,
        api_key: str = "",
        secret: str = "",
        default_type: str = "future",
    ):
        self.exchange_id = exchange_id
        self.sandbox = sandbox
        self.api_key = api_key
        self.secret = secret
        self.default_type = default_type

        self.exchange = self._build_exchange(sync=True)
        self.async_exchange = None

        self.candles: Dict[str, Dict[str, pd.DataFrame]] = defaultdict(dict)
        self._last_closed_ts: Dict[str, int] = {}
        self._callbacks: List[Callable] = []

        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._watched: Set[Tuple[str, str]] = set()
        self._lock = threading.RLock()
        self._ws_supported: Optional[bool] = None

    def _build_exchange(self, sync: bool = True):
        import ccxt

        if not sync:
            try:
                import ccxt.pro as ccxtpro
                exchange_class = getattr(ccxtpro, self.exchange_id, None)
                if exchange_class is not None:
                    return self._configure(exchange_class())
            except Exception as e:
                logger.warning("ccxt.pro not available (%s) – will fall back to REST", e)

        exchange_class = getattr(ccxt, self.exchange_id)
        return self._configure(exchange_class())

    def _configure(self, exchange):
        exchange.apiKey = self.api_key or None
        exchange.secret = self.secret or None
        exchange.enableRateLimit = True
        if self.default_type:
            exchange.options = exchange.options or {}
            exchange.options["defaultType"] = self.default_type
        if self.sandbox and hasattr(exchange, "set_sandbox_mode"):
            try:
                exchange.set_sandbox_mode(True)
            except Exception:
                pass
        return exchange

    def subscribe(self, callback: Callable):
        self._callbacks.append(callback)

    def backfill(self, symbol: str, timeframe: str = "1m", limit: int = 500) -> pd.DataFrame:
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = self._to_df(ohlcv)
        with self._lock:
            self.candles[symbol][timeframe] = df
            if not df.empty:
                self._last_closed_ts[f"{symbol}|{timeframe}"] = int(
                    df.index[-1].timestamp() * 1000
                )
        return df

    def get_df(self, symbol: str, timeframe: str = "1m") -> Optional[pd.DataFrame]:
        with self._lock:
            return self.candles.get(symbol, {}).get(timeframe)

    def watch(self, symbol: str, timeframe: str = "1m"):
        self._watched.add((symbol, timeframe))

    def start_streaming(self):
        if self._stream_thread and self._stream_thread.is_alive():
            logger.info("Streaming already running")
            return

        if not self._watched:
            logger.warning("No symbols registered via watch() – nothing to stream")
            return

        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._streaming_thread_main,
            name="candle-ws",
            daemon=True,
        )
        self._stream_thread.start()
        logger.info(
            "WebSocket streaming started for %d streams: %s",
            len(self._watched),
            list(self._watched),
        )

    def stop_streaming(self):
        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=8)
            self._stream_thread = None
        if self.async_exchange is not None:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.async_exchange.close())
                loop.close()
            except Exception:
                pass
            self.async_exchange = None
        logger.info("WebSocket streaming stopped")

    def poll(self, symbol: str, timeframe: str = "1m"):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=5)
        except Exception as e:
            logger.warning("REST fetch error %s %s: %s", symbol, timeframe, e)
            return
        if not ohlcv:
            return
        self._ingest_ohlcv(symbol, timeframe, ohlcv, source="rest")

    def _streaming_thread_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_stream_all())
        except Exception as e:
            logger.exception("Streaming thread crashed: %s", e)
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _async_stream_all(self):
        self.async_exchange = self._build_exchange(sync=False)

        if not hasattr(self.async_exchange, "watch_ohlcv"):
            logger.warning(
                "Exchange %s has no watch_ohlcv – WebSocket streaming unavailable, "
                "use poll() REST fallback",
                self.exchange_id,
            )
            self._ws_supported = False
            return

        self._ws_supported = True
        tasks = [
            asyncio.create_task(self._watch_one(symbol, timeframe))
            for symbol, timeframe in list(self._watched)
        ]
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self.async_exchange.close()
        except Exception:
            pass

    async def _watch_one(self, symbol: str, timeframe: str):
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                ohlcv = await self.async_exchange.watch_ohlcv(symbol, timeframe)
                if ohlcv:
                    self._ingest_ohlcv(symbol, timeframe, ohlcv, source="ws")
                backoff = 1.0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "WS error %s %s: %s – reconnecting in %.1fs",
                    symbol, timeframe, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    def _ingest_ohlcv(self, symbol: str, timeframe: str, ohlcv: list, source: str = "ws"):
        if not ohlcv:
            return

        df_new = self._to_df(ohlcv)
        key = f"{symbol}|{timeframe}"

        with self._lock:
            if symbol not in self.candles or timeframe not in self.candles[symbol]:
                self.candles[symbol][timeframe] = df_new
            else:
                combined = pd.concat([self.candles[symbol][timeframe], df_new])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
                self.candles[symbol][timeframe] = combined.tail(2000)

            last_ts = int(df_new.index[-1].timestamp() * 1000)
            prev_ts = self._last_closed_ts.get(key)

            if prev_ts is not None and last_ts <= prev_ts:
                return

            self._last_closed_ts[key] = last_ts
            df = self.candles[symbol][timeframe].copy()

        for cb in self._callbacks:
            try:
                cb(symbol, timeframe, df)
            except Exception as e:
                logger.exception("Callback error (%s): %s", source, e)

    @staticmethod
    def _to_df(ohlcv: list) -> pd.DataFrame:
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df.astype(float)

    @property
    def is_streaming(self) -> bool:
        return bool(
            self._stream_thread
            and self._stream_thread.is_alive()
            and not self._stop_event.is_set()
        )
