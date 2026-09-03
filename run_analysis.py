"""Composition root for the analysis layer: database in, chart file out.

The sibling of run_pipeline.py, and the same rule -- this is the only file
that knows where the database is and where the output goes. analysis/ modules
take a connection and return values; none of them opens a file or a database.

Usage:
    python run_analysis.py            # write every chart to docs/charts/

The connection is read-only. An analysis has no business writing to the
database, and `mode=ro` makes that a property of the connection rather than a
promise.
"""

import sqlite3
from pathlib import Path

from analysis import therapeutic, volume

# div_id is pinned to the file name on every write_html below. Plotly
# generates a fresh uuid otherwise, so re-running the analysis would rewrite
# every chart file with a one-line diff that means nothing.
DEFAULT_DB = Path("data") / "trials.db"
CHART_DIR = Path("docs") / "charts"


def open_database(path=DEFAULT_DB):
    return sqlite3.connect("file:{}?mode=ro".format(Path(path).as_posix()),
                           uri=True)


def write_volume_chart(con, chart_dir=CHART_DIR):
    series = volume.trials_per_year(con)
    cover = volume.coverage(con)
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / "volume-per-year.html"
    volume.figure(series, cover).write_html(
        path, include_plotlyjs="cdn", div_id=path.stem)
    print("{}: {} years, {:,} studies, {} excluded before {}".format(
        path, len(series), sum(n for _, n in series), cover.excluded,
        volume.COVERAGE_START))
    return path


def write_therapeutic_chart(con, chart_dir=CHART_DIR):
    bars = therapeutic.ranked_areas(therapeutic.trials_per_area(con))
    # The denominator comes from the volume query rather than a count of its
    # own, so the two charts cannot end up quoting different totals.
    trials = sum(count for _, count in volume.trials_per_year(con))
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / "therapeutic-areas.html"
    therapeutic.figure(bars, trials).write_html(
        path, include_plotlyjs="cdn", div_id=path.stem)
    print("{}: {} bars, {:,} memberships over {:,} trials".format(
        path, len(bars), sum(bar.trials for bar in bars), trials))
    return path


def write_area_trend_chart(con, chart_dir=CHART_DIR):
    rows = therapeutic.trials_per_area(con)
    areas = therapeutic.top_areas(rows)
    counts = therapeutic.area_counts_by_year(
        con, [code for code, _ in areas])
    trends = therapeutic.area_trends(
        counts, volume.trials_per_year(con), areas)
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / "therapeutic-mix-by-year.html"
    therapeutic.trend_figure(trends, volume.coverage(con).data_cut).write_html(
        path, include_plotlyjs="cdn", div_id=path.stem)
    print("{}: {} areas over {} years".format(
        path, len(trends), len(trends[0].years)))
    return path


def write_area_race_chart(con, chart_dir=CHART_DIR):
    rows = therapeutic.trials_per_area(con)
    # The same twelve areas the static ranking shows, so the two charts are
    # the same chart with and without a year on it.
    areas = therapeutic.top_areas(rows, count=12)
    frames = therapeutic.yearly_shares(
        therapeutic.area_counts_by_year(con), volume.trials_per_year(con),
        areas)
    chart_dir.mkdir(parents=True, exist_ok=True)
    path = chart_dir / "therapeutic-areas-by-year.html"
    therapeutic.race_figure(
        frames, volume.coverage(con).data_cut).write_html(
            path, include_plotlyjs="cdn", div_id=path.stem, auto_play=False)
    print("{}: {} frames, {} bars".format(
        path, len(frames), len(frames[0][1])))
    return path


def main():
    con = open_database()
    try:
        write_volume_chart(con)
        write_therapeutic_chart(con)
        write_area_trend_chart(con)
        write_area_race_chart(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
