"""Tests for ingestion.fetch.fetch_since.

Success criterion: given a date, fetch_since must
  1. build the URL with dd-MM-yyyy formatting embedded in the path (the
     getestudios endpoint's format — NOT the dd/MM/yyyy slash format the
     sibling `estudios` endpoint uses; mixing these up is a documented
     real-world gotcha, see PROJECT_SPEC.md 3.1)
  2. issue a GET request with a timeout set
  3. propagate HTTP and network errors rather than swallowing them
  4. return the parsed JSON body unmodified
"""

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

import requests

from ingestion.fetch import fetch_since


class FetchSinceTests(unittest.TestCase):
    @patch("ingestion.fetch.requests.get")
    def test_ordinary_date_builds_correct_url_and_returns_body(self, mock_get):
        expected_body = {"estudio": [{"identificador": "2026-000001-11-00"}]}
        mock_response = MagicMock()
        mock_response.json.return_value = expected_body
        mock_get.return_value = mock_response

        result = fetch_since(dt.date(2026, 8, 25))

        called_url = mock_get.call_args.args[0]
        self.assertEqual(
            called_url,
            "https://reec.aemps.es/reec-services/json/getestudios/25-08-2026",
        )
        self.assertEqual(result, expected_body)

    @patch("ingestion.fetch.requests.get")
    def test_single_digit_day_and_month_are_zero_padded(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"estudio": []}
        mock_get.return_value = mock_response

        fetch_since(dt.date(2026, 1, 5))

        called_url = mock_get.call_args.args[0]
        self.assertTrue(
            called_url.endswith("/05-01-2026"),
            f"expected dd-MM-yyyy zero-padded date, got: {called_url}",
        )

    @patch("ingestion.fetch.requests.get")
    def test_uses_dash_format_not_slash_format(self, mock_get):
        # Regression guard for the documented endpoint mix-up (dashes here,
        # slashes on the *other* estudios endpoint).
        mock_response = MagicMock()
        mock_response.json.return_value = {"estudio": []}
        mock_get.return_value = mock_response

        fetch_since(dt.date(2026, 3, 7))

        called_url = mock_get.call_args.args[0]
        self.assertNotIn("07/03/2026", called_url)
        self.assertIn("07-03-2026", called_url)

    @patch("ingestion.fetch.requests.get")
    def test_passes_timeout(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"estudio": []}
        mock_get.return_value = mock_response

        fetch_since(dt.date(2026, 8, 25))

        self.assertIn("timeout", mock_get.call_args.kwargs)
        self.assertGreater(mock_get.call_args.kwargs["timeout"], 0)

    @patch("ingestion.fetch.requests.get")
    def test_http_error_is_not_swallowed(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "500 Server Error"
        )
        mock_get.return_value = mock_response

        with self.assertRaises(requests.exceptions.HTTPError):
            fetch_since(dt.date(2026, 8, 25))

    @patch("ingestion.fetch.requests.get")
    def test_connection_error_is_not_swallowed(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("no network")

        with self.assertRaises(requests.exceptions.ConnectionError):
            fetch_since(dt.date(2026, 8, 25))

    @patch("ingestion.fetch.requests.get")
    def test_empty_result_set_passes_through_unchanged(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"estudio": []}
        mock_get.return_value = mock_response

        result = fetch_since(dt.date(2026, 8, 25))

        self.assertEqual(result, {"estudio": []})


if __name__ == "__main__":
    unittest.main()
