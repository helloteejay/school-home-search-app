"""Generate the FL_SCHOOLS list by joining FL DOE School Grades with
district elementary-attendance-boundary GeoJSON.

Inputs (must already exist; refresh with the sibling fetch scripts):
  data/SchoolGrades24.xlsx
  data/boundaries/broward_elementary.geojson
  data/boundaries/miamidade_elementary.geojson

Output:
  data/schools_generated.py — Python module containing a single
  ``GENERATED_SCHOOLS`` list of dicts. mock_data.py reads this when
  present and falls back to its hand-coded baseline otherwise.

Policy:
- Include only Elementary + K-8 schools (the level the app filters on)
- Include only schools with grade A or B from FL DOE 2023-24
- Skip charters (Charter School = YES) and alternative/ESE centers
- Schools without a matching polygon in the district GeoJSON are SKIPPED
  — without a real boundary the point-in-polygon filter would be wrong
- Magnet overrides: a small hand-maintained list of schools that ARE in
  the boundary feed but whose enrollment is application/lottery (e.g.
  lab schools). Tagged ``admission_type="magnet"`` so the elementary
  filter excludes them by default.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402
from shapely.geometry import shape  # noqa: E402


REPO = Path(__file__).resolve().parent.parent
DOE_XLSX = REPO / "data" / "SchoolGrades24.xlsx"
BROWARD_GJ = REPO / "data" / "boundaries" / "broward_elementary.geojson"
MD_GJ = REPO / "data" / "boundaries" / "miamidade_elementary.geojson"
OUT_PATH = REPO / "data" / "schools_generated.py"

FL_GRADE_TO_RATING = {"A": 10, "B": 8, "C": 6, "D": 4, "F": 2}

# Known magnet schools: live in the boundary feed but enrollment is
# application-based (lab schools, marine science, etc.). Override what
# the join would default to ("boundary").
MAGNET_OVERRIDES = {
    "HENRY S. WEST LABORATORY SCHOOL",      # Miami-Dade UM lab school
    "MAST ACADEMY",                          # Miami-Dade marine science magnet
    "CORAL REEF SENIOR HIGH SCHOOL",         # not elementary, but tag anyway
}

# Friendly display name overrides (FL DOE's all-caps is shouty in the UI).
def _title_case(name: str) -> str:
    """Title-case a school name with smart handling of common abbrevs."""
    # Strip trailing " SCHOOL" if it's redundant
    n = name.strip()
    # Common all-caps tokens to preserve
    preserve = {"K-8", "K8", "PK-8", "ESE", "STEM", "JR", "SR", "II", "III", "IV"}
    parts = []
    for word in n.split():
        if word in preserve:
            parts.append(word)
        elif word.endswith(",") and word[:-1] in preserve:
            parts.append(word)
        else:
            # Handle "S." style initials and common patterns
            parts.append(word.title())
    return " ".join(parts)


def _normalize_for_match(name: str) -> str:
    """Aggressively normalize a school name for fuzzy matching."""
    s = name.upper()
    # Remove common suffixes that vary across data sources
    for suffix in [
        " ELEMENTARY SCHOOL", " ELEMENTARY", " K-8 CENTER", " K-8",
        " K8 CENTER", " K8", " PK-8", " CENTER", " SCHOOL", " MAGNET",
    ]:
        s = s.replace(suffix, "")
    # Drop punctuation we don't care about
    s = re.sub(r"[.,'\-]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_boundary_index(geojson_path: Path) -> dict:
    """Index a district's elementary GeoJSON by normalized school name."""
    if not geojson_path.exists():
        print(f"WARN: missing {geojson_path}", file=sys.stderr)
        return {}
    with geojson_path.open() as f:
        gj = json.load(f)
    by_norm = {}
    for feat in gj.get("features", []):
        props = feat.get("properties") or {}
        name = props.get("NAME") or ""
        if not name or not feat.get("geometry"):
            continue
        norm = _normalize_for_match(name)
        by_norm[norm] = (name, props, feat["geometry"])
    return by_norm


def _token_sort(s: str) -> str:
    """Sort the words alphabetically — kills word-order differences like
    "Eugenia B Thomas" vs "Thomas Eugenia B".
    """
    return " ".join(sorted(s.split()))


def match_boundary(
    doe_name: str,
    district: str,
    broward: dict,
    miamidade: dict,
) -> tuple | None:
    """Return (gis_name, properties, geometry) for the DOE school, or None."""
    idx = broward if district == "BROWARD" else miamidade
    norm = _normalize_for_match(doe_name)

    # Exact match first
    if norm in idx:
        return idx[norm]

    # Token-sort match — handles "First Last" vs "Last, First" formats
    norm_sorted = _token_sort(norm)
    sorted_idx = {_token_sort(k): v for k, v in idx.items()}
    if norm_sorted in sorted_idx:
        return sorted_idx[norm_sorted]

    # Fuzzy fallback against both forms
    candidates = (
        difflib.get_close_matches(norm, idx.keys(), n=1, cutoff=0.82)
        or difflib.get_close_matches(norm_sorted, sorted_idx.keys(), n=1, cutoff=0.82)
    )
    if candidates:
        return sorted_idx.get(candidates[0]) or idx.get(candidates[0])
    return None


