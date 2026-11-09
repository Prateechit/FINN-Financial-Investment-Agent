import datetime as dt
import json
from contextlib import contextmanager

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, Integer, String, Text, create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import DATABASE_URL, DEFAULT_SETTINGS

engine = create_engine(DATABASE_URL, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Company(Base):
    __tablename__ = "companies"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(100))
    bse_code: Mapped[str | None] = mapped_column(String(16))
    in_portfolio: Mapped[bool] = mapped_column(Boolean, default=False)
    weight: Mapped[float] = mapped_column(Float, default=0.0)  # % of mock portfolio value


class PriceEOD(Base):
    __tablename__ = "prices_eod"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # "NSE:<seq_id>" / "BSE:<newsid>"
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)  # IST, naive
    exch_category: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(300))  # "Sub:" line of the filing
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(40), index=True)
    classified_by: Mapped[str | None] = mapped_column(String(20))
    materiality: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    enrichment: Mapped[dict | None] = mapped_column(JSON)
    enriched_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # deterministic -> idempotent
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # price | volume | announcement
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class KV(Base):
    """Generic cache / settings store: http bodies, pdf text, llm responses, research reports."""
    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    task: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)


def init_db():
    Base.metadata.create_all(engine)


@contextmanager
def session():
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def kv_get(key: str, max_age: dt.timedelta | None = None):
    with session() as s:
        row = s.get(KV, key)
        if row is None or (max_age and now() - row.updated_at > max_age):
            return None
        return json.loads(row.value)


def kv_set(key: str, value) -> None:
    with session() as s:
        s.merge(KV(key=key, value=json.dumps(value, default=str), updated_at=now()))


def get_settings() -> dict:
    return {**DEFAULT_SETTINGS, **(kv_get("settings") or {})}


def portfolio_symbols() -> list[str]:
    with session() as s:
        return list(s.scalars(select(Company.symbol).where(Company.in_portfolio)))
