---
title: Madrid Data Scientist Portfolio — Project Spec
status: Phase 1 (ingestion) complete — 11,847/11,847 studies. Phase 2.1 (schema design/ERD) done; 2.2 (DDL) in progress — slice 1 (sponsors + studies) written and verified
last updated: 2026-08-31
repo: https://github.com/egilq137/spain-trials-landscape
---

# Portfolio Project Spec: Clinical Data Science (Madrid job search)

## 1. Goal

Build a portfolio project demonstrating clinical/health data science skills relevant
to data scientist roles in Madrid, Spain — informed by patterns seen in real job
postings (IQVIA, Idoven, and general Madrid listings): Python + SQL, statistics
beyond basic ML (survival analysis, hypothesis testing), dashboards for
non-technical stakeholders, familiarity with clinical data structures and
regulatory/privacy awareness, and bilingual (EN/ES) communication.

**Strategic framing:** quality over quantity. Research into what makes portfolios
stand out (and what recruiters flag as red flags) consistently points to: original/
self-sourced data over pre-cleaned Kaggle sets, real deployment (not just
notebooks), thorough documentation with business framing, and the ability to
explain every decision — not volume of projects or leaderboard placement. This
spec is deliberately one focused, deep project rather than several shallow ones.

## 2. Overall structure

**"Spanish Clinical Trials Landscape Analytics"** — Spanish clinical trials
registry (REEC). Real, self-sourced via API. Registry/operations-level metadata —
no patient data, so no GDPR complexity. Covers SQL, API ingestion, time series,
geographic analysis, and survival analysis (applied to trial duration, not
patient outcomes).

---

## 3. Spain Clinical Trials Landscape Analytics

### 3.1 Data source: REEC (Registro Español de Estudios Clínicos / AEMPS)

Public by legal mandate (Ley 29/2006). No authentication required.

**Endpoints actually verified working** (found by testing directly — differ in
some details from the official PDF manual, see quirks below):

1. `https://reec.aemps.es/reec-services/json/getestudios/{fecha}`
   Method: GET · Date format: `dd-MM-yyyy`
   Returns all studies authorized/modified **since** the given date, no upper
   bound. Can return large payloads (2.5MB+ / ~700+ studies for a ~1 year lookback) —
   confirmed working, ~10s response time for that size.

2. `https://reec.aemps.es/reec-services/estudios?fechadesde={d1}&fechahasta={d2}`
   Method: GET · Date format: `dd/MM/yyyy` (**slashes**, not dashes — differs from
   endpoint 1) · Param names are **lowercase** (`fechadesde`/`fechahasta`, not
   camelCase) · Range capped at ~1 year per call (undocumented exact enforcement,
   but the manual states the constraint explicitly).

3. `https://reec.aemps.es/reec-services/json/detalle/{identificador}` — per-study
   detail lookup by EudraCT code or CodigoGESTO. **Confirmed working live** (Phase
   1.3). Not redundant with 1–2 — it's the only source of phase, purpose,
   population, and disease/indication data. ~23KB per study, ~0.2s response with
   connection reuse. Works for both id formats: legacy EudraCT (`2019-000302-29`)
   and CTIS-era (`2023-506669-70-00`), with all blocks populated in both.

4. `https://reec.aemps.es/reec-services/json/hospitales[/{codigo}]` and
   `.../centros[/{codigo}]` — hospital / primary care center directories
   (documented, not yet tested; useful for the geographic analysis).

**Official reference:** AEMPS publishes a manual for this API — "Manual de Interacción
REEC: Servicio de Extracción de Datos" (v1, 12/12/2020):
https://sede.aemps.gob.es/docs/Manual-Interaccion-REEC-Servicio-Extraccion-Datos-v1.pdf
(local copy: `docs/Manual-Interaccion-REEC-Servicio-Extraccion-Datos-v1.pdf`). Cross-checked
against our live testing — matches on the endpoints/params/date-format-per-endpoint
documented above, with one minor inconsistency: the manual's own example response
shows `FechaRegistro` with slashes (`01/02/2013`) inside the JSON/XML body, while our
live pull returned dashes (`29-07-2026`) — trust the live behavior over the example.

