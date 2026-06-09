"""Falcon FX multi-timeframe validation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from falcon_fx_bot.data.fetcher import MarketDataFetcher


@dataclass(frozen=True)
class MTFResult:
    accepted: bool
    reason: str
    d1_close: float
    d1_ema200: float
    h4_close: float
    h4_ema50: float


class MultiTimeframeChecker:
    def __init__(self, fetcher: MarketDataFetcher | None = None) -> None:
        self.fetcher = fetcher or MarketDataFetcher()

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def validate(self, pair: str, signal: str) -> MTFResult:
        signal = signal.upper()
        d1 = self.fetcher.fetch(pair, period="1y", interval="1d")
        h4 = self.fetcher.fetch(pair, period="6mo", interval="4h")
        d1_close = d1["Close"].astype(float)
        h4_close = h4["Close"].astype(float)
        d1_ema200 = self._ema(d1_close, 200)
        h4_ema50 = self._ema(h4_close, 50)
        latest_d1 = float(d1_close.iloc[-1])
        latest_d1_ema200 = float(d1_ema200.iloc[-1])
        latest_h4 = float(h4_close.iloc[-1])
        latest_h4_ema50 = float(h4_ema50.iloc[-1])
        if signal == "BUY":
            accepted = latest_d1 > latest_d1_ema200 and latest_h4 > latest_h4_ema50
        elif signal == "SELL":
            accepted = latest_d1 < latest_d1_ema200 and latest_h4 < latest_h4_ema50
        else:
            return MTFResult(False, f"Unsupported signal {signal}", latest_d1, latest_d1_ema200, latest_h4, latest_h4_ema50)
        reason = "HTF bias agrees with signal" if accepted else (
            f"HTF bias rejects {signal}: D1 close {latest_d1:.5f} vs EMA200 {latest_d1_ema200:.5f}, "
            f"H4 close {latest_h4:.5f} vs EMA50 {latest_h4_ema50:.5f}"
        )
        return MTFResult(accepted, reason, latest_d1, latest_d1_ema200, latest_h4, latest_h4_ema50)

