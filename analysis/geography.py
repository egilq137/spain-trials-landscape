"""Where trials happen: participation by region and by province.

**The map measures participation, not ownership.** A trial runs at many sites
in many regions -- 45,319 (trial, region) pairs over 11,653 located trials,
about 3.9 regions each, and only 19.5% of trials run in a single region. So a
place's number is "trials with at least one site here", and the numbers sum
to far more than the corpus. Cataluña taking part in 79% of Spanish trials is
a statement about participation; nothing here says a trial *belongs* to a
region, and REEC records nothing that would.

**Two grains, and the province one is where the errors bite.**
`centers.ccaa` is a clean vocabulary of 19 values matching Eurostat's NUTS
level 2 one for one. `centers.provincia` is a clean vocabulary of 52 with
wrong assignments in it (CENTER_CORRECTIONS below). At region grain the whole
correction table moves **one trial**: Murcia 960 to 959, Comunitat Valenciana
5,181 to 5,182. Every other corrected centre belongs to a trial that already
had a site in the right region, so the region was counted anyway -- multi-site
participation absorbs per-centre error. At province grain there is less to
absorb it, because a trial with sites in nine regions may still have only one
site in Girona.

**What is not on the maps.** 181 studies from 2013 have no located centre: 149
report no centre at all and 32 report only centres whose place REEC never
recorded. They are counted in the denominator and named in the subtitle, not
quietly dropped -- a map would otherwise imply a coverage it does not have.
"""

import collections
import csv
import json
import unicodedata

from db import cleaning_rules
from analysis.sponsors import REVIEW_STYLE
from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SERIES, SURFACE


def _first_of(year):
    """January 1st of `year`, as the stored ISO text. See volume.january_first
    for why the comparison is against a date rather than a substring."""
    return "{}-01-01".format(year)

# ---------------------------------------------------------------------------
# The seven centres whose province disagrees with their postcode
# ---------------------------------------------------------------------------
# Found by asking which centres disagree with the majority province of every
# centre sharing their postcode prefix: 7 of the 3,006 that have both a
# well-formed postcode and a province. The schema comment on centers.provincia
# used to say to derive the province from the postcode prefix instead. Reading
# the seven says otherwise -- **in three of them the postcode is the wrong
# field, not the province** -- so that rule would have fixed four rows and
# broken three, one of them worth 193 trials.
#
# The locality is what settles every case. It agrees with the name in all
# seven, and with the majority of sibling rows at the same postcode.
#
# Keyed on (center_key, localidad, cod_postal), the schema's UNIQUE, because
# center_id is a rowid handed out at load time and would point at a different
# centre after any change to load order.
Correction = collections.namedtuple("Correction", "provincia ccaa why")

CENTER_CORRECTIONS = {
    ("clinicaoftalmologicavissumalicante", "Alicante", "03016"): Correction(
        "ALICANTE", "COMUNITAT VALENCIANA",
        "Name, locality and postcode all say Alicante; 12 other centres at "
        "03016 say Alicante. VISSUM runs clinics in both provinces and this "
        "entry took the wrong one."),
    ("121351", "ÁVILA RURAL", "05003"): Correction(
        "AVILA", "CASTILLA Y LEÓN",
        "The site is called ÁVILA RURAL and sits at an Ávila postcode. Two "
        "sibling rows at 05003 say Ávila."),
    ("ORL-000011379", "Sant Joan Despí", "08970"): Correction(
        "BARCELONA", "CATALUÑA",
        "Sant Joan Despí is in Barcelona; 9 other centres at 08970 say so. "
        "The row is wrong twice over -- it files Burgos under "
        "Castilla-La Mancha, and Burgos is in Castilla y León."),
    ("ORG-100050057", "Santa Cruz de Tenerife", "38001"): Correction(
        "STA. CRUZ DE TENERIFE", "CANARIAS",
        "Locality and postcode agree on Tenerife; two sibling rows at 38001 "
        "say Santa Cruz."),
    # The next two have the right province already: what is missing is the
    # region, which REEC never sent. Their postcode is the wrong field.
    ("institutonacionaldeneurocienciasaplicadas", "Barcelona", "28006"):
        Correction(
            "BARCELONA", "CATALUÑA",
            "Name, locality and province all say Barcelona. 28006 is a Madrid "
            "postcode and is the odd field out; only the region was missing."),
    ("nuevastecnologiasendiabetesyendocrinologia", "Sevilla", "31003"):
        Correction(
            "SEVILLA", "ANDALUCÍA",
            "Locality and province agree on Sevilla. 31003 is Pamplona; the "
            "centre has no sibling rows to vote with it, and the postcode is "
            "the only field disagreeing."),
}

# The seventh. Read, and deliberately left alone -- enumerated here so the
# next person to run the disagreement query does not have to work it out
# again. Institut Català d'Oncologia reports Badalona, L'Hospitalet and
# Girona under one registry reference (see the centers DDL); the Girona
# campus carries L'Hospitalet's postcode, 08908. Province GERONA is right,
# the postcode is wrong, and both are in Cataluña, so nothing on a regional
# map moves. On the province map it is 193 trials, and it is the whole
# argument against the postcode rule.
CHECKED_UNCHANGED = {("ORG-100030394", "Girona", "08908")}

# ---------------------------------------------------------------------------
# REEC's place names to the codes the geometry is drawn with
# ---------------------------------------------------------------------------
# Spain's autonomous communities are exactly NUTS level 2, so this is a
# renaming and not a reclassification: 19 to 19, no region split or merged.
# REEC writes INE's inverted forms ('MADRID, COMUNIDAD DE'); the geometry is
# keyed by code, so the spelling is confined to this table.
NUTS = {
    "ANDALUCÍA": "ES61",
    "ARAGÓN": "ES24",
    "ASTURIAS, PRINCIPADO DE": "ES12",
    "BALEARS, ILLES": "ES53",
    "CANARIAS": "ES70",
    "CANTABRIA": "ES13",
    "CASTILLA-LA MANCHA": "ES42",
    "CASTILLA Y LEÓN": "ES41",
    "CATALUÑA": "ES51",
    "CEUTA": "ES63",
    "COMUNITAT VALENCIANA": "ES52",
    "EXTREMADURA": "ES43",
    "GALICIA": "ES11",
    "MADRID, COMUNIDAD DE": "ES30",
    "MELILLA": "ES64",
    "MURCIA, REGIÓN DE": "ES62",
    "NAVARRA, COMUNIDAD FORAL DE": "ES22",
    "PAÍS VASCO": "ES21",
    "RIOJA, LA": "ES23",
}

