"""
helpers.py

Generic building blocks shared by every generator. Nothing in here knows about a
specific dataset: put dataset-specific rules in the generator itself.
"""
import logging
import random
import shutil
import uuid

import numpy as np
import pandas as pd

from File_Manager import LOGS_DIR

logger = logging.getLogger(__name__)


def setup_logging(name: str) -> logging.Logger:
    """Log to logs/<name>.log and to the console. Returns a logger called <name>."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOGS_DIR / f"{name}.log", encoding="utf-8"),
                  logging.StreamHandler()],
        force=True,
    )
    return logging.getLogger(name)


def new_uuid(rnd: random.Random) -> str:
    """Reproducible uuid4 driven by a seeded random.Random."""
    return str(uuid.UUID(int=rnd.getrandbits(128), version=4))


def random_timestamps(n: int, rng: np.random.Generator, start: pd.Timestamp, end: pd.Timestamp,
                      saturday_weight: float = 0.6, sunday_weight: float = 0.5,
                      month_end_boost: float = 1.5) -> pd.DatetimeIndex:
    """n random timestamps between start and end.
    Quieter weekends, busier last 3 days of each month. Time of day is uniform."""
    days = pd.date_range(start, end, freq="D")
    weights = np.where(days.dayofweek == 5, saturday_weight,
                       np.where(days.dayofweek == 6, sunday_weight, 1.0))
    weights = np.where(days.day >= days.days_in_month - 2, weights * month_end_boost, weights)
    weights = weights / weights.sum()
    day_idx = rng.choice(len(days), size=n, p=weights)
    seconds = rng.integers(0, 86_400, size=n)
    return days[day_idx] + pd.to_timedelta(seconds, unit="s")


def raise_if_problems(problems: list) -> None:
    """Raise one error listing every validation problem found (does nothing if the list is empty)."""
    if problems:
        raise ValueError("Validation failed: " + "; ".join(problems))


def save_table(df: pd.DataFrame, name: str, run_dir, latest_dir) -> None:
    """Write df as Parquet and CSV to run_dir, then copy both to latest_dir."""
    parquet_path = run_dir / f"{name}.parquet"
    csv_path = run_dir / f"{name}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    shutil.copy2(parquet_path, latest_dir / parquet_path.name)
    shutil.copy2(csv_path, latest_dir / csv_path.name)
    logger.info("Saved %s: %d rows", name, len(df))