**Decision: detail-endpoint enrichment is in scope.** The manual confirms that trial
phase (`FaseUno`–`FaseCuatro`), purpose flags, population/participant totals, and
indication/disease info are **only** available via the `detalle/{identificador}`
endpoint (§4.5–4.6 of the manual) — not on the list endpoints (`getestudios`/`estudios`)
Phase 1's ingestion is built on. This data is valuable enough (phase, population,
disease type feed multiple analysis questions in §3.3) that we're committing to
fetching it, not just the list-level data. Implications, addressed by Phase 1.3
in Section 4 (built and verified; the backfill itself runs in sittings):
- **Sequencing:** detail fetch depends on `identificador` values that only exist after
  list ingestion runs — so it's necessarily a later phase, not a replacement for it.
- **Scale:** ~1 call per study (thousands total) vs. ~1 call per year for the list
  loop — the classic N+1 pattern (cheap to list N things, expensive to fetch each one's
  detail). Needs its own caching/resumability and likely a politeness delay between
  calls.
- **Schema impact:** the Phase 2 `studies` table needs columns sourced only from detail
  data (phase, population total, disease/indication) — design that table with this in
  mind rather than list-only and retrofitted later.

**Known quirks to handle in the ingestion script:**
- **`detalle` returns HTTP 200 for a study that doesn't exist**, with the
  plain-text body `El ensayo no existe en el sistema` under a
  `Content-Type: application/json` header — not a 404, and not parseable JSON.
  Undocumented; found by probing. Failure handling therefore cannot key off
  status codes: parse the body, and match the sentinel by equality after
  stripping (not `in`, or a real record quoting that phrase in a free-text field
  would be silently discarded).
- Two different date formats across endpoints (dashes vs slashes) — do not
  assume consistency.
- Query param names are lowercase and unforgiving (`fechadesde` failed silently
  as a 400 error until case was corrected).
- The site's internal Angular search API (`reec.aemps.es/reec/buscador/...`) is
  a *different*, undocumented API — do not build the pipeline on it. It's
  session-stateful, filter state gets stuck server-side across requests, and its
  list view only exposes 2 of the 11 real date fields. Use the documented
  `reec-services` endpoints above instead.
- Do not print raw fetch URLs containing query strings back through tooling that
  flags "cookie/query string" patterns — build/inspect them without echoing the
  full literal string (encountered during testing, not a data issue, just a
  tooling note).

### 3.2 Record schema (confirmed real, via live pull)

Top-level per study: `identificador`, `acronimo`, `enfermedadRara`, `calendario`
(object below), `organismo` (sponsor), `centros` (participating sites),
`intervenciones`.

`calendario` object — 11 fields:

| Field | Meaning | Fill rate (2019 cohort, n=629) | Fill rate (2025–26 cohort, n=715) |
|---|---|---|---|
| `fechaAutorizacionAEMPS` | AEMPS authorization date | 100.0% | 100.0% |
| `fechaRegistro` | Registration date | 100.0% | 100.0% |
| `fechaClasificacion` | (unused in practice) | 0.0% | 0.0% |
| `fechaInicioPrevista` | Planned start date | 87.0% | 0.0% |
| `fechaFinPrevista` | Planned end date | 0.0% | 0.0% |
| `fechaInicioReal` | **Actual start date** | 87.4% | 55.5% |
| `fechaFinRealEspana` | **Actual end date (Spain)** | 73.3% | 1.3% |
| `fechaFinRealGlobal` | Actual end date (global, multi-country trials) | 56.6% | 0.0% |
| `fechaInterrupcion` | Interruption date | 14.8% | 0.7% |
| `fechaReinicio` | Restart date after interruption | 6.8% | 0.0% |
| `fechaFinPrematuro` | Premature termination date | 26.4% | 1.1% |

