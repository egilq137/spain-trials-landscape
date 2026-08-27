"""Tests for ingestion.cache.

Success criteria per function:
  year_cache_path: deterministic path, distinct per year
  is_cached: True iff the file exists, False if the dir doesn't even exist
  save_year + load_year: round-trip a dict unchanged, including non-ASCII
    text (Spanish accents), and create the directory if missing
  load_year: raises (doesn't swallow) when the file is missing
"""

import tempfile
import unittest
from pathlib import Path

from ingestion.cache import is_cached, load_year, save_year, year_cache_path


class YearCachePathTests(unittest.TestCase):
    def test_builds_expected_filename(self):
        path = year_cache_path(2019, Path("data/raw"))
        self.assertEqual(path, Path("data/raw/2019.json"))

    def test_different_years_produce_different_paths(self):
        self.assertNotEqual(
            year_cache_path(2019, Path("data/raw")),
            year_cache_path(2020, Path("data/raw")),
        )


class IsCachedTests(unittest.TestCase):
    def test_false_when_directory_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "does_not_exist"
            self.assertFalse(is_cached(2019, missing_dir))

    def test_false_when_file_missing_but_dir_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_cached(2019, Path(tmp)))

    def test_true_after_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            save_year(2019, {"estudio": []}, raw_dir)
            self.assertTrue(is_cached(2019, raw_dir))


class SaveLoadYearTests(unittest.TestCase):
    def test_round_trip_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            original = {"estudio": [{"identificador": "2019-000001-11-00"}]}

            save_year(2019, original, raw_dir)
            loaded = load_year(2019, raw_dir)

            self.assertEqual(loaded, original)

    def test_creates_directory_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "nested" / "raw"
            self.assertFalse(raw_dir.exists())

            save_year(2019, {"estudio": []}, raw_dir)

            self.assertTrue(raw_dir.exists())

    def test_non_ascii_characters_are_preserved_readably(self):
        # ensure_ascii=False -- Spanish text should stay literal in the
        # file, not escaped as í etc.
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            original = {"estudio": [{"promotor": "Hospital Universitario de la Princesa, España"}]}

            save_year(2019, original, raw_dir)
            raw_text = year_cache_path(2019, raw_dir).read_text(encoding="utf-8")
            loaded = load_year(2019, raw_dir)

            self.assertIn("España", raw_text)
            self.assertEqual(loaded, original)

    def test_load_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                load_year(2019, raw_dir)


if __name__ == "__main__":
    unittest.main()
