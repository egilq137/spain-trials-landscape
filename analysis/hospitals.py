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
from analysis.volume import GRID, INK, MUTED, SERIES, SURFACE

Hospital = collections.namedtuple(
    "Hospital", "codcnh nombre municipio provincia cod_postal camas clase "
                "dependencia complejo")

Match = collections.namedtuple(
    "Match", "hospital closest score runner_up verdict why")
# `hospital` is the accepted match and is None unless one was accepted;
# `closest` is the best candidate whatever the verdict, because a rejection
# a reader cannot see the near-miss for is one they cannot judge.

# The four things this module is able to say. They are deliberately about the
# *evidence*, not about the centre: a catalogue of hospitals cannot establish
# that something is not a hospital, only that nothing in it resembles the
# name. Absence of a match is not evidence of absence, and the vocabulary
# should not pretend otherwise.
MATCHED = "matched"
AMBIGUOUS = "ambiguous"        # two catalogue entries the name cannot separate
NEAR_MISS = "near miss"        # something similar exists; worth a reading
NO_CANDIDATE = "no candidate"  # nothing in the catalogue resembles it

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

# Below the floor, one more line: is there anything down there worth reading?
#
# Measured on the rows the matcher refuses, 1,378 of the 1,978 score under
# 0.25 and carry 3.9% of the trial-site links between them -- the catalogue
# holds nothing resembling those names, and most of them are research
# institutes, health centres and private clinics it does not list. The 517
# between 0.25 and the floor are a different animal: a real hospital under a
# name the rule could not follow hides there (`HOSPITAL UNIVERSITARIO ALVARO
# CUNQUEIRO`, listed under its complex in Vigo) beside things that genuinely
# are not hospitals (`Vall d'Hebron Institut de Recerca`).
#
# **This line sorts the reading, not the world.** It cannot be calibrated
# against the coded rows, because those all have a right answer by
# construction; it was read off the distribution above and chosen where the
# volume falls away.
NEAR = 0.25

# The same word in another language, folded onto one token. Only language
# variants and connectors belong here -- **no hospital is named in this
# table**, which is what stops it from being tuned until the evaluation
# passes. Add to it when a new spelling appears, not when a match fails.
#
# `quironsalud` is the one entry that is not a language variant, and it is
# worth stating why it is still not a hospital. The group was Quirón; it
# merged with IDC Salud in 2016 and renamed itself Quirónsalud, so the 2024
# catalogue writes the new name in 35 entries while REEC rows still carry the
# old one. `similarity` compares whole words as a set -- deliberately, since
# the containment measure it replaced invented a match -- so `quiron` and
# `quironsalud` are simply two different words and a name sharing everything
# else scores 0.50. One line covers all 35, and it names a company rather
# than a hospital.
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
    "quironsalud": "quiron",
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



# ---------------------------------------------------------------------------
# The rows a person decided
# ---------------------------------------------------------------------------
# The matcher refuses 83 rows as ambiguous -- two catalogue entries score
# within MARGIN of each other and the name cannot separate them -- and those
# rows carry 6.6% of the trial-site links, so they are worth a reading rather
# than a better rule. They were read on docs/hospital-ambiguous.html on
# 16 September 2026; these are the answers.
#
# Keyed the way the form grouped them, on the folded name and the normalised
# town, so a decision covers every spelling REEC files the centre under.
#
# **ANSWERS overrules the score, and that is the point.** A decision here is
# a claim about the world that the string measure could not reach, so each
# one says why and can be checked against the official name above it. Three
# kinds recur:
#
#   a campus  -- the catalogue lists one institution once per site, and the
#                name is the same on all of them (Institut Catala
#                d'Oncologia, Sant Joan de Deu)
#   a rename  -- REEC files the hospital under a name it no longer uses
#                (Juan Canalejo, Hospital General Universitario de Alicante)
#   a complex -- REEC names the complex and the catalogue lists its members,
#                which the `complejo` column makes checkable
#
# A `codcnh` of None is a decision too: the centre is not in the catalogue.
Answer = collections.namedtuple("Answer", "codcnh why")

