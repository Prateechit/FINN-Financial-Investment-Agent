import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND / ".env")

DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{BACKEND / 'finn.db'}"  # blank counts as unset
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

CACHE_DIR = Path(os.getenv("FINN_CACHE_DIR") or BACKEND / ".cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

INGEST_TOKEN = os.getenv("FINN_INGEST_TOKEN", "")
CORS_ORIGINS = [o.strip() for o in (os.getenv("FINN_CORS_ORIGINS") or "*").split(",")]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Default alert thresholds; users override them in Settings.
DEFAULT_SETTINGS = {
    "window_hours": 24,
    "price_move_pct": 4.0,
    "price_move_sigma": 2.5,
    "volume_multiple": 2.0,
    "volume_lookback_days": 20,
    "alert_categories": ["results", "M&A", "management_change", "fund_raise", "credit_rating",
                         "litigation", "pledging", "insider_trading"],
    "min_alert_materiality": 70,
}
