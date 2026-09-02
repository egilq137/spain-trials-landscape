"""Raw REEC records to database column values, for the studies slice.

Pure functions: no database, no filesystem, no invented repairs.

Two kinds of work happen here, and keeping them apart is the point.

**Structural conversion** is unconditional and local: reshaping nested blocks
into flat columns, renaming raw fields, and changing representation where the
type demands it ('0'/'1' to 0/1, 'DD-MM-YYYY' to ISO-8601). Anything it cannot
convert is passed through UNCHANGED rather than nulled, so the schema's own
constraints reject it and name it. A transform that quietly repairs odd input
hides exactly what db/validate.py exists to find.

**Declared rules** come from db/rules.py and are applied on top. -1 becoming
NULL is not this module deciding something; it is a rule that was measured
against the corpus, justified in writing, and is re-checked by a test that
fails if a refresh changes the data underneath. The distinction that matters
is not "does the value change" but "is the change stated somewhere a reader
can find it" -- so no rule is invented here, and every rule applied here is
one line in rules.py.

Order matters: structural first, then the rule. flag('-1') returns -1
unchanged because -1 is not '0' or '1'; clean_flag then turns it into NULL.
An unexpected value survives both and still reaches the schema.

An optional db.manifest.Manifest counts what the rules changed. Counts are
taken from each rule's OUTPUT, never by re-testing its condition, so the
manifest cannot drift away from the rules it describes.
"""

import collections

from db.rules import (
    ROUTE_CANONICAL,
    ROUTE_NOT_A_ROUTE,
    TOTAL_UNKNOWN,
    clean_flag,
    clean_text,
    clean_total,
    is_placeholder,
    match_key,
    route_key,
)

# One intervention, before ids exist. `route` is a canonical route NAME and
# `substances` a list of (key, name): both are looked up or created by the
# caller, the same way sponsor_id is passed into study_row rather than
# resolved here.
Intervention = collections.namedtuple(
    "Intervention", "nombre_comercial codigo huerfano route substances")

# raw poblacion key -> column name. Raw keys are lowercase and unspaced.
POBLACION_FLAGS = {
    "voluntariossanos": "voluntarios_sanos",
    "pacientes": "pacientes",
    "pobvulnerable": "pob_vulnerable",
    "mujerusa": "mujer_usa",
    "mujernousa": "mujer_no_usa",
    "embarazadas": "embarazadas",
    "lactancia": "lactancia",
    "urgencia": "urgencia",
    "incapaces": "incapaces",
    "intrauteros": "intrauteros",
    "prematuros": "prematuros",
    "reciennacido": "recien_nacido",
    "preescolar": "preescolar",
    "ninos": "ninos",
    "adolescentes": "adolescentes",
    "adultos": "adultos",
    "ancianos": "ancianos",
    "menores": "menores",
}

# raw proposito key -> column name. These are camelCase in the source.
# The eight data-source flags are deliberately absent: seven are 0 in all
# 11,847 records, and otrasFuentes varies but means "other" relative to seven
# categories nobody ever ticks, so it cannot be read on its own
# (PROJECT_SPEC 3.2c). db/schema.sql has no columns for them.
PROPOSITO_FLAGS = {
    "faseUno": "fase_uno",
    "faseDos": "fase_dos",
    "faseTres": "fase_tres",
    "faseCuatro": "fase_cuatro",
    "diagnostico": "diagnostico",
    "profilaxis": "profilaxis",
    "tratamiento": "tratamiento",
    "seguridad": "seguridad",
    "eficacia": "eficacia",
    "farmacocinetica": "farmacocinetica",
    "farmacodinamica": "farmacodinamica",
    "bioequivalencia": "bioequivalencia",
    "dosis": "dosis",
    "farmacogenetica": "farmacogenetica",
    "farmacogenomica": "farmacogenomica",
    "farmacoeconomica": "farmacoeconomica",
}