ANSWERS = {
    # Institut Catalá D'Oncologia - Hospital Duran I Reynals  [c01]
    ('institut catala d oncologia',
     'hospitalet de llobregat'): Answer('081461',
        'ICO is catalogued once per campus; Duran i Reynals is the '
        "L'Hospitalet one"),
    # Hospital Universitario HM Sanchinarro  [c02]
    ('hospital universitario madrid sanchinarro',
     'madrid'): Answer('281225',
        'the catalogue prefixes the chain, HM Sanchinarro'),
    # Hospital Universitario de Salamanca. Complejo Asistencial Universitario de Salmanca  [c03]
    ('hospital universitario de salamanca',
     'salamanca'): Answer('370037',
        "the complex's acute hospital, not Los Montalvos"),
    # Hospital Universitario de Burgos. Complejo Asistencial Universitario de Burgos  [c07]
    ('hospital universitario de burgos',
     'burgos'): Answer('090155',
        "the complex's own hospital in Burgos"),
    # Hospital Universitario Clínico San Cecilio  [c08]
    ('hospital san cecilio',
     'granada'): Answer('180150',
        'San Cecilio is the Granada clinical hospital'),
    # Fundacio Hospital Sant Joan de Deu (Martorell)  [c09]
    ('fundacio hospital sant joan de deu',
     'martorell'): Answer('080898',
        'the Martorell foundation has its own entry'),
    # Hospital Provincial de Zamora Complejo Asistencial de Zamora  [c10]
    ('complejo asistencial de zamora',
     'zamora'): Answer('490028',
        'every tied candidate belongs to the Zamora complex'),
    # Benito Menni, Complex Assistencial En Salut Mental  [c15]
    ('benito menni complex assistencial en salut mental',
     'sant boi de llobregat'): Answer('080977',
        'Sant Boi, not the Granollers unit of the same name'),
    # Hospital Universitario Dr. Peset Aleixandre  [c17]
    ('hospital universitario doctor peset',
     'valencia'): Answer('460023',
        'Doctor Peset, Valencia'),
    # Hospital Universitario de Jaén  [c18]
    ('complejo hospitalario de jaen',
     'jaen'): Answer('230011',
        "the complex's university hospital in Jaen"),
    # Hospital Universitario La Paz  [c19]
    ('fundacion para la investigacion biomedica del hospital universitario la paz',
     'madrid'): Answer('280014',
        "the foundation is La Paz's research arm"),
    # Hospital Universitari Germans Trías I Pujol de Badalona  [c21]
    ('hospital germans trias i pujol',
     'badalona'): Answer('080667',
        'Germans Trias i Pujol, Badalona'),
    # HM Modelo-Belen  [c22]
    ('hospital hm modelo',
     'coruna'): Answer('150354',
        'HM Modelo, A Coruna'),
    # Hospital Universitario de Salamanca. Complejo Asistencial Universitario de Salmanca  [c23]
    ('complejo asistencial universitario de salamanca',
     'salamanca'): Answer('370037',
        "the Salamanca complex's acute hospital"),
    # Hospital General de Vic  [c26]
    ('hospital universitari de vic',
     'vic'): Answer('081108',
        'Hospital Universitari de Vic'),
    # Hospital Quirón Salud Valle del Henares  [c27]
    ('hospital quironsalud valle del henares',
     'torrejon de ardoz'): Answer('281456',
        'Quironsalud Valle del Henares'),
    # Hospital Universitario de Torrevieja  [c28]
    ('hospital de torrevieja',
     'alicante'): Answer('030339',
        'Torrevieja; REEC files the province as the town'),
    # Complexo Hospitalario Universitario de Santiago  [c31]
    ('complejo hospitalario universitario',
     'santiago de compostela'): Answer('150200',
        'the Santiago de Compostela complex'),
    # Hospital Universitario de La Princesa  [c32]
    ('fundacion para la investigacion biomedica del hospital universitario la princesa',
     'madrid'): Answer('280127',
        "the foundation is La Princesa's research arm"),
    # Hospital Provincial de Zamora Complejo Asistencial de Zamora  [c33]
    ('hospital provincial de zamora',
     'zamora'): Answer('490028',
        'Hospital Provincial de Zamora by name'),
    # Consorcio Hospital General Universitario de Valencia  [c34]
    ('hospital general de valencia',
     'valencia'): Answer('460060',
        'the Consorcio Hospital General Universitario'),
    # Hospital Clínico Universitario de Valencia  [c35]
    ('universidad de valencia',
     'valencia'): Answer('460044',
        "the Clinico is the Universitat de Valencia's"),
    # Hospital Universitario de Salamanca. Complejo Asistencial Universitario de Salmanca  [c37]
    ('hospital universitario de salamanca complejo asistencial universitario de',
     'salamanca'): Answer('370037',
        "the Salamanca complex's acute hospital"),
    # Hospital Quironsalud Zaragoza  [c38]
    ('hospital quiron zaragoza',
     'zaragoza'): Answer('500129',
        'Quiron Zaragoza'),
    # Hospital Universitario y Politécnico La Fe  [c39]
    ('hospital universitario la fe de valencia',
     'valencia'): Answer('460018',
        'La Fe, Valencia'),
    # Hospital Universitario San Pedro  [c40]
    ('complejo hospitalario san pedro hospital de la rioja',
     'logro?o'): Answer('260027',
        "San Pedro is the complex's acute hospital"),
    # Hospital Universitari Quirón Dexeus  [c41]
    ('hospital quiron',
     'barcelona'): Answer('080446',
        'Quiron Dexeus, Barcelona'),
    # Hospital Santa Maria del Rosell  [c42]
    ('hospital general universitario santa maria del rosell',
     'murcia'): Answer('300145',
        'Santa Maria del Rosell is in Cartagena; the name decides and '
        'REEC files the province as the town'),
    # Hospital Quironsalud Málaga  [c43]
    ('hospital quiron malaga',
     'malaga'): Answer('290449',
        'Quiron Malaga'),
    # Hospital Universitario de La Ribera  [c46]
    ('hospital ribera salud',
     'valencia'): Answer('460351',
        'Ribera Salud runs La Ribera in Alzira; the name decides '
        'against the town'),
    # Hospital Quironsalud Zaragoza  [c47]
    ('hospital quiron de zaragoza',
     'zaragoza'): Answer('500129',
        'Quiron Zaragoza'),
    # Hospital Universitari Mutua de Terrassa  [c50]
    ('hospital mutua de terrassa',
     'terrassa'): Answer('081094',
        'Mutua de Terrassa'),
    # Hospital Universitario Quironsalud Madrid  [c51]
    ('hospital universitario quiron madrid',
     'pozuelo de alarcon'): Answer('281203',
        'Quironsalud Madrid, in Pozuelo'),
    # Hospital Quirón Salud Valle del Henares  [c53]
    ('hospital quironsalud valle de henares',
     'torrejon de ardoz'): Answer('281456',
        'Quironsalud Valle del Henares'),
    # Hospital de Sant Joan de Deu (Manresa)  [c54]
    ('hospital san joan de deu',
     'manresa'): Answer('080863',
        'Sant Joan de Deu Manresa'),
    # Hospital G. Universitario J.M. Morales Meseguer  [c56]
    ('hospital general universitario morales meseguer',
     'murcia'): Answer('300269',
        'Morales Meseguer, Murcia'),
    # Hospital 9 de Octubre  [c57]
    ('hospital vithas valencia 9 de octubre',
     'valencia'): Answer('460291',
        'Vithas Valencia 9 de Octubre'),
    # Hospital Universitario de Salamanca. Complejo Asistencial Universitario de Salmanca  [c59]
    ('hospital clinico universitario de salamanca complejo asistencial univ sa',
     'salamanca'): Answer('370037',
        "the Salamanca complex's acute hospital"),
    # Hospital Quironsalud Málaga  [c60]
    ('quiron hospital malaga',
     'malaga'): Answer('290449',
        'Quiron Malaga'),
    # Hospital Santa Maria del Rosell  [c61]
    ('hospital general universitario santa maria del rosell',
     'cartagena'): Answer('300145',
        'Santa Maria del Rosell, Cartagena'),
    # Hospital San Rafael  [c62]
    ('el hospital universitario san rafael de madrid',
     'madrid'): Answer('280339',
        'Hospital San Rafael, Madrid'),
}


