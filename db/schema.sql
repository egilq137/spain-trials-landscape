-- Spain clinical trials landscape - relational schema (SQLite)
--
-- All four slices: sponsors, studies, funders, therapeutic areas, centers,
-- interventions.
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
DROP TABLE IF EXISTS intervention_substances;
DROP TABLE IF EXISTS study_centers;
DROP TABLE IF EXISTS study_therapeutic_areas;
DROP TABLE IF EXISTS study_funders;
DROP TABLE IF EXISTS interventions;
DROP TABLE IF EXISTS substances;
DROP TABLE IF EXISTS administration_routes;
DROP TABLE IF EXISTS centers;
DROP TABLE IF EXISTS therapeutic_areas;
DROP TABLE IF EXISTS funders;
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
    -- cleaning_rules.organisation_key output: identity. 2,967 rows.
    promotor_key TEXT NOT NULL UNIQUE CHECK (promotor_key <> ''),
    -- cleaning_rules.clean_text output: the most frequent CLEANED spelling, for
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


-- ---------------------------------------------------------------------------
-- funders - from organismo.financiador, pipe-split
-- ---------------------------------------------------------------------------
-- Many-to-many, unlike sponsor: 271 studies list more than one funder, up to
-- 12. The delimiter is inconsistent - 5,280 values end with a trailing '|' and
-- 1,563 do not - so the loader splits on '|' and discards empties.
--
-- Same two-column shape as sponsors, and keyed the same way: 2,712 distinct
-- cleaned names collapse to 2,216 identities, so 496 (18.3%) are variants of
-- a name already present -- case, accents, spacing, markup, punctuation, or a
-- descriptive clause tacked onto the end.
--
-- Deliberately NOT merged with sponsors into one organisations table, even
-- though the two overlap heavily. Sharing an id space would mean deciding
-- which sponsor rows and which funder rows are the same organisation, which
-- is entity resolution - a judgement, made at load, that every foreign key
-- would then depend on. Two tables assert only what the two source fields
-- said; analysis/ can relate them where the rule can be shown.
--
-- WHAT THIS TABLE IS FOR, AND IS NOT. financiador is recorded for
-- 6,843/6,843 EudraCT-era studies and 0/5,004 CTIS-era ones, and in 3,702 of
-- those 6,843 (54.1%) the sole funder is the sponsor respelled. So it carries
-- information beyond promotor for 3,141 studies - 26% of the corpus, all of
-- it pre-2023. It supports a pre-CTIS subgroup analysis (industry money
-- behind academically sponsored trials) and a sensitivity check on the
-- sponsor-based split. It is NOT a corpus-wide funder census, and any
-- "who funds Spanish trials" claim built on it is answering a question about
-- one era with a denominator of a quarter.
CREATE TABLE funders (
    funder_id  INTEGER PRIMARY KEY,
    -- cleaning_rules.match_key output: identity, same rule as sponsors.promotor_key.
    nombre_key TEXT NOT NULL UNIQUE CHECK (nombre_key <> ''),
    -- cleaning_rules.clean_text output, for display.
    nombre     TEXT NOT NULL        CHECK (nombre     <> '')
) STRICT;

-- Bridge: one row per (study, funder) pairing, the pair itself the key, so one
-- funder cannot be recorded twice for one study.
-- NOT NULL is explicit again - a composite PRIMARY KEY does not imply it.
-- ON DELETE CASCADE, not RESTRICT: a pairing is part of its parents rather
-- than a reference to them, so it has no meaning once either side is gone.
--
-- 'NA' is the most frequent funder name in the source (572 occurrences), and
-- placeholders create neither a funder nor a bridge row - a missing bridge row
-- already means "no funder recorded", so this needs no representation here.
-- Enforced in the loader against cleaning_rules.PLACEHOLDERS rather than by a CHECK:
-- restating the list in SQL would be a second copy that can drift from the one
-- the loader actually applies.
CREATE TABLE study_funders (
    study_id  TEXT    NOT NULL REFERENCES studies(identificador) ON DELETE CASCADE,
    funder_id INTEGER NOT NULL REFERENCES funders(funder_id)     ON DELETE CASCADE,
    PRIMARY KEY (study_id, funder_id)
) STRICT;

-- The composite PK indexes (study_id, funder_id), which answers "funders of
-- this study". The reverse question needs its own index, because the PK's
-- index cannot be searched by its second column alone.
CREATE INDEX idx_study_funders_funder_id ON study_funders(funder_id);


