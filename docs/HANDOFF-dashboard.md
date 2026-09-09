# Handoff — Phase 5, the Streamlit dashboard

**Read first:** `CLAUDE.md`, then `PROJECT_SPEC.md` §3.3 (what each chart claims
and, more importantly, what each one refuses to claim) and §3.5 (layering).
The §3.2c/§3.2d sections are the evidence behind the numbers; you do not need
them to build the dashboard, but you do need them the moment you are tempted
to change a denominator.

**State:** `main` at `f5d5c72`, clean and pushed. 597 tests pass.
Phases 1–4 are complete except survival analysis, which is deliberately
after this.

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

## Build order (§3.5 says incremental, verify in the browser after each)

1. **`.streamlit/config.toml`** with the existing palette so the app and the
   charts agree: surface `#fcfcfb`, ink `#0b0b0b`, primary `#2a78d6`. The
   figures hardcode these in `analysis/volume.py`.
2. **KPI cards, no filters.** 11,834 trials · 2,957 sponsors · 3,293 centres ·
   55 therapeutic areas · data cut 2026-08-26. Verify against
   `run_pipeline.py`'s `EXPECTED_ROWS` — if a card disagrees with that dict,
   the card is wrong.
3. **One page per §3.3 question**, reusing the existing figures unchanged and
   unfiltered. This is the checkpoint: the whole dashboard should work as a
   read-only report before any widget exists.
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

## Known-good verification

- `python -m unittest discover -s tests` → 597 tests, all passing.
- `python run_analysis.py` → 12 charts and the review page, byte-identical on
  re-run (`div_id` is pinned per file for exactly this reason).
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
