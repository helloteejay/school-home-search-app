"""Zone-level rent proxy + gross-yield annotation for the investment view.

Source: HUD FY2026 Small Area Fair Market Rents (SAFMRs), vendored for all
FL ZIPs at ``data/safmr_fl_2026.csv``. Refresh with
``scripts/fetch_safmr.py``.

Why SAFMR and what it is NOT
----------------------------
SAFMRs are the only free, ZIP-level, *bedroom-resolved* rent figures with a
stable national methodology — which makes them the right tool for ranking
school zones against each other on rough gross yield without burning
RentCast quota (50 calls/month on the free tier).

They are NOT market asking rents:

* 40th-percentile gross rent (includes utilities) across ALL unit types —
  apartments and houses pooled. In luxury SFH ZIPs (Pinecrest, Weston) the
  proxy runs well BELOW market SFH rents; in voucher-heavy or
  payment-standard-inflated metros it can run ABOVE actual asks.
* Use the resulting ``gross_yield_pct`` to COMPARE zones, not to
  underwrite a specific house. Final numbers on a shortlisted property
  should come from a property-level estimate (e.g. RentCast /avm/rent —
  one quota call per finalist, not per listing).

Schema added by ``annotate_listings``:

  est_monthly_rent   int    — SAFMR for the listing's ZIP + bedroom count
                              (clamped to 0-4BR; 5+BR homes use the 4BR rent,
                              so big-house yields are conservative)
  gross_yield_pct    float  — est_monthly_rent * 12 / price * 100
  rent_source        str    — provenance tag, mirrors rating_source/
                              boundary_source discipline
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent
SAFMR_CSV = _REPO_ROOT / "data" / "safmr_fl_2026.csv"

RENT_SOURCE = "HUD FY2026 SAFMR (40th-pct gross rent, ZIP level)"


@lru_cache(maxsize=1)
def _load_safmr() -> Dict[Tuple[str, int], int]:
    """Load the vendored CSV into {(zip, bedrooms): monthly_rent}."""
    if not SAFMR_CSV.exists():
        return {}
    table: Dict[Tuple[str, int], int] = {}
    with SAFMR_CSV.open() as f:
        for row in csv.DictReader(f):
            z = row["zip"].strip()
            for br in range(5):
                try:
                    table[(z, br)] = int(float(row[f"rent_{br}br"]))
                except (KeyError, ValueError):
                    continue
    return table


def lookup_rent(zip_code: str, bedrooms: float) -> int | None:
    """SAFMR for a ZIP + bedroom count. Bedrooms clamp to the 0-4 range
    HUD publishes (a 6BR uses the 4BR rent — intentionally conservative)."""
    table = _load_safmr()
    if not table:
        return None
    br = max(0, min(4, int(bedrooms or 0)))
    return table.get((str(zip_code).strip().zfill(5), br))


def annotate_listings(listings: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``listings`` with rent-proxy investment columns.

    Rows whose ZIP isn't in the SAFMR table (or with price <= 0) get
    ``None`` — the UI renders those blank rather than pretending.
    """
    if listings.empty:
        out = listings.copy()
        out["est_monthly_rent"] = None
        out["gross_yield_pct"] = None
        out["rent_source"] = RENT_SOURCE
        return out

    out = listings.copy()

    def _rent(row) -> int | None:
        return lookup_rent(row.get("zip_code", ""), row.get("bedrooms", 0))

    out["est_monthly_rent"] = out.apply(_rent, axis=1)
    out["gross_yield_pct"] = [
        round(rent * 12 / price * 100, 2)
        if (rent is not None and price and price > 0)
        else None
        for rent, price in zip(out["est_monthly_rent"], out["price"])
    ]
    out["rent_source"] = RENT_SOURCE
    return out
