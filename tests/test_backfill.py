"""Tests for ingestion.backfill.run_backfill.

Success criterion: for each year in [start_year, end_year] (inclusive),
run_backfill must
  1. skip years already cached -- must NOT call fetch_year for them
  2. fetch and save years not yet cached
  3. cover the full inclusive range, including when start_year == end_year
"""

import unittest
from unittest.mock import patch

from ingestion.backfill import run_backfill


class RunBackfillTests(unittest.TestCase):
    @patch("ingestion.backfill.save_year")
    @patch("ingestion.backfill.fetch_year")
    @patch("ingestion.backfill.is_cached")
    def test_fetches_and_saves_every_year_when_none_cached(
        self, mock_is_cached, mock_fetch_year, mock_save_year
    ):
        mock_is_cached.return_value = False
        mock_fetch_year.side_effect = lambda year: {"estudio": [], "year": year}

        run_backfill(2017, 2019)

        fetched_years = [call.args[0] for call in mock_fetch_year.call_args_list]
        self.assertEqual(fetched_years, [2017, 2018, 2019])
        self.assertEqual(mock_save_year.call_count, 3)

    @patch("ingestion.backfill.save_year")
    @patch("ingestion.backfill.fetch_year")
    @patch("ingestion.backfill.is_cached")
    def test_skips_already_cached_years(self, mock_is_cached, mock_fetch_year, mock_save_year):
        mock_is_cached.side_effect = lambda year, raw_dir: year == 2018

        run_backfill(2017, 2019)

        fetched_years = [call.args[0] for call in mock_fetch_year.call_args_list]
        self.assertEqual(fetched_years, [2017, 2019])

    @patch("ingestion.backfill.save_year")
    @patch("ingestion.backfill.fetch_year")
    @patch("ingestion.backfill.is_cached")
    def test_all_years_cached_fetches_nothing(
        self, mock_is_cached, mock_fetch_year, mock_save_year
    ):
        mock_is_cached.return_value = True

        run_backfill(2017, 2019)

        mock_fetch_year.assert_not_called()
        mock_save_year.assert_not_called()

    @patch("ingestion.backfill.save_year")
    @patch("ingestion.backfill.fetch_year")
    @patch("ingestion.backfill.is_cached")
    def test_single_year_range_is_inclusive(
        self, mock_is_cached, mock_fetch_year, mock_save_year
    ):
        mock_is_cached.return_value = False
        mock_fetch_year.return_value = {"estudio": []}

        run_backfill(2020, 2020)

        fetched_years = [call.args[0] for call in mock_fetch_year.call_args_list]
        self.assertEqual(fetched_years, [2020])


if __name__ == "__main__":
    unittest.main()
