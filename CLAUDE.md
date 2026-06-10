# Agent orientation

You're picking up a working Streamlit app TJ uses for his family's house hunt.
Get oriented in 60 seconds, then keep going.

## What this is

Filter active home listings to **only homes inside the attendance zone of a
top-rated elementary school**. The unique value vs. Zillow/Redfin is the
*inverse* filter — Zillow shows you a home and the school it's zoned for;
this app shows you the homes whose zoning meets a school-quality threshold.

- **User**: TJ Allison <hello@tjallison.com>. NOTE (June 2026): the family is
  NOT relocating to FL anymore — the app's purpose shifted from house hunt to
  **rental-investment screening** (cash flow + appreciation in good school
  zones). Same inverse filter, different buyer.
- **Scope today**: Broward + Miami-Dade + Hillsborough counties, FL. 180
  A-rated boundary elementary schools (91 M-D, 51 Broward, 38 Hillsborough,
  incl. the FishHawk cluster: Bevis / FishHawk Creek / Stowers). Sidebar
  Region selector splits South Florida vs Tampa Bay; live mode runs one
  RentCast radius query per metro in scope. Investment toggle adds a HUD
  SAFMR rent proxy + gross-yield ranking.
- **Scope wanted**: more metros, chosen by the investment screen (not
  US-wide for its own sake). GreatSchools API was evaluated June 2026 and
  rejected: public tiers carry no 1-10 ratings, no boundaries, no bulk
  download (Enterprise-only) — state DOE + district GIS stays the pattern.

## Stack

Streamlit + Folium + Streamlit-AgGrid + Geopandas + Shapely.
Python 3.10+. RentCast for live listings.

## How to run

```bash
cd ~/school-home-search-app
pip install -r requirements.txt
cp .env.example .env  # then fill in RENTCAST_API_KEY
streamlit run app.py
```

`USE_LIVE_DATA=false` in `.env` runs entirely on cached data — works offline,
no API key needed. `USE_LIVE_DATA=true` pulls active listings from RentCast
(free tier 50 calls/month; we use 1-2 per session via radius pagination).

Also deployed on Streamlit Community Cloud — TJ has the URL.

## Architecture

Four files do all the work. Read them in this order:

| File | What it does |
|---|---|
| `mock_data.py` | `FL_SCHOOLS` list of dicts + polygon loader. Reads `data/schools_generated.py` (142 schools) when present, falls back to a 27-entry hand-coded baseline otherwise. `_real_boundary_for()` looks up actual GIS polygons; falls back to synthetic hexagons when no boundary exists (only magnets and a couple of orphan schools). |
| `geo_engine.py` | `filter_listings_in_top_elementary_zones()` is the main filter. Spatial-joins listings against elementary polygons via `gpd.sjoin(predicate="within")`, excludes magnets unless `include_magnet=True`. Also has `schools_bbox`, `zoom_for_bbox`, and `rating_to_color` helpers. |
| `data_provider.py` | Abstract `SchoolDataProvider` and `ListingsDataProvider` interfaces + concrete `MockSchoolProvider`, `MockListingsProvider`, `GreatSchoolsProvider` (skeleton), `RentCastProvider`. `get_providers()` dispatches off `USE_LIVE_DATA`. **Schools always come from the mock provider** — that's where FL DOE ratings + district GIS polygons live; "mock" is a misnomer. Only listings ever toggle between mock and live. |
| `app.py` | Streamlit UI. Sidebar filters (incl. Region + Investment toggle) → cached fetch → spatial join → Folium map + AgGrid table. Live mode runs one broad radius RentCast query per metro group (`_radius_queries_for_schools`); ZIP mode is fallback. |
| `rent_proxy.py` | HUD FY2026 SAFMR lookup (`data/safmr_fl_2026.csv`, FL ZIPs, bedroom-resolved) + `annotate_listings()` → `est_monthly_rent`, `gross_yield_pct`, `rent_source`. Zone-comparison proxy, NOT underwriting — see module docstring for the bias caveats. |

## Data lineage (provenance matters — don't skip this)

