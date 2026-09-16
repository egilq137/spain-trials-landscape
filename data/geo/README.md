# Reference data

The only files in `data/` that are committed. `data/raw/` is gitignored
because it is 208 MB and re-fetchable; these are small and would be tedious to
rebuild by hand, so they live in the repo and the provenance lives here.

Four files, from three sources, and all of the same kind: small, external,
licensed, and describing *Spain* rather than describing this corpus. Two are
geometry, one is a gazetteer and one is a directory of hospitals; the
directory named this file when it only held polygons, and the files have not
been moved because a path in a committed artefact is worth more than a tidy
name.

**Nothing derived from the trials belongs here.** Which centre is which
hospital, which sponsor is which company, which trial counts where -- those
are conclusions, they live in `analysis/` where they can be argued with, and
`PROJECT_SPEC` 3.3 explains why for the sponsor case.

## `spain-ccaa.geojson`

19 polygons: the 17 autonomous communities plus the autonomous cities of Ceuta
and Melilla. Each feature carries `id` = `nuts_id` (so Plotly can join on
`featureidkey="id"`) and `properties.name`.

| | |
|---|---|
| Source | Eurostat GISCO, `NUTS_RG_20M_2021_4326_LEVL_2.geojson` |
| URL | https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_20M_2021_4326_LEVL_2.geojson |
| Retrieved | 2026-09-03 |
| Scale | 1:20 million (the coarsest GISCO publishes -- enough for a national choropleth, and the reason this file is 38 KB rather than several MB) |
| Projection | EPSG:4326 (WGS 84), which is what Plotly expects |
| Licence | Free reuse with attribution. Administrative boundaries: **© EuroGeographics**. See https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units |

**Attribution is required wherever a map from this file is published** -- the
README and the dashboard both carry the EuroGeographics line.

### Why NUTS rather than a Spanish source

Spain's autonomous communities are exactly NUTS level 2, so the official
European statistical geography already draws the boundary we want, with a
stable code per region (`ES30` Comunidad de Madrid, `ES51` Cataluña) that does
not depend on how anyone spells the name. REEC identifies regions by name only
-- `MADRID, COMUNIDAD DE` -- so the join has to go through a name mapping
somewhere; putting it against a coded vocabulary means the mapping is written
once, in one table, and every later question inherits it.

### How it was cut down

The published file covers every NUTS-2 region in Europe (719 KB). Filtered to
`CNTR_CODE == "ES"` and stripped to two properties, which is the whole of what
the chart reads. The filter is recorded here rather than scripted: it ran once,
the output is committed, and a rebuild means re-reading this paragraph -- the
same rule as `data/raw/`, where the durable artefact is the file and not the
code that fetched it.

## `spain-provinces.geojson`

52 polygons: the 50 provinces plus Ceuta and Melilla. `id` = `properties.ine`,
the 2-digit INE province code -- which is also the postcode prefix, so the
name-to-code table in `analysis/geography.py` is checkable against the data
rather than merely asserted, and `tests/test_geography.py` checks it.

Same source, retrieval date and licence as above, from
`NUTS_RG_20M_2021_4326_LEVL_3.geojson` (1.6 MB, all of Europe).

### Provinces are not a NUTS level

Spain has **59** NUTS-3 units and **52** provinces, because the islands are
split finer than the provinces are:

| province | INE | NUTS 3 units merged |
|---|---|---|
| Illes Balears | 07 | ES531 Eivissa y Formentera, ES532 Mallorca, ES533 Menorca |
| Las Palmas | 35 | ES704 Fuerteventura, ES705 Gran Canaria, ES708 Lanzarote |
| Santa Cruz de Tenerife | 38 | ES703 El Hierro, ES706 La Gomera, ES707 La Palma, ES709 Tenerife |

The other 49 are 1:1. Merging is safe here because the units being combined
are separate islands: disjoint polygons concatenate into one MultiPolygon and
no shared border has to be dissolved. A test asserts each of the three still
carries at least as many polygons as it has island units, since a dropped
merge would leave a province quietly missing an island.

The three merged names are written out (`Illes Balears`, `Las Palmas`,
`Santa Cruz de Tenerife`); the other 49 keep the NUTS `NAME_LATN`, which is
why the map says `Alicante/Alacant` and `Araba/Álava`.

## `postcodes.csv`

11,150 rows of `cod_postal,lat,lon,town` -- every Spanish postal code, not
only the 812 this corpus uses. The whole table is kept so that a rebuilt
database holding centres this one has never seen still places them; filtering
to the 812 would save 400 KB and turn a future load into a silent gap.

The `town` column is a **second, independent source for what town a postcode
is in**, and it exists because REEC's own `localidad` is not always usable:
twelve values have lost their accented characters to a mis-decoded byte
(`M?laga`, `Logro?o`, `Iru?a`) and 174 are blank. `analysis.geography`
falls back to this column for exactly those rows and **never overrides a
readable one** -- Institut Català d'Oncologia's Girona campus carries
L'Hospitalet's postcode, so a postcode-derived town would merge two real
sites into one.

