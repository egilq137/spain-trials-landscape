---
title: Madrid Data Scientist Portfolio — Project Spec
status: Phase 1 (ingestion) complete — 11,847/11,847 studies. **Phase 2 complete**: profiling, the ERD revision (12 tables, 4 bridges), all six cleaning-rule steps, the DDL written in four slices, validation over the whole corpus (0 rejected, no violations), and db/loader.py + run_pipeline.py rebuilding data/trials.db from the cache in 9 seconds — 11,843 studies after the 4 impossible-date drops, every row count matching §3.2c. 408 tests. Next: Phase 3, the first analysis and chart (volume per year / the CTIS break)
last updated: 2026-09-02
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

**Decision — normalise in the loader, enforce in the schema.** Implemented as
two functions in `db/cleaning_rules.py`, because a name is used for two things and the
two rules are not the same one applied twice:

  - `clean_text` — the form that is **stored and shown**. Reverses damage and
    only damage: markup decoded, invisible characters dropped, spacing
    collapsed. Case, accents and punctuation are content and survive.
  - `match_key` — the form that decides **identity**. `clean_text`, then
    apostrophe styles unified, then Unicode NFD with combining marks dropped,
    casefolded, and edge punctuation stripped.

Over the corpus this takes 3,742 distinct cleaned sponsor spellings to 3,336
identities, 3,245 centre names to 2,580, and 2,717 funder names to 2,401.

**Three refinements the implementation forced, each found by measuring:**

  - **Escaping is sometimes doubled.** Ten centre names carry
    `D&amp;#39;oncologia`, which needs one pass to reach `D&#39;oncologia` and
    a second to reach `D'oncologia`. Decoding therefore repeats to a fixed
    point, capped at three passes so a bad row cannot hang the loader.
  - **Invisible characters split values.** A byte-order mark arrived glued to
    a postcode (`&#65279;09`). Unicode category `Cf` is dropped after decoding
    — it cannot be seen, so it can only ever create a spurious second row.
  - **Apostrophe style is not accent noise.** Catalan and Valencian names are
    full of elisions — `Vall d'Hebron`, `L'Hospitalet`, `Institut Català
    d'Oncologia` — written with three different characters. U+00B4 ACUTE
    ACCENT is a standalone character, not a combining mark, so NFD leaves it
    and case-folding cannot merge `d'hebron` with `d´hebron`. Unified in
    `match_key` only: which apostrophe the registry typed is not damage.
    Merges 5 further centre names and 3 localities.

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
frequent **cleaned** spelling, for display. Storing only the normalised form
would put `astrazeneca ab` on the dashboard; storing only the raw form cannot
enforce identity. This is a change from the reverted DDL, which had a single
`promotor TEXT NOT NULL UNIQUE`.

**Correction — display is the cleaned mode, not the raw mode.** An earlier
draft of this section said `promotor` holds "the most frequent raw spelling".
That is wrong, and the largest sponsor is the counterexample: the most frequent
raw spelling is `Merck Sharp &amp; Dohme LLC` (150), ahead of the correct
`Merck Sharp & Dohme LLC` (55). Taking the raw mode would ship markup to the
dashboard. Cleaned, the two merge into one sponsor with 205 trials, which also
moves it up the ranking — decoding is not cosmetic, it changes the answer.

**REVISION — identity ignores punctuation everywhere in the string, and cuts
a descriptive clause.** The rule above was written to fold "case, accents,
spacing and markup". It folded punctuation only at the *edges* of a value,
which left two large classes of split intact. Both were found by reading the
loaded `sponsors` table rather than by profiling, which is why they survived
to Phase 2.5.

  - **Internal punctuation.** `Novartis Farmacéutica, S.A.` and `Novartis
    Farmacéutica S.A.` were two sponsors over one comma; so were `Pfizer Inc.`
    / `Pfizer, Inc.` and `Gilead Sciences, Inc.` / `Gilead Sciences Inc.`
    Punctuation is replaced with a space rather than deleted, so
    `Merck & Co.,Inc` does not become `merck & coinc` — the comma was doing a
    separator's job.
  - **Descriptive clauses.** 98 sponsor and funder values are sentences, not
    names: `Roche Farma S.A (Soc.Unipersonal) que realiza el ensayo en España
    y que actúa como representante de F.Hoffmann-La Roche Ltd`. Two such
    values differ by whichever words the writer chose, so one sponsor splits
    into as many rows as there are phrasings. `organisation_key` cuts at the
    earliest of 15 enumerated markers (`que realiza`, `como representante`,
    `subsidiary of`, `en nombre de` …), counted in the corpus rather than
    imagined. Applied to sponsors and funders only — a hospital or a molecule
    is never described this way.

