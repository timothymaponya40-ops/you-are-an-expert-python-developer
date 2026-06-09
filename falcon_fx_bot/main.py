"""Flask webhook server and scheduled bot maintenance."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, request, url_for

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


def sample_alert_payload() -> Dict[str, Any]:
    return {
        "secret": settings.webhook_secret,
        "signal": "BUY",
        "pair": "XAUUSD",
        "timeframe": "15",
        "price": 2345.50,
        "sl": 2330.00,
        "tp1": 2369.00,
        "tp2": 2380.00,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def zar(value: float) -> str:
    return f"R{value:,.2f}"


def _float_from_trade(trade: Dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        value = trade.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def dashboard_snapshot() -> Dict[str, Any]:
    broker = active_broker()
    balance = float(broker.get_balance())
    open_trades = broker.get_open_trades()
    realized_today = float(trade_log.today_pnl_zar())
    closed_trades = [row for row in trade_log.all_trades(limit=500) if row.get("status") == "closed"]
    total_realized = sum(float(row.get("pnl_zar") or 0) for row in closed_trades)
    open_unrealized = sum(
        _float_from_trade(
            trade,
            (
                "unrealizedPL",
                "unrealized_pl",
                "grossPL",
                "gross_pl",
                "profit",
                "pl",
                "pnl",
            ),
        )
        for trade in open_trades
    )
    return {
        "mode": "LIVE" if settings.live_trading else "DRY RUN",
        "broker": settings.broker,
        "balance_zar": balance,
        "today_pnl_zar": realized_today,
        "total_realized_pnl_zar": total_realized,
        "open_unrealized_pnl_zar": open_unrealized,
        "total_estimated_pnl_zar": total_realized + open_unrealized,
        "open_trades": open_trades,
        "history": trade_log.all_trades(limit=100),
    }


@app.get("/")
def home() -> str:
    mode = "LIVE" if settings.live_trading else "DRY RUN"
    return f"""
    <!doctype html>
    <html>
      <head>
        <title>Falcon FX Bot Test</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; max-width: 980px; }}
          .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
          button, a.button {{ background: #111827; color: white; border: 0; border-radius: 6px; padding: 10px 14px; text-decoration: none; cursor: pointer; }}
          .muted {{ color: #555; }}
          code {{ background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }}
        </style>
      </head>
      <body>
        <h1>Falcon FX Bot</h1>
        <div class="card">
          <p><strong>Status:</strong> running</p>
          <p><strong>Mode:</strong> {escape(mode)}</p>
          <p><strong>Webhook:</strong> <code>http://localhost:5000/webhook</code></p>
          <p class="muted">Keep LIVE_TRADING=false while testing.</p>
        </div>
        <div class="card">
          <h2>Quick test</h2>
          <p>This writes a dry-run sample trade to the local database without using broker APIs or yfinance.</p>
          <form method="post" action="/quick-test"><button type="submit">Create quick test trade</button></form>
        </div>
        <div class="card">
          <h2>Full pipeline test</h2>
          <p>This sends a sample alert through session filter, news filter, MTF validation, risk management, and dry-run execution.</p>
          <form method="post" action="/full-test"><button type="submit">Send full test alert</button></form>
        </div>
        <p><a class="button" href="/dashboard">View P/L dashboard</a> <a class="button" href="/broker-test">Test broker connection</a> <a class="button" href="/trades">View trade log</a></p>
      </body>
    </html>
    """


@app.post("/quick-test")
def quick_test() -> Any:
    signal = validator.parse(sample_alert_payload())
    record_id = trade_log.create_signal(signal)
    trade_log.update(
        record_id,
        status="dry_run_opened",
        reason="Manual quick test created from browser",
        units=0.01,
        risk_zar=450.00,
        rr_ratio=1.55,
        broker="dry_run",
        broker_trade_id=f"TEST-{record_id}",
        is_live=False,
    )
    return redirect(url_for("trades"))


@app.post("/full-test")
def full_test() -> Any:
    signal = validator.parse(sample_alert_payload())
    record_id = trade_log.create_signal(signal)
    executor.submit(process_signal, signal, record_id)
    return redirect(url_for("trades"))


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok", "live_trading": settings.live_trading, "broker": settings.broker})


@app.get("/api/dashboard")
def dashboard_api() -> Any:
    return jsonify(dashboard_snapshot())


@app.get("/broker-test")
def broker_test() -> str:
    try:
        broker = active_broker()
        summary = broker.get_account_summary()
        balance = broker.get_balance()
        status = "Connected"
        detail = escape(str(summary))
        balance_line = zar(float(balance))
        color = "#047857"
    except Exception as exc:
        status = "Not connected"
        detail = escape(str(exc))
        balance_line = "Unavailable"
        color = "#b91c1c"
    return f"""
    <!doctype html>
    <html>
      <head>
        <title>Falcon FX Broker Test</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; max-width: 980px; }}
          .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
          .status {{ color: {color}; font-size: 24px; font-weight: 700; }}
          pre {{ background: #f3f4f6; padding: 12px; border-radius: 6px; white-space: pre-wrap; }}
          a.button {{ background: #111827; color: white; border-radius: 6px; padding: 10px 14px; text-decoration: none; }}
        </style>
      </head>
      <body>
        <h1>Broker Connection Test</h1>
        <p><a class="button" href="/">Back to test page</a></p>
        <div class="card">
          <p class="status">{status}</p>
          <p><strong>Configured broker:</strong> {escape(settings.broker)}</p>
          <p><strong>Live trading flag:</strong> {escape(str(settings.live_trading))}</p>
          <p><strong>MT5 preset:</strong> {escape(settings.mt5_broker_preset)}</p>
          <p><strong>MT5 server:</strong> {escape(settings.mt5_effective_server)}</p>
          <p><strong>Balance:</strong> {balance_line}</p>
        </div>
        <h2>Details</h2>
        <pre>{detail}</pre>
      </body>
    </html>
    """


@app.get("/dashboard")
def dashboard() -> str:
    snapshot = dashboard_snapshot()
    open_rows = []
    for trade in snapshot["open_trades"]:
        trade_id = trade.get("id") or trade.get("tradeID") or trade.get("ticket") or trade.get("order") or ""
        symbol = trade.get("instrument") or trade.get("symbol") or trade.get("currency") or trade.get("pair") or ""
        units = trade.get("currentUnits") or trade.get("amountK") or trade.get("volume") or trade.get("units") or ""
        pnl = _float_from_trade(trade, ("unrealizedPL", "grossPL", "profit", "pl", "pnl"))
        open_rows.append(
            "<tr>"
            f"<td>{escape(str(trade_id))}</td>"
            f"<td>{escape(str(symbol))}</td>"
            f"<td>{escape(str(units))}</td>"
            f"<td>{zar(pnl)}</td>"
            "</tr>"
        )
    history_rows = []
    for row in snapshot["history"]:
        history_rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('created_at', '')))}</td>"
            f"<td>{escape(str(row.get('pair', '')))}</td>"
            f"<td>{escape(str(row.get('signal', '')))}</td>"
            f"<td>{escape(str(row.get('status', '')))}</td>"
            f"<td>{zar(float(row.get('risk_zar') or 0))}</td>"
            f"<td>{zar(float(row.get('pnl_zar') or 0))}</td>"
            f"<td>{escape(str(row.get('reason', '')))}</td>"
            "</tr>"
        )
    open_body = "\n".join(open_rows) or "<tr><td colspan='4'>No broker open trades reported.</td></tr>"
    history_body = "\n".join(history_rows) or "<tr><td colspan='7'>No trades logged yet.</td></tr>"
    dry_note = ""
    if not settings.live_trading:
        dry_note = "<p class='warning'>Dry-run mode is on. This page shows test trades and local log values, not real market P/L.</p>"
    return f"""
    <!doctype html>
    <html>
      <head>
        <title>Falcon FX P/L Dashboard</title>
        <meta http-equiv="refresh" content="15">
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; color: #111827; }}
          .grid {{ display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }}
          .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 14px; }}
          .label {{ color: #555; font-size: 13px; }}
          .value {{ font-size: 22px; font-weight: 700; margin-top: 6px; }}
          .profit {{ color: #047857; }}
          .loss {{ color: #b91c1c; }}
          .warning {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 10px; border-radius: 6px; }}
          table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
          th {{ background: #f3f4f6; }}
          a.button {{ background: #111827; color: white; border-radius: 6px; padding: 10px 14px; text-decoration: none; }}
        </style>
      </head>
      <body>
        <h1>Falcon FX P/L Dashboard</h1>
        <p><a class="button" href="/">Back to test page</a> <a class="button" href="/api/dashboard">View JSON</a></p>
        {dry_note}
        <div class="grid">
          <div class="card"><div class="label">Mode</div><div class="value">{escape(snapshot['mode'])}</div></div>
          <div class="card"><div class="label">Balance</div><div class="value">{zar(snapshot['balance_zar'])}</div></div>
          <div class="card"><div class="label">Today P/L</div><div class="value {'profit' if snapshot['today_pnl_zar'] >= 0 else 'loss'}">{zar(snapshot['today_pnl_zar'])}</div></div>
          <div class="card"><div class="label">Open P/L</div><div class="value {'profit' if snapshot['open_unrealized_pnl_zar'] >= 0 else 'loss'}">{zar(snapshot['open_unrealized_pnl_zar'])}</div></div>
          <div class="card"><div class="label">Total P/L</div><div class="value {'profit' if snapshot['total_estimated_pnl_zar'] >= 0 else 'loss'}">{zar(snapshot['total_estimated_pnl_zar'])}</div></div>
        </div>
        <h2>Open Trades From Broker</h2>
        <table>
          <thead><tr><th>ID</th><th>Symbol</th><th>Size</th><th>Unrealized P/L</th></tr></thead>
          <tbody>{open_body}</tbody>
        </table>
        <h2>Robot Trade History</h2>
        <table>
          <thead><tr><th>Date</th><th>Pair</th><th>Signal</th><th>Status</th><th>Risk</th><th>Closed P/L</th><th>Reason</th></tr></thead>
          <tbody>{history_body}</tbody>
        </table>
      </body>
    </html>
    """


@app.get("/trades")
def trades() -> str:
    rows = trade_log.all_trades(limit=50)
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('created_at', '')))}</td>"
            f"<td>{escape(str(row.get('pair', '')))}</td>"
            f"<td>{escape(str(row.get('signal', '')))}</td>"
            f"<td>{escape(str(row.get('status', '')))}</td>"
            f"<td>R{float(row.get('risk_zar') or 0):,.2f}</td>"
            f"<td>{escape(str(row.get('broker_trade_id', '')))}</td>"
            f"<td>{escape(str(row.get('reason', '')))}</td>"
            "</tr>"
        )
    body = "\n".join(table_rows) or "<tr><td colspan='7'>No trades logged yet.</td></tr>"
    return f"""
    <!doctype html>
    <html>
      <head>
        <title>Falcon FX Trades</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 32px; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
          th {{ background: #f3f4f6; }}
          a.button {{ background: #111827; color: white; border-radius: 6px; padding: 10px 14px; text-decoration: none; }}
        </style>
      </head>
      <body>
        <h1>Trade Log</h1>
        <p><a class="button" href="/">Back to test page</a> <a class="button" href="/dashboard">View P/L dashboard</a></p>
        <table>
          <thead>
            <tr><th>Date</th><th>Pair</th><th>Signal</th><th>Status</th><th>Risk</th><th>Trade ID</th><th>Reason</th></tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </body>
    </html>
    """


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
