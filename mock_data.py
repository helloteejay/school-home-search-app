"""Mock data generator for offline development.

Produces realistic-looking school attendance boundaries (as a tiled grid of
polygons over a target city) and active real estate listings scattered within
those boundaries. All output mirrors the schema returned by the live providers
so the rest of the app does not know — or care — that it is running on fixtures.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

# Austin, TX downtown-ish anchor. Easy to change for another city.
DEFAULT_CENTER_LAT = 30.2672
DEFAULT_CENTER_LON = -97.7431

# Grid configuration. A 4x4 tile of ~0.025 degrees per cell roughly covers
# a 10x10 mile slice of a metro area — enough variety to test filters.
GRID_ROWS = 4
GRID_COLS = 4
CELL_DEG = 0.025

# Pool of school names to draw from for the mock zones.
SCHOOL_POOL = [
    "Oakridge Elementary", "Hillcrest Middle", "Cedar Creek High",
    "Maplewood Elementary", "Riverbend Middle", "Summit Ridge High",
    "Lakeview Elementary", "Pinecrest Middle", "Crestwood High",
    "Bluebonnet Elementary", "Wildflower Middle", "Heritage Oaks High",
    "Sunset Valley Elementary", "Stone Mountain Middle", "Eagle Pass High",
    "Cypress Springs Elementary",
]

# Street name pool for synthetic addresses.
STREETS = [
    "Bluebonnet Ln", "Mockingbird Dr", "Live Oak St", "Pecan Grove Way",
    "Hill Country Rd", "Greenbelt Cir", "Shoal Creek Blvd", "Travis Heights Ave",
    "Barton Springs Rd", "Mesa Verde Dr", "Riverside Pkwy", "Tarrytown Ct",
]


@dataclass
class MockConfig:
    """Knobs for the mock generator. Defaults give a believable Austin scenario."""

    center_lat: float = DEFAULT_CENTER_LAT
    center_lon: float = DEFAULT_CENTER_LON
    grid_rows: int = GRID_ROWS
    grid_cols: int = GRID_COLS
    cell_deg: float = CELL_DEG
    n_listings: int = 120
    seed: int = 42


def _build_grid_polygons(cfg: MockConfig) -> List[Polygon]:
    """Tile a rectangular grid of polygons centered on (center_lat, center_lon)."""
    polys: List[Polygon] = []
    # Compute lower-left corner so the grid is centered on the anchor point.
    lon0 = cfg.center_lon - (cfg.grid_cols * cfg.cell_deg) / 2.0
    lat0 = cfg.center_lat - (cfg.grid_rows * cfg.cell_deg) / 2.0
    for r in range(cfg.grid_rows):
        for c in range(cfg.grid_cols):
            x0 = lon0 + c * cfg.cell_deg
            y0 = lat0 + r * cfg.cell_deg
            x1 = x0 + cfg.cell_deg
            y1 = y0 + cfg.cell_deg
            polys.append(Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
    return polys


def generate_schools(cfg: MockConfig | None = None) -> gpd.GeoDataFrame:
    """Return a GeoDataFrame of mock schools with attendance polygons.

    Columns: school_id, school_name, level, rating (1-10), zip_code, geometry.
    """
    cfg = cfg or MockConfig()
    rng = random.Random(cfg.seed)
    polys = _build_grid_polygons(cfg)

    # Bias the rating distribution so there is meaningful filtering to do.
    rating_pool = [3, 4, 5, 6, 6, 7, 7, 8, 8, 8, 9, 9, 10, 10, 7, 5]
    rng.shuffle(rating_pool)
    rating_pool = (rating_pool * ((len(polys) // len(rating_pool)) + 1))[: len(polys)]

    rows = []
    for i, poly in enumerate(polys):
        name = SCHOOL_POOL[i % len(SCHOOL_POOL)]
        # Level is implied by the name suffix to keep things readable.
        if "Elementary" in name:
            level = "Elementary"
        elif "Middle" in name:
            level = "Middle"
        else:
            level = "High"
        rows.append({
            "school_id": f"SCH-{i+1:03d}",
            "school_name": name,
            "level": level,
            "rating": rating_pool[i],
            # Fake ZIP varies by grid row so ZIP filtering does something.
            "zip_code": f"7870{(i % 9) + 1}",
            "geometry": poly,
        })

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return gdf


def generate_listings(
    schools_gdf: gpd.GeoDataFrame,
    cfg: MockConfig | None = None,
) -> pd.DataFrame:
    """Generate mock active listings scattered within the school grid bounds.

    Returns a plain DataFrame (not a GeoDataFrame) with lat/lon columns so it
    matches the shape of typical real estate API responses.
    """
    cfg = cfg or MockConfig()
    rng = random.Random(cfg.seed + 1)

    minx, miny, maxx, maxy = schools_gdf.total_bounds
    listings = []
    for i in range(cfg.n_listings):
        lon = rng.uniform(minx, maxx)
        lat = rng.uniform(miny, maxy)
        beds = rng.choices([2, 3, 4, 5, 6], weights=[1, 4, 5, 2, 1])[0]
        baths = rng.choices([1, 2, 3, 4], weights=[1, 4, 4, 1])[0]
        sqft = rng.randint(900, 4200)
        # Price scales loosely with size + a noise term — realistic for Austin.
        price = int(sqft * rng.uniform(280, 520) + rng.randint(-25000, 25000))
        listings.append({
            "listing_id": f"MLS-{100000 + i}",
            "address": f"{rng.randint(100, 9999)} {rng.choice(STREETS)}",
            "city": "Austin",
            "state": "TX",
            "zip_code": f"7870{rng.randint(1, 9)}",
            "price": price,
            "bedrooms": beds,
            "bathrooms": baths,
            "sqft": sqft,
            "year_built": rng.randint(1955, 2024),
            "latitude": lat,
            "longitude": lon,
            # Simulated listing URL so the table link column has something to open.
            "listing_url": f"https://example-listings.local/property/MLS-{100000 + i}",
        })
    return pd.DataFrame(listings)


def generate_all(cfg: MockConfig | None = None) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Convenience helper: schools + listings in one call."""
    cfg = cfg or MockConfig()
    schools = generate_schools(cfg)
    listings = generate_listings(schools, cfg)
    return schools, listings
