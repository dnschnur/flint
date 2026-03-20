"""Required Minimum Distribution (RMD) calculations for retirement accounts.

RMDs apply to traditional (pre-tax) retirement accounts like 401Ks and IRAs.
"""

import csv

from decimal import Decimal


class RMD:
  """Required Minimum Distribution calculator."""

  def __init__(self, path: str):
    """Initialize and load the RMD divisor table from a CSV file.

    Args:
      path: Path to the CSV file containing RMD divisors.
    """
    # Mapping from age to divisor
    self._divisors: dict[int, Decimal] = {}

    self._load_csv(path)

  def calculate(self, age: int, account_balance: int) -> int:
    """Calculate the required minimum distribution for a given age and balance.

    Args:
      age: The person's age.
      account_balance: The balance in the retirement account.

    Returns:
      The required minimum distribution amount, or 0 if no RMD required.
    """
    divisor = self._divisors.get(age)
    return int(round(account_balance / divisor)) if divisor else 0

  def _load_csv(self, path: str) -> None:
    """Load the RMD divisor table from the given CSV file path.

    Expected format:
      Age,Divisor
      72,27.4
      73,26.5
      ...
    """
    with open(path, 'r') as f:
      reader = csv.DictReader(f)
      for row in reader:
        age = int(row['Age'])
        self._divisors[age] = Decimal(row['Divisor'])
