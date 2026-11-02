"""Tax periods are monthly and written 'YYYY-MM' (e.g. '2026-10')."""
from __future__ import annotations

import calendar
from datetime import date


def period_bounds(period: str) -> tuple[date, date]:
    year, month = (int(p) for p in period.split("-"))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def financial_year_end(d: date) -> date:
    """Indian financial year runs 1 April to 31 March."""
    return date(d.year if d.month <= 3 else d.year + 1, 3, 31)
