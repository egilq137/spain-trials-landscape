# Handoff — end of Phase 2

**Read first:** `CLAUDE.md`, then `PROJECT_SPEC.md` §3.2c (long, and the
reasoning in it matters more than the conclusions).

**State:** `main` at `275c03b`, clean and pushed. 408 tests pass.
`feature/cleaning-rules` is merged and can be deleted when you're confident.

```bash
python run_pipeline.py build      # rebuild data/trials.db from the cache, ~9s
python run_pipeline.py validate   # dry run: what would load, what would change
python -m unittest discover -s tests
```

---

## What exists

Phase 1 (ingestion) and Phase 2 (transform + database) are complete.
11,847 studies cached as JSONL in `data/raw/detalle/` (gitignored, 208 MB,
**never rewritten** — it is the provenance record).

| module | job |
|---|---|
| `db/cleaning_rules.py` | every rule that changes a value, written as data |
| `db/cleaning_rules_tally.py` | counts what a load actually changed |
| `db/transform.py` | one record → rows. Pure functions |
| `db/centers.py` | 85,410 centre entries → 3,294 physical sites |
| `db/names.py` | which spelling of an organisation to display |
| `db/schema.sql` | 12 tables, 4 bridges, `STRICT`, written in 4 slices |
| `db/loader.py` | **the only module that writes rows** |
| `db/validate.py` | the loader again, with failures collected not raised |
| `run_pipeline.py` | composition root |

A build produces 11,843 studies (11,847 minus 4 impossible-date drops),
2,959 sponsors, 2,208 funders, 3,293 centres, 30,941 interventions, 3,305
substances, 53 routes, 55 therapeutic areas. `build` checks those counts and
exits non-zero if they move.

---

## Decisions to respect

1. **The database stores facts and derives nothing.** No `censored`,
   `survival_start`, or industry/academic label. Three defensible survival
   windows exist and they measure different things; a trial cancelled before
   enrolling is a *competing risk*, not a completion. The estimand is chosen
   in `analysis/`.
2. **Normalisation in the loader; entity resolution not.** Case, accents,
   punctuation, spacing, markup, descriptive clauses and postal addresses are
   all *how a value was typed* — safe to merge mechanically. Whether
   `Lilly S.A.` is `Eli Lilly & Co.` changes what "top sponsor" *means*, so it
   stays out of the database.
3. **`db/validate.py` has no INSERT sequence of its own.** It calls
   `loader.load` with an `Observer` that records instead of raising. Keep it
   that way: a validator with its own copy can only check the copy.
4. **Normalise for comparison, preserve for display.** Every name field has a
   folded key for identity and a real spelling for display. Folding is enough
   to group by and wrong to store — it gives `astrazeneca ab` and `a coruna`.
5. **Enumerate, don't pattern-match.** `PLACEHOLDERS` is a list because a
   regex broad enough to catch `not available` also eats `Best Available
   Treatment`; matching `none` eats *finerenone*; matching `calle` eats the
   surname *Calleja*. Patterns generate candidates; the list decides.
6. **Read every merge before accepting it.** Each identity change in this
   phase was followed by printing the groups it merged and checking them by
   eye. That is how the mistakes below were caught.

---

## Bugs this phase found, worth not repeating

- **A map keyed one way and used another.** `ROUTE_CANONICAL` keyed an HTML
  entity as raw text; the loader decoded it first, so the entry matched
  nothing and 20 rows became a 54th route. Its own corpus test passed, because
  the test normalised the way the map did, not the way the loader did.
- **A spec sentence is not a test.** §3.2c said `promotor` holds "the most
  frequent cleaned spelling" since the profiling stage. The loader stored
  *first-seen*, so a sponsor with 223 trials was called `Pfizer Inc., 235 East
  42nd Street, New York, NY 10017`. Nothing failed.
- **`:memory:` hides I/O costs.** The per-row `SAVEPOINT` was the outermost
  savepoint, so every `RELEASE` committed and fsynced. Invisible in tests;
  a 9-second build took over ten minutes against a file.
- **Clean-looking output over an empty table.** "0 rejected" covered 2 tables
  and read like 12. The report now prints rows built per table.

---

## Next: Phase 3

First analysis and chart: **trials authorised per year, with the January 2023
CTIS break**. One query plus one Plotly chart, in `analysis/`.

Two things had to be settled before drawing it:

- **Both settled in PROJECT_SPEC §3.2d, against the built database — and both
  of the assumptions written here first were wrong.** `es_ctis` marks the
  register, not the regime: 1,679 studies authorised before 2023 carry a CTIS
  identifier because their records were *transitioned*, so the regime split
  needs both fields (EudraCT / CTIS / transitioned), not either alone. And the
  pre-2017 years are a single 2017-11-02 backload, not left truncation —
  1,495 studies of the 2013-2016 cohort ended before the registry's first
  registration date, which truncation-on-still-running could not produce. The
  chart starts at 2013 (REEC's coverage boundary) and marks 2026 partial; the
  Kaplan-Meier fits take no `entry=` argument.

Then §3.3's remaining questions: therapeutic landscape, phase distribution,
sponsor structure, geography (choropleth), duration (Kaplan-Meier, log-rank,
Cox), results-reporting compliance.

### Known, deliberately left for `analysis/`

- **Corporate families.** `Lilly S.A.` (90) vs `Eli Lilly & Co.` (96); six
  AstraZeneca entities; `Roche Farma S.A.` vs `S.A.U.` vs `F. Hoffmann-La
  Roche AG`. Generate candidates by blocking on shared tokens and ranking by
  trial count — the top ~40 groups cover almost all the ranking error.
- **Drug names carry dose and form.** 27% of `interventions.nombre_comercial`
  look like `KEYTRUDA 25 mg/mL concentrate for solution for infusion`, so
  counting trials per drug from that column is currently wrong. `substances`
  is cleaner but stops in 2022 — the two fields never co-occur.
- **`provincia` names the wrong province in 258 rows.** The vocabulary is
  clean, the assignment is not. Derive province from the postcode prefix.
- **A decision, not a cleaning task:** 37 sponsors are named individuals
  (`Dra. Cristina Avendaño Solá`), 39 trials. Public by mandate, but §3.2b
  says named-individual data must not reach the dashboard. Keep, relabel, or
  drop — the user has not decided.

---

## House conventions

- Tests are stdlib `unittest`, with a "Success criteria" docstring header.
  Two layers: pure unit tests, plus corpus-backed tests decorated
  `@requires_corpus` that skip when `data/raw/detalle` is absent.
- Use the `Edit` tool for structural changes. A scripted `str.replace` has
  silently failed and deleted code in this project.
- `PYTHONIOENCODING=utf-8` on Windows, or accents print as mojibake.
- Every count in a comment, docstring, test or spec section is measured. If a
  rule changes, re-measure and update all of them — `run_pipeline.py build`
  will tell you which moved.
- Flag epidemiology/biostatistics and software-architecture concepts as
  learning opportunities, briefly. Explain from first principles.
