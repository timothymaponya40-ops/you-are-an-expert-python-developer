"""OANDA REST broker implementation."""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from falcon_fx_bot.brokers.base import Broker, OrderResult
from falcon_fx_bot.config import Config


class OandaBroker(Broker):
    name = "oanda"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = config.oanda_url
        self.account_id = config.oanda_account_id
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {config.oanda_api_key}", "Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/accounts/{self.account_id}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        if not self.config.oanda_api_key or not self.account_id:
            raise RuntimeError("OANDA_API_KEY and OANDA_ACCOUNT_ID are required")
        response = self.session.request(method, self._url(path), timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()

    def get_balance(self) -> float:
        summary = self.get_account_summary()
        account = summary.get("account", summary)
        balance = float(account.get("balance", self.config.dry_run_balance_zar))
        currency = account.get("currency", self.config.default_account_currency)
        if currency == "ZAR":
            return balance
        if currency == "USD":
            from falcon_fx_bot.data.fetcher import MarketDataFetcher

            return balance * MarketDataFetcher(self.config).usd_zar_rate()
        return balance

    def get_open_trades(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/openTrades").get("trades", [])

    def place_market_order(self, pair: str, units: float, sl: float, tp: float, side: str = "BUY") -> OrderResult:
        instrument = self.config.instrument_map.get(pair.upper(), pair.upper())
        signed_units = int(round(units))
        if side.upper() == "SELL":
            signed_units = -abs(signed_units)
        else:
            signed_units = abs(signed_units)
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(signed_units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{sl:.5f}"},
                "takeProfitOnFill": {"price": f"{tp:.5f}"},
            }
        }
        data = self._request("POST", "/orders", json=payload)
        fill = data.get("orderFillTransaction", {})
        trade_id = str(fill.get("tradeOpened", {}).get("tradeID") or fill.get("id") or "")
        entry_price = float(fill.get("price", 0) or 0)
        return OrderResult(True, self.name, trade_id, pair, signed_units, entry_price, sl, tp, data, "OANDA order filled")

    def close_trade(self, trade_id: str) -> bool:
        data = self._request("PUT", f"/trades/{trade_id}/close")
        return "orderFillTransaction" in data or "relatedTransactionIDs" in data

    def get_account_summary(self) -> Dict[str, Any]:
        return self._request("GET", "/summary")