# Provinces are keyed by their INE code, which is also the postcode prefix --
# so this table is checkable rather than merely asserted, and
# tests/test_geography.py checks it: for every code, the most common province
# among centres whose postcode starts with those two digits is the province
# named here. All 52 agree.
#
# REEC writes the Castilian forms (GERONA, LÉRIDA, VIZCAYA/BIZKAIA); the
# geometry carries the official ones (Girona, Lleida, Bizkaia). Same places,
# and the code is what joins them.
INE = {
    "ALAVA": "01", "ALBACETE": "02", "ALICANTE": "03", "ALMERÍA": "04",
    "AVILA": "05", "BADAJOZ": "06", "BALEARES": "07", "BARCELONA": "08",
    "BURGOS": "09", "CÁCERES": "10", "CÁDIZ": "11", "CASTELLÓN": "12",
    "CIUDAD REAL": "13", "CÓRDOBA": "14", "CORUÑA": "15", "CUENCA": "16",
    "GERONA": "17", "GRANADA": "18", "GUADALAJARA": "19", "GUIPÚZCOA": "20",
    "HUELVA": "21", "HUESCA": "22", "JAÉN": "23", "LEÓN": "24",
    "LÉRIDA": "25", "LA RIOJA": "26", "LUGO": "27", "MADRID": "28",
    "MÁLAGA": "29", "MURCIA": "30", "NAVARRA": "31", "OURENSE": "32",
    "ASTURIAS": "33", "PALENCIA": "34", "LAS PALMAS": "35",
    "PONTEVEDRA": "36", "SALAMANCA": "37", "STA. CRUZ DE TENERIFE": "38",
    "CANTABRIA": "39", "SEGOVIA": "40", "SEVILLA": "41", "SORIA": "42",
    "TARRAGONA": "43", "TERUEL": "44", "TOLEDO": "45", "VALENCIA": "46",
    "VALLADOLID": "47", "VIZCAYA/BIZKAIA": "48", "ZAMORA": "49",
    "ZARAGOZA": "50", "CEUTA": "51", "MELILLA": "52",
}

Place = collections.namedtuple("Place", "code trials share")


def _pairs(con, region_column, codes, since, until=None):
    """[(study_id, code)] for one geographic grain, corrections applied.

    The corrections are applied here, in Python, rather than as a CASE in the
    SQL: six rows of hand-checked judgement do not belong inside a query, and
    a query that carries them cannot be read without reading them too.

    Every (study, centre) pair is fetched -- 82,795 of them -- because a
    correction changes which place a pair lands in, and aggregating first
    would put the corrected ones in the wrong bucket before the fix applied.

    A centre whose place REEC never recorded drops out of the pairs. It does
    not drop out of the corpus: the study stays in the denominator and turns
    up in unlocated().
    """
    pairs = []
    for study_id, key, localidad, postcode, region, province in con.execute(
            """SELECT sc.study_id, c.center_key, c.localidad, c.cod_postal,
                      c.ccaa, c.provincia
                 FROM study_centers sc
                 JOIN centers c ON c.center_id = sc.center_id
                 JOIN studies st ON st.identificador = sc.study_id
                WHERE st.fecha_autorizacion_aemps >= ?
                  AND st.fecha_autorizacion_aemps < ?""",
            (_first_of(since), _first_of((until or 9998) + 1))):
        correction = CENTER_CORRECTIONS.get((key, localidad, postcode))
        if correction is not None:
            region, province = correction.ccaa, correction.provincia
        name = region if region_column else province
        if name is not None:
            pairs.append((study_id, codes[name]))
    return pairs


def region_pairs(con, since=COVERAGE_START, until=None):
    """[(study_id, NUTS 2 code)]."""
    return _pairs(con, True, NUTS, since, until)


def province_pairs(con, since=COVERAGE_START, until=None):
    """[(study_id, INE province code)]."""
    return _pairs(con, False, INE, since, until)


def participation(pairs, trials):
    """[Place] descending -- distinct trials with at least one site in each.

    A trial is counted once per place however many sites it has there, and in
    every place it reaches. `share` is of all trials in the window, so the
    181 with no located centre are in the denominator: a place's share is the
    fraction of Spanish trials it takes part in, and inflating it by dropping
    the trials nobody could place would flatter everywhere.
    """
    studies = collections.defaultdict(set)
    for study_id, code in pairs:
        studies[code].add(study_id)
    return sorted((Place(code, len(ids), 100.0 * len(ids) / trials)
                   for code, ids in studies.items()),
                  key=lambda place: -place.trials)


def unlocated(pairs, trials):
    """How many trials a map cannot place. Reported, never hidden."""
    return trials - len({study_id for study_id, _ in pairs})


# ---------------------------------------------------------------------------
# Sites as points: the dot map
# ---------------------------------------------------------------------------
# A different question from the choropleths above, and a different unit. The
# maps answer "which regions take part"; this answers "where are the sites".
#
# **The dots are centres, not trials.** A trial has no location -- its sites
# do, 7.2 of them on average and up to 93 -- so a dot per trial would be a
# dot per (trial, site) pair, about 6,000 marks stacked on the ~500 places
# that actually exist in a year. The mark is the hospital; the trial count is
# what it carries.
#
# Coordinates come from the postcode, so **every centre sharing a postcode
# shares a point**. In a dense district several large hospitals land exactly
# on top of each other. That is stated on the chart rather than jittered
# apart: jitter would invent a precision the postcode does not have, and put
# hospitals on streets they are not on.

Site = collections.namedtuple(
    "Site", "center_ids name localidad provincia trials lat lon")


def normalise_postcode(value):
    """A postcode fit to look up, or None. The rule is deliberately narrow.

    Three defects are documented in the schema and all three are repairable
    without guessing: trailing punctuation (`28006,`), digit separators
    (`28.223`), and a dropped leading zero, which is why `8214` is Barcelona
    and not nowhere.

    **Anything still holding a letter is refused rather than repaired**, and
    that refusal is the point of the function. Stripping letters instead
    turns `3584 AE` -- a Dutch postcode, Utrecht -- into `03584`, which is a
    real place in Alicante. A rule that recovers eleven more centres by also
    being able to move a hospital to another country is not worth eleven
    centres.
    """
    digits = value.strip().replace(".", "").replace(",", "")
    if not digits.isdigit():
        return None
    if len(digits) == 4:
        digits = "0" + digits
    return digits if len(digits) == 5 else None