**Interpretation:** the low fill rates in the recent cohort are expected
right-censoring (most 2025–26 trials genuinely haven't finished yet), not a data
quality problem — confirmed by the mature 2019 cohort showing strong fill rates
(73–87%) once trials have had years to run their course.

**Design decisions from this pilot:**
- Drop `fechaFinPrevista` and `fechaClasificacion` entirely — genuinely unused
  regardless of cohort age.
- Do not rely on `fechaInicioPrevista` for recent years — inconsistent over time.
- Primary survival window: `fechaAutorizacionAEMPS` → `fechaFinRealEspana`.
  Right-censor at data-extraction date for any study without a real end date.
- `fechaFinPrematuro` (~26% of mature cohort) is a genuine bonus signal — model
  as a distinct event type or covariate rather than discarding it.

### 3.2b Detail record schema (`detalle/{identificador}`, confirmed live)

Blocks beyond what the list endpoints return (~23KB/study):

| Block | Content |
|---|---|
| `proposito` | 24 int 0/1 flags: **`faseUno`–`faseCuatro`**, plus purpose (`tratamiento`, `diagnostico`, `profilaxis`), objective (`seguridad`, `eficacia`, `farmacocinetica`, `bioequivalencia`…) and data-source flags |
| `poblacion` | 19 int flags: `pacientes`, `voluntariossanos`, `pobvulnerable`, age bands (`ninos`, `adultos`, `ancianos`…), plus **`total`** (planned participants) |
| `areasTerapeuticas.area[]` | **coded** therapeutic area: `eutct` id + `nombre_es`/`nombre_en`, e.g. "Diseases [C] - Cardiovascular Diseases [C14]". Not mentioned in the manual's field list; this is the therapeutic-landscape analysis and it needs no text mining |
| `organismo` | sponsor + **`financiador`** (funder — useful for industry vs. academic), plus contact `mail`/`telefono`/`personaContacto` |
| `informacion` | 22 free-text fields ×2 languages (titles, indications, inclusion/exclusion criteria, endpoints). ~80% of the payload bytes; feeds no §3.3 question |
| `centros`, `intervenciones` | richer than the list version (`atcs`, `sustancias`, `formaFarmaceutica`) |
| `calendario` | identical to the list endpoint — useful as a consistency check |

**Design decisions from this pilot:**
- **Phase is not mutually exclusive.** `faseDos` and `faseTres` are both `1` on
  combined-phase trials (seen live). The Phase 2 schema must keep four boolean
  columns or a derived label that can express "II/III" — a single `phase` enum
  would silently mangle them.
- **Keep the whole response** in the raw cache, `informacion` included: refetching
  costs ~4 hours of API calls, re-parsing costs seconds. Field selection is a
  Phase 2 transform concern, not an ingestion concern.
- **Drop the sponsor contact fields at Phase 2** — `mail`/`telefono`/
  `personaContacto` are named individuals' details. Public by mandate, so caching
  them locally (gitignored) is fine, but they must not reach the DB or the
  deployed dashboard. Covered in the README's privacy/limitations section.
- **`poblacion.total` looks right-censored like the `calendario` fields** — 0 on
  4 of 5 sampled 2026 trials, 654/20 on older ones. Measure its fill rate on a
  mature cohort (2019) before relying on it.
- Year in `data/raw/detalle/{year}.jsonl` means "which list file the study came
  from", **not** the trial's own year — `2026.json` contains ids prefixed
  `2024-`/`2025-`. Phase 2 should derive any year column from
  `fechaAutorizacionAEMPS`, not from the filename.

### 3.2c Relational schema design (Phase 2 Step 1 — done)

Full ERD: `docs/phase2-schema-erd.html` (also published as an artifact). **15
tables, 6 many-to-many bridges.** Reviewed as a diagram before any DDL was
written, per the Phase 2 verify step. Every decision below was settled by
querying the cached data rather than by assuming — the counts are the evidence
and are worth keeping, since they're what makes the design defensible.

**Multi-valued fields arrive pipe-delimited and must be normalized.**
`sustancias` (`"DESMOPRESSIN|DESMOPRESSIN2|"`), `atcs`, `viasAdministracion`
and `organismo.financiador` are all lists crammed into one string — a 1NF
violation that would force `LIKE '%…%'` matching instead of joins. Each gets a
lookup table + bridge: `substances`/`atc_codes`/`administration_routes` keyed
off `interventions`, and `funders` keyed off `studies`. Co-funding is real, not
a formatting artifact: **27 of 629** studies in the 2019 cohort list more than
one funder (e.g. Roche + Leap Therapeutics + EORTC).

**Sponsor stays one-to-many; funder is many-to-many.** `organismo` is a `dict`
in **629/629** records checked — REEC never records more than one `promotor`
per study, so `studies.sponsor_id` is a plain FK. Real trials *can* have
co-sponsors; the source simply doesn't capture it, and modelling a
relationship the data can't populate would be wrong. Field name is
`organismo.promotor`, not `nombre`.

**`organismo.financiador` collapses to empty after the CTIS transition — a
serious limitation on any funder analysis.** Measured across the full corpus
when writing the slice-2 DDL, not sampled:

| Year | Studies with no funder recorded |
|---|---|
| 2017–2021 | 0% (fully populated, n=6,396) |
| 2022 | 31.5% (164/521) |
| 2023 | 92.4% (1,075/1,164) |
| 2024–2026 | 100% (3,766/3,766) |

Overall 5,004/11,847 (42%) carry no funder at all. The cutover matches the
January 2023 CTIS transition, so this is almost certainly a registry-practice
change rather than genuinely unfunded trials — the same break the volume
question is looking for. Consequences: **funder-based analysis is confined to
2017–2021**, and any funder count trended over time would show a fake
collapse. `sponsor` is unaffected (100% present in all 11,847). Note the
`study_funders` bridge represents this correctly with no special handling —
a study with no funder simply has no rows, which is the honest encoding, but
absence there must be read as "not recorded", never "not funded".

**Funder names are deduplicated on the exact string.** 2,563 distinct names,
of which 129 differ from another only by capitalisation. Case-folding or
fuzzy-matching organisation names is a data-cleaning decision that needs its
own evidence and review, so it is deliberately not done silently in the DDL —
same posture as leaving `departamento` un-normalized.

**`areasTerapeuticas.area` is a list in 11,847/11,847 records** (type, not
sample, settles it); 363 studies carry more than one area, so the bridge is
load-bearing rather than defensive. Only **55 distinct `eutct` codes** exist
across the whole corpus, none blank, none with conflicting `nombre_es`/
`nombre_en`, and none repeated within a single study — so `eutct_code` is
safe as a natural primary key and `therapeutic_areas` needs no surrogate id.

**`departamento` belongs on the `study_centers` bridge, not on `centers`.**
Of 361 distinct centre `referencia`s across 2019–2020, **245 (68%)** appear
with different departments across different studies — it's an attribute of the
*pairing* (this trial at this hospital), not of the hospital. Its primary key
is widened to `(study_id, center_id, departamento)` because **4,398 of 11,700**
studies-with-centres repeat the same centre under a *different* department
(e.g. one trial running through both Endocrinología and Cardiología); a
two-column key would reject those as duplicates. Kept as plain text, not
normalized — raw values are inconsistent free text ("Oncología" / "ONCOLOGY" /
"Servicio de Oncología Médica"), so a lookup table wouldn't yet support
reliable grouping.
  - **Loader detail:** blank `departamento` must load as `''`, never `NULL`.
    SQL treats each `NULL` as distinct for uniqueness purposes, so two
    blank-department rows for the same study+centre would both survive,
    silently defeating the composite key exactly where the department is
    unknown.

**`centros` field names, confirmed live** (the manual's §4.7 matches): `tipo`,
`referencia` (**not** `codigo` — an earlier draft invented that name),
`situacion`, `nombre`, `domicilio`, `localidad`, `codPostal`, `provincia`,
`ccaa`, `departamento`, `investigador`. Raw field names are kept verbatim in
the schema so columns stay directly cross-checkable against an API response.

**`investigador` is excluded** — confirmed live to be real principal-
investigator names ("Ebymar Arismendi Núñez"), so it falls under the same
named-individual rule already applied to `mail`/`telefono`/`personaContacto`
above: fine in the gitignored local cache, must not reach the DB or dashboard.

**`mujerusa`/`mujernousa` meanings are inferred, not documented.** The AEMPS
manual lists both fields but defines neither. Cross-referencing
`informacion.criteriosInclusion`/`criteriosExclusion` on matching studies:
`mujerusa` correlates with "women of childbearing potential must use an
acceptable contraceptive method", `mujernousa` with "postmenopausal or
surgically sterile" (i.e. *not* of childbearing potential, so contraception is
moot) — a standard WOCBP eligibility split. Flagged as inferred in the ERD
rather than asserted; do not present it as documented.

**`areasTerapeuticas.area[]` is a list** — a study can carry several coded
areas, so it needs `therapeutic_areas` + a `study_therapeutic_areas` bridge.
The first record sampled happened to have one element; the field's *type*, not
a sample, is what settles cardinality.

**Derived at load time, not in notebooks:** `censored`, `survival_start`
(= `fechaAutorizacionAEMPS`) and `survival_end` (= `fechaFinRealEspana`, or
the extraction date when censored), so Phase 4 doesn't re-derive censoring
logic per analysis.

### 3.2d Corrections found while writing the DDL (Phase 2.2)

Writing DDL against the full corpus, rather than the 2019–2020 samples §3.2c
was designed on, surfaced three errors in the reviewed ERD. Recorded here
because "the design was reviewed as a diagram and *still* had these" is the
argument for building the schema in slices with tests.

**The `study_centers` three-column key was too narrow — it would have rejected
1,265 rows.** §3.2c justified `(study_id, center_id, departamento)` on the
finding that 245 of 361 centres showed more than one `(departamento,
investigador)` pair. But `investigador` is excluded as named-individual data,
so the field doing the distinguishing is the one not stored. Measured on all
11,847 studies: 1,265 rows collapse to an exact duplicate under that key.

**Geography is an attribute of the pairing, not of the centre.** Same
reasoning as `departamento`, missed for `provincia`/`ccaa`/`codPostal`. 56 of
1,597 referencias report more than one CCAA — mostly stray blanks, but
`ORG-100007650` (Clínica Universidad de Navarra) reports **1,400 rows in
Navarra and 545 in Madrid**, a real second campus under one registry
reference. Resolving each centre to a single region would have silently
reassigned those 545 trials out of Madrid — the one region this project is
most about. So the three columns moved onto `study_centers`, making the key
six columns: `(study_id, center_id, departamento, provincia, ccaa,
cod_postal)`. 495 rows still duplicate under it, differing only in
`domicilio`/`localidad`/`investigador`/`situacion` — none stored — so the
loader collapses them losslessly.

**`centros.tipo` is not CAP/CHN.** §3.2c took the AEMPS manual §4.7 at its
word. Live values across all 85,410 centre entries are `'0'` (80,516), `'1'`
(4,055), `'2'` (409) and `''` (430). Meaning undecoded; the column is stored
unconstrained and must not be presented as site type until decoded. Another
manual-vs-live discrepancy, like the date-format one in §3.1.

**Centre identity is conditional, so it needs two partial unique indexes.**
Dedup is on `referencia`, not name: 179 of 1,597 referencias appear under
several spellings of one hospital (`HOSPITAL UNIVERSITARI VALL D'HEBRON` /
`Hospital Universitari Vall D Hebron` / `Hospital Universitari Vall
d'Hebron`), so deduplicating by name would split single hospitals into
several. But 2,695 of 85,410 entries have no `referencia` at all, so it cannot
be the primary key. Hence `UNIQUE(referencia) WHERE referencia IS NOT NULL`
plus `UNIQUE(nombre) WHERE referencia IS NULL`. Also worth noting for the
geography question: `nombre` is free text with inconsistent casing and
accents, so any hospital-level grouping must go through `center_id`.

### 3.3 Analysis questions / insights to extract

**These are a minimum, not a ceiling.** The list below is the starting set of
questions, not the full scope of what the data can answer — so the Phase 2
schema deliberately keeps every *structured* field REEC returns (population by
sex/age/vulnerability, all 24 purpose/objective/data-source flags, ATC codes,
administration routes), including fields no question below currently uses.
Schema design stays ahead of the question list so a new question later doesn't
require re-ingesting or redesigning. Only free text (`informacion`) and
named-individual fields are dropped, and for the specific reasons given in
§3.2b–c.

- **Volume & momentum:** trials authorized per year; look for a visible break
  around January 2023 (mandatory EU CTIS transition).
- **Therapeutic landscape:** which conditions dominate, and how the mix shifts
  over time.
- **Phase distribution:** Phase I–IV balance, overall and by sponsor type.
- **Sponsor structure:** industry vs. academic/public share; top sponsors.
- **Geography:** which CCAA / hospitals host the most trial activity (choropleth
  map; Madrid-specific angle for the target audience).
- **Trial duration (survival analysis):** time-to-completion via Kaplan-Meier,
  stratified by phase / sponsor type / therapeutic area / pre- vs. post-CTIS,
  compared with the log-rank test; multivariate Cox proportional hazards model
  with hazard ratios; proportional-hazards assumption check
  (`check_assumptions`); optional secondary endpoint: authorization → actual
  start (site-activation speed).
- **Results-reporting compliance:** share of completed trials with posted
  results, pre- vs. post-CTIS — likely headline finding, since REEC's "con
  resultados" filter showed results concentrated almost entirely in CTIS-era
  trials during earlier exploration.

### 3.4 Tools

- **Ingestion:** Python, `requests`
- **Storage:** SQLite via stdlib `sqlite3` with hand-written SQL — no ORM, so
  every query is one that can be walked through in an interview. DDL lives in
  `db/schema.sql` (version-controlled; the `.db` file is a disposable build
  artifact). Normalized schema of 15 tables — see §3.2c and the ERD. Real SQL
  queries, not pandas-only, to demonstrate the skill explicitly requested in
  job postings.
- **Survival analysis:** `lifelines` (`KaplanMeierFitter`, `CoxPHFitter`,
  `logrank_test` / `multivariate_logrank_test`)
- **Visualization:** Plotly (interactive charts + Spain choropleth map),
  Matplotlib/Seaborn (static exploratory work)
- **Dashboard:** Streamlit, deployed on Streamlit Community Cloud (free, gives a
  live link)
- **Version control:** Git/GitHub, real incremental commit history (not one dump
  commit — this is explicitly flagged as a portfolio red flag). Live at
  https://github.com/egilq137/spain-trials-landscape (public, created and pushed
  during Phase 1).
