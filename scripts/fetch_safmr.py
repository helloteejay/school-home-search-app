"""Refresh the vendored HUD Small Area FMR table (FL ZIPs only).

Downloads HUD's FY2026 SAFMR workbook (~4 MB, all 51k US ZIPs), trims to
Florida FMR areas, and writes ``data/safmr_fl_2026.csv`` for
``rent_proxy.py``.

Usage:
    python scripts/fetch_safmr.py [--force]

Source: https://www.huduser.gov/portal/datasets/fmr.html ("Small Area FMRs")
Note: huduser.gov serves an empty body to default curl/requests agents —
the browser User-Agent below is required, not cosmetic.

When FY2027 SAFMRs publish (typically late summer), update URL + OUT_PATH
year and the RENT_SOURCE tag in rent_proxy.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

URL = "https://www.huduser.gov/portal/datasets/fmr/fmr2026/fy2026_safmrs.xlsx"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "safmr_fl_2026.csv"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Re-fetch even if the CSV exists")
    args = p.parse_args()

    if OUT_PATH.exists() and not args.force:
        print(f"cached at {OUT_PATH} (use --force to refresh)")
        return 0

    print(f"GET {URL}")
    resp = requests.get(URL, headers={"User-Agent": UA}, timeout=60)
    resp.raise_for_status()
    if not resp.content:
        raise RuntimeError("huduser.gov returned an empty body — UA blocked?")

    import io

    df = pd.read_excel(io.BytesIO(resp.content))
    df.columns = [c.replace("\n", " ").strip() for c in df.columns]
    fl = df[df["HUD Fair Market Rent Area Name"].str.contains(", FL", na=False)].copy()
    out = pd.DataFrame(
        {
            "zip": fl["ZIP Code"].astype(str).str.zfill(5),
            "area_name": fl["HUD Fair Market Rent Area Name"],
            "rent_0br": fl["SAFMR 0BR"],
            "rent_1br": fl["SAFMR 1BR"],
            "rent_2br": fl["SAFMR 2BR"],
            "rent_3br": fl["SAFMR 3BR"],
            "rent_4br": fl["SAFMR 4BR"],
        }
    ).drop_duplicates(subset="zip").sort_values("zip")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH} ({len(out)} FL ZIPs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
