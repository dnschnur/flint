"""Monte Carlo retirement simulation using historical S&P 500 data.

The simulation runs in two phases:
1. A deterministic pre-retirement projection to produce starting assets.
2. Simulated retirement scenarios, one for each historical S&P 500 period of matching length.
"""

import csv

from collections import defaultdict
from decimal import Decimal
from dataclasses import dataclass, field
from typing import TypeAlias

from assets import Assets, AssetCategory, AssetDict, AssetDefaultDict
from budget import Budget, BudgetCategory, BudgetDict
from income import Income
from inflation import Inflation
from rmd import RMD
from strategy import Strategy
from tax import Tax

YearSnapshot: TypeAlias = dict[str, object]


@dataclass
class SimulationResult:
  """Result of a single Monte Carlo simulation run.

  Attributes:
    start_year: The first year of the historical S&P 500 period used.
    assets: Final asset values by category at the end of retirement.
    history: Per-year snapshots of asset balances at the start of each
      retirement year, from start_year through end_year (inclusive).
    real_estate_liquidated: True if Real Estate was force-liquidated in any
      year to cover a shortfall after all other assets were exhausted.
  """
  start_year: int
  assets: AssetDefaultDict
  history: list[YearSnapshot] = field(default_factory=list)
  real_estate_liquidated: bool = False


