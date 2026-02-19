"""Federal income tax calculation with bracket projection.

Loads tax brackets for ordinary income and long-term capital gains from two CSV files. This data is
for a single tax year; the thresholds are projected forward to future years using a fixed annual
growth rate based on historical IRS inflation adjustments.

For now, all brackets are assumed to be for the "Married Filing Jointly" filing status.

Capital gains brackets support an optional 'Inflation Adjusted' column. Brackets marked 'No', such
as the NIIT threshold, which is set by statute, are not projected forward.
"""

import csv


# Annual growth rate applied to inflation-adjusted bracket thresholds when projecting to
# future years. Based on the historical average IRS inflation adjustment over the past two
# decades (~2-3%), using a slightly conservative midpoint.
_BRACKET_GROWTH = 0.025


def _parse_rate(value: str) -> float:
  """Parse a rate string as a percentage (e.g. '10%') or decimal (e.g. '0.10')."""
  value = value.strip()
  return float(value[:-1]) / 100.0 if value.endswith('%') else float(value)


class Tax:
  """Progressive federal income tax calculator with forward bracket projection."""

  def __init__(self, income_tax_path: str, capital_gains_tax_path: str, data_year: int):
    """Initialize and load tax bracket data.

    Args:
      income_tax_path: Path to the ordinary income tax CSV file.
      capital_gains_tax_path: Path to the long-term capital gains tax CSV file.
      data_year: The tax year of the data in the CSV files.
    """
    self.data_year = data_year

    # List of (income_threshold, rate) tuples, sorted ascending by threshold.
    self._income_brackets: list[tuple[float, float]] = []

    # List of (income_threshold, rate, inflation_adjusted) tuples, sorted ascending.
    self._cg_brackets: list[tuple[float, float, bool]] = []

    self._load_income_csv(income_tax_path)
    self._load_capital_gains_csv(capital_gains_tax_path)

  def _project_brackets(self, year: int, capital_gains: bool) -> list[tuple[float, float]]:
    """Return brackets with thresholds projected to the given year.

    Args:
      year: The target tax year.
      capital_gains: If True, project capital gains brackets; otherwise ordinary income.

    Returns:
      List of (threshold, rate) tuples sorted ascending by threshold.
    """
    growth_factor = (1 + _BRACKET_GROWTH) ** (year - self.data_year)
    if capital_gains:
      return [
        (threshold * growth_factor if inflation_adjusted else threshold, rate)
        for threshold, rate, inflation_adjusted in self._cg_brackets
      ]
    return [(threshold * growth_factor, rate) for threshold, rate in self._income_brackets]

  def marginal_rate(self, amount: float, year: int, capital_gains: bool = False) -> float:
    """Returns the marginal tax rate (bracket rate) for the given income amount and year.

    Useful for gross-up calculations where the tax on a marginal withdrawal needs to be
    estimated based on the taxpayer's current income level.

    Args:
      amount: The income level at which to look up the marginal rate.
      year: The tax year.
      capital_gains: If True, look up the capital gains rate; otherwise ordinary rate.

    Returns:
      The marginal tax rate as a decimal (e.g. 0.24 for 24%).
    """
    if amount <= 0:
      return 0.0

    brackets = self._project_brackets(year, capital_gains)
    rate = brackets[0][1]
    for threshold, bracket_rate in brackets:
      if amount >= threshold:
        rate = bracket_rate
      else:
        break
    return rate

  def calculate(self, amount: float, year: int, capital_gains: bool = False) -> float:
    """Calculate progressive tax on an amount for a given year.

    Projects inflation-adjusted bracket thresholds from the base year to the target year
    using _BRACKET_GROWTH, then computes tax progressively across brackets.

    Args:
      amount: Taxable income amount.
      year: The tax year to calculate for.
      capital_gains: If True, apply long-term capital gains rates; otherwise ordinary rates.

    Returns:
      Total tax owed on the amount.
    """
    if amount <= 0:
      return 0.0

    brackets = self._project_brackets(year, capital_gains)
    total_tax = 0.0
    remaining = amount

    for i, (threshold, rate) in enumerate(brackets):
      next_threshold = brackets[i + 1][0] if i + 1 < len(brackets) else float('inf')
      taxable_in_bracket = min(remaining, next_threshold - threshold)
      if taxable_in_bracket <= 0:
        continue
      total_tax += taxable_in_bracket * rate
      remaining -= taxable_in_bracket
      if remaining <= 0:
        break

    return total_tax

  def _load_income_csv(self, path: str) -> None:
    """Load ordinary income bracket data from a CSV file.

    Expected format:
      Income,Rate
      0,10%
      23850,12%
      ...

    Args:
      path: Path to the CSV file.
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        income = float(row['Income'].replace(',', ''))
        rate = _parse_rate(row['Rate'])
        self._income_brackets.append((income, rate))
    self._income_brackets.sort(key=lambda b: b[0])

  def _load_capital_gains_csv(self, path: str) -> None:
    """Load long-term capital gains bracket data from a CSV file.

    Expected format:
      Income,Rate,Inflation Adjusted
      0,0%,Yes
      96700,15%,Yes
      250000,18.8%,No
      600050,23.8%,Yes

    The 'Inflation Adjusted' column is optional and defaults to Yes if absent.

    Args:
      path: Path to the CSV file.
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        income = float(row['Income'].replace(',', ''))
        rate = _parse_rate(row['Rate'])
        inflation_adjusted = row.get('Inflation Adjusted', 'Yes').strip().lower() != 'no'
        self._cg_brackets.append((income, rate, inflation_adjusted))
    self._cg_brackets.sort(key=lambda b: b[0])