# Read but not decided. Everything below was looked up in the catalogue in
# answer to a question the form came back with -- twenty cards marked
# "cannot tell", plus four whose answer sat in a different municipality than
# the row it was chosen for.
#
# **Nothing here changes what the code does.** `match` ignores PROPOSED; the
# form pre-ticks it, states the reason on the card, and the answer moves to
# ANSWERS only when somebody confirms it. A proposal that quietly behaved
# like a decision would be a decision nobody made.
PROPOSED = {
    # Juaneda Miramar  [c36]
    ('juaneda',
     'palma de mallorca'): Answer('070131',
        'the decision on this card was Clinica Juaneda, but REEC files this '
        'row itself under CODCNH 070131 and postcode 07011, which are '
        'Juaneda Miramar; Clinica Juaneda is 070110 at 07014'),
    # Institut Catalá D'Oncologia - Hospital Germans Trías I Pujol  [c04]
    ('institut catala d oncologia',
     'badalona'): Answer('081694',
        'ICO Badalona is the Germans Trias campus, as ICO '
        "L'Hospitalet is Duran i Reynals"),
    # Hospital General Universitario Dr. Balmis  [c05]
    ('hospital general universitario de alicante',
     'alicante'): Answer('030015',
        'renamed: the Hospital General Universitario de Alicante '
        "became Dr. Balmis in 2021. Sant Joan d'Alacant is a "
        'different hospital in another town'),
    # Institut Catalá D'Oncologia Girona - Hospital Josep Trueta  [c06]
    ('institut catala d oncologia',
     'girona'): Answer('170299',
        'ICO Girona is the Josep Trueta campus'),
    # Hospital Universitario de Cáceres  [c11]
    ('complejo hospitalario de caceres',
     'caceres'): Answer('100115',
        "the catalogue's complejo column says Hospital Universitario "
        'de Caceres belongs to the Complejo Hospitalario de Caceres; '
        'Quironsalud belongs to none'),
    # Complexo Hospitalario Universitario de Vigo  [c12]
    ('hospital xeral de vigo',
     'vigo'): Answer('360368',
        'the Xeral was absorbed into the Vigo complex and has no '
        'entry of its own; Fremap scores on the word Vigo'),
    # Hospital Universitario San Pedro  [c13]
    ('complejo hospitalario san pedro hospital de la rioja',
     'logrono'): Answer('260027',
        'the same row as c40, split by mojibake in the town'),
    # Complexo Hospitalario Universitario A Coruña  [c14]
    ('complejo hospitalario universitario juan canalejo',
     'coruna'): Answer('150011',
        'renamed: Juan Canalejo became the Complexo Hospitalario '
        'Universitario A Coruna'),
    # Hospital de Sant Joan de Deu.  [c16]
    ('fundacio sant joan de deu',
     'esplugues de llobregat'): Answer('080713',
        'the row is in Esplugues and so is this hospital; the '
        'Martorell foundation is a different one'),
    # Clínica Universidad de Navarra  [c20]
    ('universidad de navarra',
     'pamplona'): Answer('310060',
        "the university's own hospital is the Clinica Universidad de "
        'Navarra; the Hospital Universitario de Navarra is the public '
        'complex'),
    # Hospital Rio Carrión. Complejo Asistencial Universitario de Palencia.  [c24]
    ('complejo asistencial universitario de palencia',
     'palencia'): Answer('340014',
        'both tied candidates carry the Palencia complex in their '
        'complejo column, so the complex is catalogued -- Rio Carrion '
        'is its acute hospital'),
    # Hospital Santa Barbara ,Complejo Asistencial de Soria  [c25]
    ('complejo asistencial de soria',
     'soria'): Answer('420011',
        'both belong to the Complejo Asistencial de Soria; Santa '
        'Barbara is its acute hospital'),
    # Hospital Universitario y Politécnico La Fe  [c29]
    ('hospital la fe de valencia',
     'valencia'): Answer('460018',
        'La Fe by name, and the same answer as c39'),
    # Institut Catalá D'Oncologia - Hospital Duran I Reynals  [c30]
    ('institut catala d oncologia',
     'institut catala d oncologia l hospitalet'): Answer('081461',
        "the town column holds the centre's own name, and it says "
        "L'Hospitalet"),
    # not in the catalogue  [c44]
    ('hospital odontologic universitat de barcelona',
     'barcelona'): Answer(None,
        "the Universitat de Barcelona's dental hospital is a "
        'university clinic and is not in the catalogue; Hospital de '
        'Barcelona is an unrelated private hospital'),
    # Institut Catalá D'Oncologia - Hospital Germans Trías I Pujol  [c45]
    ('institut catala d oncologia',
     'institut catala d oncologia badalona'): Answer('081694',
        "the town column holds the centre's own name, and it says "
        'Badalona'),
    # Hospital Universitario Quironsalud Madrid  [c48]
    ('hospital universitario quiron',
     'madrid'): Answer('281203',
        'the same centre as c51: a damaged postcode, 28.223 for '
        '28223. The right answer was never on the card'),
    # Hospital Universitario HM Monteprincipe  [c49]
    ('hospital de madrid monteprincipe',
     'boadilla del monte'): Answer('281090',
        "HM Monteprincipe, in the row's own town"),
    # not in the catalogue  [c52]
    ('hospital de alta resolucion de ecija',
     'ecija'): Answer(None,
        'the catalogue has no entry in Ecija at all'),
    # not in the catalogue  [c55 and c58, one row since the article went]
    ('hospital odontologic universitat de barcelona',
     'hospitalet de llobregat'): Answer(None,
        'the same dental hospital as c44; Hospital de Barcelona is a '
        'different hospital in a different town'),
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
            return Match(hospital, hospital, 1.0, 0.0, MATCHED,
                         "alias: " + alias.why)

    answer = ANSWERS.get((" ".join(fold(nombre)), _town(localidad)))
    if answer is not None:
        if answer.codcnh is None:
            return Match(None, None, 0.0, 0.0, NO_CANDIDATE,
                         "read: " + answer.why)
        hospital = index.by_code[answer.codcnh]
        return Match(hospital, hospital, 1.0, 0.0, MATCHED,
                     "read: " + answer.why)

    candidates = index.candidates(localidad, cod_postal)
    if not candidates:
        return Match(None, None, 0.0, 0.0, NO_CANDIDATE,
                     "no hospital shares its postcode, town or province")

    ranked = sorted(((similarity(nombre, hospital.nombre), hospital)
                     for hospital in candidates), key=lambda pair: -pair[0])
    score, best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0

    if score < NEAR:
        return Match(None, best, score, runner_up, NO_CANDIDATE,
                     "best of {} candidates scores {:.2f}: nothing in the "
                     "catalogue resembles this name".format(
                         len(candidates), score))
    if score < ACCEPT:
        return Match(None, best, score, runner_up, NEAR_MISS,
                     "best of {} candidates scores {:.2f}, under the {:.2f} "
                     "floor".format(len(candidates), score, ACCEPT))
    if score - runner_up < MARGIN:
        return Match(None, best, score, runner_up, AMBIGUOUS,
                     "{:.2f} against {:.2f} for the next candidate is too "
                     "close to call".format(score, runner_up))
    return Match(best, best, score, runner_up, MATCHED,
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


def codes_by_centre(con, index):
    """{center_id: codcnh} for the rows a hospital was identified for.

    The shape `geography.identities` needs, and the only thing it is given:
    a centre with no confident match is simply absent, and falls back to the
    rules that were there before.

    Separate from `match_centres` because the two answer different questions
    -- that one carries the evidence a person reads, this one carries the
    conclusion a merge acts on -- and because a merge wants every centre,
    not the ones active in a window.
    """
    return {center_id: result.hospital.codcnh
            for center_id, result in (
                (row[0], match(index, row[1], row[2], row[3]))
                for row in con.execute(
                    "SELECT center_id, nombre, localidad, cod_postal "
                    "FROM centers"))
            if result.hospital is not None}


def review_page(matched, shown=120):
    """The page the matches get read on, in the shape of the sibling pages.

    Split by verdict rather than into matched and everything-else, because
    those outcomes are not one thing. A catalogue of hospitals *should* fail
    to match a research institute or a health centre, and filing that beside
    a genuine miss under one heading both overstates the work left and
    buries the rows that actually need reading.

    So three tables are printed and one bucket is only counted: the rows
    with no plausible candidate are an answer, not a queue.
    """
    import html

    groups = collections.defaultdict(list)
    for row in matched:
        groups[row[4].verdict].append(row)
    trials = sum(row[3] for row in matched) or 1

    def share(group):
        return 100 * sum(row[3] for row in group) / trials

    def table(group, limit, last_column):
        opening = ("<table><thead><tr><th>REEC centre</th><th>Town</th>"
                   "<th class='n'>Trials</th><th>{}</th><th>Why</th></tr>"
                   "</thead><tbody>".format(last_column))
        body = []
        for center_id, nombre, localidad, count, result in group[:limit]:
            hospital = result.hospital or result.closest
            official = hospital.nombre if hospital else "—"
            code = hospital.codcnh if hospital else ""
            body.append(
                "<tr><td>{}</td><td>{}</td><td class='n'>{:,}</td>"
                "<td>{}</td><td class='tag'>{}</td></tr>".format(
                    html.escape(nombre), html.escape(localidad or "—"),
                    count,
                    "{} {}".format(code, html.escape(official)).strip(),
                    html.escape(result.why)))
        return opening + "".join(body) + "</tbody></table>"

    accepted = groups[MATCHED]
    ambiguous = groups[AMBIGUOUS]
    near = groups[NEAR_MISS]
    nothing = groups[NO_CANDIDATE]

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
        "<p><strong>Nothing here merges anything.</strong> A match says which "
        "hospital a row is, and only that. Not every row has one: the "
        "catalogue lists hospitals, and a trial site can perfectly well be a "
        "research institute, a health centre or a private clinic that belongs "
        "in none of these tables. The verdicts below are about the evidence "
        "rather than about the centre &mdash; nothing in a catalogue of "
        "hospitals can establish that something <em>is not</em> one.</p>",

        "<h2>{:,} matched, carrying {:.0f}% of the trial-site links</h2>"
        .format(len(accepted), share(accepted)),
        "<p>Read the score: 1.00 is the same words in another order or "
        "another language. Anything near the {:.2f} floor is worth an "
        "eye.</p>".format(ACCEPT),
        table(accepted, shown, "Matched to"),

        "<h2>{:,} ambiguous, carrying {:.0f}%</h2>".format(
            len(ambiguous), share(ambiguous)),
        "<p>These score above the floor &mdash; the hospital is almost "
        "certainly in the catalogue &mdash; but two entries score within "
        "{:.2f} of each other and the name cannot separate them, usually one "
        "hospital the catalogue lists once per campus. <strong>The densest "
        "rows on the page</strong>, and the only ones where the matcher is "
        "asking a question rather than reporting a result.</p>".format(MARGIN),
        table(ambiguous, shown, "Closest"),

        "<h2>{:,} near misses, carrying {:.0f}%</h2>".format(
            len(near), share(near)),
        "<p>Something in the catalogue resembles the name without reaching "
        "the floor, so this is the pile worth a reading: a real hospital "
        "under a name the rule could not follow sits here beside an "
        "institute that correctly does not match. The fix for the first kind "
        "is a spelling the synonym table has not met, or a line in "
        "<code>ALIASES</code>.</p>",
        table(near, shown, "Closest"),

        "<h2>{:,} with no plausible candidate, carrying {:.0f}%</h2>".format(
            len(nothing), share(nothing)),
        "<p>Nothing in the same postcode, town or province scores {:.2f} "
        "against these names. <strong>Not a queue.</strong> This is the "
        "matcher's answer for a site the state does not catalogue as a "
        "hospital, and printing {:,} rows of it would make the page longer "
        "without making it more true. It is also the honest size of the "
        "exclusion idea: limiting the analysis to recognised hospitals would "
        "cost these {:.0f}% of links, not everything the matcher "
        "declined.</p>".format(NEAR, len(nothing), share(nothing)),
        "</body></html>"])


