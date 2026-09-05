import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple, Union

CompareFn = Callable[[str, Sequence[str]], Union[bool, float]]
ValidatorFn = Callable[[str], Union[bool, Tuple[bool, str]]]

VERIFIED = "VERIFIED"
REPAIRED = "REPAIRED"
AMBIGUOUS = "AMBIGUOUS"
BLOCKED = "BLOCKED"
UNCERTAIN = "UNCERTAIN"

DEFAULT_THRESHOLD = 0.7
DEFAULT_MAX_RETRIES = 1

_CONFIDENCE_SUFFIX = """

After answering, output your response as a single JSON object on its \
own line, with exactly these keys, IN THIS ORDER:
{"ambiguous": true/false, "interpretations": ["<reading 1>", "<reading 2>", ...], "chosen_interpretation": "<which reading you answered under, or null if not ambiguous>", "answer": "<your answer, concise>", "confidence": <float 0.0-1.0>}

Set "ambiguous" to true if the question has more than one reasonable, \
meaningfully different answer depending on interpretation (different \
named entities sharing a name, different metrics like assets vs. \
market cap, different time periods, etc.). List those readings in \
"interpretations" (empty list if not ambiguous). If ambiguous, still \
answer under your best-guess interpretation, and name it in \
"chosen_interpretation".

"confidence" is your own honest estimate of the probability that \
"answer" is factually correct, given the interpretation you chose. Do \
not pad the confidence toward 1.0 out of politeness — under-confidence \
and over-confidence are both penalized. Output ONLY the JSON object, \
nothing else."""

_JSON_RE = re.compile(r"\{[^{}]*\}")

# Distinguishes "key absent" from "key present but invalid".
_MISSING = object()


