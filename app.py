"""School-quality home search — Streamlit entry point.

Workflow:
  1. Sidebar collects city/ZIPs + min school rating + price/beds/baths filters.
  2. ``data_provider`` returns school polygons + active listings (mock by
     default; live HTTP skeletons swap in via USE_LIVE_DATA=true).
  3. ``geo_engine`` runs the point-in-polygon filter and annotates each
     surviving listing with its assigned school.
  4. Folium renders the school zones (color-coded by rating) and home pins.
  5. AgGrid (with a Pandas fallback) shows the sortable result table.

Run: ``streamlit run app.py``
"""

from __future__ import annotations

import logging
from typing import List

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

import data_provider
import geo_engine

# Optional dependency — fall back to st.dataframe if the user hasn't installed it.
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

    HAS_AGGRID = True
except ImportError:  # pragma: no cover — runtime UI choice only
    HAS_AGGRID = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Streamlit page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="School-Quality Home Search",
    page_icon=":house:",
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def _providers():
    """Cache the provider pair across reruns so we don't reshuffle mock data."""
    return data_provider.get_providers()


@st.cache_data(show_spinner=False)
def _load_schools(zip_codes: tuple[str, ...], min_rating: int):
    school_provider, _ = _providers()
    try:
        return school_provider.get_schools(
            zip_codes=list(zip_codes) if zip_codes else None,
            min_rating=min_rating,
        )
    except Exception as exc:
        logger.exception("School provider failed")
        st.error(f"Could not load schools: {exc}")
        # Return an empty GeoDataFrame with the expected columns.
        import geopandas as gpd
        return gpd.GeoDataFrame(
            columns=["school_id", "school_name", "level", "rating", "zip_code", "geometry"],
            geometry="geometry",
            crs="EPSG:4326",
        )


@st.cache_data(show_spinner=False)
def _load_listings(
    zip_codes: tuple[str, ...],
    max_price: float,
    min_beds: int,
    min_baths: int,
):
    _, listings_provider = _providers()
    try:
        return listings_provider.get_listings(
            zip_codes=list(zip_codes) if zip_codes else None,
            max_price=max_price,
            min_bedrooms=min_beds,
            min_bathrooms=min_baths,
        )
    except Exception as exc:
        logger.exception("Listings provider failed")
        st.error(f"Could not load listings: {exc}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

def render_sidebar() -> dict:
    """Render sidebar controls and return their current values."""
    st.sidebar.header("Search filters")

    st.sidebar.markdown("**Location**")
    city = st.sidebar.text_input("City, State", value="Broward + Miami-Dade, FL")
    zip_raw = st.sidebar.text_input(
        "ZIP codes (comma-separated, optional)",
        value="",
        help=(
            "Leave blank to include every zone. Try 33326 (Weston), 33076 "
            "(Parkland), 33156 (Pinecrest), 33134 (Coral Gables)."
        ),
    )
    zip_codes: List[str] = [z.strip() for z in zip_raw.split(",") if z.strip()]

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Schools**")
    min_rating = st.sidebar.slider(
        "Minimum GreatSchools rating",
        min_value=1,
        max_value=10,
        value=8,
        help="Only homes inside attendance zones with this rating or higher will be shown.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Home**")
    max_price = st.sidebar.number_input(
        "Max price ($)",
        min_value=100_000,
        max_value=10_000_000,
        value=1_500_000,
        step=25_000,
    )
    min_beds = st.sidebar.slider("Min bedrooms", 1, 6, 3)
    min_baths = st.sidebar.slider("Min bathrooms", 1, 5, 2)

    return {
        "city": city,
        "zip_codes": zip_codes,
        "min_rating": int(min_rating),
        "max_price": float(max_price),
        "min_beds": int(min_beds),
        "min_baths": int(min_baths),
    }


# ---------------------------------------------------------------------------
# Map rendering
# ---------------------------------------------------------------------------

def build_map(schools, qualifying_listings: pd.DataFrame) -> folium.Map:
    """Build the Folium map: shaded school polygons + clustered home pins."""
    (south, west), (north, east) = geo_engine.schools_bbox(schools, qualifying_listings)
    center = [(south + north) / 2, (west + east) / 2]
    zoom = geo_engine.zoom_for_bbox(south, west, north, east)

    fmap = folium.Map(location=center, zoom_start=zoom, tiles="cartodbpositron")

    # School polygons, color-coded by rating.
    for _, row in schools.iterrows():
        color = geo_engine.rating_to_color(int(row["rating"]))
        folium.GeoJson(
            row["geometry"].__geo_interface__,
            name=row["school_name"],
            style_function=lambda _f, c=color: {
                "fillColor": c,
                "color": c,
                "weight": 1.5,
                "fillOpacity": 0.25,
            },
            tooltip=folium.Tooltip(
                f"<b>{row['school_name']}</b><br>"
                f"Rating: {row['rating']}/10 ({row['level']})<br>"
                f"ZIP: {row['zip_code']}"
            ),
        ).add_to(fmap)

    # Home pins — clustered to keep the map readable when zoomed out.
    if not qualifying_listings.empty:
        cluster = MarkerCluster(name="Qualifying homes").add_to(fmap)
        for _, row in qualifying_listings.iterrows():
            popup_html = (
                f"<b>${int(row['price']):,}</b><br>"
                f"{row['address']}<br>"
                f"{int(row['bedrooms'])} bd / {row['bathrooms']} ba · "
                f"{int(row['sqft']):,} sqft<br>"
                f"<b>School:</b> {row['assigned_school']} "
                f"({int(row['school_rating'])}/10)<br>"
                f'<a href="{row["listing_url"]}" target="_blank">View listing</a>'
            )
            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=folium.Popup(popup_html, max_width=320),
                tooltip=f"${int(row['price']):,} · {int(row['bedrooms'])}bd",
                icon=folium.Icon(color="blue", icon="home", prefix="fa"),
            ).add_to(cluster)

    # NB: ``fmap.fit_bounds`` was previously called here but the streamlit-
    # folium iframe is sized AFTER Leaflet initializes — fit_bounds picks the
    # wrong zoom against the pre-resize container. zoom_for_bbox above gives
    # the right initial zoom; the user can still drag/zoom to refine.
    folium.LayerControl(collapsed=True).add_to(fmap)
    return fmap


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------