- **Testing:** every new function gets unit tests with mocked I/O (no live network
  calls in the automated suite) — success criteria stated up front, ordinary +
  edge cases covered, not just the happy path. Adopted from Phase 1 onward
  (`tests/`, stdlib `unittest.mock`, no `pytest` dependency added since stdlib
  sufficed).

### 3.5 Pipeline architecture

1. **Ingestion** (built — `ingestion/`) — two distinct fetch functions, matching
   two distinct real needs rather than one function reused two ways:
   - `fetch_year()` (`estudios` endpoint, bounded ~1yr range) — the one-time
     historical backfill, looped year-by-year via `run_backfill()` in
     `ingestion/backfill.py`, which skips years already cached.
   - `fetch_since()` (`getestudios` endpoint, unbounded "since date") — reserved
     for incremental refreshes after the backfill (not wired up yet; no
     scheduled/periodic run exists yet, just the function).
   `ingestion/cache.py` handles JSON persistence to `data/raw/{year}.json`
   (`raw_dir` passed as an argument, not a module-level global, so each piece
   stays independently testable). The backfill is runnable directly —
   `python -m ingestion.backfill [--start-year N] [--end-year N]` — not just
   importable, so it can be re-run manually without relying on ad-hoc commands.
2. **Transformation** — parse raw JSON into the relational schema; standardize
   date parsing (handling the two different formats); flag/derive censoring
   status per study. Not started (Phase 2).
