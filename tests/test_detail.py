"""Tests for ingestion.detail.

Success criteria per function:
  cached_years: years from the list cache, newest first, non-numeric ignored
  pending_ids: list-cache ids minus those already fetched OR already failed;
    tolerates a truncated final line from an interrupted run
  fetch_detail: dict on a JSON body; StudyNotFound on the plain-text
    "no existe" sentinel (which arrives as HTTP 200, not 404); DetailFetchError
    on an unparseable body or a network/HTTP error
  fetch_year_details: appends successes to the jsonl and failures to the
    sidecar; honours limit and deadline; aborts after CONSECUTIVE_FAILURE_LIMIT
    unexpected failures; a "not in registry" result never counts toward that
  coverage: listed/fetched/failed/pending per year
  run: newest year first, skips complete years, stops at the year boundary
    unless continue_past_year
  print_coverage: a header plus one aligned row per year, newest first,
    with the numbers a partial ingestion would be spotted by
  progress output: announces the pending count, then one line per 100
    records -- and never a '0/n' line before the first success
  retryable_ids: failed ids minus confirmed absences (not in registry)
  retry_year_failures: retryable ids only; success moves the record to the
    data file and drops it from the sidecar; a repeat failure refreshes its
    sidecar entry rather than duplicating it; a StudyNotFound discovered on
    retry is recorded as a confirmed absence; untouched confirmed absences
    are preserved verbatim; aborts after CONSECUTIVE_FAILURE_LIMIT
  retry_failures: iterates years with retryable failures, skips years with
    none, reports when nothing is retryable anywhere
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from ingestion.detail import (
    CONSECUTIVE_FAILURE_LIMIT,
    DETALLE_URL,
    NOT_FOUND_BODY,
    NOT_IN_REGISTRY_REASON,
    DetailFetchError,
    StudyNotFound,
    _append_jsonl,
    _record_failure,
    _recorded_ids,
    cached_years,
    coverage,
    detail_path,
    failures_path,
    fetch_detail,
    fetch_year_details,
    pending_ids,
    print_coverage,
    retry_failures,
    retry_year_failures,
    retryable_ids,
    run,
)


def make_response(text, status_ok=True):
    """A stand-in for requests.Response covering what fetch_detail touches."""
    response = Mock()
    response.text = text
    response.content = text.encode("utf-8")
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("500")
    response.json.side_effect = lambda: json.loads(text)
    return response


class CapturedOutput(unittest.TestCase):
    """Base for tests whose subject prints progress.

    Captures stdout so a passing suite stays quiet -- noisy output hides the one
    diagnostic that matters when something fails -- and so the printed output
    can be asserted on rather than merely tolerated.
    """

    def setUp(self):
        super().setUp()
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def output(self):
        return self.stdout.getvalue()


def write_list_cache(raw_dir, year, identificadores):
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = {"estudio": [{"identificador": i} for i in identificadores]}
    with open(raw_dir / f"{year}.json", "w", encoding="utf-8") as f:
        json.dump(payload, f)


class PathTests(unittest.TestCase):
    def test_detail_and_failure_paths_are_distinct_and_per_year(self):
        self.assertEqual(
            detail_path(2019, Path("data/raw")), Path("data/raw/detalle/2019.jsonl")
        )
        self.assertEqual(
            failures_path(2019, Path("data/raw")),
            Path("data/raw/detalle/2019.failures.jsonl"),
        )
        self.assertNotEqual(
            detail_path(2019, Path("data/raw")), detail_path(2020, Path("data/raw"))
        )


class CachedYearsTests(unittest.TestCase):
    def test_returns_years_newest_first_ignoring_non_numeric_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            for year in (2017, 2019, 2026):
                write_list_cache(raw_dir, year, [])
            (raw_dir / "notes.json").write_text("{}", encoding="utf-8")

            self.assertEqual(cached_years(raw_dir), [2026, 2019, 2017])

    def test_empty_dir_yields_no_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cached_years(Path(tmp)), [])

    def test_missing_dir_yields_no_years_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cached_years(Path(tmp) / "nope"), [])


class RecordedIdsTests(unittest.TestCase):
    """_recorded_ids must read back exactly the ids a run wrote, and survive
    whatever an interrupted run left behind."""

    def test_missing_file_is_an_empty_set_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_recorded_ids(Path(tmp) / "absent.jsonl"), set())

    def test_empty_file_is_an_empty_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            self.assertEqual(_recorded_ids(path), set())

    def test_reads_every_id_across_multiple_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            path.write_text(
                '{"identificador": "a"}\n{"identificador": "b"}\n', encoding="utf-8"
            )
            self.assertEqual(_recorded_ids(path), {"a", "b"})

    def test_line_without_identificador_key_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            path.write_text('{"id": 1}\n{"identificador": "a"}\n', encoding="utf-8")
            self.assertEqual(_recorded_ids(path), {"a"})


class AppendJsonlTests(unittest.TestCase):
    """_append_jsonl is the durability primitive: it must add a line without
    disturbing earlier ones, create the directory, and not mangle Spanish text."""

    def test_appends_rather_than_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "f.jsonl"
            _append_jsonl(path, {"identificador": "a"})
            _append_jsonl(path, {"identificador": "b"})

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [json.loads(line)["identificador"] for line in lines], ["a", "b"]
            )

    def test_non_ascii_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.jsonl"
            record = {"identificador": "a", "ccaa": "CATALUÑA", "n": "CLÍNIC"}
            _append_jsonl(path, record)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), record
            )


class RecordFailureTests(unittest.TestCase):
    def test_sidecar_row_carries_id_reason_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.failures.jsonl"
            _record_failure("2011-000000-11", "not in registry", path)

            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["identificador"], "2011-000000-11")
            self.assertEqual(row["reason"], "not in registry")
            self.assertIn("at", row)


class PendingIdsTests(unittest.TestCase):
    def test_all_ids_pending_when_nothing_fetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b", "c"])

            self.assertEqual(pending_ids(2019, raw_dir), ["a", "b", "c"])

    def test_skips_already_fetched_and_already_failed_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b", "c", "d"])
            path = detail_path(2019, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text('{"identificador": "a"}\n', encoding="utf-8")
            failures_path(2019, raw_dir).write_text(
                '{"identificador": "c", "reason": "not in registry"}\n', encoding="utf-8"
            )

            self.assertEqual(pending_ids(2019, raw_dir), ["b", "d"])

    def test_truncated_final_line_is_ignored_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b"])
            path = detail_path(2019, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text('{"identificador": "a"}\n{"identifica', encoding="utf-8")

            self.assertEqual(pending_ids(2019, raw_dir), ["b"])

    def test_empty_list_cache_yields_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, [])

            self.assertEqual(pending_ids(2019, raw_dir), [])

    def test_fully_fetched_year_yields_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b"])
            path = detail_path(2019, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text(
                '{"identificador": "a"}\n{"identificador": "b"}\n', encoding="utf-8"
            )

            self.assertEqual(pending_ids(2019, raw_dir), [])

    def test_missing_list_cache_raises_rather_than_reporting_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                pending_ids(1999, Path(tmp))


class FetchDetailTests(unittest.TestCase):
    def test_returns_parsed_record_on_json_body(self):
        session = Mock()
        session.get.return_value = make_response('{"identificador": "x", "id": 1}')

        self.assertEqual(fetch_detail("x", session), {"identificador": "x", "id": 1})

    def test_requests_the_expected_url_for_the_identifier(self):
        session = Mock()
        session.get.return_value = make_response('{"identificador": "2019-000302-29"}')

        fetch_detail("2019-000302-29", session)

        self.assertEqual(
            session.get.call_args.args[0], f"{DETALLE_URL}/2019-000302-29"
        )

    def test_distinct_identifiers_produce_distinct_urls(self):
        session = Mock()
        session.get.return_value = make_response("{}")

        fetch_detail("a", session)
        fetch_detail("b", session)

        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(urls, [f"{DETALLE_URL}/a", f"{DETALLE_URL}/b"])

    def test_sentinel_body_raises_study_not_found_despite_http_200(self):
        session = Mock()
        session.get.return_value = make_response(NOT_FOUND_BODY)

        with self.assertRaises(StudyNotFound):
            fetch_detail("9999-000000-00", session)

    def test_sentinel_is_recognised_with_surrounding_whitespace(self):
        session = Mock()
        session.get.return_value = make_response(f"\n  {NOT_FOUND_BODY}  \n")

        with self.assertRaises(StudyNotFound):
            fetch_detail("x", session)

    def test_a_study_whose_text_merely_contains_the_sentinel_is_still_parsed(self):
        """Guards against matching the sentinel with `in` instead of equality --
        a real record could quote that phrase in a free-text field."""
        body = json.dumps(
            {"identificador": "x", "informacion": {"justificacion": NOT_FOUND_BODY}}
        )
        session = Mock()
        session.get.return_value = make_response(body)

        self.assertEqual(fetch_detail("x", session)["identificador"], "x")

    def test_unparseable_body_raises_detail_fetch_error(self):
        session = Mock()
        session.get.return_value = make_response("<html>error</html>")

        with self.assertRaises(DetailFetchError):
            fetch_detail("x", session)

    def test_http_error_raises_detail_fetch_error(self):
        session = Mock()
        session.get.return_value = make_response("{}", status_ok=False)

        with self.assertRaises(DetailFetchError):
            fetch_detail("x", session)

    def test_network_error_raises_detail_fetch_error(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(DetailFetchError):
            fetch_detail("x", session)


class FetchYearDetailsTests(CapturedOutput):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def read_jsonl(self, path):
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_appends_every_fetched_record(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )

        stats = fetch_year_details(2019, session, self.raw_dir, delay=0)

        self.assertEqual(stats["fetched"], 2)
        records = self.read_jsonl(detail_path(2019, self.raw_dir))
        self.assertEqual([r["identificador"] for r in records], ["a", "b"])

    def test_missing_studies_go_to_sidecar_not_the_data_file(self):
        write_list_cache(self.raw_dir, 2019, ["a", "gone"])

        def respond(url, timeout):
            ident = url.rsplit("/", 1)[-1]
            if ident == "gone":
                return make_response(NOT_FOUND_BODY)
            return make_response(json.dumps({"identificador": ident}))

        session = Mock()
        session.get.side_effect = respond

        stats = fetch_year_details(2019, session, self.raw_dir, delay=0)

        self.assertEqual((stats["fetched"], stats["missing"], stats["failed"]), (1, 1, 0))
        self.assertEqual(
            [r["identificador"] for r in self.read_jsonl(detail_path(2019, self.raw_dir))],
            ["a"],
        )
        self.assertEqual(
            [r["identificador"] for r in self.read_jsonl(failures_path(2019, self.raw_dir))],
            ["gone"],
        )

    def test_limit_caps_the_number_attempted(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b", "c", "d"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )

        stats = fetch_year_details(2019, session, self.raw_dir, limit=2, delay=0)

        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(session.get.call_count, 2)

    def test_expired_deadline_stops_before_any_request(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b"])
        session = Mock()

        with patch("ingestion.detail.time.monotonic", return_value=100.0):
            stats = fetch_year_details(2019, session, self.raw_dir, deadline=50.0, delay=0)

        session.get.assert_not_called()
        self.assertEqual(stats["remaining"], 2)
        self.assertEqual(stats["fetched"], 0)

    def test_aborts_after_consecutive_unexpected_failures(self):
        ids = [str(n) for n in range(CONSECUTIVE_FAILURE_LIMIT + 5)]
        write_list_cache(self.raw_dir, 2019, ids)
        session = Mock()
        session.get.side_effect = requests.ConnectionError("down")

        with self.assertRaises(DetailFetchError):
            fetch_year_details(2019, session, self.raw_dir, delay=0)

        self.assertEqual(session.get.call_count, CONSECUTIVE_FAILURE_LIMIT)

    def test_missing_studies_do_not_count_toward_the_abort_limit(self):
        ids = [str(n) for n in range(CONSECUTIVE_FAILURE_LIMIT + 3)]
        write_list_cache(self.raw_dir, 2019, ids)
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(NOT_FOUND_BODY)

        stats = fetch_year_details(2019, session, self.raw_dir, delay=0)

        self.assertEqual(stats["missing"], len(ids))
        self.assertEqual(session.get.call_count, len(ids))

    def test_a_success_resets_the_consecutive_failure_counter(self):
        ids = [str(n) for n in range(12)]
        write_list_cache(self.raw_dir, 2019, ids)
        # fail, fail, fail, fail, succeed, repeat -- never 5 failures in a row
        responses = []
        for n in range(12):
            if n % 5 == 4:
                responses.append(make_response(json.dumps({"identificador": str(n)})))
            else:
                responses.append(make_response("<html>oops</html>"))
        session = Mock()
        session.get.side_effect = responses

        stats = fetch_year_details(2019, session, self.raw_dir, delay=0)

        self.assertEqual(session.get.call_count, 12)
        self.assertEqual(stats["fetched"], 2)

    def test_nothing_pending_makes_no_requests(self):
        write_list_cache(self.raw_dir, 2019, [])
        session = Mock()

        stats = fetch_year_details(2019, session, self.raw_dir, delay=0)

        session.get.assert_not_called()
        self.assertEqual(stats["fetched"], 0)

    def test_deadline_reached_mid_loop_stops_and_reports_the_true_remainder(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b", "c", "d"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )

        # checked once per iteration: proceed, proceed, then past the deadline
        with patch("ingestion.detail.time.monotonic", side_effect=[10.0, 20.0, 60.0]):
            stats = fetch_year_details(2019, session, self.raw_dir, deadline=50.0, delay=0)

        self.assertEqual(stats["fetched"], 2)
        self.assertEqual(stats["remaining"], 2)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(
            [r["identificador"] for r in self.read_jsonl(detail_path(2019, self.raw_dir))],
            ["a", "b"],
        )

    def test_no_deadline_means_the_year_runs_to_completion(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b", "c"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )

        stats = fetch_year_details(2019, session, self.raw_dir, deadline=None, delay=0)

        self.assertEqual(stats["fetched"], 3)
        self.assertEqual(stats["remaining"], 0)

    def test_unexpected_failure_reason_is_written_to_the_sidecar(self):
        write_list_cache(self.raw_dir, 2019, ["a"])
        session = Mock()
        session.get.return_value = make_response("<html>502</html>")

        fetch_year_details(2019, session, self.raw_dir, delay=0)

        row = self.read_jsonl(failures_path(2019, self.raw_dir))[0]
        self.assertEqual(row["identificador"], "a")
        self.assertIn("unparseable", row["reason"])
        self.assertFalse(detail_path(2019, self.raw_dir).exists())

    def test_waits_between_requests(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response('{"identificador": "x"}')

        with patch("ingestion.detail.time.sleep") as mock_sleep:
            fetch_year_details(2019, session, self.raw_dir, delay=1.0)

        self.assertEqual([c.args[0] for c in mock_sleep.call_args_list], [1.0, 1.0])

    def test_rerun_only_fetches_what_is_still_pending(self):
        write_list_cache(self.raw_dir, 2019, ["a", "b", "c"])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )

        fetch_year_details(2019, session, self.raw_dir, limit=1, delay=0)
        session.get.reset_mock()
        fetch_year_details(2019, session, self.raw_dir, delay=0)

        requested = [c.args[0].rsplit("/", 1)[-1] for c in session.get.call_args_list]
        self.assertEqual(requested, ["b", "c"])


class CoverageTests(unittest.TestCase):
    def test_counts_listed_fetched_failed_and_pending_per_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b", "c"])
            write_list_cache(raw_dir, 2020, ["d"])
            path = detail_path(2019, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text('{"identificador": "a"}\n', encoding="utf-8")
            failures_path(2019, raw_dir).write_text(
                '{"identificador": "b"}\n', encoding="utf-8"
            )

            rows = {row["year"]: row for row in coverage(raw_dir)}

            self.assertEqual(
                (rows[2019]["listed"], rows[2019]["fetched"], rows[2019]["failed"],
                 rows[2019]["pending"]),
                (3, 1, 1, 1),
            )
            self.assertEqual(rows[2020]["pending"], 1)

    def test_no_cached_years_yields_no_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(coverage(Path(tmp)), [])

    def test_complete_year_reports_zero_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a", "b"])
            path = detail_path(2019, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text(
                '{"identificador": "a"}\n{"identificador": "b"}\n', encoding="utf-8"
            )

            self.assertEqual(coverage(raw_dir)[0]["pending"], 0)


def write_failures(raw_dir, year, records):
    path = failures_path(year, raw_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class RetryableIdsTests(unittest.TestCase):
    def test_excludes_confirmed_absences_includes_real_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_failures(
                raw_dir,
                2023,
                [
                    {"identificador": "a", "reason": NOT_IN_REGISTRY_REASON},
                    {"identificador": "b", "reason": "SSLError: EOF"},
                ],
            )

            self.assertEqual(retryable_ids(2023, raw_dir), ["b"])

    def test_no_failures_file_yields_nothing_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(retryable_ids(2023, Path(tmp)), [])

    def test_all_confirmed_absences_yields_nothing_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_failures(
                raw_dir, 2023, [{"identificador": "a", "reason": NOT_IN_REGISTRY_REASON}]
            )

            self.assertEqual(retryable_ids(2023, raw_dir), [])


class RetryYearFailuresTests(CapturedOutput):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def sidecar_rows(self):
        path = failures_path(2023, self.raw_dir)
        if not path.exists():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]

    def test_a_success_moves_the_record_to_the_data_file_and_off_the_sidecar(self):
        write_failures(self.raw_dir, 2023, [{"identificador": "a", "reason": "boom"}])
        session = Mock()
        session.get.return_value = make_response('{"identificador": "a"}')

        stats = retry_year_failures(2023, session, self.raw_dir, delay=0)

        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(self.sidecar_rows(), [])
        detail_lines = detail_path(2023, self.raw_dir).read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(json.loads(detail_lines[0])["identificador"], "a")

    def test_a_repeat_failure_refreshes_rather_than_duplicates_the_entry(self):
        write_failures(
            self.raw_dir,
            2023,
            [{"identificador": "a", "reason": "boom", "at": "2020-01-01T00:00:00"}],
        )
        session = Mock()
        session.get.return_value = make_response("<html>still down</html>")

        stats = retry_year_failures(2023, session, self.raw_dir, delay=0)

        self.assertEqual(stats["still_failed"], 1)
        rows = self.sidecar_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["identificador"], "a")
        self.assertNotEqual(rows[0]["at"], "2020-01-01T00:00:00")

    def test_a_retry_that_now_confirms_absence_is_recorded_as_such(self):
        write_failures(self.raw_dir, 2023, [{"identificador": "a", "reason": "boom"}])
        session = Mock()
        session.get.return_value = make_response(NOT_FOUND_BODY)

        stats = retry_year_failures(2023, session, self.raw_dir, delay=0)

        self.assertEqual(stats["still_missing"], 1)
        rows = self.sidecar_rows()
        self.assertEqual(rows[0]["reason"], NOT_IN_REGISTRY_REASON)
        # and it's therefore excluded from the next retry pass:
        self.assertEqual(retryable_ids(2023, self.raw_dir), [])

    def test_confirmed_absences_are_left_untouched_no_request_made(self):
        write_failures(
            self.raw_dir, 2023, [{"identificador": "a", "reason": NOT_IN_REGISTRY_REASON}]
        )
        session = Mock()

        stats = retry_year_failures(2023, session, self.raw_dir, delay=0)

        session.get.assert_not_called()
        self.assertEqual((stats["resolved"], stats["still_failed"]), (0, 0))
        self.assertEqual(self.sidecar_rows(), [{"identificador": "a", "reason": NOT_IN_REGISTRY_REASON}])

    def test_mixed_batch_success_and_failure_leaves_only_the_failure_behind(self):
        write_failures(
            self.raw_dir,
            2023,
            [
                {"identificador": "a", "reason": "boom"},
                {"identificador": "b", "reason": NOT_IN_REGISTRY_REASON},
                {"identificador": "c", "reason": "boom2"},
            ],
        )
        session = Mock()

        def respond(url, timeout):
            ident = url.rsplit("/", 1)[-1]
            if ident == "c":
                return make_response("<html>nope</html>")
            return make_response(json.dumps({"identificador": ident}))

        session.get.side_effect = respond

        stats = retry_year_failures(2023, session, self.raw_dir, delay=0)

        self.assertEqual(stats["resolved"], 1)
        rows = {r["identificador"]: r["reason"] for r in self.sidecar_rows()}
        self.assertEqual(rows["b"], NOT_IN_REGISTRY_REASON)
        self.assertIn("unparseable body", rows["c"])

    def test_aborts_after_consecutive_unexpected_failures_and_still_persists_progress(self):
        ids = [str(n) for n in range(CONSECUTIVE_FAILURE_LIMIT + 2)]
        write_failures(
            self.raw_dir, 2023, [{"identificador": i, "reason": "boom"} for i in ids]
        )
        session = Mock()
        session.get.side_effect = requests.ConnectionError("down")

        with self.assertRaises(DetailFetchError):
            retry_year_failures(2023, session, self.raw_dir, delay=0)

        self.assertEqual(session.get.call_count, CONSECUTIVE_FAILURE_LIMIT)
        self.assertEqual(len(self.sidecar_rows()), CONSECUTIVE_FAILURE_LIMIT)


class RetryFailuresTests(CapturedOutput):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.retry_year_failures")
    def test_only_visits_years_with_retryable_failures(self, mock_retry, mock_session):
        write_list_cache(self.raw_dir, 2023, [])
        write_list_cache(self.raw_dir, 2022, [])
        write_failures(self.raw_dir, 2023, [{"identificador": "a", "reason": "boom"}])
        write_failures(
            self.raw_dir, 2022, [{"identificador": "b", "reason": NOT_IN_REGISTRY_REASON}]
        )
        mock_retry.return_value = {"year": 2023, "resolved": 1, "still_missing": 0, "still_failed": 0}

        retry_failures(self.raw_dir)

        self.assertEqual(mock_retry.call_count, 1)
        self.assertEqual(mock_retry.call_args.args[0], 2023)

    def test_no_failures_anywhere_prints_a_clear_message_and_does_nothing(self):
        write_list_cache(self.raw_dir, 2023, [])

        retry_failures(self.raw_dir)

        self.assertIn("no retryable failures", self.output())


class PrintCoverageTests(CapturedOutput):
    """The coverage table is how a partial ingestion is spotted, so its numbers
    matter as much as any return value -- assert on them, don't eyeball them."""

    def test_prints_a_header_and_one_row_per_year_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2019, ["a"])
            write_list_cache(raw_dir, 2026, ["b"])

            print_coverage(raw_dir)

            lines = self.output().splitlines()
            self.assertIn("year", lines[0])
            self.assertIn("pending", lines[0])
            self.assertEqual(lines[1].split(), ["2026", "1", "0", "0", "1"])
            self.assertEqual(lines[2].split(), ["2019", "1", "0", "0", "1"])

    def test_row_reports_a_partially_fetched_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2026, ["a", "b", "c"])
            path = detail_path(2026, raw_dir)
            path.parent.mkdir(parents=True)
            path.write_text('{"identificador": "a"}\n', encoding="utf-8")

            print_coverage(raw_dir)

            self.assertEqual(
                self.output().splitlines()[1].split(), ["2026", "3", "1", "0", "2"]
            )

    def test_columns_stay_aligned_across_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            write_list_cache(raw_dir, 2026, ["a"])
            write_list_cache(raw_dir, 2019, [str(n) for n in range(1000)])

            print_coverage(raw_dir)

            lines = self.output().splitlines()
            self.assertEqual(len({len(line) for line in lines}), 1)


