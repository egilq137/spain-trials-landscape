"""Which national hospital a REEC centre row is, when it is one at all.

REEC names its centres in four languages and several registries: `Hospital
Clinic of Barcelona` beside `Hospital Clinic de Barcelona`, `University
Hospital La Paz` beside `Hospital Universitario La Paz`. Matching those rows
against *each other* is all-pairs guesswork whose mistakes are invisible.
Matching each of them against the Catálogo Nacional de Hospitales -- 848
hospitals the state recognises, `data/geo/hospitals.csv` -- is a smaller
problem and a legible one: a row comes back carrying an official hospital
name, and a reader can see whether it is the right hospital.

**The configuration below was calibrated, not chosen.** 324 REEC rows carry a
`CODCNH` in their `referencia`, so for those the right answer is known without
any name matching, and every number in this module was measured against them
and then checked on a hand-read sample of rows that carry no code. What that
second sample changed is recorded in the comments, because both changes were
cases where the coded rows had flattered a rule that was wrong.

Nothing here merges anything. It answers "which hospital is this row", and
`geography.identities` is where that answer could later become a reason for
two rows to be one site.
"""

import collections
import csv
import re
import unicodedata

from analysis.sponsors import REVIEW_STYLE
from analysis.volume import GRID, INK, MUTED, SURFACE

Hospital = collections.namedtuple(
    "Hospital", "codcnh nombre municipio provincia cod_postal camas clase "
                "dependencia complejo")

Match = collections.namedtuple(
    "Match", "hospital closest score runner_up why")
# `hospital` is the accepted match and is None unless one was accepted;
# `closest` is the best candidate whatever the verdict, because a rejection
# a reader cannot see the near-miss for is one they cannot judge.

# Accept at 0.50, and only 0.10 clear of the runner-up.
#
# Measured on the 324 coded rows: correct picks score a median of 1.00, wrong
# picks never exceed 0.33. The gap between 0.33 and 0.50 is the headroom, and
# it matters because those rows are the *clean* population -- a threshold with
# no slack would not survive the messier ones.
#
# The margin costs nothing and guards something the coded rows do not contain:
# the catalogue holds near-name collisions in one town, Madrid's 966-bed
# Hospital Universitario La Paz beside its 99-bed Clínica Nuestra Señora de La
# Paz, and a tie between those two should be read by a person.
ACCEPT = 0.50
MARGIN = 0.10

# The same word in another language, folded onto one token. Only language
# variants and connectors belong here -- **no hospital is named in this
# table**, which is what stops it from being tuned until the evaluation
# passes. Add to it when a new spelling appears, not when a match fails.
SYNONYMS = {
    "university": "univ", "universitario": "univ", "universitaria": "univ",
    "universitari": "univ", "universitaris": "univ", "unibertsitate": "univ",
    "universidad": "univ", "universitat": "univ",
    "hospital": "hosp", "hospitals": "hosp", "hospitalari": "hosp",
    "hospitalario": "hosp", "hospitalaria": "hosp", "ospitale": "hosp",
    "clinic": "clinic", "clinico": "clinic", "clinica": "clinic",
    "clinical": "clinic", "cliniques": "clinic", "klinika": "clinic",
    "complejo": "complex", "complexo": "complex", "complex": "complex",
    "consorci": "complex", "consorcio": "complex",
    "centre": "centro", "center": "centro", "centro": "centro",
    "institut": "institut", "instituto": "institut", "institute": "institut",
    "fundacio": "fundacion", "fundacion": "fundacion",
    "fundacao": "fundacion", "foundation": "fundacion",
    "general": "general", "generals": "general",
}

# Words carrying no identity: articles, prepositions, and the legal forms a
# hospital's name sometimes drags along.
STOP = {"of", "de", "del", "d", "da", "do", "la", "el", "los", "las", "les",
        "l", "i", "y", "and", "a", "the", "en", "per", "para", "s", "sl",
        "slu", "sa", "sau", "sau"}


