import inspect
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple, Union

CompareFn = Callable[[str, Sequence[str]], Union[bool, float]]
ValidatorFn = Callable[[str], Union[bool, Tuple[bool, str]]]

ACCEPTED = "ACCEPTED"
REPAIRED = "REPAIRED"
AMBIGUOUS = "AMBIGUOUS"
BLOCKED = "BLOCKED"
UNCERTAIN = "UNCERTAIN"

# Set by check_with_evidence() only. check()/acheck() results carry reason=None.
EMPTY_ANSWER = "EMPTY_ANSWER"
NO_EVIDENCE = "NO_EVIDENCE"
EVIDENCE_DISAGREES = "EVIDENCE_DISAGREES"
COMPARE_FAILED = "COMPARE_FAILED"
INVALID_SCORE = "INVALID_SCORE"

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

_MISSING = object()  # tells "key absent" apart from "key present but invalid"


def _coerce_ambiguous(raw) -> Optional[bool]:
    """Accept a real bool or "true"/"false" (any case). Anything else is None."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _is_async_callable(fn) -> bool:
    """async def, a partial of one, or an object with async def __call__."""
    return (
        inspect.iscoroutinefunction(fn)
        or inspect.iscoroutinefunction(getattr(fn, "__call__", None))
    )


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
    # True when call_fn raised or returned a non-str, so there was no response to parse.
    call_failed: bool = False


class BoothRejected(Exception):
    """Raised by BoothResult.unwrap() on a non-ok result.

    The full result is on `.result`. The message leaves out the rejected
    answer text on purpose, since exception messages tend to end up in logs.
    """

    def __init__(self, result: "BoothResult"):
        self.result = result
        super().__init__(
            f"BoothResult was not ok (status={result.status}, "
            f"method={result.method}). Inspect the `.result` attribute "
            f"on this exception for the full result, including "
            f"`.result.answer` if you need the rejected text."
        )


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
    reason: Optional[str] = None
    detail: Optional[str] = None

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def ok(self) -> bool:
        return self.status in (ACCEPTED, REPAIRED)

    @property
    def all_parse_failed(self) -> bool:
        return bool(self.attempts) and all(not a.parse_ok for a in self.attempts)

    @property
    def call_failed(self) -> bool:
        """True if every attempt failed because call_fn itself failed.

        Derived from the attempts, same idea as all_parse_failed. A call error
        and a garbage response both still report method == "parse_failure";
        use this (or attempt.call_failed) to tell them apart.
        """
        return bool(self.attempts) and all(a.call_failed for a in self.attempts)

    @property
    def checker_failed(self) -> bool:
        """True when compare_fn crashed or returned an unusable score."""
        return self.reason in (COMPARE_FAILED, INVALID_SCORE)

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

    def unwrap(self) -> str:
        """Return .answer if the result is ok, otherwise raise BoothRejected.

        .answer itself stays populated on rejected results, for debugging.
        """
        if not self.ok or self.answer is None:
            raise BoothRejected(self)
        return self.answer

    def unwrap_or(self, default: str) -> str:
        """Like unwrap(), but return `default` instead of raising."""
        try:
            return self.unwrap()
        except BoothRejected:
            return default

    def to_dict(self) -> dict:
        # asdict() on the dataclass would miss the computed properties.
        return {
            "answer": self.answer,
            "status": self.status,
            "confidence": self.confidence,
            "attempts": [asdict(a) for a in self.attempts],
            "ambiguous": self.ambiguous,
            "interpretations": self.interpretations,
            "evidence_agreement": self.evidence_agreement,
            "parsed": self.parsed,
            "n_attempts": self.n_attempts,
            "ok": self.ok,
            "all_parse_failed": self.all_parse_failed,
            "call_failed": self.call_failed,
            "method": self.method,
            "reason": self.reason,
            "detail": self.detail,
            "checker_failed": self.checker_failed,
        }


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


def _iter_raw_decoded_objects(text: str):
    """Yield every JSON object that starts at a '{' in the text.

    The flat regex can't handle braces inside string values, raw_decode can.
    """
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _parse_response(raw_text: str) -> Attempt:
    candidates: List[Union[str, dict]] = []

    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if lines:
        candidates.append(lines[-1])

    candidates.extend(_JSON_RE.findall(raw_text))
    candidates.extend(_iter_raw_decoded_objects(raw_text))

    last_reason: Optional[str] = None  # why the last candidate was rejected

    for candidate in candidates:
        obj = candidate if isinstance(candidate, dict) else _try_json(candidate)
        if obj is None:
            if last_reason is None:
                last_reason = "no candidate contained a valid JSON object"
            continue

        answer = obj.get("answer")
        confidence = obj.get("confidence")
        if answer is None or confidence is None:
            last_reason = "JSON object is missing the required 'answer' or 'confidence' key"
            continue

        # Scalars get stringified. dict/list would turn into a repr that
        # looks like a real answer, so those are rejected.
        if isinstance(answer, (dict, list)):
            last_reason = "'answer' was a dict/list, not a scalar value"
            continue
        if not isinstance(answer, str):
            answer = str(answer)

        if isinstance(confidence, bool):  # bool is an int subclass, so check before float()
            last_reason = "'confidence' was a boolean, not a number"
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            last_reason = f"'confidence' could not be converted to a float: {confidence!r}"
            continue
        if not 0.0 <= confidence <= 1.0:
            last_reason = f"'confidence' {confidence} is out of the [0.0, 1.0] range"
            continue

        raw_ambiguous = obj.get("ambiguous", _MISSING)
        if raw_ambiguous is _MISSING:
            ambiguous = False
        else:
            coerced = _coerce_ambiguous(raw_ambiguous)
            if coerced is None:
                last_reason = f"'ambiguous' had an unrecognized value: {raw_ambiguous!r}"
                continue
            ambiguous = coerced

        # A blank answer is fine when ambiguous, the interpretations carry the content.
        if not ambiguous and not answer.strip():
            last_reason = "'answer' was empty or whitespace-only"
            continue

        interpretations = obj.get("interpretations") or []
        if not isinstance(interpretations, list):
            interpretations = []
        interpretations = [str(i) for i in interpretations]
        chosen = obj.get("chosen_interpretation")
        chosen = str(chosen) if chosen is not None else None  # keep falsy values like 0

        return Attempt(
            raw_text=raw_text,
            answer=answer,
            confidence=confidence,
            parse_ok=True,
            ambiguous=ambiguous,
            interpretations=interpretations,
            chosen_interpretation=chosen,
            parsed=obj,
        )

    return Attempt(
        raw_text=raw_text,
        answer=None,
        confidence=None,
        parse_ok=False,
        error=last_reason or "no JSON object could be extracted from the response",
    )


def _is_boolish(value) -> bool:
    """Native bool or a numpy bool, matched by name so numpy isn't imported."""
    if isinstance(value, bool):
        return True
    t = type(value)
    return t.__module__ == "numpy" and t.__name__ in ("bool_", "bool")


