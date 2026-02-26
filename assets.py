"""Asset tracking by category, with historical data and forward projection."""

from __future__ import annotations

import csv

from collections import defaultdict
from enum import Enum
from functools import cache

from rules import Rule, parse_rule


# CSV columns that are always ignored during parsing (e.g. human-readable notes).
_IGNORED_COLUMNS = {'Year', 'Notes'}


class AssetCategory(Enum):
  """Asset categories with associated properties."""

  CASH = ('Cash', 0.03)
  PLAN_401K = ('401K', 0.07)
  ROTH_401K = ('Roth 401K', 0.07)
  IRA = ('IRA', 0.08)
  ROTH_IRA = ('Roth IRA', 0.08)
  STOCKS = ('Stocks', 0.08)
  BONDS = ('Bonds', 0.04)
  PLAN_529 = ('529 Plan', 0.07)
  HSA = ('HSA', 0.06)
  REAL_ESTATE = ('Real Estate', 0.03)

  def __init__(self, display_name: str, growth: float):
    self.display_name = display_name
    self.growth = growth

  @staticmethod
  @cache
  def from_name(name: str) -> AssetCategory:
    """Returns the AssetCategory with the given display name.

    Raises:
      ValueError: If there is no asset category with the given name.
    """
    for cat in AssetCategory:
      if cat.display_name == name:
        return cat
    raise ValueError(f'Unrecognized asset category "{name}".')

  @property
  def is_roth(self) -> bool:
    """True for Roth accounts (tax-free growth and withdrawals)."""
    return self in {AssetCategory.ROTH_401K, AssetCategory.ROTH_IRA}

  @property
  def is_reserved(self) -> bool:
    """True for accounts reserved for specific uses and excluded from general withdrawal pools."""
    return self in {AssetCategory.HSA, AssetCategory.PLAN_529, AssetCategory.REAL_ESTATE}

  @property
  def subject_to_rmd(self) -> bool:
    """True for accounts subject to Required Minimum Distributions."""
    return self in {AssetCategory.PLAN_401K, AssetCategory.IRA}

  @property
  def withdrawal_min_age(self) -> int:
    """Minimum age for penalty-free withdrawals, or 0 if there is no restriction.

    Based on the standard 59½ rule, using 59 as the annual proxy (you will be 59½ sometime
    during the year you are 59). RMDs are mandatory and are never blocked by this check.
    """
    if self in {AssetCategory.PLAN_401K, AssetCategory.IRA,
                AssetCategory.ROTH_401K, AssetCategory.ROTH_IRA}:
      return 59
    return 0

  @property
  def cash_equivalent(self) -> bool:
    """True for liquid, tax-free-on-withdrawal accounts treated as cash in withdrawal pools."""
    return self in {AssetCategory.CASH, AssetCategory.BONDS}

  @property
  def ordinary_income(self) -> bool:
    """True if withdrawals from this account are taxed as ordinary income."""
    return self in {AssetCategory.PLAN_401K, AssetCategory.IRA}

  @property
  def capital_gains(self) -> bool:
    """True if withdrawals from this account include a capital gains component."""
    return self == AssetCategory.STOCKS

  @property
  def tracks_sp500(self) -> bool:
    """True if this account's growth tracks the S&P 500 rather than a fixed rate."""
    return self in {
      AssetCategory.STOCKS,
      AssetCategory.PLAN_401K,
      AssetCategory.ROTH_401K,
      AssetCategory.IRA,
      AssetCategory.ROTH_IRA,
      AssetCategory.PLAN_529,
      AssetCategory.HSA,
    }