def load_postcodes(path):
    """{postcode: (lat, lon)}. See data/geo/README.md for provenance."""
    with open(path, encoding="utf-8") as handle:
        rows = csv.reader(handle)
        next(rows)
        return {code: (float(lat), float(lon)) for code, lat, lon, _ in rows}


def load_towns(path):
    """{postcode: town}, the same file's other column.

    A source of truth for what town a postcode is in, which REEC's own
    `localidad` is not: twelve of its values have lost their accented
    characters to a mis-decoded byte -- `M?laga`, `Logro?o`, `Iru?a` -- and
    174 are blank. Both kinds are unusable for deciding that two rows are the
    same place, and both have a postcode that is not.
    """
    with open(path, encoding="utf-8") as handle:
        rows = csv.reader(handle)
        next(rows)
        return {code: town for code, _, _, town in rows}


def is_readable(localidad):
    """Whether a town name survived being stored.

    A `?` or a replacement character in the middle of a town name is a byte
    that did not make it through some encoding on the way here, not a town
    anyone wrote. `M?laga` is Málaga and cannot be matched against it, so it
    is treated as missing and resolved from the postcode instead.
    """
    return bool(localidad.strip()) and not ("?" in localidad
                                            or "�" in localidad)


def resolve_town(localidad, cod_postal, towns):
    """The town to compare two centre rows on, or '' when there is none.

    **The reported town wins whenever it is readable.** Deriving it from the
    postcode instead would be tidier and would be wrong: Institut Català
    d'Oncologia's Girona campus carries L'Hospitalet's postcode, 08908 -- a
    documented error, CHECKED_UNCHANGED above -- so a postcode-derived town
    would move Girona to L'Hospitalet and merge two real sites into one. The
    locality settles every case in the correction table too, for the same
    reason.

    So the postcode is a fallback for the rows where the reported town cannot
    be used at all, and never a correction of the rows where it can.
    """
    if is_readable(localidad):
        return normalise_town(localidad)
    code = normalise_postcode(cod_postal or "")
    return normalise_town(towns.get(code, "")) if code else ""


# The articles Spanish, Catalan, Galician and Valencian town names begin
# with. `l'` is written against the noun rather than spaced, so it is handled
# separately; the rest are whole words.
TOWN_ARTICLES = {"a", "o", "la", "el", "lo", "las", "los", "les", "els"}


def _without_article(words):
    """The town's words, minus a leading article. Only the first one.

    `La Línea de la Concepción` keeps its second `la`: the article being
    dropped is the one the catalogues move, and a rule that removed every
    article would start merging towns that differ by one.
    """
    if not words:
        return words
    if words[0] in TOWN_ARTICLES:
        return words[1:]
    if words[0].startswith("l'"):
        first = words[0][2:]
        return ([first] if first else []) + list(words[1:])
    return words


def normalise_town(localidad):
    """A town name comparable across spellings, or '' when there is none.

    REEC writes one town several ways: `Pamplona/Iruña` beside `Pamplona`,
    `Sabadell, Barcelona` beside `Sabadell`, `Manresa (Barcelona)` beside
    `Manresa`. All three shapes qualify the town with something larger, so
    everything from the first separator onwards is dropped, and what is left
    is compared without case or accents.

    A leading article goes too, because Spain's official town names carry one
    and the catalogues move it to the end to file them alphabetically: the
    Ministry writes `Coruña, A` and `Hospitalet de Llobregat, L'` where REEC
    writes `A Coruña` and `L'Hospitalet de Llobregat`. The comma rule above
    already strips the catalogue's trailing copy, so without this the two
    spellings of one town never meet -- 124 REEC centre rows sit in the 16
    towns this affects, and for them the town was simply never a way to look
    a hospital up.
    """
    text = localidad.split(",")[0].split("/")[0].split("(")[0]
    text = unicodedata.normalize("NFKD", text.strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_without_article(text.split()))


# Postcodes that must not join rows under one reference, because the postcode
# is the field that is wrong. Read before being written down, the same rule
# CENTER_CORRECTIONS follows, and the same case it already records: Institut
# Català d'Oncologia files L'Hospitalet, Badalona and Girona under one
# reference and gives all three L'Hospitalet's postcode, so linking on it
# would fuse three real hospitals into one.
#
# It is the only one in the corpus. 80 reference-and-postcode groups would
# merge rows whose towns disagree; 79 of them disagree because one row wrote
# the province in the town field, or lost an accent, or wrote the hospital's
# own name there. This is the one where the towns are simply three towns.
# Keyed on the postcode alone rather than on (reference, postcode), because
# the rows it has to keep apart share their name as well as their reference:
# a block that only stopped the reference from linking them would let the
# name link them instead, one line further down.
KEEP_APART = {
    "08908":
        "Institut Català d'Oncologia: L'Hospitalet, Badalona and Girona are "
        "three hospitals sharing one reference and one name, and the Girona "
        "and Badalona rows carry L'Hospitalet's postcode. They are separated "
        "by their towns, which are right. See CHECKED_UNCHANGED above.",
}


def _link(parent, one, other):
    """Union-find, so that a chain of agreements resolves to one site.

    Needed because the two signals overlap rather than nest: Althaia has rows
    at three postcodes and rows whose town field holds the province, and it
    takes both -- postcode joining the province-named row to a Manresa row,
    town joining that row to the other postcodes -- to see that all seven are
    one hospital.
    """
    while parent[one] != one:
        one = parent[one]
    while parent[other] != other:
        other = parent[other]
    parent[max(one, other)] = min(one, other)


