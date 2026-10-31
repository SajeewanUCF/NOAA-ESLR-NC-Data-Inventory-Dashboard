# North Carolina Coastal Data Inventory

Streamlit dashboard that inventories observed and model/hindcast coastal data
for the North Carolina coast and validates models against observations.

## Structure

```
nc-data-inventory/
├── app.py              # dashboard (map + Observed / Model / Validation tabs)
├── config.py           # map centre, NC bounding box, basemaps
├── validation.py       # alignment + skill metrics (Bias, RMSE, R, SI, Willmott d)
├── requirements.txt
└── loaders/
    ├── __init__.py     # registry: add each new loader here
    ├── base.py         # shared interface + helpers
    └── noaa_coops.py   # NOAA tide gauges (Step 1)
```

Every loader exposes `SOURCE_NAME`, `PRODUCTS`, `OPTIONS`, `list_stations()` and
`get_data(station_id, start, end, product, **options)`, so the dashboard needs
no changes when a new source is registered in `loaders/__init__.py`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m loaders.noaa_coops      # quick API test
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this folder to a GitHub repository.
2. Go to share.streamlit.io → **New app** → pick the repo, branch, and `app.py`.
3. Add any API keys (needed later for ERA5 / Copernicus) under **Settings → Secrets**.

## Roadmap

| Step | Source | Tab |
|---|---|---|
| 1 ✅ | Project skeleton, map, NOAA CO-OPS tide gauges | Observed |
| 2 | NDBC wave buoys | Observed |
| 3 | USGS stream gauges (NWIS) | Observed |
| 4 | USACE WIS waves | Model |
| 5 | CoDEC / GTSM-ERA5 tide & surge | Model |
| 6 | NOAA CORA water level & waves | Model |
| 7 | ERA5 wind | Model |
| 8 | CONUS404 | Model |
| 9 | Validation UI | Validation |
