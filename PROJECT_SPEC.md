---
title: Madrid Data Scientist Portfolio — Project Spec
status: Phase 1 (ingestion) complete — 11,847/11,847 studies. Phase 2.1 (ERD) done. A first DDL pass was written then reverted (kept on main, 0984446) in favour of profiling the source systematically first; 2.2 (profiling) is next
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
- Candidate survival window: `fechaAutorizacionAEMPS` → `fechaFinRealEspana`,
  but see §3.2c — the estimand is chosen in `analysis/`, not fixed here.
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

### 3.2c Profiling findings and the decisions they settle

Written from `db/profile.py` output over all 11,847 cached records, one table
at a time, before that table's DDL. Reports are kept in `docs/profiles/` so
each schema decision can be checked against the evidence behind it.

#### sponsors — source field `organismo.promotor`

**Structure and presence (settled, no judgement needed).** `organismo` is a
dict in 11,847/11,847 records — never a list, never absent. `promotor` is
present in 100%: never blank, null or absent, length 3–146. So `NOT NULL` is
justified by the data, and one sponsor per study is a property of the source
rather than a modelling shortcut. Real trials can have co-sponsors; REEC does
not record them.

**Deduplicating on the exact string is wrong — it splits real sponsors.**

| Identity rule | Distinct sponsors |
|---|---|
| exact string | 3,763 |
| + casefold / accents / whitespace / trailing punctuation | 3,345 |
| + HTML entity decoding | 3,336 |

**427 values across 315 groups are formatting variants of a sponsor already in
the list — 12.8%.** `AstraZeneca AB` (300) and `Astrazeneca AB` (45) are two
rows; Sanofi-Aventis Recherche & Développement splits nine ways. This directly
damages two §3.3 questions: "top sponsors" mis-ranks a split sponsor, and the
industry-vs-academic share inflates. Full list: `docs/profiles/sponsors-variants.txt`.

**HTML entity encoding is present in the source and is a new finding.**
`&amp;` in 519 records, `&#39;` in 35, mixed with raw `&` for the same company
— `Merck Sharp &amp; Dohme LLC` (150) and `Merck Sharp & Dohme LLC` (55) are
one sponsor split by markup alone. Case-folding cannot fix it; it needs
decoding. Worth re-checking on every other free-text field.

**Decision — normalise in the loader, enforce in the schema.** The rule, in
order: HTML unescape; Unicode NFD and drop combining marks; casefold; collapse
internal whitespace; strip surrounding whitespace and trailing `. , ; : -`.

  - **Why the loader and not somewhere else.** Not ingestion: the raw cache is
    the durable copy and must stay byte-faithful to what the registry sent.
    Not analysis: `studies.sponsor_id` is a foreign key, so identity has to be
    settled *before* ids are handed out — normalising later would mean merging
    rows and repointing every reference. The loader is the only place where
    identity is decided once, at the moment the id is assigned.
  - **Why this is safe to automate.** The rule only removes case, accents,
    spacing, punctuation and markup. For two genuinely different organisations
    to collide, their names would have to be identical letter for letter,
    which is not a realistic failure mode. Contrast the entity-resolution
    question below, which is not safe to automate.

**Decision — `sponsors` keeps two columns, not one.** `promotor_key` holds the
normalised form and carries the `UNIQUE` constraint; `promotor` holds the most
frequent raw spelling, for display. Storing only the normalised form would put
`astrazeneca ab` on the dashboard; storing only the raw form cannot enforce
identity. This is a change from the reverted DDL, which had a single
`promotor TEXT NOT NULL UNIQUE`.

**Explicitly out of scope — entity resolution.** `Novartis Farmacéutica, S.A.`
(260) and `Novartis Pharma AG` (188) are distinct legal entities in one
corporate group, as are the several Merck Sharp & Dohme entities. Grouping
them changes what "top sponsor" means and is a judgement that should be
visible and defensible, so it belongs in `analysis/` if it happens at all —
never silently in the database. Normalisation is mechanical and reversible;
entity resolution is neither.

#### studies.calendario — 11 date fields

