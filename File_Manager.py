"""
File_Manager.py

Shared paths and folder helpers for every generator in this repo.

Output layout:
    Synthetic_Data/<dataset>/<YYYY-MM-DD_HH-MM-SS>/   one folder per run
    Synthetic_Data/<dataset>/latest/                  most recent run, stable file names
"""
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory is the folder where File_Manager.py lives (the repo root)
BASE_DIR = Path(__file__).resolve().parent

# Every path can be overridden with an environment variable
LOGS_DIR = Path(os.getenv("HOST_LOGS_PATH", BASE_DIR / "logs"))
EXPORTS_DIR = Path(os.getenv("HOST_EXPORTS_PATH", BASE_DIR / "exports"))
DATA_DIR = Path(os.getenv("HOST_DATA_PATH", BASE_DIR / "data"))
ARCHIVE_DIR = Path(os.getenv("HOST_ARCHIVE_PATH", BASE_DIR / "archive"))
SYNTHETIC_DATA_DIR = Path(os.getenv("HOST_SYNTHETIC_DATA_PATH", BASE_DIR / "Synthetic_Data"))
GENERATORS_DIR = BASE_DIR / "generators"


def ensure_directories(dir_list=None) -> None:
    """Create the standard folders if they don't exist."""
    if dir_list is None:
        dir_list = [LOGS_DIR, EXPORTS_DIR, DATA_DIR, ARCHIVE_DIR, SYNTHETIC_DATA_DIR]
    for directory in dir_list:
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured directory: %s", directory)


def get_timestamped_filename(prefix: str, extension: str = "csv", include_time: bool = False) -> str:
    """Generate a filename with a timestamp, e.g. report_2026-10-21.csv"""
    fmt = "%Y-%m-%d_%H-%M-%S" if include_time else "%Y-%m-%d"
    return f"{prefix}_{datetime.now().strftime(fmt)}.{extension}"


def get_target_file_path(prefix: str, target_folder=None, extension: str = "csv",
                         include_time: bool = False) -> Path:
    """Return a full file path inside a folder, with a timestamped name."""
    folder = Path(target_folder) if target_folder else SYNTHETIC_DATA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / get_timestamped_filename(prefix, extension, include_time)


def create_parquet_timestamped_dir(dataset_name: str) -> Path:
    """Create Synthetic_Data/<dataset_name>/<timestamp>/ for one run (seconds avoid collisions)."""
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_path = SYNTHETIC_DATA_DIR / dataset_name / timestamp_str
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def get_latest_dir(dataset_name: str) -> Path:
    """Create and return Synthetic_Data/<dataset_name>/latest/ (per dataset, never shared)."""
    folder_path = SYNTHETIC_DATA_DIR / dataset_name / "latest"
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path