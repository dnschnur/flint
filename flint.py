"""Flint - Retirement simulator.

Using starting assets and a budget, runs a Monte Carlo simulation of how those assets change during
retirement, using historical S&P 500 data.
"""

import argparse
import os
import statistics

from datetime import datetime

from assets import Assets, AssetCategory
from budget import Budget
from income import Income
from rmd import RMD
from simulation import Simulation


def _resolve_data_paths(scenario: str | None) -> tuple[str, str, str]:
  """Resolve the paths to assets, budget, and income CSV files.

  If a scenario name is provided, the files are read from data/<scenario>/, otherwise from data/.

  Args:
    scenario: Name of the scenario subdirectory under data/, or None.

  Returns:
    A tuple of (assets_path, budget_path, income_path).

  Raises:
    FileNotFoundError: If any required files are missing from the scenario directory.
  """
  if scenario:
    directory = os.path.join('data', scenario)
    paths = (
      os.path.join(directory, 'assets.csv'),
      os.path.join(directory, 'budget.csv'),
      os.path.join(directory, 'income.csv'),
    )

    missing = [path for path in paths if not os.path.exists(path)]
    if missing:
      raise FileNotFoundError(
        f'Scenario "{scenario}" is missing required files: {", ".join(missing)}'
      )

    return paths

  return 'data/assets.csv', 'data/budget.csv', 'data/income.csv'


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

  args = parser.parse_args()

  try:
    assets_path, budget_path, income_path = _resolve_data_paths(args.scenario)
  except FileNotFoundError as e:
    parser.error(str(e))

  assets = Assets(assets_path)
  budget = Budget(budget_path)
  income = Income(income_path)
  rmd = RMD('data/rmd.csv')

  current_age = args.age
  current_year = datetime.now().year
  data_year = max(
    assets._last_historical_year or current_year,
    budget._last_historical_year or current_year,
    income._last_historical_year or current_year
  )

  sim = Simulation(
    assets=assets,
    budget=budget,
    income=income,
    rmd=rmd,
    current_age=current_age,
    data_year=data_year,
    sp500_path='data/sp500.csv',
    simulation_min_year=args.sp500_start,
    simulation_max_year=args.sp500_end
  )

  starting_assets = sim.project_pre_retirement(args.start_year)
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
  median_historical_end = median_result.start_year + (args.end_year - args.start_year)

  # Calculate the distribution of outcomes
  bankrupt_count = sum(1 for total in totals if total < 0)
  low_count = sum(1 for total in totals if 0 <= total < starting_total * 0.5)
  high_count = sum(1 for total in totals if total > starting_total * 2)

  bankrupt_pct = (bankrupt_count / len(totals)) * 100
  low_pct = (low_count / len(totals)) * 100
  high_pct = (high_count / len(totals)) * 100

  print('=' * 60)
  print(f'Retirement: Age {retirement_age} (year {args.start_year}) to age {end_age} (year {args.end_year})')
  print(f'Simulations run: {len(results)}')
  print()

  print(f'Starting Assets in {args.start_year}')
  print('-' * 60)
  print(f'{"Category":<30} {'Value':>29}')
  print('-' * 60)
  for category in AssetCategory:
    if starting_assets[category]:
      print(f'{category.display_name:<30} {starting_assets[category]:>29,.0f}')
  print('-' * 60)
  print(f'{"TOTAL":<30} {starting_total:>29,.0f}')
  print()

  print('Overall Statistics')
  print('-' * 60)
  print(f'{"Metric":<30} {"Value":>29}')
  print('-' * 60)
  print(f'{"Minimum Total Assets":<30} {min_total:>29,.0f}')
  print(f'{"Maximum Total Assets":<30} {max_total:>29,.0f}')
  print(f'{"Median Total Assets":<30} {median_total:>29,.0f}')
  print()

  print(f'Median Scenario - Asset Breakdown ({median_result.start_year}–{median_historical_end})')
  print('-' * 60)
  print(f'{"Category":<30} {"Value":>29}')
  print('-' * 60)
  for category in AssetCategory:
    if value := median_result.assets[category]:
      print(f'{category.display_name:<30} {value:>29,.0f}')
  print('-' * 60)
  print(f'{"TOTAL":<30} {median_total:>29,.0f}')
  print()

  print('Outcome Distribution')
  print('-' * 60)
  print(f'{"Outcome":<30} {"Percentage":>29}')
  print('-' * 60)
  print(f'{"Bankrupt":<30} {bankrupt_pct:>28.1f}%')
  print(f'{"Low  (< 50% of start)":<30} {low_pct:>28.1f}%')
  print(f'{"High (> 200% of start)":<30} {high_pct:>28.1f}%')
  print()


if __name__ == '__main__':
  main()