Report: `docs/profiles/studies-calendario.txt`.

**Format is uniform.** All 11 fields match `dd-MM-yyyy` in 100% of populated
values across all 11,847 records — no malformed dates anywhere, and the key is
always present, so blank means empty string and never a missing key.

**Two fields are dead, now confirmed on the full corpus.**
`fechaClasificacion` and `fechaFinPrevista` are blank in 11,847/11,847. The
reverted DDL dropped them on the strength of two sampled cohorts; that call was
right, and is now evidenced rather than inferred.

**`fechaAutorizacionAEMPS` is 100% present** — safe as `NOT NULL`. It is *not*
the trial's start date; see the estimand decision below.

**The corpus is not a 2017-2026 corpus.** Authorization dates run from 2009 to
2026, and **3,079 studies (26%) were authorized before 2017**:

| 2009-2012 | 2013 | 2014 | 2015 | 2016 | 2017 |
|---|---|---|---|---|---|
| 9 total | 759 | 715 | 805 | 791 | 780 |

This is not a contradiction of §4's "registry data starts at 2017" — it
resolves it. `fechaRegistro` runs from **2017-11-02**, so REEC began recording
in November 2017; trials authorized earlier were entered retrospectively. That
also explains 2017's outsized 3,304-record file: a registration backlog, as
suspected.

  - **The bias this creates is the important part.** A trial authorized in 2013
    is in this data only if it was still live enough to be retro-registered in
    late 2017. Short trials that had already finished are absent. So pre-2017
    years are **not** a sample of trials authorized then — they are a sample of
    trials authorized then *and still running four or more years later*, which
    is selection on the outcome the survival analysis measures.
  - **Consequence:** volume-per-year and any duration estimate must either
    start at 2017, or state the pre-2017 years as incomplete and biased long.
    Silently including them would overstate median duration for those years.
    This is left truncation, and it is worth reading up on before Phase 4.

**Four studies end before they are authorized — impossible, and fatal to
survival analysis if kept.**

| study | authorized | ends |
|---|---|---|
| 2016-003980-21 | 2017-03-17 | 2003-05-02 |
| 2012-004854-27 | 2015-10-19 | 2015-10-15 |
| 2014-001255-23 | 2014-06-30 | 2014-06-20 |
| 2020-005614-18 | 2021-03-04 | 2020-06-24 |

These produce negative durations, which Kaplan-Meier cannot accept.
**Decision: the loader drops them** — four records out of 11,847, with no way
to tell which of the two dates is wrong.

**Decision — no survival columns in the database. The estimand is defined in
`analysis/`.** The reverted DDL derived `censored`, `survival_start` and
`survival_end` at load, with `survival_start = fechaAutorizacionAEMPS`. That is
wrong twice over. Authorization is a regulatory green light, not a start, so
the name asserted something the column did not contain. And there is no single
correct interval — there are at least three, measuring different things:

| interval | studies with it | ends before it starts | measures |
|---|---|---|---|
| authorization → end | 6,437 | 4 | green light to completion |
| actual start → end | 5,719 | 15 | how long the trial ran |
| authorization → actual start | 10,127 | 43 | site-activation speed (§3.3) |

The gap between the first two is not noise. **718 studies have an end date but
no start date, and 445 of those have an early-termination date** — trials
authorized and then cancelled before enrolling anyone. Authorization→end counts
them with a real duration; start→end excludes them entirely. Neither is more
correct; they answer different questions, and a cancelled-before-enrolment
trial is a **competing risk**, not another kind of completion.

Choosing one at load would hide a contested analytical decision in the layer
least able to explain it. The raw dates are all stored, so `analysis/` defines
the estimand where it can be stated, varied and defended. The database stores
facts; the analysis layer decides what is being measured.

  - **Consequence for the DDL:** no `survival_*` or `censored` columns, and no
    `CHECK (survival_end >= survival_start)` — there is no such pair to
    constrain. The impossible-date check moves to the loader, which drops the
    four rows above.
  - **`fechaInicioReal` is missing for ~10% of studies in every year from 2017
    to 2024**, rising to 45% in 2026 (genuinely not yet started) and 14–21% in
    2013–2016 (retro-registration gaps). So a start→end estimand silently
    conditions on having started, which is its own selection.

