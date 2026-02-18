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

# Pre-retirement liquid asset drawdown priority order (Cash first, then Bonds, then Stocks).
_LIQUID_ASSET_CATEGORIES = (
  AssetCategory.CASH,
  AssetCategory.BONDS,
  AssetCategory.STOCKS,
)

# Asset categories excluded from the general proportional withdrawal pool during retirement.
# HSA and 529 are reserved for specific expense categories; Real Estate is illiquid and can
# only be accessed via explicit rules (e.g. a downsizing rule that converts equity to cash).
_RESERVED_ASSET_CATEGORIES = {
  AssetCategory.HSA,
  AssetCategory.PLAN_529,
  AssetCategory.REAL_ESTATE,
}


def _apply_529_withdrawal(
  new_assets: defaultdict[AssetCategory, float],
  budget: dict[BudgetCategory, float],
  eligible_529: float
) -> float:
  """Unconditionally withdraw from 529 to cover 529-eligible school expenses.

  This runs regardless of whether income covers school expenses, to ensure 529 assets
  are not wasted. Any withdrawal is returned as a credit to apply against remaining income
  or reduce a shortfall.

  Modifies new_assets in place and returns the amount withdrawn.

  Args:
    new_assets: Current asset balances (modified in place).
    budget: Budget amounts by category for the year.
    eligible_529: Fraction of the school budget payable from the 529 plan.

  Returns:
    The amount withdrawn from the 529 plan.
  """
  if not eligible_529:
    return 0.0
  school_expenses = budget.get(BudgetCategory.SCHOOL, 0.0)
  eligible_amount = school_expenses * eligible_529
  if not eligible_amount:
    return 0.0
  withdrawal = min(eligible_amount, new_assets[AssetCategory.PLAN_529])
  new_assets[AssetCategory.PLAN_529] -= withdrawal
  return withdrawal


def _apply_hsa_withdrawal(
  new_assets: defaultdict[AssetCategory, float],
  budget: dict[BudgetCategory, float],
  shortfall: float
) -> float:
  """Withdraw from HSA to cover a health expense shortfall.

  Only draws from the HSA when there is an actual funding shortfall, up to the health
  budget and available HSA balance.

  Modifies new_assets in place and returns the remaining shortfall.

  Args:
    new_assets: Current asset balances (modified in place).
    budget: Budget amounts by category for the year.
    shortfall: The current funding shortfall to reduce.

  Returns:
    The remaining shortfall after the HSA withdrawal.
  """
  health_expenses = budget.get(BudgetCategory.HEALTH, 0.0)
  if not health_expenses:
    return shortfall
  withdrawal = min(health_expenses, new_assets[AssetCategory.HSA], shortfall)
  if withdrawal:
    new_assets[AssetCategory.HSA] -= withdrawal
    shortfall -= withdrawal
  return shortfall


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
    age: int = 0,
    eligible_529: float = 0.0
  ) -> defaultdict[AssetCategory, float]:
    """Returns updated asset values after applying income and budget for the year.

    Processing order:
      1. Calculate and withdraw RMDs from applicable accounts
      2. Add regular income
      3. Process budget items (contributions and expenses)
      4. Withdraw from 529 to cover 529-eligible school expenses (always, to avoid waste)
      5. If there's a shortfall:
         a. Withdraw from HSA to cover health expenses
         b. Cover any remaining shortfall:
            - Pre-retirement: from Cash → Bonds → Stocks; raise if still insufficient
            - Retirement: proportionally from all non-Cash, non-HSA, non-529 assets;
              any uncovered remainder falls to Cash (which may go negative)

    During pre-retirement (retired=False):
      - Income is used to cover expenses and make contributions
      - Remaining income goes to cash
      - If expenses exceed income, uses priority-based withdrawal from liquid assets

    During retirement (retired=True):
      - Only non-retirement budget categories are processed
      - If income doesn't cover expenses, withdraws proportionally from non-reserved assets

    Args:
      year: The year to apply the strategy.
      assets: Current asset values by category.
      income: Total income for the year.
      budget: Budget expenditures by category for the year.
      retired: If True, indicates post-retirement (affects income calculation).
      age: Current age.
      eligible_529: Fraction of the school budget payable from the 529 plan.

    Returns:
      Updated asset values after applying income and budget.

    Raises:
      ValueError: If pre-retirement shortfall cannot be covered by liquid assets.
    """
    # Start with a copy of current assets, defaulting missing categories to 0.0.
    new_assets: defaultdict[AssetCategory, float] = defaultdict(float, assets)

    # Calculate and withdraw RMDs first
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

    # Always withdraw 529-eligible school expenses from the 529 plan, regardless of whether income
    # covers them. This prevents 529 assets from being wasted if they aren't needed for general
    # expenses. The withdrawal is credited back to remaining to reduce any shortfall (or surplus).
    remaining += _apply_529_withdrawal(new_assets, budget, eligible_529)

    # If remaining is negative, we need to withdraw from assets
    if remaining < 0:
      shortfall = -remaining

      shortfall = _apply_hsa_withdrawal(new_assets, budget, shortfall)

      if not retired:
        # Pre-retirement: withdraw remaining shortfall from liquid assets in priority order
        if shortfall:
          for asset_category in _LIQUID_ASSET_CATEGORIES:
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
        # Retirement: withdraw proportionally from non-cash, non-reserved assets, clamping each to
        # zero. Any remainder that can't be covered falls through to Cash, which is the only
        # category allowed to go negative. HSA and 529 are excluded from this pool since they are
        # reserved for their designated expense categories.
        general_pool = {
          category: balance
          for category, balance in new_assets.items()
          if category != AssetCategory.CASH
          and category not in _RESERVED_ASSET_CATEGORIES
          and balance > 0
        }

        total_pool = sum(general_pool.values())

        if total_pool:
          # Withdraw proportionally from each asset, using the original shortfall for all
          # proportion calculations so each asset's share is computed independently.
          # If an asset can't cover its proportional share, take its full balance;
          # any uncovered remainder falls to Cash.
          original_shortfall = shortfall
          for category, balance in general_pool.items():
            proportion = balance / total_pool
            withdrawal = min(balance, original_shortfall * proportion)
            new_assets[category] = balance - withdrawal
            shortfall -= withdrawal

        # Any remaining shortfall comes from Cash (may go negative)
        remaining = -shortfall

    new_assets[AssetCategory.CASH] += remaining

    return new_assets
