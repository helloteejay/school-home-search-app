"""Data provider layer — abstract interfaces + concrete implementations.

The app code talks only to the abstract interfaces below. Two concrete
implementations are wired in:

  * ``MockSchoolProvider`` / ``MockListingsProvider`` — pull from ``mock_data``
    for fully offline development.
  * ``GreatSchoolsProvider`` / ``RealtyMoleProvider`` — HTTP skeletons that
    show how to talk to the real APIs once you have keys. They are not used
    by default; flip ``USE_LIVE_DATA`` (or pass a custom provider) to enable.

Both pairs return the same column schema so the rest of the app does not
need to branch on which is active.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Iterable, Optional

import geopandas as gpd
import pandas as pd
import requests

import mock_data

logger = logging.getLogger(__name__)

# Flip to True (or set env var) once you have wired up real API credentials.
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

        ``school_id, school_name, level, rating, zip_code, admission_type, geometry``

        ``admission_type`` is ``"boundary"`` (attendance-zone enrollment) or
        ``"magnet"`` (application/lottery). Live providers without an explicit
        magnet flag should default to ``"boundary"``.

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


class RealtyMoleProvider(ListingsDataProvider):
    """Skeleton for the Realty Mole Property API (RapidAPI).

    The free tier returns active sale listings keyed by ZIP or bounding box.
    Fill in ``RAPIDAPI_KEY`` and adjust the response mapping to your plan.
    """

    BASE_URL = "https://realty-mole-property-api.p.rapidapi.com"
    SALE_LISTINGS_PATH = "/saleListings"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.api_key = api_key or os.environ.get("RAPIDAPI_KEY")
        self.timeout = timeout

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "RAPIDAPI_KEY is not set. Either export it or use the "
                "MockListingsProvider instead."
            )
        return {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "realty-mole-property-api.p.rapidapi.com",
        }

    def _fetch_zip(self, zip_code: str, max_price: Optional[float]) -> list[dict]:
        params = {"zipCode": zip_code, "limit": 200}
        if max_price is not None:
            params["maxPrice"] = int(max_price)
        try:
            resp = requests.get(
                f"{self.BASE_URL}{self.SALE_LISTINGS_PATH}",
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Realty Mole fetch failed for %s: %s", zip_code, exc)
            return []
        payload = resp.json()
        # The API sometimes returns a bare list, sometimes a dict — handle both.
        return payload if isinstance(payload, list) else payload.get("listings", [])

    def get_listings(
        self,
        zip_codes: Optional[Iterable[str]] = None,
        max_price: Optional[float] = None,
        min_bedrooms: int = 0,
        min_bathrooms: int = 0,
    ) -> pd.DataFrame:
        if not zip_codes:
            raise ValueError("RealtyMoleProvider requires at least one ZIP code.")

        rows = []
        for zip_code in zip_codes:
            for raw in self._fetch_zip(str(zip_code).strip(), max_price):
                lat = raw.get("latitude")
                lon = raw.get("longitude")
                if lat is None or lon is None:
                    continue
                beds = int(raw.get("bedrooms") or 0)
                baths = int(raw.get("bathrooms") or 0)
                if beds < int(min_bedrooms) or baths < int(min_bathrooms):
                    continue
                rows.append({
                    "listing_id": raw.get("id") or raw.get("formattedAddress"),
                    "address": raw.get("formattedAddress", ""),
                    "city": raw.get("city", ""),
                    "state": raw.get("state", ""),
                    "zip_code": str(raw.get("zipCode", "")),
                    "price": float(raw.get("price") or 0),
                    "bedrooms": beds,
                    "bathrooms": baths,
                    "sqft": int(raw.get("squareFootage") or 0),
                    "year_built": int(raw.get("yearBuilt") or 0),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "listing_url": raw.get("listingUrl", ""),
                })
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Factory — single entry point used by app.py
# ---------------------------------------------------------------------------

def get_providers(
    use_live: Optional[bool] = None,
) -> tuple[SchoolDataProvider, ListingsDataProvider]:
    """Return the (school, listings) provider pair to use.

    Defaults to mocks. Set ``USE_LIVE_DATA=true`` in the environment, or pass
    ``use_live=True`` explicitly, to switch to the live HTTP skeletons.
    """
    live = USE_LIVE_DATA if use_live is None else use_live
    if live:
        return GreatSchoolsProvider(), RealtyMoleProvider()
    return MockSchoolProvider(), MockListingsProvider()
