# Handoff — Phase 5, the Streamlit dashboard

**Read first:** `CLAUDE.md`, then `PROJECT_SPEC.md` §3.3 (what each chart claims
and, more importantly, what each one refuses to claim) and §3.5 (layering).
The §3.2c/§3.2d sections are the evidence behind the numbers; you do not need
them to build the dashboard, but you do need them the moment you are tempted
to change a denominator.

**State:** `main` at `d448db1`, clean and pushed. 731 tests pass.
Phases 1–4 are complete except survival analysis, which is deliberately
after this.

**Two of five dashboard pages are built:** Overview (KPI cards) and Geography
(three tabs, filters, a dot map). Volume, Therapeutic, Phases and Sponsors
are not started. See *Next: the volume page* below for the one open decision
before that work begins.

```bash
python run_pipeline.py build      # rebuild data/trials.db from the cache, ~9s
python run_analysis.py            # rebuild every chart into docs/
python -m unittest discover -s tests
```

---

## What exists, and what you must not rebuild

Five analysis modules. **Every one of them already separates the query from
the figure**, which is the whole reason the dashboard is cheap: take the data
function, skip the figure function, and render with Streamlit — or call the
figure function and hand the result to `st.plotly_chart`.

| module | data functions (take a connection) | figure functions (pure) |
|---|---|---|
| `analysis/volume.py` | `trials_per_year`, `coverage` | `figure` |
| `analysis/therapeutic.py` | `trials_per_area`, `area_counts_by_year` | `figure`, `trend_figure`, `race_figure` |
| `analysis/geography.py` | `region_pairs`, `province_pairs`, `load_geometry` | `figure` |
| `analysis/phases.py` | `phase_mix`, `early_phase_by_year`, `phase_by_area` | `mix_figure`, `early_phase_figure`, `heatmap_figure` |
| `analysis/sponsors.py` | `classified_studies`, `phase_four_by_year`, `top_families`, `family_review` | `share_figure`, `phase_four_figure`, `families_figure`, `review_page` |

Pure helpers that turn rows into chart-ready shapes and need no connection:
`therapeutic.ranked_areas` / `top_areas` / `area_trends` / `yearly_shares`,
`geography.participation` / `unlocated` / `names_in`,
`phases.label_of`, `sponsors.classify` / `family_of` / `display_name` /
`share_by_year`.

Twelve charts are already generated into `docs/charts/`, plus
`docs/sponsor-families.html`. Open them before writing anything: the dashboard
is these, plus filters.

---

## Architecture rules this phase has to hold

- **`app/` is presentation only.** No SQL, no `sqlite3.connect`, no business
  logic. It imports from `analysis/` and calls Streamlit. If you find yourself
  writing a query in `app/`, the function belongs in `analysis/` instead —
  that is the rule that has kept every number in this project testable.
- **`app/` is the one layer with no unit tests, by design.** Streamlit's
  execution model makes them near-worthless. The way that stays honest is by
  keeping `app/` thin enough that there is nothing in it to test. Anything
  worth a test goes in `analysis/` and gets one.
- **Connections are injected, opened read-only, and cached.**
  `run_analysis.open_database()` is the existing pattern (`mode=ro` via URI).
  In Streamlit use `@st.cache_resource` for the connection and
  `@st.cache_data` for query results — without them every widget interaction
  re-runs every query.
- **One composition root per entrypoint.** `run_pipeline.py` builds the
  database, `run_analysis.py` builds the static charts, and the Streamlit app
  is the third. Do not have `app/` reach into `run_analysis`.

---

## The trap that will actually bite you

**Each chart counts a different way, and a single global filter will silently
corrupt three of them.** This is not a detail; it is the thing that makes a
dashboard harder than a set of charts.

| chart | one trial appears | shares sum to |
|---|---|---|
| volume per year | once | 100% |
| phase mix | once | 100% |
| sponsor class | once | 100% |
| therapeutic areas | **once per area it lists** (363 list 2+) | ~104% |
| regional / province map | **once per region it has a site in** (~3.9 each) | ~390% |
| phase × area heatmap | **once per area, and per phase it reaches** | neither |

Consequences for filter design:

- A filter on therapeutic area applied to the geography map is legitimate but
  changes the map's denominator. Decide whether "% of trials" means *of all
  trials* or *of the filtered set*, then say which on the chart.
- Never build a "share of total" KPI card by summing a chart whose rows
  overlap. The volume total (11,834) is the only safe denominator, and it
  already lives in `volume.trials_per_year`.
- Every existing chart states its counting rule in its own subtitle. **If you
  re-render a figure with a filter applied, the subtitle must still be true.**
  Several subtitles quote hard numbers (`11,834 trials`, `181 trials are not
  on the map`); filtering makes those false. Either recompute the subtitle or
  keep the unfiltered chart and put the filter elsewhere.

---

## Deployment blocker to settle *before* designing pages

`data/trials.db` is **gitignored** (`*.db`) and `data/raw/` is gitignored and
273 MB. **Streamlit Community Cloud will clone the repo and find no data.**
Decide this first, because it constrains the design:

- **Commit the database.** 14 MB, well under GitHub's 100 MB file limit. Costs
  the project its "the .db is a disposable build artifact" rule, which is a
  real principle in `db/schema.sql` — but the rule was about rebuilding from
  `data/raw/`, and deployment is a different concern. Cheapest, keeps every
  filter interactive.
- **Commit a reduced database** built for the dashboard: only the columns and
  tables the app reads. Keeps the principle mostly intact, adds a build step.
- **Precompute chart data to JSON/parquet and commit that.** Smallest and
  cleanest architecturally — `analysis/` produces data, `app/` renders it —
  but it kills row-level filtering, so the dashboard becomes static charts
  with a year slider at best.

Recommended: commit the 14 MB database, and write the reason into
`db/schema.sql`'s comment so the principle and its exception sit together.

---

## What the app looks like now

Five files, and the shape is worth knowing before adding a sixth.

| file | what it is |
|---|---|
| `app/main.py` | the composition root. Pages are a literal list of `st.Page`, each with an explicit `url_path` — every view's entry point is called `page()`, so without it Streamlit infers one pathname for all of them and raises. |
| `app/session.py` | the one cached read-only connection, and `GEO_DIR`. Nothing else belongs here: cached query wrappers live beside the view that asks. |
| `app/theme.py` | reads `.streamlit/config.toml` and restyles figures. The palette lives in one file so it can change in one line. |
| `app/charts.py` | `render()` clears the authored 760px width so a figure fills its column; `render_fixed()` keeps it, for the maps only. Read its docstrings before choosing. |
| `app/views/overview.py` | the pattern to copy: a `@st.cache_data` passthrough to `analysis/`, then `page()`. ~45 lines, no logic. |

**Adding a page is three steps:** write `app/views/<name>.py` with a `page()`,
add one `st.Page(...)` line to `main.py` with a fresh `url_path`, restart the
server.

**The cache decorators are not interchangeable.** `@st.cache_data` returns a
fresh copy per call, which is what makes `charts.render()`'s mutation of the
figure safe. `@st.cache_resource` hands out the same object every time — right
for the connection and for a read-only dict (`geography.hospital_codes`),
wrong for anything a caller mutates. Arguments prefixed `_` are excluded from
the cache key; that is how the connection is passed without being hashed, and
why `since` must *not* have an underscore.

---

## Next: the volume page

**The one decision to make first: `analysis/volume.py` holds a single series.**
`trials_per_year(con)` and `coverage(con)`, and that is all. Every page built
so far wrapped three to five existing analysis functions; this one has one
chart's worth of analysis and a page's worth of screen. So the question is
what makes it a page, and there are three honest answers:

1. **One chart, unfiltered.** Render `volume.figure(series, cover)` through
   `charts.render()` and stop. Matches build-order step 3 exactly, costs
   almost nothing, and is defensible — the chart already carries its own
   counting rule and its own coverage caveat. A thin page is better than an
   invented one.
2. **Add a "since" control.** The chart is already a year axis, so a year
   *range* filter is close to meaningless — but a floor is not. `since`
   threads through `trials_per_year` and `coverage` already. Watch the trap:
   `COVERAGE_START = 2013` exists because REEC's coverage begins there and
   **nine studies are authorised earlier**. A control that offers a floor
   below 2013 quietly re-admits them, and `coverage().excluded` is what the
   subtitle uses to say so.