3. **Analysis & dashboard** — the exploratory notebooks feed the Streamlit app.
   Not started.

### 3.6 Finish line — definition of done

- Public GitHub repo, modular layout (`ingestion/`, `db/`, `analysis/`, `app/`,
  plus `docs/` for design documentation and the AEMPS manual — kept out of the
  Python packages so code directories stay code-only),
  bilingual (EN/ES) README covering the question, data source, method, and
  explicit limitations (registry-level metadata, not patient data; CTIS-transition
  discontinuity; results-reporting skew; PI names and sponsor contact details
  deliberately excluded despite being public by mandate).
- Rebuildable SQLite database with cleaned REEC data.
- Live, deployed Streamlit dashboard: KPI summary cards, filters (year /
  therapeutic area / phase / region), the Spain map, the volume time series, the
  duration/survival analysis, the results-compliance chart.
- A "key findings" section: 3–5 concrete, numbers-backed statements — the part
  to actually walk an interviewer through.

---

## 4. Build plan — phased, incremental, each step independently verifiable

Working in small steps on purpose: every phase ends with something concrete to
look at (a chart, a query result, a running app) before moving to the next.

### Phase 0 — Scaffolding (no logic yet) — done
- [x] Create folder structure (`ingestion/`, `db/`, `analysis/`, `app/`),
      `run_pipeline.py` stub, `requirements.txt`
