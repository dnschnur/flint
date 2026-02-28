"""Asset tracking by category, with a base-year snapshot and forward projection."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from functools import cache, cached_property
from typing import TypeAlias

from rules import Rule, parse_rule


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

  @cached_property
  def is_roth(self) -> bool:
    """True for Roth accounts (tax-free growth and withdrawals)."""
    return self in {AssetCategory.ROTH_401K, AssetCategory.ROTH_IRA}

  @cached_property
  def is_reserved(self) -> bool:
    """True for accounts reserved for specific uses and excluded from general withdrawal pools."""
    return self in {AssetCategory.HSA, AssetCategory.PLAN_529, AssetCategory.REAL_ESTATE}

  @cached_property
  def subject_to_rmd(self) -> bool:
    """True for accounts subject to Required Minimum Distributions."""
    return self in {AssetCategory.PLAN_401K, AssetCategory.IRA}

  @cached_property
  def withdrawal_min_age(self) -> int:
    """Minimum age for penalty-free withdrawals, or 0 if there is no restriction.

    Based on the standard 59½ rule, using 59 as the annual proxy (you will be 59½ sometime
    during the year you are 59). RMDs are mandatory and are never blocked by this check.
    """
    if self in {AssetCategory.PLAN_401K, AssetCategory.IRA,
                AssetCategory.ROTH_401K, AssetCategory.ROTH_IRA}:
      return 59
    return 0

  @cached_property
  def cash_equivalent(self) -> bool:
    """True for liquid, tax-free-on-withdrawal accounts treated as cash in withdrawal pools."""
    return self in {AssetCategory.CASH, AssetCategory.BONDS}

  @cached_property
  def ordinary_income(self) -> bool:
    """True if withdrawals from this account are taxed as ordinary income."""
    return self in {AssetCategory.PLAN_401K, AssetCategory.IRA}

  @cached_property
  def capital_gains(self) -> bool:
    """True if withdrawals from this account include a capital gains component."""
    return self == AssetCategory.STOCKS

  @cached_property
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


AssetDict: TypeAlias = dict[AssetCategory, float]
AssetDefaultDict: TypeAlias = defaultdict[AssetCategory, float]


def _parse_asset_category(name: str) -> AssetCategory:
  """Parse an asset category by enum member name or display name.

  Tries the enum member name first (e.g. 'PLAN_401K'), then the display name (e.g. '401K').

  Raises:
    ValueError: If the name doesn't match any asset category.
  """
  try:
    return AssetCategory[name.upper()]
  except KeyError:
    return AssetCategory.from_name(name)


class Assets:
  """Asset tracking with a base-year snapshot and forward projection rules.

  Supports multiple asset categories with different growth rates and custom projection rules for
  each category.
  """

  def __init__(self, base_year: int, data: dict):
    """Initialize from a scenario TOML [assets] data dict.

    Args:
      base_year: The snapshot year for the base amounts.
      data: Dict from the [assets] TOML section. Top-level keys are asset category names
          (either enum member names like 'PLAN_401K' or display names like '401K'), with numeric
          values for the base-year balance. Reserved keys:
            'rules': list of per-year rule dicts, each with a 'year' int key and category keys
                whose string values are rule strings (e.g. '+900000', '=2300000').
            'growth': sub-dict of per-category growth rate overrides, where values are
                percentages (e.g. 0 for 0%, 7 for 7%).

    Raises:
      ValueError: If any key does not match a known AssetCategory.
    """
    self.base_year = base_year

    # Base-year amounts by category.
    self._amounts: AssetDict = {}

    # Rules mapping from (category, year) to rule.
    self._rules: defaultdict[AssetCategory, dict[int, Rule]] = defaultdict(dict)

    # Per-category growth rate overrides (fraction, e.g. 0.05 for 5%).
    self._growth: dict[AssetCategory, float] = {}

    for key, value in data.items():
      if key in ('rules', 'growth'):
        continue
      self._amounts[_parse_asset_category(key)] = float(value)

    for key, value in data.get('growth', {}).items():
      self._growth[_parse_asset_category(key)] = float(value) / 100.0

    for rule_entry in data.get('rules', []):
      year = int(rule_entry['year'])
      for key, value in rule_entry.items():
        if key == 'year':
          continue
        if rule := parse_rule(value):
          self._rules[_parse_asset_category(key)][year] = rule

  @cache
  def get_category(self, category: AssetCategory, year: int) -> float:
    """Returns the amount for a category in a given year, defaulting to zero."""
    if year > self.base_year:
      return self._project_category(category, year)
    return self._amounts.get(category, 0.0)

  @cache
  def get_total(self, year: int) -> float:
    """Returns the total assets across all categories for a specific year."""
    return sum(self.get_category(category, year) for category in self._amounts)

  def apply_year(
    self, category: AssetCategory, year: int, amount: float, growth_rate: float | None = None
  ) -> float:
    """Apply one year's rule (if any) and growth to an asset balance.

    This is used by the simulation loops to advance each category's balance by a single year,
    respecting any rules defined for that year. Unlike _project_category, it operates on an
    externally-supplied balance rather than replaying from the base year — so it correctly
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

    Applies rules in order from the base year to the target year, delegating each year's step
    to apply_year(). Default growth is always applied unless a rule suppresses it.

    Args:
      category: The asset category to project.
      year: The target year for the projection.

    Returns:
      The projected asset amount for the category in the given year.
    """
    amount = self._amounts.get(category, 0.0)
    for i in range(self.base_year + 1, year + 1):
      amount = self.apply_year(category, i, amount)
    return amount
