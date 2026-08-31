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
    # 18 flags plus the planned participant total. Raw keys here are
    # lowercase and unspaced, unlike proposito's camelCase.
    "studies.poblacion": [
        "poblacion.voluntariossanos",
        "poblacion.pacientes",
        "poblacion.pobvulnerable",
        "poblacion.mujerusa",
        "poblacion.mujernousa",
        "poblacion.embarazadas",
        "poblacion.lactancia",
        "poblacion.urgencia",
        "poblacion.incapaces",
        "poblacion.intrauteros",
        "poblacion.prematuros",
        "poblacion.reciennacido",
        "poblacion.preescolar",
        "poblacion.ninos",
        "poblacion.adolescentes",
        "poblacion.adultos",
        "poblacion.ancianos",
        "poblacion.menores",
        "poblacion.total",
    ],
    # 24 flags: 4 phase, 3 purpose, 9 objective, 8 data-source. Raw keys are
    # camelCase here, unlike poblacion's lowercase.
    "studies.proposito": [
        "proposito.faseUno",
        "proposito.faseDos",
        "proposito.faseTres",
        "proposito.faseCuatro",
        "proposito.diagnostico",
        "proposito.profilaxis",
        "proposito.tratamiento",
        "proposito.seguridad",
        "proposito.eficacia",
        "proposito.farmacocinetica",
        "proposito.farmacodinamica",
        "proposito.bioequivalencia",
        "proposito.dosis",
        "proposito.farmacogenetica",
        "proposito.farmacogenomica",
        "proposito.farmacoeconomica",
        "proposito.atencionPrimaria",
        "proposito.atencionPersonalizada",
        "proposito.hospitalizacion",
        "proposito.medico",
        "proposito.farmaceutico",
        "proposito.historialClinico",
        "proposito.basesDatos",
        "proposito.otrasFuentes",
    ],
    # Candidate fields for centers + the study_centers bridge. Excluded and
    # not profiled: investigador (named individuals, PROJECT_SPEC 3.2b) and
    # domicilio (street address, unused by any analysis question).
    "centers": [
        "centros.centro[].referencia",
        "centros.centro[].nombre",
        "centros.centro[].tipo",
        "centros.centro[].situacion",
        "centros.centro[].ccaa",
        "centros.centro[].provincia",
        "centros.centro[].localidad",
        "centros.centro[].codPostal",
        "centros.centro[].departamento",
    ],
    # organismo.financiador is pipe-delimited, so it is profiled as the raw
    # string here; the split is measured separately.
    "funders": ["organismo.financiador"],
    "therapeutic_areas": [
        "areasTerapeuticas.area[].eutct",
        "areasTerapeuticas.area[].nombre_es",
        "areasTerapeuticas.area[].nombre_en",
    ],
    # The two top-level fields studies keeps. enfermedadRara sits here too: it
    # is the one flag in the record that is a string, not an integer.
    "studies.identity": [
        "identificador",
        "acronimo",
        "enfermedadRara",
    ],
}

# Tables whose report is rendered compactly.
COMPACT_TABLES = {"studies.calendario", "studies.poblacion",
                  "studies.proposito", "centers",
                  "therapeutic_areas"}

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


def walk_all(record, path):
    """walk(), but for a path crossing an array: 'centros.centro[].nombre'.

    Yields one result per array element, so counts are per centre rather than
    per study. Returns () when the array is missing or empty -- a study with no
    centres is a record-level fact, reported separately by list_shape(), not an
    absent value for every field.

    A block that is a bare object where an array is expected yields its one
    element. REEC does this for single-valued fields elsewhere, so the shape
    has to be tolerated and counted rather than assumed.
    """
    before, _, after = path.partition("[].")
    if not after:
        return [walk(record, path)]
    status, value, containers = walk(record, before)
    if status != PRESENT:
        return []
    items = value if isinstance(value, list) else [value]
    return [walk(item, after) for item in items if isinstance(item, dict)]


