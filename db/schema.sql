-- Spain clinical trials landscape - relational schema (SQLite)
--
-- Phase 2.2, slices 1-2: sponsors, studies, funders, therapeutic areas.
-- Remaining tables follow in later slices. Design rationale and the evidence
-- behind each decision live in
-- PROJECT_SPEC.md 3.2c and docs/phase2-schema-erd.html - not repeated here.
--
-- Conventions:
--   STRICT      declared types are enforced (SQLite ignores them otherwise).
--               Limits columns to INT/INTEGER/REAL/TEXT/BLOB/ANY.
--   dates       TEXT, ISO-8601. SQLite has no DATE type. The source ships
--               'DD-MM-YYYY', so the GLOB check is what stops an unconverted
--               value loading silently and breaking every date comparison.
--   booleans    INTEGER 0/1 + CHECK. SQLite has no BOOLEAN type; the source
--               ships the strings "0"/"1".
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
DROP TABLE IF EXISTS study_therapeutic_areas;
DROP TABLE IF EXISTS study_centers;
DROP TABLE IF EXISTS study_funders;
DROP TABLE IF EXISTS therapeutic_areas;
DROP TABLE IF EXISTS centers;
DROP TABLE IF EXISTS funders;
DROP TABLE IF EXISTS studies;
DROP TABLE IF EXISTS sponsors;


-- ---------------------------------------------------------------------------
-- sponsors - from organismo.promotor, deduplicated by name
-- ---------------------------------------------------------------------------
-- One sponsor per study: organismo is a dict in 11,847/11,847 records, never a
-- list. Sponsor contact fields (mail/telefono/personaContacto) are excluded as
-- named-individual data.
CREATE TABLE sponsors (
    -- INTEGER PRIMARY KEY aliases the rowid, so ids auto-assign without the
    -- AUTOINCREMENT keyword, which costs writes and buys nothing here.
    sponsor_id  INTEGER PRIMARY KEY,
    promotor    TEXT NOT NULL UNIQUE
) STRICT;


