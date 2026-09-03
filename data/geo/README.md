# Geometry

The only file in `data/` that is committed. `data/raw/` is gitignored because
it is 208 MB and re-fetchable; this is 38 KB and would be tedious to rebuild
by hand, so it lives in the repo and the provenance lives here.

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