- [x] `git init` + first commit
- Verify: `git log` shows one clean init commit; folders exist.

### Phase 1 — Ingestion

**1.1 — Minimal fetch, verify shape**
- [x] Minimal fetch against `getestudios/{fecha}` for a short window (e.g. last
      30 days) — small payload, fast to iterate on
- Verify: inspect raw JSON for 1–2 studies, confirm fields match §3.2 — done,
  fields match exactly. Noted for Phase 2 schema: `centros`/`intervenciones`
  nest one level deeper (`.centro[]` / `.intervencion[]`), and flags like
  `enfermedadRara`/`huerfano` are string `"0"`/`"1"`, not booleans. Also found:
  registry data starts at 2017 (0 records 2011–2016; 2017 has an unusually
  large 3,304-record count, likely a one-time backlog from RD 1090/2015 making
  REEC mandatory, not organic trial volume).
**1.2 — Full historical backfill (list endpoint)**
- [x] Extend to full year-by-year loop (respecting ~1-year range cap), caching
      raw JSON locally
- Verify: cached files on disk, one per year, spot-check record counts — done.
  `ingestion/fetch.py` (fetch_year, estudios endpoint), `ingestion/cache.py`
  (save/load/is_cached, raw_dir passed as an arg — no module-level globals),
  `ingestion/backfill.py` (run_backfill loop, skips already-cached years).
  Live run: 10 files in `data/raw/` (2017-2026, ~66MB total), record counts
  match the earlier manual probe exactly. Re-run confirmed instant/no-op when
  everything's already cached. 27 unit tests across fetch/cache/backfill, all
  mocked (no live network in the test suite). Runnable directly:
  `python -m ingestion.backfill [--start-year N] [--end-year N]`.