# ---------------------------------------------------------------------------
# The ambiguous rows, as a form
# ---------------------------------------------------------------------------
# 83 rows the matcher could not separate carry 6.6% of the trial-site links --
# the densest refusal on the page and the only one where the answer is a
# decision rather than a rule. They collapse to 62 distinct name-and-town
# cases, which is few enough for a person to read, and the page below is what
# they get read on: one card each, the candidates as radio buttons, and a
# button that copies the answers back out as text.
#
# Nothing here decides anything. The page proposes; ANSWERS is where a read
# decision would be written down, the same way ALIASES records a read alias.

Case = collections.namedtuple(
    "Case", "key nombre localidad cod_postal trials rows candidates "
            "suggested reason")


def ambiguous_cases(con, index, since=None):
    """[Case], busiest first: the rows a person has to separate.

    Grouped on the folded name and town, because REEC spells the same centre
    several ways -- `Institut Catala D'oncologia` and `Institut Catala
    D’oncologia` in Badalona are one question asked twice, and a form
    that asks it twice gets two chances to be answered differently.
    """
    from analysis.geography import normalise_town
    from analysis.volume import COVERAGE_START

    floor = "{}-01-01".format(COVERAGE_START if since is None else since)
    rows = con.execute(
        """SELECT c.nombre, c.localidad, c.cod_postal,
                  count(DISTINCT s.identificador) AS trials
             FROM centers c
             LEFT JOIN study_centers sc ON sc.center_id = c.center_id
             LEFT JOIN studies s ON s.identificador = sc.study_id
                  AND s.fecha_autorizacion_aemps >= ?
         GROUP BY c.center_id""", (floor,))

    grouped = collections.OrderedDict()
    for nombre, localidad, cod_postal, trials in rows:
        if match(index, nombre, localidad, cod_postal).verdict != AMBIGUOUS:
            continue
        key = (" ".join(fold(nombre)), normalise_town(localidad or ""))
        if key not in grouped:
            grouped[key] = [nombre, localidad, cod_postal, 0, 0]
        grouped[key][3] += trials
        grouped[key][4] += 1

    cases = []
    for index_of, (key, value) in enumerate(grouped.items(), start=1):
        nombre, localidad, cod_postal, trials, count = value
        ranked = sorted(
            ((similarity(nombre, hospital.nombre), hospital)
             for hospital in index.candidates(localidad, cod_postal)),
            key=lambda pair: -pair[0])[:5]
        proposal = PROPOSED.get(key)
        if proposal is not None:
            suggested, reason = proposal.codcnh or "NONE", proposal.why
        else:
            suggested = _same_town(ranked, localidad)
            reason = "the only tied candidate in this town"
        cases.append(Case("c{:02d}".format(index_of), nombre, localidad,
                          cod_postal, trials, count, ranked, suggested,
                          reason if suggested else ""))
    cases.sort(key=lambda case: -case.trials)
    # Renumbered after sorting so the ids on the page read in the order the
    # cards appear; an id that jumps around is one more thing to misread.
    return [case._replace(key="c{:02d}".format(number))
            for number, case in enumerate(cases, start=1)]


