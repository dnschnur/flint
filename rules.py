"""Projection rules for assets, budgets, and income.

Defines the Rule base class and concrete implementations, used to override default growth and
inflation rates in scenario data.

Also provides parse_rule() to construct a Rule from a rule string.

Growth behavior
---------------
After a rule is applied, the caller may also apply a default growth or inflation rate. Each rule
has an apply_growth property that controls this:

  - SetAmount:          apply_growth defaults to False (the set value is treated as final)
  - AdjustByPercentage: apply_growth defaults to True (the adjustment is a delta; growth follows)
  - AdjustByAmount:     apply_growth defaults to True (the adjustment is a delta; growth follows)

Either default can be overridden with a suffix on the rule string:
  - "!" suppresses growth (apply_growth=False)
  - "+" applies growth   (apply_growth=True)

Examples:
  "=20000"   SetAmount,          apply_growth=False  (fixed contribution, no compounding)
  "=20000+"  SetAmount,          apply_growth=True   (set, then grow)
  "-5000"    AdjustByAmount,     apply_growth=True   (reduce, then grow remainder)
  "-5000!"   AdjustByAmount,     apply_growth=False  (reduce, no further growth)
  "+3%"      AdjustByPercentage, apply_growth=True   (adjust, then grow)
  "+3%!"     AdjustByPercentage, apply_growth=False  (adjust, no further growth)
"""

from abc import ABC, abstractmethod


class Rule(ABC):
  """Base class for projection rules.

  Attributes:
    apply_growth: If True, the caller should apply the default growth/inflation rate after this
      rule. Subclasses set a default; parse_rule() may override it via the ! or + suffix.
  """

  apply_growth: bool

  @abstractmethod
  def apply(self, previous: float) -> float:
    """Returns the new amount after applying the rule."""


class SetAmount(Rule):
  """Sets the amount to a fixed value. Does not apply growth by default."""

  apply_growth = False

  def __init__(self, amount: float):
    self.amount = amount

  def apply(self, previous: float) -> float:
    """Returns the fixed amount."""
    return self.amount


class AdjustByPercentage(Rule):
  """Adjusts the previous year's amount by a percentage. Applies growth by default."""

  apply_growth = True

  def __init__(self, percentage: float):
    self.percentage = percentage

  def apply(self, previous: float) -> float:
    """Returns the previous amount adjusted by the percentage."""
    return previous * (1 + self.percentage)


class AdjustByAmount(Rule):
  """Adjusts the previous year's amount by a fixed amount. Applies growth by default."""

  apply_growth = True

  def __init__(self, amount: float):
    self.amount = amount

  def apply(self, previous: float) -> float:
    """Returns the previous amount plus the adjustment amount."""
    return previous + self.amount


def parse_rule(value: str | int | float) -> Rule | None:
  """Parse a rule value into a Rule object.

  Numeric values (int or float) are always treated as SetAmount. String formats:
    "=##.#"   -> SetAmount          (apply_growth=False by default)
    "+##.#"   -> AdjustByAmount     (apply_growth=True by default)
    "-##.#"   -> AdjustByAmount     (apply_growth=True by default)
    "+##.#%"  -> AdjustByPercentage (apply_growth=True by default)
    "-##.#%"  -> AdjustByPercentage (apply_growth=True by default)
    ""        -> None (no rule)

  Any rule string may end with "!" to suppress growth or "+" to apply growth, overriding
  the rule type's default. The suffix is stripped before parsing the value.

  Args:
    value: A numeric value or rule string to parse.

  Returns:
    The parsed Rule object, or None if no rule.
  """
  if isinstance(value, (int, float)):
    return SetAmount(float(value))

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

  # SetAmount: =##.#
  if rule_str.startswith('='):
    rule = SetAmount(float(rule_str[1:]))
  # AdjustByPercentage: +##.#% or -##.#%
  elif rule_str.endswith('%'):
    rule = AdjustByPercentage(float(rule_str[:-1]) / 100.0)
  # AdjustByAmount: +##.# or -##.#
  elif rule_str.startswith(('+', '-')):
    rule = AdjustByAmount(float(rule_str))
  else:
    return None

  if growth_override is not None:
    rule.apply_growth = growth_override

  return rule
