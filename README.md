# Flint

Flint is a retirement simulator that uses an approach inspired by the excellent ficalc.app.

You describe your current financial picture, including assets, spending, and income, and Flint
replays every historical S&P 500 period of the same length as your retirement to show how you would
have fared.

The result is a distribution of outcomes grounded in real market history rather than assumptions
about future returns.

## Philosophy

Most retirement calculators ask: *"How much can I withdraw each year?"* They answer with a single
value or withdrawal rate, often the famous "4% rule", applied uniformly to a simplified two-bucket
portfolio of stocks and bonds.

Flint takes the opposite approach. Instead of starting from a withdrawal rate, you describe your
actual spending plan, broken down into categories like housing, food, healthcare, and education.
Each category has its own inflation rate, because the things that cost more as you age, especially
healthcare, inflate faster, while other expenses shrink or disappear entirely (a paid-off mortgage,
children leaving home, no more commuting costs).

You also describe your assets with the same granularity: 401K and IRA accounts that are taxed as
ordinary income when you withdraw, Roth accounts that are tax-free, a taxable brokerage with capital
gains exposure, an HSA earmarked for medical costs, a 529 for education. Flint tracks the tax
treatment of each account type, models Required Minimum Distributions when they kick in, and
applies federal and state income tax to each year's withdrawals.

The result is a simulation that reflects *your* retirement rather than an idealized average. A
50-year-old with a paid-off house, grown children, and Social Security starting in fifteen years
has a fundamentally different spending profile from a 60-year-old still supporting a family and
carrying a mortgage. Flint lets you model both, and everything in between, including one-time
events like selling a house, an inheritance, or a child starting college.

## Requirements

**Python 3.11 or later** is required. No third-party packages are needed.

## Running Flint

```
python flint.py [options]
```

| Option | Description | Default |
|---|---|---|
| `--scenario NAME` | Load `scenarios/<name>.toml` | First non-default scenario alphabetically; falls back to `default` |
| `--port PORT` | Port for the local web server | 8080 |

On startup Flint runs an initial simulation and launches a local web server. Open
`http://localhost:8080` (or the port you chose) in a browser to see the results. Press **Ctrl-C**
to stop the server.

### Multiple scenarios

Scenario files live in `scenarios/`. Any `.toml` file placed there is automatically discovered.
The web UI has a scenario dropdown that lets you switch between them without restarting.

## The Web UI

The results page shows:

- **Starting Portfolio**: Total assets at the beginning of retirement. Click this to see how assets
  are projected to grow between the current year and the start of retirement.
- **Simulations Run**: One simulation per historical S&P 500 period of matching length.
- **Median Outcome**: The median final portfolio value across all simulations.
- **Success Rate**: The fraction of simulations that ended with positive assets.
- **Outcome Distribution**: A histogram of final portfolio values. Click a bar to see the
  individual simulations in that range. Click a simulation card to see a year-by-year breakdown
  of asset balances.

The **Retire at age / until** controls at the top let you adjust the retirement window and
re-simulate instantly. Use the scenario dropdown on the right to switch scenarios.

## Writing a Scenario File

