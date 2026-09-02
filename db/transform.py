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

from db.rules import (
    TOTAL_UNKNOWN,
    clean_flag,
    clean_text,
    clean_total,
    is_placeholder,
    match_key,
)

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
