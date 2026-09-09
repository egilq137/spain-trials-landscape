# Geometry

The only files in `data/` that are committed. `data/raw/` is gitignored
because it is 208 MB and re-fetchable; these are small and would be tedious to
rebuild by hand, so they live in the repo and the provenance lives here.

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

11,150 rows of `cod_postal,lat,lon` -- every Spanish postal code, not only the
812 this corpus uses. The whole table is kept so that a rebuilt database
holding centres this one has never seen still places them; filtering to the
812 would save 240 KB and turn a future load into a silent gap.

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
averaged into one point and rounded to five decimals, giving 11,150. Recorded
here rather than scripted, the same rule as the geojson above: it ran once and
the output is the artefact.

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
