"""Every rule that changes a value between the raw cache and the database.

Rules live here as **data**, not as logic buried in the loader, for three
reasons: this file reads as the answer to "what do we change from the raw
data?"; `git diff` on it is the changelog, so a new rule is a visible dated
line rather than an edit inside a function; and each rule can be tested
against the count that justified it, so a refresh that changes the data
underneath fails loudly instead of silently.

`data/raw/` is never rewritten, so it stays the provenance record — the
database therefore does not carry shadow columns holding the original values.
The rules plus the tally in db/cleaning_rules_tally.py are enough to get back
to any raw value.

Counts in comments are measured over all 11,847 cached studies. The
corpus-backed tests in tests/test_cleaning_rules.py re-check them when the
cache is present.

Placeholders, sentinels, administration routes, and name normalisation.
Postcode repair is here too, though it is the one rule that cannot be a pure
function of a single value -- it has to consult the rest of the corpus, so its
evidence is built by a pass in the loader and passed in. The corpus-wide
resolutions that need the same treatment live in db/centers.py, and the tally
that counts every rule's applications in db/cleaning_rules_tally.py.
"""

import collections
import html
import re
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
#   acronimo               4,765 of 6,574 non-blank   (NA alone 4,744)
#   funders.nombre           596 across the corpus      (NA alone   572)
#   substances               520 across the corpus      -- the field the
#                                 absence statements below were found in
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
    # Absence STATEMENTS, almost all of them in `sustancias`: 107 mentions
    # across 16 spellings. A trial can be authorised before its drug has an
    # INN -- an International Nonproprietary Name, the generic name a
    # substance is known by -- so the registry writes a sentence saying so
    # where the name will eventually go. 'not yet available' is the most
    # common substance value after the real drugs.
    #
    # Enumerated, like everything above, and the reason is right here in the
    # candidates: a pattern matching "available" would also delete `Best
    # Available Treatment`, which is a real comparator arm, and one matching
    # short strings would delete PRGF, 5-FU, IL-2, BCG, RUTI and V160, which
    # are real substances.
    #
    # Each was checked against every field is_placeholder is applied to, not
    # just the one that prompted it. 'tbc' is the one to re-check on a
    # refresh: here it appears only in `sustancias`, where it means "to be
    # confirmed", but TBC is also the Spanish abbreviation for tuberculosis
    # and would be a real value in a field naming a condition.
    "not yet available",
    "not available yet",
    "not yet availble",
    "not available or proposed",
    "not available yet/no disponible todavia",
    "no disponible",
    "no inn available",
    "inn not available",
    "inn not available yet",
    "none available",
    "unavailable",
    "unknown",
    "not aplicable",
    "sin asignar",
    "tbc",
    "tbd",
    # The same thing said 29 more ways, 413 further mentions, almost all of
    # them substances. Found by reading the frequency list rather than by
    # pattern -- 'Not Applicable' (115) and 'Not yet assigned' (90) sat in the
    # top eight substances, above most real drugs, and an English-versus-
    # Spanish blind spot in the first sweep had missed both.
    #
    # The candidate net that found them is also the argument for enumerating:
    # matching "none" catches finerenone, eplerenone and drospirenone;
    # matching "nan" catches nanocolloid and every recombinant protein. Both
    # would have deleted real drugs.
    "not applicable",
    "notapplicable",
    "not applicable yet",
    "not yet applicable",
    "not applicable at this stage",
    "not yet assigned",
    "not assigned",
    "not assigned yet",
    "inn not yet assigned",
    "inn name not yet assigned",
    "inn name not assigned yet",
    "no inn assigned",
    "no inn assigned yet",
    "not yet defined",
    "not yet established",
    "not established yet",
    "not yet requested",
    "inn not yet proposed",
    "inn not yet proposed see d.3.9.3",
    "not yet known",
    "not know yet",
    "not yet",
    "none yet",
    "none at this time",
    "none registered",
    "to be determined",
    "no",
    # `fold` strips edge punctuation but not these two, so they survive as
    # values naming nothing.
    "_",
    "/",
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
# nothing else. Re-checked on refresh by tests/test_cleaning_rules.py, not assumed.
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
    matters for the tally: "the registry wrote NA" and "the registry wrote
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