Scenarios are simple [TOML](http://toml.io) text files in the `scenarios/` directory. The filename
(without `.toml`) becomes the scenario name used in the `--scenario` flag and the UI dropdown.

### Top-level fields

```toml
country = "us"       # Tax jurisdiction country code (currently only "us" is supported)
state   = "ca"       # Two-letter state code for state income tax (optional)

year = 2025          # Base year: the year that all amounts below reflect
age  = 45            # Your age in the base year

retirement_age = 65  # Default retirement age shown in the UI (optional, default 65)
retirement_end = 90  # Default end age shown in the UI (optional, default 90)
```

`year` and `age` are the anchor for everything else. All asset balances, budget amounts, and income
figures should reflect your situation as of that year. Flint projects forward from there.

### Assets

The `[assets]` section lists your current balances by account type.

```toml
[assets]
"Cash"        = 100000
"401K"        = 500000
"Roth 401K"   = 150000
"IRA"         = 80000
"Roth IRA"    = 60000
"Stocks"      = 200000
"Bonds"       = 50000
"529 Plan"    = 80000
"HSA"         = 20000
"Real Estate" = 800000
```

All fields are optional. Omit any account type you don't have.

#### Account types and their tax treatment

| Account | Default growth | Tracks S&P 500 | Tax treatment |
|---|---|---|---|
| Cash | 3% | No | No tax on withdrawal |
| 401K | 7% | Yes | Ordinary income tax |
| Roth 401K | 7% | Yes | Tax-free (Roth) |
| IRA | 8% | Yes | Ordinary income tax |
| Roth IRA | 8% | Yes | Tax-free (Roth) |
| Stocks | 8% | Yes | Capital gains tax |
| Bonds | 4% | No | No tax on withdrawal |
| 529 Plan | 7% | Yes | Reserved for education |
| HSA | 6% | Yes | Reserved for healthcare |
| Real Estate | 3% | No | Reserved (not withdrawn) |

**Tracks S&P 500** means the account's annual growth rate during retirement simulations is taken
directly from historical S&P 500 data. Fixed-rate accounts (Cash, Bonds, Real Estate) use their
default rate regardless of market conditions.

**Reserved** accounts are excluded from the general withdrawal pool. The 529 is used only to cover
education expenses; the HSA covers healthcare shortfalls; Real Estate is held as an asset but not
liquidated. You can release reserved assets using rules (for example, selling a house).

**RMD accounts**: 401K and IRA accounts are subject to Required Minimum Distributions starting at
age 73, computed from IRS life expectancy tables.

**Early withdrawal restriction**: 401K, Roth 401K, IRA, and Roth IRA accounts cannot be withdrawn
before age 59 without penalty. Flint assumes that you never want to incur this penalty, and won't
withdraw from these accounts until you reach the minimum penalty-free age.

#### Growth overrides

Override any account's default annual growth rate with `[assets.growth]`. Values are percentages.

```toml
[assets.growth]
"Real Estate" = 0    # Flat (0% growth)
"Bonds"       = 4.5  # 4.5% instead of the default 4%
```

#### Capital gains percentage

`Capital Gains Percentage` sets what fraction of the current Stocks balance is gains above cost
basis, i.e. what percentage would be subject to capital gains tax if you sold everything today.
The default is `50` (50%).

```toml
[assets]
"Stocks"                   = 500000
"Capital Gains Percentage" = 60     # 60% of Stocks is gains; 40% is cost basis
```

During the simulation, future Stocks contributions (from the `Stocks` budget category) are counted
as new cost basis, which reduces the effective capital gains fraction over time. Market growth
does not change the cost basis; all growth accrues as gains.

### Budget

The `[budget]` section lists annual spending by category. Amounts are in the base year's dollars.
All fields are optional.

```toml
[budget]
"Housing"        = 36000   # Mortgage/rent, property tax, insurance, maintenance
"Utilities"      = 6000    # Electricity, gas, water, internet, phone
"Transportation" = 8000    # Car payments, insurance, fuel, maintenance
"Food"           = 18000   # Groceries and restaurants
"Health"         = 6000    # Health insurance, medical, prescriptions
"School"         = 0       # Tuition, room and board, supplies
"Children"       = 0       # Childcare, activities, supplies
"Debt"           = 0       # Credit card or other debt payments
"Business"       = 0       # Self-employment or business expenses
"Other"          = 12000   # Everything else
```

#### Default inflation rates by category

Each category inflates independently each year using its own default rate.

| Category | Default inflation |
|---|---|
| Housing | 3% |
| Utilities | 4% |
| Transportation | 4% |
| Food | 3% |
| Health | 5% |
| School | 4% |
| Children | 4% |
| Debt | 0% (fixed) |
| Business | 0% (fixed) |
| Other | 3% |

Healthcare inflates at 5% by default (significantly faster than overall inflation) to reflect the
real historical trend of medical costs outpacing overall inflation.

These rates are defaults. When historical CPI data is available, Flint uses actual historical
averages per category instead (computed from the same dataset that drives the S&P 500 simulation),
and during each Monte Carlo retirement replay, expenses grow at the inflation rate that actually
prevailed during that historical period. A scenario where the market performed as it did in the
1970s also inflates your expenses at 1970s rates. The `[budget.growth]` overrides described below
always take precedence over both defaults and historical averages.

Override any category's rate with `[budget.growth]`:

```toml
[budget.growth]
"Health"   = 6    # 6% instead of the default 5%
"Housing"  = 0    # Fixed (mortgage payment doesn't change)
```

#### Contributions

Budget categories that correspond to investment accounts are treated as annual contributions
rather than expenses. They reduce cash flow in the current year and add to the specified account.

| Budget category | Contributes to | Pre-tax? |
|---|---|---|
| Pre-Tax 401K | 401K | Yes (reduces taxable income) |
| After-Tax 401K | 401K | No |
| Roth 401K | Roth 401K | No |
| IRA | IRA | Yes (reduces taxable income) |
| Roth IRA | Roth IRA | No |
| 529 Plan | 529 Plan | No |
| HSA | HSA | No |
| Stocks | Stocks | No |
| Bonds | Bonds | No |

Contributions stop automatically when retirement begins.

#### Employer 401K match

Set `Employer 401K Match` to either a percentage of your pre-tax 401K contribution or a fixed
annual dollar amount:

```toml
# 50% match on employee contributions (e.g. contribute $20K, get $10K matched)
"Employer 401K Match" = "50%"

# Fixed annual match regardless of contribution amount
"Employer 401K Match" = 5000
```

#### 529 eligible expenses

When the School budget covers college costs that qualify for 529 withdrawals, set `529 Eligible`
to indicate what fraction of the School budget should be drawn from the 529 plan:

```toml
"529 Eligible" = "100%"   # All school expenses paid from 529
"529 Eligible" = "75%"    # 75% from 529, remainder from general assets
```

This prevents the 529 from sitting idle when school expenses exist. It is typically set via a rule
in the year your child starts college and cleared when they graduate.

### Income

The `[income]` section specifies annual income.

```toml
[income]
"Job Income"   = 120000   # Primary employment income; stops at retirement
"Other Income" = 10000    # Rental income, part-time work, etc.; continues through retirement
```

Both income types grow at 3% per year by default.

Social Security, pension income, or other retirement income streams that start at a specific age
are best modeled as Other Income rules that set the amount in the year they begin:

```toml
[income]
"Job Income"   = 150000
"Other Income" = 0

rules = [
  {year = 2042, "Other Income" = "=36000"},   # Social Security begins
]
```

---

## Rules

Rules let you model life events that change your assets, budget, or income at specific years.
Each rule is a table entry in the `rules` list with a `year` key and one or more category keys.

```toml
rules = [
  {year = 2035, "Housing" = "=24000", "Food" = "-15%"},
]
```

Multiple events in the same year go in the same rule entry. Events in different years are separate
entries.

### Rule syntax

| Format | Meaning | Example |
|---|---|---|
| `"=N"` | Set to an absolute value | `"=500000"` |
| `"+N"` | Add a dollar amount | `"+200000"` |
| `"-N"` | Subtract a dollar amount | `"-50000"` |
| `"+N%"` | Increase by a percentage | `"+10%"` |
| `"-N%"` | Decrease by a percentage | `"-20%"` |
| `"+N%@Category"` | Add N% of another category's current value | `"+45%@Real Estate"` |
| `"-N%@Category"` | Subtract N% of another category's current value | `"-10%@Stocks"` |
| `N` | (bare number) Set to an absolute value | `500000` |

Cross-category rules (`@Category`) reference another asset's value as it stands *before* any rules
for that year are applied. This makes it straightforward to model transactions where one asset's
proceeds flow into another: the source amount is always the pre-transaction market value, regardless
of what other rules apply to the same year. The category name must match an account type exactly
(e.g. `"Real Estate"`, `"401K"`).

After a rule is applied, Flint may also apply the category's default growth or inflation rate for
that year. The default behavior depends on the rule type:

| Rule type | Growth applied by default? |
|---|---|
| `"=N"` (set) | No, the value is treated as final |
| `"+N"` / `"-N"` (add/subtract) | Yes, growth follows the adjustment |
| `"+N%"` / `"-N%"` (percentage) | Yes, growth follows the adjustment |

Override the default by appending `!` (suppress growth) or `+` (force growth):

```toml
"Housing" = "=24000!"    # Set to $24,000; no inflation applied this year
"Housing" = "=24000+"    # Set to $24,000; then inflate at the Housing rate
"-50000!"                # Subtract $50,000; suppress growth this year
```

### Retirement-relative rules

The `year` key in a rule entry is normally a calendar year integer. You can also write the year
relative to whenever retirement begins, as determined by the **Retire at age** control in the UI
(or the `retirement_age` field in the scenario file):

| Year value | What year the rule applies to |
|---|---|
| `"retirement"` | The first year of retirement |
| `"retirement+N"` | N years after retirement begins |
| `"retirement-N"` | N years before retirement begins |

```toml
[budget]
rules = [
  # Switch to individual health insurance the year retirement begins
  {year = "retirement", "Health" = "+400%"},

  # Assume Medicare kicks in 5 years later and health costs drop
  {year = "retirement+5", "Health" = "-60%"},

  # Ramp down work-related spending the year before you stop working
  {year = "retirement-1", "Transportation" = "-30%", "Other" = "-20%"},
]
```

Retirement-relative rules work in assets, budget, and income. They can be combined with explicit
calendar-year rules that happen to fall in the same year, and are always applied first.

This is useful for events that are tied to the retirement date rather than a fixed calendar year;
for example, changes in spending driven by leaving the workforce, a home sale timed to coincide with
retirement, or a Social Security claim a few years after retiring.

### Sample rules

#### Selling a house

Selling outright: zero out Real Estate and add the proceeds to Cash. The `+95%` accounts for 5%
in sale fees; the cross-category reference ensures the correct amount is transferred even if the
Real Estate value has drifted from your original estimate:

```toml
rules = [
  {year = 2038, "Real Estate" = "=0", "Cash" = "+95%@Real Estate"},
]
```

Downsizing: reduce Real Estate by half and transfer most of the freed value to Cash:

```toml
rules = [
  # Buy a home half the size; net 45% of original value after fees and purchase cost
  {year = 2038, "Real Estate" = "-50%", "Cash" = "+45%@Real Estate"},
]
```

#### A child starting and finishing college

Use `School` to set the annual cost, `529 Eligible` to direct withdrawals from the 529, and a
later rule to zero everything out when they graduate:

```toml
[budget]
"School"   = 0   # No school costs today
"529 Plan" = 12000

rules = [
  {year = 2034, "School" = "=80000", "529 Eligible" = "100%"},   # College begins
  {year = 2038, "School" = "=0",     "529 Eligible" = "0%"},     # Graduates
]
```

Budget items that go to zero can also reduce other categories to reflect expenses that disappear
at the same time (childcare, clothing allowances, etc.):

```toml
{year = 2034, "School" = "=80000", "529 Eligible" = "100%", "Children" = "=0", "Food" = "-10%"},
```

#### Paying off a mortgage

Set Housing to your post-payoff carrying costs (property tax, insurance, maintenance):

```toml
rules = [
  {year = 2032, "Housing" = "=12000"},   # Mortgage paid off; only fixed costs remain
]
```

#### Social Security or pension income

Add income in the year it begins:

```toml
[income]
rules = [
  {year = 2044, "Other Income" = "=36000"},   # Social Security at full retirement age
]
```

If both partners receive Social Security at different ages, combine them into the same Other
Income stream by making the second rule additive:

```toml
rules = [
  {year = 2041, "Other Income" = "=24000"},           # Partner A starts
  {year = 2044, "Other Income" = "+18000"},           # Partner B starts; total is $42K
]
```

#### An inheritance or one-time windfall

Add a lump sum to any asset category:

```toml
rules = [
  {year = 2030, "Cash" = "+250000"},
]
```

#### Changing jobs or phasing to part-time

```toml
[income]
rules = [
  {year = 2033, "Job Income" = "=80000"},   # Downshift to part-time
  {year = 2038, "Job Income" = "=0"},       # Full retirement
]
```

#### Starting a business

```toml
[budget]
rules = [
  {year = 2031, "Business" = "=30000"},   # Annual business expenses begin
  {year = 2040, "Business" = "=0"},       # Wind down
]
```

#### Adjusting contributions over time

Reduce contributions as retirement approaches, or increase them to model catch-up contributions:

```toml
[budget]
"Pre-Tax 401K" = 20000

rules = [
  {year = 2030, "Pre-Tax 401K" = "=23000"},   # IRS limit increases (or catch-up kicks in)
]
```

---

## Complete example

The following scenario models a 45-year-old planning to retire at 65 with a moderately complex
financial picture: a mix of taxable and tax-advantaged accounts, a child heading to college in
five years, and a plan to downsize their home around retirement.

```toml
country = "us"
state   = "ca"

year = 2025
age  = 45

retirement_age = 65
retirement_end = 90

[assets]
"Cash"        = 100000
"401K"        = 1000000
"Roth IRA"    = 200000
"Stocks"      = 700000
"Real Estate" = 1000000

rules = [
  # Sell the family home and downsize; net 45% of current value after fees and replacement cost
  {year = 2040, "Real Estate" = "-50%", "Cash" = "+45%@Real Estate"},
]

[assets.growth]
"Real Estate" = 0   # Conservative assumption: no real appreciation

[budget]
"Housing"     = 50000
"Health"      = 8000
"Food"        = 40000
"Pre-Tax 401K" = 20000

rules = [
  # Child leaves for a private university
  {year = 2030, "School" = "=80000", "529 Eligible" = "100%", "Health" = "-20%", "Food" = "-20%"},
  # Child graduates; school and associated costs drop away
  {year = 2034, "School" = "=0", "529 Eligible" = "0%"},
  # Downsize: mortgage is gone and lifestyle gets cheaper
  {year = 2040, "Housing" = "-40%"},
]

[income]
"Job Income"   = 200000
"Other Income" = 0

rules = [
  {year = 2045, "Other Income" = "=30000"},   # Social Security begins
]
```
