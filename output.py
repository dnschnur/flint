"""Output formatting helpers for Flint simulation results."""

from assets import AssetCategory
from simulation import SimulationResult

_COL_WIDTH = 60
_LABEL_WIDTH = 30
_VALUE_WIDTH = _COL_WIDTH - _LABEL_WIDTH


def print_assets_table(title: str, assets: dict[AssetCategory, float]) -> None:
  """Print a table of asset values by category with a total row.

  Args:
    title: Header line printed above the table.
    assets: Asset values by category; zero-valued categories are omitted.
  """
  total = sum(assets.values())
  print(title)
  print('-' * _COL_WIDTH)
  print(f'{"Category":<{_LABEL_WIDTH}}{"Value":>{_VALUE_WIDTH}}')
  print('-' * _COL_WIDTH)
  for category in AssetCategory:
    if assets[category]:
      print(f'{category.display_name:<{_LABEL_WIDTH}}{assets[category]:>{_VALUE_WIDTH},.0f}')
  print('-' * _COL_WIDTH)
  print(f'{"TOTAL":<{_LABEL_WIDTH}}{total:>{_VALUE_WIDTH},.0f}')
  print()


def print_stats_table(
  min_total: float,
  max_total: float,
  median_total: float
) -> None:
  """Print the overall simulation statistics table.

  Args:
    min_total: Minimum total assets across all simulations.
    max_total: Maximum total assets across all simulations.
    median_total: Median total assets across all simulations.
  """
  print('Overall Statistics')
  print('-' * _COL_WIDTH)
  print(f'{"Metric":<{_LABEL_WIDTH}}{"Value":>{_VALUE_WIDTH}}')
  print('-' * _COL_WIDTH)
  print(f'{"Minimum Total Assets":<{_LABEL_WIDTH}}{min_total:>{_VALUE_WIDTH},.0f}')
  print(f'{"Maximum Total Assets":<{_LABEL_WIDTH}}{max_total:>{_VALUE_WIDTH},.0f}')
  print(f'{"Median Total Assets":<{_LABEL_WIDTH}}{median_total:>{_VALUE_WIDTH},.0f}')
  print()


def print_median_scenario_table(
  median_result: SimulationResult,
  end_year: int,
  start_year: int
) -> None:
  """Print the median scenario asset breakdown table.

  Args:
    median_result: The simulation result closest to the median outcome.
    end_year: The retirement end year (used to compute the historical end year).
    start_year: The retirement start year (used to compute the historical end year).
  """
  historical_end = median_result.start_year + (end_year - start_year)
  print_assets_table(
    f'Median Scenario - Asset Breakdown ({median_result.start_year}\u2013{historical_end})',
    median_result.assets
  )


def print_outcome_table(
  results_count: int,
  starting_total: float,
  totals: list[float]
) -> None:
  """Print the outcome distribution table.

  Args:
    results_count: Total number of simulation runs.
    starting_total: Total assets at the start of retirement.
    totals: List of final total assets for each simulation run.
  """
  bankrupt_count = sum(1 for total in totals if total < 0)
  low_count = sum(1 for total in totals if 0 <= total < starting_total * 0.5)
  high_count = sum(1 for total in totals if total > starting_total * 2)

  bankrupt_pct = (bankrupt_count / results_count) * 100
  low_pct = (low_count / results_count) * 100
  high_pct = (high_count / results_count) * 100

  print('Outcome Distribution')
  print('-' * _COL_WIDTH)
  print(f'{"Outcome":<{_LABEL_WIDTH}}{"Percentage":>{_VALUE_WIDTH}}')
  print('-' * _COL_WIDTH)
  print(f'{"Bankrupt":<{_LABEL_WIDTH}}{bankrupt_pct:>{_VALUE_WIDTH - 1}.1f}%')
  print(f'{"Low  (< 50% of start)":<{_LABEL_WIDTH}}{low_pct:>{_VALUE_WIDTH - 1}.1f}%')
  print(f'{"High (> 200% of start)":<{_LABEL_WIDTH}}{high_pct:>{_VALUE_WIDTH - 1}.1f}%')
  print()
