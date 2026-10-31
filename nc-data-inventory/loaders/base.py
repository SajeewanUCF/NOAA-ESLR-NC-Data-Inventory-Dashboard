"""Shared conventions for every data loader.

Every loader module (one per data source) exposes the same interface so the
dashboard can treat them generically:

    SOURCE_NAME : str                 human-readable name
    PRODUCTS    : dict[str, dict]     product key -> {"label": ..., "units": ...}
    OPTIONS     : dict[str, list]     extra user choices (e.g. datum), may be empty

    list_stations() -> pd.DataFrame   columns = STATION_COLUMNS
    get_data(station_id, start, end, product, **options) -> pd.DataFrame
        index  : DatetimeIndex (UTC, named "time")
        columns: one or more numeric variables, names include units, e.g. "water_level_m"

Gridded sources (ERA5, CONUS404, ...) use a "virtual station" = nearest grid
point to a lat/lon the user picks, so they fit the same interface.
"""

import pandas as pd

from config import NC_BBOX

STATION_COLUMNS = [
    "source",       # e.g. "NOAA CO-OPS"
    "station_id",   # id used by the API
    "name",
    "lat",
    "lon",
    "start",        # first available date (Timestamp, UTC) or NaT
    "end",          # last available date (Timestamp, UTC) or NaT (NaT = ongoing)
    "status",       # "active" / "historical"
]


def empty_stations() -> pd.DataFrame:
    return pd.DataFrame(columns=STATION_COLUMNS)


def in_bbox(df: pd.DataFrame, bbox=NC_BBOX) -> pd.DataFrame:
    """Keep rows whose lat/lon fall inside bbox = (lon_min, lat_min, lon_max, lat_max)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    mask = df["lon"].between(lon_min, lon_max) & df["lat"].between(lat_min, lat_max)
    return df.loc[mask].reset_index(drop=True)


def date_chunks(start: pd.Timestamp, end: pd.Timestamp, max_days: int):
    """Split [start, end] into consecutive windows no longer than max_days."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    cur = start
    while cur <= end:
        nxt = min(cur + pd.Timedelta(days=max_days - 1), end)
        yield cur, nxt
        cur = nxt + pd.Timedelta(days=1)
