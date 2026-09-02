"""Which spelling of an organisation gets shown.

`cleaning_rules.organisation_key` decides whether two values are the same
organisation. This decides what that organisation is called, which is a
different question with a different answer -- the key is unreadable by
design (`pfizerinc`), and the display column is what a dashboard prints.

PROJECT_SPEC 3.2c has said since the sponsors profile that `promotor` holds
"the most frequent cleaned spelling". The loader was storing the FIRST
spelling it happened to meet, which is not the same thing and produced
`Pfizer Inc., 235 East 42nd Street, New York, NY 10017` as the name of a
sponsor with 223 trials. Same build-an-index-then-resolve shape as
db/centers.py, and for the same reason: no single record knows which of its
spellings the rest of the corpus prefers.

Two preferences, in order:

  1. **A spelling the key rules did not have to cut.** If `organisation_key`
     trimmed a descriptive clause or a postal address off a value, that value
     carries commentary as well as a name -- so prefer one that survived
     whole. This is what turns 15 Pfizer address variants into `Pfizer Inc.`
     rather than into the commonest address.
  2. **Frequency**, ties broken alphabetically so a load is reproducible.
"""

import collections

from db.cleaning_rules import SPACES, _spaced_key, clean_text, organisation_key


def is_plain(name):
    """True when nothing was cut from this spelling to reach its key.

    A name the key rules left alone is a name; one they trimmed carried a
    clause or an address as well.
    """
    spaced = _spaced_key(name)
    if spaced is None:
        return False
    return organisation_key(name) == (SPACES.sub("", spaced) or None)


def build_name_index(values):
    """{organisation key: Counter of cleaned spellings} over the whole corpus.

    `values` is an iterable of raw organisation names -- promotors and
    funders together, because they are spelled the same ways and a sponsor
    that is also its own funder should not be shown two different ways.
    """
    index = collections.defaultdict(collections.Counter)
    for value in values:
        key, cleaned = organisation_key(value), clean_text(value)
        if key and cleaned:
            index[key][cleaned] += 1
    return index


def best_name(key, index, default=None):
    """The spelling to store for `key`, or `default` if it was never seen."""
    counter = index.get(key)
    if not counter:
        return default
    plain = collections.Counter({name: n for name, n in counter.items()
                                 if is_plain(name)})
    return min((plain or counter).items(),
               key=lambda item: (-item[1], item[0]))[0]
