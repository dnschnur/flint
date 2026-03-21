"""Income and budget allocation strategy for retirement simulations.

Defines how income, budget, and RMDs are applied to assets each year, both during the pre-retirement
accumulation phase and the retirement drawdown phase.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from assets import AssetCategory, AssetDict, AssetDefaultDict
from budget import BudgetCategory, BudgetDict
from rmd import RMD
from tax import Tax


# Pre-retirement liquid asset drawdown priority order (Cash first, then Bonds, then Stocks).
_LIQUID_ASSETS = (
  AssetCategory.CASH,
  AssetCategory.BONDS,
  AssetCategory.STOCKS,
)


@dataclass
class Finances:
  """Mutable financial state for one year's strategy application.

  Carries the asset balances and income/surplus/shortfall counters that are updated as each phase
  of the strategy executes.

  Attributes:
    assets: Asset balances by category, mutated in place as the strategy runs.
    remaining: Net income minus expenses. Positive = surplus to invest; negative = shortfall to
        cover from assets.
    taxable_income: Pre-tax income captured after contributions are deducted. Set once by
        _apply_income_tax and used later as the base income level for withdrawal gross-up.
    running_income: Cumulative ordinary income during retirement withdrawal passes. Starts at
        taxable_income and grows with each ordinary income withdrawal so that successive
        withdrawals are taxed at the correct marginal bracket.
  """
  assets: AssetDefaultDict
  remaining: int
  taxable_income: int = 0
  running_income: int = 0


def _is_withdrawal_eligible(category: AssetCategory, balance: int, age: int) -> bool:
  """Returns whether the asset is eligible for general-pool withdrawal at the given age.

  Excludes Cash (handled as the final fallback), reserved accounts (HSA, 529, Real Estate),
  Roth accounts (handled in the tax-free pool), and age-restricted accounts when the
  penalty-free withdrawal age hasn't been reached.
  """
  return (
    category != AssetCategory.CASH
    and not category.is_reserved
    and not category.is_roth
    and balance > 0
    and age >= category.withdrawal_min_age
  )


def _gross_up_ordinary(
  net: int,
  balance: int,
  running_income: int,
  year: int,
  tax: Tax,
  bracket_cap: bool = False
) -> tuple[int, int]:
  """Compute a gross ordinary-income withdrawal that yields `net` after incremental tax.

  Args:
    net: Target net amount after incremental ordinary income tax.
    balance: Available balance in the account (caps the gross withdrawal).
    running_income: Current taxable income before this withdrawal.
    year: The tax year.
    tax: Tax calculator.
    bracket_cap: If True, additionally cap at the current federal bracket boundary to avoid
        paying the higher bracket rate. Uncovered net flows to subsequent passes.

  Returns:
    (gross_withdrawal, net_covered): Gross amount withdrawn and net amount actually covered.
  """
  gross = min(balance, tax.gross_for_net_ordinary(net, running_income, year))
  if bracket_cap:
    if next_threshold := tax.next_ordinary_bracket_threshold(running_income, year):
      gross = min(gross, next_threshold - running_income)
  net_covered = gross - tax.incremental_ordinary_tax(running_income, gross, year)
  return gross, net_covered


def _withdrawal_multiplier(
  category: AssetCategory,
  tax: Tax,
  taxable_income: int,
  year: int,
  cg_fraction: Decimal
) -> Decimal:
  """Returns the gross-up multiplier for a withdrawal from the given asset category.

  To net $X from an asset after tax, the gross withdrawal is X * multiplier. The excess
  (multiplier - 1) * X represents the tax paid, which is lost rather than credited anywhere.

  Args:
    category: The asset category being withdrawn from.
    tax: Tax calculator for rate lookups.
    taxable_income: Current taxable income level, used to find the marginal rate.
    year: The tax year.
    cg_fraction: Fraction of the withdrawal treated as capital gains.

  Returns:
    Gross-up multiplier >= 1.0.
  """
  if category.capital_gains and cg_fraction:
    rate = tax.marginal_rate(taxable_income, year, capital_gains=True)
    return 1 + cg_fraction * rate
  return Decimal(1)


class Strategy:
  """Strategy that maps income and budgets to asset changes.

  Budget items that correspond to asset categories (401K, Stocks, etc.) are treated as contributions
  to those assets. All other budget items are treated as expenses that reduce available income. Any
  remaining income goes to cash.

  RMDs (Required Minimum Distributions) are withdrawn first before other asset allocation logic.
  """

  def __init__(self, rmd: RMD, tax: Tax):
    """Initialize the strategy.

    Args:
      rmd: RMD calculator for required minimum distributions.
      tax: Tax calculator for income and capital gains tax.
    """
    self.rmd = rmd
    self.tax = tax

  def apply(
    self,
    year: int,
    assets: AssetDict,
    income: int,
    budget: BudgetDict,
    retired: bool = False,
    age: int = 0,
    eligible_529: Decimal = Decimal(0),
    cg_fraction: Decimal = Decimal(0),
    employer_match_fraction: Decimal = Decimal(0)
  ) -> AssetDefaultDict:
    """Returns updated asset values after applying income, tax, and budget for the year.

    Processing order:
      1. Withdraw RMDs from applicable accounts (adds to taxable income)
      2. Make pre-tax contributions (reduces taxable income; pre-retirement only)
      3. Apply ordinary income tax on post-contribution income
      4. Process budget items (expenses and after-tax contributions)
      5. Withdraw from 529 to cover 529-eligible school expenses (always, to avoid waste)
      6. Cover any shortfall:
           Pre-retirement: HSA → liquid assets in priority order (Cash → Bonds → Stocks)
           Retirement: HSA → taxable pool → tax-free pool → fallback pool → Real Estate → Cash
      7. Reinvest any retirement surplus (50% to Stocks; remainder to Cash)

    Pre-retirement:
      - Pre-tax contributions are made and income is taxed on the remainder
      - Remaining post-tax income covers expenses; surplus goes to cash
      - If expenses exceed post-tax income, draws from liquid assets (no tax gross-up)

    During retirement:
      - No contributions are made
      - Income (including RMDs) is taxed; surplus covers expenses
      - Shortfalls are covered by proportional withdrawal from the general asset pool,
        grossed up for tax: 401K/IRA by the ordinary marginal rate, Stocks by
        cg_fraction * capital_gains_marginal_rate

    Args:
      year: The year to apply the strategy.
      assets: Current asset values by category.
      income: Total income for the year.
      budget: Budget expenditures by category for the year.
      retired: If True, indicates post-retirement (affects contribution and withdrawal logic).
      age: Current age.
      eligible_529: Fraction of the school budget payable from the 529 plan.
      cg_fraction: Fraction of stock/asset withdrawals treated as capital gains. Should be
          0 pre-retirement, ramping from 0 to 1 linearly over retirement.
      employer_match_fraction: Employer 401K match as a fraction of the employee's pre-tax
          401K contribution (e.g. 0.5 for a 50% match). Applied pre-retirement only. Added
          directly to the pre-tax 401K balance without affecting taxable income.

    Returns:
      Updated asset values after applying income and budget.

    Raises:
      ValueError: If pre-retirement shortfall cannot be covered by liquid assets.
    """
    finances = Finances(assets=defaultdict(int, assets), remaining=income)

    self._withdraw_rmds(finances, age)
    if not retired:
      self._apply_contributions(finances, budget, employer_match_fraction)
    self._apply_income_tax(finances, year)
    self._apply_budget(finances, budget, retired)
    self._apply_529(finances, budget, eligible_529)

    if finances.remaining < 0:
      if retired:
        self._cover_retirement_shortfall(finances, budget, year, age, cg_fraction)
      else:
        self._cover_pre_retirement_shortfall(finances, budget, year)

    # Any post-retirement surplus goes 50% to Stocks, and the rest to Cash.
    # A future improvement might be to allow defining the post-retirement reinvestment mix.
    if retired and finances.remaining > 0:
      reinvestment = int(round(finances.remaining / 2))
      finances.assets[AssetCategory.STOCKS] += reinvestment
      finances.remaining -= reinvestment

    finances.assets[AssetCategory.CASH] += finances.remaining
    return finances.assets

  # ---------------------------------------------------------------------------
  # Income and contribution phases
  # ---------------------------------------------------------------------------

  def _withdraw_rmds(self, finances: Finances, age: int) -> None:
    """Withdraw required minimum distributions; adds to finances.remaining as ordinary income."""
    for category in AssetCategory:
      if category.subject_to_rmd and finances.assets[category]:
        if rmd_amount := self.rmd.calculate(age, finances.assets[category]):
          finances.assets[category] -= rmd_amount
          finances.remaining += rmd_amount

  def _apply_contributions(
    self,
    finances: Finances,
    budget: BudgetDict,
    employer_match_fraction: Decimal,
  ) -> None:
    """Make pre-tax contributions (pre-retirement only); reduces taxable income."""
    for category, amount in budget.items():
      if category.is_pre_tax_contribution:
        finances.assets[category.asset_category] += amount
        finances.remaining -= amount
    if employer_match_fraction:
      pre_tax_401k = budget.get(BudgetCategory.PRE_TAX_401K, 0)
      finances.assets[AssetCategory.PLAN_401K] += int(round(pre_tax_401k * employer_match_fraction))

  def _apply_income_tax(self, finances: Finances, year: int) -> None:
    """Apply ordinary income tax; captures taxable_income for later gross-up calculations."""
    finances.taxable_income = finances.remaining
    finances.remaining -= int(round(self.tax.calculate(finances.taxable_income, year)))

  def _apply_budget(self, finances: Finances, budget: BudgetDict, retired: bool) -> None:
    """Deduct expenses and apply after-tax contributions."""
    for category, amount in budget.items():
      if category == BudgetCategory.EMPLOYER_401K_MATCH:
        if not retired:
          finances.assets[AssetCategory.PLAN_401K] += amount
        continue  # Not deducted from income
      if category.is_pre_tax_contribution:
        continue  # Already handled in _apply_contributions
      if retired and category.is_retirement_contribution:
        continue  # No contributions during retirement
      if category.asset_category:
        finances.assets[category.asset_category] += amount
      finances.remaining -= amount

  def _apply_529(self, finances: Finances, budget: BudgetDict, eligible_529: Decimal) -> None:
    """Unconditionally withdraw 529-eligible school expenses from the 529 plan.

    Credits finances.remaining regardless of whether there is a shortfall, ensuring that 529
    assets are not wasted if income already covers the school expense.
    """
    if not eligible_529:
      return
    school_expenses = budget.get(BudgetCategory.SCHOOL, 0)
    eligible_amount = int(round(school_expenses * eligible_529))
    if not eligible_amount:
      return
    withdrawal = min(eligible_amount, finances.assets[AssetCategory.PLAN_529])
    finances.assets[AssetCategory.PLAN_529] -= withdrawal
    finances.remaining += withdrawal

  # ---------------------------------------------------------------------------
  # Shortfall coverage
  # ---------------------------------------------------------------------------

  def _cover_pre_retirement_shortfall(
    self, finances: Finances, budget: BudgetDict, year: int
  ) -> None:
    """Cover a pre-retirement shortfall from the HSA (health only) then liquid assets.

    Raises ValueError if the shortfall cannot be fully covered.
    """
    shortfall = -finances.remaining
    shortfall = self._cover_hsa(finances, budget, shortfall)

    if shortfall:
      for category in _LIQUID_ASSETS:
        if not shortfall:
          break
        withdrawal = min(finances.assets[category], shortfall)
        finances.assets[category] -= withdrawal
        shortfall -= withdrawal

      if shortfall:
        raise ValueError(
          f'Insufficient liquid assets in year {year}. '
          f'Shortfall of ${shortfall:,.2f} cannot be covered pre-retirement. '
          f'Simulation requires liquid assets (Cash, Bonds, or Stocks) to cover expenses.'
        )

    finances.remaining = 0

  def _cover_retirement_shortfall(
    self,
    finances: Finances,
    budget: BudgetDict,
    year: int,
    age: int,
    cg_fraction: Decimal,
  ) -> None:
    """Cover a retirement shortfall in order:
    HSA → taxable pool → tax-free pool → fallback pool → Real Estate → Cash.

    Initializes finances.running_income to finances.taxable_income and advances it with each ordinary
    income withdrawal so that successive withdrawals are taxed at the correct marginal bracket.
    """
    finances.running_income = finances.taxable_income
    shortfall = -finances.remaining

    shortfall = self._cover_hsa(finances, budget, shortfall)
    shortfall = self._cover_taxable_pool(finances, shortfall, year, age, cg_fraction)
    shortfall = self._cover_tax_free_pool(finances, shortfall, age)
    shortfall = self._cover_fallback_pool(finances, shortfall, year, age, cg_fraction)

    # Liquidate Real Estate before going into debt if cash is already depleted.
    if shortfall and finances.assets[AssetCategory.CASH] <= 0 and finances.assets[AssetCategory.REAL_ESTATE]:
      shortfall -= finances.assets[AssetCategory.REAL_ESTATE]
      finances.assets[AssetCategory.REAL_ESTATE] = 0

    # Any remaining shortfall comes from Cash (may go negative).
    finances.remaining = -shortfall

  def _cover_hsa(self, finances: Finances, budget: BudgetDict, shortfall: int) -> int:
    """Withdraw from HSA to cover health expenses (tax-free). Returns updated shortfall."""
    health_expenses = budget.get(BudgetCategory.HEALTH, 0)
    if not health_expenses:
      return shortfall
    withdrawal = min(health_expenses, finances.assets[AssetCategory.HSA], shortfall)
    if withdrawal:
      finances.assets[AssetCategory.HSA] -= withdrawal
    return shortfall - withdrawal

  # ---------------------------------------------------------------------------
  # Proportional withdrawal passes (retirement only)
  # ---------------------------------------------------------------------------

  def _withdraw_proportional(
    self,
    finances: Finances,
    pool: dict[AssetCategory, int],
    shortfall: int,
    weights: dict[AssetCategory, int],
    compute_gross: Callable[[AssetCategory, int, int], tuple[int, int]],
  ) -> int:
    """Withdraw proportionally from pool to cover shortfall. Returns remaining shortfall.

    Args:
      finances: Current financesancial state; finances.assets is mutated in place.
      pool: Raw balances available for withdrawal, keyed by category.
      shortfall: Deficit to cover.
      weights: Values used to compute each category's proportional share of the shortfall.
          Often equal to pool; may differ when proportioning by effective (post-tax) balances.
      compute_gross: Called as compute_gross(category, balance, net_target); returns
          (gross_withdrawal, net_covered). Responsible for balance capping and tax gross-up.

    Returns:
      Remaining shortfall after withdrawals.
    """
    total_weight = sum(weights.values())
    if not total_weight:
      return shortfall
    frozen = shortfall
    for category, balance in pool.items():
      net_target = int(round(frozen * weights[category] / total_weight))
      gross, net_covered = compute_gross(category, balance, net_target)
      finances.assets[category] = balance - gross
      shortfall -= net_covered
    return shortfall

  def _cover_taxable_pool(
    self,
    finances: Finances,
    shortfall: int,
    year: int,
    age: int,
    cg_fraction: Decimal,
  ) -> int:
    """Pass 1: proportional withdrawal from taxable accounts (401K, IRA, Stocks).

    Ordinary income (401K/IRA) withdrawals are capped at the federal bracket boundary to
    avoid pushing income into the next bracket; any uncovered net stays in shortfall for
    subsequent passes. Proportions are based on effective (post-tax) balances so each
    account contributes equally in after-tax terms.

    Returns updated shortfall.
    """
    pool = {
      category: balance
      for category, balance in finances.assets.items()
      if _is_withdrawal_eligible(category, balance, age) and not category.cash_equivalent
    }
    if not pool:
      return shortfall

    # Compute each asset's effective (post-tax) balance for proportional weighting.
    # Ordinary income accounts (401K/IRA) use exact incremental tax against the full
    # balance, so bracket-crossing is correctly reflected in the proportions.
    # CG accounts use the multiplier approximation.
    effective: dict[AssetCategory, int] = {}
    cg_multipliers: dict[AssetCategory, Decimal] = {}
    for category, balance in pool.items():
      if category.ordinary_income:
        incremental_tax = self.tax.incremental_ordinary_tax(finances.taxable_income, balance, year)
        effective[category] = balance - incremental_tax
      else:
        multiplier = _withdrawal_multiplier(
            category, self.tax, finances.taxable_income, year, cg_fraction)
        effective[category] = int(round(balance / multiplier))
        cg_multipliers[category] = multiplier

    def compute_gross(category: AssetCategory, balance: int, net_target: int) -> tuple[int, int]:
      if category.ordinary_income:
        # Cap at the bracket boundary to avoid paying the higher rate; uncovered net
        # stays in shortfall for the tax-free and fallback passes.
        gross, net_covered = _gross_up_ordinary(
            net_target, balance, finances.running_income, year, self.tax, bracket_cap=True)
        finances.running_income += gross
        return gross, net_covered
      multiplier = cg_multipliers[category]
      gross = int(round(net_target * multiplier))
      return gross, net_target

    return self._withdraw_proportional(finances, pool, shortfall, effective, compute_gross)

  def _cover_tax_free_pool(self, finances: Finances, shortfall: int, age: int) -> int:
    """Pass 2: proportional withdrawal from tax-free accounts (Bonds, Cash, Roth).

    No gross-up needed; withdrawals cover shortfall without increasing taxable income.
    Drawing from this pool covers bracket-diverted shortfall from pass 1 without pushing
    income into the next bracket.

    Returns updated shortfall.
    """
    pool = {
      category: balance
      for category, balance in finances.assets.items()
      if balance > 0
      and (category.cash_equivalent
           or (category.is_roth and age >= category.withdrawal_min_age))
    }
    if not pool:
      return shortfall

    def compute_gross(category: AssetCategory, balance: int, net_target: int) -> tuple[int, int]:
      withdrawal = min(balance, net_target)
      return withdrawal, withdrawal

    return self._withdraw_proportional(finances, pool, shortfall, pool, compute_gross)

  def _cover_fallback_pool(
    self,
    finances: Finances,
    shortfall: int,
    year: int,
    age: int,
    cg_fraction: Decimal,
  ) -> int:
    """Pass 3: proportional fallback from any remaining eligible assets (without bracket cap).

    Prevents Cash from going negative while other assets still remain. Uses raw balances
    for proportioning (unlike pass 1 which uses effective balances).

    Returns updated shortfall.
    """
    pool = {
      category: balance
      for category, balance in finances.assets.items()
      if _is_withdrawal_eligible(category, balance, age)
    }
    if not pool:
      return shortfall

    def compute_gross(category: AssetCategory, balance: int, net_target: int) -> tuple[int, int]:
      if category.ordinary_income:
        gross, net_covered = _gross_up_ordinary(
            net_target, balance, finances.running_income, year, self.tax)
        finances.running_income += gross
        return gross, net_covered
      multiplier = _withdrawal_multiplier(
          category, self.tax, finances.running_income, year, cg_fraction)
      gross = min(balance, int(round(net_target * multiplier)))
      net_covered = int(round(gross / multiplier))
      return gross, net_covered

    return self._withdraw_proportional(finances, pool, shortfall, pool, compute_gross)
