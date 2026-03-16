"""Budget tracking by category, with a base-year snapshot and forward projection."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from functools import cache, cached_property
from typing import TypeAlias

from assets import AssetCategory
from rules import parse_rule, Rules


class BudgetCategory(Enum):
  """Budget categories with associated properties."""

  # Mortgage, rent, property taxes, homeowner's insurance, maintenance, home services.
  HOUSING = ('Housing', 0.03)

  # Electricity, gas, water, internet, phone.
  UTILITIES = ('Utilities', 0.04)

  # Vehicle purchases or payments, insurance, fuel, maintenance.
  TRANSPORTATION = ('Transportation', 0.04)

  # Groceries, restaurants, alcohol, snacks, desserts.
  FOOD = ('Food', 0.03)

  # Health insurance, medical and medication expenses.
  HEALTH = ('Health', 0.05)

  # Personal or children's tuition, supplies, room & board, after-school activities.
  SCHOOL = ('School', 0.04)

  # Child care (if not categorized as school), activities, supplies.
  CHILDREN = ('Children', 0.04)

  # Credit card and other debt payments not included in housing or transportation.
  DEBT = ('Debt', 0.0)

  # Expenses associated with operating a self-owned business.
  BUSINESS = ('Business', 0.0)

  # Any other expenses not included in the categories above.
  OTHER = ('Other', 0.03)

  # Contributions to asset classes.
  PRE_TAX_401K = ('Pre-Tax 401K', 0.02, AssetCategory.PLAN_401K)
  AFTER_TAX_401K = ('After-Tax 401K', 0.02, AssetCategory.PLAN_401K)
  ROTH_401K = ('Roth 401K', 0.02, AssetCategory.ROTH_401K)
  IRA = ('IRA', 0.02, AssetCategory.IRA)
  ROTH_IRA = ('Roth IRA', 0.02, AssetCategory.ROTH_IRA)
  PLAN_529 = ('529 Plan', 0.02, AssetCategory.PLAN_529)
  HSA = ('HSA', 0.02, AssetCategory.HSA)
  STOCKS = ('Stocks', 0.02, AssetCategory.STOCKS)
  BONDS = ('Bonds', 0.02, AssetCategory.BONDS)

  # Employer 401K match. Either a fixed dollar amount per year, or a percentage of the pre-tax
  # 401K contribution (e.g. '50%'). Not deducted from income.
  EMPLOYER_401K_MATCH = ('Employer 401K Match', 0.02, AssetCategory.PLAN_401K)

  def __init__(self, display_name: str, inflation: float, asset_category: 'AssetCategory | None' = None):
    self.display_name = display_name
    self.inflation = inflation
    self.asset_category = asset_category

  @staticmethod
  @cache
  def from_name(name: str) -> BudgetCategory:
    """Returns the BudgetCategory with the given display name.

    Raises:
      ValueError: If there is no budget category with the given name.
    """
    for cat in BudgetCategory:
      if cat.display_name == name:
        return cat
    raise ValueError(f'Unrecognized budget category "{name}".')

  @cached_property
  def is_pre_tax_contribution(self) -> bool:
    """True for budget categories that are pre-tax contributions reducing taxable income."""
    return self in {
      BudgetCategory.PRE_TAX_401K,
      BudgetCategory.IRA,
    }

  @cached_property
  def is_retirement_contribution(self) -> bool:
    """True for budget categories that represent contributions which stop at retirement."""
    return self in {
      BudgetCategory.PRE_TAX_401K,
      BudgetCategory.AFTER_TAX_401K,
      BudgetCategory.ROTH_401K,
      BudgetCategory.IRA,
      BudgetCategory.ROTH_IRA,
      BudgetCategory.PLAN_529,
      BudgetCategory.HSA,
      BudgetCategory.STOCKS,
      BudgetCategory.BONDS,
      BudgetCategory.EMPLOYER_401K_MATCH,
    }


BudgetDict: TypeAlias = dict[BudgetCategory, float]


def _parse_budget_category(name: str) -> BudgetCategory:
  """Parse a budget category by enum member name or display name.

  Tries the enum member name first (e.g. 'PRE_TAX_401K'), then the display name
  (e.g. 'Pre-Tax 401K').

  Raises:
    ValueError: If the name doesn't match any budget category.
  """
  try:
    return BudgetCategory[name.upper()]
  except KeyError:
    return BudgetCategory.from_name(name)


def _parse_fraction(value) -> float:
  """Parse a fraction value from a percentage string (e.g. '100%') or a plain number."""
  value_str = str(value).strip()
  if value_str.endswith('%'):
    return float(value_str[:-1]) / 100.0
  return float(value_str)


class Budget:
  """Budget tracking with a base-year snapshot and forward projection rules.

  Supports multiple budget categories with different inflation rates and custom projection rules
  for each category.
  """

  def __init__(self, base_year: int, data: dict, inflation=None):
    """Initialize from a scenario TOML [budget] data dict.

    Args:
      base_year: The snapshot year for the base amounts.
      data: Dict from the [budget] TOML section. Top-level keys are budget category names
          (either enum member names or display names), with numeric or string values. Reserved
          keys 'rules' and 'growth' are handled separately. Special keys:
            '529 Eligible': fraction of the School budget payable from a 529 plan, as a
                percentage string (e.g. '100%') or plain number (e.g. 1.0).
            'Employer 401K Match': either a plain percentage of the pre-tax 401K contribution
                (e.g. '50%'), a rule string (e.g. '=60000'), or a plain dollar amount.
            'growth': sub-dict of per-category inflation rate overrides, where values are
                percentages (e.g. 3 for 3%).
            'rules': list of per-year rule dicts, each with a 'year' key (int, "retirement",
                "retirement+N", or "retirement-N"). Retirement-relative rules apply to the year
                with the corresponding offset from retirement.
      inflation: Optional Inflation instance, providing inflation rates for each mapped category.
          Explicit 'growth' overrides in the scenario config take precedence over inflation rates.

    Raises:
      ValueError: If any key does not match a known BudgetCategory.
    """
    self.base_year = base_year

    # Base-year amounts by category.
    self._amounts: BudgetDict = {}

    # Per-category rules (calendar-year and retirement-relative).
    self._rules: defaultdict[BudgetCategory, Rules] = defaultdict(Rules)

    # Fraction of the School budget eligible to be paid from a 529 plan, by year.
    self._529_eligible: dict[int, float] = {}

    # Employer 401K match as a fraction of the employee's pre-tax 401K contribution, by year.
    # Only populated when the 'Employer 401K Match' value is a plain percentage (e.g. '50%').
    # Fixed dollar amounts use the EMPLOYER_401K_MATCH budget category instead.
    self._employer_match_fraction: dict[int, float] = {}

    # Per-category inflation rate overrides (fraction, e.g. 0.05 for 5%).
    self._inflation: dict[BudgetCategory, float] = {}

    for key, value in data.items():
      if key in ('rules', 'growth'):
        continue
      if key in ('529 Eligible', '529_eligible'):
        self._529_eligible[base_year] = _parse_fraction(value)
      elif key in ('Employer 401K Match', 'employer_401k_match'):
        self._load_employer_match(base_year, value, update_amounts=True)
      else:
        self._amounts[_parse_budget_category(key)] = float(value)

    for key, value in data.get('growth', {}).items():
      self._inflation[_parse_budget_category(key)] = float(value) / 100.0

    # Use historical averages for categories without an explicit override.
    if inflation:
      for category in BudgetCategory:
        if category not in self._inflation:
          average_rate = inflation.average_rate(category)
          if average_rate is not None:
            self._inflation[category] = average_rate

    for rule_entry in data.get('rules', []):
      year_spec = rule_entry['year']
      for key, value in rule_entry.items():
        if key == 'year':
          continue
        if key in ('529 Eligible', '529_eligible'):
          if Rules.is_retirement_spec(year_spec):
            raise ValueError('"529 Eligible" does not support retirement-relative years')
          self._529_eligible[int(year_spec)] = _parse_fraction(value)
        elif key in ('Employer 401K Match', 'employer_401k_match'):
          if Rules.is_retirement_spec(year_spec):
            raise ValueError('"Employer 401K Match" does not support retirement-relative years')
          self._load_employer_match(year_spec, value, update_amounts=False)
        else:
          category = _parse_budget_category(key)
          if rule := parse_rule(value):
            self._rules[category].add(year_spec, rule)

  def _load_employer_match(self, year_spec: str | int, value, update_amounts: bool) -> None:
    """Parse and store an Employer 401K Match value for the given year.

    A plain percentage (e.g. '50%') is stored as a fraction in _employer_match_fraction. When
    update_amounts is True (base-year data), also zeroes out the dollar amount in _amounts to
    prevent double-counting. A rule string or plain number sets the dollar-amount side and
    zeroes out the fraction.

    Args:
      year_spec: The year to associate the match with, as an int or plain integer string.
          Retirement-relative specs are not supported and should not be passed to this method.
      value: The raw TOML value (str or number).
      update_amounts: If True, also update _amounts (base-year context only).
    """
    year = int(year_spec)
    value_str = str(value).strip()
    if (isinstance(value, str)
        and value_str.endswith('%')
        and not value_str.startswith(('+', '-', '='))):
      # Plain percentage (e.g. '50%'): a fraction of the employee's pre-tax 401K contribution.
      self._employer_match_fraction[year] = float(value_str[:-1]) / 100.0
      if update_amounts:
        self._amounts[BudgetCategory.EMPLOYER_401K_MATCH] = 0.0
    elif isinstance(value, str) and (rule := parse_rule(value_str)):
      # Rule string (e.g. '=60000', '+5%'): sets the dollar-amount side.
      self._employer_match_fraction[year] = 0.0
      self._rules[BudgetCategory.EMPLOYER_401K_MATCH].add(year_spec, rule)
    else:
      # Plain number: fixed dollar match.
      self._employer_match_fraction[year] = 0.0
      if update_amounts:
        self._amounts[BudgetCategory.EMPLOYER_401K_MATCH] = float(value)
      else:
        if rule := parse_rule(value):
          self._rules[BudgetCategory.EMPLOYER_401K_MATCH].add(year_spec, rule)

  def advance(
    self,
    category: BudgetCategory,
    year: int,
    amount: float,
    inflation: float | None,
    retirement_year: int,
  ) -> float:
    """Advance a budget amount by one year, applying any rule at that year and an inflation rate.

    Args:
      category: The budget category.
      year: The target year (the year being stepped into, i.e. previous_year + 1).
      amount: The budget amount at the previous year.
      inflation: Inflation rate to apply if growth is not suppressed by a rule. Defaults to the
          category's configured rate (from the scenario's 'growth' overrides or the data-driven
          average from Inflation, falling back to the category's hardcoded default).
      retirement_year: The retirement start year.

    Returns:
      The budget amount for the given category in the given year.
    """
    if inflation is None:
      inflation = self._inflation.get(category, category.inflation)
    return self._rules[category].apply(amount, year, retirement_year, inflation)

  @cache
  def get_category(self, category: BudgetCategory, year: int, retirement_year: int) -> float:
    """Returns the amount for a category in a given year, defaulting to zero."""
    if year == self.base_year:
      return self._amounts.get(category, 0.0)
    if year > self.base_year:
      return self._project_category(category, year, retirement_year)
    return 0.0

  @cache
  def get_529_eligible_fraction(self, year: int) -> float:
    """Returns the fraction of the School budget eligible to be paid from a 529 plan.

    Uses step-function semantics: the last entry at or before the given year stays in effect
    until a newer entry overrides it. Returns 0.0 if no entry exists at or before that year.

    Args:
      year: The year to look up.

    Returns:
      A value between 0.0 and 1.0.
    """
    return Budget._step_function_lookup(self._529_eligible, year)

  @cache
  def get_employer_match_fraction(self, year: int) -> float:
    """Returns the employer 401K match as a fraction of the employee's pre-tax contribution.

    Uses step-function semantics: the last entry at or before the given year stays in effect
    until a newer entry overrides it. Returns 0.0 if no percentage entry exists at or before
    that year (i.e. a fixed dollar amount or no match is configured).

    Args:
      year: The year to look up.

    Returns:
      A value >= 0.0 (e.g. 0.5 for a 50% match).
    """
    return Budget._step_function_lookup(self._employer_match_fraction, year)

  @staticmethod
  def _step_function_lookup(data: dict[int, float], year: int) -> float:
    """Returns the value for the largest key in data that is still <= year, or 0.0."""
    eligible_years = [y for y in data if y <= year]
    if not eligible_years:
      return 0.0
    return data[max(eligible_years)]

  def _project_category(self, category: BudgetCategory, year: int, retirement_year: int) -> float:
    """Returns the projected budget for a category in a future year.

    Applies rules in order from the base year to the target year. Default inflation is
    always applied unless a rule explicitly suppresses it (rule.apply_growth=False).

    Args:
      category: The budget category to project.
      year: The target year for the projection.
      retirement_year: The retirement start year.

    Returns:
      The projected budget amount for the category in the given year.
    """
    amount = self._amounts.get(category, 0.0)
    inflation = self._inflation.get(category, category.inflation)
    for i in range(self.base_year + 1, year + 1):
      amount = self.advance(category, i, amount, inflation, retirement_year)
    return amount
