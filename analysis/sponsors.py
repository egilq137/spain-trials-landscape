"""Who sponsors Spanish trials: industry, academia, or nobody we can tell.

The database stores the sponsor's name and nothing else -- deliberately, since
"industry" is a judgement and PROJECT_SPEC 3.2c keeps judgements out of the
schema. This module makes that judgement, and the shape of it is the usual one
for this project: **patterns generate candidates, an enumerated list decides.**

**Why patterns alone fail here.** Legal-form markers (S.A., GmbH, Inc.) and
institutional words (Hospital, Universidad, Fundación) between them settle
91.6% of trials. The 8.4% they miss are not a random tail -- they are
`Sanofi-Aventis Recherche & Developpement`, `Janssen - Cilag International`,
`Argenx`, `BioNTech SE`: some of the largest sponsors in the corpus, whose
names happen to carry no legal form. A rule tuned to catch them would also
catch academic cooperative groups, which is why the exceptions are listed by
hand instead.

**Three classes, not two.** Anything the markers and the list cannot settle is
`Unclassified` and is shown as such: 576 trials, 4.9%. Forcing them into one
of the two real classes would move 5% of the corpus into whichever answer the
chart was trying to make, which is exactly the failure this project keeps
trying not to commit. Industry 9,475 (80.1%), academic or public 1,783
(15.1%).

**And the unclassified share is not constant**, which matters more than its
size: it falls from 7.8% of trials in 2013 to 2.7% in 2026 as registry names
got more complete. So part of the rising industry share is trials becoming
classifiable rather than sponsors changing, and `share_figure` draws the
industry line twice -- once over all trials, once over the classified only.
The second is about half the move.

**Named individuals keep their trials and lose their names.** 54 sponsors are
a person -- `Dra. Cristina Avendaño Solá` -- and PROJECT_SPEC 3.2b says
named-individual data must not reach the dashboard. They are counted as
academic, because an investigator-sponsored trial is exactly non-commercial
research, and displayed as `Individual investigator`. No individual sponsors
more than two trials, so nothing analytical is lost. Reversible: it is one
label, in one place.
"""

import collections
import re

import plotly.graph_objects as go

from analysis.volume import COVERAGE_START, GRID, INK, MUTED, SERIES, SURFACE

INDUSTRY = "Industry"
ACADEMIC = "Academic or public"
UNCLASSIFIED = "Unclassified"
CLASSES = (INDUSTRY, ACADEMIC, UNCLASSIFIED)

# Legal forms first, then the words companies use when they have no legal form
# in the name. 'AB', 'AG' and 'SE' are matched as whole words only -- without
# that, 'AB' matches inside 'ABBOTT' and the rule stops meaning anything.
INDUSTRY_MARKERS = (
    r"\bS\.?A\.?U?\.?\b", r"\bS\.?L\.?U?\.?\b", r"\bInc\b", r"\bLtd\b",
    r"\bLimited\b", r"\bGmbH\b", r"\bLLC\b", r"\bAB\b", r"\bA/S\b",
    r"\bN\.?V\.?\b", r"\bB\.?V\.?\b", r"\bAG\b", r"\bPlc\b", r"\bS\.?p\.?A\b",
    r"\bCorp", r"\bCo\.", r"\bKG", r"\bOy\b", r"\bAp[Ss]\b", r"\bS\.?A\.?S\b",
    r"\bSE\b", r"\bSPRL\b", r"\bSARL\b", r"\bLLP\b", r"\bUnlimited\b",
    r"Pharma", r"Laboratori", r"Biotech", r"Bioscience", r"Therapeutic",
    r"\bSciences?\b", r"\bMedicament", r"\bBiopharm", r"Recherche",
    r"\bIndustri",
)

ACADEMIC_MARKERS = (
    r"\bHospital", r"\bUniversi", r"\bFundaci", r"\bFoundation\b",
    r"\bServicio\b", r"\bServei\b", r"\bSociedad\b", r"\bSociety\b",
    r"\bAsociaci", r"\bConsorci", r"CIBER", r"\bGrupo\b", r"\bCentro\b",
    r"\bCentre\b", r"\bAgencia\b", r"\bColegio\b", r"\bComplejo\b",
    r"\bCl[ií]nic", r"\bIIS\b", r"IDIBAPS", r"\bInstitut", r"\bAcadem",
    r"\bMinisteri", r"\bConsejer", r"\bGeneralitat", r"\bJunta\b",
    r"\bOrganisation\b", r"\bNetwork\b", r"\bCollege\b", r"\bTrust\b",
)