def identities(rows, towns):
    """{center_id: identity} -- which rows are one site, decided together.

    `rows` are (center_id, center_key, localidad, cod_postal, referencia).
    Decided for the whole set at once rather than row by row, because one of
    the rules needs the row's neighbours: a row with no usable town at all
    takes the town of its key when its key has exactly one. Ramón y Cajal has
    a row with no locality and no postcode, and every other row under that
    reference says Madrid, so Madrid is what it is. Where a key has rows in
    two towns, a blank row could belong to either and stays its own site.

    An identity is either a (reference, town) pair -- the rows sharing one
    are one hospital -- or the centre's own id, which shares with nothing.
    """
    resolved, by_key = {}, collections.defaultdict(set)
    prepared = []
    for center_id, center_key, nombre, localidad, cod_postal, referencia \
            in rows:
        town = resolve_town(localidad or "", cod_postal, towns)
        resolved[center_id] = town
        prepared.append((center_id, center_key, referencia,
                         normalise_postcode(cod_postal or ""),
                         cleaning_rules.match_key(nombre or "")))
        if town:
            by_key[center_key].add(town)

    # A row with no town of its own takes its key's, when its key has one.
    for center_id, center_key, _, _, _ in prepared:
        if not resolved[center_id] and len(by_key[center_key]) == 1:
            resolved[center_id] = next(iter(by_key[center_key]))

    # Four ways to be the same hospital, each a shared identity and a shared
    # place. The reference is one identity and the name is another, and both
    # are needed: REEC issues several reference codes for one hospital and
    # leaves some rows with none -- 12 de Octubre files at 28041 under
    # ORG-100028548, under 280035, under two ORL- codes and under nothing --
    # so rows of one hospital routinely share everything except a reference.
    parent = {row[0]: row[0] for row in prepared}
    for identity_index in (2, 4):
        for place_index in (0, 3):
            seen = {}
            for row in prepared:
                identity = row[identity_index]
                place = (resolved[row[0]] if place_index == 0 else row[3])
                if not identity or not place:
                    continue
                if place_index == 3 and place in KEEP_APART:
                    continue
                pair = (identity, place)
                if pair in seen:
                    _link(parent, seen[pair], row[0])
                else:
                    seen[pair] = row[0]

    out = {}
    for row in prepared:
        root = row[0]
        while parent[root] != root:
            root = parent[root]
        out[row[0]] = root
    return out


def merge_key(referencia, town):
    """What decides that two centre rows are one site, or None for neither.

    **A registry reference and a town, and nothing else.** The reference says
    the rows belong to the same registered organisation; the town says they
    are the same site of it rather than two. Either alone is not enough:
    Institut Català d'Oncologia shares one reference across L'Hospitalet,
    Badalona and Girona, which are three real sites, and `Clínica privada`
    shares a town with other private clinics that are not it.

    Rows with no reference are never merged. That leaves 252 groups holding
    2,163 trial-site links -- 5.6% of the duplicated ones -- unmerged on
    purpose, because their key is derived from the name and the name is
    exactly what is unreliable. It is also where the town stops being
    trustworthy: Corporació Sanitària Parc Taulí is filed under Sabadell and
    under Barcelona, its province, and no rule reading those two strings can
    tell that from two genuine towns.

    `town` is already resolved and normalised -- see `resolve_town`.
    """
    if not referencia or not town:
        return None
    return (referencia, town)


def _area_join(area):
    """The two SQL fragments an optional therapeutic-area filter adds."""
    if area is None:
        return "", ()
    return ("""JOIN study_therapeutic_areas sta
                 ON sta.study_id = s.identificador AND sta.eutct_code = ?""",
            (area,))


def site_activity(con, since=COVERAGE_START, until=None, area=None,
                  towns=None):
    """[(center_id, name, localidad, provincia, postcode, trials)].

    Counted over trials authorised in the window, so a centre that ran
    nothing in it is absent rather than drawn as a zero -- an empty dot would
    claim the hospital exists on the map and did nothing, when what the data
    says is that it took part in no trial authorised in these years.

    **The province comes back corrected**, through the same CENTER_CORRECTIONS
    table the choropleths use. `centers.provincia` is a clean vocabulary
    containing wrong assignments and the schema says not to group on it
    directly; a filter reading it raw would put a handful of hospitals in a
    province the province map does not have them in, and the two views would
    disagree about the same seven centres.

    `area` is an EUTCT code. A trial listing several areas is counted in each,
    but the filter picks one, so within a filtered view each trial is counted
    once per centre and the marks stay comparable.
    """
    towns = {} if towns is None else towns
    join, params = _area_join(area)
    rows = con.execute(
        """SELECT c.center_id, c.nombre, c.localidad, c.provincia,
                  c.cod_postal, c.center_key, c.referencia, s.identificador
             FROM centers c
             JOIN study_centers sc ON sc.center_id = c.center_id
             JOIN studies s ON s.identificador = sc.study_id
             {}
            WHERE s.fecha_autorizacion_aemps >= ?
              AND s.fecha_autorizacion_aemps < ?""".format(join),
        params + (_first_of(since), _first_of((until or 9998) + 1)))

    # Every (centre, study) pair rather than a count per centre, because the
    # trials of merged rows have to be counted distinctly: a study listed
    # under both spellings of one hospital is one trial there, and summing
    # two counts would make it two. Same reason _pairs fetches its pairs.
    rows = list(rows)
    identity_of = identities(
        {(cid, key, name, localidad, postcode, referencia)
         for cid, name, localidad, _, postcode, key, referencia, _ in rows},
        towns)

    studies = collections.defaultdict(set)
    members = collections.defaultdict(dict)
    per_centre = collections.Counter()
    for (cid, name, localidad, provincia, postcode, key, referencia,
         study_id) in rows:
        correction = CENTER_CORRECTIONS.get((key, localidad, postcode))
        if correction is not None:
            provincia = correction.provincia
        identity = identity_of[cid]
        studies[identity].add(study_id)
        members[identity][cid] = (name, localidad, provincia, postcode)
        per_centre[cid] += 1

    merged = []
    for identity, ids in members.items():
        # The spelling carrying the most trials speaks for the site: it is
        # the one the registry used most often, and its postcode is the one
        # most of the activity was actually filed under -- which matters,
        # because that postcode is what puts the mark on the map.
        principal = max(ids, key=lambda cid: per_centre[cid])
        merged.append((tuple(ids), *ids[principal], len(studies[identity])))
    return sorted(merged, key=lambda row: -row[5])


# Connectors are lowercase anywhere inside a name: Hospital Clinic de
# Barcelona, Germans Trias i Pujol.
CONNECTORS = {"de", "del", "y", "i", "en", "da", "do", "dos", "a"}

# Articles are only lowercase when they follow a connector. `Virgen de las
# Nieves` takes one, and `Hospital La Paz` does not: there the article opens
# the hospital's actual name -- La Paz, La Fe, El Bierzo -- and lowercasing it
# reads as a typo to anyone who knows the place.
ARTICLES = {"la", "las", "los", "el"}

# Short and uppercase, but titles rather than acronyms: `DR. PESET` wants to
# become `Dr. Peset`, where `(H.U.C)` wants to stay as it is.
ABBREVIATIONS = {"dr", "dra", "sr", "sra", "sta", "sto", "san"}

# Catalan articles, elided onto the word they precede.
ELISIONS = {"d'", "l'", "d’", "l’"}


