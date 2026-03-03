"""Flint - Retirement simulator.

Using starting assets and a budget, runs a Monte Carlo simulation of how those assets change during
retirement, using historical S&P 500 data.
"""

import argparse
import os
import statistics
import sys
import tomllib

from collections import defaultdict

import banner
import server

from assets import Assets, AssetCategory
from budget import Budget
from income import Income
from inflation import Inflation
from rmd import RMD
from server import SimulationData
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
    try:
      return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
      raise ValueError(f'Scenario "{name}" has a TOML syntax error: {e}') from e


def _resolve_tax_paths(country: str, state: str | None) -> tuple[str, str, str | None]:
  """Resolve the paths to tax CSV files for a given country and optional state.

  Files are read from data/{country}/: income_tax.csv and capital_gains_tax.csv for federal
  taxes, and {state}/income_tax.csv for state income tax when a state is given.

  Args:
    country: ISO country code in lowercase (e.g. 'us').
    state: Two-letter state code in lowercase (e.g. 'ca'), or None.

  Returns:
    A (income_tax_path, capital_gains_path, state_income_tax_path) tuple.

  Raises:
    FileNotFoundError: If a state is given but no matching state tax file exists.
  """
  base = os.path.join('data', country)
  state_path = None
  if state:
    state_path = os.path.join(base, state, 'income_tax.csv')
    if not os.path.exists(state_path):
      raise FileNotFoundError(f'State tax file not found: {state_path}')

  return os.path.join(base, 'income_tax.csv'), os.path.join(base, 'capital_gains_tax.csv'), state_path


def _init_scenario(name: str, sp500_start: int | None, sp500_end: int | None) -> dict:
  """Load a scenario by name and initialize all simulation objects.

  Args:
    name: Scenario name (without .toml extension).
    sp500_start: Minimum year for S&P 500 data, or None for earliest available.
    sp500_end: Maximum year for S&P 500 data, or None for latest available.

  Returns:
    A context dict with keys: name, sim, base_year, age,
    default_retirement_age, default_end_age.

  Raises:
    FileNotFoundError: If the scenario file does not exist.
    ValueError: If the scenario is missing a required field.
  """
  scenario = _load_scenario(name)

  base_year = scenario.get('year', 2025)

  age = scenario.get('age')
  if age is None:
    raise ValueError(f'Scenario "{name}" is missing required field: age')

  country = scenario.get('country', 'us')
  state = scenario.get('state')
  if state:
    state = state.lower()

  income_path, cg_path, state_path = _resolve_tax_paths(country, state)

  inflation = None
  inflation_path = os.path.join('data', country, 'inflation.csv')
  if os.path.exists(inflation_path):
    inflation = Inflation(inflation_path)

  assets = Assets(base_year, scenario.get('assets', {}))
  budget = Budget(base_year, scenario.get('budget', {}), inflation)
  income = Income(base_year, scenario.get('income', {}))
  rmd = RMD('data/us/rmd.csv')
  tax = Tax(income_path, cg_path, state_path, data_year=base_year)

  sim = Simulation(
    assets=assets,
    budget=budget,
    income=income,
    rmd=rmd,
    tax=tax,
    current_age=age,
    data_year=base_year,
    sp500_path='data/us/sp500.csv',
    simulation_min_year=sp500_start,
    simulation_max_year=sp500_end,
    inflation=inflation,
  )

  return {
    'name': name,
    'sim': sim,
    'base_year': base_year,
    'age': age,
    'default_retirement_age': scenario.get('retirement_age', 65),
    'default_end_age': scenario.get('retirement_end', 90),
  }


def main():
  parser = argparse.ArgumentParser(
    description='Run retirement simulations using historical S&P 500 data'
  )
  parser.add_argument(
    '--scenario',
    type=str,
    default=None,
    help='Scenario name: reads from scenarios/<name>.toml (default: first non-default scenario)'
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

  available_scenarios = sorted(
    os.path.splitext(path)[0]
    for path in os.listdir('scenarios')
    if path.endswith('.toml')
  )

  # Use the given --scenario, or default to the first non-default one alphabetically.
  initial_scenario = args.scenario
  if not initial_scenario:
    initial_scenario = next((name for name in available_scenarios if name != 'default'), 'default')

  if initial_scenario not in available_scenarios:
    parser.error(f'Scenario not found: "{initial_scenario}"')

  def run_simulation(scenario_name: str, start_year: int | None = None, end_year: int | None = None) -> SimulationData | None:
    """Run a full simulation and return the server data dict, or None if no results."""
    try:
      ctx = _init_scenario(scenario_name, args.sp500_start, args.sp500_end)
    except (FileNotFoundError, ValueError) as e:
      print(f'Error loading scenario "{scenario_name}": {e}', file=sys.stderr)
      return None

    sim = ctx['sim']
    base_year = ctx['base_year']
    age = ctx['age']
    default_retirement_age = ctx['default_retirement_age']
    default_end_age = ctx['default_end_age']

    if start_year is None:
      start_year = base_year + (default_retirement_age - age)
    if end_year is None:
      end_year = base_year + (default_end_age - age)

    retirement_age = age + (start_year - base_year)
    end_age = age + (end_year - base_year)

    starting_assets = None
    pre_retirement_history = []
    for year, assets_snapshot, budget_snapshot in sim.project_pre_retirement(start_year):
      pre_retirement_history.append({
        'year': year + 1,
        'assets': {
          category.display_name: round(value)
          for category, value in assets_snapshot.items()
          if value
        },
        'budget': {
          category.display_name: round(amount)
          for category, amount in budget_snapshot.items()
          if amount
        },
      })
      starting_assets = assets_snapshot

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
        'name': scenario_name,
        'scenarios': available_scenarios,
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

  initial_data = run_simulation(initial_scenario)
  if initial_data is None:
    print('No simulation results. Check retirement_age and retirement_end in your scenario.')
    return

  banner.print_banner(args.port)
  server.serve(initial_data, run_simulation, available_scenarios, port=args.port)


if __name__ == '__main__':
  main()
