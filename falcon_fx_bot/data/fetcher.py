"""Market data retrieval using yfinance."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict

import pandas as pd
import requests
import yfinance as yf
import logging

from falcon_fx_bot.config import Config, settings

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    def __init__(self, config: Config = settings) -> None:
        self.config = config

    def yahoo_symbol(self, pair: str) -> str:
        return self.config.yf_symbol_map.get(pair.upper(), f"{pair.upper()}=X")

    def fetch(self, pair: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        symbol = self.yahoo_symbol(pair)
        data = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
        if data.empty:
            raise ValueError(f"No market data returned for {pair} ({symbol})")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        return data.dropna()

    @lru_cache(maxsize=16)
    def usd_zar_rate(self) -> float:
        try:
            data = yf.download("ZAR=X", period="5d", interval="1d", progress=False, auto_adjust=True)
            if not data.empty:
                value = float(data["Close"].dropna().iloc[-1])
                if value > 0:
                    return value
        except Exception as exc:
            logger.warning("Yahoo USD/ZAR lookup failed, trying exchange-rate fallback: %s", exc)
        try:
            response = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=ZAR", timeout=8)
            response.raise_for_status()
            return float(response.json()["rates"]["ZAR"])
        except Exception as exc:
            raise RuntimeError("Unable to fetch live USD/ZAR exchange rate") from exc

    def latest_prices(self) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        for pair in self.config.allowed_instruments:
            try:
                data = self.fetch(pair, period="5d", interval="1d")
                prices[pair] = float(data["Close"].iloc[-1])
            except Exception:
                continue
        return prices
