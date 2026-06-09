"""Risk controls and position sizing for ZAR accounts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from falcon_fx_bot.config import Config, settings
from falcon_fx_bot.data.fetcher import MarketDataFetcher
from falcon_fx_bot.strategy.validator import TradingSignal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    units: float = 0.0
    risk_amount_zar: float = 0.0
    rr_ratio: float = 0.0
    size_multiplier: float = 1.0


class RiskManager:
    def __init__(self, broker: Any, trade_log: Any, config: Config = settings, fetcher: MarketDataFetcher | None = None) -> None:
        self.broker = broker
        self.trade_log = trade_log
        self.config = config
        self.fetcher = fetcher or MarketDataFetcher(config)

    def evaluate(self, signal: TradingSignal, size_multiplier: float = 1.0) -> RiskDecision:
        open_trades = self.broker.get_open_trades()
        if len(open_trades) >= self.config.max_open_trades:
            return RiskDecision(False, f"Maximum open trades reached ({self.config.max_open_trades})")
        balance_zar = float(self.broker.get_balance())
        daily_loss_zar = abs(float(self.trade_log.today_realized_loss_zar()))
        if daily_loss_zar >= balance_zar * self.config.max_daily_loss_pct:
            return RiskDecision(False, "Maximum daily loss limit reached")
        sl_distance = abs(signal.price - signal.sl)
        tp_distance = abs(signal.tp1 - signal.price)
        if sl_distance <= 0:
            return RiskDecision(False, "Invalid stop-loss distance")
        rr_ratio = tp_distance / sl_distance
        if rr_ratio < self.config.min_rr_ratio:
            return RiskDecision(False, f"R:R {rr_ratio:.2f} below minimum {self.config.min_rr_ratio:.2f}", rr_ratio=rr_ratio)
        risk_fraction = self._risk_fraction(rr_ratio)
        risk_amount_zar = balance_zar * risk_fraction * size_multiplier
        pip_size = self._pip_size(signal.pair)
        sl_pips = sl_distance / pip_size
        pip_value_zar = self._pip_value_zar(signal.pair)
        units = risk_amount_zar / (sl_pips * pip_value_zar)
        if signal.signal == "SELL":
            units = -abs(units)
        else:
            units = abs(units)
        if abs(units) < 0.01:
            return RiskDecision(False, "Calculated position size is too small", rr_ratio=rr_ratio)
        return RiskDecision(True, "Risk approved", units=round(units, 2), risk_amount_zar=round(risk_amount_zar, 2), rr_ratio=round(rr_ratio, 2), size_multiplier=size_multiplier)

    def _risk_fraction(self, rr_ratio: float) -> float:
        if not self.config.use_kelly:
            return self.config.risk_per_trade
        win_rate = min(max(self.config.kelly_win_rate, 0.01), 0.99)
        payoff = max(self.config.kelly_win_loss_ratio or rr_ratio, 0.01)
        kelly = win_rate - ((1 - win_rate) / payoff)
        return min(max(kelly, 0.0), self.config.kelly_fraction_cap)

    @staticmethod
    def _pip_size(pair: str) -> float:
        if pair == "XAUUSD":
            return 0.01
        if pair.endswith("JPY"):
            return 0.01
        return 0.0001

    def _pip_value_zar(self, pair: str) -> float:
        usd_zar = self.fetcher.usd_zar_rate()
        if pair == "XAUUSD":
            return 0.01 * usd_zar
        if pair.endswith("ZAR"):
            return 1.0
        if pair.startswith("USD"):
            return 10.0
        return 10.0 * usd_zar

    def account_snapshot(self) -> Dict[str, float]:
        balance = float(self.broker.get_balance())
        return {
            "balance_zar": balance,
            "daily_loss_limit_zar": balance * self.config.max_daily_loss_pct,
            "risk_per_trade_zar": balance * self.config.risk_per_trade,
        }

