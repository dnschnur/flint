"""Income tracking, with historical data and forward projection.

Income is split into two types:
  - Job income: Primary employment income that stops at retirement.
  - Other income: Rental properties, part-time work, etc. that continues through retirement.

Each type has separate historical data and projection rules.
"""

import csv

from functools import cache

from rules import Rule, parse_rule


class Income:
  """Income tracking with historical data and projection rules."""

  def __init__(self, path: str, default_job_increase_rate: float = 0.03):
    """Initialize and load historical income data from a CSV file.

    Args:
      path: Path to the CSV file containing historical income data.
      default_job_increase_rate: Annual job income increase rate (default 3%).
    """
    # Historical income, mapping from year to amount.
    self._historical_job: dict[int, float] = {}
    self._historical_other: dict[int, float] = {}

    self._last_historical_year: int | None = None

    # Rules mapping from year to rule
    self._rules_job: dict[int, Rule] = {}
    self._rules_other: dict[int, Rule] = {}

    self._default_job_increase_rate = default_job_increase_rate

    self._load_csv(path)

  @cache
  def get(self, year: int, retired: bool = False) -> float:
    """Returns the total income for the given year.

    Args:
      year: The year to get income for.
      retired: If True, only return other income (no job income).
    """
    if year in self._historical_other:
      other_income = self._historical_other[year]
    elif self._last_historical_year and year > self._last_historical_year:
      other_income = self._project_other_income(year)
    else:
      other_income = 0.0

    if retired:
      return other_income

    if year in self._historical_job:
      return self._historical_job[year] + other_income
    if self._last_historical_year and year > self._last_historical_year:
      return self._project_job_income(year) + other_income
    return other_income

  def _load_csv(self, path: str) -> None:
    """Load historical income data from a CSV file.

    Expected format:
      Year,Job Income,Other Income,Job Rule,Other Rule
      2020,100000,5000,,
      2021,103000,5100,+3%,+2%
      2022,,,+3%,+2%
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        year = int(row['Year'])

        # Check if this row has actual historical data (not just rules)
        has_data = False
        if row['Job Income'].strip() or row['Other Income'].strip():
          has_data = True
          job_income = float(row['Job Income']) if row['Job Income'].strip() else 0.0
          other_income = float(row['Other Income']) if row['Other Income'].strip() else 0.0

          self._historical_job[year] = job_income
          self._historical_other[year] = other_income

        # Update last historical year only if this row has data
        if has_data and (not self._last_historical_year or year > self._last_historical_year):
          self._last_historical_year = year

        if 'Job Rule' in row and (job_rule := parse_rule(year, row['Job Rule'])):
          self._rules_job[year] = job_rule

        if 'Other Rule' in row and (other_rule := parse_rule(year, row['Other Rule'])):
          self._rules_other[year] = other_rule

  def _project_job_income(self, year: int) -> float:
    """Returns the projected job income for the given future year."""
    if not self._last_historical_year:
      return 0.0

    amount = self._historical_job.get(self._last_historical_year, 0.0)

    for i in range(self._last_historical_year + 1, year + 1):
      rule = self._rules_job.get(i)
      amount = rule.apply(amount) if rule else amount * (1 + self._default_job_increase_rate)

    return amount

  def _project_other_income(self, year: int) -> float:
    """Returns the projected other income for the given future year.

    Unlike job income, other income has no default growth rate: if no rule
    is set for a given year, the amount remains unchanged. Use explicit rules
    to model rent increases, cost-of-living adjustments, etc.
    """
    if not self._last_historical_year:
      return 0.0

    amount = self._historical_other.get(self._last_historical_year, 0.0)

    for i in range(self._last_historical_year + 1, year + 1):
      rule = self._rules_other.get(i)
      if rule:
        amount = rule.apply(amount)

    return amount
