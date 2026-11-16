"""Bounded reference grading, independent of the source-field comparator.

Only ``case['reference']`` is consulted.  Arithmetic is rational, and answers
are never rounded.  This module is not a general natural-language grader.
"""

from fractions import Fraction
import re


# Full matches deliberately exclude explanations, exponent notation, slash
# fractions, ambiguous currency symbols and strings containing two quantities.
_NUMBER = r"[+-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
_UNIT = r"percentage\s+points?|percent|fraction|days?|months?|items?|CAD|USD|EUR|%"
_SCALE = r"(?:\s+(?P<scale>thousand|million))?"
_AFTER = re.compile(
    rf"(?P<number>{_NUMBER}){_SCALE}\s*(?P<unit>{_UNIT})", re.IGNORECASE
)
_BEFORE = re.compile(
    rf"(?P<unit>CAD|USD|EUR)\s*(?P<number>{_NUMBER}){_SCALE}", re.IGNORECASE
)
_PAREN_AFTER = re.compile(
    rf"\((?P<number>{_NUMBER})\){_SCALE}\s*(?P<unit>{_UNIT})", re.IGNORECASE
)
_PAREN_BEFORE = re.compile(
    rf"(?P<unit>CAD|USD|EUR)\s*\((?P<number>{_NUMBER})\){_SCALE}", re.IGNORECASE
)
_UNIT_NAMES = {
    "cad": "CAD", "usd": "USD", "eur": "EUR",
    "days": "days", "months": "months", "items": "items",
    "day": "days", "month": "months", "item": "items",
    "percentage point": "percentage points",
    "percentage points": "percentage points",
    "percent": "rate", "%": "rate", "fraction": "rate",
}


def _quantity(text):
    """Return (exact base-unit value, dimension) or raise ValueError."""
    if not isinstance(text, str):
        raise ValueError("answer is not text")
    text = text.strip()
    # Also allow accounting parentheses around the complete quantity.
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    match = None
    for pattern in (_AFTER, _BEFORE, _PAREN_AFTER, _PAREN_BEFORE):
        match = pattern.fullmatch(text)
        if match:
            if pattern in (_PAREN_AFTER, _PAREN_BEFORE):
                if negative:
                    raise ValueError("nested negative parentheses")
                negative = True
            break
    if match is None:
        raise ValueError("unsupported quantity grammar")
    number = match.group("number")
    if negative and number.startswith(("-", "+")):
        raise ValueError("signed number inside negative parentheses")
    value = Fraction(number.replace(",", ""))
    if negative:
        value = -value
    unit = " ".join(match.group("unit").lower().split())
    scale = match.group("scale")
    if scale:
        if unit not in ("cad", "usd", "eur"):
            raise ValueError("scales supported for currencies only")
        value *= {"thousand": 1000, "million": 1000000}[scale.lower()]
    if unit in ("percent", "%"):
        value /= 100
    return value, _UNIT_NAMES[unit]


def grade_answer(case, answer):
    """Grade one answer against the declared reference, with no rounding.

    Labels are correct, wrong, unscoreable, and no_answer.  Empty text and
    None represent missing answers; unsupported nonempty text is unscoreable.
    Invalid references fail closed as unscoreable rather than supplying a
    correctness label.  Source facts, questions, controls, and rounding metadata
    do not participate in grading.
    """
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return {"label": "no_answer", "detail": "no answer supplied"}
    try:
        observed = _quantity(answer)
    except (ValueError, TypeError, OverflowError):
        return {"label": "unscoreable", "detail": "unsupported answer quantity"}
    try:
        reference = case["reference"]
        expected = _quantity(reference["value"] + " " + reference["unit"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return {"label": "unscoreable", "detail": "invalid declared reference"}
    if observed == expected:
        return {"label": "correct", "detail": "exact reference value and unit match"}
    if observed[1] != expected[1]:
        return {"label": "wrong", "detail": "unit or currency differs from reference"}
    return {"label": "wrong", "detail": "numeric value differs from reference"}
