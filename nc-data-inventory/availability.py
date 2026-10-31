"""Availability tab: overall temporal coverage of observations and models.

Recreates the "Observations and model hindcasts through time" chart of the
NC NBS inventory page, but from the live station inventories:
  * each observed source is a heat-strip: colour intensity = share of its
    stations active in that year (from each station's start/end dates);
  * each model/reanalysis is a bar over its COVERAGE period; an optional
    COVERAGE["core"] (e.g. GTSM original 1979-2018) is drawn dark on top of
    a light "extended version" bar;
  * a shaded band marks the common overlap period.
Station records are taken as continuous between first and last date; gaps
inside a record are not known from the inventories.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import loaders

# colours from the inventory page (light theme)
OBS_COLORS = {"noaa_coops": "#1d5f8a", "ndbc": "#6a4fb3", "usgs_nwis": "#2f7d3c"}
OBS_FALLBACK = "#7c8a92"
MODEL, MODEL_EXT, OVERLAP = "#d9622b", "#f2b89b", "rgba(47,138,87,0.13)"
PANEL = (255, 255, 255)


def _mix(hex_color: str, pct: float) -> str:
    """CSS color-mix(in srgb, color pct%, white)."""
    h = hex_color.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)])
    rgb = (c * pct + np.array(PANEL) * (1 - pct)).round().astype(int)
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def _year(v, default=None) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or (v is pd.NaT):
        return default
    t = pd.Timestamp(v)
    if pd.isna(t):
        return default
    return t.year + (t.dayofyear - 1) / 365.25


def active_counts(st_df: pd.DataFrame, now: int) -> pd.Series:
    """Number of stations with a record covering each calendar year."""
    s = st_df["start"].map(lambda v: _year(v))
    e = [(_year(v, now + 1) if stat != "historical" else _year(v)) for v, stat in zip(st_df["end"], st_df["status"])]
    rec = pd.DataFrame({"s": s, "e": e}).dropna()
    if rec.empty:
        return pd.Series(dtype=int)
    years = np.arange(int(np.floor(rec["s"].min())), now + 1)
    counts = [int(((rec["s"] < y + 1) & (rec["e"] >= y)).sum()) for y in years]
    return pd.Series(counts, index=years)


def model_ranges(mod, now: int):
    cov = mod.COVERAGE
    today = dt.date.today()
    full = (_year(cov["start"]), now + (today.timetuple().tm_yday - 1) / 365.25)
    if cov.get("end"):
        full = (full[0], _year(cov["end"]) + 1 / 365.25)
    core = cov.get("core")
    core = (_year(core[0]), _year(core[1]) + 1 / 365.25) if core else None
    return full, core


def coverage_figure(obs_rows, model_rows, overlap, x0, x1, now) -> go.Figure:
    fig = go.Figure()
    labels = []
    # ---------------- observed heat strips ----------------
    for row in obs_rows:
        c, n = row["counts"], row["n"]
        c = c[c > 0]
        if c.empty:
            continue
        pct = 0.18 + 0.82 * c.to_numpy() / max(n, 1)
        frac = dt.date.today().timetuple().tm_yday / 365.25
        widths = [frac if y == now else 1.0 for y in c.index]
        fig.add_trace(go.Bar(
            orientation="h", y=[row["label"]] * len(c), x=widths, base=c.index.to_numpy(),
            marker={"color": [_mix(row["color"], p) for p in pct], "line": {"width": 0}},
            width=0.42, offset=-0.21, showlegend=False,
            customdata=np.c_[c.index.to_numpy(), c.to_numpy()],
            hovertemplate=f"<b>{row['source']}</b><br>%{{customdata[0]}}: %{{customdata[1]}} of {n} stations<extra></extra>",
        ))
        labels.append(row["label"])
        fig.add_annotation(x=c.index.min(), y=row["label"], text=row["ann"], showarrow=False,
                           xanchor="left", yshift=17, font={"size": 11, "color": "#5b6b75"})
    # ---------------- models ----------------
    for row in model_rows:
        (s, e), core = row["full"], row["core"]
        fig.add_trace(go.Bar(
            orientation="h", y=[row["label"]], x=[e - s], base=[s], width=0.42, offset=-0.21,
            marker={"color": MODEL_EXT if core else MODEL, "line": {"width": 0}}, showlegend=False,
            hovertemplate=f"<b>{row['label']}</b><br>{row['txt']}<extra></extra>"))
        if core:
            fig.add_trace(go.Bar(
                orientation="h", y=[row["label"]], x=[core[1] - core[0]], base=[core[0]], width=0.42,
                offset=-0.21, marker={"color": MODEL, "line": {"width": 0}}, showlegend=False,
                hovertemplate=f"<b>{row['label']}</b><br>original release<extra></extra>"))
        labels.append(row["label"])
        fig.add_annotation(x=s, y=row["label"], text=row["txt"], showarrow=False, xanchor="left",
                           yshift=17, font={"size": 11, "color": "#5b6b75"})

    # ---------------- overlap band, now line, section headers ----------------
    if overlap:
        fig.add_vrect(x0=overlap[0], x1=overlap[1] + 1, fillcolor=OVERLAP, line_width=1,
                      line_color="rgba(47,138,87,0.5)", line_dash="dot", layer="below",
                      annotation_text=f"overlap {overlap[0]}–{overlap[1]}", annotation_position="bottom",
                      annotation_font={"size": 10, "color": "#2f8a57"})
    now_x = now + (dt.date.today().timetuple().tm_yday - 1) / 365.25
    fig.add_vline(x=now_x, line_dash="dash", line_color="#5b6b75", line_width=1,
                  annotation_text=dt.date.today().strftime("%b %Y"), annotation_position="top left",
                  annotation_font={"size": 10, "color": "#5b6b75"})
    n_obs = sum(1 for r in obs_rows if not r["counts"][r["counts"] > 0].empty)
    if n_obs and model_rows:   # categories are drawn bottom-up: models occupy 0..n_models-1
        fig.add_hline(y=len(model_rows) - 0.5, line_color="#d5dee3", line_width=1)
    head = {"size": 11, "color": "#5b6b75"}
    if n_obs:
        fig.add_annotation(xref="paper", x=0, y=len(labels) - 0.5, yshift=4, xanchor="right", yanchor="bottom",
                           text="<b>IN-SITU OBSERVATIONS</b>", showarrow=False, font=head)
    if model_rows:
        fig.add_annotation(xref="paper", x=0, y=len(model_rows) - 0.5, yshift=-4, xanchor="right", yanchor="top",
                           text="<b>MODEL HINDCAST / REANALYSIS</b>", showarrow=False, font=head)

    fig.update_layout(
        barmode="overlay", height=90 + 62 * len(labels), bargap=0.0,
        margin={"l": 10, "r": 20, "t": 40, "b": 40},
        plot_bgcolor="white", paper_bgcolor="white", font={"family": "Public Sans, system-ui, sans-serif"},
        xaxis={"range": [x0, x1], "dtick": 10, "gridcolor": "#d5dee3", "showgrid": True, "zeroline": False,
               "tickfont": {"size": 11, "color": "#5b6b75"}},
        yaxis={"categoryorder": "array", "categoryarray": labels[::-1], "showgrid": False, "automargin": True,
               "range": [-0.6, len(labels) - 0.1],
               "tickfont": {"size": 12.5, "color": "#15232c"}, "ticksuffix": "  "},
    )
    return fig


def station_gantt(df: pd.DataFrame, color: str, now: int) -> go.Figure:
    d = df.copy()
    d["s"] = d["start"].map(_year)
    d["e"] = [(_year(v, now + 1) if stat != "historical" else _year(v)) for v, stat in zip(d["end"], d["status"])]
    d = d.dropna(subset=["s", "e"]).sort_values("s")
    d["lab"] = d["station_id"].astype(str) + " · " + d["name"].astype(str).str.slice(0, 38)
    fig = go.Figure(go.Bar(
        orientation="h", y=d["lab"], x=d["e"] - d["s"], base=d["s"],
        marker={"color": [color if s != "historical" else _mix(color, 0.45) for s in d["status"]]},
        customdata=np.c_[d["s"].round(0).astype(int), np.where(d["status"] == "historical", d["e"].round(0).astype(int).astype(str), "present"),
                         (d["e"] - d["s"]).round(1)],
        hovertemplate="<b>%{y}</b><br>%{customdata[0]}–%{customdata[1]} (%{customdata[2]} yr)<extra></extra>"))
    fig.update_layout(height=max(260, 22 * len(d) + 80), margin={"l": 10, "r": 20, "t": 20, "b": 40},
                      plot_bgcolor="white", xaxis={"gridcolor": "#d5dee3", "dtick": 10},
                      yaxis={"categoryorder": "array", "categoryarray": d["lab"].tolist()[::-1],
                             "tickfont": {"size": 11}, "automargin": True})
    fig.add_vline(x=now + (dt.date.today().timetuple().tm_yday - 1) / 365.25,
                  line_dash="dash", line_color="#5b6b75", line_width=1)
    return fig


def availability_tab(cached_stations):
    now = dt.date.today().year
    st.markdown("##### Observations and model hindcasts through time")
    st.caption("Observed rows: colour intensity = share of the source's stations with a record in that year "
               "(records treated as continuous between first and last date). Model rows: dataset period; "
               "light bar = extended version.")

    obs_rows, all_obs = [], {}
    for key, mod in loaders.OBSERVED.items():
        df = cached_stations(key)
        if df.empty:
            continue
        all_obs[key] = df
        counts = active_counts(df, now)
        n = len(df)
        if counts.empty:
            continue
        first = int(counts[counts > 0].index.min())
        k = min(5, n)
        y5 = counts[counts >= k].index.min() if (counts >= k).any() else None
        ann = f"{first}–present" + (f" · ≥{k} active from {int(y5)}" if y5 and y5 > first else "")
        obs_rows.append({"key": key, "source": mod.SOURCE_NAME, "n": n, "counts": counts,
                         "color": OBS_COLORS.get(key, OBS_FALLBACK), "ann": ann,
                         "label": f"{mod.SOURCE_NAME} ({n} stations)"})

    model_rows = []
    for key, mod in loaders.MODEL.items():
        full, core = model_ranges(mod, now)
        cov = mod.COVERAGE
        end_txt = cov["end"][:7] if cov.get("end") else "present"
        txt = f"{cov['start'][:7]} → {end_txt} · {cov['resolution']}"
        if core:
            txt = f"{cov['core'][0][:4]}–{cov['core'][1][:4]} (ext. {cov['start'][:4]}–{end_txt[:4]}) · {cov['resolution']}"
        span = cov.get("core") or (cov["start"], cov.get("end"))
        yrs = (pd.Timestamp(span[0]).year, pd.Timestamp(span[1]).year if span[1] else now)
        model_rows.append({"label": mod.SOURCE_NAME, "full": full, "core": core, "txt": txt, "yrs": yrs})

    # ---- common overlap: all models (core periods) ∩ years every observed source has ≥ min stations
    c1, c2, c3 = st.columns([1, 1, 2])
    min_active = c1.number_input("Overlap needs ≥ N active stations per observed source", 1, 50, 1, key="av_min")
    years = set(range(1800, now + 1))
    for r in model_rows:
        years &= set(range(r["yrs"][0], r["yrs"][1] + 1))
    for r in obs_rows:
        years &= set(r["counts"][r["counts"] >= min_active].index)
    auto = (min(years), max(years)) if years else None
    use_auto = c2.toggle("Auto overlap", value=True, key="av_auto")
    if use_auto:
        overlap = auto
        c3.caption(f"Common overlap (all models + every observed source): "
                   f"**{auto[0]}–{auto[1]}**" if auto else "No common overlap at this threshold.")
    else:
        overlap = c3.slider("Overlap period", 1900, now, auto or (2008, 2018), key="av_ov")

    starts = [r["counts"][r["counts"] > 0].index.min() for r in obs_rows] + [r["full"][0] for r in model_rows]
    x0 = max(1850, int(np.floor(min(starts) / 10) * 10)) if starts else 1900
    x0 = st.slider("Start chart at", 1850, 2000, min(x0, 1900), step=10, key="av_x0")
    fig = coverage_figure(obs_rows, model_rows, overlap, x0, now + 4, now)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ---- legend (mirrors the inventory page)
    sw = lambda bg: f'<span style="display:inline-block;width:22px;height:10px;border-radius:2px;background:{bg};vertical-align:middle"></span>'
    st.markdown(
        " &nbsp; ".join([
            sw(f"linear-gradient(90deg,{_mix('#1d5f8a', .18)},#1d5f8a)") + " Stations active per year, few → all",
            sw(MODEL) + " Model hindcast / reanalysis",
            sw(MODEL_EXT) + " Extended version",
            sw(OVERLAP) + " Common overlap",
        ]), unsafe_allow_html=True)

    # ---- summary table
    rows = []
    for r in obs_rows:
        c = r["counts"]
        rows.append({"type": "Observed", "source": r["source"], "stations": r["n"],
                     "first year": int(c[c > 0].index.min()),
                     "active now": int(c.get(now, 0)),
                     f"active in overlap ({overlap[0]}–{overlap[1]})" if overlap else "active in overlap":
                         int(c.loc[overlap[0]:overlap[1]].min()) if overlap else None})
    for r in model_rows:
        rows.append({"type": "Model", "source": r["label"], "stations": None,
                     "first year": int(r["full"][0]), "active now": None})
    with st.expander("Summary table"):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # ---- per-station detail
    st.markdown("##### Record length per station")
    if all_obs:
        key = st.selectbox("Source", list(all_obs), format_func=lambda k: loaders.OBSERVED[k].SOURCE_NAME,
                           key="av_src")
        st.plotly_chart(station_gantt(all_obs[key], OBS_COLORS.get(key, OBS_FALLBACK), now),
                        width="stretch", config={"displayModeBar": False})
        st.caption("Dark bars: active stations (to present). Light bars: discontinued stations.")