def clean_flag(value):
    """-1 -> None. Everything else through unchanged.

    Applied after db.transform.flag has done the structural conversion, so an
    unexpected value is still passed to the schema rather than nulled here.
    """
    return None if value == FLAG_UNKNOWN else value


def clean_total(value):
    """0 and 999999 -> None. Everything else through unchanged.

    Two different reasons, one result: 0 is the registry's "not reported"
    (2,201 records) and 999999 is a placeholder in a phase I study that cannot
    have enrolled it. 99999 is deliberately NOT here -- see TOTAL_NOT_A_COUNT.
    """
    if value == TOTAL_UNKNOWN or value in TOTAL_NOT_A_COUNT:
        return None
    return value


# ---------------------------------------------------------------------------
# Names — markup, invisible characters, spacing, and the identity key
# ---------------------------------------------------------------------------
# Two functions, because a name is used for two different things and the two
# rules are not the same one applied twice.
#
#   clean_text  the form that is STORED and shown. Reverses damage only:
#               markup that was never meant to be read, characters that cannot
#               be seen, spacing nobody chose. Case, accents and punctuation
#               are content and survive.
#   match_key   the form that decides IDENTITY. Destroys information on
#               purpose -- case, accents, edge punctuation, apostrophe style --
#               so two spellings of one organisation land on one row.
#
# Storing only the key would put `astrazeneca ab` on the dashboard; storing
# only the cleaned text cannot enforce identity. `sponsors` therefore keeps
# both columns (PROJECT_SPEC 3.2c).

# Entity encoding is present across the corpus and is not cosmetic:
#
#   sponsors.nombre      554 occurrences,  25 distinct values
#   centers.nombre     1,130 occurrences, 179 distinct values
#   centers.localidad    103 occurrences,  44 distinct values
#   centers.cod_postal     1 occurrence  (a byte-order mark, see pad_postcode)
#
# It changes what the display column must be. PROJECT_SPEC originally said
# `promotor` holds "the most frequent raw spelling" -- but the most frequent
# raw spelling of the largest sponsor is `Merck Sharp &amp; Dohme LLC` (150),
# ahead of the correct `Merck Sharp & Dohme LLC` (55). Taking the raw mode
# would ship markup to the dashboard, so display means most frequent *cleaned*
# spelling.
#
# Ten centre names are escaped TWICE -- `Institut Catala D&amp;#39;oncologia`
# needs one pass to reach `D&#39;oncologia` and a second to reach `D'oncologia`
# -- so decoding repeats to a fixed point. The cap exists because
# `html.unescape` is not guaranteed to terminate on adversarial input and a
# loader should not hang on one bad row; three passes is one more than the
# corpus needs.
UNESCAPE_PASSES = 3

# Apostrophe styles, unified for matching only. Catalan and Valencian centre
# names are full of elisions -- `Vall d'Hebron`, `L'Hospitalet`, `Institut
# Català d'Oncologia` -- and the registry writes them with three different
# characters. U+00B4 ACUTE ACCENT is the awkward one: it is a standalone
# character, not a combining mark, so NFD leaves it in place and case-folding
# cannot merge `d'hebron` with `d´hebron`. Merges 5 further centre names and 3
# localities on top of what fold already does. Not applied to clean_text: which
# apostrophe the registry typed is not damage.
APOSTROPHES = "'‘’´`ʼ"


