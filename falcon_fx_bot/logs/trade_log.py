"""SQLite trade journal using SQLAlchemy."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, create_engine, desc, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from falcon_fx_bot.config import Config, SAST, settings

Base = declarative_base()


class TradeRecord(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    pair = Column(String(20), nullable=False, index=True)
    signal = Column(String(8), nullable=False)
    timeframe = Column(String(10), nullable=False)
    price = Column(Float, nullable=False)
    sl = Column(Float, nullable=False)
    tp1 = Column(Float, nullable=False)
    tp2 = Column(Float, nullable=False)
    units = Column(Float, default=0.0)
    risk_zar = Column(Float, default=0.0)
    rr_ratio = Column(Float, default=0.0)
    broker = Column(String(30), default="")
    broker_trade_id = Column(String(80), default="")
    status = Column(String(30), nullable=False, default="received")
    reason = Column(String(500), default="")
    pnl_zar = Column(Float, default=0.0)
    is_live = Column(Boolean, default=False)


class TradeLog:
    def __init__(self, config: Config = settings) -> None:
        self.config = config
        self.engine = create_engine(config.database_url, future=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=SAST)

    def create_signal(self, signal: Any) -> int:
        now = self.now()
        record = TradeRecord(
            created_at=now,
            updated_at=now,
            pair=signal.pair,
            signal=signal.signal,
            timeframe=signal.timeframe,
            price=signal.price,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            status="received",
        )
        with self.SessionLocal() as session:
            session.add(record)
            session.commit()
            return int(record.id)

    def update(self, record_id: int, **fields: Any) -> None:
        with self.SessionLocal() as session:
            record = session.get(TradeRecord, record_id)
            if record is None:
                return
            for key, value in fields.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.updated_at = self.now()
            session.commit()

    def log_rejection(self, signal: Any, reason: str) -> None:
        record_id = self.create_signal(signal)
        self.update(record_id, status="rejected", reason=reason)

    def has_recent_trade(self, pair: str, since: datetime) -> bool:
        with self.SessionLocal() as session:
            statement = select(TradeRecord).where(
                TradeRecord.pair == pair,
                TradeRecord.created_at >= since,
                TradeRecord.status.in_(["opened", "dry_run_opened"]),
            )
            return session.execute(statement).first() is not None

    def today_realized_loss_zar(self) -> float:
        start = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.SessionLocal() as session:
            rows = session.execute(select(TradeRecord.pnl_zar).where(TradeRecord.updated_at >= start, TradeRecord.pnl_zar < 0)).all()
        return float(sum(value for (value,) in rows if value))

    def today_pnl_zar(self) -> float:
        start = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.SessionLocal() as session:
            rows = session.execute(select(TradeRecord.pnl_zar).where(TradeRecord.updated_at >= start)).all()
        return float(sum(value for (value,) in rows if value))

    def trades_since(self, since: datetime) -> List[Dict[str, Any]]:
        with self.SessionLocal() as session:
            records = session.execute(select(TradeRecord).where(TradeRecord.created_at >= since).order_by(desc(TradeRecord.created_at))).scalars().all()
            return [self._to_dict(record) for record in records]

    def all_trades(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        statement = select(TradeRecord).order_by(desc(TradeRecord.created_at))
        if limit:
            statement = statement.limit(limit)
        with self.SessionLocal() as session:
            return [self._to_dict(record) for record in session.execute(statement).scalars().all()]

    def win_rate(self) -> float:
        with self.SessionLocal() as session:
            rows = session.execute(select(TradeRecord.pnl_zar).where(TradeRecord.status == "closed")).all()
        values = [float(value) for (value,) in rows if value is not None]
        if not values:
            return 0.0
        wins = len([value for value in values if value > 0])
        return wins / len(values)

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.all_trades())

    @staticmethod
    def _to_dict(record: TradeRecord) -> Dict[str, Any]:
        return {column.name: getattr(record, column.name) for column in record.__table__.columns}

