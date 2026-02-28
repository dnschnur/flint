"""Flint - Retirement simulator.

Using starting assets and a budget, runs a Monte Carlo simulation of how those assets change during
retirement, using historical S&P 500 data.
"""

import argparse
import os
import statistics
import tomllib

import banner
import server

from assets import Assets, AssetCategory
from budget import Budget
from income import Income
from output import print_assets_table, print_median_scenario_table, print_min_scenario_table, print_outcome_table, print_stats_table
from rmd import RMD
from simulation import Simulation
from tax import Tax


def _load_scenario(name: str) -> dict:
  """Load a scenario from scenarios/<name>.toml.

  Args:
    name: The scenario name (without .toml extension).

  Returns:
    Dict of key-value pairs from the TOML file.

  Raises:
    FileNotFoundError: If the scenario file does not exist.
  """
  path = os.path.join('scenarios', f'{name}.toml')
  if not os.path.exists(path):
    raise FileNotFoundError(f'Scenario "{name}" not found: {path}')
  with open(path, 'rb') as f:
    return tomllib.load(f)


def _resolve_tax_paths(country: str, state: str | None) -> tuple[str, str, str | None]:
  """Resolve the paths to tax CSV files for a given country and optional state.

  Files are read from data/tax/{country}/: income.csv and capital_gains.csv for federal taxes,
  and income_{state}.csv for state income tax when a state is given.

  Args:
    country: ISO country code in lowercase (e.g. 'us').
    state: Two-letter state code in lowercase (e.g. 'ca'), or None.

  Returns:
    A (income_tax_path, capital_gains_path, state_income_tax_path) tuple.

  Raises:
    FileNotFoundError: If a state is given but no matching state tax file exists.
  """
  base = os.path.join('data', 'tax', country)
  state_path = None
  if state:
    state_path = os.path.join(base, f'income_{state}.csv')
    if not os.path.exists(state_path):
      raise FileNotFoundError(f'State tax file not found: {state_path}')

  return os.path.join(base, 'income.csv'), os.path.join(base, 'capital_gains.csv'), state_path


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
    default='default',
    help='Scenario name: reads from scenarios/<name>.toml (default: "default")'
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
    '--port',
    type=int,
    default=8080,
    help='Port for the results web server (default: 8080)'
  )
  parser.add_argument(
    '--verbose',
    action='store_true',
    help='Print asset breakdown for each pre-retirement year'
  )

  args = parser.parse_args()

  try:
    scenario = _load_scenario(args.scenario)
  except FileNotFoundError as e:
    parser.error(str(e))

  base_year = scenario.get('year', 2025)

  country = scenario.get('country', 'us')
  state = scenario.get('state')
  if state:
    state = state.lower()

  try:
    income_path, cg_path, state_path = _resolve_tax_paths(country, state)
  except FileNotFoundError as e:
    parser.error(str(e))

  assets = Assets(base_year, scenario.get('assets', {}))
  budget = Budget(base_year, scenario.get('budget', {}))
  income = Income(base_year, scenario.get('income', {}))
  rmd = RMD('data/rmd.csv')
  tax = Tax(income_path, cg_path, state_path, data_year=base_year)

  sim = Simulation(
    assets=assets,
    budget=budget,
    income=income,
    rmd=rmd,
    tax=tax,
    current_age=args.age,
    data_year=base_year,
    sp500_path='data/sp500.csv',
    simulation_min_year=args.sp500_start,
    simulation_max_year=args.sp500_end
  )

  starting_assets = None
  for year, assets_snapshot in sim.project_pre_retirement(args.start_year):
    if args.verbose:
      age = args.age + (year + 1 - base_year)
      print_assets_table(f'Pre-Retirement: Year {year + 1} (Age {age})', assets_snapshot)
    starting_assets = assets_snapshot
  starting_total = sum(starting_assets.values())

  results = list(sim.run(args.start_year, args.end_year, starting_assets=starting_assets))

  if not results:
    print('No simulation results generated. Check your date ranges.')
    return

  years_until_retirement = args.start_year - base_year
  retirement_age = args.age + years_until_retirement

  years_until_end = args.end_year - base_year
  end_age = args.age + years_until_end

  totals = [sum(result.assets.values()) for result in results]

  min_total = min(totals)
  max_total = max(totals)
  median_total = statistics.median(totals)

  # Find the minimum and median simulation results
  sorted_indices = sorted(range(len(totals)), key=lambda i: totals[i])
  min_result = results[sorted_indices[0]]
  median_result = results[sorted_indices[len(totals) // 2]]

  print('=' * 60)
  print(f'Retirement: Age {retirement_age} (year {args.start_year}) to age {end_age} (year {args.end_year})')
  print(f'Simulations run: {len(results)}')
  print()

  print_assets_table(f'Starting Assets in {args.start_year}', starting_assets)
  print_stats_table(min_total, max_total, median_total)
  print_min_scenario_table(min_result, args.end_year, args.start_year)
  print_median_scenario_table(median_result, args.end_year, args.start_year)
  print_outcome_table(len(results), starting_total, totals)

  server_data = {
    'retirement': {
      'start_year': args.start_year,
      'end_year': args.end_year,
      'retirement_age': retirement_age,
      'end_age': end_age,
    },
    'starting_total': starting_total,
    'stats': {
      'min': min_total,
      'max': max_total,
      'median': median_total,
    },
    'results': [
        {'start_year': result.start_year, 'total': totals[index]}
        for index, result in enumerate(results)
    ],
  }

  banner.print_banner(args.port)
  server.serve(server_data, port=args.port)


if __name__ == '__main__':
  main()
