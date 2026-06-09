"""Webhook payload and signal validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from falcon_fx_bot.config import Config, settings


@dataclass(frozen=True)
class TradingSignal:
    signal: str
    pair: str
    timeframe: str
    price: float
    sl: float
    tp1: float
    tp2: float
    timestamp: datetime

    @property
    def side_multiplier(self) -> int:
        return 1 if self.signal == "BUY" else -1


class SignalValidator:
    required = {"signal", "pair", "timeframe", "price", "sl", "tp1", "tp2", "timestamp"}

    def __init__(self, config: Config = settings) -> None:
        self.config = config

    def parse(self, payload: Dict[str, Any]) -> TradingSignal:
        missing = self.required - set(payload)
        if missing:
            raise ValueError(f"Missing required alert fields: {', '.join(sorted(missing))}")
        signal = str(payload["signal"]).upper().strip()
        if signal not in {"BUY", "SELL"}:
            raise ValueError("signal must be BUY or SELL")
        pair = str(payload["pair"]).upper().replace("/", "").strip()
        if pair not in self.config.allowed_instruments:
            raise ValueError(f"pair {pair} is not enabled")
        timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
        trade_signal = TradingSignal(
            signal=signal,
            pair=pair,
            timeframe=str(payload["timeframe"]),
            price=float(payload["price"]),
            sl=float(payload["sl"]),
            tp1=float(payload["tp1"]),
            tp2=float(payload["tp2"]),
            timestamp=timestamp,
        )
        self._validate_geometry(trade_signal)
        return trade_signal

    @staticmethod
    def _validate_geometry(signal: TradingSignal) -> None:
        if signal.signal == "BUY":
            if not signal.sl < signal.price < signal.tp1 <= signal.tp2:
                raise ValueError("BUY requires SL < price < TP1 <= TP2")
        else:
            if not signal.sl > signal.price > signal.tp1 >= signal.tp2:
                raise ValueError("SELL requires SL > price > TP1 >= TP2")