def _capitalised(word):
    """One word, with each apostrophe- or hyphen-separated part capitalised.

    Split on both, so `d'hebron` becomes `D'Hebron` and `gomez-ulla` becomes
    `Gomez-Ulla` rather than `D'hebron` and `Gomez-ulla`.
    """
    for separator in ("'", "’", "-"):
        if separator in word:
            return separator.join(_capitalised(part)
                                  for part in word.split(separator))
    return word[:1].upper() + word[1:].lower()


def display_name(nombre):
    """A centre's name in one consistent case.

    REEC spells the same hospital several ways and the loader keeps the most
    frequent one per site, so a list of centres mixes `HOSPITAL UNIVERSITARI
    VALL D'HEBRON` with `Hospital Universitari Vall D Hebron` and reads as
    though they were two places. They are not, and neither are they merged --
    see the note on centre identity below.

    Short all-uppercase words are left alone, because they are acronyms and
    `CAE Oroitu` is not improved by becoming `Cae Oroitu`. Everything else is
    recased from scratch rather than only when it arrives shouting: recasing
    only the uppercase spellings would leave `Clínica privada` beside
    `Clínica Privada`, which is the same inconsistency one step quieter.

    **This changes how a name looks and never which centre it is.** Identity
    stays the loader's, so two entries that differ only in case remain two
    entries -- and they have to, because the centres sharing a key are
    sometimes one organisation at several addresses (Institut Català
    d'Oncologia in Badalona and in Girona) and sometimes unrelated clinics
    sharing a placeholder name (`Clínica privada` in Bilbao and in Murcia).
    A merge would be wrong in one of those two directions whichever way it
    was made, so the locality travels with the name instead.
    """
    # Whether a short uppercase word is an acronym or an ordinary word cannot
    # be told from the word: `CAE` is one and `PAZ` is not. It can be told
    # from the name around it. In a name that is shouting throughout, every
    # word is uppercase because the whole string is, so none of them is
    # evidence of anything and all of them get recased. In a name that is
    # not, an uppercase word among lowercase ones was made uppercase on
    # purpose, and is left alone.
    shouting = nombre == nombre.upper()

    out = []
    after_particle = False
    for position, word in enumerate(nombre.split()):
        letters = "".join(c for c in word if c.isalpha())
        dotted = "." in word[:-1] and letters.isupper()
        elided = word[:2].lower()
        lowered = word.lower()
        # Being a particle and being written as one are different: a name
        # opening on `De` capitalises it, and the `la` after it is still
        # following a particle.
        is_particle = (lowered in CONNECTORS
                       or (lowered in ARTICLES and after_particle))
        particle = position and is_particle
        after_particle = is_particle
        if particle:
            out.append(lowered)
        elif position and elided in ELISIONS:
            # Catalan elides its articles onto the next word, and they stay
            # lowercase inside a name the way `de` does: Vall d'Hebron,
            # L'Hospitalet becomes l'Hospitalet after the first word.
            out.append(elided + _capitalised(word[2:]))
        elif letters.lower() in ABBREVIATIONS:
            out.append(_capitalised(word))
        elif dotted:
            # `(H.U.C)` is an acronym in any name, shouting or not.
            out.append(word)
        elif (not shouting and letters and letters.isupper()
              and len(letters) <= 4):
            out.append(word)
        else:
            out.append(_capitalised(word))
    return " ".join(out)


PROVINCIA = 3


def only_provinces(rows, provinces):
    """site_activity rows in the named provinces; all of them when none are.

    Applied here rather than as a WHERE on `centers.provincia`, and the
    reason is the same one that makes site_activity correct the column at
    all: the corrections happen in Python, so a SQL filter would be reading
    the uncorrected value and would drop the very centres the correction
    table exists to move.
    """
    if not provinces:
        return rows
    return [row for row in rows if row[PROVINCIA] in provinces]


def place_sites(rows, postcodes):
    """([Site] biggest first, unplaced centres, unplaced trial-site links).

    Pure, so the join between a centre and its coordinates can be tested
    without a database or a file.

    Two counts come back rather than one because they answer different
    questions: how many hospitals are missing from the map, and how much
    activity is missing with them. A hundred unplaceable centres that ran one
    trial each is a different map from two that ran a hundred.
    """
    placed, lost_sites, lost_trials = [], 0, 0
    for center_ids, name, localidad, provincia, postcode, trials in rows:
        point = postcodes.get(normalise_postcode(postcode or "") or "")
        if point is None:
            lost_sites += 1
            lost_trials += trials
            continue
        placed.append(Site(center_ids, display_name(name), localidad,
                           provincia, trials, *point))
    return (sorted(placed, key=lambda site: -site.trials),
            lost_sites, lost_trials)


def provinces_with_sites(con, since=COVERAGE_START, until=None, area=None,
                         provinces=None):
    """{INE code} of provinces holding at least one trial in the window.

    Binary on purpose. The province choropleth already draws participation as
    a magnitude, and shading this layer by the same magnitude under dots that
    are *also* sized by it would spend two channels saying one thing. What
    this adds is the thing the dots cannot show: which provinces have no
    trial at all in the window, which is empty map rather than absent ink.

    Derived from the sites rather than from province_pairs, and taking every
    filter the marks take, so that the backdrop and the marks answer to the
    same question. A filter has to empty a province on the backdrop at the
    same moment it removes its last dot; a backdrop still shading fifty-one
    provinces under the dots of one is describing a set the map is not
    drawing.
    """
    return {INE[provincia]
            for _, _, _, provincia, _, _ in only_provinces(
                site_activity(con, since, until, area), provinces)
            if provincia in INE}


def studies_at(con, center_ids, since=COVERAGE_START, until=None, area=None):
    """[(identificador, es_ctis, year)] for one centre, newest first.

    What a reader gets after picking a hospital. The identifier is the key to
    the registry that holds the record -- see analysis/registry.py, and note
    that REEC itself publishes no per-study URL to link to.

    Takes the same filters as the marks, `area` included, because the list is
    read as the mark broken open: if the dot is sized by 40 trials and the
    list runs to 300, one of the two is lying about what it counted.
    """
    # DISTINCT because the merged rows of one hospital can both list the same
    # study, which is one trial there and not two -- the same reason
    # site_activity counts studies in a set.
    join, params = _area_join(area)
    ids = tuple(center_ids)
    return list(con.execute(
        """SELECT DISTINCT s.identificador, s.es_ctis,
                  substr(s.fecha_autorizacion_aemps, 1, 4) AS year
             FROM studies s
             JOIN study_centers sc ON sc.study_id = s.identificador
             {}
            WHERE sc.center_id IN ({})
              AND s.fecha_autorizacion_aemps >= ?
              AND s.fecha_autorizacion_aemps < ?
         ORDER BY s.fecha_autorizacion_aemps DESC""".format(
            join, ",".join("?" * len(ids))),
        params + ids + (_first_of(since),
                        _first_of((until or 9998) + 1))))


