"""MetaTrader 5 broker implementation for Exness, HFM, XM, Blackstone Futures, and other MT5 brokers."""

from __future__ import annotations

from typing import Any, Dict, List

from falcon_fx_bot.brokers.base import Broker, OrderResult
from falcon_fx_bot.config import Config


class MT5Broker(Broker):
    name = "mt5"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.mt5: Any = None
        self.connected = False

    def connect(self) -> None:
        if self.connected:
            return
        import MetaTrader5 as mt5

        self.mt5 = mt5
        kwargs: Dict[str, Any] = {}
        if self.config.mt5_path:
            kwargs["path"] = self.config.mt5_path
        initialized = mt5.initialize(**kwargs)
        if not initialized:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if self.config.mt5_login:
            authorized = mt5.login(self.config.mt5_login, password=self.config.mt5_password, server=self.config.mt5_server)
            if not authorized:
                raise RuntimeError(f"MT5 login failed for server {self.config.mt5_server}: {mt5.last_error()}")
        self.connected = True

    def get_balance(self) -> float:
        info = self.get_account_info()
        balance = float(info.get("balance", self.config.dry_run_balance_zar))
        currency = str(info.get("currency", self.config.default_account_currency)).upper()
        if currency == "ZAR":
            return balance
        if currency == "USD":
            from falcon_fx_bot.data.fetcher import MarketDataFetcher

            return balance * MarketDataFetcher(self.config).usd_zar_rate()
        return balance

    def get_open_trades(self) -> List[Dict[str, Any]]:
        self.connect()
        positions = self.mt5.positions_get()
        if positions is None:
            return []
        return [position._asdict() for position in positions]

    def place_market_order(self, pair: str, units: float, sl: float, tp: float, side: str = "BUY") -> OrderResult:
        self.connect()
        symbol = self._symbol(pair)
        if not self.mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol not available: {symbol}")
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No MT5 tick for {symbol}")
        is_buy = side.upper() == "BUY"
        order_type = self.mt5.ORDER_TYPE_BUY if is_buy else self.mt5.ORDER_TYPE_SELL
        price = float(tick.ask if is_buy else tick.bid)
        volume = self._units_to_lots(pair, abs(units))
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.config.mt5_deviation,
            "magic": self.config.mt5_magic,
            "comment": "Falcon FX Bot",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        result = self.mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"MT5 order_send returned None: {self.mt5.last_error()}")
        result_dict = result._asdict()
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order failed: {result_dict}")
        return OrderResult(True, self.name, str(result.order), pair, units if is_buy else -abs(units), price, sl, tp, result_dict, "MT5 order filled")

    def set_sl_tp(self, ticket: int, symbol: str, sl: float, tp: float) -> bool:
        self.connect()
        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": symbol,
            "sl": float(sl),
            "tp": float(tp),
            "magic": self.config.mt5_magic,
        }
        result = self.mt5.order_send(request)
        return result is not None and result.retcode == self.mt5.TRADE_RETCODE_DONE

    def close_trade(self, trade_id: str) -> bool:
        self.connect()
        positions = self.mt5.positions_get(ticket=int(trade_id))
        if not positions:
            return False
        position = positions[0]
        tick = self.mt5.symbol_info_tick(position.symbol)
        order_type = self.mt5.ORDER_TYPE_SELL if position.type == self.mt5.POSITION_TYPE_BUY else self.mt5.ORDER_TYPE_BUY
        price = tick.bid if order_type == self.mt5.ORDER_TYPE_SELL else tick.ask
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": self.config.mt5_deviation,
            "magic": self.config.mt5_magic,
            "comment": "Falcon FX emergency close",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }
        result = self.mt5.order_send(request)
        return result is not None and result.retcode == self.mt5.TRADE_RETCODE_DONE

    def get_account_info(self) -> Dict[str, Any]:
        self.connect()
        info = self.mt5.account_info()
        if info is None:
            return {"balance": self.config.dry_run_balance_zar, "currency": "ZAR"}
        return info._asdict()

    def get_account_summary(self) -> Dict[str, Any]:
        return {"account": self.get_account_info(), "open_trades": self.get_open_trades(), "server": self.config.mt5_server}

    def _symbol(self, pair: str) -> str:
        overrides = {
            "XAUUSD": "XAUUSD",
            "NAS100": "USTEC",
        }
        return overrides.get(pair.upper(), pair.upper())

    @staticmethod
    def _units_to_lots(pair: str, units: float) -> float:
        if pair == "XAUUSD":
            return round(max(units / 100.0, 0.01), 2)
        return round(max(units / 100000.0, 0.01), 2)

