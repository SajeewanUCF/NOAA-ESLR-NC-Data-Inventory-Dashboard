"""NDBC wave buoys and C-MAN stations (standard meteorological data).

Source: NOAA CoastWatch ERDDAP, dataset "cwwcNDBCMet", a quality-controlled
aggregation of every NDBC stdmet file (historical + recent), 1970 -> present.
    https://coastwatch.pfeg.noaa.gov/erddap/tabledap/cwwcNDBCMet.html

ERDDAP is used instead of the raw NDBC text files because it serves the whole
record of any station (including retired buoys) through one query interface.
Note: NDBC wind is measured at anemometer height (~4-5 m on 3-m buoys), not 10 m.
"""

from __future__ import annotations

import io
from urllib.parse import quote

import pandas as pd
import requests

from config import NC_BBOX
from loaders.base import STATION_COLUMNS, date_chunks, empty_stations, finish

SOURCE_NAME = "NDBC buoys"
KIND = "point"
COVERAGE = {"start": "1970-02-26", "end": None, "resolution": "buoys / C-MAN, 10-60 min",
            "note": "Hs, periods, wave direction, wind, pressure, temperatures"}

ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
DATASET = "cwwcNDBCMet"
TIMEOUT = 180

# ERDDAP variable -> standard column name
RENAME = {
    "wvht": "hs_m", "dpd": "tp_s", "apd": "tm_s", "mwd": "wave_dir_deg",
    "wspd": "wind_speed_ms", "wd": "wind_dir_deg", "gst": "wind_gust_ms",
    "bar": "pressure_mb", "atmp": "air_temp_c", "wtmp": "water_temp_c",
}
PRODUCTS = {
    "waves": {"label": "Waves (Hs, Tp, Tm, direction)", "vars": ["wvht", "dpd", "apd", "mwd"]},
    "met":   {"label": "Wind & pressure",               "vars": ["wspd", "wd", "gst", "bar"]},
    "temp":  {"label": "Air & water temperature",       "vars": ["atmp", "wtmp"]},
    "all":   {"label": "All standard met variables",    "vars": list(RENAME)},
}
OPTIONS: dict = {}


def _varnames() -> dict[str, str]:
    """lower-case name -> actual ERDDAP name (ERDDAP is case-sensitive)."""
    r = requests.get(f"{ERDDAP}/info/{DATASET}/index.csv", timeout=TIMEOUT)
    r.raise_for_status()
    info = pd.read_csv(io.StringIO(r.text))
    names = info.loc[info["Row Type"] == "variable", "Variable Name"]
    return {n.lower(): n for n in names}


def _query(variables: list[str], constraints: list[str]) -> pd.DataFrame:
    q = ",".join(variables) + "".join("&" + c for c in constraints)
    url = f"{ERDDAP}/tabledap/{DATASET}.csv?" + quote(q, safe="&=,")
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:          # ERDDAP answers 404 when nothing matches
        return pd.DataFrame()
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), skiprows=[1])  # row 2 = units


def _bbox_constraints() -> list[str]:
    lon0, lat0, lon1, lat1 = NC_BBOX
    return [f"longitude>={lon0}", f"longitude<={lon1}", f"latitude>={lat0}", f"latitude<={lat1}"]


