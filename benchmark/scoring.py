"""
Grading logic: "is this extracted value correct" against ground truth.
Kept separate from run_benchmark.py's orchestration so it's independently
unit-testable — the actual accuracy numbers in the README are only as
trustworthy as this comparison logic is correct.
"""
import re


def values_match(extracted: str | None, expected: str | None) -> bool:
    """Normalizes both sides before comparing, so formatting differences that
    don't change the *meaning* of a value (extra whitespace, "$1,245.50" vs
    "1245.50", trailing ".0") don't count as extraction errors.
    """
    if expected is None:
        return extracted is None or extracted.strip() == ""
    if extracted is None:
        return False

    expected_n = _normalize(expected)
    extracted_n = _normalize(extracted)
    if expected_n == extracted_n:
        return True

    # Numeric comparison (weights, currency): tolerate formatting differences
    # ($, commas) and floating point noise, but not an actually different
    # number.
    expected_num = _try_float(expected)
    extracted_num = _try_float(extracted)
    if expected_num is not None and extracted_num is not None:
        return abs(expected_num - extracted_num) < 0.01

    return False


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _try_float(value: str) -> float | None:
    cleaned = re.sub(r"[,$]", "", value.strip())
    try:
        return float(cleaned)
    except ValueError:
        return None