A third change belongs with them, and it subsumes an intermediate version of
itself. Removing the dots from `S.A.` leaves `s a`, where the same abbreviation
written without them leaves `sa` — so spacing had to go too. And once that was
being fixed, `Astra Zeneca` / `AstraZeneca` and `Pharma Mar` / `PharmaMar` are
the same problem: **the space is style as much as the comma is.** The identity
key therefore has no spaces at all. It stops being readable (`astrazenecaab`),
which is fine — it is compared, never shown, and the display column is what a
reader sees.

Checked the same way: 15 sponsor groups and 13 funder groups merge and every
one is a single organisation, including `Boehringer Ingelhei m España` (a
space inside a word) and `BTI Biotechnology Institute I mas D` for `IMASD` —
Spanish `I+D`, spelled out. 3 substances merge, all spacing inside a formula
(`CD34+CELLS` / `CD34+ CELLS`). The 11 centre identities it merges are hyphen
spacing, `S L` / `SL`, and `SUMMA 112` / `SUMMA112`.

The clause cut in `organisation_key` runs *before* spaces are removed, because
its markers are phrases and need word boundaries to match against.

| | before | after |
|---|---|---|
| sponsors | 3,336 | **2,968** |
| funders | 2,712 → 2,401 | **2,216** |
| centre names | 2,580 | **2,520** |
| substances | 3,364 | **3,305** |
| centre *sites* | 3,361 | **3,336** |

