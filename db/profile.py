"""Profile the raw REEC fields a table is going to keep, before designing it.

Reports what each field actually contains rather than what the AEMPS manual
says it contains, so the DDL is written from evidence. Deliberately scoped to
fields a table will use: profiling everything invites designing around fields
nothing needs.

Four things every field report answers:

  structure    is the containing block always the shape it is assumed to be --
               always an object, never a list, never missing
  presence     absent / null / blank / present, counted separately. In JSON
               these are four different facts, and collapsing them loses the
               distinction between "never sent" and "sent empty"
  values       every distinct value with counts when there are few, the most
               frequent when there are many. A single dominant value in an
               otherwise varied field is the signature of a placeholder
  by year      presence per year, because averaging 2017-2026 blends the two
               regimes either side of the January 2023 CTIS transition and can
               hide a field that stopped being populated altogether

Usage:
    python -m db.profile sponsors
"""

import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw" / "detalle"

# How many distinct values before a field is summarised rather than listed.
LIST_ALL_BELOW = 30
TOP_N = 12

# The source's own date format, dd-MM-yyyy.
DATE_RE = re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")

# Fields each table keeps, addressed as a dotted path into the record.
# Groups are profiled and reviewed one at a time: 51 fields of full report is
# long enough to be skimmed, which defeats the point of reading it.
TABLE_FIELDS = {
    "sponsors": ["organismo.promotor"],
    # All 11 calendario fields, not the 9 the reverted DDL kept. The decision
    # to drop fechaClasificacion and fechaFinPrevista came from two sampled
    # cohorts (§3.2); profiling re-checks it against the whole corpus rather
    # than inheriting it.
    "studies.calendario": [
        "calendario.fechaAutorizacionAEMPS",
        "calendario.fechaRegistro",
        "calendario.fechaClasificacion",
        "calendario.fechaInicioPrevista",
        "calendario.fechaFinPrevista",
        "calendario.fechaInicioReal",
        "calendario.fechaFinRealEspana",
        "calendario.fechaFinRealGlobal",
        "calendario.fechaInterrupcion",
        "calendario.fechaReinicio",
        "calendario.fechaFinPrematuro",
    ],
}

# Tables whose report is rendered compactly.
COMPACT_TABLES = {"studies.calendario"}

ABSENT, NULL, BLANK, PRESENT = "absent", "null", "blank", "present"


def iter_records(raw_dir=DEFAULT_RAW_DIR, years=None):
    """Yield (year, record) for every cached detail record."""
    paths = sorted(Path(raw_dir).glob("*.jsonl"))
    if years:
        wanted = {str(y) for y in years}
        paths = [p for p in paths if p.stem in wanted]
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                yield path.stem, json.loads(line)


def walk(record, path):
    """Follow a dotted path. Returns (status, value, container_types).

    container_types records what each parent level actually was, so an
    assumption like "organismo is always an object" is checked rather than
    trusted.
    """
    parts = path.split(".")
    node = record
    containers = []
    for part in parts[:-1]:
        containers.append(type(node).__name__)
        if not isinstance(node, dict) or part not in node:
            return ABSENT, None, containers
        node = node[part]
    containers.append(type(node).__name__)
    if not isinstance(node, dict) or parts[-1] not in node:
        return ABSENT, None, containers
    value = node[parts[-1]]
    if value is None:
        return NULL, None, containers
    if isinstance(value, str) and not value.strip():
        return BLANK, value, containers
    return PRESENT, value, containers


def normalise(text):
    """The identity rule from PROJECT_SPEC 3.2c, applied in that order.

    HTML unescape, drop accents, casefold, collapse internal whitespace, strip
    surrounding whitespace and punctuation.

    Used here only to count how many distinct values would merge under it --
    never to change what is reported. It answers "would deduplicating on the
    exact string split one real entity into several?".

    The unescape step is not cosmetic: the source mixes '&amp;' with a raw '&'
    for the same organisation, and no amount of case-folding merges those.
    """
    unescaped = html.unescape(text)
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", unescaped)
        if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.casefold().split()).strip(" .,;:-")


class FieldProfile:
    def __init__(self, path):
        self.path = path
        self.records = 0
        self.status = Counter()
        self.containers = Counter()
        self.values = Counter()
        self.by_year = defaultdict(Counter)
        self.lengths = []
        self.types = Counter()

    def add(self, year, status, value, containers):
        self.records += 1
        self.status[status] += 1
        self.by_year[year][status] += 1
        self.containers[" > ".join(containers)] += 1
        if status == PRESENT:
            self.types[type(value).__name__] += 1
            if isinstance(value, str):
                self.values[value.strip()] += 1
                self.lengths.append(len(value.strip()))

    @property
    def distinct(self):
        return len(self.values)

    @property
    def distinct_normalised(self):
        merged = Counter()
        for value, count in self.values.items():
            merged[normalise(value)] += count
        return len(merged)

    def collapsing_groups(self, limit=8):
        """Values that differ only by case, accent, spacing or trailing marks."""
        groups = defaultdict(list)
        for value in self.values:
            groups[normalise(value)].append(value)
        return sorted((v for v in groups.values() if len(v) > 1),
                      key=lambda v: -sum(self.values[x] for x in v))[:limit]


def date_summary(values):
    """(matching, total, earliest, latest) if a field looks like dates.

    Returns None when fewer than half the distinct values match the source's
    dd-MM-yyyy, so a field of ordinary text is not described as dates. Sorting
    is done on a rearranged ISO form: sorting dd-MM-yyyy as text would order by
    day of month, which is the same trap that makes the format unusable in the
    database.
    """
    if not values:
        return None
    matching = {v: c for v, c in values.items() if DATE_RE.match(v)}
    if len(matching) * 2 < len(values):
        return None
    def iso(value):
        day, month, year = value.split("-")
        return "{}-{:0>2}-{:0>2}".format(year, month, day)
    ordered = sorted(iso(v) for v in matching)
    return sum(matching.values()), sum(values.values()), ordered[0], ordered[-1]