# Every sponsor with 5 or more trials that the markers cannot settle -- either
# because they match nothing or because they match both. 5 is where the tail
# starts: below it no sponsor holds enough trials to move a percentage point,
# and 472 one- and two-trial sponsors are not worth asserting facts about.
#
# Entries are things that can be checked, not guesses. Where a name is
# genuinely ambiguous it is left out and falls to Unclassified: see MedSIR
# below, which describes itself as an independent research organisation and
# is neither a pharmaceutical company nor a public institution.
HAND_CLASSIFIED = {
    # Companies whose names carry no legal form.
    "Janssen - Cilag International": INDUSTRY,
    "Janssen Cilag International": INDUSTRY,
    "Argenx": INDUSTRY,
    "argenx BVBA": INDUSTRY,
    "GlaxoSmithKline Biologicals": INDUSTRY,
    "Celgene International II Sàrl": INDUSTRY,
    "Abivax": INDUSTRY,
    "Eli Lilly and Company": INDUSTRY,
    "Ipsen Innovation": INDUSTRY,
    "sanofi-aventis Groupe": INDUSTRY,
    "Sanofi-Aventis Research & Development": INDUSTRY,
    "Sanofi Pasteur": INDUSTRY,
    "Laboratoires Thea": INDUSTRY,
    "Insmed Incorporated": INDUSTRY,
    # Companies whose names also carry an institutional word. A corporate
    # research arm is still the company: Servier's IRIS and Takeda's
    # development centre sponsor their employers' trials.
    "Institut De Recherches Internationales Servier IRIS": INDUSTRY,
    "Institut de Recherches Internationales Servier": INDUSTRY,
    "Takeda Development Centre Europe, Ltd.": INDUSTRY,
    "Instituto Grifols S.A.": INDUSTRY,
    "Kowa Research Institute Inc.": INDUSTRY,
    # Academic cooperative groups and public providers. These are the
    # sponsors that make the academic column mean anything: national and
    # European trial networks that run their own studies.
    "Unicancer": ACADEMIC,
    "SOLTI": ACADEMIC,
    "Solti Group": ACADEMIC,
    "ETOP (European Thoracic Oncology Platform)": ACADEMIC,
    "LYSARC": ACADEMIC,
    "Hemato-Oncologie voor Volwassenen Nederland (Hovon) Stichting": ACADEMIC,
    "European Myeloma Network B.V.": ACADEMIC,
    "Erasmus MC": ACADEMIC,
    "Assistance Publique Hopitaux De Paris": ACADEMIC,
    "Parc De Salut Mar": ACADEMIC,
    "Banc de Sang i Teixits": ACADEMIC,
    # EORTC, written out in three languages. It matches an academic marker
    # ('Organisation') and an industry one ('Recherche', which is there for
    # Sanofi's and Servier's French research arms), so the markers cancel
    # and the list has to settle it. The corpus also holds the short English
    # spelling, which the markers get right on their own.
    "Europese Organisatie Voor Onderzoek En Behandeling Van Kanker "
    "Organisation Europeenne Pour La Recherche Et Le Traitement Du Cancer "
    "European Organi": ACADEMIC,
}

# A name that opens with a personal title. 'Dr. Falk Pharma GmbH' is a German
# company and matches this too, which is why an industry marker wins: the
# title says how the name begins, the legal form says what the sponsor is.
PERSONAL_TITLE = re.compile(
    r"^(Dr|Dra|D|Da|Don|Doña|Prof|Sr|Sra|Mr|Ms|Mrs)\b\.?\s", re.IGNORECASE)
INDIVIDUAL = "Individual investigator"


def _matches(markers, name):
    return any(re.search(marker, name, re.IGNORECASE) for marker in markers)


def is_individual(name):
    """A person, rather than an organisation, sponsoring their own trial."""
    return bool(PERSONAL_TITLE.match(name)) and not _matches(INDUSTRY_MARKERS,
                                                             name)