**Why this is still normalisation and not entity resolution.** Every merge was
checked, not assumed: for sponsors, funders and substances, all 211 punctuation
groups contain names that are identical once punctuation, spacing and accents
are removed — zero differ by a letter. For centres, all 19 newly merged
identities were read individually: `Dr.` vs `Dr`, an acronym in brackets,
`((iensa)` with a typo'd bracket, and `d'hebron` / `d/hebron` / `d¿hebron`,
where the third is a mojibake apostrophe.

**What was deliberately NOT done, and it is the obvious next step to reach
for.** Stripping the legal form (`S.A.`, `AG`, `Ltd`, `GmbH`) merges far more
— and merges *wrongly*. It puts `F. Hoffmann-La Roche AG` with
`F. Hoffmann-La Roche Ltd`, and `Novartis Pharma AG` with `Novartis Pharma
GmbH`, which are different companies. Tested and rejected on that evidence.
**The clause is commentary; the legal form is part of the name.**

**Where this stops, on the worked example.** `Roche Farma` went from 18 rows
to 7. The 7 that remain differ only in how the legal form is *spelled* —
`S.A.`, `S.A.U.`, `S.A. (Soc Unipersonal)`, `(Soc uni.)`, `(Soc Unip)`,
`S.A.(S.A.U.)`, and bare `Roche Farma`. Merging those needs the knowledge that
`S.A.U.` and `S.A. (Sociedad Unipersonal)` are the same designation, which is
legal-form vocabulary rather than typography. That is the line: everything
above is *how a string was typed*, and this is *what a designation means*.

**Still split, and staying that way until `analysis/` decides:** `Lilly S.A.`
(90) vs `Eli Lilly & Co.` (96), `AstraZeneca AB` (345) vs `AstraZeneca UK
Limited` (1), `Roche Farma S.A.` vs `F. Hoffmann-La Roche AG`. These are
corporate families, not spellings. Candidates can be generated by blocking on
shared tokens and ranking by trial count — the top ~40 groups cover most of
the ranking error and the long tail is single-trial sponsors that cannot move
an answer — but each merge changes what "top sponsor" *means*, so the map
belongs in `analysis/` with its counts visible.

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

**`poblacion.total`: one sentinel, and three large values that had to be
looked up rather than judged by size.** 100% present, 1,307 distinct, median
123. **2,201 values (18.6%) are 0**, meaning "not reported" rather than a trial
planning nobody. The three largest were each checked against the study record,
because "large" is not evidence:

| value | study | verdict |
|---|---|---|
| 999999 | 2025-524690-16-00 | **not a count** — a *phase I* study of BBO-11818 in KRAS-mutant solid tumours, 7 centres. Phase I enrols tens to low hundreds |
| 99999 | 2020-001366-11 | **ambiguous** — an international COVID platform trial (Ministerio de Sanidad, March 2020), RECOVERY/SOLIDARITY shape. Those really did enrol tens of thousands, so this may be an open-ended target rather than a cap |
| 114011 | 2023-506977-36-00 | **genuine** — a pragmatic randomised trial of high- vs standard-dose influenza vaccine in adults 65–79 across Galicia. Pragmatic vaccine-effectiveness trials enrol at population scale |

All three load raw, and only 999999 becomes a rule — the other two are the
record of a check, not data. Grouping them as "large values" would repeat the
error that made 114,011 look suspicious in the first place: they share nothing
but magnitude, and a rule keyed on magnitude is what got it wrong. Excluding
zeros and 999999: n=9,645, min 1, median 180. No negatives.

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
entries with 1,597 distinct values, but 2,695 entries have none, covering 1,460
distinct names. So a surrogate `center_id` is needed — but see the resolution
below: `referencia` alone is *not* sufficient identity, because it carries
placeholders and spans multiple physical sites.

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

**`codPostal` is missing a digit in 290 entries — but not necessarily the
leading zero.** Spanish postcodes are always 5 digits, the first two being the
province. 290 of 85,163 non-blank entries are 4 digits, so one digit is gone.

**Superseded decision, kept because the mistake is instructive.** The first
version of this rule zero-padded — `'3010'` → `'03010'` — and justified it with
"every padded value lands in provinces 01–09, exactly the ones whose postcodes
begin with a zero." **That is not evidence.** Zero-padding always produces a
`0X` prefix, whatever digit was really lost; deleting any digit of Madrid's
`28046` also yields a 4-digit value. The check confirmed the function, not the
hypothesis.

**Decision — triangulate the missing digit from the rest of the row.** A
*candidate* is any 5-digit code that becomes the observed value when one digit
is deleted (46 of them for a typical value). Candidates are then filtered
against what the corpus already knows, strongest evidence first:

| tier | evidence | rows |
|---|---|---|
| 1 | the **same centre** reports a candidate elsewhere in the corpus | 226 |
| 2 | the **same locality** reports a candidate | 47 |
| 3 | no candidate seen, but the zero-padded value's province is one the locality uses — confirms the province, not the code | 10 |
| — | no evidence, a tie, or a contradicted province: **left raw** | 7 |

Triangulation agrees with zero-padding on 282 of the 283 rows it resolves, so
the old rule was mostly right — but right by luck, and the one disagreement is
the proof: **`'1108'` in Cádiz is `'11008'`, not `'01108'`**, which is Álava.
Blind padding moved a clinic 700 km.

Two further properties, both tested: a recovered postcode is always exactly one
deletion from what the registry sent, so the rule can only ever restore a
dropped digit and never substitute a commoner code; and a 4-digit postcode
never votes on another, so one broken value cannot confirm the next.

**It also deleted a hand-maintained exception list.** The zero-padding version
needed `POSTCODE_NOT_A_LOST_ZERO`, enumerating `('1108','cadiz')` and
`('3016','murcia')` as special cases found by eye. Both now fall out of the
evidence — the first resolved to the right answer, the second left raw because
Murcia uses 30xxx and padding would have claimed Alicante. **A rule that
dissolves its own exception list is usually the right rule.**

11 further entries are malformed in other ways (`'08006.'`, `'3584 AE'`,
`'Madrid'`, 6–10 characters); left raw, too few and too varied. This settles
the column type independently of the leading-zero argument: `TEXT`, never
`INTEGER`.

**Architecture — this is the one rule that cannot be a pure function.** It has
to have read the whole corpus before it can resolve a single value, so the
evidence index is built by a separate pass and *passed in* rather than imported
from a module global (`build_postcode_evidence` → `resolve_postcode`). The
function stays pure given its arguments and is unit-tested on a handful of
hand-written rows. This is why postcode repair belongs with the other
corpus-wide resolutions in the loader (step 6), not with the pure rules —
the user's correction relocated it as well as fixing it.

The evidence key drops the postcode (that is the field being recovered) but
**keeps the locality**: without it, Clínica Universidad de Navarra's Pamplona
and Madrid campuses would vote on each other's postcodes, the same merge the
site-level centre key exists to prevent.


**NEW FINDING — `provincia` is a clean vocabulary containing wrong values.**
The two are different claims, and only the first was made earlier in this
section. Checked against the postcode prefix across all 85,152 centre rows
carrying a numeric postcode, 2,302 disagree with the modal province for their
prefix. 2,044 of those are blank, leaving **258 rows (0.3%) where `provincia`
names the wrong province** — 65 rows put `HOSPITAL GENERAL UNIVERSITARIO DE
ALICANTE` in Murcia, 22 put a Sant Joan d'Alacant hospital in Las Palmas, 15
put Almería's Hospital Virgen del Mar in Segovia, and 134 put Barcelona-prefix
postcodes in Gerona.

**Decision: no rule, but province-level aggregation uses the postcode prefix,
not `provincia`.** Repairing the column would mean deriving a province from a
postcode, which is a derivation and belongs in `analysis/` where the assumption
can be stated — the same line drawn for route grouping and sponsor entity
resolution. This is also a small correction to the sentence above calling
`ccaa`/`provincia` "clean coded vocabularies and good news for the choropleth":
the *vocabulary* is clean, the *assignment* is not, and the choropleth should
be built on the postcode.

**`departamento` is free text and must stay that way.** 75% present, **8,268
distinct values** across 64,047 entries, mixing languages and casing —
`Oncology` (5,714), `Medical Oncology` (2,682), `Oncología` (2,657),
`Hematology` (2,336). No lookup table would group these reliably without a
mapping exercise that is its own project. Plain `TEXT` on the bridge.

**RESOLVED — a centre is a physical site, not a registry reference.** This
replaces the earlier TODO about the `study_centers` key, and it turned out the
key was the wrong thing to fix.

**First, `referencia` is not clean.** `'NR'` appears in 119 entries covering
**103 distinct hospitals** — Barcelona Beta Brain Research Center, CITA
Alzheimer, CLINICA MON SALUT and a hundred others. Deduplicating on
`referencia` would merge them into one centre with one region. Placeholder
references must be treated as absent, falling through to the name. (It also
carries at least three coding schemes: `ORG-#########`, `ORL-#########` and
bare 6-digit codes.)

