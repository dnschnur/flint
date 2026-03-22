"""Income tracking, with a base-year snapshot and forward projection.

Income is split into two types:
  - Job income: Primary employment income that stops at retirement.
  - Other income: Rental properties, part-time work, etc. that continues through retirement.

Each type has a base-year value and optional projection rules.
"""

from decimal import Decimal
from functools import cache

from rules import parse_rule, Rules

DEFAULT_INCOME_GROWTH_RATE = Decimal('0.03')


class Income:
  """Income tracking with a base-year snapshot and projection rules."""

  def __init__(self, base_year: int, data: dict):
    """Initialize from a scenario TOML [income] data dict.

    Args:
      base_year: The snapshot year for the base income amounts.
      data: Dict from the [income] TOML section. Recognized keys are 'Job Income' and
          'Other Income', with numeric values for the base-year amounts. An optional 'rules'
          key contains a list of per-year rule dicts with a 'year' key (int, "retirement",
          "retirement+N", or "retirement-N") and the same income keys. An optional 'growth'
          sub-dict may supply a fixed annual growth rate override for 'Other Income' (e.g.
          growth = {"Other Income" = 2} for 2%). When absent, Other Income grows at the
          historical inflation rate during retirement (floored at zero). Retirement-relative
          rules apply to the year with the corresponding offset from retirement.
    """
    self.base_year = base_year
    self._job_income = int(data.get('Job Income', 0))
    self._other_income = int(data.get('Other Income', 0))

    self._rules_job = Rules()
    self._rules_other = Rules()

    # Optional fixed growth rate override for Other Income (fraction, e.g. 0.02 for 2%).
    # When None, the Monte Carlo simulation uses the historical inflation rate floored at 0.
    growth_overrides = data.get('growth', {})
    raw_override = growth_overrides.get('Other Income')
    self._other_income_growth_override: Decimal | None = (
      Decimal(raw_override) / 100 if raw_override is not None else None
    )

    for rule_entry in data.get('rules', []):
      year_spec = rule_entry['year']
      if 'Job Income' in rule_entry:
        if rule := parse_rule(str(rule_entry['Job Income']).strip()):
          self._rules_job.add(year_spec, rule)
      if 'Other Income' in rule_entry:
        if rule := parse_rule(str(rule_entry['Other Income']).strip()):
          self._rules_other.add(year_spec, rule)

  @cache
  def get(self, year: int, retirement_year: int) -> int:
    """Returns the total income for the given year.

    Args:
      year: The year to get income for.
      retirement_year: The retirement start year.
    """
    other_income = self._project_other_income(year, retirement_year)
    if year < retirement_year:
      return self._project_job_income(year, retirement_year) + other_income
    return other_income

  def _project(self, base_amount: int, rules: Rules, year: int, retirement_year: int) -> int:
    """Returns a projected income amount for the given year.

    Applies rules and the default growth rate year-by-year from the base year.

    Args:
      base_amount: The base-year income amount.
      rules: Rules for this income type.
      year: The target year.
      retirement_year: The retirement start year.
    """
    if year <= self.base_year:
      return base_amount

    amount = base_amount
    for i in range(self.base_year + 1, year + 1):
      amount = rules.apply(amount, i, retirement_year, DEFAULT_INCOME_GROWTH_RATE)

    return amount

  def _project_job_income(self, year: int, retirement_year: int) -> int:
    """Returns the projected job income for the given year."""
    return self._project(self._job_income, self._rules_job, year, retirement_year)

  def advance_other(
    self, year: int, amount: int, inflation_rate: Decimal | None, retirement_year: int
  ) -> int:
    """Advance Other Income by one year, applying rules and an inflation rate.

    Used in the Monte Carlo retirement loop to grow Other Income using the matched historical
    inflation rate rather than the long-run average.

    Args:
      year: The target year (the year being stepped into, i.e. previous_year + 1).
      amount: The Other Income amount at the previous year.
      inflation_rate: Historical inflation rate to apply. Floored at zero unless an explicit
          growth override is configured. Pass None to fall back to DEFAULT_INCOME_GROWTH_RATE.
      retirement_year: The retirement start year.

    Returns:
      The Other Income amount for the given year.
    """
    if self._other_income_growth_override is not None:
      rate = self._other_income_growth_override
    elif inflation_rate is not None:
      rate = max(Decimal(0), inflation_rate)
    else:
      rate = DEFAULT_INCOME_GROWTH_RATE
    return self._rules_other.apply(amount, year, retirement_year, rate)

  def _project_other_income(self, year: int, retirement_year: int) -> int:
    """Returns the projected other income for the given year."""
    return self._project(self._other_income, self._rules_other, year, retirement_year)
