"""Session, news, and duplicate-trade filters."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from falcon_fx_bot.config import Config, SAST, settings
from falcon_fx_bot.strategy.validator import TradingSignal


@dataclass(frozen=True)
class FilterResult:
    allowed: bool
    reason: str
    size_multiplier: float = 1.0


def now_sast() -> datetime:
    return datetime.now(tz=SAST)


def _between(value: time, start: time, end: time) -> bool:
    return start <= value <= end


class SessionFilter:
    def evaluate(self, signal: TradingSignal, at: Optional[datetime] = None) -> FilterResult:
        current = (at or now_sast()).astimezone(SAST)
        current_time = current.time()
        blocked_windows = (
            (time(8, 30), time(9, 30)),
            (time(16, 30), time(17, 30)),
            (time(21, 30), time(22, 30)),
        )
        if any(_between(current_time, start, end) for start, end in blocked_windows):
            return FilterResult(False, "Blocked around SAST market open/close window")
        london = _between(current_time, time(9, 0), time(17, 0))
        new_york = _between(current_time, time(15, 0), time(22, 0))
        asian_gold = signal.pair == "XAUUSD" and _between(current_time, time(2, 0), time(10, 0))
        if london or new_york:
            return FilterResult(True, "London/New York session")
        if asian_gold:
            return FilterResult(True, "Asian gold liquidity window", 0.5)
        return FilterResult(False, "Outside allowed trading sessions")


class NewsFilter:
    def __init__(self, config: Config = settings) -> None:
        self.config = config

    def evaluate(self, signal: TradingSignal, at: Optional[datetime] = None) -> FilterResult:
        if not self.config.news_filter_enabled:
            return FilterResult(True, "News filter disabled")
        events = list(self._events())
        if not events:
            return FilterResult(True, "No configured high-impact news events")
        current = (at or now_sast()).astimezone(SAST)
        window = timedelta(minutes=self.config.high_impact_news_window_minutes)
        currencies = self._currencies_for_pair(signal.pair)
        for event_time, currency, title in events:
            if currency in currencies and abs(current - event_time) <= window:
                return FilterResult(False, f"High-impact {currency} news: {title}")
        return FilterResult(True, "No conflicting high-impact news")

    def _events(self) -> Iterable[tuple[datetime, str, str]]:
        if not self.config.news_events_csv:
            return []
        path = Path(self.config.news_events_csv)
        if not path.exists():
            return []
        rows = []
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    event_time = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone(SAST)
                    rows.append((event_time, row["currency"].upper(), row.get("title", "Scheduled event")))
                except (KeyError, ValueError):
                    continue
        return rows

    @staticmethod
    def _currencies_for_pair(pair: str) -> set[str]:
        if pair == "XAUUSD":
            return {"USD", "XAU"}
        if len(pair) >= 6:
            return {pair[:3], pair[3:6]}
        return {pair}


class DuplicateFilter:
    def __init__(self, trade_log: "TradeLog", config: Config = settings) -> None:
        self.trade_log = trade_log
        self.config = config

    def evaluate(self, signal: TradingSignal) -> FilterResult:
        since = now_sast() - timedelta(hours=self.config.duplicate_window_hours)
        if self.trade_log.has_recent_trade(signal.pair, since):
            return FilterResult(False, f"Rate limit: {signal.pair} already traded in last {self.config.duplicate_window_hours} hours")
        return FilterResult(True, "No duplicate trade")

