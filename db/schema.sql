-- Spain clinical trials landscape - relational schema (SQLite)
--
-- Slice 1: sponsors + studies. Later slices append funders,
-- therapeutic_areas, centers and interventions.
--
-- Written from db/profile.py's reports over all 11,847 cached records. The
-- evidence behind every decision is in PROJECT_SPEC.md 3.2c and
-- docs/phase2-schema-erd.html; the counts quoted here are pointers to it,
-- not the argument itself.
--
-- Conventions:
--   STRICT      declared types are enforced (SQLite ignores them otherwise).
--   dates       TEXT, ISO-8601. SQLite has no DATE type. The source ships
--               'DD-MM-YYYY', so the GLOB check is what stops an unconverted
--               value loading silently and breaking every date comparison.
--   booleans    INTEGER 0/1 + CHECK. SQLite has no BOOLEAN type.
--   NULL        a CHECK passes when it evaluates to NULL, so dropping
--               NOT NULL is all that is needed to let a sentinel through as
--               NULL - the CHECK still constrains every non-NULL value.
--   names       raw REEC field names, snake_cased, so each column is directly
--               checkable against an API response.
--
-- Rebuild:  sqlite3 data/trials.db < db/schema.sql
-- The .db is a disposable build artifact; data/raw/ is the durable copy.

-- Connection-scoped, not stored in the file: SQLite ignores foreign keys
-- unless every connection sets this, so the application must repeat it on
-- each connect or the FKs below are decorative.
PRAGMA foreign_keys = ON;

-- Dropped children-first, so no statement removes a table another still
-- references.
DROP TABLE IF EXISTS studies;
DROP TABLE IF EXISTS sponsors;


-- ---------------------------------------------------------------------------
-- sponsors - from organismo.promotor
-- ---------------------------------------------------------------------------
-- One sponsor per study: organismo is a dict in 11,847/11,847 records, never a
-- list. Contact fields (mail/telefono/personaContacto) are named-individual
-- data and never reach the database.
--
-- Two name columns, because a name is used for two things. Deduplicating on
-- the exact string splits 427 values across 315 real sponsors - 'AstraZeneca
-- AB' and 'Astrazeneca AB' become two rows. Storing only the normalised form
-- instead would put 'astrazeneca ab' on the dashboard.
--
-- Entity resolution stays out of the database: Novartis Farmaceutica S.A. and
-- Novartis Pharma AG are distinct legal entities, and merging them changes
-- what "top sponsor" means. That judgement belongs in analysis/.
CREATE TABLE sponsors (
    -- INTEGER PRIMARY KEY aliases the rowid, so ids auto-assign without the
    -- AUTOINCREMENT keyword, which costs writes and buys nothing here.
    sponsor_id   INTEGER PRIMARY KEY,
    -- rules.match_key output: identity. 3,336 rows.
    promotor_key TEXT NOT NULL UNIQUE CHECK (promotor_key <> ''),
    -- rules.clean_text output: the most frequent CLEANED spelling, for
    -- display. Not the raw mode - that is 'Merck Sharp &amp; Dohme LLC'.
    promotor     TEXT NOT NULL        CHECK (promotor     <> '')
) STRICT;


