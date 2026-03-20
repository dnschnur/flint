"""Shared utility functions."""

from decimal import Decimal


def parse_percentage(value: str | int | float) -> Decimal:
  """Parse a percentage string or plain number into a Decimal fraction.

  A value ending with '%' is divided by 100 (e.g. '50%' -> Decimal('0.5')).
  A plain number is converted as-is (e.g. '0.5' or 0.5 -> Decimal('0.5')).
  """
  value_str = str(value).strip()
  if value_str.endswith('%'):
    return Decimal(value_str[:-1]) / 100
  return Decimal(value_str)
