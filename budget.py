"""Budget tracking by category, with historical data and forward projection."""

from __future__ import annotations

import csv

from collections import defaultdict
from enum import Enum
from functools import cache

from rules import Rule, parse_rule


class BudgetCategory(Enum):
  """Budget categories with associated properties."""

  HOUSING = ('Housing', 0.03)
  HEALTH = ('Health', 0.05)
  SCHOOL = ('School', 0.04)
  FOOD = ('Food', 0.03)
  PRE_TAX_401K = ('Pre-Tax 401K', 0.02)
  AFTER_TAX_401K = ('After-Tax 401K', 0.02)
  PRE_TAX_ROTH_401K = ('Pre-Tax 401K (Roth)', 0.02)
  AFTER_TAX_ROTH_401K = ('After-Tax 401K (Roth)', 0.02)
  IRA = ('IRA', 0.02)
  ROTH_IRA = ('Roth IRA', 0.02)
  PLAN_529 = ('529 Plan', 0.02)
  HSA = ('HSA', 0.02)
  STOCKS = ('Stocks', 0.02)
  BONDS = ('Bonds', 0.02)

  def __init__(self, display_name: str, inflation: float):
    self.display_name = display_name
    self.inflation = inflation

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


class Budget:
  """Budget tracking with historical data and projection rules.

  Supports multiple budget categories with different inflation rates and custom projection rules for
  each category.
  """

  def __init__(self, path: str):
    """Initialize and load historical budget data from a CSV file.

    Args:
      path: Path to the CSV file containing historical budget data.
    """
    # Historical data: {year: {category: amount}}
    self._historical: dict[int, dict[BudgetCategory, float]] = {}

    # Latest year with historical data
    self._last_historical_year: int | None = None

    # Rules mapping from (category, year) to rule
    self._rules: defaultdict[BudgetCategory, dict[int, Rule]] = defaultdict(dict)

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

  def _load_csv(self, path: str) -> None:
    """Load historical budget data from the given CSV file path.

    Expected format:
      Year,Housing,Health,Housing Rules,Health Rules,...
      2020,1000,2000,,
      2021,1100,2200,+5%,+10%
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
            category = BudgetCategory.from_name(category_name)
            if rule := parse_rule(year, value):
              self._rules[category][year] = rule
          elif value.strip():
            category = BudgetCategory.from_name(col_name)
            year_data[category] = float(value)

        if year_data:
          self._historical[year] = year_data
          if not self._last_historical_year or year > self._last_historical_year:
            self._last_historical_year = year

  def _project_category(self, category: BudgetCategory, year: int) -> float:
    """Returns the projected budget for a category in a future year.

    Applies rules in order from the last historical year to the target year.

    If no rule applies for a year, applies the default inflation rate.

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

    # Project year by year, applying rules or default inflation
    for i in range(self._last_historical_year + 1, year + 1):
      rule = category_rules.get(i)
      amount = rule.apply(amount) if rule else amount * (1 + category.inflation)

    return amount
