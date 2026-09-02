"""Resolving 85,410 centre entries into 3,306 physical sites.

Every other transform in this project is a pure function of one record. This
one cannot be, and the reason is worth stating: a centre entry does not carry
enough information to describe its own site. Its name is one of several
spellings, its region is often blank, and its postcode may be missing a digit
that only the rest of the corpus can supply. So the corpus is read once to
build an index of what it collectively knows, and a second time to resolve each
entry against it.

`build_center_index` -> `center_row` follows the shape cleaning_rules.py
already uses for `build_postcode_evidence` -> `resolve_postcode`: the index is
built by a pass and PASSED IN, never imported from a module global. The resolving
function stays pure given its arguments, so it can be tested on a handful of
hand-written entries instead of on 85,410 real ones.

Three resolutions happen here, all of them "most frequent wins":

  * **the locality's spelling**, resolved across the WHOLE corpus rather than
    per site. Sites already group correctly, because the key compares the
    locality rather than storing it -- but the stored value is what a
    dashboard groups by, and
    `BARCELONA`, `Barcelona` and `barcelona` are three bars in that chart.
    Resolved once per place, every site in a city stores the same spelling
  * **the name**, because the two commonest values in the whole field are one
    hospital -- HOSPITAL UNIVERSITARI VALL D'HEBRON (2,667) and Hospital
    Universitari Vall D Hebron (1,553)
  * **provincia and ccaa**, because 149 sites disagree with themselves; 132 of
    those only because one variant is blank, and the other 17 are
    single-occurrence typos that lose to the majority by construction
  * **the postcode**, delegated to cleaning_rules.resolve_postcode

Identity is the awkward part and is deliberately two-layered. A site is
(reference-or-name, locality, postcode), but the postcode is the field being
repaired, so it cannot also be part of the key used to repair it. The evidence
key is therefore (reference-or-name, locality) -- dropping the postcode,
keeping the locality, because without the locality Clinica Universidad de
Navarra's Pamplona and Madrid campuses would vote on each other's postcodes,
which is the exact merge the site-level key exists to prevent.
"""

import collections

from db.cleaning_rules import (
    build_postcode_evidence,
    clean_text,
    fold,
    is_placeholder,
    match_key,
    resolve_postcode,
)

CenterIndex = collections.namedtuple(
    "CenterIndex", "postcodes names localities regions place_names")

# What one entry contributes, before any resolution. Kept small on purpose:
# the index materialises one of these per centre entry, and there are 85,410.
Entry = collections.namedtuple(
    "Entry", "identity nombre localidad cod_postal provincia ccaa referencia")


def read_entry(raw):
    """One raw centro dict as the fields a site is built from.

    Returns None when the entry names no site at all -- 5 of the 85,410. Three
    are blank in every field but `situacion`; two name the site '.' or '-',
    which folds away to nothing, so match_key gives them no identity either.
    Same outcome by two routes, which is why the rule is "identity is empty"
    rather than "the fields are blank". They create no centre and no bridge
    row, the same shape as a placeholder funder.
    """
    referencia = clean_text(raw.get("referencia"))
    if referencia is not None and is_placeholder(referencia):
        # 'NR' in 119 entries covering 103 distinct hospitals. Deduplicating
        # on it would merge them into one centre with one region.
        referencia = None
    nombre = clean_text(raw.get("nombre"))
    identity = referencia if referencia is not None else match_key(nombre)
    if identity is None:
        return None
    return Entry(identity=identity,
                 nombre=nombre,
                 localidad=clean_text(raw.get("localidad")),
                 cod_postal=clean_text(raw.get("codPostal")),
                 provincia=clean_text(raw.get("provincia")),
                 ccaa=clean_text(raw.get("ccaa")),
                 referencia=referencia)


def place_key(localidad):
    """How two spellings of one place are compared.

    `match_key`, not `fold`: a locality is a name, and it is compared the same
    way every other name in this project is compared. `fold` alone left
    `Hospitalet de Llobregat, L'` apart from `HOSPITALET DE LLOBREGAT (L´)`
    over a comma, a bracket and an apostrophe style.
    """
    return match_key(localidad) or ""


def evidence_key(entry):
    """The group a postcode is repaired within: identity plus locality."""
    return (entry.identity, place_key(entry.localidad))