**Second, one reference can cover several physical sites.** Clínica
Universidad de Navarra reports Pamplona and Madrid under `ORG-100007650`;
Institut Català d'Oncologia reports Badalona, Hospitalet and Girona under
`ORG-100030394`. Both are real. That is why 1,616 (study, centre) pairs
disagreed about geography — not per-trial variation, but a centre grain too
coarse to describe where the trial actually ran.

Measuring identity schemes over the whole corpus:

| identity | distinct sites | (study, centre) pairs with >1 geography |
|---|---|---|
| referencia only | 2,849 | 1,616 |
| referencia + postcode | 3,114 | 488 |
| referencia + locality | 3,228 | 661 |
| **referencia + locality + postcode** | **3,361** | **11** |

**Decision: `centers` is keyed on (reference-or-name, `localidad`,
`cod_postal`)** — 3,361 sites, 512 more rows than the coarse version, and the
conflict all but disappears. (The loader builds **3,360**: this count grouped
the five nameless entries above as a site, and they now create none.) Consequences, all of them simplifications:

  - **Geography moves back onto `centers`**, where it is now stable by
    construction. It does not repeat across 85,410 bridge rows.
  - **`study_centers` becomes a plain two-column bridge**, `PRIMARY KEY
    (study_id, center_id)`. No six-column key, and no `DISTINCT` needed to
    count a trial's sites.
  - **The Madrid problem solves itself.** CUN Madrid and CUN Pamplona are two
    centres, so the 545 Madrid trials stay in Madrid without geography having
    to live on the pairing.
  - **149 sites still disagree on `provincia`/`ccaa`; resolve by most frequent
    non-blank value.** 132 differ only because one variant is blank. The other
    17 are single-occurrence typos — `ORG-100028551` is Salamanca 1,122 times
    and Madrid once — which lose to the majority by construction.