def _same_town(ranked, localidad):
    """The tied candidate in the row's own municipality, if exactly one is.

    A suggestion, not a rule, and it is only offered when it is unambiguous:
    the catalogue lists the Institut Catala d'Oncologia once per campus, so
    the Girona row's answer is the Girona entry even though the L'Hospitalet
    one scores higher on the name. Where two tied candidates share the town,
    or none does, the card opens with nothing chosen.
    """
    from analysis.geography import normalise_town

    if not ranked:
        return None
    town = normalise_town(localidad or "")
    if not town:
        return None
    tied = [hospital for score, hospital in ranked
            if score >= ranked[0][0] - MARGIN]
    here = [hospital for hospital in tied
            if normalise_town(hospital.municipio) == town]
    return here[0].codcnh if len(here) == 1 else None


FORM_SCRIPT = """
const KEY = 'hospital-ambiguous-v1';

// Every read and write is guarded. A page opened straight off the disk can
// have no storage to speak of -- the browser refuses it on some origins, and
// a private window hands back nothing -- and the form has to keep working
// when that happens. Losing the saved answers is a nuisance; a page whose
// buttons do not respond looks broken.
function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || '{}'); }
  catch (e) { return {}; }
}
function store() {
  try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
}
const saved = load();

function progress() {
  const cards = document.querySelectorAll('.case');
  let done = 0, links = 0, total = 0;
  cards.forEach(card => {
    const n = Number(card.dataset.trials);
    total += n;
    const picked = card.querySelector('input:checked');
    card.classList.toggle('done', !!picked);
    if (picked) { done += 1; links += n; }
  });
  document.getElementById('progress').textContent =
    done + ' of ' + cards.length + ' decided \\u2014 ' +
    links.toLocaleString() + ' of ' + total.toLocaleString() + ' trial-links';
  document.getElementById('copy').disabled = done === 0;
}

function restore() {
  Object.entries(saved).forEach(([name, value]) => {
    const input = document.querySelector(
      'input[name="' + name + '"][value="' + value + '"]');
    if (input) input.checked = true;
  });
  document.querySelectorAll('textarea').forEach(box => {
    if (saved['note:' + box.name]) box.value = saved['note:' + box.name];
  });
  progress();
}

document.addEventListener('change', event => {
  if (event.target.type !== 'radio') return;
  saved[event.target.name] = event.target.value;
  store();
  progress();
});

document.addEventListener('input', event => {
  if (event.target.tagName !== 'TEXTAREA') return;
  saved['note:' + event.target.name] = event.target.value;
  store();
});

function decisions() {
  const lines = ['HOSPITAL-AMBIGUOUS-DECISIONS v1'];
  document.querySelectorAll('.case').forEach(card => {
    const picked = card.querySelector('input:checked');
    if (!picked) return;
    const note = card.querySelector('textarea').value.trim();
    lines.push(card.dataset.id + ' = ' + picked.value +
               '   # ' + card.dataset.name +
               (note ? '  //  ' + note : ''));
  });
  return lines.join('\\n');
}

document.getElementById('copy').addEventListener('click', () => {
  const text = decisions();
  navigator.clipboard.writeText(text).then(() => {
    document.getElementById('copy').textContent = 'Copied \\u2014 paste it back';
  }, () => {
    document.getElementById('dump').textContent = text;
    document.getElementById('dump').hidden = false;
  });
});

document.getElementById('show').addEventListener('click', () => {
  const box = document.getElementById('dump');
  box.textContent = decisions();
  box.hidden = !box.hidden;
});

document.getElementById('hide-done').addEventListener('change', event => {
  document.body.classList.toggle('hide-done', event.target.checked);
});

restore();
"""

