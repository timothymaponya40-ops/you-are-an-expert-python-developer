"""Broker factory and public broker adapters."""

from __future__ import annotations

from falcon_fx_bot.config import Config, settings
from falcon_fx_bot.brokers.base import Broker


def get_broker(config: Config = settings) -> Broker:
    if config.broker == "oanda":
        from falcon_fx_bot.brokers.oanda import OandaBroker

        return OandaBroker(config)
    if config.broker == "fxcm":
        from falcon_fx_bot.brokers.fxcm import FXCMBroker

        return FXCMBroker(config)
    if config.broker in {"mt5", "metatrader5", "blackstone", "exness", "hfm"}:
        from falcon_fx_bot.brokers.mt5_broker import MT5Broker

        return MT5Broker(config)
    raise ValueError(f"Unsupported broker: {config.broker}")