def _run_validator(
    validator: Optional[ValidatorFn], answer: Optional[str]
) -> Tuple[bool, Optional[str]]:
    """Run the validator. Returns (passed, error_message).

    Accepts bool, (bool, str), (bool, None), or the list form of either tuple.
    """
    if validator is None or answer is None:
        return True, None
    try:
        result = validator(answer)
    except Exception as e:
        return False, f"Validator raised {type(e).__name__}: {e}"

    if inspect.iscoroutine(result):
        result.close()  # avoids a "never awaited" warning
        return False, (
            "Validator returned a coroutine — validator must be "
            "synchronous. If your check needs to await something, "
            "resolve it before calling check()/acheck() and pass a "
            "plain sync function."
        )

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
    """Return a final result for this attempt, or None to keep going."""
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

    if attempt.parse_ok and attempt.confidence is not None and attempt.confidence >= threshold:
        status = ACCEPTED if attempt_index == 0 else REPAIRED
        return BoothResult(
            answer=attempt.answer,
            status=status,
            confidence=attempt.confidence,
            attempts=attempts,
            parsed=attempt.parsed,
        )

    return None


def _next_prompt(original_prompt: str, attempt: Attempt) -> str:
    if attempt.call_failed:
        # Nothing came back to comment on, so just ask again.
        return _build_prompt(original_prompt)
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
    if not isinstance(max_retries, int):
        raise TypeError(f"max_retries must be an int, got {type(max_retries).__name__}")
    if max_retries < 0:
        raise ValueError(f"max_retries must be >= 0, got {max_retries}")


def _validate_call_args(prompt, call_fn) -> None:
    if not isinstance(prompt, str):
        raise TypeError(f"prompt must be a str, got {type(prompt).__name__}")
    if not callable(call_fn):
        raise TypeError(f"call_fn must be callable, got {type(call_fn).__name__}")


def _validate_on_attempt_callable(on_attempt) -> None:
    # Fail before any LLM call is spent.
    if on_attempt is not None and not callable(on_attempt):
        raise TypeError(f"on_attempt must be callable, got {type(on_attempt).__name__}")


def _validate_evidence_args(evidence_threshold: float) -> None:
    # bool is rejected here (unlike max_retries): True/False as a threshold is almost certainly a mistake.
    if isinstance(evidence_threshold, bool) or not isinstance(evidence_threshold, (int, float)):
        raise TypeError(
            f"evidence_threshold must be a real number, got {type(evidence_threshold).__name__}"
        )
    if not 0.0 <= evidence_threshold <= 1.0:
        raise ValueError(
            f"evidence_threshold must be between 0.0 and 1.0, got {evidence_threshold}"
        )


def _is_empty_evidence(evidence) -> bool:
    # len() instead of `not evidence`, which raises for multi-element numpy arrays.
    try:
        return len(evidence) == 0
    except TypeError:
        return not evidence