-- ---------------------------------------------------------------------------
-- therapeutic_areas - coded disease/indication lookup (EU CT vocabulary)
-- ---------------------------------------------------------------------------
-- The cleanest field in the source: areasTerapeuticas.area is a list in
-- 11,847/11,847 records, every study has at least one, and all three fields
-- are present in 12,289/12,289 elements with no blanks.
--
-- eutct is a safe natural primary key - 55 distinct codes, and none carries
-- more than one name pair. The names are functionally dependent on the code,
-- so they belong here and never on the bridge, and no surrogate id is needed.
--
-- Names embed a category code ('Diseases [C] - Cancer [C04]'). Not extracted:
-- eutct already keys the table, so a second identifier would be redundant.
CREATE TABLE therapeutic_areas (
    eutct_code TEXT NOT NULL PRIMARY KEY CHECK (eutct_code <> ''),
    nombre_es  TEXT NOT NULL             CHECK (nombre_es  <> ''),
    nombre_en  TEXT NOT NULL             CHECK (nombre_en  <> '')
) STRICT;

-- Bridge, and load-bearing rather than defensive: 12,289 elements over 11,847
-- studies, so 442 extra memberships across 363 studies that a column on
-- studies would lose.
CREATE TABLE study_therapeutic_areas (
    study_id   TEXT NOT NULL REFERENCES studies(identificador)        ON DELETE CASCADE,
    eutct_code TEXT NOT NULL REFERENCES therapeutic_areas(eutct_code) ON DELETE CASCADE,
    PRIMARY KEY (study_id, eutct_code)
) STRICT;

-- Same reasoning as above: the PK covers "areas of this study", this covers
-- "studies in this area" - which is the therapeutic-landscape question.
CREATE INDEX idx_study_therapeutic_areas_eutct ON study_therapeutic_areas(eutct_code);


-- ---------------------------------------------------------------------------
-- centers - one row per physical site, not per registry reference
-- ---------------------------------------------------------------------------
-- A centre is keyed on (reference-or-name, localidad, cod_postal). Measured
-- over 85,410 entries, that grain is what makes the geography stable:
--
--   identity                        sites   (study, centre) pairs disagreeing
--   referencia only                 2,849   1,616
--   referencia + postcode           3,114     488
--   referencia + locality           3,228     661
--   reference-or-name + both        3,336      11
--
-- referencia alone is too coarse in both directions. It is missing from 2,695
-- entries, and 'NR' appears in 119 covering 103 distinct hospitals, so
-- placeholders must fall through to the name. And one reference can cover
-- several real sites: Clinica Universidad de Navarra reports Pamplona and
-- Madrid under ORG-100007650, Institut Catala d'Oncologia reports Badalona,
-- Hospitalet and Girona under ORG-100030394.
--
-- Consequences, all simplifications: geography lives here rather than
-- repeating across 85,410 bridge rows, study_centers is a plain pair, and the
-- 545 Madrid trials at CUN stay in Madrid without any resolution step.
--
-- Dropped: tipo and situacion (undocumented codes the manual describes
-- wrongly, used by no question), departamento (8,268 free-text values mixing
-- languages and casing), domicilio and investigador (named-individual and
-- street-level data). All remain in data/raw/.
CREATE TABLE centers (
    center_id  INTEGER PRIMARY KEY,
    -- The identity part of the key: referencia when it is a real reference,
    -- otherwise cleaning_rules.match_key of the name. Computed by the loader because
    -- the choice between the two is conditional. CHECK (<> '') is what stops
    -- the 5 entries that name no site - 3 blank in every field but situacion,
    -- 2 whose name is '.' or '-' - from collapsing into one nameless centre
    -- that every study reporting one would appear to share. 3,335 sites load
    -- (3,336 before the four impossible-date studies go); 3.2c's 3,361
    -- counted those five as one and predated punctuation-insensitive names.
    center_key TEXT NOT NULL CHECK (center_key <> ''),
    -- Kept alongside the key so a site can be traced back to what the
    -- registry sent. NULL for the 2,695 entries with none and the 119 'NR's.
    referencia TEXT             CHECK (referencia <> ''),
    -- The most frequent cleaned spelling, resolved over the corpus: the two
    -- commonest name values are one hospital, HOSPITAL UNIVERSITARI VALL
    -- D'HEBRON (2,667) and Hospital Universitari Vall D Hebron (1,553).
    nombre     TEXT NOT NULL    CHECK (nombre <> ''),

    -- Geography. The two key parts are '' when blank and never NULL: SQL
    -- treats every NULL as distinct, so a NULL here would defeat the UNIQUE
    -- below and duplicate exactly the sites whose locality is unknown.
    localidad  TEXT NOT NULL,
    -- TEXT, never INTEGER: 25,477 values have a leading zero, 290 are missing
    -- a digit, and 11 are not postcodes at all ('08006.', '3584 AE',
    -- 'Madrid'). No format CHECK, deliberately - the 7 postcodes the
    -- triangulation rule cannot resolve are stored raw on purpose, and a
    -- CHECK would turn a documented gap into a load failure.
    cod_postal TEXT NOT NULL,
    -- Not part of the key, so these use NULL rather than '' for "never
    -- reported". Resolved per site by most frequent non-blank value; 149
    -- sites disagree, 132 only because one variant is blank.
    -- provincia is a clean vocabulary containing wrong assignments - 258 rows
    -- name a province the postcode contradicts - so province-level
    -- aggregation derives the province from the postcode prefix in analysis/,
    -- where the assumption can be stated. Do not group by this column.
    provincia  TEXT             CHECK (provincia <> ''),
    ccaa       TEXT             CHECK (ccaa      <> ''),

    -- The identity rule itself. One constraint over three present columns,
    -- rather than partial indexes: the conditional part (reference or name)
    -- is already resolved into center_key by the loader, so the schema has a
    -- single unambiguous key to enforce.
    UNIQUE (center_key, localidad, cod_postal)
) STRICT;