**Two smaller inconsistencies, recorded but not yet decided.** 43 studies have
an actual start before their authorization date; 11 have a `fechaReinicio` with
no `fechaInterrupcion` — a restart from an interruption that was never
recorded.

**More fields die at the CTIS transition.** `fechaInicioPrevista` falls from
~87% (2017-2021) to 32% in 2023 and 2% in 2025. `fechaFinRealEspana` falls from
88% to 1%, though that one confounds two causes -- recent trials genuinely have
not ended yet, and the field may also have stopped being populated. Those are
not separable from this data alone, which matters because that field is the
survival endpoint and therefore decides who is censored.

#### studies.poblacion — 18 flags + participant total

Report: `docs/profiles/studies-poblacion.txt`.

**All 19 fields are JSON integers, not strings.** Only `enfermedadRara` is a
string `"0"`/`"1"`; the 18 poblacion flags, all 24 proposito flags and
`poblacion.total` are integers. §4's note that "flags are string `"0"`/`"1"`"
holds for `enfermedadRara` and must not be generalised — the reverted DDL's
comment that the source ships flag strings was wrong for 42 of 43 flags.

**All 19 are present in 11,847/11,847** — never blank, null or absent. So
`NOT NULL` is justified across the group.

**12 of the 18 flags contain `-1`**, an undocumented third value. AEMPS defines
neither it nor several of the fields.

| flag | 0 | 1 | -1 |
|---|---|---|---|
| urgencia | 11,666 | 170 | **11** |
| mujerusa | 5,796 | 6,043 | **8** |
| embarazadas | 11,719 | 120 | **8** |
| lactancia | 11,804 | 36 | **7** |
| mujernousa | 9,842 | 1,999 | **6** |
| incapaces | 10,263 | 1,578 | **6** |
| preescolar, adolescentes | | | **2 each** |
| intrauteros, prematuros, reciennacido, ninos | | | **1 each** |

Six flags never carry it: `voluntariossanos`, `pacientes`, `pobvulnerable`,
`adultos`, `ancianos`, `menores`.

**`poblacion.total` carries two sentinels, not one.** 100% present, 1,307
distinct, median 123. But **2,201 values (18.6%) are 0**, which means "not
reported" rather than a trial planning nobody — and the maximum is **999999**,
a single obvious placeholder, with one further 99999. Excluding zeros and both
sentinels: n=9,644, min 1, median 180, max 99,999. No negatives.

**Decision — sentinels load as `NULL`, and here the mapping loses nothing.**
`-1` and `total = 0` both mean "unknown", which SQL already has a word for.
Stored raw they make every `AVG` and `SUM` silently wrong: `mujerusa` would
average in a `-1`, and mean planned participants would include 2,201 zeros.

The reason this is safe rather than merely convenient: **there are no existing
NULLs to collide with.** Every one of the 18 poblacion fields, all 24 proposito
fields and `total` is present in 11,847/11,847 records — never blank, never
null, never absent — and `-1` is the only non-0/1 value that occurs anywhere.
So a `NULL` in a flag column means "the source sent `-1`" and can mean nothing
else. The mapping is reversible by inspection, without consulting the raw
cache, so no information is lost by applying it.

  - **Flags:** `-1` → `NULL` in the 12 fields that carry it. Columns stay
    nullable; a `CHECK (x IN (0,1))` still applies, since a CHECK passes when
    it evaluates to NULL.
  - **`poblacion.total`:** `0` → `NULL` (2,201 records). Unambiguous for the
    same reason.
  - **`total` = 999999 / 99999 / 114011 are left raw.** One record each, so
    they are outliers rather than a sentinel convention, and a schema rule for
    a single row is not worth its cost. Recorded here as known outliers for
    analysis to exclude; 999999 and 99999 are almost certainly placeholders.
  - **`proposito` needs none of this.** All 24 flags are strictly 0/1 across
    the corpus, so they stay `NOT NULL` with `CHECK (x IN (0,1))`.
  - **This invariant is a property of the current corpus, not a guarantee.** A
    refresh that sends a genuinely absent field would make `NULL` ambiguous.
    The profiler counts blank/null/absent separately and the validator reports
    unexpected values, so either would surface it — re-check on refresh rather
    than assume it still holds.

