"""Inflation rates based on historical CPI/PCE data.

Provides inflation rates for each BudgetCategory, either as averages used as default growth rates,
or as year-specific values used by the Monte Carlo simulation.
"""

import csv

from decimal import Decimal
from functools import cache

from budget import BudgetCategory


# Maps each BudgetCategory to the inflation.csv column(s) that best represent its price growth.
# Categories without an entry fall back to their hardcoded BudgetCategory.inflation default.
_INFLATION_COLUMNS: dict[BudgetCategory, list[str]] = {
  BudgetCategory.HOUSING:        ['CPI_Shelter'],
  BudgetCategory.UTILITIES:      ['CPI_Electricity', 'CPI_PipedGas', 'CPI_WaterSewer'],
  BudgetCategory.TRANSPORTATION: ['CPI_Gasoline', 'CPI_NewVehicles', 'CPI_VehicleMaintenance',
                                  'CPI_VehicleInsurance'],
  BudgetCategory.FOOD:           ['CPI_FoodAtHome', 'CPI_FoodAwayFromHome'],
  BudgetCategory.HEALTH:         ['PCE_Healthcare'],
  BudgetCategory.SCHOOL:         ['CPI_CollegeTuition'],
  BudgetCategory.CHILDREN:       ['CPI_TuitionChildcare'],
  BudgetCategory.OTHER:          ['CPI_All'],
}


class Inflation:
  """Inflation rates for each BudgetCategory, based on historical CPI/PCE data."""

  def __init__(self, inflation_path: str):
    """Loads inflation data.

    Args:
      inflation_path: Path to the inflation.csv file.
    """
    self._series: dict[str, dict[int, Decimal]] = self._load_inflation(inflation_path)
    self._average_rates: dict[str, Decimal] = self._compute_average_rates()

  def _load_inflation(self, path: str) -> dict[str, dict[int, Decimal]]:
    """Load inflation.csv into {column: {year: value}}.

    Args:
      path: Path to inflation.csv.

    Returns:
      Dict mapping column name to year -> normalized index value.
    """
    series: dict[str, dict[int, Decimal]] = {}
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        year = int(row['Year'])
        for column, value in row.items():
          if column == 'Year':
            continue
          if value and value.strip():
            series.setdefault(column, {})[year] = Decimal(value)
    return series

  def _compute_average_rates(self) -> dict[str, Decimal]:
    """Compute the average annual rate for each series.

    Returns:
      Dict mapping column name to average annual growth rate (e.g. 0.035 for 3.5%).
    """
    averages: dict[str, Decimal] = {}
    for column, year_values in self._series.items():
      years = sorted(year_values)
      rates = [
        year_values[years[i]] / year_values[years[i - 1]] - 1
        for i in range(1, len(years))
        if years[i] == years[i - 1] + 1
           and year_values[years[i - 1]] > 0
           and year_values[years[i]] > 0
      ]
      if rates:
        averages[column] = sum(rates) / len(rates)
    return averages

  @cache
  def average_rate(self, category: BudgetCategory) -> Decimal | None:
    """Return the average inflation rate for a budget category.

    Averages annual rates across all mapped inflation.csv columns.

    Args:
      category: The budget category.

    Returns:
      Average annual inflation rate (e.g. 0.035 for 3.5%), or None if the category has no mapping.
    """
    if columns := _INFLATION_COLUMNS.get(category, []):
      rates = [self._average_rates[column] for column in columns if column in self._average_rates]
      if rates:
        return sum(rates) / len(rates)
    return None

  @cache
  def rate(self, category: BudgetCategory, year: int) -> Decimal:
    """Return the inflation rate for a budget category from year to year + 1.

    Falls back to average_rate() when year or year + 1 is outside the dataset, and to
    category.inflation if there is no average available.

    Args:
      category: The budget category.
      year: Start of the one-year interval.

    Returns:
      Annual inflation rate (e.g. 0.035 for 3.5%).
    """
    columns = _INFLATION_COLUMNS.get(category, [])
    if not columns:
      return category.inflation

    year_rates = []
    for column in columns:
      year_data = self._series.get(column, {})
      current_value = year_data.get(year)
      next_value = year_data.get(year + 1)
      if current_value and next_value and current_value > 0:
        year_rates.append(next_value / current_value - 1)

    if not year_rates:
      fallback = self.average_rate(category)
      return fallback if fallback is not None else category.inflation

    return sum(year_rates) / len(year_rates)
