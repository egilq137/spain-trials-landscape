"""Coarse groups over the canonical administration routes.

`db.cleaning_rules.ROUTE_CANONICAL` answers "what route is this value?" -- a
mechanical question, so it lives with the other cleaning rules. This module
answers "which routes count as the same thing for the question I am asking?",
which is a judgement, so it lives here. Merging `oral use` into `oral` is
harmonisation; deciding that sublingual counts as oral is a claim about what
the analysis cares about, and a pharmacokineticist would dispute it (see the
note on the oral group below).

That split is why there is no `grupo` column on `administration_routes`: a
column freezes one answer into the database, and a different question would
want a different one. The map is applied at query time instead, so a chart
that wants the 52 canonical routes can still have them.

52 canonical routes -> 12 groups, over the 16,969 interventions that carry a
route at all. The other 13,972 have none: the field only exists from 2022
onward, when it replaced `sustancias` at the CTIS transition, so route
analysis is confined to that side of the break and the absence is structural,
not missingness to impute.

Row counts below are from the loaded corpus and are what makes the grouping
defensible rather than tidy-looking: four routes carry 98% of the rows, and
every group past `intramuscular` exists to keep a long tail of 1-3 row routes
from being 40 separate slices of a pie chart.
"""

# Canonical route -> group. Every value of ROUTE_CANONICAL appears exactly
# once; `tests/test_routes.py` fails if one is added upstream without a group,
# because a fallthrough here would silently drop rows from a total.
ROUTE_GROUP = {
    # --- oral, 7,285 rows ---------------------------------------------------
    # JUDGEMENT: sublingual, buccal and oromucosal are grouped with oral
    # because they enter by the mouth, which is the distinction a landscape
    # count is drawing. Pharmacologically they are not oral: they cross the
    # oral mucosa and skip the first pass through the liver, so a
    # bioavailability question would have to separate them again. 22 rows, so
    # the choice moves nothing either way -- it is stated because it is the
    # kind of thing that stops being harmless once someone reuses the map.
    "oral": "oral",
    "sublingual": "oral",
    "buccal": "oral",
    "oromucosal": "oral",
    # Feeding tube: not by mouth, but the same destination and the same
    # first-pass metabolism, which is the part that matters.
    "enteral": "oral",

    # --- intravenous, 6,182 rows -------------------------------------------
    # Kept alone rather than folded into a "parenteral" group: with oral it is
    # 79% of the corpus, and the oral/IV split is the shape of the whole
    # picture.
    "intravenous": "intravenous",

    # --- subcutaneous, 1,782 rows ------------------------------------------
    "subcutaneous": "subcutaneous",

    # --- intramuscular, 356 rows -------------------------------------------
    # Its own group at 2% mostly because it is where vaccines are, and a
    # vaccine question would be unanswerable if it were inside "other".
    "intramuscular": "intramuscular",

    # --- parenteral, route unspecified, 298 rows ---------------------------
    # NOT merged into the injected groups above, and not into "other
    # parenteral" either. These are rows where the registry said "injection"
    # or "parenteral" and stopped; the group exists so that a chart shows them
    # as an answer the source did not give, rather than hiding them inside a
    # route nobody recorded. Second-biggest reason to distrust a route total
    # after the 13,972 nulls.
    "injection, route unspecified": "parenteral, unspecified",
    "parenteral, route unspecified": "parenteral, unspecified",

    # --- respiratory, 255 rows ---------------------------------------------
    "inhalation": "respiratory",
    "nasal": "respiratory",
    "intratracheal": "respiratory",

    # --- skin, 196 rows ----------------------------------------------------
    # JUDGEMENT: intradermal sits here rather than with the injected groups.
    # It is a needle, but the target is the skin, and the trials using it are
    # dermatological or vaccine-intradermal rather than systemic. Debatable;
    # 35 rows.
    "topical": "skin",
    "cutaneous": "skin",
    "transdermal": "skin",
    "percutaneous": "skin",
    "intradermal": "skin",

    # --- ocular, 152 rows --------------------------------------------------
    # Small in rows, but it is the whole of a therapeutic area: intravitreal
    # alone is 58 rows of retinal trials that would vanish into "other".
    "ocular": "ocular",
    "conjunctival": "ocular",
    "intravitreal": "ocular",
    "subretinal": "ocular",
    "suprachoroidal": "ocular",
    "intracameral": "ocular",
    "retrobulbar": "ocular",

    # --- central nervous system, 87 rows -----------------------------------
    # JUDGEMENT: perineural is peripheral nerve, not central, so the group
    # name is a convenience. It is here because the alternative was a group of
    # one. 7 rows.
    "intrathecal": "central nervous system",
    "epidural": "central nervous system",
    "intracisternal": "central nervous system",
    "intracerebroventricular": "central nervous system",
    "intracerebral": "central nervous system",
    "perineural": "central nervous system",

    # --- other parenteral, 54 rows -----------------------------------------
    # Injected or infused, systemic or vascular intent, none of them big
    # enough to stand alone. Distinguished from "local or regional" by whether
    # the drug is meant to travel.
    "intraarterial": "other parenteral",
    "intracoronary": "other parenteral",
    "intraperitoneal": "other parenteral",
    "intraosseous": "other parenteral",
    "intralymphatic": "other parenteral",
    "intraamniotic": "other parenteral",
    "extracorporeal": "other parenteral",

    # --- local or regional, 175 rows ---------------------------------------
    # Delivered into or onto one structure, meant to act there. The residual
    # group, so it is the one to look inside before quoting it.
    "intratumoral": "local or regional",
    "peritumoral": "local or regional",
    "intralesional": "local or regional",
    "intravesical": "local or regional",
    "intraarticular": "local or regional",
    "intrabursal": "local or regional",
    "infiltration": "local or regional",
    "intracochlear": "local or regional",
    "auricular": "local or regional",
    "dental": "local or regional",
    "vaginal": "local or regional",
    "rectal": "local or regional",
    # An implant or a graft is a placement, not a route, and the registry uses
    # both words that way. Grouped by where the thing ends up.
    "implantation": "local or regional",
    "transplantation": "local or regional",

    # --- multiple routes, 147 rows -----------------------------------------
    # Values naming more than one route, which `interventions` cannot split
    # because it carries a single route_id. Stays its own group for the same
    # reason it stays its own canonical value: assigning it to the first route
    # written would invent a fact.
    "multiple routes": "multiple routes",
}


def route_group(canonical):
    """The group a canonical route belongs to.

    Raises KeyError on an unknown route rather than returning a default. A
    route reaching this function is one the loader already recognised, so an
    unknown value means ROUTE_CANONICAL grew a route this map has not been
    told about -- a fact worth a traceback, not a silent slide into "other".
    """
    return ROUTE_GROUP[canonical]