FORM_STYLE = """
.bar {{ position:sticky; top:0; z-index:5; background:{surface};
        border-bottom:1px solid {grid}; padding:10px 0 12px; margin:0 0 18px;
        display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
.bar button {{ font:inherit; font-size:13px; padding:6px 13px; border-radius:6px;
        border:1px solid {accent}; background:{accent}; color:{surface};
        cursor:pointer; }}
.bar button.ghost {{ background:transparent; color:{accent}; }}
.bar button[disabled] {{ opacity:.45; cursor:default; }}
#progress {{ font-variant-numeric:tabular-nums; font-weight:600; }}
.bar label {{ font-size:13px; color:{muted}; }}
.case {{ border:1px solid {grid}; border-left:4px solid {grid};
        border-radius:8px; padding:12px 15px; margin:0 0 12px; }}
.case.done {{ border-left-color:{accent}; }}
body.hide-done .case.done {{ display:none; }}
.case h3 {{ font-size:15px; margin:0 0 2px; }}
.case .where {{ color:{muted}; font-size:12.5px; margin:0 0 10px; }}
.opt {{ display:block; padding:4px 0; font-size:13.5px; }}
.opt input {{ margin-right:8px; }}
.opt .score {{ font-variant-numeric:tabular-nums; color:{accent};
        font-weight:600; margin-right:8px; }}
.opt .facts {{ color:{muted}; font-size:12.5px; }}
.opt.suggested {{ font-weight:600; }}
.reason {{ color:{muted}; font-size:12.5px; margin:9px 0 0;
        padding-left:11px; border-left:2px solid {accent}; }}
.case textarea {{ width:100%; box-sizing:border-box; margin-top:8px;
        font:inherit; font-size:12.5px; padding:5px 7px; border-radius:5px;
        border:1px solid {grid}; background:transparent; color:inherit;
        resize:vertical; min-height:30px; }}
#dump {{ white-space:pre-wrap; font-family:ui-monospace, monospace;
        font-size:12.5px; border:1px solid {grid}; border-radius:6px;
        padding:12px; margin-top:16px; }}
"""