def classify(name):
    """One of CLASSES. Hand list, then individuals, then family, then markers.

    The family table is consulted only where the markers cannot decide.
    `Novartis Farmacéutica` and `Janssen R&D Ireland` carry no legal form and
    no institutional word, so the markers give up on them, and membership of
    a corporate family settles it -- every family in FAMILIES is a company.
    That is worth 68 trials that were Unclassified before the families
    existed.

    It comes second, not first, because a marker is direct evidence about
    this entity while family membership is an inference from its name. A
    hypothetical `Fundación Servier` is a foundation whatever the pattern
    matches, and the ordering is what says so.
    """
    if name in HAND_CLASSIFIED:
        return HAND_CLASSIFIED[name]
    if is_individual(name):
        return ACADEMIC
    industry = _matches(INDUSTRY_MARKERS, name)
    academic = _matches(ACADEMIC_MARKERS, name)
    if industry != academic:
        return INDUSTRY if industry else ACADEMIC
    if family_of(name) in FAMILY_NAMES:
        return INDUSTRY
    # Both markers or neither, and no family. A tie-break here would be a rule
    # invented to avoid saying "I do not know", and the sponsors it would
    # decide are the ones nobody checked.
    return UNCLASSIFIED


def display_name(name):
    """The name a chart may show. Individuals become a generic label."""
    return INDIVIDUAL if is_individual(name) else name


def classified_studies(con, since=COVERAGE_START):
    """[(study_id, year, sponsor class)] for every trial in the window."""
    return [(study_id, int(year), classify(name))
            for study_id, year, name in con.execute(
                """SELECT st.identificador,
                          substr(st.fecha_autorizacion_aemps, 1, 4),
                          sp.promotor
                     FROM studies st
                     JOIN sponsors sp ON sp.sponsor_id = st.sponsor_id
                    WHERE st.fecha_autorizacion_aemps >= ?""",
                ("{}-01-01".format(since),))]


def share_by_year(rows):
    """[(year, {class: share})] -- who sponsors each year's trials.

    Shares of the year's trials, so the three classes sum to 100%: a trial
    has exactly one sponsor in REEC, which makes this the second chart in the
    project that can say so.
    """
    totals = collections.defaultdict(collections.Counter)
    for _, year, sponsor_class in rows:
        totals[year][sponsor_class] += 1
    return [(year, {sponsor_class: 100.0 * counts[sponsor_class]
                    / sum(counts.values()) for sponsor_class in CLASSES})
            for year, counts in sorted(totals.items())]


# --- charts ----------------------------------------------------------------

# Categorical slots 1 and 2 for the two real classes; unclassified is drawn in
# ink, because it is not a third kind of sponsor, it is the absence of an
# answer, and giving it a hue would put it on the same footing as the two.
INDUSTRY_COLOUR = SERIES
ACADEMIC_COLOUR = "#eb6834"


def phase_four_by_year(con, rows, since=COVERAGE_START):
    """[(year, class, trials, phase IV trials)] from a classified corpus."""
    sponsor_class = {study_id: name for study_id, _, name in rows}
    counts = collections.defaultdict(collections.Counter)
    for study_id, year, phase_four in con.execute(
            """SELECT identificador, substr(fecha_autorizacion_aemps, 1, 4),
                      fase_cuatro
                 FROM studies
                WHERE fecha_autorizacion_aemps >= ?""",
            ("{}-01-01".format(since),)):
        key = (int(year), sponsor_class[study_id])
        counts[key]["trials"] += 1
        counts[key]["phase_four"] += phase_four
    return [(year, name, counts[(year, name)]["trials"],
             counts[(year, name)]["phase_four"])
            for year, name in sorted(counts)]


# Neither grey is a series colour: unclassified is the absence of an answer,
# and the classified-only line is the industry line with that absence removed.
# One sits lighter than the other so the reference reads as the stronger of
# the two, and both carry an end label, which is what the palette's contrast
# note requires of anything this pale.
ABSENT = "#a8a7a1"


def _line(fig, years, values, name, colour, width=2, yshift=0):
    """One series, with a dot and its value at the end."""
    last = len(years) - 1
    fig.add_trace(go.Scatter(
        x=years, y=values, name=name, mode="lines+markers",
        line=dict(color=colour, width=width),
        marker=dict(color=colour, size=[0] * last + [8],
                    line=dict(color=SURFACE, width=2)),
        hovertemplate="%{y:.1f}%<extra>" + name + "</extra>"))
    fig.add_annotation(x=years[-1], y=values[-1], xshift=12, yshift=yshift,
                       text="{:.0f}%".format(values[-1]), showarrow=False,
                       xanchor="left", font=dict(size=11, color=MUTED))


