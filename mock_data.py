"""Mock data generator — South Florida edition (Broward + Miami-Dade).

Produces realistic-looking school attendance boundaries for the top-rated
public schools across Broward and Miami-Dade counties, plus active listings
priced for each neighborhood. Replaces the original Austin grid scaffold.

All output mirrors the schema returned by the live providers so the rest of
the app does not know — or care — that it is running on fixtures.

Note: school centroids and ratings are approximations of public data, not
guarantees of current GreatSchools ratings. Swap in a live SchoolDataProvider
once you've licensed boundary data.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon


# ---------------------------------------------------------------------------
# School fixture data — top-rated public schools in Broward + Miami-Dade.
# Format: (name, level, rating, lat, lon, zone_radius_deg, zip_code, admission_type)
#
# admission_type values:
#   "boundary" — attendance is determined by where you live (the use case
#                this app is built for)
#   "magnet"   — admission by application/lottery; living in the polygon
#                does NOT guarantee enrollment. Filtered out by default so
#                TJ's family doesn't get false confidence from a magnet zone.
#
# Radii are tuned to give visible-but-distinct polygons on the map at a
# typical zoom of ~10 over both counties.
# ---------------------------------------------------------------------------

FL_SCHOOLS: List[Tuple[str, str, int, float, float, float, str, str]] = [
    # ---- Broward County ----
    # Weston cluster
    ("Eagle Ridge Elementary",      "Elementary", 10, 26.0930, -80.4007, 0.012, "33326", "boundary"),
    ("Country Isles Elementary",    "Elementary", 10, 26.1090, -80.4138, 0.011, "33326", "boundary"),
    ("Tequesta Trace Middle",       "Middle",      9, 26.0975, -80.4099, 0.018, "33326", "boundary"),
    ("Cypress Bay High",            "High",        9, 26.0860, -80.4061, 0.030, "33327", "boundary"),
    # Parkland cluster
    ("Riverglades Elementary",      "Elementary", 10, 26.3225, -80.2330, 0.013, "33067", "boundary"),
    ("Park Trails Elementary",      "Elementary", 10, 26.3115, -80.2575, 0.014, "33076", "boundary"),
    ("Westglades Middle",           "Middle",      9, 26.3115, -80.2515, 0.020, "33076", "boundary"),
    ("Marjory Stoneman Douglas HS", "High",        8, 26.3105, -80.2702, 0.030, "33076", "boundary"),
    # Cooper City cluster
    ("Embassy Creek Elementary",    "Elementary", 10, 26.0573, -80.2858, 0.012, "33330", "boundary"),
    ("Pioneer Middle",              "Middle",      9, 26.0593, -80.2870, 0.017, "33330", "boundary"),
    ("Cooper City High",            "High",        8, 26.0608, -80.2942, 0.025, "33330", "boundary"),
    # Coral Springs / Coconut Creek (mid-tier)
    ("Heron Heights Elementary",    "Elementary",  9, 26.2640, -80.2730, 0.013, "33076", "boundary"),
    ("Coral Springs High",          "High",        7, 26.2475, -80.2530, 0.025, "33065", "boundary"),

    # ---- Miami-Dade County ----
    # Pinecrest / Palmetto Bay
    ("Pinecrest Elementary",        "Elementary", 10, 25.6620, -80.3055, 0.012, "33156", "boundary"),
    ("Coral Reef Elementary",       "Elementary",  9, 25.6580, -80.3015, 0.012, "33156", "boundary"),
    ("Palmetto Middle",             "Middle",      8, 25.6483, -80.3185, 0.018, "33156", "boundary"),
    ("Miami Palmetto Senior High",  "High",        8, 25.6573, -80.3192, 0.027, "33176", "boundary"),
    # Coral Gables
    ("Sunset Elementary",           "Elementary", 10, 25.7110, -80.2818, 0.010, "33143", "boundary"),
    # Henry S. West Lab is a UM partnership lab school — admission by lottery
    # weighted to faculty/staff. NOT a normal residential elementary.
    ("Henry S. West Laboratory",    "Elementary",  9, 25.7195, -80.2750, 0.010, "33134", "magnet"),
    ("Ponce de Leon Middle",        "Middle",      8, 25.7263, -80.2705, 0.015, "33134", "boundary"),
    ("Coral Gables Senior High",    "High",        8, 25.7273, -80.2769, 0.025, "33134", "boundary"),
    # Aventura — K-8 is residency-based for Aventura residents.
    ("Aventura Waterways K-8",      "Elementary",  9, 25.9595, -80.1500, 0.013, "33180", "boundary"),
    ("Dr. Michael M. Krop High",    "High",        7, 25.9528, -80.1798, 0.025, "33180", "boundary"),
    # Doral K-8 is residency-based.
    ("Eugenia B. Thomas K-8",       "Elementary",  9, 25.8120, -80.4040, 0.014, "33178", "boundary"),
    ("Doral Academy / Reagan HS",   "High",        8, 25.7800, -80.3700, 0.022, "33178", "boundary"),
    # Key Biscayne — MAST is a magnet HS (marine science). Application-based.
    ("MAST Academy",                "High",       10, 25.7383, -80.1693, 0.015, "33149", "magnet"),
    # Coral Reef Senior High is application-based magnet (medical sciences,
    # international studies, agriscience programs). Geography doesn't help.
    ("Coral Reef Senior High",      "High",       10, 25.6347, -80.3895, 0.020, "33177", "magnet"),
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

    Columns: school_id, school_name, level, rating (1-10), zip_code,
    admission_type ("boundary" or "magnet"), geometry.
    """
    rows = []
    for i, (name, level, rating, lat, lon, r, zip_code, admission_type) in enumerate(FL_SCHOOLS):
        # Seed each polygon deterministically by name so re-runs render the
        # same boundaries.
        poly = _irregular_polygon(lat, lon, r, seed=abs(hash(name)) % (2**31))
        rows.append({
            "school_id": f"SCH-{i+1:03d}",
            "school_name": name,
            "level": level,
            "rating": rating,
            "zip_code": zip_code,
            "admission_type": admission_type,
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
