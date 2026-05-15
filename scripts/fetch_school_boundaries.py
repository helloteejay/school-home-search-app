"""Refresh real elementary attendance-boundary polygons for the schools in
FL_SCHOOLS.

Pulls GeoJSON from each district's open data ArcGIS service and writes:

  data/boundaries/broward_elementary.geojson
  data/boundaries/miamidade_elementary.geojson

Usage:
    python scripts/fetch_school_boundaries.py [--force]

Sources:
  Broward — services.arcgis.com/JMAJrTsHNLrSsWf5/.../AllSchoolBoundaries/8
            (filtered to SCHOOLTYPE='Elementary School')
  Miami-Dade — services.arcgis.com/8Pc9XBTAsYuxx9Ny/.../ElementaryAttendanceBoundary_gdb/0

After running, ``python -c 'import mock_data; mock_data._load_boundary_cache.cache_clear() if hasattr(mock_data._load_boundary_cache, "cache_clear") else None'``
isn't needed — Streamlit reloads on file change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "boundaries"

# (county_key, output_filename, REST query URL)
ENDPOINTS = {
    "broward": (
        "broward_elementary.geojson",
        # The all-levels service; filter to elementary via the query string.
        "https://services.arcgis.com/JMAJrTsHNLrSsWf5/arcgis/rest/services/"
        "AllSchoolBoundaries/FeatureServer/8/query?"
        "where=SCHOOLTYPE%3D%27Elementary%20School%27"
        "&outFields=NAME,SCHOOLTYPE,LOC_NO"
        "&returnGeometry=true&outSR=4326&f=geojson",
    ),
    "miamidade": (
        "miamidade_elementary.geojson",
        "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/"
        "ElementaryAttendanceBoundary_gdb/FeatureServer/0/query?"
        "where=1%3D1"
        "&outFields=NAME,DISPLAYNAME,ZIPCODE,ID"
        "&returnGeometry=true&outSR=4326&f=geojson",
    ),
}


def fetch(url: str, dest: Path) -> int:
    """curl the URL to dest; return feature count."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  GET {url[:80]}...")
    subprocess.run(["curl", "-sSL", "-o", str(dest), url], check=True)
    with dest.open() as f:
        data = json.load(f)
    feats = data.get("features", [])
    if not feats:
        raise RuntimeError(f"Empty feature collection from {url}")
    return len(feats)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Re-fetch even if files exist")
    args = p.parse_args()

    for county, (filename, url) in ENDPOINTS.items():
        dest = DATA_DIR / filename
        if dest.exists() and not args.force:
            print(f"{county}: cached at {dest} (use --force to refresh)")
            continue
        print(f"{county}: fetching to {dest}")
        n = fetch(url, dest)
        print(f"  -> {n} features ({dest.stat().st_size:,} bytes)")

    print("\nDone. Restart streamlit (or hit Rerun in the toolbar) to pick up changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