DISPLAY_COLUMNS = [
    "address", "price", "bedrooms", "bathrooms", "sqft", "year_built",
    "assigned_school", "school_rating", "school_level", "zip_code", "listing_url",
]


def render_table(df: pd.DataFrame) -> None:
    """Render the result table with AgGrid if available, else st.dataframe."""
    if df.empty:
        st.info("No homes match your filters. Try lowering the school rating or raising the price.")
        return

    view = df[DISPLAY_COLUMNS].copy()

    if HAS_AGGRID:
        # JsCode wrappers are required for streamlit-aggrid >=1.0 — a bare
        # string is treated as a column-field reference, not a JS function.
        price_formatter = JsCode(
            "function(params) { "
            "return params.value != null ? '$' + Number(params.value).toLocaleString() : ''; "
            "}"
        )
        # AgGrid >=31 (under streamlit-aggrid 1.x's React wrapper) escapes
        # string returns and crashes on raw DOM elements returned from a
        # plain function. The class-style renderer with init()/getGui()
        # bypasses React entirely — AgGrid mounts the element directly.
        link_renderer = JsCode("""
            class UrlCellRenderer {
              init(params) {
                this.eGui = document.createElement('a');
                this.eGui.textContent = 'View';
                this.eGui.setAttribute('href', params.value || '#');
                this.eGui.setAttribute('target', '_blank');
                this.eGui.setAttribute('rel', 'noopener');
              }
              getGui() { return this.eGui; }
              refresh() { return false; }
            }
        """)

        gb = GridOptionsBuilder.from_dataframe(view)
        gb.configure_default_column(filter=True, sortable=True, resizable=True, flex=1)
        # Flex weights let columns share whatever width the iframe ends up at —
        # min widths alone caused the rightmost columns (ZIP, Listing) to clip.
        gb.configure_column("address", header_name="Address", flex=3, minWidth=160)
        gb.configure_column(
            "price", header_name="Price", type=["numericColumn"],
            valueFormatter=price_formatter, flex=1.4, minWidth=100,
        )
        gb.configure_column("bedrooms", header_name="Beds", flex=0.6, minWidth=60)
        gb.configure_column("bathrooms", header_name="Baths", flex=0.6, minWidth=60)
        gb.configure_column("sqft", header_name="Sqft", type=["numericColumn"], flex=0.8, minWidth=70)
        gb.configure_column("year_built", header_name="Year", flex=0.7, minWidth=60)
        gb.configure_column("assigned_school", header_name="School", flex=2.4, minWidth=140)
        gb.configure_column("school_rating", header_name="Rating", flex=0.8, minWidth=70)
        gb.configure_column("school_level", header_name="Level", flex=1, minWidth=80)
        gb.configure_column("zip_code", header_name="ZIP", flex=0.7, minWidth=60)
        gb.configure_column(
            "listing_url", header_name="Listing",
            cellRenderer=link_renderer, flex=0.7, minWidth=70,
        )
        AgGrid(
            view,
            gridOptions=gb.build(),
            allow_unsafe_jscode=True,
            theme="streamlit",
            height=420,
        )
    else:
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "price": st.column_config.NumberColumn("Price", format="$%d"),
                "listing_url": st.column_config.LinkColumn("Listing"),
            },
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.title("Find homes inside top-rated school zones")
    st.caption(
        "Active listings cross-referenced with school attendance boundaries. "
        "MVP covers Broward + Miami-Dade (Weston, Parkland, Cooper City, "
        "Pinecrest, Coral Gables, Aventura, Doral, Key Biscayne). Mock data "
        "by default — set `USE_LIVE_DATA=true` to hit live APIs."
    )

    filters = render_sidebar()

    # Cache keys are hashable, so convert lists to tuples before passing in.
    schools = _load_schools(tuple(filters["zip_codes"]), filters["min_rating"])
    listings = _load_listings(
        tuple(filters["zip_codes"]),
        filters["max_price"],
        filters["min_beds"],
        filters["min_baths"],
    )

    qualifying = geo_engine.filter_listings_in_top_schools(
        listings, schools, min_rating=filters["min_rating"]
    )

    # Top metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schools (>= rating)", len(schools))
    c2.metric("Listings considered", len(listings))
    c3.metric("Homes in top zones", len(qualifying))
    if not qualifying.empty:
        c4.metric("Median price", f"${int(qualifying['price'].median()):,}")
    else:
        c4.metric("Median price", "—")

    st.subheader("Map")
    fmap = build_map(schools, qualifying)
    st_folium(fmap, width=None, height=560, returned_objects=[])

    st.subheader("Qualifying homes")
    render_table(qualifying)

    with st.expander("Debug / raw data"):
        st.write("**Schools matching filters**")
        st.dataframe(
            pd.DataFrame(schools.drop(columns="geometry")) if not schools.empty else pd.DataFrame(),
            use_container_width=True,
            hide_index=True,
        )
        st.write("**All listings (pre-geo-filter)**")
        st.dataframe(listings, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
