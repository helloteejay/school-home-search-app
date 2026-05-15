"""Refresh FL DOE school-grade ratings for the schools in FL_SCHOOLS.

Downloads (or reuses) the Florida DOE annual School Grades XLSX, looks up
each school by name + district, prints a diff against the current mock_data
ratings, and emits a snippet you can paste into FL_SCHOOLS.

Usage:
    python scripts/fetch_school_grades.py [--year 24] [--force-download]

The default year (``24``) targets ``SchoolGrades24.xlsx`` — the 2023-24
school year, published in September 2024. Florida publishes a new file
each summer; update ``--year`` when the next release lands.

Source: https://www.fldoe.org/accountability/accountability-reporting/school-grades/
File URL pattern: https://www.fldoe.org/file/18534/SchoolGrades{year}.xlsx
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Add the parent directory to the path so we can import mock_data.FL_SCHOOLS.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # type: ignore  # noqa: E402

import mock_data  # noqa: E402


DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FL_GRADE_TO_RATING = {"A": 10, "B": 8, "C": 6, "D": 4, "F": 2}

# (display name in our FL_SCHOOLS, substring to find in FL DOE School Name,
#  optional district filter to disambiguate when names collide across counties)
LOOKUPS = [
    ("Eagle Ridge Elementary",           "EAGLE RIDGE ELEMENTARY",         "BROWARD"),
    ("Country Isles Elementary",         "COUNTRY ISLES ELEMENTARY",       "BROWARD"),
    ("Tequesta Trace Middle",            "TEQUESTA TRACE MIDDLE",          "BROWARD"),
    ("Cypress Bay High",                 "CYPRESS BAY HIGH",               "BROWARD"),
    ("Riverglades Elementary",           "RIVERGLADES ELEMENTARY",         "BROWARD"),
    ("Park Trails Elementary",           "PARK TRAILS ELEMENTARY",         "BROWARD"),
    ("Westglades Middle",                "WESTGLADES MIDDLE",              "BROWARD"),
    ("Marjory Stoneman Douglas HS",      "STONEMAN DOUGLAS",               "BROWARD"),
    ("Embassy Creek Elementary",         "EMBASSY CREEK ELEMENTARY",       "BROWARD"),
    ("Pioneer Middle",                   "PIONEER MIDDLE",                 "BROWARD"),
    ("Cooper City High",                 "COOPER CITY HIGH",               "BROWARD"),
    ("Heron Heights Elementary",         "HERON HEIGHTS ELEMENTARY",       "BROWARD"),
    ("Coral Springs High",               "CORAL SPRINGS HIGH",             "BROWARD"),
    ("Pinecrest Elementary",             "PINECREST ELEMENTARY SCHOOL",    "MIAMI-DADE"),
    ("Coral Reef Elementary",            "CORAL REEF ELEMENTARY",          "MIAMI-DADE"),
    ("Palmetto Middle",                  "PALMETTO MIDDLE",                "MIAMI-DADE"),
    ("Miami Palmetto Senior High",       "PALMETTO SENIOR HIGH",           "MIAMI-DADE"),
    ("Sunset Elementary",                "SUNSET ELEMENTARY SCHOOL",       "MIAMI-DADE"),
    ("Henry S. West Laboratory",         "WEST LABORATORY",                "MIAMI-DADE"),
    ("Ponce de Leon Middle",             "PONCE DE LEON MIDDLE",           "MIAMI-DADE"),
    ("Coral Gables Senior High",         "CORAL GABLES SENIOR",            "MIAMI-DADE"),
    ("Aventura Waterways K-8",           "AVENTURA WATERWAYS",             "MIAMI-DADE"),
    ("Dr. Michael M. Krop High",         "DR. MICHAEL M. KROP",            "MIAMI-DADE"),
    ("Eugenia B. Thomas K-8",            "EUGENIA B. THOMAS",              "MIAMI-DADE"),
    ("Ronald W. Reagan/Doral Senior High", "REAGAN/DORAL",                 "MIAMI-DADE"),
    ("MAST Academy",                     "MAST ACADEMY",                   "MIAMI-DADE"),
    ("Coral Reef Senior High",           "CORAL REEF SENIOR",              "MIAMI-DADE"),
]


def download_grades_file(year: str, force: bool = False) -> Path:
    """Download (or reuse) the FL DOE School Grades XLSX for the given year."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / f"SchoolGrades{year}.xlsx"
    if dest.exists() and not force:
        return dest
    # FL DOE is behind Akamai; need browser-like headers to avoid 403.
    url = f"https://www.fldoe.org/file/18534/SchoolGrades{year}.xlsx"
    print(f"Downloading {url} -> {dest}")
    cmd = [
        "curl", "-sSL", "-o", str(dest),
        "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "-H", "Accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
        "-H", "Accept-Language: en-US,en;q=0.9",
        "-H", f"Referer: https://www.fldoe.org/accountability/accountability-reporting/school-grades/",
        "--compressed", url,
    ]
    subprocess.run(cmd, check=True)
    if dest.stat().st_size < 100_000:
        raise RuntimeError(
            f"Downloaded file is suspiciously small ({dest.stat().st_size} bytes). "
            "FL DOE may have changed its URL or anti-bot rules."
        )
    return dest


