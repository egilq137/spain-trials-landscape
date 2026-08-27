---
title: Madrid Data Scientist Portfolio — Project Spec
status: planning complete, ready to build
last updated: 2026-08-27
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
   detail lookup by EudraCT code or CodigoGESTO (documented, not yet tested;
   probably unnecessary since endpoints 1–2 already return full records including
   the `calendario` date block).

4. `https://reec.aemps.es/reec-services/json/hospitales[/{codigo}]` and
   `.../centros[/{codigo}]` — hospital / primary care center directories
   (documented, not yet tested; useful for the geographic analysis).

**Official reference:** AEMPS publishes a manual for this API — "Manual de Interacción
REEC: Servicio de Extracción de Datos" (v1, 12/12/2020):
https://sede.aemps.gob.es/docs/Manual-Interaccion-REEC-Servicio-Extraccion-Datos-v1.pdf
(local copy: `Manual-Interaccion-REEC-Servicio-Extraccion-Datos-v1.pdf`). Cross-checked
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
fetching it, not just the list-level data. Implications, to be handled as their own
build-plan step (Section 4) once list ingestion is proven out — not designed yet:
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

### 3.3 Analysis questions / insights to extract

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
- **Storage:** SQLite (or DuckDB) — normalized schema: studies, sponsors,
  interventions, centers, study–centers bridge table. Real SQL queries, not
  pandas-only, to demonstrate the skill explicitly requested in job postings.
- **Survival analysis:** `lifelines` (`KaplanMeierFitter`, `CoxPHFitter`,
  `logrank_test` / `multivariate_logrank_test`)
- **Visualization:** Plotly (interactive charts + Spain choropleth map),
  Matplotlib/Seaborn (static exploratory work)
- **Dashboard:** Streamlit, deployed on Streamlit Community Cloud (free, gives a
  live link)
- **Version control:** Git/GitHub, real incremental commit history (not one dump
  commit — this is explicitly flagged as a portfolio red flag)

### 3.5 Pipeline architecture

1. **Ingestion** — loop year-by-year (respecting the ~1-year range cap), calling
   `getestudios`/`estudios` endpoints, caching raw JSON locally to avoid
   re-hitting the API on every run.
2. **Transformation** — parse raw JSON into the relational schema; standardize
   date parsing (handling the two different formats); flag/derive censoring
   status per study.
3. **Analysis & dashboard** — the exploratory notebooks feed the Streamlit app.

### 3.6 Finish line — definition of done

- Public GitHub repo, modular layout (`ingestion/`, `db/`, `analysis/`, `app/`),
  bilingual (EN/ES) README covering the question, data source, method, and
  explicit limitations (registry-level metadata, not patient data; CTIS-transition
  discontinuity; results-reporting skew).
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
- [x] Minimal fetch against `getestudios/{fecha}` for a short window (e.g. last
      30 days) — small payload, fast to iterate on
- Verify: inspect raw JSON for 1–2 studies, confirm fields match §3.2 — done,
  fields match exactly. Noted for Phase 2 schema: `centros`/`intervenciones`
  nest one level deeper (`.centro[]` / `.intervencion[]`), and flags like
  `enfermedadRara`/`huerfano` are string `"0"`/`"1"`, not booleans. Also found:
  registry data starts at 2017 (0 records 2011–2016; 2017 has an unusually
  large 3,304-record count, likely a one-time backlog from RD 1090/2015 making
  REEC mandatory, not organic trial volume).
- [x] Extend to full year-by-year loop (respecting ~1-year range cap), caching
      raw JSON locally
- Verify: cached files on disk, one per year, spot-check record counts — done.
  `ingestion/fetch.py` (fetch_year, estudios endpoint), `ingestion/cache.py`
  (save/load/is_cached, raw_dir passed as an arg — no module-level globals),
  `ingestion/backfill.py` (run_backfill loop, skips already-cached years).
  Live run: 10 files in `data/raw/` (2017-2026, ~66MB total), record counts
  match the earlier manual probe exactly. Re-run confirmed instant/no-op when
  everything's already cached. 27 unit tests across fetch/cache/backfill, all
  mocked (no live network in the test suite).

### Phase 2 — Transformation + SQLite schema
- [ ] Design normalized schema (studies, sponsors, interventions, centers,
      study–centers bridge) — review as a diagram before writing the loader
- [ ] Write loader (raw JSON → tables): handle two date formats, derive
      censoring status per study
- Verify: SQL queries against the DB (e.g. count grouped by year) match counts
  seen in cached JSON

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
