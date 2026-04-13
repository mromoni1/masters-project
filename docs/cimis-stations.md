# CIMIS Station Selection — Napa County

Generated: 2026-04-13  
Source: CIMIS station list API — `https://et.water.ca.gov/api/station`  
Selection threshold: ≥ 10 years of continuous record  

---

## Selection Rationale

The CIMIS network has been expanding since the mid-1980s. To ensure
that each station contributes a statistically meaningful time series
for climate-trend analysis, stations with fewer than 10 years of
data are excluded. Ten years is the minimum window needed to
characterise inter-annual variability and align with the growing
season records in the CDFA Grape Crush data (1991–present).

ETo availability is assumed for all CIMIS weather stations — the
network instruments every station for reference evapotranspiration
by design. Station-level data gaps (missing daily records) should
be assessed during ingestion and documented in the cleaning step.

Stations are ranked by record length (longest first). The primary
ingestion target is the full selected set; stations can be dropped
later if gap analysis reveals insufficient coverage.

---

## Selected Stations (2)

These stations meet the ≥ 10-year threshold and are targeted by the
CIMIS ingestion script.

| Station ID | Name | Status | Connect Date | Disconnect Date | Record (yrs) | Elevation (ft) | Lat | Lon |
|---|---|---|---|---|---|---|---|---|
| 77 | Oakville | Active | 1989-03-01 | 2050-12-31 | 61.8 | 190 | 38º25'43N / 38.428475 | -122º24'37W / -122.410210 |
| 109 | Carneros | Inactive | 1993-03-11 | 2022-01-13 | 28.8 | 5 | 38º13'10N / 38.219503 | -122º21'18W / -122.354960 |

---

## Excluded Stations (1)

Stations in Napa County with fewer than 10 years of record.

| Station ID | Name | Status | Connect Date | Disconnect Date | Record (yrs) |
|---|---|---|---|---|---|
| 79 | Angwin | Inactive | 1989-05-11 | 1996-12-27 | 7.6 |

---

## Variables Available at CIMIS Stations

All CIMIS weather stations in the selected set report the following
daily data items relevant to this project:

| Variable | CIMIS Code | Notes |
|---|---|---|
| Reference ETo (grass) | ETo | Primary water demand signal |
| Air temperature (max) | Tx | Cross-validation against PRISM |
| Air temperature (min) | Tn | Cross-validation against PRISM |
| Solar radiation | Rs | Component of Spatial CIMIS |
| Relative humidity (avg) | Rh | Supplementary |
| Wind speed | U2 | Supplementary |

> **Note:** Spatial CIMIS (gridded ETo) is available from ~2003 onward
> and supplements point station data for years/areas with gaps.

---

## Usage in Ingestion Script

The station IDs listed in **Selected Stations** above are the
authoritative targets for the CIMIS ingestion script. Copy the IDs
into a constant in `src/ingestion/ingest_cimis.py`:

```python
NAPA_STATION_IDS: list[str] = [
    "77",  # Oakville
    "109",  # Carneros
]
```
