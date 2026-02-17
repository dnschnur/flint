"""Asset tracking by category, with historical data and forward projection."""

from __future__ import annotations

import csv

from collections import defaultdict
from enum import Enum
from functools import cache

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


class Assets:
  """Asset tracking with historical data and projection rules.

  Supports multiple asset categories with different growth rates and custom projection rules for
  each category.
  """

  def __init__(self, path: str):
    """Initialize and load historical asset data from a CSV file.

    Args:
      path: Path to the CSV file containing historical asset data.
    """
    # Historical data: {year: {category: amount}}
    self._historical: dict[int, dict[AssetCategory, float]] = {}

    # Latest year with historical data
    self._last_historical_year: int | None = None

    # Rules mapping from (category, year) to rule
    self._rules: defaultdict[AssetCategory, dict[int, Rule]] = defaultdict(dict)

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

    Expected format:
      Year,Cash,Stocks,Cash Rules,Stocks Rules,...
      2020,10000,50000,,
      2021,12000,55000,+5%,+10%
      2022,,,+5%,+10%
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        year = int(row['Year'])
        year_data = {}

        for col_name, value in row.items():
          if col_name == 'Year':
            continue

          if col_name.endswith(' Rules'):
            category_name = col_name[:-6]  # Remove ' Rules' suffix
            category = AssetCategory.from_name(category_name)
            if rule := parse_rule(year, value):
              self._rules[category][year] = rule
          elif value.strip():
            category = AssetCategory.from_name(col_name)
            year_data[category] = float(value)

        if year_data:
          self._historical[year] = year_data
          if not self._last_historical_year or year > self._last_historical_year:
            self._last_historical_year = year

  def _project_category(self, category: AssetCategory, year: int) -> float:
    """Returns the projected assets for a category in a future year.

    Applies rules in order from the last historical year to the target year.

    If no rule applies for a year, applies the default growth rate.

    Args:
      category: The asset category to project.
      year: The target year for the projection.

    Returns:
      The projected asset amount for the category in the given year.
    """
    if not self._last_historical_year:
      return 0.0

    amount = self._historical.get(self._last_historical_year, {}).get(category, 0.0)
    category_rules = self._rules.get(category, {})

    # Project year by year, applying rules or default growth
    for i in range(self._last_historical_year + 1, year + 1):
      rule = category_rules.get(i)
      amount = rule.apply(amount) if rule else amount * (1 + category.growth)

    return amount