def ambiguous_page(cases):
    """The form. One card per case, and the answers come back as text.

    A form rather than a table because the outcome is a decision per row and
    a table cannot take one. Answers are kept in `localStorage`, so the page
    survives a reload; `Copy decisions` is what leaves the browser.
    """
    import html

    cards = []
    for case in cases:
        options = []
        for score, hospital in case.candidates:
            suggested = hospital.codcnh == case.suggested
            options.append(
                "<label class='opt{}'><input type='radio' name='{}' "
                "value='{}'{}><span class='score'>{:.2f}</span>{} "
                "<span class='facts'>{} beds \u00b7 {} \u00b7 "
                "{}</span></label>".format(
                    " suggested" if suggested else "", case.key,
                    hospital.codcnh, " checked" if suggested else "", score,
                    html.escape(hospital.nombre), hospital.camas or "?",
                    html.escape(hospital.clase),
                    html.escape(hospital.municipio)))
        none = case.suggested == "NONE"
        options.append(
            "<label class='opt{}'><input type='radio' name='{}' value='NONE'{}>"
            "<span class='facts'>None of these \u2014 not a hospital the "
            "catalogue lists</span></label>".format(
                " suggested" if none else "", case.key,
                " checked" if none else ""))
        options.append(
            "<label class='opt'><input type='radio' name='{}' value='UNSURE'>"
            "<span class='facts'>Cannot tell from here</span></label>".format(
                case.key))
        cards.append(
            "<div class='case' data-id='{}' data-trials='{}' data-name=\"{}\">"
            "<h3>{}</h3><p class='where'>{} \u00b7 {} \u00b7 <b>{:,}</b> "
            "trials{}</p>{}{}<textarea name='{}' placeholder='why, if it is "
            "not obvious'></textarea></div>".format(
                case.key, case.trials,
                html.escape(case.nombre.replace('"', "'")),
                html.escape(_readable(case.nombre)),
                html.escape(case.localidad or "\u2014"),
                html.escape(case.cod_postal or "no postcode"), case.trials,
                "" if case.rows == 1 else
                " \u00b7 {} REEC spellings".format(case.rows),
                "".join(options), _reason(case.reason), case.key))

    return "\n".join([
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Ambiguous hospital matches</title><style>",
        REVIEW_STYLE.format(surface=SURFACE, ink=INK, muted=MUTED, grid=GRID),
        FORM_STYLE.format(surface=SURFACE, muted=MUTED, grid=GRID,
                          accent=SERIES),
        "</style></head><body>",
        "<h1>Which hospital is this?</h1>",
        "<p>{} cases the matcher could not separate, busiest first. Each "
        "scores above the {:.2f} floor \u2014 the hospital is almost "
        "certainly one of the candidates \u2014 but two of them score within "
        "{:.2f} and the name cannot choose. Origen de los datos: Ministerio "
        "de Sanidad, Consumo y Bienestar Social; data updated 31 December "
        "2024.</p>".format(len(cases), ACCEPT, MARGIN),
        "<p><b>Pick one per card, then press Copy decisions and paste the "
        "result back into the conversation.</b> Each card opens with an "
        "answer already ticked and the reason for it stated underneath "
        "\u2014 a proposal to confirm or overrule, not a decision. Nothing "
        "pre-ticked has changed what the code does. Answers are saved in "
        "this browser as you go.</p>",
        "<div class='bar'><span id='progress'></span>",
        "<button id='copy' type='button' disabled>Copy decisions</button>",
        "<button id='show' class='ghost' type='button'>Show as text</button>",
        "<label><input type='checkbox' id='hide-done'> hide decided</label>",
        "</div>",
        "".join(cards),
        "<pre id='dump' hidden></pre>",
        "<script>", FORM_SCRIPT, "</script>",
        "</body></html>"])


def _reason(reason):
    """The line under the options saying why one of them is pre-ticked.

    A pre-ticked radio with no stated reason is an answer the reader has no
    way to disagree with, which makes confirming it worth nothing.
    """
    import html

    if not reason:
        return ""
    return ("<p class='reason'>Pre-ticked: {}. Overrule it if that is "
            "wrong.</p>".format(html.escape(reason)))


def _readable(nombre):
    from analysis.geography import display_name
    return display_name(nombre)
