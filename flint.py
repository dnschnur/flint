"""Flint - Retirement simulator.

Using starting assets and a budget, runs a Monte Carlo simulation of how those assets change during
retirement, using historical S&P 500 data.
"""

import argparse
import os
import statistics
import tomllib

from datetime import datetime

from assets import Assets, AssetCategory
from budget import Budget
from income import Income
from output import print_assets_table, print_median_scenario_table, print_outcome_table, print_stats_table
from rmd import RMD
from simulation import Simulation
from tax import Tax
from util import DataPaths


def _load_scenario_info(directory: str) -> dict:
  """Load optional scenario metadata from info.toml.

  Args:
    directory: Path to the scenario directory.

  Returns:
    Dict of key-value pairs from the TOML file, or empty dict if the file doesn't exist.
  """
  path = os.path.join(directory, 'info.toml')
  if not os.path.exists(path):
    return {}
  with open(path, 'rb') as f:
    return tomllib.load(f)


def _resolve_data_paths(scenario: str | None, state: str | None) -> DataPaths:
  """Resolve the paths to assets, budget, income, tax, and optional state tax CSV files.

  Required files (assets, budget, income) are read from data/<scenario>/ when a scenario is
  given, with a hard error if any are missing. Tax files (income_tax, capital_gains_tax) are
  optional per-scenario: the scenario's copy is used if present, otherwise data/ defaults.

  When a state is given, income_tax_{state}.csv is resolved the same way: the scenario's copy
  is used if present, otherwise the data/ copy. A hard error is raised if no copy exists.

  Args:
    scenario: Name of the scenario subdirectory under data/, or None.
    state: Two-letter state code (e.g. 'ca'), or None.

  Returns:
    A DataPaths with all resolved file paths.

  Raises:
    FileNotFoundError: If any required files are missing from the scenario directory, or if a
        state is given but no matching income_tax_{state}.csv file exists.
  """
  if scenario:
    directory = os.path.join('data', scenario)
    required = [
      os.path.join(directory, 'assets.csv'),
      os.path.join(directory, 'budget.csv'),
      os.path.join(directory, 'income.csv'),
    ]

    missing = [path for path in required if not os.path.exists(path)]
    if missing:
      raise FileNotFoundError(
        f'Scenario "{scenario}" is missing required files: {", ".join(missing)}'
      )

    def _scenario_or_default(filename):
      scenario_path = os.path.join(directory, filename)
      return scenario_path if os.path.exists(scenario_path) else os.path.join('data', filename)

    state_path = None
    if state:
      state_path = _scenario_or_default(f'income_tax_{state}.csv')
      if not os.path.exists(state_path):
        raise FileNotFoundError(f'State tax file not found: {state_path}')

    return DataPaths(
      assets=required[0],
      budget=required[1],
      income=required[2],
      income_tax=_scenario_or_default('income_tax.csv'),
      capital_gains_tax=_scenario_or_default('capital_gains_tax.csv'),
      state_income_tax=state_path,
    )

  state_path = None
  if state:
    state_path = os.path.join('data', f'income_tax_{state}.csv')
    if not os.path.exists(state_path):
      raise FileNotFoundError(f'State tax file not found: {state_path}')

  return DataPaths(
    assets='data/assets.csv',
    budget='data/budget.csv',
    income='data/income.csv',
    income_tax='data/income_tax.csv',
    capital_gains_tax='data/capital_gains_tax.csv',
    state_income_tax=state_path,
  )


def main():
  parser = argparse.ArgumentParser(
    description='Run retirement simulations using historical S&P 500 data'
  )
  parser.add_argument(
    'start_year',
    type=int,
    help='Retirement year (when job income stops)'
  )
  parser.add_argument(
    'end_year',
    type=int,
    help='Last year of retirement (inclusive)'
  )
  parser.add_argument(
    'age',
    type=int,
    help='Current age'
  )
  parser.add_argument(
    '--scenario',
    type=str,
    default=None,
    help='Scenario: reads assets, budget, and income from data/<scenario>/ rather than data/'
  )
  parser.add_argument(
    '--state',
    type=str,
    default=None,
    metavar='CODE',
    help='State income tax: two-letter state code (e.g. ca). Loads income_tax_{code}.csv and '
         'combines with federal tax. Checks the scenario directory first, then data/.'
  )
  parser.add_argument(
    '--sp500-start',
    type=int,
    default=None,
    help='Minimum year for S&P 500 historical data (default: earliest available)'
  )
  parser.add_argument(
    '--sp500-end',
    type=int,
    default=None,
    help='Maximum year for S&P 500 historical data (default: latest available)'
  )
  parser.add_argument(
    '--verbose',
    action='store_true',
    help='Print asset breakdown for each pre-retirement year'
  )

  args = parser.parse_args()

  scenario = _load_scenario_info(os.path.join('data', args.scenario)) if args.scenario else {}

  state = args.state or scenario.get('state')
  if state:
    state = state.lower()

  try:
    paths = _resolve_data_paths(args.scenario, state)
  except FileNotFoundError as e:
    parser.error(str(e))

  assets = Assets(paths.assets)
  budget = Budget(paths.budget)
  income = Income(paths.income)
  rmd = RMD('data/rmd.csv')

  current_age = args.age
  current_year = datetime.now().year
  data_year = max(
    assets._last_historical_year or current_year,
    budget._last_historical_year or current_year,
    income._last_historical_year or current_year
  )

  tax = Tax(paths, data_year=data_year)

  sim = Simulation(
    assets=assets,
    budget=budget,
    income=income,
    rmd=rmd,
    tax=tax,
    current_age=current_age,
    data_year=data_year,
    sp500_path='data/sp500.csv',
    simulation_min_year=args.sp500_start,
    simulation_max_year=args.sp500_end
  )

  starting_assets = None
  for year, assets_snapshot in sim.project_pre_retirement(args.start_year):
    if args.verbose:
      age = args.age + (year + 1 - data_year)
      print_assets_table(f'Pre-Retirement: Year {year + 1} (Age {age})', assets_snapshot)
    starting_assets = assets_snapshot
  starting_total = sum(starting_assets.values())

  results = list(sim.run(args.start_year, args.end_year, starting_assets=starting_assets))

  if not results:
    print('No simulation results generated. Check your date ranges.')
    return

  years_until_retirement = args.start_year - data_year
  retirement_age = args.age + years_until_retirement

  years_until_end = args.end_year - data_year
  end_age = args.age + years_until_end

  totals = [sum(result.assets.values()) for result in results]

  min_total = min(totals)
  max_total = max(totals)
  median_total = statistics.median(totals)

  # Find the median simulation result
  median_idx = sorted(range(len(totals)), key=lambda i: totals[i])[len(totals) // 2]
  median_result = results[median_idx]

  print('=' * 60)
  print(f'Retirement: Age {retirement_age} (year {args.start_year}) to age {end_age} (year {args.end_year})')
  print(f'Simulations run: {len(results)}')
  print()

  print_assets_table(f'Starting Assets in {args.start_year}', starting_assets)
  print_stats_table(min_total, max_total, median_total)
  print_median_scenario_table(median_result, args.end_year, args.start_year)
  print_outcome_table(len(results), starting_total, totals)


if __name__ == '__main__':
  main()