def clean_text(text):
    """Decode markup, drop invisible characters, collapse spacing.

    Blank becomes None so a NOT NULL constraint catches it rather than an
    empty-string row being created. Placeholders are NOT handled here: whether
    'NA' should become NULL is is_placeholder's decision, and keeping the two
    apart lets the tally count them separately.
    """
    if text is None:
        return None
    decoded = str(text)
    for _ in range(UNESCAPE_PASSES):
        nxt = html.unescape(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    # Category Cf is "format": zero-width joiners, direction marks, and the
    # byte-order mark that arrived inside one postcode. Invisible, but they
    # split otherwise identical values into two rows.
    visible = "".join(c for c in decoded if unicodedata.category(c) != "Cf")
    return " ".join(visible.split()) or None


# Punctuation is style wherever it sits, not only at the ends of a value.
# `fold` strips it at the edges, which left `Novartis Farmacéutica, S.A.` and
# `Novartis Farmacéutica S.A.` as two sponsors over one comma. Replacing it
# with a space rather than deleting it keeps `Merck & Co.,Inc` from becoming
# `merck & coinc`: the punctuation was doing a separator's job.
#
# Measured over the corpus before this was adopted: it merges 249 sponsor rows
# across 211 groups, 125 funder rows and 4 substances, and every one of those
# groups differs ONLY by punctuation, spacing or accent style -- checked by
# comparing the letters of the merged names, not assumed. It also merges the
# two most frequent centre names in the source, which 3.2c had already
# identified as one hospital: HOSPITAL UNIVERSITARI VALL D'HEBRON (2,667) and
# Hospital Universitari Vall D Hebron (1,553).
IDENTITY_PUNCTUATION = ".,;:()[]{}\"/\\!¡?¿" + APOSTROPHES

# Removing the dots from `S.A.` leaves `s a`, where the same abbreviation
# written without them leaves `sa`. So the letters of an abbreviation are
# closed back up: a run of single characters becomes one token. Measured over
# every sponsor and funder name, this merges 58 further identities, and not
# one of them differs by anything except dots and spacing.
INITIALS = re.compile(r"\b(?:[a-z0-9] )+[a-z0-9]\b")

# And having got that far, the space itself is style too. `Astra Zeneca` and
# `AstraZeneca` are one company; so are `Pharma Mar` and `PharmaMar`,
# `Geiser Pharma` and `GeiserPharma`, `AB Science` and `ABScience`, `World
# Antidoping Agency` and `World Anti Doping Agency`. The registry also writes
# `Boehringer Ingelhei m España` with a space inside a word, and `BTI
# Biotechnology Institute I mas D` for `IMASD` -- Spanish `I+D`, spelled out.
#
# Checked the way the others were: 15 sponsor groups and 13 funder groups
# merge, and every one is a single organisation. Substances merge 3, all of
# them spacing inside a formula (`CD34+CELLS` / `CD34+ CELLS`).
#
# The key stops being readable -- `astrazenecaab` -- which is fine, because it
# is compared and never shown. The display column is what a reader sees.
SPACES = re.compile(r"\s+")


def _spaced_key(text):
    """The identity form with its spaces still in.

    Only `organisation_key` needs this: its clause markers are phrases, so the
    cut has to happen while there are still word boundaries to cut at.
    """
    cleaned = clean_text(text)
    if cleaned is None:
        return None
    spaced = "".join(" " if c in IDENTITY_PUNCTUATION else c for c in cleaned)
    return fold(spaced) or None


def match_key(text):
    """The identity form: cleaned, punctuation and spacing removed, folded.

    Over the corpus: 3,245 distinct cleaned centre names collapse to 2,520
    identities, and 4,244 substance spellings to 3,305. Sponsors and funders
    go through `organisation_key` below, which adds one more cut.

    Safe to automate because it only removes case, accents, spacing, markup and
    punctuation style. Two genuinely different organisations would have to be
    identical letter for letter to collide. This is emphatically NOT entity
    resolution -- `Novartis Farmacéutica, S.A.` and `Novartis Pharma AG` are
    different legal entities and stay different rows (PROJECT_SPEC 3.2c), and
    so do `F. Hoffmann-La Roche AG` and `F. Hoffmann-La Roche Ltd`, which is
    why the legal form itself is never stripped here.
    """
    key = _spaced_key(text)
    return SPACES.sub("", key) or None if key is not None else None


# Phrases that turn an organisation's name into a sentence about it. Counted
# in the corpus rather than imagined -- 98 sponsor and funder values carry one,
# covering 299 trials:
#
#   subsidiary of 74   que realiza 38   como representante 36   actua como 38
#   que actua 31       representante de 23   en nombre de 12    filial de 1
#
# The registry is describing a relationship, not naming a different company:
#
#   Roche Farma S.A (Soc.Unipersonal) que realiza el ensayo en España y que
#   actúa como representante de F.Hoffmann-La Roche Ltd
#
# Two such values differ by whichever words the writer chose that day, so they
# split one sponsor into as many rows as there are phrasings. Cutting at the
# first marker leaves the name, which is the part that identifies anyone.
#
# NOT the same as stripping the legal form, which is the next thing anyone
# reaches for and is wrong: it merges Roche AG with Roche Ltd and Novartis
# Pharma AG with GmbH, which are different companies. The clause is commentary;
# the legal form is part of the name.
ORGANISATION_CLAUSES = (
    "que realiza",
    "que actua",
    "actua como",
    "actuando como",
    "como representante",
    "representante de",
    "en representacion de",
    "que representa",
    "representado en espana por",
    "realizado en espana por",
    "por delegacion de",
    "por encargo de",
    "en nombre de",
    # 'care of'. `Genentech Inc. c/o F. Hoffmann-La Roche Ltd` names Genentech
    # and then says who to reach them through -- the same shape as `que
    # representa en España a`, not an address. 27 mentions across Genentech,
    # BeiGene and Kiniksa.
    "c/o",
    "c o ",
    "por cuenta de",
    "en calidad de",
    "a subsidiary of",
    "subsidiary of",
    "filial de",
    "on behalf of",
    "de aqui en adelante",
)


# A postal address tacked onto a company name. `Pfizer Inc., 235 East 42nd
# Street, New York, NY 10017` appears in 15 spellings over 85 mentions, all of
# them the same company as the plain `Pfizer Inc.` -- the address is what
# splits them, since no two writers punctuate a street the same way.
#
# The street word must be preceded by a NUMBER, which is what makes this safe:
# `Duke Street Bio Limited` is a real company name containing "Street" and
# must survive. Matching the word `calle` on its own would be worse still --
# it is inside `Calleja` and `Calles`, which are surnames, and two sponsors
# here are people.
ADDRESS = re.compile(
    r"[,\s]\s*\d+[a-z]*\s+(?:[\w'’.-]+\s+){0,3}"
    r"(street|st\b|road|rd\b|avenue|ave\b|boulevard|blvd\b|drive|lane|"
    r"calle|avenida|avda|paseo|carrer|via)\b")


def organisation_key(text):
    """`match_key`, with any descriptive clause cut off the end.

    For sponsors and funders only. A centre or a substance is not described
    this way, and the markers are Spanish and English organisational language
    that has no business deciding whether two hospitals are the same site.

    A trailing postal address is cut the same way and for the same reason: it
    describes where the company is rather than who it is, and no two writers
    punctuate a street identically.

    Both are cut at the EARLIEST marker, and only when something is left in
    front of it -- a value that begins with one names nobody and is left alone
    for the schema to refuse.
    """
    key = _spaced_key(text)
    if key is None:
        return None
    cuts = [key.find(marker) for marker in ORGANISATION_CLAUSES]
    address = ADDRESS.search(key)
    if address and address.start() > 0:
        cuts.append(address.start())
    earliest = min((c for c in cuts if c > 0), default=None)
    if earliest is not None:
        key = key[:earliest].strip() or key
    return SPACES.sub("", key) or None


# ---------------------------------------------------------------------------
# Administration routes
# ---------------------------------------------------------------------------
# 129 distinct values over 17,268 intervention records, for perhaps 35 real
# routes. Two separate problems, so two maps: one that decides what a value
# *is*, and one that decides what bucket it counts in.
#
# The field only exists from 2022 onward -- it replaced `sustancias` at the
# CTIS transition and the two never co-occur -- so any route analysis is
# confined to that side of the break.

# Both route maps are keyed on `route_key`, NOT on `fold` alone. The
# difference is one value and it was a real bug: the corpus sends
# 'INFUSI&Oacute;N INTRAVENOSA' 20 times, and an earlier version of this map
# keyed it as the entity text on the reasoning that nothing decoded it. The
# loader does decode it -- clean_text runs on every stored value -- so the
# entry matched nothing and 20 rows fell through as a 54th route. Keeping the
# lookup and its corpus tests on one normalisation is what makes the
# no-fallthrough test able to see that; folding the raw value here while the
# loader cleans it first meant the test and the pipeline asked different
# questions.
def route_key(raw):
    """The form both route maps are keyed on: cleaned, then folded."""
    return fold(clean_text(raw))


# Values that name no route. Not the same as absent: the registry wrote
# something, and what it wrote was "we do not know" or "does not apply".
ROUTE_NOT_A_ROUTE = frozenset({
    "unknown use",                             # 149
    "other use",                               # 129
    "route of administration not applicable",  # 19
    "new",                                     # 1
    "spc",                                     # 1  (summary of product characteristics)
})

# Folded raw value -> canonical route. Merges phrasing (`oral` / `oral use`),
# real misspellings, and dosage forms that name their route unambiguously.
#
# Inferences are marked, because they are the entries most likely to be wrong:
#   * bare `infusion` and `solution for infusion` are read as intravenous,
#     which is what infusion means in practice but is not what the field says
#   * `intravascular` and `subdermal` are read as their common equivalents
#   * `solution for injection` names a form, not a route, so it becomes
#     "injection, route unspecified" rather than being guessed at
ROUTE_CANONICAL = {
    # --- oral and other enteral --------------------------------------------
    "oral": "oral",
    "oral use": "oral",
    "in drinking water use": "oral",
    "sublingual use": "sublingual",
    "buccal use": "buccal",
    "oromucosal use": "oromucosal",
    "enteral feeding tube": "enteral",
    "oral, nasogastric tube or percutaneous endoscopic gastrostomy tube use": "enteral",
    # --- intravenous --------------------------------------------------------
    "intravenous": "intravenous",
    "intravenous use": "intravenous",
    "intravenous infusion": "intravenous",
    "intravenous administration": "intravenous",
    "intravenous injection": "intravenous",
    "intravenous perfusion use": "intravenous",
    "intravenous drip use": "intravenous",
    "intravenous drip": "intravenous",
    "intravenous bolus use": "intravenous",
    "intravenous slow bolus injection": "intravenous",
    "direct intravenous injection": "intravenous",
    "iv infusion": "intravenous",
    "solution for intravenous infusion": "intravenous",
    "infusion intravenosa": "intravenous",           # 20 rows, entity-encoded
    "intravenious infusion": "intravenous",          # misspelling, 466 rows
    "intravenus use": "intravenous",                 # misspelling, 51 rows
    "infusion": "intravenous",                       # INFERRED
    "solution for infusion": "intravenous",          # INFERRED
    "concentrate for solution for infusion": "intravenous",  # INFERRED
    "intravascular use": "intravenous",              # INFERRED
    # Same route written twice, so not actually compound.
    "intravenous bolus injection/iv infusion": "intravenous",
    "iv injection, iv infusion": "intravenous",
    # --- subcutaneous -------------------------------------------------------
    "subcutaneous": "subcutaneous",
    "subcutaneous use": "subcutaneous",
    "subcutaneous injection": "subcutaneous",
    "subdermal use": "subcutaneous",                 # INFERRED
    # --- intramuscular ------------------------------------------------------
    "intramuscular": "intramuscular",
    "intramuscular use": "intramuscular",
    "intramuscular injection": "intramuscular",
    # --- respiratory --------------------------------------------------------
    "inhalation": "inhalation",
    "inhalation use": "inhalation",
    "inhalation gas": "inhalation",
    "inhalational route": "inhalation",
    "nasal use": "nasal",
    "nasal spray": "nasal",
    "intranasal use": "nasal",
    "intratracheal use": "intratracheal",
    "endotracheopulmonary use": "intratracheal",
    # --- skin and surface ---------------------------------------------------
    "topical": "topical",
    "topical use": "topical",
    "topical application": "topical",
    "topical administration": "topical",
    "topical application on wound": "topical",
    "cutaneous": "cutaneous",
    "cutaneous use": "cutaneous",
    "transdermal use": "transdermal",
    "percutaneous use": "percutaneous",
    "intradermal": "intradermal",
    "intradermal injection": "intradermal",
    "intraepidermal use": "intradermal",
    # --- eye ----------------------------------------------------------------
    "ocular": "ocular",
    "ocular use": "ocular",
    "ophthalmic": "ocular",
    "ophthalmic use": "ocular",
    "eye/ear/nose drops": "ocular",
    "conjunctival use": "conjunctival",
    "subconjunctival use": "conjunctival",
    "intravitreal use": "intravitreal",
    "subretinal use": "subretinal",
    "suprachoroidal": "suprachoroidal",
    "intracameral use": "intracameral",
    "retrobulbar use": "retrobulbar",
    # --- central nervous system --------------------------------------------
    "intrathecal": "intrathecal",
    "intrathecal use": "intrathecal",
    "i.t. bolus injection to the intrathecal space": "intrathecal",
    "intracisternal use": "intracisternal",
    "cisterna magna puncture (icm)": "intracisternal",
    "intracerebroventricular (icv)": "intracerebroventricular",
    "intraventricular use": "intracerebroventricular",
    "intracerebral use": "intracerebral",
    "epidural use": "epidural",
    "perineural use": "perineural",
    # --- other targeted -----------------------------------------------------
    "intratumoral": "intratumoral",
    "intratumoral use": "intratumoral",
    "peritumoral use": "peritumoral",
    "intralesional use": "intralesional",
    "intravesical use": "intravesical",
    "intraperitoneal use": "intraperitoneal",
    "intraarterial use": "intraarterial",
    "intracoronary use": "intracoronary",
    "antegrade epicardial coronary artery infusion": "intracoronary",
    "intra-articular injection": "intraarticular",
    "intraarticular use": "intraarticular",
    "intraosseous use": "intraosseous",
    "intrabursal use": "intrabursal",
    "intralymphatic use": "intralymphatic",
    "intraamniotic use": "intraamniotic",
    "intracochlear": "intracochlear",
    "intracochlear injection": "intracochlear",
    "auricular use": "auricular",
    "dental use": "dental",
    "vaginal use": "vaginal",
    "rectal use": "rectal",
    "extracorporeal use": "extracorporeal",
    "implantation": "implantation",
    "transplantation": "transplantation",
    "infiltration": "infiltration",
    "local injection": "infiltration",
    # --- names a route, but not which one -----------------------------------
    "injection": "injection, route unspecified",
    "solution for injection": "injection, route unspecified",
    "injectable solution": "injection, route unspecified",
    "solution for injection in pre-filled syringe": "injection, route unspecified",
    "parenteral": "parenteral, route unspecified",
    "parenteral use": "parenteral, route unspecified",
    # --- names more than one route ------------------------------------------
    # interventions carries a single route_id, so these cannot be split without
    # a bridge the rest of the data does not justify -- 256 rows of 17,268.
    # They get a canonical value that says so, rather than being forced into
    # whichever route happens to be written first.
    "oral and iv": "multiple routes",
    "intravenous use and oral use": "multiple routes",
    "intravenous (iv) or subcutaneous (sc)": "multiple routes",
    "subcutaneous and intravenous use": "multiple routes",
    "subcutaneous or intravenous": "multiple routes",
    "intramuscular or subcutaneous": "multiple routes",
    "intramuscular or intravenous": "multiple routes",
    "intravenous/subcutaneous/intramuscular": "multiple routes",
    "intravenous, intra-arterial, intrathecal use": "multiple routes",
    "intravenous injection/infusion, intramuscular injection": "multiple routes",
    "solution for injection or infusion": "multiple routes",
    "infiltration, perineural use": "multiple routes",
}

# No coarse grouping here. An earlier draft added a four-bucket
# oral/intravenous/subcutaneous/other map plus a `grupo` column; it is gone.
# The 53 canonical routes above ARE the grouping, and they are as far as this
# module can go without judgement: merging `oral use` into `oral` is
# mechanical, but deciding that intramuscular counts as "other" is a choice
# about what a question is asking. Same line as sponsor entity resolution --
# normalisation here, classification in `analysis/`, where it can be stated
# and varied per question rather than frozen in a column.


# ---------------------------------------------------------------------------
# Postcodes
# ---------------------------------------------------------------------------
# Spanish postcodes are always 5 digits, the first two being the province. 290
# of 85,163 non-blank entries are 4 digits, so one digit is missing.
#
# WHICH digit is missing is the whole question, and an earlier version of this
# module got it wrong. It assumed the leading zero, zero-padded, and defended
# that with "every padded value lands in provinces 01-09, exactly the ones
# whose postcodes start with a zero" -- which is no evidence at all, because
# zero-padding always produces a 0X prefix whatever digit was really lost.
# Deleting any digit of Madrid's 28046 also yields a four-digit value.
#
# So the value is triangulated from the rest of the row instead of assumed,
# using evidence in descending order of strength. A candidate is any 5-digit
# code that becomes the observed value when one digit is deleted -- 46 of them
# for a typical value, before any filtering.
#
#   tier 1  the SAME CENTRE reports a candidate elsewhere in the corpus    226
#   tier 2  the same LOCALITY reports a candidate                           47
#   tier 3  no candidate seen, but the zero-padded value's province is one   10
#           the locality uses -- confirms the province, not the full code
#   --      no evidence, or the province is contradicted: left raw            7
#
# Triangulation agrees with blind zero-padding on 282 of the 283 it resolves,
# so the old rule was mostly right -- but it was right by luck, and the one
# disagreement is the proof: '1108' in Cádiz is not '01108' (Álava) but
# '11008', which is a code that locality actually uses. Zero-padding would
# have moved a Cádiz clinic to Álava.
#
# This also deletes a hand-maintained exception list. The previous version
# enumerated ('1108','cadiz') and ('3016','murcia') as "not lost zeros" after
# I found them by eye; both now fall out of the evidence -- the first resolved
# to the right answer, the second left raw because Murcia uses 30xxx and
# padding would have claimed Alicante.
#
# Malformed in other ways and deliberately left raw, 11 entries: '08006.',
# '28.223', '46014,', '3584 AE' (a Dutch postcode), '48993 Vizc', 'Madrid',
# 'Coruña, A'. Too few and too varied for a rule; the schema's CHECK names
# them. One more, '&#65279;09', is a byte-order mark glued to two digits;
# clean_text removes the mark and what is left is still not a postcode.
#
# ARCHITECTURE: unlike every other rule in this file, this one cannot be a
# pure function of one value -- it needs to have read the whole corpus first.
# That is why the evidence is built by a separate pass and PASSED IN rather
# than imported from a module global: `resolve_postcode` stays pure given its
# arguments, so it can be tested on a handful of hand-written rows instead of
# on 85,410 real ones. It is also why postcode repair belongs with the other
# corpus-wide resolutions in the loader (step 6), not with the pure rules.
POSTCODE_LENGTH = 5

PostcodeEvidence = collections.namedtuple(
    "PostcodeEvidence", "by_centre by_locality prefixes")

Resolution = collections.namedtuple("Resolution", "postcode basis")


def postcode_candidates(four):
    """Every 5-digit code that becomes `four` when one digit is deleted."""
    out = set()
    for position in range(POSTCODE_LENGTH):
        for digit in "0123456789":
            candidate = four[:position] + digit + four[position:]
            if candidate[:position] + candidate[position + 1:] == four:
                out.add(candidate)
    return out


def build_postcode_evidence(entries):
    """Index the valid postcodes in the corpus, for resolving the broken ones.

    `entries` is an iterable of (postcode, centre_key, locality). Only 5-digit
    numeric postcodes contribute -- the broken ones are what we are resolving,
    so they cannot vote on the answer.

    `centre_key` must NOT include the postcode, and MUST include the locality.
    The centre key defined in PROJECT_SPEC 3.2c is (reference-or-name,
    locality, postcode), and both halves of that matter here: keeping the
    postcode would put a centre's broken row in a different group from its good
    ones and hide the best evidence there is, while dropping the locality would
    let Clínica Universidad de Navarra's Pamplona and Madrid campuses vote on
    each other's postcodes -- the same merge the site-level key exists to
    prevent. Getting this wrong is not a crash: it silently moves 16 rows from
    one tier to another.
    """
    evidence = PostcodeEvidence(
        collections.defaultdict(collections.Counter),
        collections.defaultdict(collections.Counter),
        collections.defaultdict(collections.Counter))
    for postcode, centre_key, locality in entries:
        text = clean_text(postcode)
        if not (text and text.isdigit() and len(text) == POSTCODE_LENGTH):
            continue
        evidence.by_centre[centre_key][text] += 1
        evidence.by_locality[fold(locality)][text] += 1
        evidence.prefixes[fold(locality)][text[:2]] += 1
    return evidence


def resolve_postcode(raw, centre_key, locality, evidence):
    """Recover a 4-digit postcode from the rest of the corpus.

    Returns a Resolution: the postcode, and which tier of evidence produced it,
    so the cleaning-rules tally can report how each row was settled rather than only
    that something changed. `basis` is None when nothing was changed.

    Anything that is not exactly four digits passes through unchanged -- the
    11 otherwise-malformed entries are left for the schema to reject.
    """
    text = clean_text(raw)
    if text is None:
        return Resolution(None, None)
    if not (text.isdigit() and len(text) == POSTCODE_LENGTH - 1):
        return Resolution(text, None)

    candidates = postcode_candidates(text)
    key = fold(locality)

    for basis, counts in (("same centre", evidence.by_centre.get(centre_key)),
                          ("same locality", evidence.by_locality.get(key))):
        seen = {code: n for code, n in (counts or {}).items()
                if code in candidates}
        if not seen:
            continue
        # Ties are not resolved. '1108' in Cádiz sees 11008 seven times and
        # 11408 five, and the majority is taken -- but a genuine tie is two
        # equally good answers, and picking one would be the same mistake as
        # assuming the leading zero.
        ranked = sorted(seen.items(), key=lambda item: -item[1])
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return Resolution(text, None)
        return Resolution(ranked[0][0], basis)

    # Tier 3: no candidate observed anywhere. Fall back to the leading zero,
    # but only where the locality's own postcodes agree it is that province.
    padded = text.zfill(POSTCODE_LENGTH)
    prefixes = evidence.prefixes.get(key)
    if prefixes and padded[:2] in prefixes:
        return Resolution(padded, "province agrees")
    return Resolution(text, None)