def _layout(fig, title, subtitle, y_title):
    fig.update_layout(
        title=dict(text=title,
                   subtitle=dict(text=subtitle,
                                 font=dict(size=12, color=MUTED)),
                   font=dict(size=17, color=INK)),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0,
                    font=dict(size=11, color=MUTED)),
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=80, b=90, l=60), width=760, height=470)
    fig.update_xaxes(dtick=1, showgrid=False, linecolor=GRID,
                     ticks="outside", tickcolor=GRID)
    fig.update_yaxes(title_text=y_title, rangemode="tozero", ticksuffix="%",
                     gridcolor=GRID, zeroline=False)
    return fig


def share_figure(shares):
    """Who sponsors each year's trials, as three shares that sum to 100%.

    A fourth line carries industry as a share of the *classified* trials
    only. The unclassified share falls from 7.8% to 2.7% across the window --
    registry names got more complete -- so part of the crude industry rise is
    trials becoming classifiable rather than sponsors changing. The muted line
    is what is left when that is taken out, and it is about half the move.
    """
    years = [year for year, _ in shares]
    fig = go.Figure()
    _line(fig, years, [share[INDUSTRY] for _, share in shares],
          INDUSTRY, INDUSTRY_COLOUR)
    _line(fig, years, [share[ACADEMIC] for _, share in shares],
          ACADEMIC, ACADEMIC_COLOUR)
    _line(fig, years, [share[UNCLASSIFIED] for _, share in shares],
          UNCLASSIFIED, ABSENT)
    # Nudged clear of the industry label, which ends two points below it.
    _line(fig, years,
          [100.0 * share[INDUSTRY] / (share[INDUSTRY] + share[ACADEMIC])
           for _, share in shares],
          "Industry, of classified trials only", MUTED, width=1, yshift=11)
    return _layout(
        fig, "Industry sponsors four trials in five, and the share is rising",
        "A trial has exactly one sponsor, so the three classes sum to 100%."
        "<br>The muted line removes the unclassified, which shrank from 7.8% "
        "to 2.7% as registry names got more complete.",
        "share of trials authorised")


def phase_four_figure(rows):
    """Phase IV share within each sponsor class.

    The chart that decomposes the corpus-wide phase IV decline. Two things
    can shrink a rate: the groups doing the thing can do less of it, or the
    groups doing the most of it can become a smaller part of the corpus.
    Here it is both, and only one of them is what it looked like.
    """
    years = sorted({year for year, _, _, _ in rows})
    fig = go.Figure()
    for name, colour in ((INDUSTRY, INDUSTRY_COLOUR),
                         (ACADEMIC, ACADEMIC_COLOUR)):
        values = [100.0 * phase_four / trials
                  for year, sponsor_class, trials, phase_four in rows
                  if sponsor_class == name]
        _line(fig, years, values, name, colour)
    return _layout(
        fig, "Academic sponsors did not stop running phase IV trials",
        "Share of each class's own trials that are phase IV. Academic phase "
        "IV intensity is flat;<br>industry's fell by two thirds, and academic "
        "sponsors became a smaller share of the corpus.",
        "of that class's trials, phase IV")


