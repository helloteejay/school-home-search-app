"""Data provider layer — abstract interfaces + concrete implementations.

The app code talks only to the abstract interfaces below. Concrete
implementations:

  * ``MockSchoolProvider`` — reads from ``mock_data``, which now serves
    real FL DOE 2023-24 ratings + real Broward/Miami-Dade attendance
    polygons. The "mock" name is a misnomer at this point; it's our
    canonical school data layer.
  * ``MockListingsProvider`` — synthetic FL listings (Broward + Miami-Dade)
    for offline development.
  * ``RentCastProvider`` — live RentCast (formerly Realty Mole) API for
    actual for-sale listings. Requires ``RENTCAST_API_KEY``. Enabled by
    setting ``USE_LIVE_DATA=true`` in the environment.

Live mode only swaps the **listings** provider — the school data stays on
the mock provider because we already have real ratings + real boundaries
baked in. Once a live boundary feed materializes for another state, swap
in a real ``SchoolDataProvider`` for that geography.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Optional

import geopandas as gpd
import pandas as pd
import requests

import mock_data

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Read KEY=VALUE pairs from .env into os.environ. No-op if no file.

    Done manually so we don't add python-dotenv as a dep just for one file.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # Don't overwrite a value already set in the actual environment.
        os.environ.setdefault(key, value)


def _load_streamlit_secrets() -> None:
    """If running under Streamlit Cloud, pull secrets into os.environ.

    Streamlit Cloud exposes deploy-time secrets via ``st.secrets`` (a TOML
    file managed via the dashboard). We surface them as env vars so the
    rest of the module — which reads ``os.environ.get(...)`` — works
    identically whether the key came from .env locally or st.secrets on
    the cloud.
    """
    try:
        import streamlit as st  # type: ignore
        # st.secrets is a Mapping; iterating gives keys.
        for key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
    except Exception:
        # Not running under streamlit, no secrets configured, etc. — fine.
        pass


_load_dotenv()
_load_streamlit_secrets()

# Flip to True (or set env var) to use the live RentCast listings API.
USE_LIVE_DATA = os.environ.get("USE_LIVE_DATA", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------

class SchoolDataProvider(ABC):
    """Returns school metadata + attendance-boundary polygons."""

    @abstractmethod
    def get_schools(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        min_rating: int = 1,
    ) -> gpd.GeoDataFrame:
        """Return a GeoDataFrame with columns:

        ``school_id, school_name, level, rating, zip_code, admission_type,
        geometry, boundary_source``

        ``admission_type`` is ``"boundary"`` (attendance-zone enrollment) or
        ``"magnet"`` (application/lottery). Live providers without an explicit
        magnet flag should default to ``"boundary"``.

        ``boundary_source`` is ``"district"`` if the polygon came from a
        district GIS feed (authoritative) or ``"synthetic"`` if it's an
        approximation around the school centroid (fallback only).

        ``geometry`` must be a Shapely polygon in EPSG:4326 (lat/lon).
        """


class ListingsDataProvider(ABC):
    """Returns active for-sale listings with lat/lon coordinates."""

    @abstractmethod
    def get_listings(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        max_price: Optional[float] = None,
        min_bedrooms: int = 0,
        min_bathrooms: int = 0,
    ) -> pd.DataFrame:
        """Return a DataFrame with columns:

        ``listing_id, address, city, state, zip_code, price, bedrooms,
        bathrooms, sqft, year_built, latitude, longitude, listing_url``
        """


# ---------------------------------------------------------------------------
# Mock implementations (default, no API keys required)
# ---------------------------------------------------------------------------

class MockSchoolProvider(SchoolDataProvider):
    """Reads from ``mock_data.generate_schools`` and applies basic filters."""

    def __init__(self, cfg: Optional[mock_data.MockConfig] = None) -> None:
        self._cfg = cfg or mock_data.MockConfig()
        # Cache the generated frame — regenerating it on every UI rerender
        # would be wasteful and would also reshuffle the random ratings.
        self._cache: Optional[gpd.GeoDataFrame] = None

    def _load(self) -> gpd.GeoDataFrame:
        if self._cache is None:
            self._cache = mock_data.generate_schools(self._cfg)
        return self._cache

    def get_schools(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        min_rating: int = 1,
    ) -> gpd.GeoDataFrame:
        gdf = self._load().copy()
        if zip_codes:
            zips = {str(z).strip() for z in zip_codes if str(z).strip()}
            if zips:
                gdf = gdf[gdf["zip_code"].isin(zips)]
        gdf = gdf[gdf["rating"] >= int(min_rating)]
        return gdf.reset_index(drop=True)


class MockListingsProvider(ListingsDataProvider):
    """Reads from ``mock_data.generate_listings`` and applies basic filters."""

    def __init__(self, cfg: Optional[mock_data.MockConfig] = None) -> None:
        self._cfg = cfg or mock_data.MockConfig()
        self._cache: Optional[pd.DataFrame] = None

    def _load(self) -> pd.DataFrame:
        if self._cache is None:
            schools = mock_data.generate_schools(self._cfg)
            self._cache = mock_data.generate_listings(schools, self._cfg)
        return self._cache

    def get_listings(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        max_price: Optional[float] = None,
        min_bedrooms: int = 0,
        min_bathrooms: int = 0,
    ) -> pd.DataFrame:
        df = self._load().copy()
        if zip_codes:
            zips = {str(z).strip() for z in zip_codes if str(z).strip()}
            if zips:
                df = df[df["zip_code"].isin(zips)]
        if max_price is not None:
            df = df[df["price"] <= float(max_price)]
        df = df[df["bedrooms"] >= int(min_bedrooms)]
        df = df[df["bathrooms"] >= int(min_bathrooms)]
        return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Live API skeletons — implement when credentials are available
# ---------------------------------------------------------------------------

class GreatSchoolsProvider(SchoolDataProvider):
    """Skeleton for GreatSchools (or a state GIS education dataset).

    GreatSchools' public API does NOT return attendance-boundary polygons —
    those typically come from a separate source (state DOE, district GIS
    portal, or a vendor like SchoolDigger). This class shows the shape of
    the integration; ``_fetch_boundaries`` is where you would plug in the
    boundary feed.
    """

    SCHOOLS_ENDPOINT = "https://gs-api.greatschools.org/schools"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or os.environ.get("GREATSCHOOLS_API_KEY")
        self.timeout = timeout

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "GREATSCHOOLS_API_KEY is not set. Either export it or use the "
                "MockSchoolProvider instead."
            )
        return {"X-API-Key": self.api_key, "Accept": "application/json"}

    def _fetch_schools(self, zip_code: str) -> list[dict]:
        """Query the GreatSchools metadata endpoint for one ZIP."""
        params = {"zip": zip_code, "limit": 50}
        try:
            resp = requests.get(
                self.SCHOOLS_ENDPOINT,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("GreatSchools fetch failed for %s: %s", zip_code, exc)
            return []
        return resp.json().get("schools", [])

    def _fetch_boundaries(self, school_id: str) -> Optional[dict]:
        """Override with your boundary source (state GIS, district feed, etc.)."""
        # Intentionally not implemented — every region has a different feed.
        return None

    def get_schools(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        min_rating: int = 1,
    ) -> gpd.GeoDataFrame:
        if not zip_codes:
            raise ValueError("GreatSchoolsProvider requires at least one ZIP code.")
        from shapely.geometry import shape

        rows = []
        for zip_code in zip_codes:
            for school in self._fetch_schools(str(zip_code).strip()):
                rating = school.get("rating")
                if rating is None or int(rating) < int(min_rating):
                    continue
                boundary = self._fetch_boundaries(school["universal_id"])
                if not boundary:
                    continue
                rows.append({
                    "school_id": school["universal_id"],
                    "school_name": school["name"],
                    "level": school.get("level", "Unknown"),
                    "rating": int(rating),
                    "zip_code": str(zip_code).strip(),
                    # GreatSchools metadata doesn't natively flag magnet status
                    # across all plans — assume boundary and override on the
                    # client side for known magnet/lab schools.
                    "admission_type": school.get("admission_type", "boundary"),
                    "geometry": shape(boundary),
                })
        return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


class RentCastProvider(ListingsDataProvider):
    """Live for-sale listings from RentCast (formerly Realty Mole).

    https://api.rentcast.io/v1/listings/sale

    Auth: ``X-Api-Key`` header. Free tier is 50 calls/month; each call
    returns up to 500 listings.

    Two query modes:
      - ZIP mode (one call per ZIP, ~100-500 listings each)
      - Radius mode (one call covers a lat/lon disk, up to 500 listings)

    Radius mode is preferred — far cheaper on quota when you want broad
    coverage. We paginate via ``offset`` if a single radius call hits the
    500-listing cap.

    RentCast doesn't support ``maxPrice`` server-side; we fetch broadly
    and filter client-side. Same for "min beds/baths" semantics.
    """

    BASE_URL = "https://api.rentcast.io/v1"
    SALE_LISTINGS_PATH = "/listings/sale"
    PAGE_LIMIT = 500  # RentCast hard cap per call
    MAX_PAGES = 5     # safety guard so a wide query can't burn all quota

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0) -> None:
        self.api_key = api_key or os.environ.get("RENTCAST_API_KEY")
        self.timeout = timeout

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "RENTCAST_API_KEY is not set. Either export it, drop it in "
                "school-home-finder/.env, or use the MockListingsProvider."
            )
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    def _paged_fetch(self, params: dict) -> list[dict]:
        """Pull listings page by page until we run out or hit MAX_PAGES."""
        items: list[dict] = []
        params = dict(params, limit=self.PAGE_LIMIT, status="Active")
        for page in range(self.MAX_PAGES):
            params["offset"] = page * self.PAGE_LIMIT
            try:
                resp = requests.get(
                    f"{self.BASE_URL}{self.SALE_LISTINGS_PATH}",
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("RentCast fetch failed (page %s): %s", page, exc)
                break
            payload = resp.json()
            batch = payload if isinstance(payload, list) else payload.get("listings", [])
            if not batch:
                break
            items.extend(batch)
            if len(batch) < self.PAGE_LIMIT:
                break  # less than a full page means we're done
        return items

    def _fetch_zip(self, zip_code: str) -> list[dict]:
        return self._paged_fetch({"zipCode": zip_code})

    def fetch_radius(self, lat: float, lon: float, radius_miles: float) -> list[dict]:
        """Public hook used by app.py to do a single broad radius query."""
        return self._paged_fetch(
            {"latitude": lat, "longitude": lon, "radius": radius_miles}
        )

    @staticmethod
    def _redfin_url(item: dict) -> str:
        """Build a Redfin search URL from the listing's address as a fallback
        link when RentCast doesn't return one."""
        addr = item.get("formattedAddress", "")
        if not addr:
            return ""
        return f"https://www.redfin.com/stingray/do/location-autocomplete?location={addr.replace(' ', '%20')}&v=2"

    @staticmethod
    def _normalize(raw: dict) -> Optional[dict]:
        """Map one raw RentCast item to our canonical listing schema.
        Returns None if the item lacks coordinates (can't be placed on the map)."""
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        if lat is None or lon is None:
            return None
        return {
            "listing_id": raw.get("id") or raw.get("formattedAddress"),
            "address": raw.get("formattedAddress") or raw.get("addressLine1") or "",
            "city": raw.get("city") or "",
            "state": raw.get("state") or "",
            "zip_code": str(raw.get("zipCode") or ""),
            "price": float(raw.get("price") or 0),
            "bedrooms": float(raw.get("bedrooms") or 0),
            "bathrooms": float(raw.get("bathrooms") or 0),
            "sqft": int(raw.get("squareFootage") or 0),
            "year_built": int(raw.get("yearBuilt") or 0),
            "latitude": float(lat),
            "longitude": float(lon),
            "listing_url": RentCastProvider._redfin_url(raw),
        }

    def get_listings(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        max_price: Optional[float] = None,
        min_bedrooms: int = 0,
        min_bathrooms: int = 0,
    ) -> pd.DataFrame:
        if not zip_codes:
            raise ValueError(
                "RentCastProvider.get_listings needs at least one ZIP. For broad "
                "coverage use get_listings_in_radius instead."
            )

        rows = []
        for zip_code in zip_codes:
            for raw in self._fetch_zip(str(zip_code).strip()):
                row = self._normalize(raw)
                if row is None:
                    continue
                if row["bedrooms"] < float(min_bedrooms) or row["bathrooms"] < float(min_bathrooms):
                    continue
                if max_price is not None and row["price"] > float(max_price):
                    continue
                rows.append(row)
        return pd.DataFrame(rows)

    def get_listings_in_radius(
        self,
        lat: float,
        lon: float,
        radius_miles: float,
    ) -> pd.DataFrame:
        """One broad lat/lon/radius query. Use this when you want coverage
        across many ZIPs without burning a call per ZIP. Filters happen
        client-side on the returned DataFrame.
        """
        rows = []
        for raw in self.fetch_radius(lat, lon, radius_miles):
            row = self._normalize(raw)
            if row is not None:
                rows.append(row)
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Factory — single entry point used by app.py
# ---------------------------------------------------------------------------

def get_providers(
    use_live: Optional[bool] = None,
) -> tuple[SchoolDataProvider, ListingsDataProvider]:
    """Return the (school, listings) provider pair to use.

    Schools always come from ``MockSchoolProvider`` — that's where FL DOE
    ratings and district GIS boundaries are baked in. ``USE_LIVE_DATA=true``
    only swaps listings to ``RentCastProvider``.
    """
    live = USE_LIVE_DATA if use_live is None else use_live
    if live:
        return MockSchoolProvider(), RentCastProvider()
    return MockSchoolProvider(), MockListingsProvider()
