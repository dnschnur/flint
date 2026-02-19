"""Shared utility types for Flint."""

from dataclasses import dataclass


@dataclass
class DataPaths:
  """Resolved file paths for a simulation run.

  Attributes:
    assets: Path to the assets CSV file.
    budget: Path to the budget CSV file.
    income: Path to the income CSV file.
    income_tax: Path to the federal income tax CSV file.
    capital_gains_tax: Path to the capital gains tax CSV file.
    state_income_tax: Path to the state income tax CSV file, or None.
  """
  assets: str
  budget: str
  income: str
  income_tax: str
  capital_gains_tax: str
  state_income_tax: str | None