-- ---------------------------------------------------------------------------
-- studies - one row per trial, the hub every other table hangs off
-- ---------------------------------------------------------------------------
CREATE TABLE studies (
    -- NOT NULL is explicit because SQLite does not imply it from PRIMARY KEY
    -- on non-INTEGER columns. 11,847 present, 11,847 distinct.
    identificador               TEXT NOT NULL PRIMARY KEY
        CHECK (identificador GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]'
            OR identificador GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    -- The registry era, read off the identifier format: EudraCT is 14 chars
    -- (6,843), CTIS 17 (5,004). Generated rather than loaded, so it cannot
    -- disagree with the id it is read from. An exact marker for the CTIS
    -- transition, where a date threshold only approximates one.
    es_ctis                     INTEGER NOT NULL
        GENERATED ALWAYS AS (length(identificador) = 17) VIRTUAL,
    sponsor_id                  INTEGER NOT NULL REFERENCES sponsors(sponsor_id)
                                    ON DELETE RESTRICT,
    -- Display only: 15.3% are real acronyms, 0% from 2023. Blanks and the 19
    -- placeholder spellings ('NA' alone 4,744 times) load as NULL, so '' here
    -- would mean the loader skipped a rule.
    acronimo                    TEXT             CHECK (acronimo <> ''),
    -- The one flag the source sends as a string; the other 42 are integers.
    enfermedad_rara             INTEGER NOT NULL CHECK (enfermedad_rara IN (0, 1)),

    -- calendario - 9 of 11 fields. fechaClasificacion and fechaFinPrevista
    -- are blank in 11,847/11,847 records and are dropped.
    --
    -- No survival columns, and no CHECK across a pair of dates. There is no
    -- single window: authorisation->end covers 6,437 studies, start->end
    -- 5,719, authorisation->start 10,127, and they measure different things.
    -- The loader drops the 4 studies that end before they are authorised.
    -- The estimand is defined in analysis/ (PROJECT_SPEC 3.2c).
    fecha_autorizacion_aemps    TEXT NOT NULL CHECK (fecha_autorizacion_aemps GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_registro              TEXT NOT NULL CHECK (fecha_registro           GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_inicio_prevista       TEXT          CHECK (fecha_inicio_prevista    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_inicio_real           TEXT          CHECK (fecha_inicio_real        GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_real_espana       TEXT          CHECK (fecha_fin_real_espana    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_real_global       TEXT          CHECK (fecha_fin_real_global    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_interrupcion          TEXT          CHECK (fecha_interrupcion       GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_reinicio              TEXT          CHECK (fecha_reinicio           GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_prematuro         TEXT          CHECK (fecha_fin_prematuro      GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),

    -- poblacion - 18 flags + planned total.
    -- These six never carry the -1 sentinel, so they stay NOT NULL.
    voluntarios_sanos           INTEGER NOT NULL CHECK (voluntarios_sanos IN (0, 1)),
    pacientes                   INTEGER NOT NULL CHECK (pacientes         IN (0, 1)),
    pob_vulnerable              INTEGER NOT NULL CHECK (pob_vulnerable    IN (0, 1)),
    adultos                     INTEGER NOT NULL CHECK (adultos           IN (0, 1)),
    ancianos                    INTEGER NOT NULL CHECK (ancianos          IN (0, 1)),
    menores                     INTEGER NOT NULL CHECK (menores           IN (0, 1)),
    -- The other 12 carry an undocumented -1 (54 values), which the loader maps
    -- to NULL. Lossless here only because every one of these fields is present
    -- in 11,847/11,847 records and -1 is the only non-0/1 value, so there are
    -- no existing NULLs for it to collide with. A property of this corpus,
    -- re-checked on refresh rather than assumed.
    -- mujer_usa/mujer_no_usa meanings are INFERRED, not documented by AEMPS.
    mujer_usa                   INTEGER          CHECK (mujer_usa         IN (0, 1)),
    mujer_no_usa                INTEGER          CHECK (mujer_no_usa      IN (0, 1)),
    embarazadas                 INTEGER          CHECK (embarazadas       IN (0, 1)),
    lactancia                   INTEGER          CHECK (lactancia         IN (0, 1)),
    urgencia                    INTEGER          CHECK (urgencia          IN (0, 1)),
    incapaces                   INTEGER          CHECK (incapaces         IN (0, 1)),
    intrauteros                 INTEGER          CHECK (intrauteros       IN (0, 1)),
    prematuros                  INTEGER          CHECK (prematuros        IN (0, 1)),
    recien_nacido               INTEGER          CHECK (recien_nacido     IN (0, 1)),
    preescolar                  INTEGER          CHECK (preescolar        IN (0, 1)),
    ninos                       INTEGER          CHECK (ninos             IN (0, 1)),
    adolescentes                INTEGER          CHECK (adolescentes      IN (0, 1)),
    -- 0 means "not reported" in 2,201 records and loads as NULL, so a stored 0
    -- would mean a trial planning nobody. 999999/99999/114011 load raw: one
    -- record each, and only the first is a known non-count.
    poblacion_total             INTEGER          CHECK (poblacion_total > 0),

    -- proposito - 16 of 24 flags, all strictly 0/1 across the corpus, so this
    -- block needs no sentinel handling. Seven data-source flags are 0 in every
    -- record and are dropped; otras_fuentes varies but means "other" relative
    -- to seven categories nobody ever ticks, so the whole block goes.
    --
    -- Four phase columns, never an enum: 1,436 studies set two and 3 set
    -- three. Every study sets at least one, so a 0 means "not this phase" -
    -- but that is a corpus property, not a constraint, so it is not enforced.
    fase_uno                    INTEGER NOT NULL CHECK (fase_uno          IN (0, 1)),
    fase_dos                    INTEGER NOT NULL CHECK (fase_dos          IN (0, 1)),
    fase_tres                   INTEGER NOT NULL CHECK (fase_tres         IN (0, 1)),
    fase_cuatro                 INTEGER NOT NULL CHECK (fase_cuatro       IN (0, 1)),
    -- Purpose is the opposite case: 6,125 studies (51.7%) set none of these
    -- three, which reads as "not recorded" rather than a trial with no purpose.
    diagnostico                 INTEGER NOT NULL CHECK (diagnostico       IN (0, 1)),
    profilaxis                  INTEGER NOT NULL CHECK (profilaxis        IN (0, 1)),
    tratamiento                 INTEGER NOT NULL CHECK (tratamiento       IN (0, 1)),
    seguridad                   INTEGER NOT NULL CHECK (seguridad         IN (0, 1)),
    eficacia                    INTEGER NOT NULL CHECK (eficacia          IN (0, 1)),
    farmacocinetica             INTEGER NOT NULL CHECK (farmacocinetica   IN (0, 1)),
    farmacodinamica             INTEGER NOT NULL CHECK (farmacodinamica   IN (0, 1)),
    bioequivalencia             INTEGER NOT NULL CHECK (bioequivalencia   IN (0, 1)),
    dosis                       INTEGER NOT NULL CHECK (dosis             IN (0, 1)),
    farmacogenetica             INTEGER NOT NULL CHECK (farmacogenetica   IN (0, 1)),
    farmacogenomica             INTEGER NOT NULL CHECK (farmacogenomica   IN (0, 1)),
    farmacoeconomica            INTEGER NOT NULL CHECK (farmacoeconomica  IN (0, 1))
) STRICT;

-- SQLite auto-indexes PRIMARY KEY and UNIQUE, but never the child side of a
-- foreign key - without this, every sponsor JOIN scans all of studies.
CREATE INDEX idx_studies_sponsor_id ON studies(sponsor_id);

-- Range scans for the commonest filter: trials per year.
CREATE INDEX idx_studies_fecha_autorizacion ON studies(fecha_autorizacion_aemps);