**1.3 — Detail-endpoint enrichment (see §3.1, §3.2b)**
- [x] `ingestion/detail.py` — fetches `detalle/{identificador}` for every study
      collected in 1.2, giving phase, purpose flags, population totals and coded
      therapeutic area. Schema in §3.2b.
- [x] Caching + politeness, given the N+1 scale (11,847 studies, ~1 call each,
      vs. ~10 calls for the whole list loop):
      - append-per-record to `data/raw/detalle/{year}.jsonl`, so an interrupted
        run loses at most the study in flight
      - **resume by study id**, not by year: a re-run diffs the list cache
        against what's on disk, so the same zero-argument command does the next
        chunk of work each time (state lives on disk, not in the command)
      - failures to a `{year}.failures.jsonl` sidecar, splitting expected data
        issues (study not in registry) from real failures (error page, network)
        via distinct exception types per CLAUDE.md §5
      - fixed 1s delay, sequential, single connection; abort after 5 consecutive
        unexpected failures rather than hammering a service that's unhappy
      - each run stops at the year boundary or the time budget (default 60 min),
        whichever comes first, so a partial run always leaves a year either
        complete or cleanly partial — never silently half-analysed
- [x] Runnable directly: `python -m ingestion.detail`
      `[--max-minutes N] [--year N] [--limit N] [--continue-past-year] [--status]`
- [x] Verify: 68 unit tests (all mocked, no live network in the suite); happy
      path, resume-without-duplicates, and the not-found sentinel additionally
      confirmed against the live endpoint. `--status` reports per-year coverage
      (listed / fetched / failed / pending) so partial ingestion can't be
      mistaken for complete data in Phase 2.
- [x] `--retry-failures` — added once real failures existed to design against,
      rather than guessing. Skips confirmed absences (`reason == "not in
      registry"`, which repeats identically on every attempt) and re-attempts
      the rest; a resolved failure moves to the data file and drops off the
      sidecar, a repeat failure refreshes its sidecar entry instead of
      duplicating it. Same consecutive-failure abort as the main loop.
      All failures seen so far have been transient network drops
      (`RemoteDisconnected`, SSL `EOF`), clustered within seconds of each
      other — confirmed by hand that a manually-retried id returns fine — not
      genuine absences, and every one resolved on its first retry.
