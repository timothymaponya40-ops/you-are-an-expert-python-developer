"""Streamlit dashboard for Falcon FX Bot."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from falcon_fx_bot.brokers import get_broker
from falcon_fx_bot.config import SAST, settings
from falcon_fx_bot.data.fetcher import MarketDataFetcher
from falcon_fx_bot.logs.trade_log import TradeLog


def zar(value: float) -> str:
    return f"R{value:,.2f}"


@st.cache_resource(show_spinner=False)
def get_trade_log() -> TradeLog:
    return TradeLog(settings)


@st.cache_resource(show_spinner=False)
def get_fetcher() -> MarketDataFetcher:
    return MarketDataFetcher(settings)


def get_dashboard_broker() -> Any:
    if settings.live_trading:
        broker = get_broker(settings)
        broker.connect()
        return broker

    class DryRunDashboardBroker:
        def get_balance(self) -> float:
            return settings.dry_run_balance_zar

        def get_open_trades(self) -> list[dict[str, Any]]:
            return []

        def close_all_trades(self) -> int:
            return 0

    return DryRunDashboardBroker()


st.set_page_config(page_title="Falcon FX Bot", layout="wide")
st.title("Falcon FX Bot")

trade_log = get_trade_log()
broker = get_dashboard_broker()
fetcher = get_fetcher()

balance = float(broker.get_balance())
today_pnl = trade_log.today_pnl_zar()
win_rate = trade_log.win_rate()
week_start = trade_log.now() - timedelta(days=7)
weekly_trades = trade_log.trades_since(week_start)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Account balance", zar(balance))
col2.metric("Today's P&L", zar(today_pnl), f"{(today_pnl / balance * 100) if balance else 0:.2f}%")
col3.metric("Win rate", f"{win_rate:.1%}")
col4.metric("Trades this week", str(len(weekly_trades)))

if st.button("Emergency close all trades", type="primary"):
    closed = broker.close_all_trades()
    st.warning(f"Emergency stop submitted. Closed {closed} open trade(s).")

left, right = st.columns([1, 1])
with left:
    st.subheader("Open trades")
    open_trades = broker.get_open_trades()
    st.dataframe(pd.DataFrame(open_trades), use_container_width=True, hide_index=True)

with right:
    st.subheader("Live prices")
    prices = fetcher.latest_prices()
    price_rows = [{"pair": pair, "price": price} for pair, price in prices.items()]
    st.dataframe(pd.DataFrame(price_rows), use_container_width=True, hide_index=True)

history = trade_log.dataframe()
st.subheader("Trade history")
if history.empty:
    st.info("No trades logged yet.")
else:
    history["created_at"] = pd.to_datetime(history["created_at"]).dt.tz_convert(SAST)
    pair_filter = st.multiselect("Pair", sorted(history["pair"].dropna().unique().tolist()), default=[])
    status_filter = st.multiselect("Status", sorted(history["status"].dropna().unique().tolist()), default=[])
    filtered = history.copy()
    if pair_filter:
        filtered = filtered[filtered["pair"].isin(pair_filter)]
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]
    st.dataframe(
        filtered.sort_values("created_at", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={"pnl_zar": st.column_config.NumberColumn("P&L", format="R %.2f")},
    )
    equity = filtered.sort_values("created_at").copy()
    equity["equity_zar"] = balance + equity["pnl_zar"].fillna(0).cumsum()
    fig = px.line(equity, x="created_at", y="equity_zar", title="Equity curve", labels={"equity_zar": "Equity (ZAR)", "created_at": "Date"})
    st.plotly_chart(fig, use_container_width=True)

st.caption(f"SAST timezone: {trade_log.now().strftime('%Y-%m-%d %H:%M:%S %Z')} | Live trading: {settings.live_trading}")