# raw calendario key -> column name. fechaClasificacion and fechaFinPrevista
# are deliberately absent: 0% filled in both cohorts sampled (PROJECT_SPEC 3.2).
CALENDARIO_DATES = {
    "fechaAutorizacionAEMPS": "fecha_autorizacion_aemps",
    "fechaRegistro": "fecha_registro",
    "fechaInicioPrevista": "fecha_inicio_prevista",
    "fechaInicioReal": "fecha_inicio_real",
    "fechaFinRealEspana": "fecha_fin_real_espana",
    "fechaFinRealGlobal": "fecha_fin_real_global",
    "fechaInterrupcion": "fecha_interrupcion",
    "fechaReinicio": "fecha_reinicio",
    "fechaFinPrematuro": "fecha_fin_prematuro",
}


def iso_date(raw):
    """'18-12-2019' -> '2019-12-18'. Blank -> None. Anything else, unchanged.

    Passing an unconvertible value straight through is deliberate: the column's
    GLOB check will reject it and name it, which is more useful than a None
    that looks like an ordinary missing date.
    """
    text = (raw or "").strip()
    if not text:
        return None
    parts = text.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        day, month, year = parts
        if len(year) == 4 and len(month) == 2 and len(day) == 2:
            return f"{year}-{month}-{day}"
    return text


def flag(raw):
    """'0'/'1' -> 0/1. Anything else, unchanged, for the CHECK to reject."""
    text = str(raw).strip() if raw is not None else ""
    return int(text) if text in ("0", "1") else (raw if raw is not None else None)


def integer(raw):
    """Digits -> int. Anything else unchanged, including blank."""
    text = str(raw).strip() if raw is not None else ""
    return int(text) if text.isdigit() else (raw if raw is not None else None)


def acronym(raw):
    """Cleaned acronym, or None when there is none.

    4,763 of the 6,574 non-blank acronyms are placeholders -- 'NA' 4,744 times
    and eighteen other spellings. Kept as text they would make 'NA' the most
    common trial acronym in Spain.
    """
    return None if is_placeholder(raw) else clean_text(raw)


def sponsor_name(record, manifest=None):
    """organismo.promotor as it should be displayed. Blank -> None.

    Cleaned rather than raw: the raw mode for the largest sponsor is
    `Merck Sharp &amp; Dohme LLC`, which is not a name.
    """
    raw = (record.get("organismo") or {}).get("promotor")
    cleaned = clean_text(raw)
    if manifest is not None and raw is not None and cleaned != raw.strip():
        manifest.applied("sponsors.promotor", "markup or spacing cleaned")
    return cleaned


def sponsor_key(record):
    """organismo.promotor as identity. Blank -> None.

    What the loader looks a sponsor up by before handing out a sponsor_id.
    Identity has to be settled before ids exist, because studies.sponsor_id is
    a foreign key -- normalising afterwards would mean merging rows and
    repointing every reference.
    """
    return match_key((record.get("organismo") or {}).get("promotor"))


def funders(record, manifest=None):
    """[(key, display name)] for one study, in source order.

    `financiador` is pipe-delimited and the delimiter is inconsistent -- 5,280
    values end with a trailing '|' and 1,563 do not -- so splitting and
    discarding empties handles both without a rule about trailing separators.

    Placeholders create no funder. 584 mentions are 'NA' and its spellings,
    and 'NA' is the single most frequent funder name in the source: kept, it
    would appear on the dashboard as an organisation that funded 572 trials.
    A study with no real funder simply gets no bridge row, which already means
    "none recorded".

    Deduplicated by key, because 12 studies name one funder twice under two
    spellings and the bridge's PRIMARY KEY (study_id, funder_id) refuses the
    second. Deduplicating on the raw string would not catch those.
    """
    raw = (record.get("organismo") or {}).get("financiador") or ""
    out = []
    seen = set()
    for part in raw.split("|"):
        if not part.strip():
            continue
        if is_placeholder(part):
            if manifest is not None:
                manifest.applied("funders.nombre", "placeholder -> no funder")
            continue
        key, name = match_key(part), clean_text(part)
        if key is None or key in seen:
            if manifest is not None and key is not None:
                manifest.applied("funders.nombre", "repeated within a study")
            continue
        seen.add(key)
        if manifest is not None and name != part.strip():
            manifest.applied("funders.nombre", "markup or spacing cleaned")
        out.append((key, name))
    return out