#### studies.proposito — 24 flags

Report: `docs/profiles/studies-proposito.txt`. All 24 are integers, present in
11,847/11,847, and **strictly 0/1** — no `-1`, so unlike `poblacion` this group
needs no sentinel handling and stays `NOT NULL`.

**Seven of the eight data-source flags are constant 0 in every record**:
`atencionPrimaria`, `atencionPersonalizada`, `hospitalizacion`, `medico`,
`farmaceutico`, `historialClinico`, `basesDatos`. A column that never varies
carries no information. **Decision: drop all seven** — the same call as
`fechaClasificacion`/`fechaFinPrevista`, on the same evidence.

`otrasFuentes` is the sole survivor and is set in 1,801 studies. Kept, but its
meaning is unclear precisely because its siblings are dead: "other" relative to
seven categories nobody ever ticks. Do not present it as a data-source finding
without that caveat.

**The four phase flags stay four columns — an enum would mangle 12.1% of the
corpus.**

| phase flags set | studies | share |
|---|---|---|
| 1 | 10,408 | 87.9% |
| 2 | 1,436 | 12.1% |
| 3 | 3 | 0.03% |
| 0 | **0** | — |

Every study sets at least one, so a phase label is always derivable and a `0`
here means "not this phase" rather than "not recorded". Commonest combinations:
I+II (960), II+III (369), III+IV (88). A handful are non-adjacent — I+III (16),
II+IV (2) — which may be data errors; too few to act on, recorded so they are
not mistaken for a pattern later.

**A `0` does not mean the same thing in every block.** For phase it is
informative, because every study sets one. For purpose it is not: **6,125
studies (51.7%) set none of `diagnostico`/`profilaxis`/`tratamiento`**, which
reads as "purpose not recorded" rather than a trial with no purpose. The
objective block sits between the two — only 3.4% are all-zero, and most studies
set two to four of the nine. Any analysis counting "trials by purpose" must
state which of these it is treating as a denominator.

#### studies identity — identificador, acronimo, enfermedadRara

Report: `docs/profiles/studies-identity.txt`.

**`identificador` is a clean primary key.** Present in 11,847/11,847, and
**11,847 distinct** — no duplicate anywhere in the corpus, so `TEXT NOT NULL
PRIMARY KEY` is justified rather than assumed.

**The identifier format is an exact CTIS marker, and a better one than dates.**
Every id matches one of two patterns, with nothing unrecognised:

| format | example | count | share |
|---|---|---|---|
| EudraCT (14 chars) | `2019-000302-29` | 6,843 | 57.8% |
| CTIS (17 chars) | `2023-506669-70-00` | 5,004 | 42.2% |

This is worth a derived column. The pre/post-CTIS split is a headline question
(§3.3), and the id gives it exactly, where a date threshold only approximates
it — trials authorised before the transition were still registered afterwards.

**Correction to the `financiador` finding above.** §3.2c reports funder
coverage collapsing across 2022-2024. The real pattern is cleaner and is not
about calendar time at all: **funder is recorded for 6,843/6,843 EudraCT-era
studies and 0/5,004 CTIS-era ones.** Not a decline — a clean switch tied to
the registration system. The earlier by-year table was showing file windows
that blend the two regimes, which is exactly the artefact that makes per-year
fill rates misleading when a regime change is the real variable.

