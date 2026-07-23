"""Application-wide formatting and parsing for user-facing general numbers."""

from __future__ import annotations

import math
from typing import Final


US_NUMBER_FORMAT: Final = "1,000.00"
EUROPEAN_NUMBER_FORMAT: Final = "1.000,00"
NUMBER_FORMATS: Final = (US_NUMBER_FORMAT, EUROPEAN_NUMBER_FORMAT)

_active_number_format = US_NUMBER_FORMAT


def normalize_number_format(value: object) -> str:
    """Return a supported number-format identifier, defaulting to U.S. style."""
    text = str(value).strip()
    return text if text in NUMBER_FORMATS else US_NUMBER_FORMAT


def set_active_number_format(value: object) -> str:
    """Set the process-wide display convention used by the desktop application."""
    global _active_number_format
    _active_number_format = normalize_number_format(value)
    return _active_number_format


def active_number_format() -> str:
    """Return the current application-wide display convention."""
    return _active_number_format


def format_number(
    value: float | int,
    _config: object | None = None,
    *,
    max_decimal_places: int = 2,
) -> str:
    """Format a finite number and trim decimal places that are not needed."""
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    decimal_places = max(int(max_decimal_places), 0)
    if round(number, decimal_places) == 0:
        number = 0.0
    result = f"{number:,.{decimal_places}f}"
    if decimal_places:
        result = result.rstrip("0").rstrip(".")
    if _active_number_format == EUROPEAN_NUMBER_FORMAT:
        result = result.translate(str.maketrans({",": ".", ".": ","}))
    return result


def parse_number(value: object, default: float = 0.0) -> float:
    """Parse a number using the active grouping and decimal separators."""
    text = str(value).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if _active_number_format == EUROPEAN_NUMBER_FORMAT:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return default
