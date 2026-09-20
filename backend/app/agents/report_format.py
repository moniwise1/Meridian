"""
The Meridian numeric presentation rules, in one place.

Every generated document - PDF report, PPTX deck, XLSX workbook - has to
show the same figure the same way, so these rules live here rather than
being re-implemented (and drifting) in three generators. Nothing in this
module reads or derives business data; it only decides how an
already-computed number is written down.

Two rules here exist because getting them wrong produces a confidently
wrong report rather than an obviously broken one:

- A rate is stored as a rate and formatted once. A value of 94.2 that is
  already a percentage must never be formatted as a percentage a second
  time, which is what turns 94.2% into 9,420.0%. `looks_like_bad_percent`
  detects the result of that mistake so the report can FLAG it. It
  deliberately does not repair anything: silently dividing by 100 would
  hide a real defect in the customer's source data, and the correct
  figure cannot be known from this side.

- A change in a percentage is not a percentage change. Going from 40.2%
  to 33.1% is 7.1 percentage POINTS, not 7.1%. `fmt_pp_change` and
  `fmt_growth` are separate functions so a caller has to choose.
"""
from __future__ import annotations

# A rate can legitimately exceed 100% (growth, variance, utilisation
# against a soft target), so the ceiling here is only applied to fields
# the caller has said are bounded - see `looks_like_bad_percent`.
BOUNDED_RATE_MAX = 100.0

# Above this, a "percentage" is far more likely to be a double-formatted
# rate than a real figure. 9,420% is the real case this comes from; a
# genuine 150% growth figure stays well clear of it.
IMPLAUSIBLE_PERCENT = 1000.0

_RATE_WORDS = ("rate", "ratio", "share", "percent", "percentage", "utilisation",
               "utilization", "completeness", "margin", "conversion", "on-time", "on time")


def as_number(value) -> float | None:
    """A float, or None for anything that is not a real finite number.

    Strings are accepted because extracted-document values arrive as text
    ("1,250", "40.2%"); a value that cannot be read as a number returns
    None so the caller can omit it rather than print a zero it invented.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text:
            return None
        try:
            f = float(text)
        except ValueError:
            return None
    # NaN and the infinities are not printable figures.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def abbreviate(value) -> str:
    """709_000_000 -> '709.0m';  1_250_000_000 -> '1.25bn';  36688 -> '36,688'.

    Millions carry one decimal and billions two, matching the Meridian
    examples. Anything under a million is written out in full with
    thousands separators rather than abbreviated, so an order count or a
    unit price stays readable as itself.
    """
    n = as_number(value)
    if n is None:
        return ""
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n >= 1_000_000_000:
        return f"{sign}{n / 1_000_000_000:,.2f}bn"
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:,.1f}m"
    if n == int(n):
        return f"{sign}{int(n):,}"
    return f"{sign}{n:,.2f}"


def fmt_currency(value, code: str = "NGN") -> str:
    """'NGN 709.0m'. The code is written out rather than using a symbol:
    fpdf2's core fonts are Latin-1 and have no Naira glyph, and 'NGN' is
    unambiguous in a document that may be read outside Nigeria."""
    n = as_number(value)
    if n is None:
        return ""
    return f"{code} {abbreviate(n)}"


def fmt_number(value) -> str:
    """'19,325'. Whole numbers keep their separators; fractions keep two
    decimals so a unit price does not silently round to a whole."""
    n = as_number(value)
    if n is None:
        return ""
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


def fmt_percent(value, decimals: int = 1) -> str:
    """Formats a value that is ALREADY a percentage: 40.2 -> '40.2%'.

    Takes a percentage rather than a decimal fraction because that is the
    form figures arrive in from the analysis pipeline (a chart whose unit
    is '%' carries 40.2, not 0.402). `fmt_rate` is the one that takes a
    fraction, for callers holding 0.402.
    """
    n = as_number(value)
    if n is None:
        return ""
    return f"{n:.{decimals}f}%"


def fmt_rate(value, decimals: int = 1) -> str:
    """Formats a stored decimal rate: 0.402 -> '40.2%'."""
    n = as_number(value)
    if n is None:
        return ""
    return f"{n * 100:.{decimals}f}%"


def fmt_growth(old, new, decimals: int = 1) -> str:
    """Relative change between two figures, signed: '+84.9%'.

    Returns '' when the baseline is zero or missing - a percentage change
    from nothing is undefined, and printing a large number there would be
    an invented figure.
    """
    a, b = as_number(old), as_number(new)
    if a is None or b is None or a == 0:
        return ""
    change = (b - a) / abs(a) * 100
    return f"{change:+.{decimals}f}%"


def fmt_pp_change(old_pct, new_pct, decimals: int = 1) -> str:
    """Difference between two percentages, in points: '-7.1 percentage points'.

    Deliberately spelled out. '7.1%' would be read as a relative change
    (which, for 40.2 -> 33.1, is 17.7%) and is the single most common way
    a ratio improvement gets misreported.
    """
    a, b = as_number(old_pct), as_number(new_pct)
    if a is None or b is None:
        return ""
    diff = b - a
    unit = "percentage point" if abs(round(diff, decimals)) == 1 else "percentage points"
    return f"{diff:+.{decimals}f} {unit}"


def is_rate_label(label: str | None) -> bool:
    """Whether a column/unit/title names something measured as a rate."""
    text = (label or "").replace("_", " ").lower()
    if "%" in text:
        return True
    return any(word in text for word in _RATE_WORDS)


def looks_like_bad_percent(value, label: str | None = None) -> bool:
    """True when a value presented as a percentage cannot be one.

    This is the 9,420% case: a rate stored as 94.20 and then formatted as
    a percentage again. It reports the defect and never repairs it - the
    true value may be 94.2% or 9.42%, and only the source can say which.
    """
    if not is_rate_label(label):
        return False
    n = as_number(value)
    if n is None:
        return False
    return n < 0 or n > IMPLAUSIBLE_PERCENT


def percent_warnings(labels: list, values: list, unit: str | None = None,
                     title: str | None = None) -> list[str]:
    """Plain-language warnings for a chart whose values are impossible as
    percentages. Empty list when the chart is not a percentage chart or
    every value is plausible."""
    if not (is_rate_label(unit) or is_rate_label(title)):
        return []
    bad = []
    for label, value in zip(labels, values):
        if looks_like_bad_percent(value, unit or title or "%"):
            n = as_number(value)
            bad.append(f"{label}: {n:,.1f}" if n is not None else str(label))
    if not bad:
        return []
    listed = "; ".join(bad[:6])
    more = f" (and {len(bad) - 6} more)" if len(bad) > 6 else ""
    return [
        f"Impossible percentage values are present and have not been altered: {listed}{more}. "
        f"A rate stored as 94.20 and then formatted as a percentage again becomes 9,420.0%. "
        f"Repair the source field and rerun before using this measure for any decision."
    ]


def format_metric(label: str | None, value, currency: str = "NGN") -> str:
    """Formats a figure according to what its own label says it is.

    A label mentioning a rate is written as a percentage, a label naming
    a count is written as a plain number, and everything else is treated
    as currency - which is what the analysis pipeline's monetary sums
    are. Returns '' for a value that is not a number, so a caller can
    drop the card rather than show a blank or a zero.
    """
    n = as_number(value)
    if n is None:
        return ""
    text = (label or "").lower()
    if is_rate_label(label):
        return fmt_percent(n)
    if any(word in text for word in ("count", "rows", "orders", "items", "units", "number of", "quantity")):
        return fmt_number(n)
    return fmt_currency(n, currency)