3. **Write new analysis.** Cumulative totals, year-on-year change, or a
   monthly view of the last few years. This is real work in `analysis/` with
   tests, not dashboard work — and it should be decided as an analysis
   question, not reached for to fill a page.

Recommendation: start at (1), look at it in the browser, and only then decide
whether it is too thin. That is the order every other page went in.

**Facts the page must reproduce** (verified at `d448db1`):

- 11,834 trials, 2013 (759) through 2026 (674)
- `coverage()` → `data_cut='2026-08-26'`, `excluded=9`
- the subtitle already says all three things: counted on the AEMPS
  authorisation date, 2026 partial to the data cut, 9 trials excluded before
  2013

**If you filter anything, re-read the counting table above.** Volume is the
one chart where a trial appears exactly once, which is precisely why its total
is the only safe denominator in the project. A therapeutic-area filter applied
here would silently break that: 363 trials list two or more areas, so the
filtered bars would no longer sum to a number that means "trials".

**`volume.figure` also draws the CTIS mandate line** at
`CTIS_MANDATE_BOUNDARY = 2022.5` — between the bars, not on one, because CTIS
became compulsory on 2023-01-31. Do not move it to 2023 to make it line up.

---

## Build order (§3.5 says incremental, verify in the browser after each)

1. ~~**`.streamlit/config.toml`**~~ **Done.** The dashboard uses a teal accent
   (`#2f6f6b`) on a warm surface, *not* the blue the static charts use.
   `docs/charts/` stays blue on purpose: those files are the Phase 4
   deliverable and were not re-rendered. `app/theme.py` reads the config, so
   the palette changes in one line.
2. ~~**KPI cards, no filters.**~~ **Done** — `app/views/overview.py`. Note the
   counts are **2013-scoped** and therefore disagree with
   `run_pipeline.py`'s `EXPECTED_ROWS` (11,843 rows, 2,959 sponsors) by
   design. `analysis/overview.py` documents why `EXPECTED_ROWS` is the wrong
   oracle: it counts what the pipeline loaded, not what the corpus is.
3. **One page per §3.3 question**, reusing the existing figures unchanged and
   unfiltered. This is the checkpoint: the whole dashboard should work as a
   read-only report before any widget exists. **Geography went further than
   this** — it has filters and a dot map — because it was built first at the
   user's request. Volume, Therapeutic, Phases and Sponsors are still at
   step 3.
4. **Then filters, one at a time**, re-reading the counting table above each
   time. Year range is the safe one to start with (every chart is already
   keyed on authorisation year and `COVERAGE_START` is shared).
5. **Phase distribution by region** — deferred here from Phase 4 on purpose,
   because it is a filter rather than a chart. Already measured: phase I share
   runs Navarra 24.9%, Madrid 21.8%, Cataluña 20.2% against País Vasco 5.8%
   and Balears 4.5%.
6. **`use_container_width=True`** on every `st.plotly_chart`. The figures are
   built at a fixed 760px (860 for the heatmap) for the static files.

---

## Working on it: restart the server after touching `analysis/`

**Streamlit's auto-reload does not re-import modules under `analysis/`.** It
reloads the page script and the files in `app/`, and keeps the old
`analysis.*` in memory. Editing a query and seeing nothing change is the mild
version; the loud version is a `TypeError` about argument counts, from a new
`app/views/*.py` calling an old `analysis/*.py` that has not grown the
parameter yet. Both were hit repeatedly while building the geography page,
and neither is a bug in the code being edited.

So: after editing anything under `analysis/`, stop the server and start it
again. "Rerun" and "Always rerun" are not enough. Only `app/` edits hot-reload
honestly.

Two other environment notes from the same phase:

- **`pyarrow` is blocked on the development machine** by an Application
  Control policy, surfacing as `ImportError: DLL load failed while importing
  lib`. Nothing in the app needs it, but `st.dataframe`, `st.table` and
  `st.write` of anything table-shaped will crash. Use `st.markdown` and
  `st.metric`, which is what the pages do.