def list_shape(records, path):
    """Per-record facts about an array: how many studies have it, and how long.

    Kept apart from the per-element profile because they answer different
    questions -- 'how many studies list no centre at all' is not the same as
    'how many centre records have no name'.
    """
    before = path.partition("[].")[0]
    empty = 0
    types = Counter()
    lengths = Counter()
    for _, record in records:
        status, value, _ = walk(record, before)
        if status != PRESENT:
            empty += 1
            types["missing"] += 1
            continue
        types[type(value).__name__] += 1
        items = value if isinstance(value, list) else [value]
        lengths[len(items)] += 1
        if not items:
            empty += 1
    return empty, types, lengths


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
        # Rows in the source. Differs from .records for an array field, where
        # one study contributes many centres.
        self.source_records = 0

    def add(self, year, status, value, containers):
        self.records += 1
        self.status[status] += 1
        self.by_year[year][status] += 1
        self.containers[" > ".join(containers)] += 1
        if status == PRESENT:
            self.types[type(value).__name__] += 1
            # Every scalar is counted, not only strings. An earlier version
            # recorded strings alone, so the poblacion and proposito flags --
            # JSON integers, not the "0"/"1" strings the manual implies --
            # reported "never populated" while being present in every record,
            # hiding their value distribution entirely.
            if isinstance(value, (str, int, float, bool)):
                cleaned = value.strip() if isinstance(value, str) else value
                self.values[cleaned] += 1
            if isinstance(value, str):
                self.lengths.append(len(value.strip()))

    @property
    def distinct(self):
        return len(self.values)

    @property
    def distinct_normalised(self):
        merged = Counter()
        for value, count in self.values.items():
            merged[normalise(value) if isinstance(value, str) else value] += count
        return len(merged)

    def collapsing_groups(self, limit=8):
        """Values that differ only by case, accent, spacing or trailing marks."""
        groups = defaultdict(list)
        for value in self.values:
            if not isinstance(value, str):
                continue
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
    matching = {v: c for v, c in values.items()
                if isinstance(v, str) and DATE_RE.match(v)}
    if len(matching) * 2 < len(values):
        return None
    def iso(value):
        day, month, year = value.split("-")
        return "{}-{:0>2}-{:0>2}".format(year, month, day)
    ordered = sorted(iso(v) for v in matching)
    return sum(matching.values()), sum(values.values()), ordered[0], ordered[-1]


def numeric_summary(values):
    """(count, zeros, negatives, min, median, max) for a numeric field.

    Returns None unless every value is a number, so a field of text is never
    described with statistics that do not apply to it. Zeros and negatives are
    called out separately because in this source a zero is usually "not
    reported" rather than a measured nought.
    """
    if not values or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                             for v in values):
        return None
    expanded = sorted(v for v, c in values.items() for _ in range(c))
    middle = expanded[len(expanded) // 2]
    return (len(expanded), values.get(0, 0), sum(c for v, c in values.items() if v < 0),
            expanded[0], middle, expanded[-1])


def profile_field(path, raw_dir=DEFAULT_RAW_DIR, years=None, records=None):
    profile = FieldProfile(path)
    source = records if records is not None else iter_records(raw_dir, years)
    for year, record in source:
        profile.source_records += 1
        for result in walk_all(record, path):
            profile.add(year, *result)
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
        # Listing beats summarising here: min/median/max of a 0/1 flag says
        # nothing, and the whole point of the low-cardinality branch is that a
        # rogue value cannot hide.
        out("  values    " + "  |  ".join(
            "{!r} {}".format(v, c) for v, c in profile.values.most_common()))
        if profile.distinct == 1:
            out("  CONSTANT  one value in every record -- carries no information")
    elif numeric_summary(profile.values):
        count, zeros, negatives, low, mid, high = numeric_summary(profile.values)
        out("  range     min {}  median {}  max {}".format(low, mid, high))
        out("  zeros     {} ({:.1%}){}".format(
            zeros, zeros / count,
            "   NEGATIVES {}".format(negatives) if negatives else ""))
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
    paths = TABLE_FIELDS[table]
    if "[]." in paths[0]:
        empty, types, lengths = list_shape(records, paths[0])
        total_elements = sum(n * c for n, c in lengths.items())
        print("array {}  --  {} studies, {} elements".format(
            paths[0].partition("[].")[0], len(records), total_elements))
        print("  container types : {}".format(dict(types)))
        print("  studies with none: {}".format(empty))
        print("  elements per study: min {}  max {}  mean {:.1f}".format(
            min(lengths), max(lengths), total_elements / max(sum(lengths.values()), 1)))
        print()
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