def _coerce_ambiguous(raw) -> Optional[bool]:
    """Real bool passes through. "true"/"false" strings (any case) are
    accepted. Anything else returns None (reject, don't guess)."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


@dataclass
class Attempt:
    raw_text: str
    answer: Optional[str]
    confidence: Optional[float]
    parse_ok: bool
    error: Optional[str] = None
    ambiguous: bool = False
    interpretations: List[str] = field(default_factory=list)
    chosen_interpretation: Optional[str] = None
    passed_validation: bool = True
    validation_error: Optional[str] = None
    parsed: Optional[dict] = None


@dataclass
class BoothResult:
    answer: Optional[str]
    status: str
    confidence: Optional[float] = None
    attempts: List[Attempt] = field(default_factory=list)
    ambiguous: bool = False
    interpretations: List[str] = field(default_factory=list)
    evidence_agreement: Optional[float] = None
    parsed: Optional[dict] = None

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def ok(self) -> bool:
        return self.status in (VERIFIED, REPAIRED)

    @property
    def all_parse_failed(self) -> bool:
        return bool(self.attempts) and all(not a.parse_ok for a in self.attempts)

    @property
    def method(self) -> str:
        if self.status == AMBIGUOUS:
            return "ambiguity"
        if not self.attempts:
            return "evidence"
        if self.all_parse_failed:
            return "parse_failure"
        if not self.attempts[-1].passed_validation:
            return "validation"
        return "confidence"


def _build_prompt(user_prompt: str) -> str:
    return user_prompt.rstrip() + _CONFIDENCE_SUFFIX


def _build_retry_prompt(original_prompt: str, previous: Attempt) -> str:
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"On a previous attempt you answered: \"{previous.answer}\" "
        f"with confidence {previous.confidence}.\n"
        f"Reconsider carefully. If that answer is correct, restate it. "
        f"If it is wrong, give the corrected answer."
        f"{_CONFIDENCE_SUFFIX}"
    )


def _build_parse_failure_prompt(original_prompt: str, previous: Attempt) -> str:
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"Your previous response could not be parsed: it did not "
        f"contain a valid JSON object with the required keys. Output "
        f"your response as a single JSON object with exactly the "
        f"required keys, and nothing else — no markdown code fences, "
        f"no commentary before or after it."
        f"{_CONFIDENCE_SUFFIX}"
    )


def _build_validation_failure_prompt(original_prompt: str, previous: Attempt) -> str:
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"Your previous answer was: \"{previous.answer}\"\n\n"
        f"That answer failed validation: {previous.validation_error}\n\n"
        f"Reconsider carefully and provide a corrected answer that "
        f"satisfies the validation requirement."
        f"{_CONFIDENCE_SUFFIX}"
    )


def _try_json(candidate: str) -> Optional[dict]:
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _parse_response(raw_text: str) -> Attempt:
    candidates = []

    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if lines:
        candidates.append(lines[-1])

    candidates.extend(_JSON_RE.findall(raw_text))

    for candidate in candidates:
        obj = _try_json(candidate)
        if obj is None:
            continue
        answer = obj.get("answer")
        confidence = obj.get("confidence")
        if answer is None or confidence is None:
            continue
        # bool is a subclass of int, so float(True/False) succeeds
        # silently — must reject before the float() conversion.
        if isinstance(confidence, bool):
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= confidence <= 1.0:
            continue

        raw_ambiguous = obj.get("ambiguous", _MISSING)
        if raw_ambiguous is _MISSING:
            ambiguous = False
        else:
            coerced = _coerce_ambiguous(raw_ambiguous)
            if coerced is None:
                continue
            ambiguous = coerced

        interpretations = obj.get("interpretations") or []
        if not isinstance(interpretations, list):
            interpretations = []
        interpretations = [str(i) for i in interpretations]
        chosen = obj.get("chosen_interpretation")
        # `is not None` (not a truthy check) so 0/""/False survive.
        chosen = str(chosen) if chosen is not None else None

        return Attempt(
            raw_text=raw_text,
            answer=str(answer),
            confidence=confidence,
            parse_ok=True,
            ambiguous=ambiguous,
            interpretations=interpretations,
            chosen_interpretation=chosen,
            parsed=obj,
        )

    return Attempt(raw_text=raw_text, answer=None, confidence=None, parse_ok=False)


def _is_boolish(value) -> bool:
    """True for native bool and numpy's boolean scalar (checked by
    type name, not by importing numpy — booth stays zero-dependency).
    numpy >=2.0 renamed the scalar type's __name__ from "bool_" to
    "bool", so both spellings are accepted for cross-version safety."""
    if isinstance(value, bool):
        return True
    t = type(value)
    return t.__module__ == "numpy" and t.__name__ in ("bool_", "bool")


def _run_validator(
    validator: Optional[ValidatorFn], answer: Optional[str]
) -> Tuple[bool, Optional[str]]:
    """Accepted shapes: bool (incl. numpy.bool_), (bool, str),
    (bool, None), and the list form of either tuple."""
    if validator is None or answer is None:
        return True, None
    try:
        result = validator(answer)
    except Exception as e:
        return False, f"Validator raised {type(e).__name__}: {e}"

    if _is_boolish(result):
        passed = bool(result)
        return passed, (None if passed else "Validator returned False")

    if isinstance(result, (tuple, list)) and len(result) == 2:
        passed, message = result
        if _is_boolish(passed) and (message is None or isinstance(message, str)):
            passed = bool(passed)
            if message is None:
                message = None if passed else "Validator returned False (no message provided)"
            return passed, message

    return False, (
        f"Validator returned an invalid type: {type(result).__name__} "
        f"(expected bool or (bool, str))"
    )


def _evaluate(
    attempts: List[Attempt],
    attempt: Attempt,
    attempt_index: int,
    threshold: float,
) -> Optional[BoothResult]:
    if attempt.parse_ok and attempt.ambiguous:
        return BoothResult(
            answer=attempt.answer,
            status=AMBIGUOUS,
            confidence=attempt.confidence,
            attempts=attempts,
            ambiguous=True,
            interpretations=attempt.interpretations,
            parsed=attempt.parsed,
        )

    if attempt.parse_ok and not attempt.passed_validation:
        return None

    if attempt.parse_ok and attempt.confidence >= threshold:
        status = VERIFIED if attempt_index == 0 else REPAIRED
        return BoothResult(
            answer=attempt.answer,
            status=status,
            confidence=attempt.confidence,
            attempts=attempts,
            parsed=attempt.parsed,
        )

    return None


def _next_prompt(original_prompt: str, attempt: Attempt) -> str:
    if not attempt.parse_ok:
        return _build_parse_failure_prompt(original_prompt, attempt)
    if not attempt.passed_validation:
        return _build_validation_failure_prompt(original_prompt, attempt)
    return _build_retry_prompt(original_prompt, attempt)


def _finalize_uncertain(attempts: List[Attempt]) -> BoothResult:
    last_ok = next((a for a in reversed(attempts) if a.parse_ok), None)
    return BoothResult(
        answer=last_ok.answer if last_ok else None,
        status=UNCERTAIN,
        confidence=last_ok.confidence if last_ok else None,
        attempts=attempts,
        parsed=last_ok.parsed if last_ok else None,
    )


def _validate_args(threshold: float, max_retries: int) -> None:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
    if max_retries < 0:
        raise ValueError(f"max_retries must be >= 0, got {max_retries}")


def _validate_evidence_args(evidence_threshold: float) -> None:
    if not 0.0 <= evidence_threshold <= 1.0:
        raise ValueError(
            f"evidence_threshold must be between 0.0 and 1.0, got {evidence_threshold}"
        )


def check_with_evidence(
    answer: str,
    evidence: Sequence[str],
    compare_fn: CompareFn,
    evidence_threshold: float = DEFAULT_THRESHOLD,
) -> BoothResult:
    _validate_evidence_args(evidence_threshold)

    # 0.4.5: a whitespace-only answer is treated as empty, same as "".
    if not answer or not answer.strip() or not evidence:
        return BoothResult(answer=answer or None, status=UNCERTAIN, confidence=None)

    try:
        raw_result = compare_fn(answer, evidence)
    except Exception:
        return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)

    # 0.4.5: use _is_boolish so numpy.bool_ is treated as a strict
    # pass/fail, same as validator results, instead of falling through
    # to the float() branch below.
    if _is_boolish(raw_result):
        passed = bool(raw_result)
        score = 1.0 if passed else 0.0
    else:
        try:
            score = float(raw_result)
        except (TypeError, ValueError):
            return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)
        if not 0.0 <= score <= 1.0:
            return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)
        passed = score >= evidence_threshold

    status = VERIFIED if passed else BLOCKED
    return BoothResult(
        answer=answer,
        status=status,
        confidence=score,
        evidence_agreement=score,
    )


def check(
    call_fn: Callable[[str], str],
    prompt: str,
    threshold: float = DEFAULT_THRESHOLD,
    max_retries: int = DEFAULT_MAX_RETRIES,
    on_attempt: Optional[Callable[[int, Attempt], Any]] = None,
    *,
    validator: Optional[ValidatorFn] = None,
) -> BoothResult:
    _validate_args(threshold, max_retries)
    if on_attempt is not None and inspect.iscoroutinefunction(on_attempt):
        raise TypeError(
            "check() cannot await an async on_attempt callback. "
            "Use acheck() with an async on_attempt, or pass a sync "
            "callback to check()."
        )

    attempts: List[Attempt] = []
    current_prompt = _build_prompt(prompt)

    for i in range(max_retries + 1):
        try:
            raw = call_fn(current_prompt)
        except Exception as e:
            attempt = Attempt(
                raw_text=f"{type(e).__name__}: {e}",
                answer=None,
                confidence=None,
                parse_ok=False,
                error=str(e),
            )
        else:
            attempt = _parse_response(raw)

        if attempt.parse_ok and not attempt.ambiguous:
            passed, err = _run_validator(validator, attempt.answer)
            attempt.passed_validation = passed
            attempt.validation_error = err

        if on_attempt is not None:
            on_attempt(i, attempt)
        attempts.append(attempt)

        result = _evaluate(attempts, attempt, i, threshold)
        if result is not None:
            return result

        current_prompt = _next_prompt(prompt, attempt)

    return _finalize_uncertain(attempts)


async def acheck(
    call_fn: Callable[[str], Awaitable[str]],
    prompt: str,
    threshold: float = DEFAULT_THRESHOLD,
    max_retries: int = DEFAULT_MAX_RETRIES,
    on_attempt: Optional[
        Union[Callable[[int, Attempt], Any], Callable[[int, Attempt], Awaitable[Any]]]
    ] = None,
    *,
    validator: Optional[ValidatorFn] = None,
) -> BoothResult:
    if not inspect.iscoroutinefunction(call_fn):
        raise TypeError(
            "acheck() requires an async call_fn (async def ... -> str). "
            "Use check() for a synchronous call_fn."
        )
    _validate_args(threshold, max_retries)

    attempts: List[Attempt] = []
    current_prompt = _build_prompt(prompt)

    for i in range(max_retries + 1):
        try:
            raw = await call_fn(current_prompt)
        except Exception as e:
            attempt = Attempt(
                raw_text=f"{type(e).__name__}: {e}",
                answer=None,
                confidence=None,
                parse_ok=False,
                error=str(e),
            )
        else:
            attempt = _parse_response(raw)

        if attempt.parse_ok and not attempt.ambiguous:
            passed, err = _run_validator(validator, attempt.answer)
            attempt.passed_validation = passed
            attempt.validation_error = err

        if on_attempt is not None:
            if inspect.iscoroutinefunction(on_attempt):
                await on_attempt(i, attempt)
            else:
                on_attempt(i, attempt)
        attempts.append(attempt)

        result = _evaluate(attempts, attempt, i, threshold)
        if result is not None:
            return result

        current_prompt = _next_prompt(prompt, attempt)

    return _finalize_uncertain(attempts)