**SETTLED — `tipo`, `situacion` and `departamento` are dropped.** The leaning
below was confirmed when the DDL was written. `tipo` and `situacion` are
undocumented codes the manual describes wrongly and no §3.3 question uses;
`departamento`'s 8,268 values were never groupable without a mapping exercise
that is its own project. All three stay in the raw cache if they are ever
decoded. With `departamento` gone, `study_centers` carries nothing but the
pairing.

**NEW FINDING — 5 centre entries name no centre at all**, across 3 studies.
`nombre` is blank in 3 of 85,410 entries, and those same 3 have no usable
`referencia` either — in fact every field is blank except `situacion: '2'`,
and all three belong to one study, `2016-004019-11`. Building the loader found
**two more of a different shape**: `2015-004391-29` and `2012-004128-39` each
list a site whose name is `'.'` or `'-'` and which carries an investigator but
no hospital. Punctuation-only names fold away to nothing, so `match_key`
returns `None` and they have no identity either — the same outcome by a
different route, and the reason the rule is "identity is empty" rather than
"the fields are blank". They are empty rows, not under-described sites, so
there is nothing for identity to be built from.
**Decision: they create no centre and no bridge row**, the same shape as the
`'NA'` funder rule — absence of a bridge row already says the study reported no
site there. Enforced in the schema by `CHECK (center_key <> '')`, so an empty
entry is refused rather than collapsing into a single nameless centre that
every such study would then appear to share. Excluding them, `nombre` is
non-blank in every remaining entry, which is what justifies its `NOT NULL`.

**PROVISIONAL (superseded by the above) — drop `tipo`, `situacion` and
`departamento`.** Recorded as
leaning, not settled. `tipo` and `situacion` are cheap: undocumented codes the
manual describes wrongly, absent from every §3.3 question, still in the raw
cache if decoded later. `departamento` costs the "which hospital service runs
trials" angle, though 8,268 values mixing languages and casing were never
groupable without a mapping exercise. With the key resolved above,
`departamento` is no longer propping anything up — dropping it is now purely a
question of whether the field is worth keeping, not a structural change.

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

**Administration routes need grouping, and it belongs on the lookup table.**
129 distinct values, and normalisation by case/accent merges none of them —
they are genuinely different strings for a small number of real routes.

Two separable problems, which belong in different places:

  - **Spelling and phrasing → the loader.** `oral` (4,026) and `oral use`
    (3,219) are one route. So are `intravenous`, `intravenous use`,
    `intravenous infusion`, `iv infusion`. And there are real misspellings:
    **`intravenious infusion` (466) and `intravenus use` (51)** — 517 rows a
    naive match on "intravenous" would miss entirely. Mechanical, enumerable.
  - **Grouping into clinical categories → a `grupo` column on
    `administration_routes`, filled by the loader from an enumerated map.**
    Unlike sponsor entity resolution this is 129 hand-reviewable rows, the
    mapping lives in one place, and `nombre` is kept so any later question can
    regroup from the original.

**Settled — harmonise, but do not bucket.** `db/cleaning_rules.py` reduces the 129 raw
values to **53 canonical routes** via `ROUTE_CANONICAL`, plus a small
`ROUTE_NOT_A_ROUTE` set for the 299 rows (1.7%) that name no route at all —
`unknown use`, `other use`, `route of administration not applicable`.

**No coarse grouping is stored.** An earlier draft added an
oral/intravenous/subcutaneous/other bucket column; it is gone. Merging
`oral use` into `oral` is mechanical, but deciding that intramuscular counts
as "other" is a judgement about what a question is asking — the same line
already drawn for sponsor entity resolution. The canonical routes are the
grouping; anything coarser belongs in `analysis/`, where it can be stated and
varied per question rather than frozen in a column.

Two properties of the maps, both enforced by tests:

  - **No fallthrough.** Every one of the 129 values must appear in exactly one
    of the two maps. An unmapped value fails a test rather than being silently
    absorbed — which is how `-1` stayed invisible for so long.
  - **No dead entries.** A key matching nothing is a typo, or a rule for data
    that no longer exists. Either way it should not sit there unnoticed.

