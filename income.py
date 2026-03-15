"""Income tracking, with a base-year snapshot and forward projection.

Income is split into two types:
  - Job income: Primary employment income that stops at retirement.
  - Other income: Rental properties, part-time work, etc. that continues through retirement.

Each type has a base-year value and optional projection rules.
"""

from functools import cache

from rules import Rule, parse_rule, RETIREMENT_RULE_YEAR


class Income:
  """Income tracking with a base-year snapshot and projection rules."""

  def __init__(self, base_year: int, data: dict, default_job_increase_rate: float = 0.03):
    """Initialize from a scenario TOML [income] data dict.

    Args:
      base_year: The snapshot year for the base income amounts.
      data: Dict from the [income] TOML section. Recognized keys are 'Job Income' and
          'Other Income', with numeric values for the base-year amounts. An optional 'rules'
          key contains a list of per-year rule dicts with a 'year' key (int or "retirement")
          and the same income keys. Rules with year = "retirement" fire at whatever calendar
          year retirement begins, resolved automatically by the simulation loops.
      default_job_increase_rate: Annual job income increase rate (default 3%).
    """
    self.base_year = base_year
    self._job_income = float(data.get('Job Income', 0))
    self._other_income = float(data.get('Other Income', 0))

    # Rules mapping from year to rule.
    self._rules_job: dict[int, Rule] = {}
    self._rules_other: dict[int, Rule] = {}

    self._default_job_increase_rate = default_job_increase_rate

    for rule_entry in data.get('rules', []):
      year = Rule.parse_year(rule_entry['year'])
      if 'Job Income' in rule_entry:
        if rule := parse_rule(str(rule_entry['Job Income']).strip()):
          self._rules_job[year] = rule
      if 'Other Income' in rule_entry:
        if rule := parse_rule(str(rule_entry['Other Income']).strip()):
          self._rules_other[year] = rule

  @cache
  def get(self, year: int, retirement_year: int) -> float:
    """Returns the total income for the given year.

    Args:
      year: The year to get income for.
      retired: If True, only return other income (no job income).
      retirement_year: The retirement start year.
    """
    other_income = self._project_other_income(year, retirement_year)
    if year < retirement_year:
      return self._project_job_income(year, retirement_year) + other_income
    return other_income

  def _project(
    self, base_amount: float, rules: dict[int, Rule], year: int, retirement_year: int,
  ) -> float:
    """Returns a projected income amount for the given year.

    Applies rules and the default growth rate year-by-year from the base year.

    Args:
      base_amount: The base-year income amount.
      rules: Dict mapping years to rules for this income type.
      year: The target year.
      retirement_year: The retirement start year.
    """
    if year <= self.base_year:
      return base_amount

    amount = base_amount
    for i in range(self.base_year + 1, year + 1):
      # Apply at-retirement rules first. These never apply growth.
      if i == retirement_year and (rule := rules.get(RETIREMENT_RULE_YEAR)):
        amount = rule.apply(amount)

      if rule := rules.get(i):
        amount = rule.apply(amount)
        if rule.apply_growth:
          amount *= 1 + self._default_job_increase_rate
      else:
        amount *= 1 + self._default_job_increase_rate

    return amount

  def _project_job_income(self, year: int, retirement_year: int) -> float:
    """Returns the projected job income for the given year."""
    return self._project(self._job_income, self._rules_job, year, retirement_year)

  def _project_other_income(self, year: int, retirement_year: int) -> float:
    """Returns the projected other income for the given year."""
    return self._project(self._other_income, self._rules_other, year, retirement_year)
