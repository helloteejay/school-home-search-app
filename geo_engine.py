"""Geospatial filtering — point-in-polygon checks via Shapely / GeoPandas.

Given a frame of listings (lat/lon) and a frame of school attendance polygons,
keep only the listings that physically fall inside at least one school zone
meeting the minimum rating, and annotate each surviving listing with its
assigned school.
"""

from __future__ import annotations

from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


def listings_to_geodataframe(listings: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert a plain listings DataFrame into a GeoDataFrame of points."""
    if listings.empty:
        return gpd.GeoDataFrame(
            listings.assign(geometry=[]), geometry="geometry", crs="EPSG:4326"
        )
    geometry = [Point(xy) for xy in zip(listings["longitude"], listings["latitude"])]
    return gpd.GeoDataFrame(listings.copy(), geometry=geometry, crs="EPSG:4326")


def filter_listings_in_top_schools(
    listings: pd.DataFrame,
    schools: gpd.GeoDataFrame,
    min_rating: int = 8,
) -> pd.DataFrame:
    """Return listings that sit inside a school zone with rating >= ``min_rating``.

    The output DataFrame is the original listings rows annotated with:

    ``assigned_school``, ``school_rating``, ``school_level``, ``school_id``

    If a listing falls inside multiple qualifying zones (e.g. an elementary
    and a high school both serve the same address) the highest-rated zone
    wins, then highest level (High > Middle > Elementary) as a tiebreaker.
    """
    if listings.empty or schools.empty:
        return _empty_result(listings)

    qualifying = schools[schools["rating"] >= int(min_rating)].copy()
    if qualifying.empty:
        return _empty_result(listings)

    listings_gdf = listings_to_geodataframe(listings)

    # Spatial join: each listing × each polygon it falls inside.
    # ``predicate="within"`` is the modern GeoPandas API for point-in-polygon.
    joined = gpd.sjoin(
        listings_gdf,
        qualifying[["school_id", "school_name", "level", "rating", "geometry"]],
        how="inner",
        predicate="within",
    )

    if joined.empty:
        return _empty_result(listings)

    # Resolve multi-zone matches: pick the best school per listing.
    level_order = {"High": 3, "Middle": 2, "Elementary": 1}
    joined["_level_rank"] = joined["level"].map(level_order).fillna(0)
    joined = (
        joined.sort_values(["rating", "_level_rank"], ascending=[False, False])
        .drop_duplicates(subset="listing_id", keep="first")
    )

    out = joined.drop(columns=["geometry", "index_right", "_level_rank"]).rename(
        columns={
            "school_name": "assigned_school",
            "rating": "school_rating",
            "level": "school_level",
        }
    )
    return out.reset_index(drop=True)


def _empty_result(listings: pd.DataFrame) -> pd.DataFrame:
    """Build an empty result frame that still has the annotated columns."""
    cols = list(listings.columns) + [
        "assigned_school",
        "school_rating",
        "school_level",
        "school_id",
    ]
    return pd.DataFrame(columns=cols)


def rating_to_color(rating: int) -> str:
    """Map a 1-10 GreatSchools-style rating to a Folium-friendly hex color."""
    if rating >= 9:
        return "#1a7f37"   # deep green
    if rating >= 7:
        return "#2da44e"   # green
    if rating >= 5:
        return "#d4a72c"   # amber
    if rating >= 3:
        return "#cf222e"   # red
    return "#82071e"       # dark red


def schools_bbox(
    schools: gpd.GeoDataFrame,
    listings: Optional[pd.DataFrame] = None,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return ((south, west), (north, east)) so Folium can fit_bounds the map."""
    if schools is None or schools.empty:
        if listings is not None and not listings.empty:
            return (
                (float(listings["latitude"].min()), float(listings["longitude"].min())),
                (float(listings["latitude"].max()), float(listings["longitude"].max())),
            )
        # Reasonable Austin default if we have nothing.
        return ((30.15, -97.90), (30.40, -97.60))

    minx, miny, maxx, maxy = schools.total_bounds
    return ((miny, minx), (maxy, maxx))


def zoom_for_bbox(south: float, west: float, north: float, east: float) -> int:
    """Heuristic initial zoom for a lat/lon bbox.

    Folium's ``fit_bounds`` is unreliable inside streamlit-folium because the
    iframe is sized after the map initializes — Leaflet computes the wrong
    zoom against a smaller-than-final container. Setting ``zoom_start`` from
    the bbox up front avoids the race.
    """
    span = max(abs(north - south), abs(east - west))
    if span > 5:
        return 6
    if span > 2:
        return 8
    if span > 0.5:
        return 10
    if span > 0.1:
        return 11
    if span > 0.03:
        return 12
    return 13