Four entries are marked INFERRED because the source does not literally say the
route: bare `infusion`, `solution for infusion` and `concentrate for solution
for infusion` are read as intravenous, and `intravascular`/`subdermal` as
their common equivalents. `solution for injection` and friends name a *form*,
not a route, so they become `injection, route unspecified` rather than being
guessed at.

**Correction to the finding above: a single route value can name two routes.**
16 distinct values across 256 rows do — `intravenous bolus injection/iv
infusion`, `oral and iv` (43), `intravenous (iv) or subcutaneous (sc)` (34).
So "never multi-valued" is true only of the pipe delimiter; the free text
sometimes carries two. Too few to justify restoring the bridge, but the
grouping map has to decide what each compound value becomes.

**`sustancias` is genuinely multi-valued and keeps its bridge:** 12,389
elements with one substance, 512 with two, 182 with three, up to 7. That is
the one intervention bridge the data supports.

**Correction, measured when the DDL was written: the tail is far longer than
"up to 7".** Splitting all 13,236 populated values gives **15,130 substance
mentions**, and the per-element counts run 8, 9, 10 … up to **45** — one
element lists 45 substances, two list 27, three list 23. The head of the
distribution above is right and the tail was cut off. It changes nothing
structurally (the bridge already handles any number) but it does mean a
"substances per intervention" statistic has a long right tail and should be
reported as a median, not a mean.

**`sustancias` needs the same name normalisation as every other name field,
and needs it more.** Profiled per substance rather than per pipe-joined
string: 15,130 mentions, of which **884 are placeholders** (`N/A`, `NA`, `Not
available` — the same enumerated list, and they create no substance and no
bridge row). The rest give **4,244 distinct cleaned spellings collapsing to
3,364 identities — 880 merge, 20.7%**, the highest rate of any name field in
this project (sponsors 10.8%, centres 20.5%, funders 11.7%). So `substances`
takes the same `nombre_key` + `nombre` pair, on measured evidence rather than
by analogy.

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
genuine differences. **Decision: drop `nombreCientifico`** — the duplication is
not worth a column, and the commercial name is the one an analysis would
display.

**REVISION — `sustancias` carries 520 placeholder mentions, not 884, and the
missed ones were the biggest.** The first pass matched the enumerated
`PLACEHOLDERS` list, which was built from `acronimo` and `financiador` and so
was Spanish-shaped. Reading the loaded `substances` table by frequency found
`Not Applicable` (115) and `Not yet assigned` (90) sitting in the **top eight
substances, above most real drugs**, plus 43 further spellings of the same
statement — `not assigned`, `not yet defined`, `not yet established`, `none
yet`, `to be determined`, `INN not yet proposed`, `TBC`.

**Why the registry writes them.** A trial can be authorised before its drug
has an INN — an International Nonproprietary Name, the generic name a
substance is finally known by — so the registry writes a sentence saying so
where the name will go. That is a real fact about early-phase trials, and it
belongs in the same bucket as `'NA'`: absence of a bridge row already says it.

**Enumerated, and the candidate sweep is the argument for enumerating.** The
word net used to *find* these also matched real drugs: `none` catches
finerenone, eplerenone and drospirenone; `nan` catches nanocolloid and every
recombinant protein; `available` catches `Best Available Treatment`, a real
comparator arm; and any short-string rule would delete PRGF, 5-FU, IL-2, BCG,
RUTI and V160. Patterns find candidates; only the list decides.

Each of the 45 additions was checked against **every** field
`is_placeholder` touches, not just the one that prompted it — `not applicable`
turns out to be an intervention name 10 times and a funder once, `No` a funder
11 times. `tbc` is the one to re-check on a refresh: it means "to be
confirmed" here, but TBC is also the Spanish abbreviation for tuberculosis.

Effect: substances 3,352 → **3,308**, intervention_substances 14,127 →
**13,651**, funders 2,232 → **2,230**, acronyms 4,763 → **4,765**.

