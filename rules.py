"""Projection rules for assets, budgets, and income.

Growth behavior
---------------
After a rule is applied, the caller may also apply a default growth or inflation rate. Each rule
has an apply_growth property that controls this:

  - SetAmount:               apply_growth defaults to False (set value is treated as final)
  - AdjustByPercentage:      apply_growth defaults to True (adjustment is a delta; growth follows)
  - AdjustByAmount:          apply_growth defaults to True (adjustment is a delta; growth follows)
  - AdjustByFractionOfOther: apply_growth defaults to True (adjustment is a delta; growth follows)

Either default can be overridden with a suffix on the rule string:
  - "!" suppresses growth (apply_growth=False)
  - "+" applies growth   (apply_growth=True)

Examples:
  "=20000"             SetAmount,               apply_growth=False  (fixed contribution, no compounding)
  "=20000+"            SetAmount,               apply_growth=True   (set, then grow)
  "-5000"              AdjustByAmount,          apply_growth=True   (reduce, then grow remainder)
  "-5000!"             AdjustByAmount,          apply_growth=False  (reduce, no further growth)
  "+3%"                AdjustByPercentage,      apply_growth=True   (adjust, then grow)
  "+3%!"               AdjustByPercentage,      apply_growth=False  (adjust, no further growth)
  "+45%@Real Estate"   AdjustByFractionOfOther, apply_growth=True   (add 45% of Real Estate's pre-rule value)
  "-10%@Real Estate!"  AdjustByFractionOfOther, apply_growth=False  (subtract 10% of Real Estate, no growth)

Cross-category rules
--------------------
The @Category suffix references another asset category by its display name (e.g. "Real Estate").
The base value is taken from a context dict passed to apply() - a snapshot of all asset values
taken *before* any rules for that year are applied. This means:

  {year = 2040, "Real Estate" = "-50%", "Cash" = "+45%@Real Estate"}

...correctly computes Cash's gain as 45% of Real Estate's pre-rule (market) value, not its
post-rule value. When no context is available (e.g. in the static pre-simulation projection),
the cross-category term is treated as 0 and the rule is a no-op.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from assets import AssetCategory, AssetDict


class Rule(ABC):
  """Base class for projection rules.

  Attributes:
    apply_growth: If True, the caller should apply the default growth/inflation rate after this
      rule. Subclasses set a default; parse_rule() may override it via the ! or + suffix.
  """

  apply_growth: bool

  @abstractmethod
  def apply(self, previous: int, context: AssetDict | None = None) -> int:
    """Returns the new amount after applying the rule.

    Args:
      previous: The current value before applying the rule.
      context: Optional asset snapshot keyed by AssetCategory, holding pre-rule values for the
        current year. Used by cross-category rules; ignored by all others.
    """


class SetAmount(Rule):
  """Sets the amount to a fixed value. Does not apply growth by default."""

  apply_growth = False

  def __init__(self, amount: int):
    self.amount = amount

  def apply(self, previous: int, context: AssetDict | None = None) -> int:
    """Returns the fixed amount."""
    return self.amount


class AdjustByPercentage(Rule):
  """Adjusts the previous year's amount by a percentage. Applies growth by default."""

  apply_growth = True

  def __init__(self, percentage: Decimal):
    self.percentage = percentage

  def apply(self, previous: int, context: AssetDict | None = None) -> Decimal:
    """Returns the previous amount adjusted by the percentage."""
    return int(round(previous * (1 + self.percentage)))


class AdjustByAmount(Rule):
  """Adjusts the previous year's amount by a fixed amount. Applies growth by default."""

  apply_growth = True

  def __init__(self, amount: int):
    self.amount = amount

  def apply(self, previous: int, context: AssetDict | None = None) -> int:
    """Returns the previous amount plus the adjustment amount."""
    return previous + self.amount


class AdjustByFractionOfOther(Rule):
  """Adds a signed fraction of another asset category's pre-rule value. Applies growth by default.

  Used for cross-category rules where one category's adjustment depends on another's value,
  e.g. "+45%@Real Estate" adds 45% of Real Estate's pre-rule balance to the target category.

  When no context is available (e.g. in the static per-category projection path), the
  cross-category term is 0 and the rule returns previous unchanged.
  """

  apply_growth = True

  def __init__(self, category: AssetCategory, fraction: Decimal):
    self.category = category
    self.fraction = fraction  # signed; negative subtracts

  def apply(self, previous: int, context: AssetDict | None = None) -> int:
    """Returns previous plus fraction * the other category's pre-rule value."""
    other = context.get(self.category, 0) if context else 0
    return previous + int(round(self.fraction * other))