| | |
|---|---|
| Source | GeoNames postal-code export, `ES.zip` → `ES.txt` |
| URL | https://download.geonames.org/export/zip/ES.zip |
| Retrieved | 2026-09-09 |
| Projection | EPSG:4326 (WGS 84), as the geojson files |
| Licence | **Creative Commons Attribution 4.0**, https://creativecommons.org/licenses/by/4.0/ |

**Attribution is required wherever these points are published** -- the dot map
carries "Sites placed by postcode (GeoNames, CC BY 4.0)" beside the
EuroGeographics line.

### How it was cut down

The export is 37,867 rows, one per (postcode, place) pair, so a postcode with
four named localities appears four times. Rows sharing a postcode were
averaged into one point and rounded to five decimals, and the first place name
for each postcode was kept as `town`, giving 11,150. Recorded here rather than
scripted, the same rule as the geojson above: it ran once and the output is
the artefact.

GeoNames is inconsistent about accents in its own place names -- `Malaga` and
`Leon` unaccented beside `Logroño` and `Pamplona/Iruña`. It does not matter
here, because every comparison goes through
`analysis.geography.normalise_town`, which strips accents and the qualifier
after a comma, slash or bracket.

### What a postcode centroid can and cannot say

It is the centre of a postal district, so **every hospital sharing a postcode
gets the same point**, and in dense districts several large hospitals land on
top of each other. The dot map says so in its subtitle rather than jittering
them apart, which would invent a precision the source does not have and put
hospitals on streets they are not on.

`analysis.geography.normalise_postcode` is what joins REEC's `cod_postal` to
this table, and it repairs only the three defects the schema documents --
trailing punctuation, digit separators, a dropped leading zero. **It refuses
anything still holding a letter**, which costs 11 centres and is worth it:
stripping letters instead turns `3584 AE`, a Dutch postcode, into `03584`,
which is a real place in Alicante.

## `hospitals.csv`

848 rows, one per hospital in Spain: `codcnh`, `nombre`, `municipio`,
`provincia`, `cod_postal`, `camas`, `clase`, `dependencia`, `complejo`.

| | |
|---|---|
| Source | Catálogo Nacional de Hospitales 2025, sheet `DIRECTORIO DE HOSPITALES` of `CNH_2025.xlsx` |
| URL | https://www.sanidad.gob.es/estadEstudios/estadisticas/sisInfSanSNS/ofertaRecursos/hospitales/docs/CNH_2025.xlsx |
| Retrieved | 2026-09-16 (file last modified 2025-10-30) |
| Data updated | **31 December 2024** -- the catalogue is revised annually on 31 December and takes effect the following 1 January |
| Licence | Free reuse, including commercial. https://sede.mscbs.gob.es/datosabiertos/condiciones.htm |

**The licence requires all of the following wherever this data is
published**, and the pages built from it carry them:

- the source, worded as **"Origen de los datos: Ministerio de Sanidad,
  Consumo y Bienestar Social"**
- the date the data was updated, above
- no suggestion that the Ministry participates in, sponsors or endorses this
  work -- it does not
- no distortion of the meaning of the information

### How it was cut down

The workbook has nine sheets; this is the first one, with 9 of its 22 columns
kept. Dropped: the street address, telephone and email (contact details this
project has no use for and PROJECT_SPEC 3.2b's rule against personal data
points away from), the internal `CCN` identifier, and the numeric codes that
duplicate the labels kept -- `Cód. Clase de Centro` beside `Clase de Centro`,
and so on. The two code tables the workbook ships are readable in full and
are not reproduced: their labels are already spelled out in these rows.

Recorded here rather than scripted, the same rule as the files above: it ran
once and the output is the artefact.

### What it is for, and what it is not

It is an **authority list**: 848 hospitals the state recognises, each with an
official name, a municipality and a postcode. REEC's centre rows are messy in
four languages, and matching each of them against one clean list is a smaller
and far more checkable problem than matching 3,293 messy rows against each
other -- a row gets an official hospital name assigned, and a reader can see
whether it is the right one.

`codcnh` is a real key into this data and REEC already carries it: **324 of
REEC's numeric `referencia` values are `CODCNH` codes**, verified by name and
postcode, not merely by format. The rest of REEC's numeric references are a
second series in the 11xxxx-12xxxx band covering health centres of every
kind, which is why they are absent from a catalogue of hospitals.

**It does not settle the matching on its own.** The catalogue holds
near-name collisions within one municipality: Madrid has both `Hospital
Universitario La Paz` (966 beds, general, public) and `Clínica Nuestra Señora
de La Paz` (99 beds, mental health, private); Barcelona has both `Hospital
Universitari Vall D'Hebron` (1,315 beds) and `Centre Sociosanitari Sant Jordi
de la Vall D'Hebron` (57 beds). A match on name similarity alone picks the
wrong one often enough to matter, which is why `camas`, `clase` and
`cod_postal` are kept: they are what makes a match checkable.

`complejo` names the 41 hospital complexes, covering 114 hospitals. It is the
ministry's own answer to a question this project keeps meeting -- whether two
sites are one organisation -- and it is worth more than any string rule that
could be written for it.