**`acronimo` is mostly absent or a placeholder, and dies entirely at CTIS.**
55.5% present, but **4,762 of those 6,574 values are placeholders** — `'NA'`
alone is 4,744, 72.2% of everything non-blank, plus `N/A`, `N.A.`, `No aplica`,
`No aplicable` and casing variants. **Real acronyms: 1,812 studies, 15.3% of
the corpus, 1,802 distinct.** By id year the real rate holds around 25% through
2021, falls to 5.7% in 2022 and is **0% from 2023 onward**.

  - **Decision: placeholders load as `NULL`, joining the 5,273 blanks.** Note
    this is *not* the reversible mapping used for the poblacion sentinels —
    blanks already become `NULL`, so afterwards `NULL` cannot distinguish
    "empty" from `'NA'`. It is justified on different grounds: both mean the
    trial has no acronym, so the distinction has no analytical use, and the
    raw cache retains it. The placeholder list is enumerated, not fuzzy-matched.
  - With 15.3% coverage and nothing after 2022, `acronimo` is display-only.
    It cannot support any analysis over time.

**`enfermedadRara` is the one string flag in the record.** `'0'`/`'1'` as text,
where all 42 poblacion and proposito flags are integers. Present in
11,847/11,847, strictly 0/1, no sentinel — so `NOT NULL` with `CHECK (x IN
(0,1))` after conversion. 2,444 studies (20.6%) are flagged rare-disease.

#### centers and the study_centers bridge

Report: `docs/profiles/centers.txt`. Counts here are per **centre entry**
(85,410) rather than per study, except where stated.

**Array shape confirmed.** `centros.centro` is a list in 11,847/11,847 records
— never a bare object. **147 studies list no centre at all**; the rest average
7.2, maximum 93.

**Identity is conditional, and must be.** `referencia` is present in 96.8% of
entries with **1,597 distinct values**, but **2,695 entries have none**, so it
cannot be the primary key. The 2,695 cover **1,460 distinct names**. Hence a
surrogate `center_id`, with `UNIQUE(referencia) WHERE referencia IS NOT NULL`
plus `UNIQUE(nombre) WHERE referencia IS NULL`.

**Deduplicate on `referencia`, never on `nombre`.** The name field's two most
frequent values are the same hospital: `HOSPITAL UNIVERSITARI VALL D'HEBRON`
(2,667) and `Hospital Universitari Vall D Hebron` (1,553). 3,305 distinct names
against 1,597 referencias.

**Geography belongs on the bridge, not on `centers`.** Only **28 of 1,597
referencias (1.8%)** ever report more than one CCAA, so resolving each centre
to a single region is *nearly* right — and the exception is the one that
matters. `ORG-100007650`, Clínica Universidad de Navarra, reports **1,400
entries in Navarra and 545 in Madrid**: a real second campus under one registry
reference. Resolving it would reassign 545 trials out of the region this
project is about. The remaining 27 conflicts are small (3, 1, 59 entries).
Cost of the choice: `ccaa`/`provincia`/`localidad`/`cod_postal` repeat across
85,410 bridge rows instead of 1,597 centre rows.

**`ccaa` and `provincia` are clean coded vocabularies**, which is unusual in
this source and good news for the choropleth. `ccaa` has exactly **19 distinct
values** — the 17 autonomous communities plus Ceuta and Melilla — at 99.5%
present. `provincia` has exactly **52** — the 50 provinces plus both autonomous
cities — at 97.3%. Madrid is 22,148 entries, second to Cataluña's 23,317.

**`codPostal` has lost leading zeros — 290 entries are 4 digits.** Spanish
postcodes are always 5, the first two being the province, so `'3010'` is
Alicante's `'03010'` with the zero stripped somewhere upstream. **Decision:
zero-pad 4-digit numeric values to 5 at load**, which is an enumerable
correction rather than a guess. 11 further entries are malformed in other ways
(`'08006.'`, 6-10 characters); left raw, too few and too varied for a rule.
This settles the column type independently of the earlier leading-zero
argument: `TEXT`, never `INTEGER`.

**`departamento` is free text and must stay that way.** 75% present, **8,268
distinct values** across 64,047 entries, mixing languages and casing —
`Oncology` (5,714), `Medical Oncology` (2,682), `Oncología` (2,657),
`Hematology` (2,336). No lookup table would group these reliably without a
mapping exercise that is its own project. Plain `TEXT` on the bridge.

