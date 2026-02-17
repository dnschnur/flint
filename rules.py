"""Projection rules for assets, budgets, and income.

Defines the Rule base class and concrete implementations, used to override default growth and
inflation rates in CSV data files.

Also provides parse_rule() to construct a Rule from a CSV rule string.
"""

from abc import ABC, abstractmethod


class Rule(ABC):
  """Base class for projection rules."""

  @abstractmethod
  def apply(self, previous: float) -> float:
    """Returns the new amount after applying the rule."""


class SetAmount(Rule):
  """Sets the amount to a fixed value."""

  def __init__(self, amount: float):
    self.amount = amount

  def apply(self, previous: float) -> float:
    """Returns the fixed amount."""
    return self.amount


class AdjustByPercentage(Rule):
  """Adjusts the previous year's amount by a percentage."""

  def __init__(self, percentage: float):
    self.percentage = percentage

  def apply(self, previous: float) -> float:
    """Returns the previous amount adjusted by the percentage."""
    return previous * (1 + self.percentage)


class AdjustByAmount(Rule):
  """Adjusts the previous year's amount by a fixed amount."""

  def __init__(self, amount: float):
    self.amount = amount

  def apply(self, previous: float) -> float:
    """Returns the previous amount plus the adjustment amount."""
    return previous + self.amount


def parse_rule(year: int, rule_str: str) -> Rule | None:
  """Parse a rule string from CSV format.

  Formats:
    "=##.#"   -> SetAmount
    "+##.#"   -> AdjustByAmount (positive)
    "-##.#"   -> AdjustByAmount (negative)
    "+##.#%"  -> AdjustByPercentage (positive)
    "-##.#%"  -> AdjustByPercentage (negative)
    ""        -> None (no rule)

  Args:
    year: The year the rule applies to (unused, retained for call-site clarity).
    rule_str: The rule string from the CSV.

  Returns:
    The parsed Rule object, or None if no rule.
  """
  if not rule_str or not rule_str.strip():
    return None

  rule_str = rule_str.strip()

  # SetAmount: =##.#
  if rule_str.startswith('='):
    return SetAmount(float(rule_str[1:]))

  # AdjustByPercentage: +##.#% or -##.#%
  if rule_str.endswith('%'):
    return AdjustByPercentage(float(rule_str[:-1]) / 100.0)

  # AdjustByAmount: +##.# or -##.#
  if rule_str.startswith(('+', '-')):
    return AdjustByAmount(float(rule_str))

  return None