-- Bridge: one row per (study, site). 147 studies list no centre at all and
-- simply have no rows here; the rest average 7.2 sites, maximum 93.
-- Nothing else belongs on it - with the site grain above, every attribute
-- that used to vary per pairing is a property of the site.
CREATE TABLE study_centers (
    study_id  TEXT    NOT NULL REFERENCES studies(identificador) ON DELETE CASCADE,
    center_id INTEGER NOT NULL REFERENCES centers(center_id)     ON DELETE CASCADE,
    PRIMARY KEY (study_id, center_id)
) STRICT;

-- "Which studies ran at this hospital" - the geography question, and the
-- direction the PK's index cannot answer.
CREATE INDEX idx_study_centers_center_id ON study_centers(center_id);

-- No index on ccaa or cod_postal: geography moved onto centers, which is
-- 3,335 rows. A region rollup scans that in full whatever the plan, and the
-- 85,410-row version this replaces is what needed one.


-- ---------------------------------------------------------------------------
-- administration_routes - the 53 canonical routes
-- ---------------------------------------------------------------------------
-- A lookup with a plain foreign key from interventions, NOT a bridge. The
-- source pipe-delimits the field, implying a list, but 0 of 17,268 populated
-- elements carry two: the delimiter models a relationship the data never uses.
--
-- The 129 raw values reach 53 canonical routes through cleaning_rules.ROUTE_CANONICAL,
-- which merges phrasing ('oral' / 'oral use'), real misspellings
-- ('intravenious infusion', 466 rows) and forms that name their route
-- unambiguously. Every raw value must appear in exactly one of the two route
-- maps; tests/test_cleaning_rules.py fails on a fallthrough or a dead entry.
--
-- No grupo column. Merging 'oral use' into 'oral' is mechanical; deciding
-- that intramuscular counts as "other" is a judgement about what a question
-- is asking, so the coarse buckets live in analysis/ where they can vary per
-- question. The 53 routes ARE the grouping the database stores.
--
-- Two canonical values name a gap rather than a route, and are stored because
-- naming the gap is more honest than a NULL that could mean anything:
-- 'injection, route unspecified' (a dosage form, not a route) and 'multiple
-- routes' (16 values over 256 rows that genuinely name two, e.g. 'oral and
-- iv'). The 299 rows saying 'unknown use' or 'other use' name no route at all
-- and get no route_id - cleaning_rules.ROUTE_NOT_A_ROUTE.
CREATE TABLE administration_routes (
    route_id INTEGER PRIMARY KEY,
    nombre   TEXT NOT NULL UNIQUE CHECK (nombre <> '')
) STRICT;