**PROVISIONAL — drop `tipo`, `situacion` and `departamento` from the centre
tables.** Recorded as leaning, not settled.

  - **`tipo` and `situacion`: low cost.** Both are undocumented codes that the
    manual describes wrongly, so nothing currently readable is lost, and both
    remain in the gitignored raw cache if either is ever decoded. Neither
    appears in any §3.3 question.
  - **`departamento`: real cost, real simplification.** Dropping it loses the
    "which hospital service runs trials" angle entirely — 8,268 distinct values
    over 64,047 entries — and that angle is not recoverable without a mapping
    exercise, so losing it is arguably losing little that was usable. What it
    buys is a smaller, more honest grain: one row per trial-at-a-site rather
    than one per trial-at-a-service.
  - **But it re-opens the key, which `departamento` was propping up:**

| candidate key | rows |
|---|---|
| raw centre entries | 85,410 |
| study + centre + geography + departamento | 85,070 |
| study + centre + geography | 83,429 |
| study + centre | 81,111 |

  - The gap between the last two is the problem to settle: **2,071 (study,
    centre) pairs report more than one geography *within a single study*.** So
    `(study_id, center_id)` alone is not yet a key.
  - **TODO before the `study_centers` DDL — inspect those 2,071 pairs.** If
    they are mostly the multi-campus case (one trial genuinely running at both
    CUN Pamplona and CUN Madrid), the geography is real information and belongs
    in the key. If they are mostly inconsistent entry for one physical site,
    resolve per pair instead and take the clean one-row-per-site grain. The
    answer decides between:
    `PRIMARY KEY (study_id, center_id, provincia, ccaa, localidad, cod_postal)`
    — faithful, but counting a trial's sites needs `DISTINCT` — and
    `PRIMARY KEY (study_id, center_id)` with a documented resolution rule.

**`tipo` and `situacion` are strings, not integers**, unlike every flag in
`studies`. `tipo` is `'0'` (80,516), `'1'` (4,055), `'2'` (409), blank (430) —
**not** the `CAP`/`CHN` the AEMPS manual §4.7 documents. `situacion` is 100%
present and well spread: `'2'` (40,950), `'0'` (24,231), `'1'` (20,229). Both
are undocumented codes; stored raw, and neither may be presented as site type
or status until decoded.

#### therapeutic_areas — a coded vocabulary, and the cleanest field in the source

Report: `docs/profiles/therapeutic-areas.txt`.

`areasTerapeuticas.area` is a list in 11,847/11,847 records, **every study has
at least one** (max 8, mean 1.04), and all three fields are present in
12,289/12,289 elements with no blanks.

**`eutct` is a safe natural primary key.** 55 distinct codes, and **0 of the 55
carry more than one name pair** — `nombre_es` and `nombre_en` are functionally
dependent on the code, so they belong in the lookup table and never on the
bridge. No surrogate id is needed.

**The bridge is load-bearing, not defensive.** 12,289 elements over 11,847
studies, so 442 extra memberships across 363 studies. A column on `studies`
would lose them.

Names embed a category code — `Diseases [C] - Cancer [C04]`, 53 distinct
bracket codes. Not extracted: `eutct` already keys the table, so a second
identifier would be redundant.

#### funders — same identity problem as sponsors, plus a placeholder

Report: `docs/profiles/funders.txt`. `organismo.financiador` is pipe-delimited
and the delimiter is inconsistent — 5,280 values end with a trailing `|`, 1,563
do not. Splitting on `|` and discarding empties handles both.

**Co-funding is real but uncommon:** 271 studies list more than one funder, up
to 12. That is what makes this many-to-many rather than a column.

**The same normalisation rule as sponsors applies, and is needed:** 2,724
distinct names collapse to **2,404** — **320 merge**, 11.7%, the same
case/accent/spacing/entity variants. `funders` therefore gets the same
`nombre_key` + `nombre` pair as `sponsors`.

**`'NA'` is the single most frequent funder name — 572 occurrences.** The same
placeholder as `acronimo`, in a lookup table where it would appear as an
organisation that funded 572 trials. **Decision: placeholder values create no
funder and no bridge row**, using the enumerated list from the `acronimo`
decision. Absence of a bridge row already means "no funder recorded", so this
needs no new representation.