def parse_rule(value: str | int) -> Rule | None:
  """Parse a rule value into a Rule object.

  Numeric int values are always treated as SetAmount. String formats:

    "=##.#"          -> SetAmount               (apply_growth=False by default)
    "+##.#"          -> AdjustByAmount          (apply_growth=True by default)
    "-##.#"          -> AdjustByAmount          (apply_growth=True by default)
    "+##.#%"         -> AdjustByPercentage      (apply_growth=True by default)
    "-##.#%"         -> AdjustByPercentage      (apply_growth=True by default)
    "+##.#%@Name"    -> AdjustByFractionOfOther (apply_growth=True by default)
    "-##.#%@Name"    -> AdjustByFractionOfOther (apply_growth=True by default)
    ""               -> None (no rule)

  Any rule string may end with "!" to suppress growth or "+" to apply growth, overriding
  the rule type's default. The suffix is stripped before parsing the value.

  For cross-category rules ("+N%@Category Name"), the category name is the display name of
  another asset category. The rule adds N% of that category's pre-rule value to the target.

  Args:
    value: A numeric value or rule string to parse.

  Returns:
    The parsed Rule object, or None if no rule.
  """
  if isinstance(value, int):
    return SetAmount(value)

  rule_str = value
  if not rule_str or not rule_str.strip():
    return None

  rule_str = rule_str.strip()

  # Check for growth override suffix before parsing the value.
  growth_override: bool | None = None
  if rule_str.endswith('!'):
    growth_override = False
    rule_str = rule_str[:-1]
  elif rule_str.endswith('+'):
    growth_override = True
    rule_str = rule_str[:-1]

  # Cross-category: +##.#%@Category Name or -##.#%@Category Name
  if '@' in rule_str:
    amount_part, category_name = rule_str.split('@', 1)  # e.g. "+45%", "Real Estate"
    if amount_part.endswith('%') and amount_part.startswith(('+', '-')):
      from assets import AssetCategory  # lazy import to avoid circular dependency
      category = AssetCategory.from_name(category_name)
      rule = AdjustByFractionOfOther(category, Decimal(amount_part[:-1]) / 100)
    else:
      raise ValueError(f'Invalid cross-category rule: {value!r}')
  # SetAmount: =###
  elif rule_str.startswith('='):
    rule = SetAmount(int(rule_str[1:]))
  # AdjustByPercentage: +##.#% or -##.#%
  elif rule_str.endswith('%'):
    rule = AdjustByPercentage(Decimal(rule_str[:-1]) / 100)
  # AdjustByAmount: +### or -###
  elif rule_str.startswith(('+', '-')):
    rule = AdjustByAmount(int(rule_str))
  else:
    raise ValueError(f'Unrecognized rule format: {value!r}')

  if growth_override is not None:
    rule.apply_growth = growth_override

  return rule


class Rules:
  """Collection of calendar-year or retirement-relative rules.

  Rules are held in two separate maps:
    - Calendar rules: keyed by the exact calendar year (e.g. 2034).
    - Retirement rules: keyed by offset from retirement year.
  """

  def __init__(self):
    self._calendar: dict[int, Rule] = {}
    self._retirement: dict[int, Rule] = {}

  @staticmethod
  def is_retirement_spec(year_spec: str | int) -> bool:
    """Returns whether the given rule entry year-spec is retirement-relative."""
    if isinstance(year_spec, int):
      return False
    return year_spec.strip().lower().startswith('retirement')

  @staticmethod
  def _parse_retirement_offset(year_spec: str) -> int:
    """Returns the retirement-year offset for the given retirement-relative year-spec.

    Raises:
      ValueError: If the spec cannot be parsed.
    """
    year_spec = year_spec.strip().lower()
    if year_spec == 'retirement':
      return 0
    try:
      return int(year_spec[len('retirement'):])
    except ValueError:
      raise ValueError(f'Invalid retirement year spec: {year_spec!r}')

  def add(self, year_spec: str | int, rule: Rule) -> None:
    """Stores the given rule.

    Args:
      year_spec: A calendar year (int or string such as "2034") or retirement-relative spec.
      rule: Rule to store.
    """
    if self.is_retirement_spec(year_spec):
      self._retirement[self._parse_retirement_offset(year_spec)] = rule
    else:
      self._calendar[int(year_spec)] = rule

  def apply(
    self, amount: int, year: int, retirement_year: int, growth: Decimal, context=None
  ) -> int:
    """Applies rules to the given amount in the given year.

    If there is a retirement-relative rule for this year, it is applied first, followed by any
    calendar-year rule. Growth is applied last, as long as the calendar-year rule (if there is one)
    doesn't explicitly disable growth.

    Args:
      amount: The value before the given year's rules and growth.
      year: The current simulation year.
      retirement_year: The retirement start year, used for retirement-relative rules.
      growth: Growth or inflation rate to (potentially) apply after the calendar-year rule.
      context: Optional asset snapshot keyed by AssetCategory, used for cross-category rules.

    Returns:
      The updated amount after applying rules and growth, rounded to the nearest integer.
    """
    if rule := self._retirement.get(year - retirement_year):
      amount = rule.apply(amount, context)

    growth_factor = 1 + growth
    if rule := self._calendar.get(year):
      amount = rule.apply(amount, context)
      if rule.apply_growth:
        amount *= growth_factor
    else:
      amount *= growth_factor

    return int(round(amount))
