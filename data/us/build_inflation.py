"""Builds the data/us/inflation.csv composite historical US inflation dataset.

Data sources:
  - FRED (Federal Reserve Bank of St. Louis): https://fred.stlouisfed.org
    CSV endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID
  - BLS Public Data API v1 (no registration required):
    https://api.bls.gov/publicAPI/v1/timeseries/data/

Run from the repository root:

    python data/us/build_inflation.py
"""

import csv
import datetime
import io
import json
import sys
import time
import urllib.request

from statistics import mean

OUTPUT_PATH  = 'data/us/inflation.csv'
BASE_YEAR    = 2000  # All series normalized to BASE_YEAR = 100
FRED_DELAY   = 1     # Seconds between FRED requests
BLS_DELAY    = 2     # Seconds between BLS API requests (stricter rate limit)
MIN_OVERLAP  = 5     # Minimum overlap years required for a backfill delta

HTTP_USER_AGENT = 'python-flint/1.0'

# FRED series: (fred_series_id, column_name)
# Monthly and quarterly series are automatically averaged to annual.
FRED_SERIES = [
  # BEA PCE chain-type price indexes (annual, 2017 = 100)
  ('DHLCRG3A086NBEA', 'PCE_Healthcare'),       # Health care services
  ('DHEDRG3A086NBEA', 'PCE_HigherEducation'),  # Higher education
  ('DFSARG3A086NBEA', 'PCE_FoodServices'),     # Food services & accommodations
  ('DGRDRG3A086NBEA', 'PCE_GroundTransport'),  # Ground transportation
  ('DTINRG3A086NBEA', 'PCE_VehicleInsurance'), # Motor vehicle & transport insurance
  ('DHUTRG3Q086SBEA', 'PCE_HousingUtils'),     # Housing & utilities (quarterly)

  # BLS CPI-U (monthly -> annual average, 1982-84 = 100)
  # We use not-seasonally-adjusted (CUUR) variants where they provide earlier start dates.
  # For annual averages, this makes no difference, since seasonal effects cancel out over a year.
  ('CPIAUCNS',         'CPI_All'),              # All items NSA; starts Jan 1913
  ('CUUR0000SAH1',     'CPI_Shelter'),          # Shelter; starts Dec 1952
  ('CUUR0000SEHA',     'CPI_Rent'),             # Rent of primary residence; starts Dec 1914
  ('CUUR0000SEHF01',   'CPI_Electricity'),      # Electricity; starts Dec 1913
  ('CUSR0000SEHF02',   'CPI_PipedGas'),         # Utility gas; starts Jan 1952
  ('CUSR0000SEHG',     'CPI_WaterSewer'),       # Water, sewer, trash; starts Dec 1997
  ('CUUR0000SAF11',    'CPI_FoodAtHome'),       # Food at home; starts Jan 1947
  ('CUUR0000SEFV',     'CPI_FoodAwayFromHome'), # Food away from home; starts Jan 1953
  ('CUUR0000SETB01',   'CPI_Gasoline'),         # Gasoline NSA; starts Mar 1935
  ('CUUR0000SETA01',   'CPI_NewVehicles'),      # New vehicles NSA; starts Mar 1947
  ('CUUR0000SETD',     'CPI_VehicleMaintenance'),  # Vehicle maintenance NSA; starts Mar 1947
  ('CPIMEDSL',         'CPI_MedicalCare'),      # Medical care (all); starts Jan 1947
  ('CUUR0000SAM2',     'CPI_MedicalServices'),  # Medical care services NSA; starts Mar 1935
  ('CUSR0000SEMD',     'CPI_HospitalServices'), # Hospital services; starts Jan 1978
  ('CUSR0000SEEB',     'CPI_TuitionChildcare'), # Tuition, school fees, childcare; starts Dec 1977
]

# BLS series not available on FRED - fetched directly from BLS API v1.
# (bls_series_id, column_name, first_year_available)
BLS_SERIES = [
  # CUUR0000SETE: Motor vehicle insurance (not seasonally adjusted)
  # Item code SETE, not SETG which is public transit.
  ('CUUR0000SETE',   'CPI_VehicleInsurance', 1996),
  # CUUR0000SEEB01: College tuition and fees (not seasonally adjusted)
  # SEEB01 = college only; SEEB02 = K-12 only; SEEB = combined w/ childcare.
  ('CUUR0000SEEB01', 'CPI_CollegeTuition',   1978),
]