**Half the funder rows only repeat the sponsor.** In **3,702 of 6,843 studies
with a funder (54.1%)**, the sole funder is the sponsor under a different
spelling. Combined with the CTIS-era absence, `financiador` carries information
beyond `promotor` for roughly **26% of the corpus** — 3,141 of 11,847. Worth
stating before any "who funds Spanish trials" claim.

#### interventions — and three planned tables that do not survive it

Report: `docs/profiles/interventions.txt`. Counts are per **intervention
element** (30,946) unless stated.

**The block is genuinely optional, unlike `centros`.** `intervenciones` is
*absent* from 1,514 studies — not blank, missing — and 1,516 studies end up
with no intervention at all. The rest average 3.0, maximum 98.

**`atcs` is empty in all 30,946 elements. Drop `atc_codes` and its bridge.**
The ERD planned a lookup table and a many-to-many bridge for a field that has
never carried a single value in this corpus. Two of the fifteen tables go.

**`viasAdministracion` is never multi-valued, so its bridge is unjustified
too.** Present in 17,268 elements and **exactly one route in every one of
them** — 0 elements with two. The pipe delimiter implies a list the data never
uses. Downgrade to a lookup plus a plain foreign key, or a column; a
many-to-many models a relationship the source cannot express. A third bridge
goes.

**`sustancias` is genuinely multi-valued and keeps its bridge:** 12,389
elements with one substance, 512 with two, 182 with three, up to 7. That is
the one intervention bridge the data supports.

**`sustancias` and `viasAdministracion` never co-occur — the source swapped one
for the other.** Not one element has both:

| | count | share |
|---|---|---|
| substances only | 13,236 | 42.8% |
| routes only | 17,268 | 55.8% |
| neither | 442 | 1.4% |
| **both** | **0** | **0%** |

By year, `sustancias` runs 97–98% through 2021 then falls to 4% in 2023 and 0%
from 2024; `viasAdministracion` is 0% through 2021 and 96–100% from 2023. So
neither field covers the corpus, and any analysis using either is confined to
one side of the CTIS transition. They are not interchangeable — a substance is
not a route — so this is a genuine loss of comparability, not a rename.

**`nombreComercial` and `nombreCientifico` are the same string in 90.3% of
elements.** Keeping both stores 27,949 duplicated values to preserve 2,997
genuine differences. Worth deciding whether the scientific name earns its
column.

**`formaFarmaceutica` is 56.4% placeholder, and its two language columns are
swapped for exactly that value.** `'Not indicated'` (English) sits in the
Spanish column and `'No Indicado'` (Spanish) in the English one, 17,459 times.
Every real value is correctly placed — `Comprimido recubierto con película` /
`Film-coated tablet`. So the swap is specific to the placeholder, which means a
loader that maps placeholders to NULL removes the problem rather than needing
to correct it.

**`huerfano`** is a string `'0'`/`'1'` like `enfermedadRara`, 99.9% present, 25
blanks, 2,447 orphan-designated. **`codigo`** is 78.7% present and improves
sharply over time — 52% through 2021, 100% from 2024.

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
  artifact). Normalized schema of 15 tables — see the ERD. Real SQL
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
      diagram in
      `docs/phase2-schema-erd.html`. Five errors were caught during review
      that would otherwise have reached the loader: an invented `centros`
      field name, `departamento` on the wrong table, a too-narrow composite
      key, four un-normalized pipe-delimited fields, and a wrong sponsor
      field name.
