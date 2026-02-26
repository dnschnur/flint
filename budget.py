"""Budget tracking by category, with historical data and forward projection."""

from __future__ import annotations

import csv

from collections import defaultdict
from enum import Enum
from functools import cache

from assets import AssetCategory
from rules import Rule, parse_rule


# CSV columns that are always ignored during parsing (e.g. human-readable notes).
_IGNORED_COLUMNS = {'Year', 'Notes'}


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

  @property
  def is_pre_tax_contribution(self) -> bool:
    """True for budget items that are pre-tax contributions reducing taxable income."""
    return self in {
      BudgetCategory.PRE_TAX_401K,
      BudgetCategory.IRA,
    }

  @property
  def is_retirement_contribution(self) -> bool:
    """True for budget items that represent contributions which stop at retirement."""
    return self in {
      BudgetCategory.PRE_TAX_401K,
      BudgetCategory.AFTER_TAX_401K,
      BudgetCategory.ROTH_401K,
      BudgetCategory.IRA,
      BudgetCategory.ROTH_IRA,
      BudgetCategory.PLAN_529,
      BudgetCategory.HSA,
      BudgetCategory.EMPLOYER_401K_MATCH,
    }


class Budget:
  """Budget tracking with historical data and projection rules.

  Supports multiple budget categories with different inflation rates and custom projection rules for
  each category.
  """

  def __init__(self, path: str, inflation: dict[str, float] | None = None):
    """Initialize and load historical budget data from a CSV file.

    Args:
      path: Path to the CSV file containing historical budget data.
      inflation: Optional per-category inflation rate overrides, keyed by enum member name
          (e.g. 'housing') with values as fractions (e.g. 0.05 for 5%). Overrides the default
          inflation rate on the BudgetCategory enum when projecting future years.

    Raises:
      ValueError: If any key in inflation does not match a known BudgetCategory name.
    """
    # Historical data: {year: {category: amount}}
    self._historical: dict[int, dict[BudgetCategory, float]] = {}

    # Latest year with historical data
    self._last_historical_year: int | None = None

    # Rules mapping from (category, year) to rule
    self._rules: defaultdict[BudgetCategory, dict[int, Rule]] = defaultdict(dict)

    # Fraction of the School budget eligible to be paid from a 529 plan, by year.
    # Unlike historical data, entries here do not advance _last_historical_year.
    self._529_eligible: dict[int, float] = {}

    # Employer 401K match as a fraction of the employee's pre-tax 401K contribution, by year.
    # Only populated when the 'Employer 401K Match' column has a plain percentage (e.g. '50%').
    # Fixed dollar amounts use the EMPLOYER_401K_MATCH budget category instead.
    self._employer_match_fraction: dict[int, float] = {}

    # Per-category inflation rate overrides (fraction, e.g. 0.05 for 5%).
    self._inflation: dict[BudgetCategory, float] = {}

    if inflation:
      for key, value in inflation.items():
        try:
          category = BudgetCategory[key.upper()]
        except KeyError:
          raise ValueError(f'Unknown budget category in inflation overrides: "{key}"')
        self._inflation[category] = value

    self._load_csv(path)

  @cache
  def get_category(self, category: BudgetCategory, year: int) -> float:
    """Returns the amount for a category in a given year, defaulting to zero."""
    if year in self._historical and category in self._historical[year]:
      return self._historical[year][category]
    if self._last_historical_year and year > self._last_historical_year:
      return self._project_category(category, year)
    return 0.0

  @cache
  def get_total(self, year: int) -> float:
    """Returns the total budget across all categories for a specific year."""
    if year in self._historical:
      categories = self._historical[year].keys()
    elif self._last_historical_year and year > self._last_historical_year:
      # For future years, use categories from the last historical year.
      categories = self._historical.get(self._last_historical_year, {}).keys()
    else:
      return 0.0

    return sum(self.get_category(category, year) for category in categories)

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
    fraction = 0.0
    for entry_year, entry_fraction in self._529_eligible.items():
      if entry_year <= year:
        fraction = entry_fraction
    return fraction

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
    fraction = 0.0
    for entry_year, entry_fraction in self._employer_match_fraction.items():
      if entry_year <= year:
        fraction = entry_fraction
    return fraction

  def _load_csv(self, path: str) -> None:
    """Load historical budget data from the given CSV file path.

    Each non-Year column names a budget category, except for the special '529 Eligible' column.
    Values are interpreted as rules if they parse as one (e.g. '+3%', '=20000'), or as fixed
    historical amounts otherwise. A row advances _last_historical_year only if it contains at
    least one fixed amount.

    Expected format:
      Year,Housing,Health,529 Eligible,...
      2025,30000,8000,
      2030,,,-10%
      2033,,,100%
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        year = int(row['Year'])
        year_data = {}

        for col_name, value in row.items():
          if col_name in _IGNORED_COLUMNS:
            continue

          value = value.strip()
          if not value:
            continue

          if col_name == '529 Eligible':
            # Fraction of the School budget payable from a 529 plan.
            # Does not count as historical data; does not advance _last_historical_year.
            fraction = float(value[:-1]) / 100.0 if value.endswith('%') else float(value)
            self._529_eligible[year] = fraction
          elif col_name == 'Employer 401K Match':
            # To prevent double-counting when switching between types, each form zeroes out the
            # other for that year: a percentage stores 0.0 as a historical dollar amount, and a
            # dollar amount/rule records 0.0 in _employer_match_fraction.
            if value.endswith('%') and not value.startswith(('+', '-', '=')):
              # Plain percentage (e.g. '50%'): a fraction of the employee's pre-tax 401K
              # contribution. Checked before parse_rule because parse_rule also matches
              # bare percentages as AdjustByPercentage rules.
              fraction = float(value[:-1]) / 100.0
              self._employer_match_fraction[year] = fraction
              year_data[BudgetCategory.EMPLOYER_401K_MATCH] = 0.0
            elif rule := parse_rule(year, value):
              self._employer_match_fraction[year] = 0.0
              self._rules[BudgetCategory.EMPLOYER_401K_MATCH][year] = rule
            else:
              self._employer_match_fraction[year] = 0.0
              year_data[BudgetCategory.EMPLOYER_401K_MATCH] = float(value)
          else:
            category = BudgetCategory.from_name(col_name)
            if rule := parse_rule(year, value):
              self._rules[category][year] = rule
            else:
              year_data[category] = float(value)

        if year_data:
          self._historical[year] = year_data
          if not self._last_historical_year or year > self._last_historical_year:
            self._last_historical_year = year

  def _project_category(self, category: BudgetCategory, year: int) -> float:
    """Returns the projected budget for a category in a future year.

    Applies rules in order from the last historical year to the target year. Default inflation is
    always applied unless a rule explicitly suppresses it (rule.apply_growth=False).

    Args:
      category: The budget category to project.
      year: The target year for the projection.

    Returns:
      The projected budget amount for the category in the given year.
    """
    if not self._last_historical_year:
      return 0.0

    amount = self._historical.get(self._last_historical_year, {}).get(category, 0.0)
    category_rules = self._rules.get(category, {})
    inflation = self._inflation.get(category, category.inflation)

    # Project year by year, applying rules and/or default inflation.
    # If a rule exists, apply it; then apply inflation unless the rule suppresses it.
    # If no rule exists, apply inflation unconditionally.
    for i in range(self._last_historical_year + 1, year + 1):
      rule = category_rules.get(i)
      if rule:
        amount = rule.apply(amount)
        if rule.apply_growth:
          amount *= 1 + inflation
      else:
        amount *= 1 + inflation

    return amount