# --- corporate families ----------------------------------------------------
#
# 2,957 sponsors is a list of legal entities, not of companies. Novartis files
# under ten spellings and Roche under fourteen, so a ranking of the raw
# column answers "which legal entity signed the most protocols" when the
# question people mean is "which company is behind the most Spanish trials".
# Resolving that is entity resolution, which PROJECT_SPEC 3.2c keeps out of
# the database on purpose: merging changes what "top sponsor" means, so it
# belongs here, where it can be read and argued with.
#
# Candidates were generated by blocking on the leading token of the folded
# name and ranking by trial count, then **every group was read before it was
# accepted**. Reading is not a formality; it caught all four of these:
#
#   * `Merck Sharp & Dohme` (347 trials, US) and `Merck KGaA` (66, German) are
#     different companies that split in 1917. A `Merck` rule merges them, and
#     also swallows `Merckle GmbH`, which is a third company again.
#   * `Roche Farma S.A.` and `F. Hoffmann-La Roche` block apart -- one starts
#     with `Roche`, the other with `F.` -- and are one company. Several of the
#     Spanish entries say so in the name: "que actúa como representante de
#     F. Hoffmann-La Roche".
#   * `Lilly S.A.` and `Eli Lilly & Co.` block apart for the same reason, and
#     are the pair the Phase 2 handoff flagged: 101 trials against 95.
#   * The block key `laboratorios` gathers 29 unrelated Spanish laboratories
#     and `fundacion` gathers 137 unrelated foundations. A common word is not
#     a family, and neither block produced a single merge.
#
# The registry often states the relationship itself -- `Medivation Inc. (a
# wholly owned subsidiary of Pfizer)`, `Millennium Pharmaceuticals, Inc., a
# wholly owned subsidiary of Takeda` -- so a pattern that looks anywhere in
# the name picks up acquisitions without anyone having to know about them.
#
# **When an acquisition is merged, and when it is not.** Two cases merge: an
# arm the parent owned for the whole window (Genentech has been Roche's since
# 2009, Genzyme Sanofi's since 2011, MedImmune AstraZeneca's since 2007), and
# a name that declares its parent, where the registry states the relationship
# rather than us inferring it. Companies bought *during* the window and still
# filing under their own name are left alone: Celgene, Seagen, Actelion, Kite
# and Baxalta each ran trials here for years before their buyer owned them,
# and crediting those trials backwards would misdate the corpus. The rule is
# the window, not the present day, and it is why Celgene still has its own
# row.
#
# First match wins, so the exceptions come first. A sponsor matching nothing
# keeps its own name and is its own family: most of the 2,957 are.
FAMILIES = (
    # A joint venture of two families, dissolved in 2016. It belongs to
    # neither, and putting it in either would be a merge nobody could defend.
    (r"Sanofi Pasteur MSD", "Sanofi Pasteur MSD"),
    (r"Merck Sharp ?(&|and) ?Dohme", "Merck Sharp & Dohme (MSD)"),
    (r"Merck (KGaA|Healthcare)", "Merck KGaA"),
    (r"\bRoche\b", "Roche"),
    (r"\bNovartis\b", "Novartis"),
    (r"AstraZeneca", "AstraZeneca"),
    (r"\bJanssen\b", "Janssen (Johnson & Johnson)"),
    (r"\bAbbVie\b", "AbbVie"),
    (r"\bPfizer\b", "Pfizer"),
    (r"GlaxoSmithKline", "GlaxoSmithKline"),
    (r"Bristol[- ]?Myers Squibb", "Bristol Myers Squibb"),
    (r"\bSanofi\b", "Sanofi"),
    (r"\bLilly\b", "Eli Lilly"),
    (r"Boehringer", "Boehringer Ingelheim"),
    (r"\bAmgen\b", "Amgen"),
    (r"\bBayer\b", "Bayer"),
    (r"\bGilead\b", "Gilead"),
    # Acquired by Bristol Myers Squibb in 2019, and left separate: half this
    # corpus predates the acquisition, so merging would credit BMS with
    # trials it did not run at the time it did not own them.
    (r"\bCelgene\b", "Celgene"),
    (r"\bIncyte\b", "Incyte"),
    (r"\bTakeda\b", "Takeda"),
    (r"\bServier\b", "Servier"),
    (r"\bAstellas\b", "Astellas"),
    (r"\bIpsen\b", "Ipsen"),

    # --- second pass, from reading docs/sponsor-families.html ---------------
    # A rule cannot report the merge it failed to make, so these came from
    # scanning what the first pass left alone, biggest first. Four are arms
    # sharing no token with their parent, findable only by knowing about
    # them; five are one organisation spelling its own name several ways.
    (r"\bGenentech\b", "Roche"),
    (r"\bGenzyme\b", "Sanofi"),
    (r"\bMedImmune\b", "AstraZeneca"),
    (r"Millennium Pharmaceuticals", "Takeda"),
    (r"\bUCB\b", "UCB"),
    (r"\bEisai\b", "Eisai"),
    (r"ViiV Healthcare", "ViiV Healthcare"),
    # One company under two names: BeiGene renamed itself BeOne Medicines.
    (r"\bBeiGene\b|\bBeOne Medicines\b", "BeiGene (BeOne Medicines)"),
    # An S.L. and the same name without it. Its own description is
    # "independent research organisation", which is why it was left
    # Unclassified in the first pass; the S.L. spelling settles it as a
    # commercial entity, which is all "Industry" claims here.
    (r"Medica Scientia Innovation Research",
     "Medica Scientia Innovation Research (MedSIR)"),
)