- [ ] **`docs/phase2-schema-erd.html` is now stale and must be revised once
      profiling is done.** It is the 2.1 deliverable and still the global map
      the slices are cut against, so it is kept rather than deleted — but it
      currently asserts things profiling has already contradicted or has yet
      to confirm, and it is published as an artifact, so a reader has no way
      to tell which parts still hold.
  - Confirmed wrong already: `sponsors` is drawn with a single
    `promotor text` column. Per §3.2c it needs `promotor_key` carrying the
    UNIQUE plus `promotor` for display, because deduplicating on the exact
    string splits 427 values across 315 sponsors.
  - Every other claim in it is provisional until the corresponding table is
    profiled — including the ones it presents as evidence-backed, since that
    evidence came from the 2019–2020 sample rather than the full corpus.
  - Revise it **after** profiling completes, not per table: editing it
    piecemeal would leave it inconsistent with itself midway, and the
    published artifact would show a design nobody had reviewed as a whole.

**2.2 — Data profiling (moved ahead of the DDL)**
- Rationale for the reorder: a first pass at the DDL was written and reverted
  (kept on `main`, commit `0984446`). It surfaced real findings, but each one
  came from a targeted check of a field already under suspicion, so what got
  examined depended on what happened to be guessed. Profiling every field
  systematically is the version of that which does not depend on guessing.
- [x] `db/profile.py` — one report per source field: present/blank/absent
      counts, distinct-value count, and the value distribution. Low-cardinality
      fields list every value with counts; high-cardinality fields list the
      most frequent, where a single dominant value in an otherwise free-text
      field is the signature of a placeholder. Also reports how many values
      would merge under case/accent/spacing normalisation, which is what
      caught the sponsor-name splitting.
- Scope: only the fields a table actually keeps. Reports are committed to
  `docs/profiles/` — they summarise the 208MB cache, which is gitignored, so
  nobody could regenerate them from a clone.
- [x] `sponsors` — profiled, decisions recorded in §3.2c: normalise names in
      the loader, key on the normalised form, keep the most frequent raw
      spelling for display. Entity resolution stays out of the database.
- [x] Fill rates broken down **by year, not corpus-wide**. Averaging across
      2017–2026 blends two regimes either side of the January 2023 CTIS
      transition and can hide a field that stopped being populated entirely.
- [ ] `studies` — 51 source fields, the big one
- [x] `centers` — profiled. **TODO before its DDL:** inspect the 2,071
      (study, centre) pairs whose geography varies within one study, to decide
      the `study_centers` key (§3.2c).
- [x] `funders`, `therapeutic_areas`
- [x] `interventions` + substances / atc_codes / administration_routes
- **Profiling complete.** Revise `docs/phase2-schema-erd.html` next (2.1),
  then write the DDL from §3.2c.
- Each table's findings go into §3.2c before its DDL is written.

**2.3 — DDL (after profiling)**
- [ ] `db/schema.sql` — rebuilt from what the profile shows. The reverted
      version is available for comparison (`git show main:db/schema.sql`) but
      is not a starting point; its constraints encode assumptions the profile
      has not yet confirmed.
- [ ] `tests/test_schema.py` — each constraint asserted to reject its bad
      value, not merely that the script runs.

**2.4 — Validation before load**
- [ ] `db/validate.py` — pushes every cached record through the schema in an
      in-memory database and reports every constraint violation grouped with
      counts, rather than stopping at the first. Checked in on this branch
      (`b43a7a8`) against the reverted schema; needs rebasing onto the new one.
- Profiling and validation are complementary, not alternatives: profiling
  finds problems within a single field, validation finds problems that only
  exist across fields or across records — key collisions, broken uniqueness,
  foreign-key integrity.

**2.5 — Loader**
- [ ] `db/loader.py` — raw JSON/JSONL → rows → `INSERT`s. Takes the DB
      connection and `raw_dir` as arguments (same explicit-dependency pattern
      as `ingestion/cache.py`, so it stays testable against
      `sqlite3.connect(":memory:")`). Handles: the two date formats,
      `"0"`/`"1"` strings → booleans, the `.centro[]`/`.intervencion[]`
      nesting, pipe-splitting the four multi-valued fields, blank
      `departamento` → `''` not `NULL`, and dropping the four records whose
      end date precedes their authorization date. Derives no survival or
      censoring columns — see §3.2c
- [ ] Wire into `run_pipeline.py` as the composition root, so the whole DB
      rebuilds from `data/raw/` in one command

**2.6 — Tests + verify**
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
