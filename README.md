# School-Quality Home Search

Local-only Streamlit app that filters active real estate listings to homes
sitting inside the attendance zone of a top-rated public school.

## Quick start

```bash
cd school-home-finder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app boots with mock data for Broward + Miami-Dade counties, FL — covering
top-rated public school zones in Weston, Parkland, Cooper City, Coral Springs,
Pinecrest, Palmetto Bay, Coral Gables, Aventura, Doral, and Key Biscayne. No
API keys required.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit UI, sidebar filters, Folium map, AgGrid table |
| `data_provider.py` | Abstract `SchoolDataProvider` / `ListingsDataProvider` interfaces, mock implementations, and live HTTP skeletons (GreatSchools, Realty Mole) |
| `geo_engine.py` | Point-in-polygon filtering with Shapely/GeoPandas + map-color helpers |
| `mock_data.py` | ~27 real Broward + Miami-Dade schools w/ polygon zones + ~180 listings priced by ZIP |
| `requirements.txt` | Dependencies |

## Switching to live data

Set the relevant API keys and enable live mode:

```bash
export USE_LIVE_DATA=true
export RAPIDAPI_KEY=...         # Realty Mole via RapidAPI
export GREATSCHOOLS_API_KEY=... # GreatSchools (boundary feed plugged in separately)
streamlit run app.py
```

`GreatSchoolsProvider._fetch_boundaries` is left unimplemented on purpose —
every region's boundary source is different (state DOE, district GIS, vendor
feed). Plug yours in there.

## How the filter works

1. The school provider returns polygons + ratings.
2. The listings provider returns lat/lon points.
3. `geo_engine.filter_listings_in_top_schools` runs a GeoPandas `sjoin`
   (`predicate="within"`) keeping only points inside polygons whose
   `rating >= min_rating`, then collapses multi-zone matches to the
   highest-rated school per listing.