- **`use_container_width` is the old spelling.** In Streamlit 1.63
  `st.plotly_chart(width="stretch")` is the default and passing
  `use_container_width=True` warns. Build order step 6 below is out of date on
  this point; see `app/charts.py`, which also explains why the maps are the
  one thing that must *not* stretch.

---

## Constraints that are not negotiable

- **Named individuals must never be displayed.** PROJECT_SPEC §3.2b. 54
  sponsors are people; `sponsors.display_name()` and `sponsors.family_of()`
  both already return `"Individual investigator"` for them. Any new sponsor
  list in the dashboard must go through one of those, not through
  `sponsors.promotor` directly.
- **Sponsor contact fields never reach the app** — they are not in the
  database at all, and must not be re-added.
- **The EuroGeographics attribution travels with the maps.** See
  `data/geo/README.md`; the figures already carry it, so do not strip it when
  restyling.
- **2026 is a partial year** (data cut 2026-08-26) and every time-series chart
  says so. A dashboard that lets the user select "2026" alone must keep
  saying so.
- **Coverage starts 2013.** `volume.COVERAGE_START`. Nine studies are
  authorised earlier and are excluded everywhere; a year filter must not
  quietly re-admit them.

---

## What the geography phase changed underneath everything

Not needed to build the volume page — volume reads `studies` and nothing
else — but it is the largest change since this document was written, and it
moves numbers on any page that counts centres.

REEC centre rows are now matched against the **Catálogo Nacional de
Hospitales** (`data/geo/hospitals.csv`, 848 state-recognised hospitals) by
`analysis/hospitals.py`, and `geography.identities` merges rows sharing a
code. Consequences:

- 1,378 of 3,293 centre rows resolve to a national hospital
- the dot map draws **1,889 sites**, down from 2,275
- `docs/hospital-matches.html` and `docs/hospital-ambiguous.html` are the
  review pages; 19 ambiguous cases worth 93 trial-links are deliberately
  left undecided, and 512 near misses have never been read
- decisions a person made live in `ANSWERS` / `PROPOSED` in
  `analysis/hospitals.py`, each with its reason. **Rules were never tuned to
  fix individual rows** — that separation is the point, and the thresholds
  still hold 0 wrong matches on the 324-row calibration set

The one trap it introduced: `ANSWERS` is keyed on `normalise_town`'s output,
so **changing that function invalidates stored keys**. Two tests guard it
(`test_a_key_survives_its_own_normaliser`, `test_the_answers_are_reachable`).
Treat an edit there as a migration, not a refactor.

Attribution requirement: the catalogue needs "Origen de los datos: Ministerio
de Sanidad, Consumo y Bienestar Social" and its 31 December 2024 update date
wherever it is shown. The review pages already carry both.

---

## Known-good verification

- `python -m unittest discover -s tests` → 731 tests, all passing (~35s).
- `python run_analysis.py` → 12 charts and three review pages,
  byte-identical on re-run (`div_id` is pinned per file for exactly this
  reason).
- `streamlit run app/main.py` → Overview and Geography. There is a
  `.claude/launch.json` (`dashboard`, port 8502) if your tooling uses it.
- Headline numbers the dashboard must reproduce: 11,834 trials from 2013;
  cancer 4,239 (35.8%); Cataluña 79.0% and Madrid 75.2% regional
  participation; industry 9,475 (80.1%); phase III 4,468 (37.8%).

---

## Deliberately not in this phase

- **Survival analysis** — Phase 4's last question, held until after the
  dashboard so it can slot in as one more page. It needs a decision first:
  which of three windows is the duration (authorisation→end, 6,437 studies;
  start→end, 5,719; authorisation→start, 10,127, which is a different
  question), and `fechaFinPrematuro` handled as a **competing risk** rather
  than as censoring.
- **Results-reporting compliance** — §3.3 expected this to be the headline,
  but **the REEC API does not carry it**: no results field in the detail
  endpoint, the list endpoint, or the raw cache. The original evidence was the
  website's Angular search filter, which §3.1 rules out as a source. Pending
  decision: drop it with the reason documented, probe for an undocumented
  endpoint, or take it from EU CTR/EudraCT as a second source.
- **The 68 centres with a postcode and no province** — a prefix fill, noted in
  §3.3's geography follow-up.