# Every family above is a company, which is what lets classify() use
# membership as evidence.
FAMILY_NAMES = frozenset(family for _, family in FAMILIES)


def family_of(name):
    """The corporate family a sponsor belongs to, or the sponsor itself.

    Individuals are generalised first, so a person never reaches a pattern
    and never appears in a ranking under their own name.
    """
    if is_individual(name):
        return INDIVIDUAL
    for pattern, family in FAMILIES:
        if re.search(pattern, name, re.IGNORECASE):
            return family
    return name


def top_families(con, count=15, since=COVERAGE_START):
    """[(family, trials, spellings)] -- the ranking the merge is for."""
    families = collections.Counter()
    spellings = collections.Counter()
    for name, trials in con.execute(
            """SELECT sp.promotor, count(*)
                 FROM studies st
                 JOIN sponsors sp ON sp.sponsor_id = st.sponsor_id
                WHERE st.fecha_autorizacion_aemps >= ?
             GROUP BY sp.promotor""", ("{}-01-01".format(since),)):
        family = family_of(name)
        families[family] += trials
        spellings[family] += 1
    return [(family, trials, spellings[family])
            for family, trials in families.most_common(count)]


def families_figure(families, trials):
    """The ranking the merge exists for, longest bar at the top.

    The spelling count rides the hover rather than the label: it is evidence
    that the merge did something, not part of the answer to "who sponsors the
    most trials".
    """
    labels = [family for family, _, _ in families][::-1]
    counts = [count for _, count, _ in families][::-1]
    spellings = [spelling for _, _, spelling in families][::-1]

    fig = go.Figure(go.Bar(
        x=counts, y=labels, orientation="h",
        marker=dict(color=INDUSTRY_COLOUR, cornerradius=4),
        text=["{:,}".format(count) for count in counts],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        customdata=list(zip(spellings,
                            [100.0 * count / trials for count in counts])),
        hovertemplate="%{y}<br>%{x:,} trials (%{customdata[1]:.1f}% of all)"
                      "<br>%{customdata[0]} spellings in the registry"
                      "<extra></extra>"))

    fig.update_layout(
        title=dict(
            text="Top sponsors, once the corporate families are merged",
            subtitle=dict(
                text="A company files under many legal entities: Novartis "
                     "under 10 spellings, Roche under 14.<br>Unmerged, the "
                     "list is led by AstraZeneca AB with 348 — an entity, "
                     "not a company.",
                font=dict(size=12, color=MUTED)),
            font=dict(size=17, color=INK)),
        bargap=0.42, showlegend=False,
        plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, sans-serif", color=MUTED, size=12),
        margin=dict(t=95, r=70, b=40, l=230), width=760,
        height=110 + 30 * len(families))
    fig.update_xaxes(visible=False, range=[0, max(counts) * 1.12])
    fig.update_yaxes(showgrid=False, linecolor=GRID, ticks="")
    return fig


# --- the review page -------------------------------------------------------
#
# The rules above are the artifact; the groups they produce are derived. This
# renders both, because "read every merge before accepting it" needs somewhere
# to do the reading, and a console dump is not somewhere.
#
# The second table is the one that earns the page. It lists every sponsor that
# joined no family, biggest first, which is the only way to notice a family
# that should exist and does not -- a rule cannot report the merge it failed
# to make.

def family_review(con, since=COVERAGE_START):
    """(merged, unmerged) -- what the rules did, and what they left alone.

    merged:   [(family, trials, [(spelling, trials)])], biggest family first
    unmerged: [(sponsor, trials, class)], biggest first
    """
    members = collections.defaultdict(list)
    for name, trials in con.execute(
            """SELECT sp.promotor, count(*)
                 FROM studies st
                 JOIN sponsors sp ON sp.sponsor_id = st.sponsor_id
                WHERE st.fecha_autorizacion_aemps >= ?
             GROUP BY sp.promotor""", ("{}-01-01".format(since),)):
        members[family_of(name)].append((name, trials))

    merged, unmerged = [], []
    for family, spellings in members.items():
        total = sum(trials for _, trials in spellings)
        if len(spellings) > 1:
            merged.append((family, total,
                           sorted(spellings, key=lambda s: -s[1])))
        else:
            unmerged.append((family, total, classify(spellings[0][0])))
    merged.sort(key=lambda row: -row[1])
    unmerged.sort(key=lambda row: -row[1])
    return merged, unmerged