# ---------------------------------------------------------------------------
# Candidate duplicate centres, for reading
# ---------------------------------------------------------------------------
# 333 centre keys cover 810 rows and 46.6% of all trial-site links, so the
# same hospital under two spellings is not a rounding error on this map.
#
# **Blocking on the key is where the candidates come from and not where the
# decision is made**, the same rule the sponsor families follow. A key gathers
# rows that are sometimes one site spelled twice, sometimes several real sites
# of one organisation, and sometimes unrelated places sharing a placeholder
# name. All three shapes appear in the top of this list:
#
#   ORG-100009329  Hospital Clínic, Barcelona 08036 and 08028 -- one site
#   ORG-100030394  Institut Català d'Oncologia, L'Hospitalet / Badalona /
#                  Girona -- three sites, and Badalona itself under two
#                  postcodes, so the group is both shapes at once
#   clinicaprivada `Clínica privada` in Bilbao, Burgos, Madrid, Murcia --
#                  four unrelated clinics
#
# The town nearly separates them and cannot be trusted to: Corporació
# Sanitària Parc Taulí is filed under Sabadell and under Barcelona, which is
# its province rather than its town. So the rule generates the list and a
# person reads it, which is what CentreGroup is for.

CentreGroup = collections.namedtuple("CentreGroup", "key sites trials")
CentreSite = collections.namedtuple("CentreSite", "label rows trials merged")
CentreRow = collections.namedtuple(
    "CentreRow", "center_id name localidad cod_postal referencia trials")


def _site_label(rows):
    """What to call a merged site on the review page.

    The town its busiest rows agree on. Taken from the rows rather than from
    the identity, because the identity is a centre id once rows can be joined
    by postcode as well as by town -- and a number tells the reader nothing
    about whether the merge was right.
    """
    counted = collections.Counter(
        normalise_town(row.localidad or "") for row in rows)
    counted.pop("", None)
    return counted.most_common(1)[0][0] if counted else "no town"


def centre_groups(con, towns, since=COVERAGE_START, until=None):
    """[CentreGroup] where one key covers several centres, biggest first.

    Each group carries the *sites* it resolved into, so the page built from
    this can show what became what rather than leaving the reader to match
    labels across rows. A group with one site is one hospital that was spelled
    several ways; a group with several is either several real sites or
    several unrelated places, and only reading tells them apart.

    Site totals count studies distinctly rather than summing the rows, for
    the reason site_activity does: Hospital Clínic's two spellings share two
    studies, so the merged site holds 2,925 trials and not 2,927.
    """
    rows = con.execute(
        """SELECT c.center_key, c.center_id, c.nombre, c.localidad,
                  c.cod_postal, c.referencia, s.identificador
             FROM centers c
             JOIN study_centers sc ON sc.center_id = c.center_id
             JOIN studies s ON s.identificador = sc.study_id
            WHERE s.fecha_autorizacion_aemps >= ?
              AND s.fecha_autorizacion_aemps < ?""",
        (_first_of(since), _first_of((until or 9998) + 1)))

    rows = list(rows)
    identity_of = identities(
        {(cid, key, name, localidad, postcode, referencia)
         for key, cid, name, localidad, postcode, referencia, _ in rows},
        towns)

    members = collections.defaultdict(dict)
    per_site = collections.defaultdict(set)
    per_centre = collections.defaultdict(set)
    for key, cid, name, localidad, postcode, referencia, study_id in rows:
        identity = identity_of[cid]
        members[key][cid] = (name, localidad, postcode, referencia, identity)
        per_site[(key, identity)].add(study_id)
        per_centre[cid].add(study_id)

    groups = []
    for key, centres in members.items():
        if len(centres) < 2:
            continue
        by_site = collections.defaultdict(list)
        for cid, (name, localidad, postcode, referencia,
                  identity) in centres.items():
            by_site[identity].append(CentreRow(
                cid, name, localidad, postcode, referencia,
                len(per_centre[cid])))

        sites = sorted(
            (CentreSite(
                _site_label(rows_),
                sorted(rows_, key=lambda row: -row.trials),
                len(per_site[(key, identity)]),
                len(rows_) > 1)
             for identity, rows_ in by_site.items()),
            key=lambda site: -site.trials)
        groups.append(CentreGroup(
            key, sites,
            len({study for identity in by_site
                 for study in per_site[(key, identity)]})))
    return sorted(groups, key=lambda group: -group.trials)


