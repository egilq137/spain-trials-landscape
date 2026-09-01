"""Every rule that changes a value between the raw cache and the database.

Rules live here as **data**, not as logic buried in the loader, for three
reasons: this file reads as the answer to "what do we change from the raw
data?"; `git diff` on it is the changelog, so a new rule is a visible dated
line rather than an edit inside a function; and each rule can be tested
against the count that justified it, so a refresh that changes the data
underneath fails loudly instead of silently.

`data/raw/` is never rewritten, so it stays the provenance record — the
database therefore does not carry shadow columns holding the original values.
The rules plus the load manifest are enough to get back to any raw value.

Counts in comments are measured over all 11,847 cached studies. The
corpus-backed tests in tests/test_rules.py re-check them when the cache is
present.

Step 1 of 6: placeholders and sentinels, as data plus the two functions the
corpus tests need to check them. Route spellings, name normalisation and
postcode padding follow; the functions that apply these rules arrive in step 3
with the code that calls them.
"""

import unicodedata

# ---------------------------------------------------------------------------
# Placeholders — text meaning "nothing here", which the registry writes instead
# of leaving a field blank.
# ---------------------------------------------------------------------------
# Matched against a casefolded, accent-stripped, whitespace-collapsed form, so
# 'N/A', 'n/a' and ' N.A. ' are one entry. Enumerated rather than pattern-
# matched: a regex broad enough to catch these also catches real values --
# 'NA' is a legitimate trade name fragment, and a fuzzy rule would eat it.
#
# Where they occur:
#   acronimo               4,763 of 6,574 non-blank   (NA alone 4,744)
#   funders.nombre           584 across the corpus      (NA alone   572)
#   centers.referencia       119  -- spanning 103 distinct hospitals, so this
#                                   one changes identity, not just a label
#   centers.nombre             2
#   interventions.nombre   2,205  -- '-' 1,922 and 'NA' 283
#
# The totals are higher than the single most frequent form in each field,
# which is the point of enumerating rather than matching only 'NA': 'None'
# (11) and 'NO APLICA' (1) are funders, and a lone '.' is an acronym.
PLACEHOLDERS = frozenset({
    "na",
    "n/a",
    "n.a",
    "nr",
    "n.r",
    "nd",
    "n.d",
    "no aplica",
    "no aplicable",
    "no consta",
    "none",
    "ninguno",
    "not available",
})

# Values that are punctuation only -- '-' (1,922 intervention names), '--',
# '.', '..' -- are not listed above. `fold` strips edge punctuation, so they
# reduce to the empty string, and `is_placeholder` treats "folded away to
# nothing, but was not blank to begin with" as a placeholder. That covers any
# such value without having to enumerate every combination of dashes and dots.

# ---------------------------------------------------------------------------
# Sentinels — numbers meaning "unknown", in columns that otherwise hold counts
# or flags.
# ---------------------------------------------------------------------------
# Both load as NULL. Storing them raw makes every AVG and SUM silently wrong:
# a -1 averaged into a flag, and 2,201 zeros averaged into planned enrolment.
#
# This mapping loses nothing, and that is a property of the data rather than a
# convenience: every poblacion and proposito field is present in 11,847/11,847
# records -- never blank, never null, never absent -- and -1 is the only value
# that is not 0 or 1. So there are no pre-existing NULLs for the mapping to
# collide with, and a NULL in a flag column means "the source sent -1" and
# nothing else. Re-checked on refresh by tests/test_rules.py, not assumed.
FLAG_UNKNOWN = -1

# The 12 poblacion flags that carry -1, and how many values each. The other 6
# (voluntariossanos, pacientes, pobvulnerable, adultos, ancianos, menores)
# never do, and neither does any of the 24 proposito flags -- which is why
# those stay NOT NULL.
FLAGS_WITH_UNKNOWN = {
    "urgencia": 11,
    "mujerusa": 8,
    "embarazadas": 8,
    "lactancia": 7,
    "mujernousa": 6,
    "incapaces": 6,
    "preescolar": 2,
    "adolescentes": 2,
    "intrauteros": 1,
    "prematuros": 1,
    "reciennacido": 1,
    "ninos": 1,
}

# poblacion.total. 0 means "not reported", not a trial planning nobody --
# 2,201 records, 18.6%. Median is 180 once excluded.
TOTAL_UNKNOWN = 0

# The largest values were each looked up rather than judged by size, because
# size is not evidence -- a phase I oncology trial cannot enrol 114,011 and a
# pragmatic phase IV vaccine trial easily can. Only one of the three turned out
# to be actionable, so only that one is data; the rest is the record of the
# check.
#
#   999999  2025-524690-16-00 -- NOT a count. A phase I open-label study of
#           BBO-11818 in KRAS-mutant solid tumours across 7 centres. Phase I
#           oncology enrols tens to low hundreds.
#
#    99999  2020-001366-11 -- ambiguous, and deliberately left so. An
#           international platform trial of COVID treatments in hospitalised
#           patients (Ministerio de Sanidad, authorised 25-03-2020), the
#           RECOVERY/SOLIDARITY shape. Those genuinely enrolled tens of
#           thousands, so five nines may be a real open-ended target. Loads
#           raw; nothing treats it specially.
#
#   114011  2023-506977-36-00 -- genuine. A pragmatic randomised trial of
#           high-dose vs standard-dose influenza vaccine in adults aged 65-79
#           across Galicia. Nothing to do about it: it is an ordinary value
#           that happens to be large, so it is noted here and nowhere else.
TOTAL_NOT_A_COUNT = frozenset({999999})

# ---------------------------------------------------------------------------
# Records excluded entirely
# ---------------------------------------------------------------------------
# End date precedes authorisation, which yields a negative duration that
# Kaplan-Meier cannot take. Four records out of 11,847, and no way to tell
# which of the two dates is wrong, so the record goes rather than a guess.
IMPOSSIBLE_DATE_STUDIES = frozenset({
    "2016-003980-21",  # authorised 2017-03-17, ends 2003-05-02
    "2012-004854-27",  # authorised 2015-10-19, ends 2015-10-15
    "2014-001255-23",  # authorised 2014-06-30, ends 2014-06-20
    "2020-005614-18",  # authorised 2021-03-04, ends 2020-06-24
})


def fold(text):
    """Casefold, strip accents, collapse whitespace, drop edge punctuation.

    The comparison form for placeholder matching. Not the sponsor identity
    rule -- that one also decodes HTML entities and is applied to values we
    keep, where this one only decides whether to discard a value.
    """
    if text is None:
        return ""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", str(text))
        if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.casefold().split()).strip(" .,;:-'´`")


def is_placeholder(text):
    """True when a value means "nothing here" rather than carrying content.

    Blank is not a placeholder -- it is already absent, and the distinction
    matters for the manifest: "the registry wrote NA" and "the registry wrote
    nothing" are different facts about the source even though both load as
    NULL.
    """
    if text is None:
        return False
    trimmed = str(text).strip()
    if not trimmed:
        return False
    folded = fold(trimmed)
    # Folded away to nothing while not blank to begin with: punctuation only.
    return True if not folded else folded in PLACEHOLDERS

# No clean_text / clean_flag / clean_total helpers here yet. They would be the
# obvious wrappers, but nothing calls them until db/transform.py is wired up in
# step 3, and a tested-but-uncalled function is still an uncalled function.
# They arrive with their caller.