class Assets:
  """Asset tracking with historical data and projection rules.

  Supports multiple asset categories with different growth rates and custom projection rules for
  each category.
  """

  def __init__(self, path: str, growth: dict[str, float] | None = None):
    """Initialize and load historical asset data from a CSV file.

    Args:
      path: Path to the CSV file containing historical asset data.
      growth: Optional per-category growth rate overrides, keyed by enum member name
          (e.g. 'roth_401k') with values as fractions (e.g. 0.05 for 5%). Overrides the default
          growth rate on the AssetCategory enum for projection and pre-retirement growth.

    Raises:
      ValueError: If any key in growth does not match a known AssetCategory name.
    """
    # Historical data: {year: {category: amount}}
    self._historical: dict[int, dict[AssetCategory, float]] = {}

    # Latest year with historical data
    self._last_historical_year: int | None = None

    # Rules mapping from (category, year) to rule
    self._rules: defaultdict[AssetCategory, dict[int, Rule]] = defaultdict(dict)

    # Per-category growth rate overrides (fraction, e.g. 0.05 for 5%).
    self._growth: dict[AssetCategory, float] = {}

    if growth:
      for key, value in growth.items():
        try:
          category = AssetCategory[key.upper()]
        except KeyError:
          raise ValueError(f'Unknown asset category in growth overrides: "{key}"')
        self._growth[category] = value

    self._load_csv(path)

  @cache
  def get_category(self, category: AssetCategory, year: int) -> float:
    """Returns the amount for a category in a given year, defaulting to zero."""
    if year in self._historical and category in self._historical[year]:
      return self._historical[year][category]
    if self._last_historical_year and year > self._last_historical_year:
      return self._project_category(category, year)
    return 0.0

  @cache
  def get_total(self, year: int) -> float:
    """Returns the total assets across all categories for a specific year."""
    if year in self._historical:
      categories = self._historical[year].keys()
    elif self._last_historical_year and year > self._last_historical_year:
      # For future years, use categories from the last historical year.
      categories = self._historical.get(self._last_historical_year, {}).keys()
    else:
      return 0.0

    return sum(self.get_category(category, year) for category in categories)

  def _load_csv(self, path: str) -> None:
    """Load historical asset data from the given CSV file path.

    Each non-Year column names an asset category. Values are interpreted as rules if they parse
    as one (e.g. '+3%', '=20000'), or as fixed historical amounts otherwise. A row advances
    _last_historical_year only if it contains at least one fixed amount.

    Expected format:
      Year,Cash,401K,...
      2025,10000,500000
      2026,+3%,+5%
      2027,,=600000
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

          category = AssetCategory.from_name(col_name)
          if rule := parse_rule(year, value):
            self._rules[category][year] = rule
          else:
            year_data[category] = float(value)

        if year_data:
          self._historical[year] = year_data
          if not self._last_historical_year or year > self._last_historical_year:
            self._last_historical_year = year

  def apply_year(
    self, category: AssetCategory, year: int, amount: float, growth_rate: float | None = None
  ) -> float:
    """Apply one year's rule (if any) and growth to an asset balance.

    This is used by the simulation loops to advance each category's balance by a single year,
    respecting any rules defined for that year. Unlike _project_category, it operates on an
    externally-supplied balance rather than replaying from historical data — so it correctly
    handles balances that have been modified by income, withdrawals, and contributions.

    Args:
      category: The asset category being advanced.
      year: The year being applied (rules for this year are consulted).
      amount: The current balance before this year's rule and growth.
      growth_rate: Growth rate to apply. Defaults to category.growth if not specified. Pass an
          explicit rate (e.g. S&P 500 return) to override the default for stock-like assets.

    Returns:
      The updated balance after applying any rule and growth.
    """
    rate = growth_rate if growth_rate is not None else self._growth.get(category, category.growth)
    rule = self._rules.get(category, {}).get(year)
    if rule:
      amount = rule.apply(amount)
      if rule.apply_growth:
        amount *= 1 + rate
    else:
      amount *= 1 + rate
    return amount

  def _project_category(self, category: AssetCategory, year: int) -> float:
    """Returns the projected assets for a category in a future year.

    Applies rules in order from the last historical year to the target year, delegating each
    year's step to apply_year(). Default growth is always applied unless a rule suppresses it.

    Args:
      category: The asset category to project.
      year: The target year for the projection.

    Returns:
      The projected asset amount for the category in the given year.
    """
    if not self._last_historical_year:
      return 0.0

    amount = self._historical.get(self._last_historical_year, {}).get(category, 0.0)
    for i in range(self._last_historical_year + 1, year + 1):
      amount = self.apply_year(category, i, amount)
    return amount