class ProgressOutputTests(CapturedOutput):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_n_studies(self, n):
        write_list_cache(self.raw_dir, 2019, [str(i) for i in range(n)])
        session = Mock()
        session.get.side_effect = lambda url, timeout: make_response(
            json.dumps({"identificador": url.rsplit("/", 1)[-1]})
        )
        fetch_year_details(2019, session, self.raw_dir, delay=0)

    def test_announces_how_many_are_pending_before_starting(self):
        self.run_n_studies(3)

        self.assertIn("2019: 3 to fetch", self.output())

    def test_prints_progress_every_hundred_records(self):
        self.run_n_studies(250)

        progress = [
            line.strip() for line in self.output().splitlines() if "/250" in line
        ]
        self.assertEqual(progress, ["100/250", "200/250"])

    def test_short_run_prints_no_progress_line_at_zero(self):
        """0 % 100 == 0, so without the truthiness guard every iteration before
        the first success would print '0/...'."""
        self.run_n_studies(3)

        self.assertNotIn("0/3", self.output())


class RunTests(CapturedOutput):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_starts_with_the_newest_year_and_stops_at_the_year_boundary(
        self, mock_fetch, mock_session
    ):
        for year in (2019, 2025, 2026):
            write_list_cache(self.raw_dir, year, ["a"])
        mock_fetch.return_value = {
            "year": 2026, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=60)

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(mock_fetch.call_args.args[0], 2026)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_continue_past_year_moves_on_to_the_next_year(self, mock_fetch, mock_session):
        for year in (2025, 2026):
            write_list_cache(self.raw_dir, year, ["a"])
        mock_fetch.side_effect = lambda year, *a, **kw: {
            "year": year, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=60, continue_past_year=True)

        years = [call.args[0] for call in mock_fetch.call_args_list]
        self.assertEqual(years, [2026, 2025])

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_skips_years_with_nothing_pending(self, mock_fetch, mock_session):
        write_list_cache(self.raw_dir, 2026, ["a"])
        write_list_cache(self.raw_dir, 2025, ["b"])
        path = detail_path(2026, self.raw_dir)
        path.parent.mkdir(parents=True)
        path.write_text('{"identificador": "a"}\n', encoding="utf-8")
        mock_fetch.return_value = {
            "year": 2025, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=60)

        self.assertEqual(mock_fetch.call_args.args[0], 2025)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_explicit_year_overrides_the_newest_first_order(self, mock_fetch, mock_session):
        for year in (2019, 2026):
            write_list_cache(self.raw_dir, year, ["a"])
        mock_fetch.return_value = {
            "year": 2019, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=60, year=2019)

        self.assertEqual(mock_fetch.call_args.args[0], 2019)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_zero_max_minutes_means_no_deadline(self, mock_fetch, mock_session):
        write_list_cache(self.raw_dir, 2026, ["a"])
        mock_fetch.return_value = {
            "year": 2026, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=0)

        self.assertIsNone(mock_fetch.call_args.args[3])

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_a_finite_budget_is_passed_through_as_a_deadline(self, mock_fetch, mock_session):
        write_list_cache(self.raw_dir, 2026, ["a"])
        mock_fetch.return_value = {
            "year": 2026, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        with patch("ingestion.detail.time.monotonic", return_value=1000.0):
            run(raw_dir=self.raw_dir, max_minutes=30)

        self.assertEqual(mock_fetch.call_args.args[3], 1000.0 + 30 * 60)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_nothing_pending_anywhere_fetches_nothing(self, mock_fetch, mock_session):
        write_list_cache(self.raw_dir, 2026, ["a"])
        path = detail_path(2026, self.raw_dir)
        path.parent.mkdir(parents=True)
        path.write_text('{"identificador": "a"}\n', encoding="utf-8")

        run(raw_dir=self.raw_dir, max_minutes=60)

        mock_fetch.assert_not_called()

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_limit_stops_after_one_year_even_with_continue_past_year(
        self, mock_fetch, mock_session
    ):
        for year in (2025, 2026):
            write_list_cache(self.raw_dir, year, ["a", "b"])
        mock_fetch.return_value = {
            "year": 2026, "fetched": 1, "missing": 0, "failed": 0, "remaining": 0
        }

        run(raw_dir=self.raw_dir, max_minutes=60, limit=1, continue_past_year=True)

        self.assertEqual(mock_fetch.call_count, 1)

    @patch("ingestion.detail.requests.Session")
    @patch("ingestion.detail.fetch_year_details")
    def test_partial_year_does_not_spill_into_the_next_year(self, mock_fetch, mock_session):
        for year in (2025, 2026):
            write_list_cache(self.raw_dir, year, ["a", "b"])
        mock_fetch.return_value = {
            "year": 2026, "fetched": 1, "missing": 0, "failed": 0, "remaining": 1
        }

        run(raw_dir=self.raw_dir, max_minutes=60, continue_past_year=True)

        self.assertEqual(mock_fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
