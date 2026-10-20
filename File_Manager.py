import os
import logging
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Base directory is strictly the folder where File_Manager.py lives ("Synthetic Data Generator")
BASE_DIR = Path(__file__).resolve().parent

# Explicitly map directories using absolute relative paths
LOGS_DIR = Path(os.getenv("HOST_LOGS_PATH", BASE_DIR / "logs"))
EXPORTS_DIR = Path(os.getenv("HOST_EXPORTS_PATH", BASE_DIR / "exports"))
DATA_DIR = Path(os.getenv("HOST_DATA_PATH", BASE_DIR / "data"))
ARCHIVE_DIR = Path(os.getenv("HOST_ARCHIVE_PATH", BASE_DIR / "archive"))
SCHEMAS_DIR = Path(os.getenv("HOST_SCHEMAS_PATH", BASE_DIR / "Columns_Json"))
SYNTHETIC_DATA_DIR = Path(os.getenv("HOST_SYNTHETIC_DATA_PATH", BASE_DIR / "Synthetic_Data"))


def ensure_directories(dir_list=None):
    """Creates necessary folders if they don't exist using os.path.exists checks."""
    if dir_list is None:
        dir_list = [LOGS_DIR, EXPORTS_DIR, DATA_DIR, ARCHIVE_DIR, SYNTHETIC_DATA_DIR, SCHEMAS_DIR]
    
    for directory in dir_list:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"Directory Created: {directory}")
        else:
            logger.debug(f"Directory already exists: {directory}")


def get_timestamped_filename(prefix, extension="csv", include_time=False):
    """Generates a filename with precise timestamps."""
    if include_time:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d")
    return f"{prefix}_{timestamp}.{extension}"


def get_target_file_path(prefix, target_folder=None, extension="csv", include_time=False):
    """Returns a fully resolved file path inside a target folder with a timestamp."""
    folder = Path(target_folder) if target_folder else SYNTHETIC_DATA_DIR
    
    if not os.path.exists(folder):
        os.makedirs(folder)
        logger.info(f"Directory Created: {folder}")
        
    filename = get_timestamped_filename(prefix, extension=extension, include_time=include_time)
    return folder / filename