def profile_field(path, raw_dir=DEFAULT_RAW_DIR, years=None, records=None):
    profile = FieldProfile(path)
    source = records if records is not None else iter_records(raw_dir, years)
    for year, record in source:
        profile.add(year, *walk(record, path))
    return profile


def print_profile(profile, stream=sys.stdout):
    def out(text=""):
        print(text, file=stream)

    total = profile.records
    out("=" * 72)
    out(profile.path)
    out("=" * 72)

    out("structure (types of each level, outermost first)")
    for shape, count in profile.containers.most_common():
        out("  {:40s} {:6d}  {:6.1%}".format(shape, count, count / total))

    out()
    out("presence")
    for status in (PRESENT, BLANK, NULL, ABSENT):
        count = profile.status[status]
        out("  {:10s} {:6d}  {:6.1%}".format(status, count, count / total))
    if len(profile.types) > 1:
        out("  value types seen: {}".format(dict(profile.types)))

    if profile.lengths:
        out()
        out("length  min {}  max {}  mean {:.0f}".format(
            min(profile.lengths), max(profile.lengths),
            sum(profile.lengths) / len(profile.lengths)))

    out()
    out("distinct values: {} exact".format(profile.distinct))
    if profile.distinct:
        merged = profile.distinct_normalised
        out("                 {} after casefold/accent/space normalisation"
            " ({} would merge)".format(merged, profile.distinct - merged))
        top = profile.values.most_common(1)[0]
        share = top[1] / sum(profile.values.values())
        out("                 most frequent value is {:.1%} of non-blank".format(share))

    out()
    if 0 < profile.distinct <= LIST_ALL_BELOW:
        out("all values")
        for value, count in profile.values.most_common():
            out("  {:6d}  {!r}".format(count, value))
    elif profile.distinct:
        out("most frequent values")
        for value, count in profile.values.most_common(TOP_N):
            out("  {:6d}  {!r}".format(count, value))
        singles = sum(1 for c in profile.values.values() if c == 1)
        out("  ... {} values occur exactly once".format(singles))

    groups = profile.collapsing_groups()
    if groups:
        out()
        out("values that differ only by case/accent/spacing/punctuation")
        for group in groups:
            for value in sorted(group, key=lambda v: -profile.values[v]):
                out("  {:6d}  {!r}".format(profile.values[value], value))
            out("  --")

    out()
    out("presence by year")
    out("  {:6s} {:>7s} {:>7s} {:>7s} {:>7s}".format(
        "year", PRESENT, BLANK, NULL, ABSENT))
    for year in sorted(profile.by_year):
        counts = profile.by_year[year]
        out("  {:6s} {:7d} {:7d} {:7d} {:7d}".format(
            year, counts[PRESENT], counts[BLANK], counts[NULL], counts[ABSENT]))


def print_compact(profile, stream=sys.stdout):
    """A few lines per field, for groups too large to read in full.

    Keeps the parts that carry a decision -- presence, the full value list when
    cardinality is low, and fill rate per year -- and drops the rest.
    """
    def out(text=""):
        print(text, file=stream)

    total = profile.records
    present = profile.status[PRESENT]
    out(profile.path)
    out("  presence  present {} ({:.1%})   blank {}   null {}   absent {}".format(
        present, present / total, profile.status[BLANK],
        profile.status[NULL], profile.status[ABSENT]))

    shapes = [s for s in profile.containers if not s.endswith("dict")]
    if shapes:
        out("  STRUCTURE unexpected container types: {}".format(
            {s: profile.containers[s] for s in shapes}))
    if len(profile.types) > 1:
        out("  TYPES     mixed value types: {}".format(dict(profile.types)))

    if not profile.distinct:
        out("  distinct  0 -- never populated")
        out()
        return

    out("  distinct  {} exact".format(profile.distinct))

    dates = date_summary(profile.values)
    if dates:
        matching, values_total, earliest, latest = dates
        note = "" if matching == values_total else "   <-- {} DO NOT".format(
            values_total - matching)
        out("  format    {}/{} match dd-MM-yyyy{}".format(
            matching, values_total, note))
        out("  range     {} .. {}".format(earliest, latest))
    elif profile.distinct <= LIST_ALL_BELOW:
        out("  values    " + "  |  ".join(
            "{!r} {}".format(v, c) for v, c in profile.values.most_common()))
    else:
        out("  top       " + "  |  ".join(
            "{!r} {}".format(v, c) for v, c in profile.values.most_common(4)))

    years = sorted(profile.by_year)
    out("  by year   " + "  ".join(
        "{} {:.0%}".format(y, profile.by_year[y][PRESENT] / sum(
            profile.by_year[y].values())) for y in years))
    out()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    table = argv[0] if argv else "sponsors"
    if table not in TABLE_FIELDS:
        print("unknown table {!r}; known: {}".format(
            table, ", ".join(sorted(TABLE_FIELDS))), file=sys.stderr)
        return 1
    records = list(iter_records())
    render = print_compact if table in COMPACT_TABLES else print_profile
    if render is print_compact:
        print("{}  --  {} fields over {} studies".format(
            table, len(TABLE_FIELDS[table]), len(records)))
        print()
    for path in TABLE_FIELDS[table]:
        render(profile_field(path, records=records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
