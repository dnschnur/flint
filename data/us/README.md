# USA Reference Data

## Overview

| File | Description |
|---|---|
| `sp500.csv` | Historical S&P 500 monthly values from 1871 to the present |
| `rmd.csv` | IRS Uniform Lifetime Table for Required Minimum Distributions |
| `income_tax.csv` | Federal income tax brackets by year |
| `capital_gains_tax.csv` | Federal long-term capital gains tax brackets by year |
| `ca/income_tax.csv` | California state income tax brackets by year |
| `inflation.csv` | Composite per-category inflation dataset, 1913 to the present |
| `build_inflation.py` | Script to regenerate `inflation.csv` from FRED and BLS |

## `sp500.csv`

Monthly S&P 500 index values used by the Monte Carlo engine to replay historical return
sequences.

## `rmd.csv`

IRS Uniform Lifetime Table divisors by age, used to compute Required Minimum Distributions
from 401K and IRA accounts once the account holder reaches age 73.

## `income_tax.csv` and `capital_gains_tax.csv`

Federal tax bracket tables with one set of thresholds per filing year.

## `ca/income_tax.csv`

California state income tax brackets, structured identically to the federal income bracket
table.

To add brackets for another state, create `<state_code>/income_tax.csv` following the same
format; Flint loads it automatically when `state = "<state_code>"` is set in a scenario.

## `inflation.csv`

Rows cover **1913 through the most recent complete calendar year** (CPI data) or 1929 (BEA PCE
data). Earlier years are backfilled synthetically where noted below.

All series are normalized to **2000 = 100**.

### Column definitions

