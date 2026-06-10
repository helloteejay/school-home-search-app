# Agent orientation

You're picking up a working Streamlit app TJ uses for his family's house hunt.
Get oriented in 60 seconds, then keep going.

## What this is

Filter active home listings to **only homes inside the attendance zone of a
top-rated elementary school**. The unique value vs. Zillow/Redfin is the
*inverse* filter — Zillow shows you a home and the school it's zoned for;
this app shows you the homes whose zoning meets a school-quality threshold.

- **User**: TJ Allison <hello@tjallison.com>. Family relocating from NYC to FL.
- **Scope today**: Broward + Miami-Dade counties, FL. ~142 A-rated boundary
  elementary schools across both counties.
- **Scope wanted**: US-wide, with the ability to target specific metros. See
  "Expansion" below — this is the active stretch goal.

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
| `app.py` | Streamlit UI. Sidebar filters → cached fetch → spatial join → Folium map + AgGrid table. Live mode uses one broad radius RentCast query (`_fetch_listings_in_radius`); ZIP mode is fallback. |

## Data lineage (provenance matters — don't skip this)

| Layer | Source | Refresh script |
|---|---|---|
| School ratings | FL DOE 2023-24 School Grades XLSX (vendored at `data/SchoolGrades24.xlsx`). Letter → 10/8/6/4/2 mapping + raw `rating_pct`. | `scripts/fetch_school_grades.py` |
| Attendance polygons | Broward `AllSchoolBoundaries` + Miami-Dade `ElementaryAttendanceBoundary` ArcGIS REST. Cached at `data/boundaries/*.geojson`. | `scripts/fetch_school_boundaries.py` |
| Generated school list | The join of the above two. | `scripts/build_fl_schools.py` |
| Listings | RentCast `/v1/listings/sale` with lat/lon+radius. | Live runtime; cached in Streamlit session. |

Every school carries a `boundary_source` field (`"district"` or `"synthetic"`)
and a `rating_source` field (`"FL DOE 2023-24 School Grades"`). The map
tooltip says "Boundary: district GIS" or "Boundary: approximate" so TJ
always knows which kind of polygon he's looking at. **Preserve this
traceability** — it's why the audit signed off.

## What's done

- ✅ Real ratings (FL DOE) — not made up
- ✅ Real attendance polygons (Broward + Miami-Dade GIS)
- ✅ Magnet/lab schools excluded by default via `admission_type` field
- ✅ Live RentCast listings with quota-efficient radius queries
- ✅ 142 elementary zones, ~250 qualifying homes at default filters
- ✅ Pushed to GitHub; deployed on Streamlit Cloud

## What's NOT done (current ask)

**Expand beyond Broward + Miami-Dade.** TJ wants to point this at the
entire US, with the ability to target specific metros. The constraint:
**no free national attendance-boundary dataset exists.** Three real paths:

| Path | Trade-off |
|---|---|
| **A. Per-metro curation** | Free + high accuracy. ~2-3 hrs per new metro (find district GIS + state rating file + write a small loader, same pattern as `scripts/build_fl_schools.py`). |
| **B. GreatSchools API** | ~$50/mo, US-wide ratings, but "nearest school" instead of "in attendance zone" — meaningfully less accurate. TJ has said he doesn't want to pay. |
| **C. ATTOM / SchoolDigger enterprise** | $500+/mo. TJ has rejected. |

**Recommended approach:** Path A, one metro at a time. The `SchoolDataProvider`
abstraction supports it — a new metro is a new `*_SCHOOLS` data file +
boundary GeoJSONs + a small loader in `mock_data.py`. Ask TJ which metros
are on his shortlist before building anything broad.

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
