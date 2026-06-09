"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
import pytz

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")
DEFAULT_SQLITE_URL = f"sqlite:///{(BASE_DIR / 'falcon_fx.sqlite3').as_posix()}"

SAST = pytz.timezone("Africa/Johannesburg")


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    app_env: str = os.getenv("APP_ENV", "production")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "")
    broker: str = os.getenv("BROKER", "oanda").lower()
    live_trading: bool = _bool("LIVE_TRADING", False)
    default_account_currency: str = os.getenv("ACCOUNT_CURRENCY", "ZAR")
    base_currency: str = "ZAR"
    risk_per_trade: float = _float("RISK_PER_TRADE", 0.01)
    max_daily_loss_pct: float = _float("MAX_DAILY_LOSS_PCT", 0.03)
    max_open_trades: int = _int("MAX_OPEN_TRADES", 3)
    min_rr_ratio: float = _float("MIN_RR_RATIO", 1.5)
    use_kelly: bool = _bool("USE_KELLY", False)
    kelly_win_rate: float = _float("KELLY_WIN_RATE", 0.55)
    kelly_win_loss_ratio: float = _float("KELLY_WIN_LOSS_RATIO", 1.5)
    kelly_fraction_cap: float = _float("KELLY_FRACTION_CAP", 0.02)
    webhook_workers: int = _int("WEBHOOK_WORKERS", 4)
    duplicate_window_hours: int = _int("DUPLICATE_WINDOW_HOURS", 4)
    database_url: str = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)
    news_filter_enabled: bool = _bool("NEWS_FILTER_ENABLED", True)
    high_impact_news_window_minutes: int = _int("HIGH_IMPACT_NEWS_WINDOW_MINUTES", 60)
    news_events_csv: str = os.getenv("NEWS_EVENTS_CSV", "")
    dry_run_balance_zar: float = _float("DRY_RUN_BALANCE_ZAR", 45000.0)
    allowed_instruments: List[str] = field(
        default_factory=lambda: [item.strip().upper() for item in os.getenv(
            "ALLOWED_INSTRUMENTS",
            "XAUUSD,EURUSD,GBPUSD,USDJPY,USDZAR,EURZAR,GBPZAR,NAS100",
        ).split(",") if item.strip()]
    )
    instrument_map: Dict[str, str] = field(default_factory=lambda: {
        "XAUUSD": "XAU_USD",
        "EURUSD": "EUR_USD",
        "GBPUSD": "GBP_USD",
        "USDJPY": "USD_JPY",
        "USDZAR": "USD_ZAR",
        "EURZAR": "EUR_ZAR",
        "GBPZAR": "GBP_ZAR",
        "NAS100": "NAS100_USD",
    })
    yf_symbol_map: Dict[str, str] = field(default_factory=lambda: {
        "XAUUSD": "GC=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "USDZAR": "ZAR=X",
        "EURZAR": "EURZAR=X",
        "GBPZAR": "GBPZAR=X",
        "NAS100": "NQ=F",
    })
    oanda_api_key: str = os.getenv("OANDA_API_KEY", "")
    oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_environment: str = os.getenv("OANDA_ENVIRONMENT", "practice").lower()
    fxcm_token: str = os.getenv("FXCM_TOKEN", "")
    fxcm_server: str = os.getenv("FXCM_SERVER", "demo")
    mt5_login: int = _int("MT5_LOGIN", 0)
    mt5_password: str = os.getenv("MT5_PASSWORD", "")
    mt5_server: str = os.getenv("MT5_SERVER", "Exness-MT5Real")
    mt5_path: str = os.getenv("MT5_PATH", "")
    mt5_magic: int = _int("MT5_MAGIC", 20260608)
    mt5_deviation: int = _int("MT5_DEVIATION", 20)
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_whatsapp_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    twilio_whatsapp_to: str = os.getenv("TWILIO_WHATSAPP_TO", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = _int("SMTP_PORT", 587)
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_to: str = os.getenv("EMAIL_TO", "")

    @property
    def oanda_url(self) -> str:
        if self.oanda_environment == "live":
            return "https://api-fxtrade.oanda.com/v3"
        return "https://api-fxpractice.oanda.com/v3"


settings = Config()