REVIEW_STYLE = """
body {{ margin: 0; padding: 32px 40px 64px; background: {surface};
        color: {ink}; font: 14px/1.5 system-ui, sans-serif; max-width: 1000px; }}
h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px; }}
h2 {{ font-size: 16px; font-weight: 600; margin: 40px 0 4px; }}
p  {{ color: {muted}; margin: 4px 0 16px; max-width: 66ch; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th {{ text-align: left; font-weight: 600; color: {muted}; padding: 6px 10px;
      border-bottom: 1px solid {grid}; }}
td {{ padding: 4px 10px; border-bottom: 1px solid {grid};
      vertical-align: top; }}
td.n {{ text-align: right; font-variant-numeric: tabular-nums;
        white-space: nowrap; }}
tr.family td {{ font-weight: 600; border-bottom: none; padding-top: 14px; }}
tr.spelling td {{ color: {muted}; }}
tr.spelling td.name {{ padding-left: 28px; }}
.tag {{ font-size: 11px; color: {muted}; }}
input {{ font: 13px system-ui, sans-serif; padding: 6px 10px; width: 320px;
         border: 1px solid {grid}; border-radius: 4px; margin-bottom: 12px; }}
"""


def review_page(merged, unmerged):
    """A self-contained page: every merge, and everything left unmerged."""
    import html

    def row(cells, css=""):
        return "<tr{}>{}</tr>".format(
            ' class="{}"'.format(css) if css else "",
            "".join(cells))

    lines = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
             "<title>Sponsor families</title><style>",
             REVIEW_STYLE.format(surface=SURFACE, ink=INK, muted=MUTED,
                                 grid=GRID),
             "</style></head><body>",
             "<h1>Sponsor families</h1>",
             "<p>Every merge the rules in <code>analysis/sponsors.py</code> "
             "made, and every sponsor they left alone. Generated by "
             "<code>run_analysis.py</code>, so it cannot drift from the "
             "rules it documents. Counts are trials authorised since "
             "{}.</p>".format(COVERAGE_START),
             "<h2>{} families, {:,} trials</h2>".format(
                 len(merged), sum(total for _, total, _ in merged)),
             "<p>Each family is one company filing under several legal "
             "entities. Read the spellings under a family: if one of them "
             "does not belong to that company, the rule that caught it is "
             "wrong.</p>",
             "<table><thead>",
             row(["<th>Sponsor as the registry spells it</th>",
                  "<th class='n'>Trials</th>"]),
             "</thead><tbody>"]

    for family, total, spellings in merged:
        lines.append(row(["<td>{}</td>".format(html.escape(family)),
                          "<td class='n'>{:,} <span class='tag'>in {} "
                          "spellings</span></td>".format(total,
                                                         len(spellings))],
                         "family"))
        for name, trials in spellings:
            lines.append(row(
                ["<td class='name'>{}</td>".format(html.escape(name)),
                 "<td class='n'>{:,}</td>".format(trials)], "spelling"))

    lines += ["</tbody></table>",
              "<h2>{:,} sponsors joined no family</h2>".format(len(unmerged)),
              "<p><strong>This is the table to scan.</strong> A rule cannot "
              "report the merge it failed to make, so the only way to notice "
              "a missing family is to read what was left alone, biggest "
              "first. Anything here with a familiar corporate name, or two "
              "rows that are obviously the same organisation, is a family "
              "the rules missed.</p>",
              "<input id='filter' type='search' placeholder='Filter "
              "sponsors\u2026' autocomplete='off'>",
              "<table><thead>",
              row(["<th>Sponsor</th>", "<th>Class</th>",
                   "<th class='n'>Trials</th>"]),
              "</thead><tbody id='rows'>"]

    for name, trials, sponsor_class in unmerged:
        lines.append(row(["<td>{}</td>".format(html.escape(name)),
                          "<td class='tag'>{}</td>".format(sponsor_class),
                          "<td class='n'>{:,}</td>".format(trials)]))

    lines += ["</tbody></table>",
              "<script>",
              "const box = document.getElementById('filter');",
              "const rows = [...document.querySelectorAll('#rows tr')];",
              "box.addEventListener('input', () => {",
              "  const q = box.value.toLowerCase();",
              "  for (const tr of rows)",
              "    tr.hidden = q && !tr.cells[0].textContent"
              ".toLowerCase().includes(q);",
              "});",
              "</script></body></html>"]
    return "\n".join(lines)
