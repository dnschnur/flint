"""Income and budget allocation strategy for retirement simulations.

Defines how income, budget, and RMDs are applied to assets each year, both during the pre-retirement
accumulation phase and the retirement drawdown phase.
"""

from collections import defaultdict

from assets import AssetCategory
from budget import BudgetCategory
from rmd import RMD


# Mapping from budget categories to corresponding asset categories
_BUDGET_TO_ASSET_CATEGORIES = {
  BudgetCategory.PRE_TAX_401K: AssetCategory.PLAN_401K,
  BudgetCategory.AFTER_TAX_401K: AssetCategory.PLAN_401K,
  BudgetCategory.PRE_TAX_ROTH_401K: AssetCategory.ROTH_401K,
  BudgetCategory.AFTER_TAX_ROTH_401K: AssetCategory.ROTH_401K,
  BudgetCategory.IRA: AssetCategory.IRA,
  BudgetCategory.ROTH_IRA: AssetCategory.ROTH_IRA,
  BudgetCategory.PLAN_529: AssetCategory.PLAN_529,
  BudgetCategory.HSA: AssetCategory.HSA,
  BudgetCategory.STOCKS: AssetCategory.STOCKS,
  BudgetCategory.BONDS: AssetCategory.BONDS,
}

# Budget categories that represent retirement account contributions.
# These are skipped during retirement since contributions are no longer made.
_RETIREMENT_CONTRIBUTION_CATEGORIES = {
  BudgetCategory.PRE_TAX_401K,
  BudgetCategory.AFTER_TAX_401K,
  BudgetCategory.PRE_TAX_ROTH_401K,
  BudgetCategory.AFTER_TAX_ROTH_401K,
  BudgetCategory.IRA,
  BudgetCategory.ROTH_IRA,
  BudgetCategory.PLAN_529,
  BudgetCategory.HSA,
}

# Asset categories subject to RMDs (traditional/pre-tax retirement accounts)
_RMD_CATEGORIES = {
  AssetCategory.PLAN_401K,  # Traditional 401K
  AssetCategory.IRA,         # Traditional IRA
}


class Strategy:
  """Strategy that maps income and budgets to asset changes.

  Budget items that correspond to asset categories (401K, Stocks, etc.) are treated as contributions
  to those assets. All other budget items are treated as expenses that reduce available income. Any
  remaining income goes to cash.

  RMDs (Required Minimum Distributions) are withdrawn first before other asset allocation logic.
  """

  def __init__(self, rmd: RMD):
    """Initialize the strategy.

    Args:
      rmd: RMD calculator for required minimum distributions.
    """
    self.rmd = rmd

  def apply(
    self,
    year: int,
    assets: dict[AssetCategory, float],
    income: float,
    budget: dict[BudgetCategory, float],
    retired: bool = False,
    age: int = 0
  ) -> defaultdict[AssetCategory, float]:
    """Returns updated asset values after applying income and budget for the year.

    Processing order:
      1. Calculate and withdraw RMDs from applicable accounts
      2. Add regular income
      3. Process budget items (contributions and expenses)
      4. If there's a shortfall withdraw:
         - Pre-retirement: health expenses from HSA, then the rest from Cash → Bonds → Stocks.
           Raise an exception if there are insufficient liquid assets at this point.
         - Retirement: proportionally from all assets

    During pre-retirement (retired=False):
      - Income is used to cover expenses and make contributions
      - Remaining income goes to cash
      - If expenses exceed income, uses priority-based withdrawal from liquid assets

    During retirement (retired=True):
      - Only non-retirement budget categories are processed
      - If income doesn't cover expenses, withdraws proportionally from all assets

    Args:
      year: The year to apply the strategy.
      assets: Current asset values by category.
      income: Total income for the year.
      budget: Budget expenditures by category for the year.
      retired: If True, indicates post-retirement (affects income calculation).
      age: Current age.

    Returns:
      Updated asset values after applying income and budget.

    Raises:
      ValueError: If pre-retirement shortfall cannot be covered by liquid assets.
    """
    # Start with a copy of current assets, defaulting missing categories to 0.0.
    new_assets: defaultdict[AssetCategory, float] = defaultdict(float, assets)

    # Step 1: Calculate and withdraw RMDs first
    rmd_income = 0.0
    for asset_category in _RMD_CATEGORIES:
      if new_assets[asset_category] > 0:
        rmd_amount = self.rmd.calculate(age, new_assets[asset_category])
        if rmd_amount > 0:
          new_assets[asset_category] -= rmd_amount
          rmd_income += rmd_amount

    remaining = income + rmd_income

    for category, amount in budget.items():
      # Skip retirement account contributions during retirement
      if retired and category in _RETIREMENT_CONTRIBUTION_CATEGORIES:
        continue

      if category in _BUDGET_TO_ASSET_CATEGORIES:
        new_assets[_BUDGET_TO_ASSET_CATEGORIES[category]] += amount
      remaining -= amount

    # If remaining is negative, we need to withdraw from assets
    if remaining < 0:
      shortfall = -remaining

      if not retired:
        # Pre-retirement: Use priority-based withdrawal
        # First, withdraw health expenses from HSA
        health_expenses = budget.get(BudgetCategory.HEALTH, 0.0)
        if health_expenses > 0:
          hsa_withdrawal = min(health_expenses, new_assets[AssetCategory.HSA], shortfall)
          if hsa_withdrawal > 0:
            new_assets[AssetCategory.HSA] -= hsa_withdrawal
            shortfall -= hsa_withdrawal

        # Then withdraw remaining shortfall from liquid assets in priority order
        if shortfall:
          for asset_category in (AssetCategory.CASH, AssetCategory.BONDS, AssetCategory.STOCKS):
            if shortfall <= 0:
              break
            withdrawal = min(new_assets[asset_category], shortfall)
            if withdrawal > 0:
              new_assets[asset_category] -= withdrawal
              shortfall -= withdrawal

          if shortfall:
            raise ValueError(
              f'Insufficient liquid assets in year {year}. '
              f'Shortfall of ${shortfall:,.2f} cannot be covered pre-retirement. '
              f'Simulation requires liquid assets (Cash, Bonds, or Stocks) to cover expenses.'
            )

        remaining = 0
      else:
        # Retirement: Withdraw proportionally from non-Cash assets, clamping each to zero.
        # Any remainder that can't be covered (because assets are exhausted) falls through to Cash,
        # which is the only category that is allowed to go negative.
        non_cash = {category: balance
                    for category, balance in new_assets.items()
                    if category != AssetCategory.CASH and balance > 0}
        total_non_cash = sum(non_cash.values())

        if total_non_cash:
          # Withdraw proportionally from each non-Cash asset. If an asset's proportional share
          # exceeds its balance, take the full balance and credit it in full against the shortfall;
          # the remainder falls to Cash.
          for category, balance in non_cash.items():
            proportion = balance / total_non_cash
            withdrawal = min(balance, shortfall * proportion)
            new_assets[category] = balance - withdrawal
            shortfall -= withdrawal

        # Any remaining shortfall comes from Cash (may go negative)
        remaining = -shortfall

    new_assets[AssetCategory.CASH] += remaining

    return new_assets
