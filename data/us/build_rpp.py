"""Builds the data/us/rpp.csv Regional Price Parities (RPPs) by state dataset.

Data source:
  - BEA Regional Price Parities (SARPP):
    https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area
    Bulk ZIP download (no registration): https://apps.bea.gov/regional/zip/SARPP.zip

Run from the repository root:

    python data/us/build_rpp.py
"""

import csv
import io
import sys
import urllib.request
import zipfile

OUTPUT_PATH = 'data/us/rpp.csv'
ZIP_URL = 'https://apps.bea.gov/regional/zip/SARPP.zip'

# Output column name for each BEA line code.
# The BEA publishes five RPP components; we preserve all five.
CATEGORIES = {
  '1': 'All_Items',
  '2': 'Goods',
  '3': 'Services_Housing',
  '4': 'Services_Utilities',
  '5': 'Services_Other',
}

# BEA state name → ISO 3166-2 two-letter code.
STATE_CODES = {
  'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
  'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
  'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI',
  'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
  'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME',
  'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN',
  'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE',
  'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
  'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH',
  'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI',
  'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX',
  'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
  'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY',
}


def fetch_sarpp_csv() -> str:
  """Download SARPP.zip from BEA and return the state RPP CSV text.

  Returns:
    Text content of the SARPP_STATE_*.csv file inside the archive.

  Raises:
    RuntimeError: If no state CSV is found inside the ZIP.
  """
  print(f'Downloading {ZIP_URL}...')
  request = urllib.request.Request(ZIP_URL, headers={'User-Agent': 'python-flint/1.0'})
  with urllib.request.urlopen(request, timeout=60) as response:
    zip_bytes = response.read()

  with zipfile.ZipFile(io.BytesIO(zip_bytes)) as f:
    csv_names = sorted(
      name for name in f.namelist()
      if name.upper().startswith('SARPP_STATE') and name.upper().endswith('.CSV')
    )
    if not csv_names:
      raise RuntimeError(f'No SARPP_STATE*.csv found in ZIP. Contents: {f.namelist()}')
    csv_name = csv_names[-1]  # Most recent if multiple
    print(f'Extracting {csv_name}...')
    return f.read(csv_name).decode('utf-8-sig')  # utf-8-sig strips any BOM


def parse_sarpp(text: str) -> dict[tuple[str, str], dict[str, float]]:
  """Parse the SARPP state CSV into {(geo_name, line_code): {year: value}}.

  BEA bulk-download CSV format:
    Row 0:   header - GeoFIPS, GeoName, Region, TableName, LineCode, ..., 2008, ..., 2024
    Rows 1+: data - one row per (state, line code); GeoFIPS has a leading space
    Last 3:  footnote rows (single-field strings); ignored

  Uses csv.reader with column-index addressing to avoid ambiguity from footnote rows that have
  fewer fields than the header.

  Args:
    text: Raw CSV text from the SARPP ZIP archive.

  Returns:
    Nested dict mapping (geo_name, line_code) to a year-to-RPP-value dict.
    geo_name values are as provided by BEA (e.g. 'California', 'United States').
    line_code strings match the keys in CATEGORIES.
  """
  reader = csv.reader(io.StringIO(text))
  rows = list(reader)
  if not rows:
    raise RuntimeError('SARPP CSV is empty')

  header = rows[0]
  try:
    geo_name_idx  = header.index('GeoName')
    line_code_idx = header.index('LineCode')
  except ValueError as error:
    raise RuntimeError(f'Expected column not found in SARPP header: {error}') from error

  # Year columns: 4-digit numeric strings in the header.
  year_indices = [(i, col) for i, col in enumerate(header) if col.isdigit() and len(col) == 4]

  result: dict[tuple[str, str], dict[str, float]] = {}
  for row in rows[1:]:
    # Skip footnote / short rows (e.g. "Last updated: ...")
    if len(row) <= line_code_idx:
      continue
    geo_name  = row[geo_name_idx].strip()
    line_code = row[line_code_idx].strip()
    if not geo_name or not line_code:
      continue

    year_values: dict[str, float] = {}
    for index, year in year_indices:
      raw = row[index].strip().replace(',', '') if index < len(row) else ''
      if raw and raw not in ('(NA)', 'NA', '(D)', '(L)', '.', ''):
        try:
          year_values[year] = float(raw)
        except ValueError:
          pass

    if year_values:
      result[(geo_name, line_code)] = year_values

  return result


def main() -> None:
  csv_text = fetch_sarpp_csv()

  print('Parsing...')
  raw = parse_sarpp(csv_text)
  if not raw:
    print('ERROR: no data parsed from CSV', file=sys.stderr)
    sys.exit(1)

  # Collect all years covered by the five category columns.
  all_years = sorted({
    year
    for (_, line_code), year_vals in raw.items()
    for year in year_vals
    if line_code in CATEGORIES
  })

  # All regions except the US national aggregate (which is always 0 by definition).
  all_regions = sorted({
    region for (region, line_code) in raw
    if line_code in CATEGORIES and region != 'United States'
  })

  print(f'\nYears: {all_years[0]}–{all_years[-1]}')
  print(f'States/territories: {len(all_regions)}')

  # Build output rows: one per (region, year).
  # Each category value is the deviation from the national average: RPP - 100.
  columns = ['Year', 'State'] + list(CATEGORIES.values())
  rows = []
  skipped = []

  for region in all_regions:
    state_code = STATE_CODES.get(region)
    if state_code is None:
      skipped.append(region)
      continue
    for year in all_years:
      row: dict[str, object] = {'Year': year, 'State': state_code}
      for line_code, col_name in CATEGORIES.items():
        val = raw.get((region, line_code), {}).get(year)
        row[col_name] = f'{val - 100:.2f}' if val is not None else ''
      rows.append(row)

  if skipped:
    print(f'\n  NOTE: skipped {len(skipped)} unrecognized region(s): {skipped}', file=sys.stderr)

  print(f'\nWriting {OUTPUT_PATH}  ({len(rows)} rows)...')
  with open(OUTPUT_PATH, 'w', newline='') as output_file:
    writer = csv.DictWriter(output_file, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)

  # Sanity-check sample: latest year, spread of states
  print('\nSample (latest year, selected states):')
  latest_year = all_years[-1]
  sample = {'CA', 'TX', 'NY', 'FL', 'MS', 'WV'}
  header = f'  {"State":<6} ' + '  '.join(f'{col:>20}' for col in CATEGORIES.values())
  print(header)
  for row in rows:
    if row['Year'] == latest_year and row['State'] in sample:
      vals = '  '.join(f'{row[col]:>20}' for col in CATEGORIES.values())
      print(f'  {row["State"]:<6} {vals}')

  print('\nDone.')


if __name__ == '__main__':
  main()