| Column | Description | Primary source | Original start |
|---|---|---|---|
| `PCE_Healthcare` | Personal consumption expenditures price index: health care services | BEA/FRED `DHLCRG3A086NBEA` | 1929 |
| `PCE_HigherEducation` | PCE price index: higher education services | BEA/FRED `DHEDRG3A086NBEA` | 1929 |
| `PCE_FoodServices` | PCE price index: food services and accommodations | BEA/FRED `DFSARG3A086NBEA` | 1929 |
| `PCE_GroundTransport` | PCE price index: ground transportation services | BEA/FRED `DGRDRG3A086NBEA` | 1929 |
| `PCE_VehicleInsurance` | PCE price index: motor vehicle and transportation insurance | BEA/FRED `DTINRG3A086NBEA` | 1929 |
| `PCE_HousingUtils` | PCE price index: housing and utilities (quarterly series, averaged to annual) | BEA/FRED `DHUTRG3Q086SBEA` | 1947 |
| `CPI_All` | CPI-U all items (not seasonally adjusted), used as baseline backfill series | BLS/FRED `CPIAUCNS` | Jan 1913 |
| `CPI_Shelter` | CPI: shelter (rent + owners' equivalent rent + lodging) | BLS/FRED `CUUR0000SAH1` | Dec 1952 |
| `CPI_Rent` | CPI: rent of primary residence | BLS/FRED `CUUR0000SEHA` | Dec 1914 |
| `CPI_Electricity` | CPI: electricity | BLS/FRED `CUUR0000SEHF01` | Dec 1913 |
| `CPI_PipedGas` | CPI: utility (piped) gas service | BLS/FRED `CUSR0000SEHF02` | Jan 1952 |
| `CPI_WaterSewer` | CPI: water, sewer, and trash collection | BLS/FRED `CUSR0000SEHG` | Dec 1997 |
| `CPI_FoodAtHome` | CPI: food at home (groceries) | BLS/FRED `CUUR0000SAF11` | Jan 1947 |
| `CPI_FoodAwayFromHome` | CPI: food away from home (restaurants) | BLS/FRED `CUUR0000SEFV` | Jan 1953 |
| `CPI_Gasoline` | CPI: gasoline (all types) | BLS/FRED `CUUR0000SETB01` | Mar 1935 |
| `CPI_NewVehicles` | CPI: new vehicles | BLS/FRED `CUUR0000SETA01` | Mar 1947 |
| `CPI_VehicleMaintenance` | CPI: motor vehicle maintenance and repair | BLS/FRED `CUUR0000SETD` | Mar 1947 |
| `CPI_VehicleInsurance` | CPI: motor vehicle insurance | BLS API `CUUR0000SETE` | Jan 1996 |
| `CPI_MedicalCare` | CPI: medical care (all, including commodities and services) | BLS/FRED `CPIMEDSL` | Jan 1947 |
| `CPI_MedicalServices` | CPI: medical care services | BLS/FRED `CUUR0000SAM2` | Mar 1935 |
| `CPI_HospitalServices` | CPI: hospital and related services | BLS/FRED `CUSR0000SEMD` | Jan 1978 |
| `CPI_CollegeTuition` | CPI: college tuition and fees | BLS API `CUUR0000SEEB01` | Jan 1978 |
| `CPI_TuitionChildcare` | CPI: tuition, other school fees, and childcare | BLS/FRED `CUSR0000SEEB` | Jan 1978 |

Most CPI series use not-seasonally-adjusted (NSA, `CUUR` prefix) variants rather than the
seasonally-adjusted (`CUSR`) equivalents. For annual averages, the two are mathematically
identical (seasonal effects cancel over twelve months), but NSA series are often available
earlier. `CPI_VehicleInsurance` and `CPI_CollegeTuition` are not published on FRED and are
fetched directly from the BLS Public Data API.

## Sources

### BEA Personal Consumption Expenditures (PCE) Price Indexes
- **URL:** https://fred.stlouisfed.org (search by series ID)
- **Direct CSV download (no registration):** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID`
- **Frequency:** Annual
- **Base year:** 2017 = 100 (renormalized to 2000 = 100 in this file)
- **Why preferred for healthcare:** The PCE healthcare deflator covers all medical spending
  (including employer-paid and government-paid insurance), whereas the CPI medical series
  covers only out-of-pocket consumer expenditures. The PCE measure better reflects the true
  cost trend a household will face over time.
- **Why preferred for education:** The PCE higher-education index starts in 1929 vs. 1978 for
  the CPI college tuition series, providing 49 additional years of primary data.

### BLS Consumer Price Index (CPI-U)
- **URL:** https://fred.stlouisfed.org or https://download.bls.gov/pub/time.series/cu/
- **Direct CSV download (no registration):** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID`
- **Frequency:** Monthly (annual averages computed here)
- **Base year:** 1982–84 = 100 (renormalized to 2000 = 100 in this file)
- **Coverage:** Most subcategories start 1935–1978; electricity starts December 1913.
  `CPIAUCNS` (all items, not seasonally adjusted) starts January 1913 and serves as the
  baseline for backfilling.

## Backfill methodology

Many series do not cover the full 1913–present range. Where a series starts later than
the earliest available data (1913 for CPI, 1929 for PCE), synthetic values are generated
by extrapolating backward using a longer related series, adjusted for the average historical
rate difference between the two.

### Algorithm

Given a *primary* series P (shorter) and a *reference* series R (longer):

1. Find the **overlap period**: years where both P and R have original data.
2. For each year y in the overlap, compute:
   - `rate_P(y) = P[y] / P[y-1] - 1`
   - `rate_R(y) = R[y] / R[y-1] - 1`
3. Compute `delta = mean(rate_P(y) - rate_R(y))` across all overlap years.
   This is the average annual spread by which P inflated faster (or slower) than R.
4. For each year y before P starts (working backward):
   - `synthetic_rate(y→y+1) = rate_R(y→y+1) + delta`
   - `P[y] = P[y+1] / (1 + synthetic_rate(y→y+1))`

This ensures that the synthetic pre-history inflates at the same *relative* pace as the
reference series, adjusted up or down by the long-run spread between the two series.

### Backfill chain

Each series is extended backward through one or more steps, always using the closest
available proxy as the reference before falling back to `CPI_All`:

| Series extended | Step 1 reference | Step 2 reference | Step 3 reference |
|---|---|---|---|
| `PCE_Healthcare` | `CPI_All` (1913) | - | - |
| `PCE_HigherEducation` | `CPI_All` (1913) | - | - |
| `PCE_FoodServices` | `CPI_All` (1913) | - | - |
| `PCE_GroundTransport` | `CPI_All` (1913) | - | - |
| `PCE_VehicleInsurance` | `CPI_All` (1913) | - | - |
| `PCE_HousingUtils` | `CPI_All` (1913) | - | - |
| `CPI_Rent` | `CPI_All` (1913) | - | - |
| `CPI_Shelter` | `CPI_Rent` (1914) | `CPI_All` (1913) | - |
| `CPI_PipedGas` | `CPI_Electricity` (1913) | - | - |
| `CPI_WaterSewer` | `CPI_PipedGas` (1952+) | `CPI_Electricity` (1913) | - |
| `CPI_FoodAtHome` | `CPI_All` (1913) | - | - |
| `CPI_FoodAwayFromHome` | `CPI_FoodAtHome` (1947) | `CPI_All` (1913) | - |
| `CPI_Gasoline` | `CPI_All` (1913) | - | - |
| `CPI_VehicleMaintenance` | `CPI_All` (1913) | - | - |
| `CPI_NewVehicles` | `CPI_VehicleMaintenance` (1947) | `CPI_All` (1913) | - |
| `CPI_VehicleInsurance` | `PCE_VehicleInsurance` (1929) | `CPI_All` (1913) | - |
| `CPI_MedicalCare` | `PCE_Healthcare` (1929) | `CPI_All` (1913) | - |
| `CPI_MedicalServices` | `CPI_MedicalCare` (1947) | - | - |
| `CPI_HospitalServices` | `CPI_MedicalServices` (1935) | - | - |
| `CPI_CollegeTuition` | `PCE_HigherEducation` (1929) | `CPI_All` (1913) | - |
| `CPI_TuitionChildcare` | `PCE_HigherEducation` (1929) | `CPI_All` (1913) | - |

### Synthetic vs. original data

Synthetic (backfilled) values are distinguishable from original values by year:

- **PCE series**: original ≥ 1929 (or ≥ 1947 for `PCE_HousingUtils`); synthetic 1913–1928
- **CPI_FoodAtHome, CPI_VehicleMaintenance, CPI_MedicalCare**: original ≥ 1947; synthetic 1913–1946
- **CPI_Electricity**: original ≥ 1913 (nearly no synthetic data)
- **CPI_Rent**: original ≥ 1914 (Dec 1914); synthetic 1913 only
- **CPI_Shelter**: original ≥ 1952 (Dec 1952); synthetic 1913–1951
- **CPI_FoodAwayFromHome**: original ≥ 1953; synthetic 1913–1952
- **CPI_PipedGas**: original ≥ 1952; synthetic 1913–1951
- **CPI_Gasoline, CPI_MedicalServices**: original ≥ 1935 (Mar 1935); synthetic 1913–1934
- **CPI_NewVehicles**: original ≥ 1947 (Mar 1947); synthetic 1913–1946
- **CPI_HospitalServices**: original ≥ 1978; rest derived from CPI_MedicalServices chain
- **CPI_CollegeTuition, CPI_TuitionChildcare**: original ≥ 1978; 1929–1977 from PCE_HigherEducation; 1913–1928 from CPI_All
- **CPI_VehicleInsurance**: original ≥ 1996; 1929–1995 from PCE_VehicleInsurance; 1913–1928 from CPI_All
- **CPI_WaterSewer**: original ≥ 1997; rest derived from CPI_PipedGas/CPI_Electricity chain

## Updating the dataset

Run `build_inflation.py` from the repository root to fetch fresh data from FRED and
regenerate `inflation.csv`:

```bash
python data/us/build_inflation.py
```

The script requires only Python 3.11+ standard library modules (no third-party packages).
FRED updates CPI data monthly (mid-month for the prior month) and BEA PCE data annually
(typically released in Q2 for the prior year). Running the script once per year is sufficient
to keep the dataset current.

## Limitations

- **`CPI_WaterSewer` and `CPI_VehicleInsurance` have very short primary histories** (~27
  years each). Their backfilled values before ~1997 are rough estimates.
- **`PCE_FoodServices` bundles restaurants with hotel accommodation**, slightly inflating
  the food-away-from-home rate. `CPI_FoodAwayFromHome` is a cleaner restaurant-only measure
  from 1953 onward.
- **OER methodology**: `CPI_Shelter` uses Owners' Equivalent Rent for homeowners, which is
  an imputed measure that lags actual home-price appreciation and can diverge significantly
  from transaction prices during housing market cycles.