def therapeutic_area_rows(record):
    """[(eutct, nombre_es, nombre_en)] for one study.

    The cleanest field in the source: a list in 11,847/11,847 records, every
    study has at least one, all three fields present in 12,289/12,289 elements
    with no blanks, and no study repeats a code. So there is nothing to
    deduplicate and nothing to repair -- clean_text changes 0 of the 36,867
    values here. It is applied anyway, so a refresh that introduces markup
    meets the same rule as every other stored name rather than a special case.
    """
    areas = (record.get("areasTerapeuticas") or {}).get("area") or []
    return [(clean_text(area.get("eutct")),
             clean_text(area.get("nombre_es")),
             clean_text(area.get("nombre_en")))
            for area in areas]


def route_name(raw, manifest=None):
    """The canonical administration route, or None when the value names none.

    129 raw values for 53 real routes, harmonised through
    rules.ROUTE_CANONICAL: phrasing ('oral' / 'oral use'), real misspellings
    ('intravenious infusion', 466 rows), and dosage forms that name their
    route unambiguously.

    299 rows say 'unknown use', 'other use' or 'route of administration not
    applicable'. Those name no route and get None -- which is not the same as
    the 13,678 elements where the field is simply absent, but both mean the
    intervention has no route to point at, and the source's own distinction
    between them survives in data/raw/.

    An UNMAPPED value passes through cleaned rather than being dropped or
    guessed at. It then appears in administration_routes as itself, so a
    refresh that adds a 130th spelling shows up as 54 routes where 53 are
    expected instead of being silently absorbed -- the failure mode that let
    -1 stay invisible for so long.
    """
    text = clean_text(raw)
    if text is None:
        return None
    key = route_key(raw)
    if key in ROUTE_NOT_A_ROUTE:
        if manifest is not None:
            manifest.applied("interventions.route_id", "names no route -> NULL")
        return None
    canonical = ROUTE_CANONICAL.get(key)
    if canonical is None:
        return text
    if manifest is not None and canonical != text:
        manifest.applied("administration_routes.nombre", "harmonised")
    return canonical


def substances(intervention, manifest=None):
    """[(key, display name)] for one intervention, in source order.

    Pipe-delimited like financiador, and handled the same way: split, discard
    empties, drop placeholders (884 mentions), deduplicate by key. The
    normalisation matters more here than anywhere else -- 4,244 distinct
    cleaned spellings collapse to 3,364 identities, 20.7%.
    """
    raw = intervention.get("sustancias") or ""
    out = []
    seen = set()
    for part in raw.split("|"):
        if not part.strip():
            continue
        if is_placeholder(part):
            if manifest is not None:
                manifest.applied("substances.nombre",
                                 "placeholder -> no substance")
            continue
        key, name = match_key(part), clean_text(part)
        if key is None or key in seen:
            continue
        seen.add(key)
        out.append((key, name))
    return out


