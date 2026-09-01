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
"""

from db.rules import (
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
    "atencionPrimaria": "atencion_primaria",
    "atencionPersonalizada": "atencion_personalizada",
    "hospitalizacion": "hospitalizacion",
    "medico": "medico",
    "farmaceutico": "farmaceutico",
    "historialClinico": "historial_clinico",
    "basesDatos": "bases_datos",
    "otrasFuentes": "otras_fuentes",
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


def sponsor_name(record):
    """organismo.promotor as it should be displayed. Blank -> None.

    Cleaned rather than raw: the raw mode for the largest sponsor is
    `Merck Sharp &amp; Dohme LLC`, which is not a name.
    """
    return clean_text((record.get("organismo") or {}).get("promotor"))


def sponsor_key(record):
    """organismo.promotor as identity. Blank -> None.

    What the loader looks a sponsor up by before handing out a sponsor_id.
    Identity has to be settled before ids exist, because studies.sponsor_id is
    a foreign key -- normalising afterwards would mean merging rows and
    repointing every reference.
    """
    return match_key((record.get("organismo") or {}).get("promotor"))


def study_row(record, sponsor_id):
    """One studies row. sponsor_id is passed in, not looked up.

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

    row = {
        "identificador": record.get("identificador"),
        "sponsor_id": sponsor_id,
        "acronimo": acronym(record.get("acronimo")),
        "enfermedad_rara": flag(record.get("enfermedadRara")),
    }
    for raw_key, column in CALENDARIO_DATES.items():
        row[column] = iso_date(calendario.get(raw_key))
    for raw_key, column in POBLACION_FLAGS.items():
        row[column] = clean_flag(flag(poblacion.get(raw_key)))
    row["poblacion_total"] = clean_total(integer(poblacion.get("total")))
    for raw_key, column in PROPOSITO_FLAGS.items():
        row[column] = clean_flag(flag(proposito.get(raw_key)))
    return row