# Column display order in output CSV
ALL_COLUMNS = [col for _, col in FRED_SERIES] + [col for _, col, _ in BLS_SERIES]

# Backfill chain: (shorter_series, reference_series).
# Each step extends shorter_series backward using reference_series.
# Earlier steps use the closest proxy; later steps fall back to CPI_All.
BACKFILL = [
  # PCE series (1929) -> extend to 1913 using CPI_All
  ('PCE_Healthcare',        'CPI_All'),
  ('PCE_HigherEducation',   'CPI_All'),
  ('PCE_FoodServices',      'CPI_All'),
  ('PCE_GroundTransport',   'CPI_All'),
  ('PCE_VehicleInsurance',  'CPI_All'),
  ('PCE_HousingUtils',      'CPI_All'),

  # CPI_Rent (1914) -> CPI_All (1913)
  ('CPI_Rent',              'CPI_All'),

  # CPI_Shelter (1952): step 1 = CPI_Rent (closest proxy), step 2 = CPI_All
  ('CPI_Shelter',           'CPI_Rent'),
  ('CPI_Shelter',           'CPI_All'),

  # CPI_PipedGas (1952) -> CPI_Electricity (same utility basket; starts 1913)
  ('CPI_PipedGas',          'CPI_Electricity'),

  # CPI_WaterSewer (~1997): step 1 = piped gas, step 2 = electricity
  ('CPI_WaterSewer',        'CPI_PipedGas'),
  ('CPI_WaterSewer',        'CPI_Electricity'),

  # CPI_FoodAtHome (1947) -> CPI_All
  ('CPI_FoodAtHome',        'CPI_All'),

  # CPI_FoodAwayFromHome (1953): step 1 = food at home, step 2 = CPI_All
  ('CPI_FoodAwayFromHome',  'CPI_FoodAtHome'),
  ('CPI_FoodAwayFromHome',  'CPI_All'),

  # CPI_Gasoline (1935) -> CPI_All
  ('CPI_Gasoline',          'CPI_All'),

  # CPI_VehicleMaintenance (1947) -> CPI_All
  ('CPI_VehicleMaintenance','CPI_All'),

  # CPI_NewVehicles (1947): step 1 = vehicle maintenance, step 2 = CPI_All
  ('CPI_NewVehicles',       'CPI_VehicleMaintenance'),
  ('CPI_NewVehicles',       'CPI_All'),

  # CPI_VehicleInsurance (~1996): step 1 = PCE version (1929), step 2 = CPI_All
  ('CPI_VehicleInsurance',  'PCE_VehicleInsurance'),
  ('CPI_VehicleInsurance',  'CPI_All'),

  # CPI_MedicalCare (1947): step 1 = PCE Healthcare (1929), step 2 = CPI_All
  ('CPI_MedicalCare',       'PCE_Healthcare'),
  ('CPI_MedicalCare',       'CPI_All'),

  # CPI_MedicalServices (1935): extend via CPI_MedicalCare chain
  ('CPI_MedicalServices',   'CPI_MedicalCare'),

  # CPI_HospitalServices (1978): extend via CPI_MedicalServices chain
  ('CPI_HospitalServices',  'CPI_MedicalServices'),

  # CPI_TuitionChildcare (1978): step 1 = PCE HigherEd (1929), step 2 = CPI_All
  ('CPI_TuitionChildcare',  'PCE_HigherEducation'),
  ('CPI_TuitionChildcare',  'CPI_All'),

  # CPI_CollegeTuition (1978): step 1 = PCE HigherEd (1929), step 2 = CPI_All
  ('CPI_CollegeTuition',    'PCE_HigherEducation'),
  ('CPI_CollegeTuition',    'CPI_All'),
]


