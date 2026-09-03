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

from analysis import volume

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
    volume.figure(series, cover).write_html(path, include_plotlyjs="cdn")
    print("{}: {} years, {:,} studies, {} excluded before {}".format(
        path, len(series), sum(n for _, n in series), cover.excluded,
        volume.COVERAGE_START))
    return path


def main():
    con = open_database()
    try:
        write_volume_chart(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
