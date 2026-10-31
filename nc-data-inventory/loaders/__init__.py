"""Registry of data loaders.

Add each new loader module here once it is written; the dashboard builds its
tabs and layer lists from these two dicts, so nothing else has to change.
"""

from loaders import noaa_coops

# key -> module
OBSERVED = {
    "noaa_coops": noaa_coops,
    # "ndbc": ndbc,            # Step 2
    # "usgs_nwis": usgs_nwis,  # Step 3
}

MODEL = {
    # "wis": wis,              # Step 4
    # "codec_gtsm": codec,     # Step 5
    # "cora": cora,            # Step 6
    # "era5": era5,            # Step 7
    # "conus404": conus404,    # Step 8
}

# marker colour per source on the map
COLORS = {
    "noaa_coops": "#1f77b4",
    "ndbc": "#ff7f0e",
    "usgs_nwis": "#2ca02c",
    "wis": "#9467bd",
    "codec_gtsm": "#8c564b",
    "cora": "#e377c2",
    "era5": "#7f7f7f",
    "conus404": "#bcbd22",
}