- [x] `poblacion.total` fill rate checked on the mature 2019 cohort (629
      studies): **100% present, 81.6% non-zero** — confirms the right-censoring
      read from §3.2b (brand-new 2026 trials were mostly `total: 0` since
      enrollment hasn't been reported yet). Safe to use for population-size
      analysis once Phase 2 excludes trials still in progress.
- [x] Run to completion — **all 10 years complete: 11,847/11,847 studies
      fetched, 0 pending, 0 unresolved failures anywhere.** `data/raw/detalle/`
      is 208MB. A few years' `.failures.jsonl` sidecars are now empty (0 bytes)
      rather than absent — they hit transient failures that `--retry-failures`
      later resolved. Kept on disk deliberately: an empty sidecar records that
      the year had failures and recovered, which a missing file wouldn't.
- [ ] Still open: spot-check a handful of fetched records against the REEC
      website for the same study ID (§3.6's verify step) — not yet done.

Phase 1 (ingestion) is now fully done: list-level data (1.1–1.2) and
detail-level enrichment (1.3) are both complete for all 11,847 studies, 2017
through 2026. Phase 2 (transformation + SQLite schema) is next.

### Phase 2 — Transformation + SQLite schema

**2.1 — Schema design (ERD)**
- [x] Design normalized schema — reviewed as a diagram before writing the
      loader. **15 tables, 6 many-to-many bridges**; full design and the
      evidence behind each decision in §3.2c, diagram in
      `docs/phase2-schema-erd.html`. Five errors were caught during review
      that would otherwise have reached the loader: an invented `centros`
      field name, `departamento` on the wrong table, a too-narrow composite
      key, four un-normalized pipe-delimited fields, and a wrong sponsor
      field name.

**2.2 — DDL**
- Built in slices rather than all 15 tables at once, so the conventions are
  validated against real constraint behaviour before being repeated 13 more
  times.
- [x] Slice 1 — `sponsors` + `studies` (59 columns, the hub). `STRICT` tables
      so declared types are enforced instead of SQLite's default dynamic
      typing; dates as ISO-8601 `TEXT` with a `GLOB` check (the source ships
      `DD-MM-YYYY`, so an unconverted value would otherwise load silently and
      break every date comparison); booleans as `INTEGER` + `CHECK (x IN
      (0,1))`. `NOT NULL` set from full-corpus counts, not the 2019 sample:
      0/11,847 blank `promotor` and 0/11,847 non-numeric `poblacion.total`
      justify `NOT NULL` on `sponsor_id` and `poblacion_total`, both of which
      the ERD had annotated more conservatively. Verified by executing the DDL
      against `:memory:` and asserting each constraint rejects its bad value.
- [x] Tests — `tests/test_schema.py`, asserting each constraint rejects its
      bad value rather than merely that the script runs. Written before
      slice 2 so the conventions were pinned before being repeated. It
      immediately caught a wrong belief: `PRAGMA foreign_keys` in
      `schema.sql` *does* apply to the connection running the script (it is
      only later connections that revert to off), so the loader and app must
      set it per-connect but the build script itself is already covered.
- [x] Slice 2 — `funders` + `study_funders`, `therapeutic_areas` +
      `study_therapeutic_areas`. Introduces the many-to-many bridge on its
      two simplest instances: composite PK on the pairing, `ON DELETE
      CASCADE` (a pairing belongs to its parents, unlike `studies.sponsor_id`
      which is a reference to one and so uses `RESTRICT`), and a second index
      on the non-leading key column, since a composite PK's index cannot
      serve a lookup by its second column alone. `therapeutic_areas` uses the
      natural key `eutct_code`; evidence in §3.2c.
- [x] Slice 3 — `centers` + `study_centers`. **The ERD's three-column key was
      wrong and this slice corrected it** — see §3.2d. Also introduced partial
      unique indexes for `centers`' conditional identity (referencia when
      present, otherwise nombre), which a plain `UNIQUE` cannot express
      because SQL treats every `NULL` as distinct.
- [ ] Slice 4 — `interventions` (one-to-many from studies) plus `substances`,
      `atc_codes`, `administration_routes` and their 3 bridges — slice 2's
      pattern repeated one level down.

**2.3 — Loader**
- [ ] `db/loader.py` — raw JSON/JSONL → rows → `INSERT`s. Takes the DB
      connection and `raw_dir` as arguments (same explicit-dependency pattern
      as `ingestion/cache.py`, so it stays testable against
      `sqlite3.connect(":memory:")`). Handles: the two date formats,
      `"0"`/`"1"` strings → booleans, the `.centro[]`/`.intervencion[]`
      nesting, pipe-splitting the four multi-valued fields, blank
      `departamento` → `''` not `NULL`, and deriving `censored` /
      `survival_start` / `survival_end`
- [ ] Wire into `run_pipeline.py` as the composition root, so the whole DB
      rebuilds from `data/raw/` in one command

**2.4 — Tests + verify**
- [ ] Unit tests following the existing `tests/` pattern (stdlib
      `unittest.mock`, small fixtures, no live network/DB): date parsing both
      formats, flag conversion, censoring derivation, pipe-splitting
- Verify: SQL queries against the DB (e.g. count grouped by year) match counts
  seen in cached JSON — 11,847 studies total

### Phase 3 — First analysis + visualization checkpoint
- [ ] Volume per year / CTIS-transition break (single query + one Plotly chart)
- Verify: chart sanity-checks against known facts (Jan 2023 dip/jump)

### Phase 4 — Remaining analyses (Section 3.3), one at a time
- [ ] Therapeutic landscape
- [ ] Phase distribution
- [ ] Sponsor structure
- [ ] Geography (choropleth)
- [ ] Survival analysis (Kaplan-Meier → log-rank → Cox PH → assumption check) —
      last, since it depends on the DB being fully trustworthy
- [ ] Results-reporting compliance
- Verify: each gets its own small notebook + a visual checkpoint before the next

### Phase 5 — Dashboard
- [ ] Build Streamlit incrementally: KPI cards → filters → one chart type at a
      time, reusing what's validated in notebooks
- Verify: run locally in browser after each page/section is added

### Phase 6 — Deploy + README
- [ ] Deploy to Streamlit Community Cloud
- [ ] Write bilingual (EN/ES) README with key findings (written last, once
      findings are known)