| Layer | Source | Refresh script |
|---|---|---|
| School ratings | FL DOE 2023-24 School Grades XLSX (vendored at `data/SchoolGrades24.xlsx`). Letter → 10/8/6/4/2 mapping + raw `rating_pct`. | `scripts/fetch_school_grades.py` |
| Attendance polygons | Broward `AllSchoolBoundaries` + Miami-Dade `ElementaryAttendanceBoundary` ArcGIS REST. Hillsborough: `gis.drmp.com` hosted layer "HCPS School Zones 2025-26" (DRMP = HCPS's GIS vendor; backs the district's official locator app). HCPS's own ArcGIS orgs only publish stale 2020-21 layers that predate the June 2023 districtwide rezoning — don't use them. Cached at `data/boundaries/*.geojson`, properties normalized to `NAME`/`ZIPCODE` at fetch time. | `scripts/fetch_school_boundaries.py` |
| Generated school list | The join of the above two via the `DISTRICTS` registry (adding a metro = one registry line + one endpoint). | `scripts/build_fl_schools.py` |
| Rent proxy | HUD FY2026 Small Area FMRs, FL ZIPs, vendored at `data/safmr_fl_2026.csv`. huduser.gov serves an empty body without a browser User-Agent — the fetch script sets one. | `scripts/fetch_safmr.py` |
| Listings | RentCast `/v1/listings/sale` with lat/lon+radius. | Live runtime; cached in Streamlit session. |

Known vintage mismatch: ratings are FL DOE 2023-24 while HCPS zones are
2025-26 (current locator layer). The join is by school name, not geography,
so a rezoned school keeps its grade; refresh ratings when DOE publishes.

Every school carries a `boundary_source` field (`"district"` or `"synthetic"`)
and a `rating_source` field (`"FL DOE 2023-24 School Grades"`). The map
tooltip says "Boundary: district GIS" or "Boundary: approximate" so TJ
always knows which kind of polygon he's looking at. **Preserve this
traceability** — it's why the audit signed off.

## What's done

- ✅ Real ratings (FL DOE) — not made up
- ✅ Real attendance polygons (Broward + Miami-Dade GIS)
- ✅ Magnet/lab schools excluded by default via `admission_type` field
- ✅ Live RentCast listings with quota-efficient radius queries (now per-metro)
- ✅ 180 elementary zones across 3 counties (Hillsborough added June 2026 —
  validated the "new metro in a few hours" claim: one endpoint + one registry line)
- ✅ Region selector (South Florida / Tampa Bay / All)
- ✅ Investment view: HUD SAFMR rent proxy + gross-yield ranking (`rent_proxy.py`)
- ✅ `.gitignore` (didn't exist before June 2026 — `.env` was one `git add .`
  away from leaking the RentCast key)
- ✅ Pushed to GitHub; deployed on Streamlit Cloud

## What's NOT done (next candidates, in rough priority order)

1. **Ratings refresh** — FL DOE has published newer School Grades since the
   vendored 2023-24 file; `scripts/fetch_school_grades.py` + rerun the build.
   Cheap, improves every metro at once, and closes the HCPS vintage gap.
2. **Property-level rent for finalists** — RentCast `/v1/avm/rent` on
   shortlisted listings only (1 quota call each). The SAFMR proxy ranks
   zones; this prices houses. Natural `RentCastProvider` extension.
3. **More metros, screen-driven** — per-metro curation remains the pattern
   (state DOE ratings + district GIS polygons + one `DISTRICTS` registry
   line). National datasets stay dead ends: NCES SABS discontinued 2015-16;
   GreatSchools public API has no ratings numbers, no boundaries, no bulk
   (verified June 2026). Ask TJ which metro the investment screen surfaces
   next before building.

## TJ's preferences (load-bearing)

- **No sycophancy.** State only grounded claims, name the loose ends, don't
  grovel when caught. If you say "great approach" he'll flag it.
- **Run `/decision-accountability` proactively** when recommending wait/defer/
  out-of-scope — *before* presenting the recommendation, not after. He
  flagged corner-cutting framings as costly in past sessions.
- **Elementary only.** Don't add middle/high filters; the focus is intentional.
- **Boundary-based filter.** Magnet/lottery schools are excluded by design
  because residency doesn't grant enrollment — adding them defeats the point.

## Decision history (commit messages are the audit log)

```
f0fec48 chore: load st.secrets on Streamlit Cloud
d279f3a feat: 13x school expansion + radius RentCast queries
a8ff733 feat: wire RentCast live listings (RealtyMole rebrand)
40d1cf6 feat: bake FL DOE 2023-24 ratings + add refresh script
3a85e74 feat: real district GIS attendance polygons
e7b4ad6 feat: elementary-focused filter + magnet exclusion
6ce7d72 fix: unbreak map/table + retarget MVP to South Florida
[older] add school-quality home search Streamlit app (initial scaffold)
```

`git log --oneline` is a decent narrative. Each commit message explains
*why*, not just *what*.

## Don't

- Don't commit `.env` (it's gitignored, but be explicit).
- Don't replace `MockSchoolProvider` with `GreatSchoolsProvider` without TJ
  signing off — he hasn't authorized the spend.
- Don't add features beyond what TJ asked for. He prefers narrow, tested
  changes over surface-area expansion.
- Don't introduce dependencies if you can avoid it. We manually parse
  `.env` rather than adding python-dotenv, for example.