**`formaFarmaceutica` is dropped, both language columns.** No §3.3 question
uses dosage form, and the field is in poor shape: **56.4% placeholder, with the
two language columns swapped for exactly that value.** `'Not indicated'` (English) sits in the
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
- [x] **`docs/phase2-schema-erd.html` revised after profiling** — 12 tables and
      4 bridges, down from 15 and 6. Republished to the same artifact URL.
      Profiling found a fifth ERD error the earlier review missed:
      `intervenciones[].tipo` was documented with meanings from manual §4.8,
      and the endpoint returns no such field on any of the 30,946 elements.
      The manual has now been wrong about a date format, a site-type
      vocabulary, and a field's existence.
- Superseded note (kept for the record): **the ERD was stale and had to be
      revised once profiling was done.** It is the 2.1 deliverable and still the global map
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
      the loader, key on the normalised form, keep the most frequent cleaned
      spelling for display. Entity resolution stays out of the database.
- [x] Fill rates broken down **by year, not corpus-wide**. Averaging across
      2017–2026 blends two regimes either side of the January 2023 CTIS
      transition and can hide a field that stopped being populated entirely.
- [ ] `studies` — 51 source fields, the big one
- [x] `centers` — profiled, and the key question resolved (§3.2c): a centre is
      a physical site, keyed on reference-or-name + locality + postcode, which
      turns `study_centers` into a plain two-column bridge.
- [x] `funders`, `therapeutic_areas`
- [x] `interventions` + substances / atc_codes / administration_routes
- **Profiling complete.** Revise `docs/phase2-schema-erd.html` next (2.1),
  then write the DDL from §3.2c.
- Each table's findings go into §3.2c before its DDL is written.

**2.2b — Cleaning rules as data (`db/cleaning_rules.py`)**
Six steps, so each rule lands with the count that justifies it and a corpus
test that fails when a refresh changes the data underneath.
- [x] 1. Placeholders and sentinels — `PLACEHOLDERS`, `FLAG_UNKNOWN`,
      `TOTAL_UNKNOWN`, `TOTAL_NOT_A_COUNT`, `IMPOSSIBLE_DATE_STUDIES`.
- [x] 2. Administration routes — 129 raw values to 53 canonical routes plus 5
      that name no route. No coarse grouping: the canonical routes are the
      grouping, and bucketing is a question-dependent choice for `analysis/`.
- [x] 3. Name normalisation — `clean_text` / `match_key`, and the sentinel
      appliers `clean_flag` / `clean_total` wired into `db/transform.py`,
      which is where every rule so far gets its first caller. Verified over
      the corpus: 54 flag NULLs, 2,202 total NULLs, 10,036 acronym NULLs,
      3,742 sponsor spellings to 3,336 identities.
- [x] 3b. Postcode repair by triangulation (§3.2c) — replaces the zero-padding
      rule, which was assuming the answer rather than deriving it. 283 of 290
      resolved from the corpus, 7 left raw. Strictly this is step 6 work:
      it is the only rule that must read the whole corpus first, so its
      evidence index is built by a pass in the loader and passed in.
- [x] 4. The cleaning-rules tally (`db/cleaning_rules_tally.py`) — counts every rule application
      by (field, rule), so a load reports what it changed rather than only
      that it succeeded. Over the corpus: 7,652 changes in 11,847 records —
      4,763 placeholder acronyms, 2,201 unreported totals, 585 sponsor names
      cleaned of markup or spacing, 54 `-1` flags across 12 columns, 1 total
      that was never a count.
      - **Counts come from each rule's output, never from re-testing its
        condition.** `is_placeholder` is not called twice. A tally that
        re-runs the test can drift away from the rule it claims to describe,
        which is the one failure mode a tally must not have; a corpus test
        asserts the counted flag totals are the same dict as
        `cleaning_rules.FLAGS_WITH_UNKNOWN`.
      - **It counts, it does not log.** Per-row provenance would be a table
        the size of the database, and `data/raw/` already holds every original
        value. Records seen is tracked separately from changes made, so the
        report has a denominator.
      - The two `poblacion_total` sentinels are counted apart: "the registry
        declined to report" and "this is not a count" both load as NULL but
        are different facts.