def centres_review_page(groups, shown=60):
    """A page listing the candidates, for the reading that has to happen.

    The sibling of `sponsors.review_page`, and it earns its place the same
    way: a rule cannot report the merge it failed to make, so the only way to
    find one is to read what the rule left alone.

    `towns` is the column to read first. One town and several postcodes is
    almost always one site typed twice; several towns is almost always
    several real sites, or several unrelated places under a shared name.
    Almost, in both directions, which is the reason this is a page and not a
    rule.
    """
    import html

    lines = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
             "<title>Centre duplicates</title><style>",
             REVIEW_STYLE.format(surface=SURFACE, ink=INK, muted=MUTED,
                                 grid=GRID),
             # The sites are a level the sponsor page does not have, so they
             # need a rung of their own between the key and its spellings.
             "tr.site td {{ color: {ink}; font-weight: 600; font-size: 12px; "
             "border-bottom: none; padding-top: 10px; }}"
             "tr.site td.name {{ padding-left: 20px; }}"
             "tr.spelling td.name {{ padding-left: 44px; }}".format(ink=INK),
             "</style></head><body>",
             "<h1>Centre duplicates</h1>",
             "<p>Every centre key covering more than one row, biggest first. "
             "Generated by <code>run_analysis.py</code>. These are "
             "<strong>candidates</strong>: nothing here is merged, and no "
             "count in the project depends on this page. Trials are those "
             "authorised since {}.</p>".format(COVERAGE_START),
             "<p><strong>How to read it.</strong> Each bold row is one "
             "registry key. Under it, each <em>Site</em> row is a hospital "
             "the key resolved into, and the plain rows beneath a site are "
             "the spellings that became it. A key with one site was one "
             "hospital written several ways. A key with several is either "
             "several real sites of one organisation — Institut Català "
             "d'Oncologia runs in L'Hospitalet, Badalona and Girona — or "
             "unrelated places sharing a name, and merging either would be "
             "wrong.</p>",
             "<p>Every total counts each trial once. A key's total can "
             "therefore be <em>smaller</em> than its sites added up — a trial "
             "running at both Clínica Universidad de Navarra's Pamplona and "
             "Madrid sites is one trial for the key and one at each site — "
             "and a merged site's total can be smaller than its rows added "
             "up, which is the point of merging them: Hospital Clínic's two "
             "spellings share two studies, so the site holds 2,925 and not "
             "2,927.</p>",
             "<p><strong>What to look for.</strong> A site whose rows are "
             "obviously the same place as another site's: that is a merge "
             "the rule missed, and the reason is usually in the Town column. "
             "Hospital Clínic has a row whose town field holds the "
             "hospital's own name, so there was no town to match on. The "
             "town is not decisive on its own either — Parc Taulí is filed "
             "under Sabadell and under Barcelona, its province.</p>",
             "<h2>{:,} keys covering more than one row, {:,} trials; the {} "
             "largest below</h2>".format(
                 len(groups), sum(group.trials for group in groups),
                 min(shown, len(groups))),
             "<table><thead><tr>",
             "<th>Centre as the registry spells it</th>",
             "<th>Town</th><th>Postcode</th>",
             "<th class='n'>Trials</th>",
             "</tr></thead><tbody>"]

    for group in groups[:shown]:
        first = group.sites[0].rows[0]
        lines.append(
            "<tr class='family'><td>{}</td><td class='tag'>{}</td>"
            "<td class='tag'>{}</td><td class='n'>{:,}</td></tr>".format(
                html.escape(display_name(first.name)),
                html.escape(first.referencia or "no reference"),
                "{} site{}".format(len(group.sites),
                                   "" if len(group.sites) == 1 else "s"),
                group.trials))
        for number, site in enumerate(group.sites, start=1):
            lines.append(
                "<tr class='site'><td class='name'>{}</td><td></td><td></td>"
                "<td class='n'>{:,}</td></tr>".format(
                    "Site {} of {} — {}".format(
                        number, len(group.sites),
                        "{} rows merged on “{}”".format(
                            len(site.rows), html.escape(site.label or ""))
                        if site.merged else "one row, nothing to merge"),
                    site.trials))
            for row in site.rows:
                lines.append(
                    "<tr class='spelling'><td class='name'>{}</td><td>{}</td>"
                    "<td>{}</td><td class='n'>{:,}</td></tr>".format(
                        html.escape(row.name),
                        html.escape(row.localidad or "—"),
                        html.escape(row.cod_postal or "—"),
                        row.trials))

    lines.append("</tbody></table></body></html>")
    return "\n".join(lines)


