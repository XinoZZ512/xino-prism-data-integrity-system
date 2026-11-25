from __future__ import annotations

import math
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def column_letter(index: int) -> str:
    result = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def cell_range(row: int, start_col: int, end_col: int) -> str:
    return f"{column_letter(start_col)}{row}:{column_letter(max(start_col, end_col))}{row}"


def cell_address(row: int, col: int) -> str:
    return f"{column_letter(col)}{row}"


def parse_scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return None
    if not _NUMBER_RE.match(text):
        return text
    try:
        if not any(marker in text for marker in ".eE"):
            return int(text)
        return float(text)
    except ValueError:
        return text


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and math.isfinite(float(value))


def as_float(value: Any) -> float | None:
    if not is_number(value):
        return None
    return float(value)


def stable_value(value: Any) -> str:
    if value is None:
        return "<blank>"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value).strip()


def decimal_tail(value: Any) -> str | None:
    if not is_number(value):
        return None
    try:
        decimal = Decimal(str(value)).copy_abs()
    except (InvalidOperation, ValueError):
        return None
    text = format(decimal, "f")
    if "." not in text:
        return None
    fraction = text.split(".", 1)[1].rstrip("0")
    return fraction[-1] if fraction else "0"


def terminal_digit(value: Any) -> str | None:
    if not is_number(value):
        return None
    text = format(Decimal(str(value)).copy_abs(), "f").replace(".", "").lstrip("0")
    return text[-1] if text else "0"


def shannon_entropy(counts: Iterable[int]) -> float:
    values = [count for count in counts if count]
    total = sum(values)
    if total == 0 or len(values) <= 1:
        return 0.0
    entropy = 0.0
    for count in values:
        probability = count / total
        entropy -= probability * math.log2(probability)
    return entropy


def chi_square_sf_df8(statistic: float) -> float:
    """Exact survival function for chi-square with eight degrees of freedom."""
    if statistic < 0:
        return 1.0
    x = statistic / 2.0
    return math.exp(-x) * (1.0 + x + (x**2) / 2.0 + (x**3) / 6.0)


def json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