def load_grades(xlsx_path: Path) -> pd.DataFrame:
    """Load the FL DOE grades XLSX into a flat DataFrame with normalized headers."""
    df = pd.read_excel(xlsx_path, sheet_name="School Grades 2024", engine="openpyxl", header=3)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def lookup(df: pd.DataFrame, needle: str, district: str | None) -> pd.Series | None:
    """Find the first row whose school name contains the needle (and optionally
    matches the district)."""
    rows = df
    if district:
        rows = rows[rows["District Name"] == district]
    matches = rows[rows["School Name"].astype(str).str.contains(needle, na=False, regex=False)]
    if matches.empty:
        return None
    return matches.iloc[0]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", default="24", help="Two-digit year (e.g. 24 for SchoolGrades24.xlsx)")
    p.add_argument("--force-download", action="store_true", help="Re-download even if cached")
    args = p.parse_args()

    xlsx = download_grades_file(args.year, force=args.force_download)
    df = load_grades(xlsx)

    print(f"\n{'Target':<36} {'Source name':<46} {'Dist':<11} {'Grade':<5} {'Pct':>5} {'Now':>3} {'Was':>3}")
    print("-" * 115)

    current_by_name = {s["name"]: s for s in mock_data.FL_SCHOOLS}
    drift = []

    for display, needle, district in LOOKUPS:
        row = lookup(df, needle, district)
        if row is None:
            print(f"{display:<36} {'NO MATCH':<46} {'-':<11} {'-':<5} {'-':>5} {'-':>3} {'-':>3}")
            continue
        grade = str(row["Grade 2024"]).strip()
        pct = row["Percent of Total Possible Points"]
        new_rating = FL_GRADE_TO_RATING.get(grade)
        old_rating = current_by_name.get(display, {}).get("rating")
        delta = "" if new_rating == old_rating else f" (was {old_rating})"
        print(
            f"{display:<36} {row['School Name']:<46} {row['District Name']:<11} "
            f"{grade:<5} {pct:>5.0f} {new_rating!s:>3} {old_rating!s:>3}{delta}"
        )
        if new_rating != old_rating:
            drift.append((display, old_rating, new_rating, grade, pct))

    if drift:
        print(f"\n{len(drift)} school(s) drifted. Update mock_data.FL_SCHOOLS by hand:")
        for d, old, new, g, pct in drift:
            print(f"  {d}: rating {old} -> {new}, pct {pct:.0f}, grade {g}")
    else:
        print("\nNo drift — all FL_SCHOOLS ratings match the latest FL DOE file.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