class Simulation:
  """Simulation of pre-retirement and post-retirement assets."""

  def __init__(
    self,
    assets: Assets,
    budget: Budget,
    income: Income,
    rmd: RMD,
    tax: Tax,
    current_age: int,
    data_year: int,
    sp500_path: str,
    simulation_min_year: int | None = None,
    simulation_max_year: int | None = None,
    inflation: Inflation | None = None,
  ):
    """Initialize the simulation.

    Args:
      assets: Assets tracker with historical and projected values.
      budget: Budget with historical and projected values.
      income: Income tracker with historical and projected values.
      rmd: RMD calculator for required minimum distributions.
      tax: Tax calculator for income and capital gains tax.
      current_age: Current age of the person.
      data_year: The year corresponding to current_age. This is the anchor year from which ages and
          projections are calculated; it should match the latest historical year across the assets,
          budget, and income data.
      sp500_path: Path to CSV file with historical S&P 500 data.
      simulation_min_year: Minimum year for simulation data, or None for the earliest available.
      simulation_max_year: Maximum year for simulation data, or None for the latest available.
      inflation: Optional historical inflation data. When provided, the Monte Carlo simulation uses
          year-specific historical inflation rates (matched to the S&P 500 replay period) rather
          than the budget category's fixed average rates, improving accuracy of the scenario.
    """
    self.assets = assets
    self.budget = budget
    self.income = income
    self.strategy = Strategy(rmd=rmd, tax=tax)
    self.current_age = current_age
    self.data_year = data_year
    self.inflation = inflation

    self._sp500_data = self._load_sp500(sp500_path)

    available_years = sorted(self._sp500_data.keys())
    self.simulation_min_year = simulation_min_year or available_years[0]
    self.simulation_max_year = simulation_max_year or available_years[-1]

  def _get_year_budget(self, year: int, retirement_year: int) -> BudgetDict:
    """Returns budget amounts for the given year, omitting zero or absent categories."""
    return {
      category: amount
      for category in BudgetCategory
      if (amount := self.budget.get_category(category, year, retirement_year))
    }

  def project_pre_retirement(self, retirement_year: int):
    """Project assets year by year from the data year up to (not including) retirement_year.

    This phase is deterministic — it uses fixed income, budget, and default growth rates rather than
    historical S&P 500 data. The result is the same for every simulation run, so it should be
    computed once and reused.

    Yields (year, assets) after each year's strategy and growth are applied, starting with the data
    year and ending with retirement_year - 1. The final yielded assets are the starting assets for
    retirement.

    Args:
      retirement_year: Retirement year (when job income stops).
    """
    # Get initial asset values from the data year
    current_assets = {}
    for category in AssetCategory:
      value = self.assets.get_category(category, self.data_year, retirement_year)
      if value > 0:
        current_assets[category] = value

    # Project year by year, applying income, budget, and default growth rates
    for year in range(self.data_year, retirement_year):
      age = self.current_age + (year - self.data_year)

      year_income = self.income.get(year, retirement_year)
      year_budget = self._get_year_budget(year, retirement_year)

      current_assets = self.strategy.apply(
        year, current_assets, year_income, year_budget, retired=False, age=age,
        eligible_529=self.budget.get_529_eligible_fraction(year),
        employer_match_fraction=self.budget.get_employer_match_fraction(year)
      )

      new_assets = defaultdict(int)
      for category, value in current_assets.items():
        new_assets[category] = self.assets.apply_year(
            category, year + 1, value, retirement_year, context=current_assets)

      current_assets = new_assets
      yield year, current_assets, year_budget

  def run(
    self,
    start_year: int,
    end_year: int,
    starting_assets: AssetDict | None = None
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
    if starting_assets:
      pre_retirement_assets = starting_assets
    else:
      *_, (_, pre_retirement_assets, _) = self.project_pre_retirement(start_year)

    simulation_length = end_year - start_year
    max_historical_start = self.simulation_max_year - simulation_length

    for historical_start_year in range(self.simulation_min_year, max_historical_start + 1):
      historical_end_year = historical_start_year + simulation_length
      if historical_end_year in self._sp500_data:
        assets, history, real_estate_liquidated = self._run_single_simulation(
            pre_retirement_assets, start_year, end_year, historical_start_year)
        yield SimulationResult(
            start_year=historical_start_year, assets=assets, history=history,
            real_estate_liquidated=real_estate_liquidated)

  def _get_sp500_return(self, start_year: int, end_year: int) -> Decimal:
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

  def _load_sp500(self, path: str) -> dict[int, Decimal]:
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
          value = Decimal(row['Value'].replace(',', ''))
          data[year] = value
    return data

  def _compute_stock_basis(self, start_year: int, starting_stocks: int) -> Decimal:
    """Estimate the stock cost basis at the start of retirement.

    Starts from the base-year Stocks balance scaled by (1 - Capital Gains Percentage), then
    adds all pre-retirement Stocks budget contributions, which are pure cost basis (you paid for
    them; they haven't grown yet).

    Pre-retirement withdrawals from Stocks are not accounted for, which slightly overestimates
    the basis (and conservatively underestimates capital gains). This is acceptable given that
    Stocks is the last account tapped for pre-retirement shortfalls.

    Args:
      start_year: The retirement start year.
      starting_stocks: The Stocks balance at the start of retirement.

    Returns:
      Estimated cost basis, clamped to [0, starting_stocks].
    """
    initial_stocks = self.assets.get_category(
        AssetCategory.STOCKS, self.data_year, retirement_year=start_year)
    basis = initial_stocks * (1 - self.assets.base_cg_fraction)

    # Stock budget contributions during pre-retirement are pure cost basis.
    # TODO: this doesn't factor in cash contributions reinvested as stock!
    for year in range(self.data_year, start_year):
      basis += self.budget.get_category(BudgetCategory.STOCKS, year, retirement_year=start_year)

    return Decimal(max(0, min(basis, starting_stocks)))

  def _run_single_simulation(
    self,
    starting_assets: AssetDict,
    start_year: int,
    end_year: int,
    historical_start_year: int
  ) -> tuple[AssetDefaultDict, list[YearSnapshot], bool]:
    """Run a single simulation using a specific historical period.

    Args:
      starting_assets: Asset values at the start of retirement.
      start_year: Retirement year (when job income stops).
      end_year: Last year of retirement (inclusive).
      historical_start_year: Starting year for historical S&P 500 data.

    Returns:
      Tuple of (assets, history, real_estate_liquidated), where assets contains final values for
      each asset category, history is a list of per-year snapshots from start_year to end_year, and
      real_estate_liquidated is True if the Real Estate balance dropped to zero in any year
      (inferred by comparing the pre/post-strategy balance within the retirement loop).
    """
    history = []
    real_estate_liquidated = False
    current_assets = defaultdict(int, starting_assets)
    current_historical_year = historical_start_year

    # Normally whole-dollar values like this would use an int, but here we use Decimal, so it's
    # cleaner to recompute it from year-to-year in the loop below, without losing precision.
    stock_basis = self._compute_stock_basis(start_year, current_assets.get(AssetCategory.STOCKS, 0))

    # Track budget amounts directly so each year's budget grows by the actual historical
    # inflation rate rather than the long-run average. Rules still fire at their scheduled
    # calendar years via Budget.advance.
    current_budget = self._get_year_budget(start_year, retirement_year=start_year)

    for year in range(start_year, end_year + 1):
      age = self.current_age + (year - self.data_year)

      # Capture start-of-year snapshot before strategy withdrawals are applied.
      history.append({
        'year': year,
        'assets': {
          category.display_name: value
          for category, value in current_assets.items()
          if value
        },
        'budget': {
          category.display_name: amount
          for category, amount in current_budget.items()
          if amount and category.asset_category is None
        },
      })

      # Compute capital gains fraction from tracked cost basis.
      old_stocks = current_assets.get(AssetCategory.STOCKS, 0)
      cg_fraction = max(Decimal(0), 1 - stock_basis / old_stocks) if old_stocks else Decimal(0)

      year_income = self.income.get(year, retirement_year=start_year)

      real_estate_before = current_assets[AssetCategory.REAL_ESTATE]

      current_assets = self.strategy.apply(
        year, current_assets, year_income, current_budget, retired=True, age=age,
        eligible_529=self.budget.get_529_eligible_fraction(year),
        cg_fraction=cg_fraction,
        employer_match_fraction=self.budget.get_employer_match_fraction(year)
      )

      if real_estate_before and not current_assets[AssetCategory.REAL_ESTATE]:
        real_estate_liquidated = True

      # After withdrawals, reduce basis proportionally to the Stocks balance reduction.
      # Market growth (applied below in apply_year) leaves basis unchanged — all growth is gains.
      new_stocks = current_assets.get(AssetCategory.STOCKS, 0)
      if old_stocks and new_stocks < old_stocks:
        # This doesn't use *= because otherwise new_stocks / old_stocks produces a float, which we
        # can't multiply with stock_basis, which is (and should remain) a Decimal. Starting with
        # stock_basis on the right-hand-side forces the use of Decimal for intermediate values.
        stock_basis = stock_basis * new_stocks / old_stocks

      if year < end_year:  # Don't grow in the final year
        next_historical_year = current_historical_year + 1
        sp500_return = self._get_sp500_return(current_historical_year, next_historical_year)

        # Advance each budget category by one year using the matched historical inflation rate.
        current_budget = {
          category: self.budget.advance(
            category, year + 1, amount,
            self.inflation.rate(category, current_historical_year) if self.inflation else None,
            retirement_year=start_year
          )
          for category, amount in current_budget.items()
        }

        new_assets = {}
        for category, value in current_assets.items():
          growth_rate = sp500_return if category.tracks_sp500 else None
          new_assets[category] = self.assets.apply_year(
              category, year + 1, value, retirement_year=start_year,
              growth_rate=growth_rate, context=current_assets)

        current_assets = new_assets
        current_historical_year = next_historical_year

    # Append a final snapshot at end_year + 1 showing the post-strategy end-of-simulation
    # balances. This fills the gap that would otherwise leave the last year's activity invisible,
    # since all other snapshots are captured before the strategy fires for that year.
    history.append({
      'year': end_year + 1,
      'assets': {
        category.display_name: value
        for category, value in current_assets.items()
        if value
      },
      'budget': {},
    })

    return current_assets, history, real_estate_liquidated
