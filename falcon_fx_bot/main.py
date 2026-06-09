"""Flask webhook server and scheduled bot maintenance."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request

from falcon_fx_bot.brokers import get_broker
from falcon_fx_bot.config import settings
from falcon_fx_bot.logs.trade_log import TradeLog
from falcon_fx_bot.notifications.alerts import AlertService
from falcon_fx_bot.risk.manager import RiskManager
from falcon_fx_bot.strategy.filters import DuplicateFilter, NewsFilter, SessionFilter
from falcon_fx_bot.strategy.mtf_check import MultiTimeframeChecker
from falcon_fx_bot.strategy.validator import SignalValidator, TradingSignal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("falcon_fx")

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=settings.webhook_workers)
trade_log = TradeLog(settings)
alerts = AlertService(settings)
validator = SignalValidator(settings)
mtf_checker = MultiTimeframeChecker()
session_filter = SessionFilter()
news_filter = NewsFilter(settings)
duplicate_filter = DuplicateFilter(trade_log, settings)


class DryRunBroker:
    name = "dry_run"

    def get_balance(self) -> float:
        return settings.dry_run_balance_zar

    def get_open_trades(self) -> list[dict[str, Any]]:
        return []

    def place_market_order(self, pair: str, units: float, sl: float, tp: float, side: str = "BUY") -> Any:
        from falcon_fx_bot.brokers.base import OrderResult

        return OrderResult(True, self.name, f"DRY-{trade_log.now().timestamp():.0f}", pair, units, 0.0, sl, tp, {}, "Dry-run order accepted")

    def close_trade(self, trade_id: str) -> bool:
        return True

    def get_account_summary(self) -> dict[str, Any]:
        return {"account": {"balance": settings.dry_run_balance_zar, "currency": "ZAR"}, "mode": "dry_run"}


def active_broker() -> Any:
    if settings.live_trading:
        broker = get_broker(settings)
        broker.connect()
        return broker
    return DryRunBroker()


def validate_webhook_auth(payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not settings.webhook_secret:
        return True, "No webhook secret configured"
    supplied = request.headers.get("X-Webhook-Secret") or str(payload.get("secret", ""))
    if supplied != settings.webhook_secret:
        return False, "Invalid webhook secret"
    return True, "Authorized"


@app.post("/webhook")
def webhook() -> Any:
    payload = request.get_json(silent=True) or {}
    ok, reason = validate_webhook_auth(payload)
    if not ok:
        return jsonify({"status": "rejected", "reason": reason}), 401
    try:
        signal = validator.parse(payload)
    except Exception as exc:
        return jsonify({"status": "rejected", "reason": str(exc)}), 400
    record_id = trade_log.create_signal(signal)
    executor.submit(process_signal, signal, record_id)
    return jsonify({"status": "accepted", "record_id": record_id}), 200


def reject(record_id: int, reason: str) -> None:
    logger.info("Rejected trade %s: %s", record_id, reason)
    trade_log.update(record_id, status="rejected", reason=reason)


def process_signal(signal: TradingSignal, record_id: int) -> None:
    try:
        session = session_filter.evaluate(signal)
        if not session.allowed:
            reject(record_id, session.reason)
            return
        news = news_filter.evaluate(signal)
        if not news.allowed:
            reject(record_id, news.reason)
            return
        duplicate = duplicate_filter.evaluate(signal)
        if not duplicate.allowed:
            reject(record_id, duplicate.reason)
            return
        mtf = mtf_checker.validate(signal.pair, signal.signal)
        if not mtf.accepted:
            reject(record_id, mtf.reason)
            return
        broker = active_broker()
        risk_manager = RiskManager(broker, trade_log, settings)
        risk = risk_manager.evaluate(signal, size_multiplier=session.size_multiplier)
        if not risk.approved:
            reject(record_id, risk.reason)
            if "daily loss" in risk.reason.lower():
                alerts.daily_loss_hit(f"Trading paused: {risk.reason}")
            return
        result = broker.place_market_order(signal.pair, risk.units, signal.sl, signal.tp1, signal.signal)
        status = "opened" if settings.live_trading else "dry_run_opened"
        trade_log.update(
            record_id,
            status=status,
            reason=result.message,
            units=result.units,
            risk_zar=risk.risk_amount_zar,
            rr_ratio=risk.rr_ratio,
            broker=result.broker,
            broker_trade_id=result.trade_id,
            is_live=settings.live_trading,
        )
        alerts.trade_opened(signal, risk.risk_amount_zar, settings.risk_per_trade * session.size_multiplier)
        logger.info("Trade %s opened via %s", record_id, result.broker)
    except Exception as exc:
        logger.exception("Signal processing failed")
        trade_log.update(record_id, status="error", reason=str(exc))
        alerts.system_error(str(exc))


def daily_health_check() -> None:
    try:
        broker = active_broker()
        summary = broker.get_account_summary()
        logger.info("Daily health check: %s", summary)
    except Exception as exc:
        logger.warning("Health check failed: %s", exc)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Africa/Johannesburg")
    scheduler.add_job(daily_health_check, "cron", hour=8, minute=0, id="daily_health_check", replace_existing=True)
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    create_scheduler()
    app.run(host="0.0.0.0", port=5000, threaded=True)

