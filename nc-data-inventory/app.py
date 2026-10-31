"""North Carolina Coastal Data Inventory — Streamlit dashboard.

Run locally:   streamlit run app.py
"""

from __future__ import annotations

import datetime as dt

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

import config
import loaders
from validation import align, metrics

st.set_page_config(page_title=config.APP_TITLE, page_icon="🌊", layout="wide")


# --------------------------------------------------------------------------- #
# Cached wrappers around the loaders (API calls are slow; cache them)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=24 * 3600, show_spinner="Loading station list…")
def cached_stations(key: str, group: str) -> pd.DataFrame:
    mod = (loaders.OBSERVED | loaders.MODEL)[key]
    df = mod.list_stations()
    df["key"] = key
    return df


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_data(key: str, station_id: str, start, end, product: str, **opts) -> pd.DataFrame:
    mod = (loaders.OBSERVED | loaders.MODEL)[key]
    return mod.get_data(station_id, start, end, product, **opts)


# --------------------------------------------------------------------------- #
# Map
# --------------------------------------------------------------------------- #
def make_map(stations: pd.DataFrame, basemap: str) -> folium.Map:
    tiles, attr = config.BASEMAPS[basemap]
    m = folium.Map(location=config.MAP_CENTER, zoom_start=config.MAP_ZOOM,
                   tiles=tiles, attr=attr, control_scale=True)
    lon0, lat0, lon1, lat1 = config.NC_BBOX
    folium.Rectangle([(lat0, lon0), (lat1, lon1)], color="#444", weight=1,
                     fill=False, dash_array="5,5", tooltip="Study region").add_to(m)

    for key, grp in stations.groupby("key"):
        mod = (loaders.OBSERVED | loaders.MODEL)[key]
        fg = folium.FeatureGroup(name=mod.SOURCE_NAME)
        for r in grp.itertuples():
            start = r.start.strftime("%Y-%m-%d") if pd.notna(r.start) else "?"
            end = r.end.strftime("%Y-%m-%d") if pd.notna(r.end) else "present"
            folium.CircleMarker(
                location=(r.lat, r.lon), radius=6, weight=1,
                color="black", fill=True, fill_opacity=0.9 if r.status == "active" else 0.4,
                fill_color=loaders.COLORS.get(key, "#333"),
                # tooltip text is parsed back on click: "key|station_id|name"
                tooltip=f"{key}|{r.station_id}|{r.name}",
                popup=folium.Popup(f"<b>{r.name}</b><br>{mod.SOURCE_NAME} {r.station_id}"
                                   f"<br>{start} → {end}", max_width=250),
            ).add_to(fg)
        fg.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def clicked_station(map_state: dict | None):
    tip = (map_state or {}).get("last_object_clicked_tooltip")
    if tip and tip.count("|") >= 2:
        key, sid, _ = tip.split("|", 2)
        return key, sid
    return None