def fold(text):
    """Lowercase, accent-free, punctuation-free words."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", text).split()


def tokens(name):
    """The word set a name is compared on."""
    return {SYNONYMS.get(word, word) for word in fold(name)} - STOP


def similarity(one, other):
    """Shared words over all words -- the Jaccard index of the two sets.

    A *set* measure, so word order cannot matter, which is the whole reason
    it is here: `University Hospital La Paz` and `Hospital Universitario La
    Paz` are the same four words in two orders, and a character-by-character
    measure scores them 0.62 -- under any threshold worth having.

    **Containment was tried and rejected**, although it scored better on the
    coded rows. Dividing by the smaller set flatters short generic names:
    `Hospital Universitari de Bellvitge` is three tokens of which two are
    `hosp` and `univ`, so every university hospital in the province scores
    0.67 against it, and Parc Taulí in Sabadell was confidently matched to a
    hospital in L'Hospitalet. A measure that improves on the easy population
    and invents a match on the hard one is worse than the one it replaced.
    """
    left, right = tokens(one), tokens(other)
    return len(left & right) / len(left | right) if left | right else 0.0


# ---------------------------------------------------------------------------
# Hospitals whose official name shares nothing with the name REEC uses
# ---------------------------------------------------------------------------
# No string measure reaches these: the registry and the catalogue simply call
# the hospital different things. Keyed on a distinctive word of the REEC name
# -- one that no other hospital in the catalogue uses -- because REEC spells
# each of them several ways and a whole-name key would have to list them all.
#
# Every entry is one hospital, read before it was written down, and states
# why. An alias is a claim that can be wrong, so it says who is claiming it.
Alias = collections.namedtuple("Alias", "codcnh why")

ALIASES = {
    "tauli": Alias(
        "080958",
        "Parc Taulí is the name of the corporation; the catalogue lists its "
        "hospital as Hospital de Sabadell, same town and same postcode "
        "08208. No other catalogue entry contains the word."),
    "lucus": Alias(
        "270018",
        "Hospital Universitario Lucus Augusti is the Lugo complex's own "
        "name for itself; the catalogue calls it Complexo Hospitalario "
        "Universitario de Lugo, same town and same postcode 27003."),
    "anderson": Alias(
        "281113",
        "REEC writes Centro Oncológico MD Anderson International España and "
        "the catalogue Hospital MD Anderson Cáncer Center Madrid: one "
        "hospital, same postcode 28033, sharing only the founder's name."),
}


def load_hospitals(path):
    """[Hospital]. See data/geo/README.md for provenance and the licence."""
    with open(path, encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        return [Hospital(**row) for row in rows]


class Index:
    """The catalogue, arranged for looking a centre up three ways.

    Postcode, municipality and province, and **all three are searched**
    rather than the first that answers. That was the first draft's bug: REEC
    and the catalogue disagree about postcodes often enough to matter --
    Gregorio Marañón is 28009 in one and 28007 in the other, Sant Pau 08025
    and 08041 because the hospital moved campus, Ramón y Cajal 28034 and
    28001 where the catalogue looks like the wrong one -- and stopping at the
    postcode meant that whenever some *other* hospital shared it, the right
    one was never considered. Neither source is authoritative about
    postcodes, so the name decides and geography only narrows the field.
    """

    def __init__(self, hospitals):
        self.hospitals = hospitals
        self.by_postcode = collections.defaultdict(list)
        self.by_town = collections.defaultdict(list)
        self.by_province = collections.defaultdict(list)
        self.by_code = {}
        for hospital in hospitals:
            self.by_postcode[hospital.cod_postal].append(hospital)
            self.by_town[_town(hospital.municipio)].append(hospital)
            self.by_province[hospital.cod_postal[:2]].append(hospital)
            self.by_code[hospital.codcnh] = hospital

    def candidates(self, localidad, cod_postal):
        """Every hospital in the postcode, the town, or the province."""
        from analysis.geography import normalise_postcode

        code = normalise_postcode(cod_postal or "") or ""
        seen, found = set(), []
        for group in (self.by_postcode.get(code, []),
                      self.by_town.get(_town(localidad), []),
                      self.by_province.get(code[:2], [])):
            for hospital in group:
                if hospital.codcnh not in seen:
                    seen.add(hospital.codcnh)
                    found.append(hospital)
        return found


def _town(name):
    from analysis.geography import normalise_town
    return normalise_town(name or "")


def match(index, nombre, localidad, cod_postal):
    """The hospital this row is, or a Match saying why it is not decided.

    `hospital` is None on every outcome except a match, and `why` always
    says what happened, because a rejection a reader cannot interpret is
    indistinguishable from a bug.
    """
    alias = _alias_for(nombre)
    if alias is not None:
        hospital = index.by_code.get(alias.codcnh)
        if hospital is not None:
            return Match(hospital, hospital, 1.0, 0.0,
                         "alias: " + alias.why)

    candidates = index.candidates(localidad, cod_postal)
    if not candidates:
        return Match(None, None, 0.0, 0.0,
                     "no hospital shares its postcode, town or province")

    ranked = sorted(((similarity(nombre, hospital.nombre), hospital)
                     for hospital in candidates), key=lambda pair: -pair[0])
    score, best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0

    if score < ACCEPT:
        return Match(None, best, score, runner_up,
                     "best of {} candidates scores {:.2f}, under {:.2f} -- "
                     "probably not a hospital, or not in the catalogue"
                     .format(len(candidates), score, ACCEPT))
    if score - runner_up < MARGIN:
        return Match(None, best, score, runner_up,
                     "{:.2f} against {:.2f} for the next candidate is too "
                     "close to call".format(score, runner_up))
    return Match(best, best, score, runner_up,
                 "{:.2f}, next best {:.2f}".format(score, runner_up))


def _alias_for(nombre):
    words = set(fold(nombre))
    for word, alias in ALIASES.items():
        if word in words:
            return alias
    return None


def match_centres(con, index, since=None):
    """[(center_id, nombre, localidad, trials, Match)], busiest first.

    Takes a connection because the centres live in the database; the
    catalogue does not, and neither does the answer -- see the note at the
    top of data/geo/README.md about what belongs where.
    """
    from analysis.volume import COVERAGE_START

    floor = "{}-01-01".format(COVERAGE_START if since is None else since)
    rows = con.execute(
        """SELECT c.center_id, c.nombre, c.localidad, c.cod_postal,
                  count(DISTINCT s.identificador) AS trials
             FROM centers c
             LEFT JOIN study_centers sc ON sc.center_id = c.center_id
             LEFT JOIN studies s ON s.identificador = sc.study_id
                  AND s.fecha_autorizacion_aemps >= ?
         GROUP BY c.center_id""", (floor,))
    matched = [(center_id, nombre, localidad, trials,
                match(index, nombre, localidad, cod_postal))
               for center_id, nombre, localidad, cod_postal, trials in rows]
    return sorted(matched, key=lambda row: -row[3])


def review_page(matched, shown=120):
    """The page the matches get read on, in the shape of the sibling pages.

    Rejections are listed as prominently as matches, because the rule cannot
    report the hospital it failed to find and reading the refusals is the
    only way to notice one.
    """
    import html

    accepted = [row for row in matched if row[4].hospital is not None]
    rejected = [row for row in matched if row[4].hospital is None]
    trials = sum(row[3] for row in matched) or 1

    def rows_for(group, limit):
        out = []
        for center_id, nombre, localidad, count, result in group[:limit]:
            shown_hospital = result.hospital or result.closest
            official = shown_hospital.nombre if shown_hospital else "—"
            code = shown_hospital.codcnh if shown_hospital else ""
            out.append(
                "<tr><td>{}</td><td>{}</td><td class='n'>{:,}</td>"
                "<td>{}</td><td class='tag'>{}</td></tr>".format(
                    html.escape(nombre), html.escape(localidad or "—"),
                    count,
                    "{} {}".format(code, html.escape(official)).strip(),
                    html.escape(result.why)))
        return "".join(out)

    return "\n".join([
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<title>Hospital matches</title><style>",
        REVIEW_STYLE.format(surface=SURFACE, ink=INK, muted=MUTED, grid=GRID),
        "</style></head><body>",
        "<h1>Hospital matches</h1>",
        "<p>Every REEC centre against the Catálogo Nacional de Hospitales. "
        "Generated by <code>run_analysis.py</code>. Origen de los datos: "
        "Ministerio de Sanidad, Consumo y Bienestar Social; data updated "
        "31 December 2024.</p>",
        "<p><strong>Nothing here merges anything.</strong> A match says "
        "which hospital a row is, and only that.</p>",
        "<h2>{:,} matched, carrying {:.0f}% of the trial-site links</h2>"
        .format(len(accepted),
                100 * sum(row[3] for row in accepted) / trials),
        "<p>Read the score: 1.00 is the same words in another order or "
        "another language. Anything near the 0.50 floor is worth an eye.</p>",
        "<table><thead><tr><th>REEC centre</th><th>Town</th>"
        "<th class='n'>Trials</th><th>Matched to</th><th>Why</th></tr>"
        "</thead><tbody>", rows_for(accepted, shown), "</tbody></table>",
        "<h2>{:,} sent to review, carrying {:.0f}%</h2>".format(
            len(rejected), 100 * sum(row[3] for row in rejected) / trials),
        "<p>These should be research institutes, health centres and clinics "
        "the catalogue does not list -- it is a catalogue of hospitals. "
        "<strong>A hospital in this table is a miss</strong>, and the fix is "
        "either a spelling the synonym table has not met or a line in "
        "<code>ALIASES</code>.</p>",
        "<table><thead><tr><th>REEC centre</th><th>Town</th>"
        "<th class='n'>Trials</th><th>Closest</th><th>Why</th></tr>"
        "</thead><tbody>", rows_for(rejected, shown), "</tbody></table>",
        "</body></html>"])
