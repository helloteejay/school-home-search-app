"""Mock data generator — South Florida edition (Broward + Miami-Dade).

Produces realistic-looking school attendance boundaries for the top-rated
public schools across Broward and Miami-Dade counties, plus active listings
priced for each neighborhood. Replaces the original Austin grid scaffold.

All output mirrors the schema returned by the live providers so the rest of
the app does not know — or care — that it is running on fixtures.

School ratings come from the Florida DOE 2023-24 School Grades
(``data/SchoolGrades24.xlsx``, fetched from fldoe.org). Run
``scripts/fetch_school_grades.py`` to refresh when the next year publishes.
Centroids and polygon radii are still approximations — district GIS
boundary data is the next swap. See README for status.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon


# ---------------------------------------------------------------------------
# School fixture data — top-rated public schools in Broward + Miami-Dade.
#
# Each dict carries:
#   name, level, lat, lon, zone_radius_deg, zip_code, admission_type
#       — geometry inputs we own
#   rating, rating_pct, rating_source
#       — pulled from FL DOE 2023-24 School Grades; rating is a 1-10 scale
#         derived from the letter grade (A=10, B=8, C=6, D=4, F=2),
#         rating_pct preserves the underlying "Percent of Total Possible
#         Points" so finer-grained ranking is possible later.
#
# admission_type values:
#   "boundary" — attendance is determined by where you live (the app's job)
#   "magnet"   — admission by application/lottery; living in the polygon
#                does NOT guarantee enrollment. Filtered out by default.
#
# Radii are tuned for visible-but-distinct polygons at zoom ~10. Real
# attendance boundaries are TBD (see scripts/ and README).
# ---------------------------------------------------------------------------

_FLDOE_SOURCE = "FL DOE 2023-24 School Grades"

FL_SCHOOLS: List[Dict[str, Any]] = [
    # ---- Broward County ----
    # Weston cluster
    {"name": "Eagle Ridge Elementary",      "level": "Elementary", "rating": 10, "rating_pct": 62.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0930, "lon": -80.4007, "zone_radius_deg": 0.012, "zip_code": "33326", "admission_type": "boundary"},
    {"name": "Country Isles Elementary",    "level": "Elementary", "rating": 10, "rating_pct": 67.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.1090, "lon": -80.4138, "zone_radius_deg": 0.011, "zip_code": "33326", "admission_type": "boundary"},
    {"name": "Tequesta Trace Middle",       "level": "Middle",     "rating": 10, "rating_pct": 73.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0975, "lon": -80.4099, "zone_radius_deg": 0.018, "zip_code": "33326", "admission_type": "boundary"},
    {"name": "Cypress Bay High",            "level": "High",       "rating": 10, "rating_pct": 74.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0860, "lon": -80.4061, "zone_radius_deg": 0.030, "zip_code": "33327", "admission_type": "boundary"},
    # Parkland cluster
    {"name": "Riverglades Elementary",      "level": "Elementary", "rating": 10, "rating_pct": 70.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.3225, "lon": -80.2330, "zone_radius_deg": 0.013, "zip_code": "33067", "admission_type": "boundary"},
    {"name": "Park Trails Elementary",      "level": "Elementary", "rating": 10, "rating_pct": 74.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.3115, "lon": -80.2575, "zone_radius_deg": 0.014, "zip_code": "33076", "admission_type": "boundary"},
    {"name": "Westglades Middle",           "level": "Middle",     "rating": 10, "rating_pct": 74.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.3115, "lon": -80.2515, "zone_radius_deg": 0.020, "zip_code": "33076", "admission_type": "boundary"},
    {"name": "Marjory Stoneman Douglas HS", "level": "High",       "rating": 10, "rating_pct": 73.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.3105, "lon": -80.2702, "zone_radius_deg": 0.030, "zip_code": "33076", "admission_type": "boundary"},
    # Cooper City cluster
    {"name": "Embassy Creek Elementary",    "level": "Elementary", "rating": 10, "rating_pct": 72.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0573, "lon": -80.2858, "zone_radius_deg": 0.012, "zip_code": "33330", "admission_type": "boundary"},
    {"name": "Pioneer Middle",              "level": "Middle",     "rating": 10, "rating_pct": 75.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0593, "lon": -80.2870, "zone_radius_deg": 0.017, "zip_code": "33330", "admission_type": "boundary"},
    {"name": "Cooper City High",            "level": "High",       "rating": 10, "rating_pct": 70.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.0608, "lon": -80.2942, "zone_radius_deg": 0.025, "zip_code": "33330", "admission_type": "boundary"},
    # Coral Springs / Coconut Creek (mid-tier)
    {"name": "Heron Heights Elementary",    "level": "Elementary", "rating": 10, "rating_pct": 73.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.2640, "lon": -80.2730, "zone_radius_deg": 0.013, "zip_code": "33076", "admission_type": "boundary"},
    {"name": "Coral Springs High",          "level": "High",       "rating":  8, "rating_pct": 62.0, "rating_source": _FLDOE_SOURCE,
     "lat": 26.2475, "lon": -80.2530, "zone_radius_deg": 0.025, "zip_code": "33065", "admission_type": "boundary"},

    # ---- Miami-Dade County ----
    # Pinecrest / Palmetto Bay
    {"name": "Pinecrest Elementary",        "level": "Elementary", "rating": 10, "rating_pct": 76.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.6620, "lon": -80.3055, "zone_radius_deg": 0.012, "zip_code": "33156", "admission_type": "boundary"},
    {"name": "Coral Reef Elementary",       "level": "Elementary", "rating": 10, "rating_pct": 74.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.6580, "lon": -80.3015, "zone_radius_deg": 0.012, "zip_code": "33156", "admission_type": "boundary"},
    {"name": "Palmetto Middle",             "level": "Middle",     "rating": 10, "rating_pct": 64.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.6483, "lon": -80.3185, "zone_radius_deg": 0.018, "zip_code": "33156", "admission_type": "boundary"},
    {"name": "Miami Palmetto Senior High",  "level": "High",       "rating": 10, "rating_pct": 64.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.6573, "lon": -80.3192, "zone_radius_deg": 0.027, "zip_code": "33176", "admission_type": "boundary"},
    # Coral Gables
    {"name": "Sunset Elementary",           "level": "Elementary", "rating": 10, "rating_pct": 83.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7110, "lon": -80.2818, "zone_radius_deg": 0.010, "zip_code": "33143", "admission_type": "boundary"},
    # Henry S. West Lab is a UM partnership lab school — admission by lottery
    # weighted to faculty/staff. NOT a normal residential elementary.
    {"name": "Henry S. West Laboratory",    "level": "Elementary", "rating": 10, "rating_pct": 89.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7195, "lon": -80.2750, "zone_radius_deg": 0.010, "zip_code": "33134", "admission_type": "magnet"},
    # Ponce de Leon Middle dropped to C in 2023-24 (was made up at 8 before).
    {"name": "Ponce de Leon Middle",        "level": "Middle",     "rating":  6, "rating_pct": 55.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7263, "lon": -80.2705, "zone_radius_deg": 0.015, "zip_code": "33134", "admission_type": "boundary"},
    {"name": "Coral Gables Senior High",    "level": "High",       "rating": 10, "rating_pct": 67.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7273, "lon": -80.2769, "zone_radius_deg": 0.025, "zip_code": "33134", "admission_type": "boundary"},
    # Aventura — K-8 is residency-based for Aventura residents.
    {"name": "Aventura Waterways K-8",      "level": "K-8",        "rating": 10, "rating_pct": 68.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.9595, "lon": -80.1500, "zone_radius_deg": 0.013, "zip_code": "33180", "admission_type": "boundary"},
    {"name": "Dr. Michael M. Krop High",    "level": "High",       "rating":  8, "rating_pct": 58.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.9528, "lon": -80.1798, "zone_radius_deg": 0.025, "zip_code": "33180", "admission_type": "boundary"},
    # Doral K-8 is residency-based.
    {"name": "Eugenia B. Thomas K-8",       "level": "K-8",        "rating": 10, "rating_pct": 68.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.8120, "lon": -80.4040, "zone_radius_deg": 0.014, "zip_code": "33178", "admission_type": "boundary"},
    {"name": "Ronald W. Reagan/Doral Senior High", "level": "High", "rating": 8, "rating_pct": 61.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7800, "lon": -80.3700, "zone_radius_deg": 0.022, "zip_code": "33178", "admission_type": "boundary"},
    # Key Biscayne — MAST is a magnet HS (marine science). Application-based.
    {"name": "MAST Academy",                "level": "High",       "rating": 10, "rating_pct": 89.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.7383, "lon": -80.1693, "zone_radius_deg": 0.015, "zip_code": "33149", "admission_type": "magnet"},
    # Coral Reef Senior High is application-based magnet.
    {"name": "Coral Reef Senior High",      "level": "High",       "rating": 10, "rating_pct": 79.0, "rating_source": _FLDOE_SOURCE,
     "lat": 25.6347, "lon": -80.3895, "zone_radius_deg": 0.020, "zip_code": "33177", "admission_type": "magnet"},
]


# Friendly city names + state per ZIP so generated listings carry the right
# location label.
FL_CITIES_BY_ZIP = {
    "33326": ("Weston", "FL"),
    "33327": ("Weston", "FL"),
    "33330": ("Cooper City", "FL"),
    "33076": ("Parkland", "FL"),
    "33067": ("Parkland", "FL"),
    "33065": ("Coral Springs", "FL"),
    "33156": ("Pinecrest", "FL"),
    "33176": ("Palmetto Bay", "FL"),
    "33134": ("Coral Gables", "FL"),
    "33143": ("Coral Gables", "FL"),
    "33180": ("Aventura", "FL"),
    "33149": ("Key Biscayne", "FL"),
    "33178": ("Doral", "FL"),
    "33177": ("Miami", "FL"),
}


# (low, high) listing price band per ZIP, anchored to 2025 South Florida
# realities. Mock listings draw uniformly from this range.
ZIP_PRICE_BANDS = {
    "33326": (700_000,   2_500_000),  # Weston
    "33327": (800_000,   3_000_000),  # Weston west
    "33330": (500_000,   1_300_000),  # Cooper City
    "33076": (700_000,   2_200_000),  # Parkland
    "33067": (700_000,   2_000_000),  # Parkland
    "33065": (400_000,     900_000),  # Coral Springs
    "33156": (1_000_000, 4_000_000),  # Pinecrest
    "33176": (600_000,   1_500_000),  # Palmetto Bay (outer)
    "33134": (800_000,   3_500_000),  # Coral Gables
    "33143": (1_000_000, 4_000_000),  # South Miami / Gables
    "33180": (500_000,   2_500_000),  # Aventura
    "33149": (1_500_000, 8_000_000),  # Key Biscayne
    "33178": (450_000,   1_400_000),  # Doral
    "33177": (350_000,     750_000),  # Miami south
}


# Florida-feeling street names for synthetic addresses.
FL_STREETS = [
    "Ocean Dr", "Bayshore Blvd", "Palm Ave", "Hibiscus Ln", "Royal Palm Way",
    "Sunset Dr", "Coral Way", "Biscayne Blvd", "Las Olas Blvd", "Sample Rd",
    "Pines Blvd", "Stirling Rd", "Sheridan St", "Hollywood Blvd", "Dixie Hwy",
    "Coconut Palm Dr", "Mahogany Ln", "Banyan Trail", "Mangrove Ct", "Seagrape Ln",
    "Flamingo Rd", "Pelican Way", "Royal Poinciana Blvd", "Heron Bay Dr",
]


@dataclass
class MockConfig:
    """Knobs for the mock generator. Defaults give a realistic SoFlo scenario."""

    n_listings: int = 180
    seed: int = 42


# ---------------------------------------------------------------------------
# Polygon helpers
# ---------------------------------------------------------------------------

def _irregular_polygon(lat: float, lon: float, radius_deg: float, seed: int) -> Polygon:
    """Build an 8-vertex polygon around (lat, lon) with jittered radii so
    attendance zones look organic rather than square.
    """
    rng = random.Random(seed)
    pts = []
    for i in range(8):
        angle = i * (math.pi / 4)
        jitter = rng.uniform(0.7, 1.25)
        dx = math.cos(angle) * radius_deg * jitter
        dy = math.sin(angle) * radius_deg * jitter
        pts.append((lon + dx, lat + dy))
    return Polygon(pts)


# ---------------------------------------------------------------------------
# Public API — used by data_provider.MockSchoolProvider / MockListingsProvider
# ---------------------------------------------------------------------------

def generate_schools(cfg: MockConfig | None = None) -> gpd.GeoDataFrame:
    """Return a GeoDataFrame of mock South Florida schools w/ attendance zones.

    Columns: school_id, school_name, level, rating (1-10), rating_pct (the
    raw FL DOE "Percent of Total Possible Points"), rating_source, zip_code,
    admission_type ("boundary" or "magnet"), geometry.
    """
    rows = []
    for i, s in enumerate(FL_SCHOOLS):
        # Seed each polygon deterministically by name so re-runs render the
        # same boundaries.
        poly = _irregular_polygon(
            s["lat"], s["lon"], s["zone_radius_deg"],
            seed=abs(hash(s["name"])) % (2**31),
        )
        rows.append({
            "school_id": f"SCH-{i+1:03d}",
            "school_name": s["name"],
            "level": s["level"],
            "rating": s["rating"],
            "rating_pct": s.get("rating_pct"),
            "rating_source": s.get("rating_source"),
            "zip_code": s["zip_code"],
            "admission_type": s["admission_type"],
            "geometry": poly,
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def generate_listings(
    schools_gdf: gpd.GeoDataFrame,
    cfg: MockConfig | None = None,
) -> pd.DataFrame:
    """Generate mock active listings — most inside school zones, some outside.

    Returns a plain DataFrame (not a GeoDataFrame) with lat/lon columns so it
    matches the shape of typical real estate API responses.
    """
    cfg = cfg or MockConfig()
    rng = random.Random(cfg.seed + 1)

    listings = []
    listing_id = 100_000

    # ~80% of listings placed inside a school polygon (so the spatial filter
    # has something meaningful to keep), priced for that neighborhood.
    in_zone_count = int(cfg.n_listings * 0.8)
    schools = list(schools_gdf.itertuples(index=False))
    per_school = max(in_zone_count // max(len(schools), 1), 1)

    for school in schools:
        zip_code = school.zip_code
        city, state = FL_CITIES_BY_ZIP.get(zip_code, ("Miami", "FL"))
        low, high = ZIP_PRICE_BANDS.get(zip_code, (400_000, 1_000_000))
        minx, miny, maxx, maxy = school.geometry.bounds
        for _ in range(per_school):
            lon = rng.uniform(minx, maxx)
            lat = rng.uniform(miny, maxy)
            price = rng.randint(low, high)
            beds = rng.choices([2, 3, 4, 5, 6], weights=[1, 3, 5, 3, 1])[0]
            baths = rng.choices([1.5, 2, 2.5, 3, 3.5, 4], weights=[1, 4, 3, 4, 2, 1])[0]
            sqft = int(beds * rng.uniform(450, 850))
            listings.append({
                "listing_id": f"MLS-{listing_id}",
                "address": f"{rng.randint(100, 9999)} {rng.choice(FL_STREETS)}",
                "city": city,
                "state": state,
                "zip_code": zip_code,
                "price": price,
                "bedrooms": beds,
                "bathrooms": baths,
                "sqft": sqft,
                "year_built": rng.randint(1965, 2024),
                "latitude": lat,
                "longitude": lon,
                "listing_url": (
                    f"https://www.redfin.com/FL/{city.replace(' ', '-')}/"
                    f"home/{listing_id}"
                ),
            })
            listing_id += 1

    # Add a sprinkling of listings OUTSIDE the top-school polygons so the
    # spatial filter has visible rejects (and the "all listings" debug view
    # shows realistic noise).
    minx, miny, maxx, maxy = schools_gdf.total_bounds
    n_outside = cfg.n_listings - len(listings)
    for _ in range(max(n_outside, 0)):
        lat = rng.uniform(miny, maxy)
        lon = rng.uniform(minx, maxx)
        price = rng.randint(300_000, 1_500_000)
        listings.append({
            "listing_id": f"MLS-{listing_id}",
            "address": f"{rng.randint(100, 9999)} {rng.choice(FL_STREETS)}",
            "city": "Miami",
            "state": "FL",
            # Random "off-grid" ZIP so it doesn't accidentally match a top zone.
            "zip_code": f"330{rng.randint(40, 99)}",
            "price": price,
            "bedrooms": rng.choices([2, 3, 4], weights=[2, 4, 3])[0],
            "bathrooms": rng.choices([1.5, 2, 2.5, 3], weights=[1, 3, 2, 1])[0],
            "sqft": rng.randint(900, 2500),
            "year_built": rng.randint(1960, 2024),
            "latitude": lat,
            "longitude": lon,
            "listing_url": f"https://www.redfin.com/FL/Miami/home/{listing_id}",
        })
        listing_id += 1

    return pd.DataFrame(listings)


def generate_all(cfg: MockConfig | None = None) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Convenience helper: schools + listings in one call."""
    cfg = cfg or MockConfig()
    schools = generate_schools(cfg)
    listings = generate_listings(schools, cfg)
    return schools, listings