def list_stations() -> pd.DataFrame:
    try:
        vm = _varnames()
    except Exception:
        return empty_stations()
    st, lon, lat, t = vm.get("station", "station"), vm.get("longitude"), vm.get("latitude"), vm.get("time")

    df = pd.DataFrame()
    # Newer versions of the dataset carry per-station coverage dates -> one cheap query
    if "data_coverage_start" in vm and "data_coverage_end" in vm:
        cols = [st, lon, lat, vm["data_coverage_start"], vm["data_coverage_end"]]
        if "station_name" in vm:
            cols.append(vm["station_name"])
        try:
            df = _query(cols, _bbox_constraints() + ["distinct()"])
            df = df.rename(columns={vm["data_coverage_start"]: "start",
                                    vm["data_coverage_end"]: "end",
                                    vm.get("station_name", "_"): "name"})
        except Exception:
            df = pd.DataFrame()
    # Fallback: first/last observation time per station
    if df.empty:
        try:
            raw = _query([st, lon, lat, t], _bbox_constraints() + [f'orderByMinMax("{st},{t}")'])
            g = raw.groupby(st)
            df = pd.DataFrame({lon: g[lon].last(), lat: g[lat].last(),
                               "start": g[t].min(), "end": g[t].max()}).reset_index()
        except Exception:
            return empty_stations()

    df = df.rename(columns={st: "station_id", lon: "lon", lat: "lat"})
    df = df.groupby("station_id", as_index=False).last()   # buoys drift: keep latest position
    df["station_id"] = df["station_id"].astype(str)
    if "name" not in df:
        df["name"] = "NDBC " + df["station_id"]
    df["name"] = df["name"].fillna("NDBC " + df["station_id"])
    df["start"] = pd.to_datetime(df["start"], utc=True, errors="coerce")
    df["end"] = pd.to_datetime(df["end"], utc=True, errors="coerce")
    recent = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)
    df["status"] = ["active" if pd.notna(e) and e >= recent else "historical" for e in df["end"]]
    df.loc[df["status"] == "active", "end"] = pd.NaT
    df["source"] = SOURCE_NAME

    # per-variable records: which stations actually measured waves / wind, and when
    for var, tag in (("wvht", "wave"), ("wspd", "wind")):
        rec = _var_record(vm, var)
        df[f"{tag}_start"] = df["station_id"].map(rec["start"]) if rec is not None else pd.NaT
        df[f"{tag}_end"] = df["station_id"].map(rec["end"]) if rec is not None else pd.NaT
        if rec is None:  # query failed: numeric ids are moored buoys (waves), letters are C-MAN/NOS (wind)
            has = df["station_id"].str.match(r"^\d") if tag == "wave" else pd.Series(True, index=df.index)
            df.loc[has, f"{tag}_start"], df.loc[has, f"{tag}_end"] = df.loc[has, "start"], df.loc[has, "end"]
    extra = ["wave_start", "wave_end", "wind_start", "wind_end"]
    return df[STATION_COLUMNS + extra]


def _var_record(vm: dict, var: str) -> pd.DataFrame | None:
    """First/last time each NC-region station reported a valid value of `var`."""
    if var not in vm:
        return None
    st, t, v = vm["station"], vm["time"], vm[var]
    try:
        raw = _query([st, t], _bbox_constraints() + [f"{v}!=NaN", f'orderByMinMax("{st},{t}")'])
    except Exception:
        return None
    if raw.empty:
        return pd.DataFrame(columns=["start", "end"])
    raw[t] = pd.to_datetime(raw[t], utc=True, errors="coerce")
    g = raw.groupby(raw[st].astype(str))[t]
    return pd.DataFrame({"start": g.min(), "end": g.max()})


def get_data(station_id: str, start, end, product: str = "waves", progress=None, **_) -> pd.DataFrame:
    vm = _varnames()
    wanted = [v for v in PRODUCTS[product]["vars"] if v in vm]
    cols = [vm["time"]] + [vm[v] for v in wanted]
    chunks = list(date_chunks(start, end, 5 * 365))
    parts = []
    for i, (b, e) in enumerate(chunks):
        cons = [f'{vm["station"]}="{station_id}"',
                f'{vm["time"]}>={b:%Y-%m-%d}T00:00:00Z', f'{vm["time"]}<={e:%Y-%m-%d}T23:59:59Z']
        try:
            parts.append(_query(cols, cons))
        except requests.RequestException:
            pass
        if progress:
            progress((i + 1) / len(chunks))
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame()
    raw = pd.concat(parts)
    raw.index = pd.to_datetime(raw.pop(vm["time"]), utc=True)
    raw.columns = [c.lower() for c in raw.columns]
    out = raw.rename(columns=RENAME).apply(pd.to_numeric, errors="coerce")
    return finish(out, start, end)


if __name__ == "__main__":
    print(list_stations())
    print(get_data("41025", "2023-08-01", "2023-08-03"))  # Diamond Shoals