# --------------------------------------------------------------------------- #
# A data tab (Observed or Model): sources -> map -> inventory -> time series
# --------------------------------------------------------------------------- #
def data_tab(group_name: str, registry: dict, basemap: str):
    if not registry:
        st.info(f"No {group_name.lower()} loaders added yet.")
        return

    labels = {k: m.SOURCE_NAME for k, m in registry.items()}
    chosen = st.multiselect("Data sources", list(registry), default=list(registry),
                            format_func=labels.get, key=f"src_{group_name}")
    if not chosen:
        return

    stations = pd.concat([cached_stations(k, group_name) for k in chosen], ignore_index=True)

    col_map, col_inv = st.columns([3, 2])
    with col_map:
        state = st_folium(make_map(stations, basemap), height=560, use_container_width=True,
                          key=f"map_{group_name}",
                          returned_objects=["last_object_clicked_tooltip"])
    with col_inv:
        st.markdown(f"**Inventory — {len(stations)} stations**")
        show = stations.assign(
            source=stations["key"].map(labels),
            start=stations["start"].dt.strftime("%Y-%m-%d"),
            end=stations["end"].dt.strftime("%Y-%m-%d").fillna("present"),
        )[["source", "station_id", "name", "start", "end", "status"]]
        st.dataframe(show, height=520, hide_index=True, width="stretch")

    # ---- station selection (map click or dropdown) ----
    st.divider()
    stations["label"] = stations["key"].map(labels) + " · " + stations["station_id"] + " · " + stations["name"]
    hit = clicked_station(state)
    default_idx = 0
    if hit:
        match = stations.index[(stations["key"] == hit[0]) & (stations["station_id"] == hit[1])]
        if len(match):
            default_idx = int(match[0])
    row = stations.loc[st.selectbox("Station (or click one on the map)", stations.index,
                                    index=default_idx, format_func=stations["label"].get,
                                    key=f"stn_{group_name}")]
    mod = registry[row["key"]]

    c1, c2, c3, c4 = st.columns(4)
    product = c1.selectbox("Product", list(mod.PRODUCTS),
                           format_func=lambda p: mod.PRODUCTS[p]["label"], key=f"prod_{group_name}")
    opts = {name: c2.selectbox(name.capitalize(), choices, key=f"opt_{name}_{group_name}")
            for name, choices in getattr(mod, "OPTIONS", {}).items()}

    rec_start = row["start"].date() if pd.notna(row["start"]) else dt.date(1900, 1, 1)
    rec_end = row["end"].date() if pd.notna(row["end"]) else dt.date.today()
    default_start = max(rec_start, rec_end - dt.timedelta(days=config.DEFAULT_WINDOW_DAYS))
    start = c3.date_input("Start", default_start, min_value=rec_start, max_value=rec_end,
                          key=f"s_{group_name}")
    end = c4.date_input("End", rec_end, min_value=rec_start, max_value=rec_end,
                        key=f"e_{group_name}")
    st.caption(f"Record available: {rec_start} → {rec_end}. "
               "Long periods are downloaded in chunks and may take a few minutes.")

    if st.button("Load data", type="primary", key=f"go_{group_name}"):
        with st.spinner("Downloading…"):
            df = cached_data(row["key"], row["station_id"], pd.Timestamp(start),
                             pd.Timestamp(end), product, **opts)
        st.session_state[f"df_{group_name}"] = (row["label"], df)

    if f"df_{group_name}" in st.session_state:
        label, df = st.session_state[f"df_{group_name}"]
        if df.empty:
            st.warning("No data returned for this request (try another period, product or datum).")
        else:
            fig = px.line(df.reset_index(), x="time", y=list(df.columns), title=label)
            fig.update_layout(height=420, legend_title=None, xaxis_title="Time (UTC)")
            st.plotly_chart(fig, width="stretch")
            st.download_button("Download CSV", df.to_csv().encode(),
                               file_name=f"{label.replace(' · ', '_')}.csv", mime="text/csv",
                               key=f"dl_{group_name}")


# --------------------------------------------------------------------------- #
# Validation tab
# --------------------------------------------------------------------------- #
def validation_tab():
    if not loaders.MODEL:
        st.info("Validation becomes available once at least one model/hindcast loader is added "
                "(Steps 4–8). The comparison engine (`validation.py`) is already in place: it "
                "resamples observed and model series to a common step and reports Bias, RMSE, "
                "MAE, R, Scatter Index and Willmott's d.")
        return
    st.write("Pick an observed station and a model source; the model is sampled at the "
             "nearest grid point / output point to the observation.")
    # Full UI is built in Step 9 once model loaders exist.
    _ = align, metrics


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
st.title(config.APP_TITLE)
with st.sidebar:
    st.header("Settings")
    basemap = st.radio("Basemap", list(config.BASEMAPS))
    st.caption("Region: " + ", ".join(f"{v}" for v in config.NC_BBOX) + " (lon/lat bbox)")
    if st.button("Clear cached data"):
        st.cache_data.clear()

tab_obs, tab_mod, tab_val = st.tabs(["📡 Observed data", "🖥️ Model / hindcast data", "✅ Validation"])
with tab_obs:
    data_tab("Observed", loaders.OBSERVED, basemap)
with tab_mod:
    data_tab("Model", loaders.MODEL, basemap)
with tab_val:
    validation_tab()
