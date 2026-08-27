# CLAUDE.md

Portfolio project for Madrid data-scientist job applications — see `PROJECT_SPEC.md`
for full context. Favor demonstrable, explainable code over cleverness — every
decision should be something you can walk an interviewer through.

Behavioral guidelines to reduce common LLM coding mistakes, plus project-specific
architecture conventions.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Learning Context

This is a learning project as much as a portfolio project — alongside the
deliverables, use it to build depth in epidemiology/biostatistics and in
software design/architecture.

- When a key epidemiology/biostatistics concept comes up in the work (e.g.
  censoring, hazard ratios, proportional-hazards assumptions, person-time,
  competing risks), briefly flag it and point to it as something worth studying
  further — don't just apply it silently.
- When a key software design/architecture concept comes up (e.g. dependency
  injection, separation of concerns, why a particular layering or folder
  structure was chosen), briefly flag it the same way.
- Keep these call-outs short — a sentence or two, not a lecture — and tied to the
  real code/analysis just written, not abstract theory.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Project Architecture

Adapted from "4 tiers" / package-by-feature architecture patterns:

| Layer | Folder | Responsibility |
|---|---|---|
| Persistence | `ingestion/`, `db/` | Talking to the REEC API and the SQLite database. No business logic. |
| Service | `analysis/` | Transformation, statistics, survival analysis — the actual domain logic. |
| View | `app/` | Streamlit dashboard — presentation only, no direct DB/API calls. |

- **Package by feature within each layer**, not by technical type — e.g. inside
  `analysis/`, group by analysis question (volume, survival, geography) rather
  than by function-type.
- **Composition root:** one entrypoint (e.g. `run_pipeline.py`) wires ingestion →
  transform → db → analysis explicitly. Avoid modules reaching into each other's
  globals.
- **Explicit dependencies:** pass DB connections/config into functions as
  arguments rather than importing module-level singletons, so pieces stay
  testable in isolation.
- **Error handling:** distinguish expected data issues (missing/malformed REEC
  fields — see `PROJECT_SPEC.md` §3.2 for known fill-rate gaps) from real
  failures (API down, schema mismatch). Use specific exception types; don't
  silently pass or return `None` for either case.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer
rewrites due to overcomplication, clarifying questions come before implementation
rather than after mistakes, and epi/biostat or architecture concepts get flagged
as learning opportunities rather than applied silently.
