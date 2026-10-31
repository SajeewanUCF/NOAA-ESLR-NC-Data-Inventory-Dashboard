"""NOAA Coastal Ocean Reanalysis (CORA) — water level and waves.

Source: NOAA Open Data Dissemination, AWS bucket s3://noaa-nos-cora-pds (public).
GEC domain (US East & Gulf coasts, Caribbean), hourly, 1979-2022, ADCIRC+SWAN
unstructured mesh (~500 m at the coast). Water levels are relative to MSL.

Access follows NOAA's own notebooks (github.com/NOAA-CO-OPS/CORA-Coastal-Ocean-Reanalysis-CORA):
the intake catalog in the bucket points to cloud-optimised Zarr stores; the
"-timeseries" stores are chunked for long point time series. Here the catalog
YAML is read directly so the app does not depend on intake.
The model value is taken at the mesh node nearest the requested point.
"""

from __future__ import annotations

from functools import lru_cache

import fsspec
import numpy as np
import pandas as pd
import xarray as xr
import yaml

from config import NC_BBOX
from loaders.base import empty_stations, finish, nearest, parse_point

SOURCE_NAME = "NOAA CORA"
KIND = "gridded"
COVERAGE = {"start": "1979-01-01", "end": "2022-12-31", "resolution": "ADCIRC+SWAN mesh (~500 m), hourly",
            "note": "Water level (rel. MSL), Hs, Tp, mean wave direction"}

BUCKET = "s3://noaa-nos-cora-pds"
S3 = {"anon": True}
DOMAIN = "GEC"

PRODUCTS = {
    "water_level": {"label": "Water level, rel. MSL (hourly)", "tag": "fort.63",  "var": "zeta",     "col": "water_level_m"},
    "hs":          {"label": "Significant wave height",        "tag": "swan_HS",  "var": "swan_HS",  "col": "hs_m"},
    "tp":          {"label": "Peak wave period",               "tag": "swan_TPS", "var": "swan_TPS", "col": "tp_s"},
    "dir":         {"label": "Mean wave direction",            "tag": "swan_DIR", "var": "swan_DIR", "col": "wave_dir_deg"},
}
OPTIONS: dict = {}


@lru_cache(maxsize=1)
def _catalog() -> dict:
    import zarr
    names = ["CORA_intake_zarr3.yml", "CORA_intake.yml"]
    if int(zarr.__version__.split(".")[0]) < 3:
        names.reverse()
    last_err = None
    for n in names:
        try:
            with fsspec.open(f"{BUCKET}/{n}", "r", **S3) as f:
                cat = yaml.safe_load(f)
            return cat.get("sources", cat)
        except Exception as e:  # noqa: PERF203
            last_err = e
    raise RuntimeError(f"Could not read CORA intake catalog: {last_err}")


def _entry_name(tag: str) -> str:
    srcs = _catalog()
    want = f"CORA-{DOMAIN}-{tag}.63-timeseries".replace(".63.63", ".63")
    if want in srcs:
        return want
    for name in srcs:  # tolerate small naming changes
        if DOMAIN in name and tag in name and "timeseries" in name:
            return name
    raise KeyError(f"No CORA catalog entry for {tag}")


@lru_cache(maxsize=8)
def _open(tag: str) -> xr.Dataset:
    entry = _catalog()[_entry_name(tag)]
    args = dict(entry.get("args", {}))
    url = str(args.pop("urlpath")).replace("{{ CATALOG_DIR }}", BUCKET).replace("{{CATALOG_DIR}}", BUCKET)
    so = args.pop("storage_options", None) or S3
    kw = {k: v for k, v in args.items() if k in ("consolidated", "group")}
    if url.startswith("reference://") or url.endswith(".json") or "reference" in str(entry.get("driver", "")):
        fo = url.replace("reference://", "")
        fs = fsspec.filesystem("reference", fo=fo, remote_protocol="s3", remote_options=so,
                               target_options=so)
        return xr.open_dataset(fs.get_mapper(""), engine="zarr", consolidated=False, chunks={})
    return xr.open_zarr(url, storage_options=so, chunks={}, **kw)


@lru_cache(maxsize=8)
def _nc_nodes(tag: str):
    """Node indices and coordinates inside the NC box (loaded once)."""
    ds = _open(tag)
    x, y = ds["x"].values, ds["y"].values
    lon0, lat0, lon1, lat1 = NC_BBOX
    idx = np.where((x >= lon0) & (x <= lon1) & (y >= lat0) & (y <= lat1))[0]
    return idx, y[idx], x[idx]


def list_stations():
    return empty_stations()


def get_data(station_id: str, start, end, product: str = "water_level", progress=None, **_) -> pd.DataFrame:
    p = PRODUCTS[product]
    lat, lon = parse_point(station_id)
    ds = _open(p["tag"])
    idx, ys, xs = _nc_nodes(p["tag"])
    j, dist = nearest(lat, lon, ys, xs)
    node = int(idx[j])
    da = ds[p["var"]].isel(node=node).sel(time=slice(str(pd.Timestamp(start).date()),
                                                     str((pd.Timestamp(end) + pd.Timedelta(days=1)).date())))
    if progress:
        progress(0.5)
    vals = da.values.astype(float)
    vals[vals < -999] = np.nan                     # dry nodes / fill values
    out = pd.DataFrame({p["col"]: vals}, index=pd.to_datetime(da["time"].values))
    if progress:
        progress(1.0)
    out = finish(out, start, end)
    out.attrs["model_location"] = (float(ys[j]), float(xs[j]))
    out.attrs["note"] = f"CORA node {node}, {dist:.2f} km from requested point"
    return out


if __name__ == "__main__":
    print(get_data("34.72,-76.67", "2018-09-13", "2018-09-15"))  # near Beaufort, NC