-- ---------------------------------------------------------------------------
-- studies - one row per trial, the hub every other table hangs off
-- ---------------------------------------------------------------------------
CREATE TABLE studies (
    -- NOT NULL is explicit because SQLite does not imply it from PRIMARY KEY
    -- on non-INTEGER columns.
    identificador               TEXT NOT NULL PRIMARY KEY,
    sponsor_id                  INTEGER NOT NULL REFERENCES sponsors(sponsor_id)
                                    ON DELETE RESTRICT,
    acronimo                    TEXT,   -- often ' NA '/blank; loader maps to NULL
    enfermedad_rara             INTEGER NOT NULL CHECK (enfermedad_rara IN (0, 1)),

    -- derived at load so Phase 4 never re-derives censoring per notebook.
    -- censored = 1 means the trial had not ended at extraction, so its true
    -- duration is only known to be at least survival_end - survival_start.
    censored                    INTEGER NOT NULL CHECK (censored IN (0, 1)),
    survival_start              TEXT NOT NULL CHECK (survival_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    survival_end                TEXT NOT NULL CHECK (survival_end   GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),

    -- calendario: 9 of 11 fields (fechaClasificacion and fechaFinPrevista are
    -- 0% filled in both cohorts sampled, so dropped)
    fecha_autorizacion_aemps    TEXT NOT NULL CHECK (fecha_autorizacion_aemps GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_registro              TEXT NOT NULL CHECK (fecha_registro           GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_inicio_prevista       TEXT          CHECK (fecha_inicio_prevista    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_inicio_real           TEXT          CHECK (fecha_inicio_real        GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_real_espana       TEXT          CHECK (fecha_fin_real_espana    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_real_global       TEXT          CHECK (fecha_fin_real_global    GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_interrupcion          TEXT          CHECK (fecha_interrupcion       GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_reinicio              TEXT          CHECK (fecha_reinicio           GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    fecha_fin_prematuro         TEXT          CHECK (fecha_fin_prematuro      GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),

    -- poblacion: 18 flags + planned total.
    -- mujer_usa/mujer_no_usa meanings are INFERRED, not documented by AEMPS.
    voluntarios_sanos           INTEGER NOT NULL CHECK (voluntarios_sanos IN (0, 1)),
    pacientes                   INTEGER NOT NULL CHECK (pacientes         IN (0, 1)),
    pob_vulnerable              INTEGER NOT NULL CHECK (pob_vulnerable    IN (0, 1)),
    mujer_usa                   INTEGER NOT NULL CHECK (mujer_usa         IN (0, 1)),
    mujer_no_usa                INTEGER NOT NULL CHECK (mujer_no_usa      IN (0, 1)),
    embarazadas                 INTEGER NOT NULL CHECK (embarazadas       IN (0, 1)),
    lactancia                   INTEGER NOT NULL CHECK (lactancia         IN (0, 1)),
    urgencia                    INTEGER NOT NULL CHECK (urgencia          IN (0, 1)),
    incapaces                   INTEGER NOT NULL CHECK (incapaces         IN (0, 1)),
    intrauteros                 INTEGER NOT NULL CHECK (intrauteros       IN (0, 1)),
    prematuros                  INTEGER NOT NULL CHECK (prematuros        IN (0, 1)),
    recien_nacido               INTEGER NOT NULL CHECK (recien_nacido     IN (0, 1)),
    preescolar                  INTEGER NOT NULL CHECK (preescolar        IN (0, 1)),
    ninos                       INTEGER NOT NULL CHECK (ninos             IN (0, 1)),
    adolescentes                INTEGER NOT NULL CHECK (adolescentes      IN (0, 1)),
    adultos                     INTEGER NOT NULL CHECK (adultos           IN (0, 1)),
    ancianos                    INTEGER NOT NULL CHECK (ancianos          IN (0, 1)),
    menores                     INTEGER NOT NULL CHECK (menores           IN (0, 1)),
    -- 0 means "not yet reported", not "zero planned" (~18% of the 2019 cohort).
    -- Analysis must exclude 0, not average it.
    poblacion_total             INTEGER NOT NULL CHECK (poblacion_total >= 0),

    -- proposito: phase, purpose, objective, data-source flags.
    -- The four phase columns are independent, NOT an enum - combined-phase
    -- trials ("II/III") set two flags.
    fase_uno                    INTEGER NOT NULL CHECK (fase_uno          IN (0, 1)),
    fase_dos                    INTEGER NOT NULL CHECK (fase_dos          IN (0, 1)),
    fase_tres                   INTEGER NOT NULL CHECK (fase_tres         IN (0, 1)),
    fase_cuatro                 INTEGER NOT NULL CHECK (fase_cuatro       IN (0, 1)),
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
    farmacoeconomica            INTEGER NOT NULL CHECK (farmacoeconomica  IN (0, 1)),
    atencion_primaria           INTEGER NOT NULL CHECK (atencion_primaria      IN (0, 1)),
    atencion_personalizada      INTEGER NOT NULL CHECK (atencion_personalizada IN (0, 1)),
    hospitalizacion             INTEGER NOT NULL CHECK (hospitalizacion   IN (0, 1)),
    medico                      INTEGER NOT NULL CHECK (medico            IN (0, 1)),
    farmaceutico                INTEGER NOT NULL CHECK (farmaceutico      IN (0, 1)),
    historial_clinico           INTEGER NOT NULL CHECK (historial_clinico IN (0, 1)),
    bases_datos                 INTEGER NOT NULL CHECK (bases_datos       IN (0, 1)),
    otras_fuentes               INTEGER NOT NULL CHECK (otras_fuentes     IN (0, 1))
) STRICT;

-- SQLite auto-indexes PRIMARY KEY and UNIQUE, but never the child side of a
-- foreign key - without this, every sponsor JOIN scans all of studies.
CREATE INDEX idx_studies_sponsor_id ON studies(sponsor_id);

-- Range scans for the commonest filters: trials per year, pre/post-CTIS split.
CREATE INDEX idx_studies_fecha_autorizacion ON studies(fecha_autorizacion_aemps);


-- ---------------------------------------------------------------------------
-- funders - from organismo.financiador, pipe-split, deduplicated by name
-- ---------------------------------------------------------------------------
-- Many-to-many with studies, unlike sponsor: 271/11,847 studies list more than
-- one funder (up to 12).
--
-- Deduplicated on the exact string, so 129 names that differ only by case
-- survive as separate rows. Case-folding or fuzzy-matching sponsor names is a
-- data-cleaning decision needing its own evidence; it is not made silently here.
CREATE TABLE funders (
    funder_id   INTEGER PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE
) STRICT;

-- Bridge: one row per (study, funder) pairing. The pair itself is the key, so
-- the same funder cannot be recorded twice for one study.
-- NOT NULL is explicit again - a composite PRIMARY KEY does not imply it.
-- ON DELETE CASCADE, not RESTRICT: a pairing is part of its parents rather
-- than a reference to them, so it has no meaning once either side is gone.
CREATE TABLE study_funders (
    study_id    TEXT NOT NULL REFERENCES studies(identificador) ON DELETE CASCADE,
    funder_id   INTEGER NOT NULL REFERENCES funders(funder_id)  ON DELETE CASCADE,
    PRIMARY KEY (study_id, funder_id)
) STRICT;

-- The composite PK indexes (study_id, funder_id), which answers "funders of
-- this study". The reverse question, "studies of this funder", needs its own
-- index because the PK's index cannot be searched by its second column alone.
CREATE INDEX idx_study_funders_funder_id ON study_funders(funder_id);


-- ---------------------------------------------------------------------------
-- therapeutic_areas - coded disease/indication lookup (EU CT vocabulary)
-- ---------------------------------------------------------------------------
-- Only 55 distinct codes across the whole corpus, each with one consistent
-- name pair, so eutct_code is safe as a natural primary key - no surrogate id
-- needed. Raw field name is 'eutct'; '_code' is added for readability.
CREATE TABLE therapeutic_areas (
    eutct_code  TEXT NOT NULL PRIMARY KEY,
    nombre_es   TEXT NOT NULL,
    nombre_en   TEXT NOT NULL
) STRICT;

-- Bridge: areasTerapeuticas.area is always a list, and 363/11,847 studies
-- carry more than one area, so this cannot be a column on studies.
CREATE TABLE study_therapeutic_areas (
    study_id    TEXT NOT NULL REFERENCES studies(identificador)            ON DELETE CASCADE,
    eutct_code  TEXT NOT NULL REFERENCES therapeutic_areas(eutct_code)     ON DELETE CASCADE,
    PRIMARY KEY (study_id, eutct_code)
) STRICT;

-- Same reasoning as above: the PK covers "areas of this study", this covers
-- "studies in this area" - which is the therapeutic-landscape question.
CREATE INDEX idx_study_therapeutic_areas_eutct ON study_therapeutic_areas(eutct_code);


-- ---------------------------------------------------------------------------
-- centers - hospitals and sites, deduplicated on referencia
-- ---------------------------------------------------------------------------
-- Identity is the raw 'referencia', not the name. 179 of 1,597 referencias
-- appear under several spellings of one hospital ("HOSPITAL UNIVERSITARI VALL
-- D'HEBRON" / "Hospital Universitari Vall D Hebron" / "Hospital Universitari
-- Vall d'Hebron"), so deduplicating by name would split single hospitals into
-- several. The loader picks the most frequent spelling for nombre.
--
-- Geography is deliberately NOT here - it is per-trial and lives on the bridge
-- below. investigador is excluded as named-individual data (PROJECT_SPEC 3.2c).
CREATE TABLE centers (
    center_id   INTEGER PRIMARY KEY,
    -- 2,695 of 85,410 raw entries have no referencia, so it cannot be the
    -- primary key and must stay nullable.
    referencia  TEXT,
    nombre      TEXT NOT NULL,
    -- Observed values are '0'/'1'/'2'/'', NOT the CAP/CHN the AEMPS manual
    -- documents (§4.7) - another manual-vs-live discrepancy. Left unconstrained
    -- rather than pinned to today's four values, so a refresh cannot fail on a
    -- new one. Meaning is undecoded; do not present it as site type.
    tipo        TEXT
) STRICT;

-- Identity in two parts, because it is genuinely conditional: a referencia when
-- there is one, otherwise the name. Partial unique indexes state that directly.
-- A plain UNIQUE(referencia) could not express it - SQL treats every NULL as
-- distinct, so all 2,695 blank-referencia sites would slip through unchecked.
CREATE UNIQUE INDEX idx_centers_referencia
    ON centers(referencia) WHERE referencia IS NOT NULL;
CREATE UNIQUE INDEX idx_centers_nombre_no_ref
    ON centers(nombre)     WHERE referencia IS NULL;


-- ---------------------------------------------------------------------------
-- study_centers - bridge, many-to-many, plus per-trial attributes
-- ---------------------------------------------------------------------------
-- Every text column here describes the pairing, not the hospital:
--   departamento  the same hospital runs different trials through different
--                 services; 2,980 (study, center) pairs list more than one.
--   provincia/ccaa/cod_postal  a referencia can span real campuses - e.g.
--                 Clinica Universidad de Navarra reports 1,400 rows in Navarra
--                 and 545 in Madrid. Storing region per trial keeps those 545
--                 in Madrid instead of resolving the site to one region.
--
-- Hence the six-column key: one row per distinct combination actually reported.
-- The ERD's three-column key was too narrow - it was justified by distinct
-- (departamento, investigador) pairs, but investigador is excluded, so 1,265
-- rows would have been rejected at load.
--
-- LOADER: every text part of the key must be '' when blank, never NULL. SQL
-- treats each NULL as distinct for uniqueness, so blank rows would duplicate
-- instead of collapsing - exactly where the value is unknown. 495 remaining
-- duplicates differ only in domicilio/localidad/investigador/situacion, none
-- of which is stored, so the loader collapses them.
CREATE TABLE study_centers (
    study_id     TEXT NOT NULL REFERENCES studies(identificador) ON DELETE CASCADE,
    center_id    INTEGER NOT NULL REFERENCES centers(center_id)  ON DELETE CASCADE,
    departamento TEXT NOT NULL,
    provincia    TEXT NOT NULL,
    ccaa         TEXT NOT NULL,
    -- TEXT, not INTEGER: 25,477 entries have a leading zero ('08036'), and the
    -- field also carries free text ('Madrid', '46014,', '3584 AE').
    cod_postal   TEXT NOT NULL,
    PRIMARY KEY (study_id, center_id, departamento, provincia, ccaa, cod_postal)
) STRICT;

-- "Which studies ran at this hospital" - the leading column of the PK is
-- study_id, so that direction needs its own index.
CREATE INDEX idx_study_centers_center_id ON study_centers(center_id);

-- Drives the geography question: trials per region, and the Madrid choropleth.
CREATE INDEX idx_study_centers_ccaa ON study_centers(ccaa);
