"""FXCM broker implementation using fxcmpy."""

from __future__ import annotations

from typing import Any, Dict, List

from falcon_fx_bot.brokers.base import Broker, OrderResult
from falcon_fx_bot.config import Config


class FXCMBroker(Broker):
    name = "fxcm"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.connection: Any = None

    def connect(self) -> None:
        if self.connection is not None:
            return
        if not self.config.fxcm_token:
            raise RuntimeError("FXCM_TOKEN is required")
        import fxcmpy

        self.connection = fxcmpy.fxcmpy(access_token=self.config.fxcm_token, server=self.config.fxcm_server, log_level="error")

    def get_balance(self) -> float:
        self.connect()
        accounts = self.connection.get_accounts()
        balance = float(accounts.iloc[0]["balance"])
        currency = str(accounts.iloc[0].get("currency", self.config.default_account_currency)).upper()
        if currency == "ZAR":
            return balance
        if currency == "USD":
            from falcon_fx_bot.data.fetcher import MarketDataFetcher

            return balance * MarketDataFetcher(self.config).usd_zar_rate()
        return balance

    def get_open_trades(self) -> List[Dict[str, Any]]:
        self.connect()
        trades = self.connection.get_open_positions()
        if trades is None or trades.empty:
            return []
        return trades.to_dict("records")

    def place_market_order(self, pair: str, units: float, sl: float, tp: float, side: str = "BUY") -> OrderResult:
        self.connect()
        is_buy = side.upper() == "BUY"
        amount = max(abs(float(units)) / 1000.0, 0.001)
        symbol = pair[:3] + "/" + pair[3:] if len(pair) == 6 else pair
        order = self.connection.open_trade(
            symbol=symbol,
            is_buy=is_buy,
            is_in_pips=False,
            amount=amount,
            time_in_force="GTC",
            order_type="AtMarket",
            stop=sl,
            limit=tp,
        )
        trade_id = str(getattr(order, "tradeId", "") or getattr(order, "orderId", ""))
        return OrderResult(True, self.name, trade_id, pair, units if is_buy else -abs(units), 0.0, sl, tp, {"order": str(order)}, "FXCM order submitted")

    def close_trade(self, trade_id: str) -> bool:
        self.connect()
        self.connection.close_trade(trade_id=trade_id, amount="ALL")
        return True

    def get_account_summary(self) -> Dict[str, Any]:
        self.connect()
        return {
            "accounts": self.connection.get_accounts().to_dict("records"),
            "open_positions": self.get_open_trades(),
        }