def intervention_rows(record, manifest=None):
    """One Intervention per element of intervenciones.intervencion.

    The block is genuinely optional, unlike centros: it is ABSENT from 1,514
    studies rather than empty, so `record.get` doing the work is the point.

    Nothing here is deduplicated across elements. Two arms of one trial can
    name the same drug, and each is a row: an intervention belongs to its
    study rather than being a shared object, which is why interventions is a
    child table and not a lookup plus a bridge.
    """
    elements = (record.get("intervenciones") or {}).get("intervencion") or []
    rows = []
    for element in elements:
        raw_name = element.get("nombreComercial")
        # 100% present, but '-' appears 1,922 times and 'NA' 283. Same
        # enumerated placeholder list as acronimo and financiador.
        name = None if is_placeholder(raw_name) else clean_text(raw_name)
        if manifest is not None and is_placeholder(raw_name):
            manifest.applied("interventions.nombre_comercial",
                             "placeholder -> NULL")
        raw_huerfano = element.get("huerfano")
        rows.append(Intervention(
            nombre_comercial=name,
            codigo=clean_text(element.get("codigo")),
            # Blank in 25 of 30,946 elements. Blank means absent, which is not
            # the same as the -1 sentinel elsewhere: there is no rule to
            # declare here, only a missing value.
            huerfano=(flag(raw_huerfano)
                      if str(raw_huerfano or "").strip() else None),
            route=route_name(element.get("viasAdministracion"), manifest),
            substances=substances(element, manifest)))
    return rows


def study_row(record, sponsor_id, manifest=None):
    """One studies row. sponsor_id is passed in, not looked up.

    `manifest` counts what the declared rules changed. It is optional so that
    the transform stays usable on its own, and every count is taken from the
    rule's OUTPUT rather than by re-testing its condition -- `is_placeholder`
    is not called twice. Counting by re-running the test would let the manifest
    drift away from the rule it claims to describe, which is the one failure
    mode a manifest must not have.

    Stores the calendario dates as recorded and derives nothing from them. An
    earlier version computed censored/survival_start/survival_end here; that
    is now `analysis/`'s job, because there is no single right answer:

      * authorization to end measures regulatory green light to completion,
        and includes the 445 trials cancelled before enrolling anyone
      * actual start to end measures how long a trial ran, and excludes them
      * authorization to actual start measures site-activation speed

    All three are legitimate and answer different questions, and early
    termination is a competing risk rather than another kind of completion.
    Choosing one here would hide a contested analytical decision in the layer
    least able to explain it. The database stores facts; the analysis layer
    defines what is being measured (PROJECT_SPEC 3.2c).
    """
    calendario = record.get("calendario") or {}
    poblacion = record.get("poblacion") or {}
    proposito = record.get("proposito") or {}
    if manifest is not None:
        manifest.saw_record()

    raw_acronym = record.get("acronimo")
    row = {
        "identificador": record.get("identificador"),
        "sponsor_id": sponsor_id,
        "acronimo": acronym(raw_acronym),
        "enfermedad_rara": flag(record.get("enfermedadRara")),
    }
    if manifest is not None and raw_acronym and raw_acronym.strip():
        # Non-blank in, nothing out: only is_placeholder can do that.
        if row["acronimo"] is None:
            manifest.applied("studies.acronimo", "placeholder -> NULL")
        elif row["acronimo"] != raw_acronym.strip():
            manifest.applied("studies.acronimo", "markup or spacing cleaned")

    for raw_key, column in CALENDARIO_DATES.items():
        row[column] = iso_date(calendario.get(raw_key))

    for source, mapping in ((poblacion, POBLACION_FLAGS),
                            (proposito, PROPOSITO_FLAGS)):
        for raw_key, column in mapping.items():
            raw = source.get(raw_key)
            row[column] = clean_flag(flag(raw))
            # Every flag is present in every record and is 0, 1 or -1, so a
            # NULL out of a non-None in can only be the sentinel.
            if manifest is not None and raw is not None and row[column] is None:
                manifest.applied("studies." + column, "-1 (unknown) -> NULL")

    raw_total = poblacion.get("total")
    row["poblacion_total"] = clean_total(integer(raw_total))
    if manifest is not None and raw_total is not None \
            and row["poblacion_total"] is None:
        # Two sentinels with different meanings, counted apart: one is the
        # registry declining to report, the other is a value that is not a
        # count at all (PROJECT_SPEC 3.2c).
        manifest.applied(
            "studies.poblacion_total",
            "0 (not reported) -> NULL" if integer(raw_total) == TOTAL_UNKNOWN
            else "not a count -> NULL")
    return row