def load_geometry(path):
    """Polygons keyed by code. See data/geo/README.md for provenance."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def names_in(geometry):
    """{code: display name}. The geometry is the authority on spelling."""
    return {feature["id"]: feature["properties"]["name"]
            for feature in geometry["features"]}


# A single hue, light to dark, from the documented sequential ramp: magnitude
# is one quantity and a second hue would imply a second thing being measured.
# The lightest step is allowed to sit near the surface because it means
# "almost none", which is what a sequential ramp's low end is for.
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
             "#0d366b"]

# The Canary Islands are 1,000 km off the coast, so a single map containing
# them spends half its canvas on empty Atlantic. Spanish official cartography
# answers this with an inset box, and so does this: the same polygons and the
# same colour scale on a second geo axis at its own scale, with the
# displacement admitted in a caption rather than hidden by quietly moving the
# islands next to Andalucía. One region at NUTS 2; two provinces at INE.
CANARY_CODES = {"ES70", "35", "38"}

# The peninsula, the Balearics, Ceuta and Melilla. The latitude floor is 34.9
# rather than the mainland's 36 because Ceuta and Melilla are on the African
# coast, and a map of Spanish trial sites that cropped two autonomous cities
# would be wrong in the way this whole module is about.
MAINLAND = dict(lonaxis_range=[-9.8, 4.6], lataxis_range=[34.9, 44.0])
CANARIES = dict(lonaxis_range=[-18.3, -13.2], lataxis_range=[27.5, 29.5])


def figure(places, geometry, title, subtitle_text):
    """Participation as a choropleth, with the Canaries inset."""
    import plotly.graph_objects as go

    # Both traces share one scale, so a colour means the same thing in the
    # inset as on the mainland. Left to itself each trace would normalise to
    # its own values, and the islands would come out the darkest place in
    # Spain.
    ceiling = max(place.share for place in places)
    names = names_in(geometry)

    def choropleth(rows, geo, showscale):
        return go.Choropleth(
            geojson=geometry, featureidkey="id", geo=geo,
            locations=[place.code for place in rows],
            z=[place.share for place in rows],
            text=[names[place.code] for place in rows],
            customdata=[place.trials for place in rows],
            colorscale=BLUE_RAMP, zmin=0, zmax=ceiling, showscale=showscale,
            marker=dict(line=dict(color=SURFACE, width=1)),
            colorbar=dict(
                title=dict(text="% of Spanish trials with a site here",
                           side="top", font=dict(size=11, color=MUTED)),
                orientation="h", x=0.5, y=-0.06, xanchor="center",
                yanchor="bottom", ticksuffix="%", thickness=10, len=0.45,
                outlinewidth=0, tickfont=dict(size=11, color=MUTED)),
            hovertemplate="%{text}<br>%{customdata:,} trials, %{z:.1f}% of all"
                          "<extra></extra>")

    fig = go.Figure([
        choropleth([p for p in places if p.code not in CANARY_CODES],
                   "geo", True),
        choropleth([p for p in places if p.code in CANARY_CODES],
                   "geo2", False)])

    fig.update_layout(
        title=dict(text=title,
                   subtitle=dict(text=subtitle_text,
                                 font=dict(size=12, color=MUTED)),
                   font=dict(size=17, color=INK)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=10, b=90, l=10), width=760, height=600,
        # Two notes rather than one line: at one line they ran through the
        # colour bar's tick labels, and the inset needs its caption beside
        # the inset rather than in a credit at the far corner.
        annotations=[
            dict(x=0.01, y=0.31, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Canarias, at its own scale"),
            dict(x=0, y=-0.12, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Boundaries © EuroGeographics (Eurostat GISCO, NUTS)")])
    fig.update_geos(visible=False, projection_type="mercator", bgcolor=SURFACE)
    fig.update_layout(
        geo=dict(domain=dict(x=[0, 1], y=[0, 1]), **MAINLAND),
        geo2=dict(domain=dict(x=[0.0, 0.22], y=[0.0, 0.30]),
                  visible=False, bgcolor=SURFACE, **CANARIES))
    return fig


# The name the base layer answers to. app/theme.py restyles choropleths by
# name, because this one is a two-colour backdrop and the participation maps
# are a sequential ramp, and a selector on the trace type alone cannot tell
# them apart.
BASE_LAYER = "provinces"


def sites_figure(sites, geometry, active, title, subtitle_text):
    """The dot map: one mark per centre, area proportional to trials.

    Drawn over the provinces, which are filled where a trial ran in the
    window and left as background where none did. The fill is two colours,
    not a ramp: how much is already the dots' job, and the backdrop's job is
    where the borders are and which of them are empty.

    **Area, not radius.** Plotly's `sizemode="area"` is what makes a hospital
    with 400 trials read as four times one with 100; sizing the radius by the
    count instead would draw it sixteen times the ink and overstate every
    large site. The eye compares blobs by area whatever the code intended, so
    the encoding has to be the one the eye is already using.

    The Canaries are a second subplot at their own scale, as on the
    choropleths, and sites are split between the two by longitude rather than
    by province, since a point either falls in the inset's window or it does
    not.
    """
    import plotly.graph_objects as go

    biggest = max((site.trials for site in sites), default=1)

    def dots(rows, geo):
        return go.Scattergeo(
            geo=geo, lon=[site.lon for site in rows],
            lat=[site.lat for site in rows],
            text=[site.name for site in rows],
            customdata=[(site.localidad, site.trials) for site in rows],
            mode="markers",
            marker=dict(
                size=[site.trials for site in rows],
                sizemode="area",
                # The largest mark is 34px across; every other follows from
                # it. sizeref is Plotly's units-per-pixel-squared, so it is
                # derived from the biggest value rather than tuned by hand,
                # and a filtered year cannot silently rescale the map.
                sizeref=2.0 * biggest / (34.0 ** 2),
                sizemin=3,
                color=SERIES, opacity=0.65,
                line=dict(width=0.5, color=SURFACE)),
            hovertemplate="<b>%{text}</b><br>%{customdata[0]}"
                          "<br>%{customdata[1]:,} trials<extra></extra>")

    def base(geo):
        """The provinces, filled where something ran in the window."""
        codes = [feature["id"] for feature in geometry["features"]]
        names = names_in(geometry)
        return go.Choropleth(
            geojson=geometry, featureidkey="id", geo=geo, name=BASE_LAYER,
            locations=codes,
            z=[1 if code in active else 0 for code in codes],
            zmin=0, zmax=1, showscale=False,
            text=[names[code] for code in codes],
            colorscale=[[0, SURFACE], [1, GRID]],
            marker=dict(line=dict(color=MUTED, width=0.4)),
            hovertemplate="%{text}<extra></extra>")

    mainland = [site for site in sites if site.lon > -12]
    canaries = [site for site in sites if site.lon <= -12]

    # Base first, dots second: Plotly draws traces in order, and a backdrop
    # drawn last is a backdrop over the thing it backs.
    fig = go.Figure([base("geo"), base("geo2"),
                     dots(mainland, "geo"), dots(canaries, "geo2")])
    fig.update_layout(
        # The subtitle is a second line of the title's own text rather than
        # Plotly's `title.subtitle`, which on this figure renders *above* the
        # title and overlaps it. The choropleths use `title.subtitle` and are
        # fine, and the difference was not the margin, the title anchoring or
        # the second subplot's visibility -- all three were tried. Two lines
        # of one string cannot come out in the wrong order, so the layout
        # stops depending on which of those it was.
        title=dict(
            text="{}<br><span style='font-size:12px;font-weight:400;"
                 "color:{}'>{}</span>".format(title, MUTED, subtitle_text),
            font=dict(size=17, color=INK)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE, showlegend=False,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        # t is 95, the same as the choropleths, and it is not a free choice:
        # Plotly anchors the subtitle to the top of the paper and the title
        # relative to the margin, so a *larger* top margin slides the title
        # down past its own subtitle and prints one over the other.
        margin=dict(t=95, r=10, b=60, l=10), width=760, height=600,
        annotations=[
            dict(x=0.01, y=0.31, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Canarias, at its own scale"),
            dict(x=0, y=-0.09, xref="paper", yref="paper", xanchor="left",
                 showarrow=False, font=dict(size=10, color=MUTED),
                 text="Boundaries © EuroGeographics (Eurostat GISCO, NUTS). "
                      "Sites placed by postcode (GeoNames, CC BY 4.0)")])
    # visible=False on the geo frames, exactly as the choropleths have it.
    # The land under the dots is drawn by the province layer above, so the
    # base map has nothing left to contribute -- and leaving the second
    # subplot visible is what put the title underneath its own subtitle: an
    # inset that draws its own frame claims margin at the top of the paper,
    # and Plotly resolves the collision by moving the title rather than the
    # subtitle.
    fig.update_geos(visible=False, projection_type="mercator",
                    bgcolor=SURFACE)
    fig.update_layout(
        geo=dict(domain=dict(x=[0, 1], y=[0, 1]), **MAINLAND),
        geo2=dict(domain=dict(x=[0.0, 0.22], y=[0.0, 0.30]),
                  visible=False, bgcolor=SURFACE, **CANARIES))
    return fig


def sites_subtitle(note=None):
    """What the dots cannot say for themselves.

    One short line, because the figure is 760px wide and a subtitle that runs
    past it is clipped rather than wrapped -- and because on the unfiltered
    first view every extra line is clutter the reader has to get past before
    reaching the map.

    `note` names the filters in force. Without it a filtered map is a map of
    everything as far as the reader can tell, and every count under it -- all
    of the filtered set -- would read as a claim about the corpus.

    What the map cannot place is deliberately *not* here. It belongs with the
    reader who is asking about coverage rather than in the way of the one
    reading the map, so it is a line underneath, and only when there is
    something to report.
    """
    line = "Hospitals sharing a postcode share a point."
    return "{} · {}".format(note, line) if note else line


def subtitle(places, geometry, unplaced, grain):
    """The two things a reader has to know before reading the colours."""
    leader = places[0]
    return ("A trial counts in every {} it has a site in, so they overlap: "
            "{} alone takes part in {:.0f}% of them.<br>{:,} trials are not "
            "on the map — they report no centre, or none whose {} was "
            "recorded.".format(grain, names_in(geometry)[leader.code],
                               leader.share, unplaced, grain))
