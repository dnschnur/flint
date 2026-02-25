"""Federal and state income tax calculation with bracket projection.

Loads tax brackets for ordinary income and long-term capital gains from two CSV files. This data is
for a single tax year; the thresholds are projected forward to future years using a fixed annual
growth rate based on historical IRS inflation adjustments.

For now, all brackets are assumed to be for the "Married Filing Jointly" filing status.

Capital gains brackets support an optional 'Inflation Adjusted' column. Brackets marked 'No', such
as the NIIT threshold, which is set by statute, are not projected forward.

An optional state income tax file may be provided. When present, state rates are combined with
federal rates for ordinary income calculations.
"""

import csv

from util import DataPaths


# Annual growth rate applied to inflation-adjusted bracket thresholds when projecting to
# future years. Based on the historical average IRS inflation adjustment over the past two
# decades (~2-3%), using a slightly conservative midpoint.
_BRACKET_GROWTH = 0.025


def _parse_rate(value: str) -> float:
  """Parse a rate string as a percentage (e.g. '10%') or decimal (e.g. '0.10')."""
  value = value.strip()
  return float(value[:-1]) / 100.0 if value.endswith('%') else float(value)


class Tax:
  """Progressive federal and state income tax calculator with forward bracket projection.

  Optionally combines federal ordinary income tax with a state income tax. Capital gains tax
  remains federal-only.
  """

  def __init__(self, paths: DataPaths, data_year: int):
    """Initialize and load tax bracket data.

    Args:
      paths: Resolved data file paths. Uses income_tax, capital_gains_tax, and
          state_income_tax (if set).
      data_year: The tax year of the data in the CSV files.
    """
    self.data_year = data_year

    # List of (income_threshold, rate) tuples, sorted ascending by threshold.
    self._income_brackets: list[tuple[float, float]] = self._load_bracket_list(paths.income_tax)

    # List of (income_threshold, rate, inflation_adjusted) tuples, sorted ascending.
    self._cg_brackets: list[tuple[float, float, bool]] = self._load_capital_gains_csv(
        paths.capital_gains_tax)

    # State income brackets as (threshold, rate) tuples, or empty if no state is loaded.
    self._state_income_brackets: list[tuple[float, float]] = (
      self._load_bracket_list(paths.state_income_tax) if paths.state_income_tax else []
    )

  def calculate(self, amount: float, year: int, capital_gains: bool = False) -> float:
    """Calculate progressive tax on an amount for a given year.

    For ordinary income, combines federal and any loaded state taxes.

    Args:
      amount: Taxable income amount.
      year: The tax year to calculate for.
      capital_gains: If True, apply long-term capital gains rates; otherwise ordinary rates.

    Returns:
      Total tax owed on the amount.
    """
    if amount <= 0:
      return 0.0
    total = self._calculate_from_brackets(self._project_brackets(year, capital_gains), amount)
    if not capital_gains and self._state_income_brackets:
      total += self._calculate_from_brackets(
        self._project_bracket_list(self._state_income_brackets, year), amount
      )
    return total

  def next_ordinary_bracket_threshold(self, income: float, year: int) -> float:
    """Returns the next federal ordinary income threshold above the given income level.

    Uses federal brackets only, so that small state bracket steps (e.g. CA's 1%→2% at ~$22K)
    don't trigger overly aggressive Roth diversion. Only meaningful federal jumps (e.g. 12%→22%,
    22%→24%) influence the cap.

    Alternative: include state brackets but add a minimum combined-rate-increase threshold
    (e.g. only cap at boundaries where the marginal rate jumps by >= 5%) so that small state
    steps are ignored while large combined jumps still trigger Roth diversion.

    Args:
      income: Current income level.
      year: The tax year.

    Returns:
      The income level at which the next higher federal ordinary income bracket begins.
    """
    brackets = self._project_brackets(year, capital_gains=False)
    return next((threshold for threshold, _ in brackets if threshold > income), float('inf'))

  def gross_for_net_ordinary(self, net: float, base_income: float, year: int) -> float:
    """Compute the gross 401K/IRA withdrawal that yields exactly 'net' after incremental tax.

    Finds the gross amount such that:
      gross - (calculate(base_income + gross, year) - calculate(base_income, year)) = net

    Handles bracket-crossing withdrawals correctly and includes state tax automatically.

    Args:
      net: Target net amount after incremental ordinary income tax.
      base_income: Current taxable income before this withdrawal.
      year: The tax year.

    Returns:
      Gross withdrawal amount >= net.
    """
    if net <= 0:
      return 0.0
    base_tax = self.calculate(base_income, year)
    lo, hi = net, net * 3  # gross >= net; 3x covers up to ~67% marginal rate
    for _ in range(32):
      mid = (lo + hi) / 2
      if mid - (self.calculate(base_income + mid, year) - base_tax) < net:
        lo = mid
      else:
        hi = mid
    return (lo + hi) / 2

  def marginal_rate(self, amount: float, year: int, capital_gains: bool = False) -> float:
    """Returns the marginal tax rate for the given income amount and year.

    For ordinary income, combines the federal marginal rate with any loaded state marginal rates.

    Args:
      amount: The income level at which to look up the marginal rate.
      year: The tax year.
      capital_gains: If True, look up the capital gains rate; otherwise ordinary rate.

    Returns:
      The combined marginal tax rate as a decimal (e.g. 0.24 for 24%).
    """
    if amount <= 0:
      return 0.0
    rate = self._marginal_from_brackets(self._project_brackets(year, capital_gains), amount)
    if not capital_gains and self._state_income_brackets:
      rate += self._marginal_from_brackets(
        self._project_bracket_list(self._state_income_brackets, year), amount
      )
    return rate

  def _calculate_from_brackets(self, brackets: list[tuple[float, float]], amount: float) -> float:
    """Calculate progressive tax for the given amount from a projected bracket list."""
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

  def _load_bracket_list(self, path: str) -> list[tuple[float, float]]:
    """Load a simple Income,Rate CSV and return sorted (threshold, rate) pairs.

    Expected format:
      Income,Rate
      0,10%
      23850,12%
      ...

    Args:
      path: Path to the CSV file.

    Returns:
      List of (income_threshold, rate) tuples sorted ascending by threshold.
    """
    brackets = []
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        income = float(row['Income'].replace(',', ''))
        rate = _parse_rate(row['Rate'])
        brackets.append((income, rate))
    brackets.sort(key=lambda b: b[0])
    return brackets

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
    brackets = []
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        income = float(row['Income'].replace(',', ''))
        rate = _parse_rate(row['Rate'])
        inflation_adjusted = row.get('Inflation Adjusted', 'Yes').strip().lower() != 'no'
        brackets.append((income, rate, inflation_adjusted))
    brackets.sort(key=lambda b: b[0])
    return brackets

  def _marginal_from_brackets(self, brackets: list[tuple[float, float]], amount: float) -> float:
    """Return the marginal rate for the given amount from a projected bracket list."""
    rate = brackets[0][1]
    for threshold, bracket_rate in brackets:
      if amount >= threshold:
        rate = bracket_rate
      else:
        break
    return rate

  def _project_bracket_list(
    self, brackets: list[tuple[float, float]], year: int
  ) -> list[tuple[float, float]]:
    """Project a simple (threshold, rate) bracket list forward to the given year.

    Args:
      brackets: List of (threshold, rate) tuples.
      year: The target tax year.

    Returns:
      Projected list with thresholds scaled by the growth factor.
    """
    growth_factor = (1 + _BRACKET_GROWTH) ** (year - self.data_year)
    return [(threshold * growth_factor, rate) for threshold, rate in brackets]

  def _project_brackets(self, year: int, capital_gains: bool) -> list[tuple[float, float]]:
    """Return brackets with thresholds projected to the given year.

    Args:
      year: The target tax year.
      capital_gains: If True, project capital gains brackets; otherwise ordinary income.

    Returns:
      List of (threshold, rate) tuples sorted ascending by threshold.
    """
    if capital_gains:
      growth_factor = (1 + _BRACKET_GROWTH) ** (year - self.data_year)
      return [
        (threshold * growth_factor if inflation_adjusted else threshold, rate)
        for threshold, rate, inflation_adjusted in self._cg_brackets
      ]
    return self._project_bracket_list(self._income_brackets, year)
