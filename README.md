# School-Quality Home Search

Local-only Streamlit app that filters active real estate listings to homes
sitting inside the attendance zone of a top-rated **elementary** public
school. MVP scope: Broward + Miami-Dade counties (Weston, Parkland, Cooper
City, Pinecrest, Coral Gables, Aventura, Doral, Key Biscayne).

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
| `data/SchoolGrades24.xlsx` | Florida DOE 2023-24 School Grades (source of `FL_SCHOOLS` ratings) |
| `scripts/fetch_school_grades.py` | Re-fetch the FL DOE file + print drift vs. current `FL_SCHOOLS` |

## Ratings source

Ratings in `mock_data.FL_SCHOOLS` come from the [Florida DOE 2023-24
School Grades](https://www.fldoe.org/accountability/accountability-reporting/school-grades/)
(`data/SchoolGrades24.xlsx`). Mapping is letter-to-rating: A=10, B=8, C=6,
D=4, F=2. The underlying "Percent of Total Possible Points" is also kept
per school as `rating_pct` for finer-grained ranking later.

When the next school year's grades publish (typically September):

```bash
python scripts/fetch_school_grades.py --year 25 --force-download
```

The script prints a diff against the current `FL_SCHOOLS` ratings. Update
the dicts by hand — staying explicit so we can audit what changed.

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
3. `geo_engine.filter_listings_in_top_elementary_zones` scopes the spatial
   join to Elementary + K-8 schools only (the levels TJ cares about),
   excludes `admission_type == "magnet"` by default (since magnet
   enrollment is by application/lottery, not geography), and keeps homes
   whose elementary zone meets `min_rating`.
