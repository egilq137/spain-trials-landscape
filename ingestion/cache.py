"""Local JSON caching for raw REEC API responses, one file per year."""

import json
from pathlib import Path

DEFAULT_RAW_DIR = Path("data/raw")


def year_cache_path(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> Path:
    return raw_dir / f"{year}.json"


def is_cached(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> bool:
    return year_cache_path(year, raw_dir).exists()


def save_year(year: int, data: dict, raw_dir: Path = DEFAULT_RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = year_cache_path(year, raw_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_year(year: int, raw_dir: Path = DEFAULT_RAW_DIR) -> dict:
    path = year_cache_path(year, raw_dir)
    with open(path, encoding="utf-8") as f:
        return json.load(f)