-- ---------------------------------------------------------------------------
-- substances - active ingredients, from the pipe-delimited sustancias field
-- ---------------------------------------------------------------------------
-- Same two-column identity pattern as sponsors, funders and centers, and here
-- on the strongest evidence of the four: profiled per substance rather than
-- per pipe-joined string, 15,130 mentions give 4,244 distinct cleaned
-- spellings against 3,305 identities, so 939 merge - 22.1%.
--
-- 884 mentions are placeholders ('N/A', 'NA', 'Not available'). They create no
-- substance and no bridge row, the same rule as funders and empty centres.
CREATE TABLE substances (
    substance_id INTEGER PRIMARY KEY,
    nombre_key   TEXT NOT NULL UNIQUE CHECK (nombre_key <> ''),
    nombre       TEXT NOT NULL        CHECK (nombre     <> '')
) STRICT;


-- ---------------------------------------------------------------------------
-- interventions - one row per intervention element, a child of studies
-- ---------------------------------------------------------------------------
-- Not deduplicated into a lookup plus a bridge, unlike every other repeated
-- name in this schema. An element carries its own codigo, huerfano and route,
-- so two studies using KEYTRUDA are describing their own arm rather than
-- referencing a shared object; and 11,259 distinct commercial names over
-- 30,946 elements is a drug-identity problem that would need its own
-- evidence. Rows here belong to their study and cascade with it.
--
-- The block is genuinely optional, unlike centros: intervenciones is ABSENT
-- from 1,514 studies, and 1,516 end up with no intervention. The rest average
-- 3.0, maximum 98.
--
-- Dropped: atcs (empty in all 30,946 elements, taking a planned lookup and
-- bridge with it), nombreCientifico (identical to nombreComercial in 90.3% of
-- elements - 27,949 duplicated values to preserve 2,997 differences),
-- formaFarmaceutica in both languages (no question uses dosage form, 56.4%
-- placeholder, and the two language columns are swapped for exactly that
-- value), and tipo, which the AEMPS manual documents and the endpoint does
-- not return.
CREATE TABLE interventions (
    intervention_id  INTEGER PRIMARY KEY,
    study_id         TEXT NOT NULL REFERENCES studies(identificador)
                         ON DELETE CASCADE,
    -- 100% present, but '-' appears 1,922 times and 'NA' 283, so placeholders
    -- load as NULL and the column is nullable.
    nombre_comercial TEXT    CHECK (nombre_comercial <> ''),
    -- 78.7% present, and improving: 52% through 2021, 100% from 2024.
    codigo           TEXT    CHECK (codigo <> ''),
    -- A string '0'/'1' in the source like enfermedadRara, not an integer like
    -- the studies flags. 25 blanks, so nullable; 2,447 orphan-designated.
    huerfano         INTEGER CHECK (huerfano IN (0, 1)),
    -- Nullable, and mostly NULL: the field is populated in 17,268 of 30,946
    -- elements and only from 2022 onward. RESTRICT rather than CASCADE - a
    -- route is a shared vocabulary entry, so deleting one should fail loudly
    -- rather than quietly delete the interventions using it.
    route_id         INTEGER REFERENCES administration_routes(route_id)
                         ON DELETE RESTRICT
) STRICT;

-- The child side of both foreign keys, neither indexed by SQLite on its own.
CREATE INDEX idx_interventions_study_id ON interventions(study_id);
CREATE INDEX idx_interventions_route_id ON interventions(route_id);

-- Bridge, and the one the intervention data actually supports: 512 elements
-- list two substances, 182 three, and the tail runs to 45.
CREATE TABLE intervention_substances (
    intervention_id INTEGER NOT NULL REFERENCES interventions(intervention_id)
                        ON DELETE CASCADE,
    substance_id    INTEGER NOT NULL REFERENCES substances(substance_id)
                        ON DELETE CASCADE,
    PRIMARY KEY (intervention_id, substance_id)
) STRICT;

-- "Which trials used this substance" - the reverse of the PK's leading column.
CREATE INDEX idx_intervention_substances_substance_id
    ON intervention_substances(substance_id);

-- A note the schema cannot express, and the one most likely to be forgotten:
-- sustancias and viasAdministracion NEVER co-occur. Not one element of 30,946
-- has both - substances run 97-98% through 2021 then 0% from 2024, routes 0%
-- through 2021 then 96-100% from 2023. The source swapped one for the other at
-- the CTIS transition. So neither column covers the corpus, and a substance is
-- not a route: this is a real loss of comparability across the break, not a
-- rename. Any analysis of either is confined to one side of it.