def check_with_evidence(
    answer: str,
    evidence: Sequence[str],
    compare_fn: CompareFn,
    evidence_threshold: float = DEFAULT_THRESHOLD,
) -> BoothResult:
    _validate_evidence_args(evidence_threshold)

    if answer is not None and not isinstance(answer, str):
        raise TypeError(f"answer must be a str, got {type(answer).__name__}")

    if not answer or not answer.strip():
        return BoothResult(
            answer=None, status=UNCERTAIN, confidence=None,
            reason=EMPTY_ANSWER, detail="answer was empty or whitespace-only",
        )
    if _is_empty_evidence(evidence):
        return BoothResult(
            answer=answer, status=UNCERTAIN, confidence=None,
            reason=NO_EVIDENCE, detail="evidence sequence was empty",
        )

    try:
        raw_result = compare_fn(answer, evidence)
    except Exception as e:
        return BoothResult(
            answer=answer, status=UNCERTAIN, confidence=None,
            reason=COMPARE_FAILED, detail=f"{type(e).__name__}: {str(e)[:200]}",
        )

    # An async compare_fn just hands back a coroutine instead of raising.
    if inspect.iscoroutine(raw_result):
        raw_result.close()
        raise TypeError(
            "compare_fn must be synchronous and return bool or float "
            "directly, not a coroutine. check_with_evidence() does "
            "not support an async compare_fn."
        )

    # Booleans are strict pass/fail, so evidence_threshold doesn't apply to them.
    if _is_boolish(raw_result):
        passed = bool(raw_result)
        score = 1.0 if passed else 0.0
        block_detail = None if passed else "compare_fn returned False"
    else:
        try:
            score = float(raw_result)
        except (TypeError, ValueError):
            return BoothResult(
                answer=answer, status=UNCERTAIN, confidence=None,
                reason=INVALID_SCORE,
                detail=f"compare_fn returned a non-numeric value: {raw_result!r}",
            )
        if not 0.0 <= score <= 1.0:
            return BoothResult(
                answer=answer, status=UNCERTAIN, confidence=None,
                reason=INVALID_SCORE,
                detail=f"compare_fn returned {score}, outside the [0.0, 1.0] range",
            )
        passed = score >= evidence_threshold
        block_detail = (
            None if passed
            else f"score {score} below evidence_threshold {evidence_threshold}"
        )

    status = ACCEPTED if passed else BLOCKED
    return BoothResult(
        answer=answer,
        status=status,
        confidence=score,
        evidence_agreement=score,
        reason=None if passed else EVIDENCE_DISAGREES,
        detail=block_detail,
    )


def _attempt_from_call_error(e: Exception) -> Attempt:
    """call_fn raised, so there is no response to parse."""
    return Attempt(
        raw_text=f"{type(e).__name__}: {e}",
        answer=None,
        confidence=None,
        parse_ok=False,
        error=str(e),
        call_failed=True,
    )


def _call_fn_to_attempt(raw) -> Optional[Attempt]:
    """Turn a non-str return from call_fn into a failed Attempt.

    Returns None when raw is a str, meaning normal parsing should go ahead.
    """
    if isinstance(raw, str):
        return None
    return Attempt(
        raw_text=repr(raw),
        answer=None,
        confidence=None,
        parse_ok=False,
        error=f"call_fn returned {type(raw).__name__}, expected str",
        call_failed=True,
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
    _validate_call_args(prompt, call_fn)
    _validate_args(threshold, max_retries)
    if _is_async_callable(call_fn):
        raise TypeError(
            "check() requires a synchronous call_fn. Use acheck() for "
            "an async call_fn (async def ... -> str, or an object "
            "with an async def __call__)."
        )
    _validate_on_attempt_callable(on_attempt)
    if on_attempt is not None and _is_async_callable(on_attempt):
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
            attempt = _attempt_from_call_error(e)
        else:
            bad_return = _call_fn_to_attempt(raw)
            attempt = bad_return if bad_return is not None else _parse_response(raw)

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
    _validate_call_args(prompt, call_fn)
    if not _is_async_callable(call_fn):
        raise TypeError(
            "acheck() requires an async call_fn (async def ... -> str, "
            "or an object with an async def __call__). Use check() for "
            "a synchronous call_fn."
        )
    _validate_args(threshold, max_retries)
    _validate_on_attempt_callable(on_attempt)  # sync or async is decided per call below

    attempts: List[Attempt] = []
    current_prompt = _build_prompt(prompt)

    for i in range(max_retries + 1):
        try:
            raw = await call_fn(current_prompt)
        except Exception as e:
            attempt = _attempt_from_call_error(e)
        else:
            bad_return = _call_fn_to_attempt(raw)
            attempt = bad_return if bad_return is not None else _parse_response(raw)

        if attempt.parse_ok and not attempt.ambiguous:
            passed, err = _run_validator(validator, attempt.answer)
            attempt.passed_validation = passed
            attempt.validation_error = err

        if on_attempt is not None:
            if _is_async_callable(on_attempt):
                await on_attempt(i, attempt)
            else:
                on_attempt(i, attempt)
        attempts.append(attempt)

        result = _evaluate(attempts, attempt, i, threshold)
        if result is not None:
            return result

        current_prompt = _next_prompt(prompt, attempt)

    return _finalize_uncertain(attempts)