def build_center_index(raw_entries):
    """Everything the corpus collectively knows about its sites.

    `raw_entries` is an iterable of raw centro dicts. Consumed once; the small
    tuples it produces are kept, not the dicts.

    Two sub-passes, in this order and not the other: postcodes must be
    repaired before sites can be grouped, because the repaired postcode is
    part of the site key. Only well-formed postcodes vote, so a broken value
    can never confirm another.
    """
    entries = [entry for entry in map(read_entry, raw_entries)
               if entry is not None]

    postcodes = build_postcode_evidence(
        (entry.cod_postal, evidence_key(entry), entry.localidad)
        for entry in entries)

    names = collections.defaultdict(collections.Counter)
    localities = collections.defaultdict(collections.Counter)
    regions = collections.defaultdict(collections.Counter)
    # Keyed on the FOLDED locality and shared by every site in that place, so
    # one city has one spelling wherever it appears. The per-site `localities`
    # counter above cannot do this: it only ever sees one site's entries, and
    # a city with 335 sites would resolve its spelling 335 times over.
    place_names = collections.defaultdict(collections.Counter)
    for entry in entries:
        if entry.localidad:
            place_names[place_key(entry.localidad)][entry.localidad] += 1
    for entry in entries:
        key = _site_key(entry, postcodes)
        if entry.nombre:
            names[key][entry.nombre] += 1
        if entry.localidad:
            localities[key][entry.localidad] += 1
        # Blanks do not vote: a site whose region is recorded once and blank
        # 400 times has a region, and it is the one that was recorded.
        for field, value in (("provincia", entry.provincia),
                             ("ccaa", entry.ccaa)):
            if value:
                regions[key][(field, value)] += 1

    return CenterIndex(postcodes=postcodes, names=names,
                       localities=localities, regions=regions,
                       place_names=place_names)


def _site_key(entry, postcodes):
    """(identity, compared locality, repaired postcode) -- the grouping key.

    Compared, not display: the key must not split MADRID from Madrid, nor
    `Coruña, A` from `CORUÑA (A)`. The display spellings are resolved
    separately -- and for the locality, across the whole corpus.
    """
    resolution = resolve_postcode(
        entry.cod_postal, evidence_key(entry), entry.localidad, postcodes)
    return (entry.identity, place_key(entry.localidad),
            resolution.postcode or "")


def _most_frequent(counter, default=None):
    """Most frequent value; ties broken alphabetically so a load is stable."""
    if not counter:
        return default
    return min(counter.items(), key=lambda item: (-item[1], item[0]))[0]


def _best_spelling(counter, default=None):
    """Most frequent spelling that is not shouting, else most frequent.

    For place names, where the display value is also what a dashboard shows.
    541 of the 675 localities have at least one mixed-case spelling on record;
    for 29 of them ALL CAPS wins on raw frequency, and preferring the
    mixed-case one gives `Donostia-San Sebastián` and `Coruña (A)` instead of
    the same words in capitals. A registry that shouts is not more
    authoritative.

    It never invents a spelling: the 134 localities the registry only ever
    wrote in capitals stay in capitals, because there is nothing else to pick.
    """
    if not counter:
        return default
    quiet = collections.Counter({value: n for value, n in counter.items()
                                 if not value.isupper()})
    return _most_frequent(quiet or counter, default)


def center_row(raw, index, tally=None):
    """(site key, row) for one raw centro dict, or None when it names no site.

    The site key is what the loader deduplicates on; the row is what it
    inserts. Every field on the row is resolved over the whole site rather
    than taken from this entry, so two entries for one site produce identical
    rows and the second is simply skipped.
    """
    entry = read_entry(raw)
    if entry is None:
        if tally is not None:
            tally.applied("centers.nombre", "names no site -> no centre")
        return None

    key = _site_key(entry, index.postcodes)
    if tally is not None:
        resolution = resolve_postcode(
            entry.cod_postal, evidence_key(entry), entry.localidad,
            index.postcodes)
        if resolution.basis is not None:
            tally.applied("centers.cod_postal",
                             "digit recovered ({})".format(resolution.basis))

    regions = index.regions.get(key, {})
    row = {
        "center_key": entry.identity,
        "referencia": entry.referencia,
        "nombre": _most_frequent(index.names.get(key), entry.nombre),
        # '' and not NULL: both are part of the UNIQUE, and SQL counts every
        # NULL as distinct, so a NULL here would duplicate exactly the sites
        # whose locality or postcode is unknown.
        # The place's spelling, not this site's: see build_center_index.
        "localidad": _best_spelling(index.place_names.get(key[1])) or "",
        "cod_postal": key[2],
        "provincia": _most_frequent(
            {v: n for (f, v), n in regions.items() if f == "provincia"}),
        "ccaa": _most_frequent(
            {v: n for (f, v), n in regions.items() if f == "ccaa"}),
    }
    return key, row


def study_centers(record):
    """The raw centro dicts of one study, in source order.

    centros.centro is a list in 11,847/11,847 records, never a bare object.
    147 studies list none.
    """
    return (record.get("centros") or {}).get("centro") or []
