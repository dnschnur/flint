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

from collections import defaultdict
from assets import Assets, AssetCategory
from budget import Budget
from income import Income
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
  args = parser.parse_args()

  try:
    scenario = _load_scenario(args.scenario)
  except FileNotFoundError as e:
    parser.error(str(e))

  base_year = scenario.get('year', 2025)

  age = scenario.get('age')
  if age is None:
    parser.error('Scenario is missing required field: age')

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
    current_age=age,
    data_year=base_year,
    sp500_path='data/sp500.csv',
    simulation_min_year=args.sp500_start,
    simulation_max_year=args.sp500_end
  )

  default_retirement_age = scenario.get('retirement_age', age + 15)
  default_end_age = scenario.get('retirement_end', age + 45)

  default_start = base_year + (default_retirement_age - age)
  default_end = base_year + (default_end_age - age)

  def run_simulation(start_year: int, end_year: int) -> dict | None:
    """Run a full simulation and return the server data dict, or None if no results."""
    years_until_retirement = start_year - base_year
    retirement_age = age + years_until_retirement

    years_until_end = end_year - base_year
    end_age = age + years_until_end

    starting_assets = None
    pre_retirement_history = []
    for year, snapshot in sim.project_pre_retirement(start_year):
      pre_retirement_history.append({
        'year': year + 1,
        'assets': {
          category.display_name: round(value)
          for category, value in snapshot.items()
          if value
        },
      })
      starting_assets = snapshot

    if starting_assets is None:
      current = defaultdict(float)
      for category in AssetCategory:
        value = sim.assets.get_category(category, base_year)
        if value:
          current[category] = value
      starting_assets = current

    starting_total = sum(starting_assets.values())

    results = list(sim.run(start_year, end_year, starting_assets=starting_assets))

    if not results:
      return None

    totals = [sum(result.assets.values()) for result in results]

    median_total = statistics.median(totals)

    return {
      'retirement': {
        'start_year': start_year,
        'end_year': end_year,
        'retirement_age': retirement_age,
        'end_age': end_age,
      },
      'scenario': {
        'base_year': base_year,
        'age': age,
        'default_retirement_age': default_retirement_age,
        'default_end_age': default_end_age,
      },
      'starting_total': starting_total,
      'pre_retirement_history': pre_retirement_history,
      'stats': {
        'min': min(totals),
        'max': max(totals),
        'median': median_total,
      },
      'results': [
          {'start_year': result.start_year, 'total': totals[index], 'history': result.history}
          for index, result in enumerate(results)
      ],
    }

  initial_data = run_simulation(default_start, default_end)
  if initial_data is None:
    print('No simulation results. Check retirement_start and retirement_end in your scenario.')
    return

  banner.print_banner(args.port)
  server.serve(initial_data, run_simulation, port=args.port)


if __name__ == '__main__':
  main()
