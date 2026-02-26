"""Income and budget allocation strategy for retirement simulations.

Defines how income, budget, and RMDs are applied to assets each year, both during the pre-retirement
accumulation phase and the retirement drawdown phase.
"""

from collections import defaultdict

from assets import AssetCategory
from budget import BudgetCategory
from rmd import RMD
from tax import Tax


# Pre-retirement liquid asset drawdown priority order (Cash first, then Bonds, then Stocks).
_LIQUID_ASSETS = (
  AssetCategory.CASH,
  AssetCategory.BONDS,
  AssetCategory.STOCKS,
)


def _is_withdrawal_eligible(category: AssetCategory, balance: float, age: int) -> bool:
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
  net: float,
  balance: float,
  running_income: float,
  year: int,
  tax: Tax,
  bracket_cap: bool = False
) -> tuple[float, float]:
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
  gross = tax.gross_for_net_ordinary(net, running_income, year)
  if bracket_cap:
    bracket_remaining = tax.next_ordinary_bracket_threshold(running_income, year) - running_income
    gross = min(gross, bracket_remaining, balance)
  else:
    gross = min(gross, balance)
  net_covered = gross - tax.incremental_ordinary_tax(running_income, gross, year)
  return gross, net_covered


def _withdrawal_multiplier(
  category: AssetCategory,
  tax: Tax,
  taxable_income: float,
  year: int,
  cg_fraction: float
) -> float:
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
    return 1.0 + cg_fraction * rate
  if category.ordinary_income:
    rate = tax.marginal_rate(taxable_income, year, capital_gains=False)
    return 1.0 + rate
  return 1.0


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
  budget and available HSA balance. HSA withdrawals for qualified medical expenses are
  tax-free, so no gross-up is applied.

  Modifies new_assets in place and returns the amount withdrawn.

  Args:
    new_assets: Current asset balances (modified in place).
    budget: Budget amounts by category for the year.
    shortfall: The current funding shortfall to reduce.

  Returns:
    The amount withdrawn from the HSA.
  """
  health_expenses = budget.get(BudgetCategory.HEALTH, 0.0)
  if not health_expenses:
    return 0.0
  withdrawal = min(health_expenses, new_assets[AssetCategory.HSA], shortfall)
  if withdrawal:
    new_assets[AssetCategory.HSA] -= withdrawal
  return withdrawal


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
    assets: dict[AssetCategory, float],
    income: float,
    budget: dict[BudgetCategory, float],
    retired: bool = False,
    age: int = 0,
    eligible_529: float = 0.0,
    cg_fraction: float = 0.0,
    employer_match_fraction: float = 0.0
  ) -> defaultdict[AssetCategory, float]:
    """Returns updated asset values after applying income, tax, and budget for the year.

    Processing order:
      1. Calculate and withdraw RMDs from applicable accounts (adds to income)
      2. Make pre-tax contributions (reduces taxable income)
      3. Apply ordinary income tax on post-contribution income
      4. Withdraw from 529 to cover 529-eligible school expenses (always, to avoid waste)
      5. Process remaining budget items (expenses and after-tax contributions)
      6. If there's a shortfall:
         a. Withdraw from HSA to cover health expenses (tax-free)
         b. Cover any remaining shortfall:
            - Pre-retirement: from Cash → Bonds → Stocks
            - Retirement: proportionally from non-Cash, non-reserved assets, grossed up for
              tax. Any uncovered remainder falls to Cash, which may go negative.

    During pre-retirement (retired=False):
      - Pre-tax contributions are made and income is taxed on the remainder
      - Remaining post-tax income covers expenses; surplus goes to cash
      - If expenses exceed post-tax income, draws from liquid assets (no tax gross-up)

    During retirement (retired=True):
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
          0.0 pre-retirement, ramping from 0.0 to 1.0 linearly over retirement.
      employer_match_fraction: Employer 401K match as a fraction of the employee's pre-tax
          401K contribution (e.g. 0.5 for a 50% match). Applied pre-retirement only. Added
          directly to the pre-tax 401K balance without affecting taxable income.

    Returns:
      Updated asset values after applying income and budget.

    Raises:
      ValueError: If pre-retirement shortfall cannot be covered by liquid assets.
    """
    # Start with a copy of current assets, defaulting missing categories to 0.0.
    new_assets: defaultdict[AssetCategory, float] = defaultdict(float, assets)

    # Calculate and withdraw RMDs first; they count as ordinary income.
    rmd_income = 0.0
    for asset_category in AssetCategory:
      if asset_category.subject_to_rmd and new_assets[asset_category] > 0:
        rmd_amount = self.rmd.calculate(age, new_assets[asset_category])
        if rmd_amount > 0:
          new_assets[asset_category] -= rmd_amount
          rmd_income += rmd_amount

    remaining = income + rmd_income

    # Make pre-tax contributions first (pre-retirement only).
    # These reduce taxable income since they come out of gross income before tax.
    if not retired:
      for category, amount in budget.items():
        if category.is_pre_tax_contribution:
          new_assets[category.asset_category] += amount
          remaining -= amount

      # Apply employer 401K match. This does not affect taxable income.
      if employer_match_fraction:
        pre_tax_401k = budget.get(BudgetCategory.PRE_TAX_401K, 0.0)
        new_assets[AssetCategory.PLAN_401K] += pre_tax_401k * employer_match_fraction

    # Apply ordinary income tax on the post-contribution income.
    # Track taxable_income for use in withdrawal gross-up calculations later.
    taxable_income = remaining
    remaining -= self.tax.calculate(taxable_income, year)

    # Process remaining budget items (expenses and after-tax contributions).
    for category, amount in budget.items():
      if category == BudgetCategory.EMPLOYER_401K_MATCH:
        new_assets[AssetCategory.PLAN_401K] += amount
        continue
      if category.is_pre_tax_contribution:
        continue  # Already handled previously
      if retired and category.is_retirement_contribution:
        continue  # No contributions during retirement

      if category.asset_category:
        new_assets[category.asset_category] += amount
      remaining -= amount

    # Always withdraw 529-eligible school expenses from the 529 plan, regardless of whether income
    # covers them. This prevents 529 assets from being wasted if they aren't needed for general
    # expenses. The withdrawal is credited back to remaining.
    remaining += _apply_529_withdrawal(new_assets, budget, eligible_529)

    # If remaining is negative, we need to withdraw from assets.
    if remaining < 0:
      shortfall = -remaining

      # HSA covers health expenses first (tax-free, no gross-up).
      shortfall -= _apply_hsa_withdrawal(new_assets, budget, shortfall)

      if not retired:
        # Pre-retirement: withdraw from liquid assets in priority order.
        if shortfall:
          for asset_category in _LIQUID_ASSETS:
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
        # Retirement shortfall withdrawal order:
        #   1. Proportional from taxable pool (401K, IRA, Stocks), grossed up for tax.
        #      Ordinary income (401K/IRA) withdrawals are capped at the federal bracket
        #      boundary; uncovered net stays in shortfall for the tax-free pass.
        #   2. Proportional from tax-free pool (Bonds, Cash, Roth): none of these add taxable
        #      income on withdrawal, so drawing them covers bracket-diverted shortfall without
        #      pushing income into the next bracket.
        #   3. Fallback: remaining non-reserved assets without bracket cap, to avoid negative
        #      Cash while other assets still remain.
        #   4. Cash as final fallback (may go negative).

        # Pass 1: Proportional from taxable pool (401K, IRA, Stocks). Bonds, Cash, and Roth
        # are excluded as tax-free sources handled in pass 2. Each asset is grossed up for
        # tax so proportional allocation is based on effective (post-tax) balances.
        general_pool = {
          category: balance
          for category, balance in new_assets.items()
          if _is_withdrawal_eligible(category, balance, age)
          and category != AssetCategory.BONDS
        }

        # Compute each asset's effective (post-tax) balance for proportional allocation.
        # Ordinary income accounts (401K/IRA) use exact incremental tax against the full
        # balance, so bracket-crossing is correctly reflected in the proportions.
        # CG accounts use the multiplier approximation.
        effective_pool = {}
        cg_multipliers = {}
        for category, balance in general_pool.items():
          if category.ordinary_income:
            incremental_tax = self.tax.incremental_ordinary_tax(taxable_income, balance, year)
            effective_pool[category] = balance - incremental_tax
          else:
            multiplier = _withdrawal_multiplier(
                category, self.tax, taxable_income, year, cg_fraction)
            effective_pool[category] = balance / multiplier
            cg_multipliers[category] = multiplier
        total_effective = sum(effective_pool.values())

        running_income = taxable_income
        if total_effective:
          # Allocate proportionally by effective balance so each asset contributes equally
          # in post-tax terms. For ordinary income accounts, gross up using a running income
          # total so that each successive withdrawal is taxed at the correct bracket.
          original_shortfall = shortfall
          for category, balance in general_pool.items():
            effective_balance = effective_pool[category]
            proportion = effective_balance / total_effective
            net_needed = min(effective_balance, original_shortfall * proportion)
            if category.ordinary_income:
              # Cap at the bracket boundary (to avoid paying the higher rate) and at the available
              # balance. Leave any uncovered net in shortfall for the tax-free and fallback passes.
              gross_withdrawal, net_covered = _gross_up_ordinary(
                net_needed, balance, running_income, year, self.tax, bracket_cap=True)
              shortfall -= net_covered
              running_income += gross_withdrawal
            else:
              gross_withdrawal = net_needed * cg_multipliers[category]
              shortfall -= net_needed
            new_assets[category] = balance - gross_withdrawal

        # Pass 2: Proportional from tax-free pool (Bonds, Cash, Roth). None of these add
        # taxable income on withdrawal, so drawing them proportionally covers bracket-diverted
        # shortfall from pass 1 without pushing income into the next bracket.
        if shortfall > 0:
          tax_free_pool = {}
          for category, balance in new_assets.items():
            if category == AssetCategory.BONDS and balance > 0:
              tax_free_pool[category] = balance
            elif category == AssetCategory.CASH and balance > 0:
              tax_free_pool[category] = balance
            elif (category.is_roth and balance > 0
                  and age >= category.withdrawal_min_age):
              tax_free_pool[category] = balance
          total_tax_free = sum(tax_free_pool.values())
          if total_tax_free > 0:
            original_shortfall = shortfall
            for category, balance in tax_free_pool.items():
              proportion = balance / total_tax_free
              withdrawal = min(balance, original_shortfall * proportion)
              new_assets[category] -= withdrawal
              shortfall -= withdrawal

        # Pass 3: Fallback — draw proportionally from any remaining non-reserved, non-Roth,
        # non-Cash assets without bracket cap. Prevents Cash from going negative while other
        # assets still remain.
        if shortfall:
          fallback_pool = {
            category: balance
            for category, balance in new_assets.items()
            if _is_withdrawal_eligible(category, balance, age)
          }
          total_fallback = sum(fallback_pool.values())
          if total_fallback:
            original_shortfall = shortfall
            for category, balance in fallback_pool.items():
              proportion = balance / total_fallback
              net_target = original_shortfall * proportion
              if category.ordinary_income:
                gross_withdrawal, net_covered = _gross_up_ordinary(
                  net_target, balance, running_income, year, self.tax)
                running_income += gross_withdrawal
              else:
                multiplier = _withdrawal_multiplier(
                  category, self.tax, running_income, year, cg_fraction)
                gross_withdrawal = min(balance, net_target * multiplier)
                net_covered = gross_withdrawal / multiplier
              new_assets[category] = balance - gross_withdrawal
              shortfall -= net_covered

        # Any remaining shortfall comes from Cash (may go negative).
        remaining = -shortfall

    new_assets[AssetCategory.CASH] += remaining

    return new_assets
