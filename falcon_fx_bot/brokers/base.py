"""Abstract broker interface used by the trading pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class OrderResult:
    success: bool
    broker: str
    trade_id: str
    pair: str
    units: float
    entry_price: float
    sl: float
    tp: float
    raw: Dict[str, Any]
    message: str = ""


class Broker(ABC):
    name: str

    def connect(self) -> None:
        return None

    @abstractmethod
    def get_balance(self) -> float:
        """Return account balance in ZAR where possible."""

    @abstractmethod
    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Return open trades."""

    @abstractmethod
    def place_market_order(self, pair: str, units: float, sl: float, tp: float, side: str = "BUY") -> OrderResult:
        """Place a market order."""

    @abstractmethod
    def close_trade(self, trade_id: str) -> bool:
        """Close a broker trade/order by id."""

    @abstractmethod
    def get_account_summary(self) -> Dict[str, Any]:
        """Return broker account summary."""

    def close_all_trades(self) -> int:
        closed = 0
        for trade in self.get_open_trades():
            trade_id: Optional[str] = str(trade.get("id") or trade.get("tradeID") or trade.get("ticket") or "")
            if trade_id and self.close_trade(trade_id):
                closed += 1
        return closed

