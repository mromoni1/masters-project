# Data sources

Reference for all ingestion work. Contains access details, variable lists,
known quirks, and download instructions for every source. One section per
source. Read the relevant section before writing any ingestion script.

---

## PRISM

**What it is:** Gridded climate data for the continental US. The gold standard
for historical climate analysis in California, especially in complex terrain
like Napa Valley. Accounts for elevation, coastal fog, rain shadows, and
mountain microclimates.

**Maintained by:** PRISM Climate Group, Oregon State University

**URL:** https://prism.oregonstate.edu

**Variables used:**

| Variable | Code | Notes |
|---|---|---|
| Daily min temperature | tmin | Primary input for frost day calculation |
| Daily max temperature | tmax | Primary input for heat stress calculation |
| Daily mean temperature | tmean | Used for GDD calculation |
| Precipitation | ppt | Winter precipitation total |
| Min vapor pressure deficit | vpdmin | Supplementary water stress signal |
| Max vapor pressure deficit | vpdmax | Supplementary water stress signal |

**Temporal coverage:**
- Daily grids: 1981–present (primary window for this project)
- Monthly grids: 1895–present (available for long-baseline trend analysis)

**Spatial resolution:**
- 4km: free, publicly available — use this
- 800m: requires fee — not needed at AVA-level aggregation

**Download approach:**
- Bulk gridded download via FTP: `ftp://prism.nacse.org/daily/`
- Or use the PRISM API for point/polygon time series extraction
- Clip to Napa Valley AVA bounding box before saving to reduce file size

**Known quirks:**
- High-resolution (800m) time series data requires a fee
- Monthly data and daily data use different station networks — monthly averages
  do not always match the average of the corresponding dailies
- PRISM explicitly states their data should not be used to calculate long-term
  trends without careful handling — document this as a known limitation
- Files are delivered per-variable per-day as rasters; processing to
  district-level aggregates requires spatial averaging step

**Local path:** `data/raw/prism/`

---

## CDFA Grape Crush Report

**What it is:** Annual survey of all California grape crushers, required by
state law. The most comprehensive source of California winegrape data. Covers
40+ years of history with full industry participation.

**Maintained by:** California Department of Food and Agriculture (CDFA) in
cooperation with USDA NASS Pacific Regional Office

**URL:** https://www.cdfa.ca.gov/mkt/grapecrush.html

**Archive:** https://www.nass.usda.gov/Statistics_by_State/California/Publications/Specialty_and_Other_Releases/Grapes/Crush/Reports/

**Variables used:**

| Variable | Notes |
|---|---|
| Crushed tonnage | Primary yield target variable |
| Degrees Brix at harvest | Primary quality proxy target variable |
| Weighted average price per ton | Secondary — revealed quality proxy |
| Variety | Filter to Cab Sauv, Pinot Noir, Chardonnay |
| District | 17 CDFA grape pricing districts — aggregate to Napa districts |

**Temporal coverage:** 40+ years; exact start year varies by variety and
district. Cabernet Sauvignon has the deepest history.

**Format:** Annual PDF reports with associated Excel/CSV data tables.
Table 8 contains per-transaction data including Brix. Table 10 contains
weighted average prices by variety and district.

**Known quirks:**
- Data is self-reported by crushers; published ~4 months after harvest
- District boundaries do not map 1:1 to AVA boundaries — document the
  mapping used in a comment in the ingestion script
- Less common varieties (Merlot, Petit Verdot, Sauvignon Blanc) have
  spottier records — this project focuses on the three best-covered varieties
- Brix values are at-crush averages, not peak ripeness measurements

**Local path:** `data/raw/cdfa/`

---

## CIMIS

**What it is:** California Irrigation Management Information System. Operated
by the California Department of Water Resources. Provides reference
evapotranspiration (ETo) and weather data from 145+ active stations,
mostly in agricultural areas.

**Maintained by:** California Department of Water Resources (DWR)

**URL:** https://cimis.water.ca.gov

**API docs:** https://et.water.ca.gov/Rest/Index

**Variables used:**

| Variable | Code | Notes |
|---|---|---|
| Reference ETo (grass) | ETo | Primary water demand signal |
| Air temperature | Tx, Tn | Cross-validation against PRISM |
| Solar radiation | Rs | Component of Spatial CIMIS |
| Relative humidity | Rh | Supplementary |

