"""Where a reader can go to read the study itself.

**REEC has no per-study URL to link to.** Its public site renders a study by
POSTing the identifier to `../buscador/setEstudioDetail` and expanding a card
in place, so the address bar still says `/reec/public/list.html` and there is
nothing to put in an href. That `buscador` endpoint is also the internal
search API PROJECT_SPEC 3.1 rules out as a source, and using it as a link
target would depend on the same undocumented interface.

So the link goes to the registry that issued the identifier instead, which is
a better destination anyway: it is the record REEC itself is republishing,
and it carries fields REEC does not -- including posted results, which
PROJECT_SPEC 3.3 wants and the REEC API does not carry.

`studies.es_ctis` already distinguishes the two, having been generated from
the identifier format (14 characters EudraCT, 17 CTIS). Note what it is being
used for here: this is a claim about *which register holds the record*, which
is exactly what 3.2d says the column means and all it means. Nothing here
groups by it or reads it as a regime.

Both patterns were checked against real identifiers from this database before
being written down, `2017-004836-13` and `2026-525913-30-00`.
"""

CTIS_URL = "https://euclinicaltrials.eu/ctis-public/view/{}"

# The /ES suffix asks for the Spanish record specifically -- an EudraCT trial
# has one per national authority, and the Spanish one names the AEMPS as the
# competent authority, which is the one this project is about.
EUDRACT_URL = "https://www.clinicaltrialsregister.eu/ctr-search/trial/{}/ES"


def public_url(identificador, es_ctis):
    """The public page for a study, in the register that issued its number."""
    template = CTIS_URL if es_ctis else EUDRACT_URL
    return template.format(identificador)


def register_of(es_ctis):
    """What to call the destination, so a link can say where it goes."""
    return "CTIS" if es_ctis else "EudraCT"