def fetch_fred(series_id: str) -> dict[str, float]:
  """Download a FRED series as a date-string-to-value mapping.

  FRED CSV format:
      observation_date,<SERIES_ID>
      1947-01-01,21.480
      ...

  Args:
    series_id: The FRED series identifier (e.g. 'CPIAUCNS').

  Returns:
    Dict mapping ISO date strings (e.g. '1947-01-01') to float values.
    Returns an empty dict if the fetch fails.
  """
  url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
  time.sleep(FRED_DELAY)

  try:
    request = urllib.request.Request(url, headers={'User-Agent': HTTP_USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
      text = response.read().decode('utf-8')

    reader = csv.DictReader(io.StringIO(text))
    value_field = reader.fieldnames[1]  # Second column is named after the series ID
    return {
      row['observation_date']: float(row[value_field])
      for row in reader
      if row.get(value_field, '').strip() not in ('', '.')
    }
  except Exception as error:
    print(f'  WARNING: FRED fetch failed for {series_id}: {error}', file=sys.stderr)
    return {}


def fetch_bls(series_id: str, first_year: int) -> dict[str, float]:
  """Download a BLS series from the BLS Public Data API v1 (no registration).

  BLS API v1 limits to 10 years per request, so this loops in 10-year windows.

  Args:
    series_id: The BLS series identifier (e.g. 'CUUR0000SETE').
    first_year: The earliest year of available data for this series.

  Returns:
    Dict mapping ISO date strings (e.g. '1978-01-01') to float values, with one entry per month.
    Returns an empty dict on failure.
  """
  end_year = datetime.date.today().year
  raw: dict[str, float] = {}

  for start in range(first_year, end_year + 1, 10):
    stop = min(start + 9, end_year)

    payload = json.dumps({
      'seriesid': [series_id],
      'startyear': str(start),
      'endyear': str(stop),
    }).encode()

    url = 'https://api.bls.gov/publicAPI/v1/timeseries/data/'
    headers = {'Content-Type': 'application/json', 'User-Agent': HTTP_USER_AGENT}

    try:
      time.sleep(BLS_DELAY)
      request = urllib.request.Request(url, data=payload, headers=headers, method='POST')
      with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)

      if result.get('status') != 'REQUEST_SUCCEEDED':
        print(
          f'  WARNING: BLS API returned status '
          f'"{result.get("status")}" for {series_id} {start}-{stop}',
          file=sys.stderr,
        )
        continue

      for observation in result['Results']['series'][0]['data']:
        period = observation['period']
        if not period.startswith('M') or period == 'M13':
          continue  # Skip annual-average rows
        month = period[1:]  # 'M01' -> '01'
        date = f"{observation['year']}-{month}-01"
        try:
          raw[date] = float(observation['value'])
        except ValueError:
          pass
    except Exception as error:
      print(f'  WARNING: BLS API failed for {series_id} {start}-{stop}: {error}', file=sys.stderr)

  return raw


def to_annual(raw: dict[str, float]) -> dict[int, float]:
  """Average all FRED/BLS monthly or quarterly observations into annual values.

  Args:
    raw: Dict mapping ISO date strings to float values, as returned by fetch_fred() or fetch_bls().

  Returns:
    Dict mapping calendar years to the mean of all observations in that year.
  """
  by_year: dict[int, list[float]] = {}
  for date, value in raw.items():
    year = int(date[:4])
    by_year.setdefault(year, []).append(value)
  return {year: mean(values) for year, values in by_year.items()}


def normalize(series: dict[int, float], base_year: int) -> dict[int, float]:
  """Return a new series scaled so that series[base_year] == 100.

  Args:
    series: Dict mapping years to index values.
    base_year: The year to normalize to 100.
      If not present in series, falls back to the closest available year with a warning.

  Returns:
    A new dict with the same years, scaled so the base year equals 100.
  """
  if base_year not in series:
    # Fall back to the closest available year.
    closest = min(series, key=lambda year: abs(year - base_year))
    factor = 100.0 / series[closest]
    print(f'  NOTE: {base_year} not in series; normalizing to {closest} instead', file=sys.stderr)
  else:
    factor = 100.0 / series[base_year]
  return {year: value * factor for year, value in series.items()}


def backfill_series(
  primary: dict[int, float],
  reference: dict[int, float],
  min_overlap: int = MIN_OVERLAP,
) -> dict[int, float]:
  """Extend a primary series backward using a reference series, adjusted by mean rate spread.

  1. Compute year-over-year rates for both series in their overlap period.
  2. delta = mean(rate_primary - rate_reference) over the overlap.
  3. For each year before primary's start (working backward):
       synthetic_rate(year -> year+1) = rate_reference(year -> year+1) + delta
       primary[year] = primary[year+1] / (1 + synthetic_rate)

  Args:
    primary: The shorter series to extend, as a year-to-value dict.
    reference: The longer series to use as the backfill reference.
    min_overlap: Minimum number of overlapping years required to compute a meaningful delta.
      Steps with fewer overlap years are skipped.

  Returns:
    A new dict with the same entries as primary, plus synthetic values for years before primary's
    original start that are covered by reference. Returns primary unchanged if reference doesn't
    extend further back or there is insufficient overlap.
  """
  if not primary or not reference:
    return primary

  primary_start = min(primary)
  ref_start = min(reference)

  if ref_start >= primary_start:
    return primary  # Reference doesn't extend coverage further back

  overlap = [
    year for year in sorted(primary)
    if year - 1 in primary and year in reference and year - 1 in reference
  ]

  if len(overlap) < min_overlap:
    print(f'    WARNING: only {len(overlap)} overlap year(s) - skipping step', file=sys.stderr)
    return primary

  delta = mean(
    (primary[year] / primary[year - 1] - 1) - (reference[year] / reference[year - 1] - 1)
    for year in overlap
  )

  result = dict(primary)
  anchor = primary[primary_start]

  for year in range(primary_start - 1, ref_start - 1, -1):
    if year not in reference or year + 1 not in reference:
      break
    ref_rate = reference[year + 1] / reference[year] - 1
    synthetic_rate = ref_rate + delta
    result[year] = anchor / (1 + synthetic_rate)
    anchor = result[year]

  return result


def main() -> None:
  series: dict[str, dict[int, float]] = {}

  print('Fetching from FRED (fred.stlouisfed.org)…')
  for fred_id, col in FRED_SERIES:
    print(f'  {fred_id:30s} -> {col}')
    if raw := fetch_fred(fred_id):
      annual = to_annual(raw)
      series[col] = normalize(annual, BASE_YEAR)
      print(f'    {min(annual)}–{max(annual)}  ({len(annual)} years)')
    else:
      series[col] = {}

  print('\nFetching from BLS API (api.bls.gov)…')
  for bls_id, col, first_year in BLS_SERIES:
    print(f'  {bls_id:30s} -> {col}  (from {first_year})')
    if raw := fetch_bls(bls_id, first_year):
      annual = to_annual(raw)
      series[col] = normalize(annual, BASE_YEAR)
      print(f'    {min(annual)}–{max(annual)}  ({len(annual)} years)')
    else:
      series[col] = {}

  print('\nBackfilling…')
  for shorter, longer in BACKFILL:
    if not series.get(shorter) or not series.get(longer):
      continue
    original_start = min(series[shorter])
    series[shorter] = backfill_series(series[shorter], series[longer])
    new_start = min(series[shorter])
    if new_start < original_start:
      print(f'  {shorter:30s}  {original_start} -> {new_start}  (via {longer})')

  all_years = sorted({year for serie in series.values() for year in serie})
  if not all_years:
    print('\nERROR: no data fetched - nothing to write.', file=sys.stderr)
    sys.exit(1)

  print(f'\nWriting {OUTPUT_PATH}  ({all_years[0]}–{all_years[-1]})…')
  with open(OUTPUT_PATH, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Year'] + ALL_COLUMNS)
    for year in all_years:
      row = [year]
      for col in ALL_COLUMNS:
        val = series.get(col, {}).get(year)
        row.append(f'{val:.4f}' if val is not None else '')
      writer.writerow(row)

  print('\nColumn coverage after backfilling:')
  for col in ALL_COLUMNS:
    col_data = series.get(col, {})
    if col_data:
      print(f'  {col:30s}  {min(col_data)}–{max(col_data)}')
    else:
      print(f'  {col:30s}  (no data)')

  print('\nDone.')


if __name__ == '__main__':
  main()
