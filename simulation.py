"""Monte Carlo retirement simulation using historical S&P 500 data.

The simulation runs in two phases:
1. A deterministic pre-retirement projection to produce starting assets.
2. Simulated retirement scenarios, one for each historical S&P 500 period of matching length.
"""

import csv

from collections import defaultdict
from dataclasses import dataclass

from assets import Assets, AssetCategory
from budget import Budget, BudgetCategory
from income import Income
from rmd import RMD
from strategy import Strategy


# Asset categories that track S&P 500 performance
_STOCK_LIKE_ASSETS = {
  AssetCategory.STOCKS,
  AssetCategory.PLAN_401K,
  AssetCategory.ROTH_401K,
  AssetCategory.IRA,
  AssetCategory.ROTH_IRA,
  AssetCategory.PLAN_529,
  AssetCategory.HSA,
}


@dataclass
class SimulationResult:
  """Result of a single Monte Carlo simulation run.

  Attributes:
    start_year: The first year of the historical S&P 500 period used.
    assets: Final asset values by category at the end of retirement.
  """
  start_year: int
  assets: defaultdict[AssetCategory, float]


class Simulation:
  """Simulation of pre-retirement and post-retirement assets."""

  def __init__(
    self,
    assets: Assets,
    budget: Budget,
    income: Income,
    rmd: RMD,
    current_age: int,
    data_year: int,
    sp500_path: str,
    simulation_min_year: int | None = None,
    simulation_max_year: int | None = None
  ):
    """Initialize the simulation.

    Args:
      assets: Assets tracker with historical and projected values.
      budget: Budget with historical and projected values.
      income: Income tracker with historical and projected values.
      rmd: RMD calculator for required minimum distributions.
      current_age: Current age of the person.
      data_year: The year corresponding to current_age. This is the anchor year from which ages and
          projections are calculated; it should match the latest historical year across the assets,
          budget, and income data.
      sp500_path: Path to CSV file with historical S&P 500 data.
      simulation_min_year: Minimum year for simulation data, or None for the earliest available.
      simulation_max_year: Maximum year for simulation data, or None for the latest available.
    """
    self.assets = assets
    self.budget = budget
    self.income = income
    self.strategy = Strategy(rmd=rmd)
    self.current_age = current_age
    self.data_year = data_year

    self._sp500_data = self._load_sp500(sp500_path)

    available_years = sorted(self._sp500_data.keys())
    self.simulation_min_year = simulation_min_year or available_years[0]
    self.simulation_max_year = simulation_max_year or available_years[-1]

  def project_pre_retirement(self, retirement_year: int) -> defaultdict[AssetCategory, float]:
    """Project assets from the data year up to (not including) retirement_year.

    This phase is deterministic — it uses fixed income, budget, and default growth rates rather than
    historical S&P 500 data. The result is the same for every simulation run, so it should be
    computed once and reused.

    Args:
      retirement_year: Retirement year (when job income stops).

    Returns:
      Dict mapping AssetCategory to asset values at the start of retirement.
    """
    # The data year is the CSV anchor year, stored as self.data_year. We derive it here from the
    # source objects as a consistency check; both should agree.
    data_year = max(
      self.assets._last_historical_year or retirement_year,
      self.budget._last_historical_year or retirement_year,
      self.income._last_historical_year or retirement_year
    )

    # Get initial asset values from the data year
    current_assets = {}
    for category in AssetCategory:
      value = self.assets.get_category(category, data_year)
      if value > 0:
        current_assets[category] = value

    # Project year by year, applying income, budget, and default growth rates
    for year in range(data_year, retirement_year):
      age = self.current_age + (year - self.data_year)

      year_income = self.income.get(year, retired=False)
      year_budget = {}
      for category in BudgetCategory:
        if amount := self.budget.get_category(category, year):
          year_budget[category] = amount

      current_assets = self.strategy.apply(
        year, current_assets, year_income, year_budget, retired=False, age=age,
        eligible_529=self.budget.get_529_eligible_fraction(year)
      )

      new_assets = defaultdict(float)
      for category, value in current_assets.items():
        new_assets[category] = value * (1 + category.growth)

      current_assets = new_assets

    return current_assets

  def run(
    self,
    start_year: int,
    end_year: int,
    starting_assets: dict[AssetCategory, float] | None = None
  ):
    """Run Monte Carlo simulation across all available historical periods.

    For each historical period of length (end_year - start_year), simulates how assets would perform
    if the market behaves as it did during that period.

    The simulation works in two phases:
    1. Pre-retirement: Project assets from the data year to start_year (once, deterministic)
    2. Retirement: Monte Carlo simulation from start_year to end_year

    Args:
      start_year: Retirement year (when job income stops).
      end_year: Last year of retirement (inclusive).
      starting_assets: Pre-computed asset values at the start of retirement, as returned by
        project_pre_retirement(). If not provided, project_pre_retirement() is called internally.

    Yields:
      SimulationResult for each historical period, containing the historical
      start year and final asset values.
    """
    # Pre-retirement is deterministic; accept pre-computed values to avoid redundant work when the
    # caller has already called project_pre_retirement() (e.g. to display the starting assets table).
    pre_retirement_assets = starting_assets or self.project_pre_retirement(start_year)

    simulation_length = end_year - start_year
    max_historical_start = self.simulation_max_year - simulation_length

    for historical_start_year in range(self.simulation_min_year, max_historical_start + 1):
      historical_end_year = historical_start_year + simulation_length
      if historical_end_year in self._sp500_data:
        assets = self._run_single_simulation(
            pre_retirement_assets, start_year, end_year, historical_start_year)
        yield SimulationResult(start_year=historical_start_year, assets=assets)

  def _get_sp500_return(self, start_year: int, end_year: int) -> float:
    """Returns the S&P 500 return between two years.

    Args:
      start_year: Start year.
      end_year: End year.

    Returns:
      The percentage return (e.g., 0.10 for 10% gain).
    """
    start_value = self._sp500_data[start_year]
    end_value = self._sp500_data[end_year]
    return (end_value - start_value) / start_value

  def _load_sp500(self, path: str) -> dict[int, float]:
    """Load historical S&P 500 data from CSV (January values only).

    Expected format:
      Date,Value
      1871-01,4.44
      1871-02,4.50
      ...

    Args:
      path: Path to the CSV file.

    Returns:
      Dict mapping years to S&P 500 values (January only).
    """
    data = {}
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        date = row['Date']
        # Only load January values (YYYY-01)
        if date.endswith('-01'):
          year = int(date[:4])
          value = float(row['Value'].replace(',', ''))
          data[year] = value
    return data

  def _run_single_simulation(
    self,
    starting_assets: dict[AssetCategory, float],
    start_year: int,
    end_year: int,
    historical_start_year: int
  ) -> defaultdict[AssetCategory, float]:
    """Run a single simulation using a specific historical period.

    Args:
      starting_assets: Asset values at the start of retirement.
      start_year: Retirement year (when job income stops).
      end_year: Last year of retirement (inclusive).
      historical_start_year: Starting year for historical S&P 500 data.

    Returns:
      Dict mapping AssetCategory to final asset values.
    """
    current_assets = defaultdict(float, starting_assets)
    current_historical_year = historical_start_year

    for year in range(start_year, end_year + 1):
      age = self.current_age + (year - self.data_year)

      year_income = self.income.get(year, retired=True)
      year_budget = {}
      for category in BudgetCategory:
        if amount := self.budget.get_category(category, year):
          year_budget[category] = amount

      current_assets = self.strategy.apply(
        year, current_assets, year_income, year_budget, retired=True, age=age,
        eligible_529=self.budget.get_529_eligible_fraction(year)
      )

      if year < end_year:  # Don't grow in the final year
        next_historical_year = current_historical_year + 1
        sp500_return = self._get_sp500_return(current_historical_year, next_historical_year)

        new_assets = {}
        for category, value in current_assets.items():
          if category in _STOCK_LIKE_ASSETS:
            new_assets[category] = value * (1 + sp500_return)
          else:
            new_assets[category] = value * (1 + category.growth)

        current_assets = new_assets
        current_historical_year = next_historical_year

    return current_assets