**Temporal coverage:** Station network active since mid-1980s; coverage
improves over time. Some Napa-area stations have records from ~1985.

**Access:**
- Free public API — requires AppKey registration at cimis.water.ca.gov
- REST API delivers hourly and daily records per station
- Spatial CIMIS provides 2km gridded ETo derived from satellite + stations
- Store AppKey in `.env`, never hardcode in scripts

**Napa Valley stations to target:** Identify active and historical stations
within Napa County using the station list endpoint before writing the
ingestion script. Prefer stations with the longest continuous records.

**Known quirks:**
- Station network has gaps — some years/stations have missing data requiring
  interpolation or imputation; document approach taken
- Spatial CIMIS (gridded ETo) is only available from ~2003 onward
- ETo is reference evapotranspiration from a standardized grass surface —
  must be converted to crop ET using vine crop coefficients (Kc) for
  actual vine water demand; this conversion is optional for this project

**Local path:** `data/raw/cimis/`

---

## SSURGO (soil data)

**What it is:** USDA Soil Survey Geographic Database. National soil survey
data at the county level. Provides static soil physical properties per map
unit. Used as fixed covariates in the model — soil properties do not change
year to year.

**Maintained by:** USDA Natural Resources Conservation Service (NRCS)

**URL:** https://websoilsurvey.sc.egov.usda.gov

**Variables used:**

| Variable | Code | Notes |
|---|---|---|
| Available water capacity | awc_r | Most important soil feature for viticulture |
| Drainage class | drainagecl | Categorical: well/moderately well/somewhat poor/poor |
| Clay fraction (%) | claytotal_r | Affects water retention and heat capacity |
| Texture class | texcl | Categorical: loam/clay loam/sandy loam/etc. |

**Spatial coverage:** Download for Napa County. Spatially average each
variable to AVA district level using a spatial join — one value per district.

**Access:**
- Download via Web Soil Survey "Download Soils Data" for Napa County
- Or use the SSURGO API / Soil Data Access query service
- Static download — run once, not annually

**Known quirks:**
- Map unit polygons don't align with AVA boundaries — spatial averaging
  introduces some imprecision; document the averaging method used
- Some map units have null values for specific attributes — handle with
  spatial median imputation within county
- SSURGO data is revised periodically; note the version/download date

**Local path:** `data/raw/ssurgo/`

---

## DWR water year classifications

**What it is:** Annual water year type classifications for California, based
on accumulated precipitation and runoff. Published by the California
Department of Water Resources and the State Water Resources Control Board.

**Maintained by:** California DWR

**URL:** https://cdec.water.ca.gov/reportapp/javareports?name=WSIHIST

**Variable used:**

| Variable | Values | Notes |
|---|---|---|
| Water year type | W / AN / BN / D / C | Wet, Above Normal, Below Normal, Dry, Critically Dry |

**Temporal coverage:** 1901–present for Sacramento Valley index;
use Sacramento Valley index as the primary signal for Napa.

**Access:** Download historical table from CDEC. Single CSV with one row
per year. Updated annually by October.

**Known quirks:**
- Water year runs October 1 – September 30, not calendar year — align
  carefully with growing season year in feature matrix
- Multiple regional indices exist (Sacramento, San Joaquin, Trinity);
  use Sacramento Valley as the Napa-relevant index
- Classification is coarse (5 categories) — treat as ordinal categorical,
  not continuous

**Local path:** `data/raw/dwr/`

---

## Data directory structure

```
data/
├── raw/
│   ├── prism/          ← daily raster grids per variable per year
│   ├── cdfa/           ← annual crush report CSVs
│   ├── cimis/          ← station ETo records by station and year
│   ├── ssurgo/         ← soil survey download for Napa County
│   └── dwr/            ← water year classification table
├── processed/
│   ├── features.parquet       ← final feature matrix (year × variety × AVA)
│   ├── targets.parquet        ← Brix and tonnage by year × variety × district
│   └── baselines.parquet      ← precomputed baseline predictions
└── feedback.db         ← SQLite harvest log (see docs/database.md)
```

---

## Source priority and conflict resolution

If PRISM and CIMIS temperature values diverge for the same location and date,
PRISM is authoritative for model inputs. CIMIS temperature is used only for
cross-validation. ETo values come exclusively from CIMIS — PRISM does not
provide ETo.