- [x] 5. The tally is wired into `db/validate.py` as a dry run. Every row
      builder gets the same `CleaningRulesTally`, so a validation run reports
      what a real load *would* change before anything is written. Over the
      corpus: **28,933 changes in 11,847 records**. The studies-only subtotal
      is unchanged at 7,652, which is the check that wiring the other tables
      in did not disturb what was already measured.
      - The route rule is labelled "mapped to canonical", not "harmonised".
        It fires on all 16,969 populated route values, and most differ from
        their canonical form only by case — calling that a merge would
        overstate what the map does. The real merges are a subset and are
        visible in `ROUTE_CANONICAL` itself.
      - Rules are tallied for every record the transform touches, including
        one whose row is then rejected. The tally answers "what did the
        cleaning rules do", which is a question about the transform, not
        about the insert.
- [x] 6. Corpus-wide resolutions — done in `db/centers.py`, which was the only
      table that needed them. `build_center_index` reads the corpus once
      (most frequent centre name, most frequent non-blank `provincia`/`ccaa`,
      and the postcode evidence), and `center_row` resolves each entry
      against the index it is passed. Same build/pass-in shape as postcode
      repair (3b), which was the template as expected: the resolver stays
      pure given its arguments and is unit-tested on hand-written entries.

**2.3 — DDL (after profiling)**
- [x] `db/schema.sql` — rebuilt from what the profile shows, in four slices:
      sponsors + studies, funders + therapeutic areas, centers, interventions.
      12 tables, 4 bridges, `STRICT` throughout. The reverted version was kept
      for comparison (`git show 0984446:db/schema.sql`) but not used as a
      starting point; its constraints encoded assumptions the profile has
      since contradicted — survival columns most of all.
- [x] `tests/test_schema.py` — each constraint asserted to reject its bad
      value, not merely that the script runs. 82 tests.

**2.4 — Validation before load**
- [x] `db/validate.py` — pushes every cached record through the schema in an
      in-memory database and reports every constraint violation grouped with
      counts, rather than stopping at the first. Rebased onto the new schema
      and extended to all 12 tables: **11,847 checked, 11,847 accepted, 0
      rejected, no violations.** It also reports rows built per table, because
      "no violations" over an empty table is an unexercised table rather than
      a clean one — which is how a 54th administration route was caught.
- Profiling and validation are complementary, not alternatives: profiling
  finds problems within a single field, validation finds problems that only
  exist across fields or across records — key collisions, broken uniqueness,
  foreign-key integrity.

**2.5 — Loader**
- [x] `db/loader.py` — raw JSONL → rows → `INSERT`s, taking the connection and
      `raw_dir` as arguments. **It is the only module that writes rows:**
      `db/validate.py` now calls it against an in-memory database with an
      `Observer` that records failures instead of raising, so "validated"
      means "went through the code that loads it". A validator with its own
      INSERT sequence can only check the sequence it happens to share with
      the loader, and the two drift the first time either learns something.
      - Failure policy is injected, not decided: the default `Observer`
        raises on the first refused row, because by then validation has
        already been over the same corpus and a failure means something
        changed.
      - Drops the four impossible-date studies, and the tally says so. That
        also removes every row **only** they referenced — 2 sponsors (Ixaka
        Limited, VHIO), 1 funder and 1 centre — so four row counts are one or
        two below §3.2c's cache figures by design.
      - Derives no survival or censoring columns (§3.2c).
      - **Performance, and a real bug:** the whole write pass runs in one
        explicit transaction. Without it the per-row `SAVEPOINT` is the
        outermost savepoint, so every `RELEASE` commits and every commit
        fsyncs — invisible against `:memory:`, and the difference between
        **9 seconds and over 10 minutes** against a file.
- [x] Wired into `run_pipeline.py` as the composition root: `python
      run_pipeline.py build` rebuilds `data/trials.db` from `data/raw/` in 9
      seconds, `validate` runs the dry run. Ingestion is deliberately NOT
      wired in — it costs ~4 hours of API calls and `data/raw/` is the
      durable copy, so a database rebuild must not be able to touch it.
      `build` also checks the row counts against the figures profiling
      predicted, and exits non-zero if they differ: a load that silently
      drops a table still "succeeds", and this is the cheapest thing that
      notices. It earned its place on the first run, catching the
      dropped-study cascade above.

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