def derive_radius_deg(geometry: dict) -> float:
    """Crude radius hint from polygon bounds — used only as a tooltip /
    legend cue, not for the actual filter."""
    poly = shape(geometry)
    minx, miny, maxx, maxy = poly.bounds
    return max(maxx - minx, maxy - miny) / 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--min-grade",
        choices=["A", "B", "C"],
        default="A",
        help="Lowest FL DOE letter grade to include (default A)",
    )
    args = p.parse_args()

    min_rating = FL_GRADE_TO_RATING[args.min_grade]

    print(f"Loading FL DOE grades from {DOE_XLSX}")
    df = pd.read_excel(
        DOE_XLSX, sheet_name="School Grades 2024", engine="openpyxl", header=3
    )
    df.columns = [str(c).strip() for c in df.columns]

    sub = df[df["District Name"].isin(["BROWARD", "MIAMI-DADE"])].copy()
    elem_mask = sub["School Name"].astype(str).str.contains(
        "ELEMENTARY|K-8|K8", regex=True, na=False
    )
    sub = sub[elem_mask]

    # Skip charters + alternative/ESE
    sub = sub[~sub["Charter School"].astype(str).str.upper().isin({"YES", "Y"})]
    sub = sub[
        ~sub["Alternative/ESE Center School"].astype(str).str.upper().isin({"YES", "Y"})
    ]

    print(f"  {len(sub)} non-charter, non-alternative elementaries in scope")

    print(f"Loading boundary indexes")
    broward = load_boundary_index(BROWARD_GJ)
    md = load_boundary_index(MD_GJ)
    print(f"  Broward index: {len(broward)} schools")
    print(f"  Miami-Dade index: {len(md)} schools")

    generated = []
    matched_at_grade = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    unmatched = []

    for _, row in sub.iterrows():
        grade = str(row["Grade 2024"]).strip()
        if grade not in FL_GRADE_TO_RATING:
            continue
        rating = FL_GRADE_TO_RATING[grade]
        if rating < min_rating:
            continue

        doe_name = str(row["School Name"]).strip()
        district = row["District Name"]
        result = match_boundary(doe_name, district, broward, md)
        if result is None:
            unmatched.append(f"{district}: {doe_name}")
            continue

        gis_name, props, geometry = result
        poly = shape(geometry)
        centroid = poly.centroid

        # Determine level — K-8s announce themselves in the name
        upper = doe_name.upper()
        if "K-8" in upper or "K8" in upper or "PK-8" in upper:
            level = "K-8"
        else:
            level = "Elementary"

        # Magnet override
        admission_type = "magnet" if gis_name.upper() in MAGNET_OVERRIDES else "boundary"

        # ZIP: prefer the GIS property if present (Miami-Dade has ZIPCODE),
        # else leave blank (Broward doesn't expose ZIP in its boundary feed).
        zip_code = ""
        if "ZIPCODE" in props and props["ZIPCODE"]:
            try:
                zip_code = str(int(props["ZIPCODE"]))
            except (ValueError, TypeError):
                pass

        generated.append({
            "name": _title_case(doe_name),
            "gis_name": gis_name,
            "level": level,
            "rating": rating,
            "rating_pct": float(row["Percent of Total Possible Points"])
                          if pd.notna(row["Percent of Total Possible Points"]) else None,
            "rating_source": "FL DOE 2023-24 School Grades",
            "lat": round(float(centroid.y), 6),
            "lon": round(float(centroid.x), 6),
            "zone_radius_deg": round(derive_radius_deg(geometry), 4),
            "zip_code": zip_code,
            "admission_type": admission_type,
            "district": "broward" if district == "BROWARD" else "miamidade",
            "doe_name": doe_name,
        })
        matched_at_grade[grade] += 1

    print(f"\nMatched: {len(generated)} schools")
    for g, n in matched_at_grade.items():
        if n:
            print(f"  Grade {g}: {n}")
    print(f"Unmatched (no GIS boundary): {len(unmatched)}")
    for u in unmatched[:10]:
        print(f"  - {u}")
    if len(unmatched) > 10:
        print(f"  ... +{len(unmatched) - 10} more")

    # Write the generated module
    print(f"\nWriting {OUT_PATH}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        f.write('"""Generated by scripts/build_fl_schools.py — do not edit by hand.\n\n')
        f.write(f"Source: FL DOE 2023-24 School Grades x Broward/Miami-Dade GIS\n")
        f.write(f"Generated: {pd.Timestamp.now().isoformat()}\n")
        f.write(f'Schools: {len(generated)} (min grade {args.min_grade})\n')
        f.write('"""\n\n')
        f.write("from __future__ import annotations\n\n")
        f.write("GENERATED_SCHOOLS = [\n")
        for s in generated:
            f.write("    " + repr(s) + ",\n")
        f.write("]\n")

    print(f"Done. {len(generated)} schools written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
