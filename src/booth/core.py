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

_MISSING = object()  # distinguishes "key absent" from "key present but invalid"


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


def _is_async_callable(fn) -> bool:
    """True for async def, functools.partial of one, or an object with
    async def __call__. A sync __call__ that returns an awaitable at
    runtime is intentionally not detected — no signature-level way to
    tell without calling it."""
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


class BoothRejected(Exception):
    """0.5.0: raised by BoothResult.unwrap() when the result is not ok
    (status is AMBIGUOUS, UNCERTAIN, or BLOCKED). Carries the full
    original BoothResult as `.result`, so a caller handling this
    exception can still inspect `.status`, `.method`, `.attempts`, and
    everything else — unwrap() trades away the answer, not the
    diagnostics.

    Deliberately excludes the raw answer/evidence text from the
    exception's own string message: exception messages routinely end
    up in logs, and a rejected answer is exactly the kind of content
    that shouldn't be logged by default just because someone called
    unwrap(). Inspect `.result.answer` explicitly if you need it."""

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
        """0.5.0: returns `.answer` as a plain `str` if this result is
        ok (ACCEPTED or REPAIRED) — uses exactly the same predicate as
        `.ok`, so the two can never disagree. Raises BoothRejected
        otherwise, carrying the full result on the exception.

        This does not change `.answer` itself: it stays populated on
        rejected results (AMBIGUOUS/UNCERTAIN/BLOCKED) exactly as
        before, intentionally, for debugging and logging visibility
        into what got rejected. unwrap() is a stricter, opt-in
        accessor layered on top of that existing field, not a
        replacement for it — use it when you want a plain `str` back
        (no `Optional[str]` handling at every call site) and you'd
        rather handle rejection as an exception than as an `if`."""
        if not self.ok or self.answer is None:
            raise BoothRejected(self)
        return self.answer

    def unwrap_or(self, default: str) -> str:
        """0.5.0: like unwrap(), but returns `default` instead of
        raising when the result isn't ok."""
        try:
            return self.unwrap()
        except BoothRejected:
            return default

    def to_dict(self) -> dict:
        """Includes computed properties too — asdict(self) alone would
        silently drop them (method, ok, etc. aren't dataclass fields)."""
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
            "method": self.method,
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
    """0.4.9: fallback extractor for item 2. The flat _JSON_RE regex
    only matches a JSON object with no nested braces at all, so an
    object embedded in surrounding prose whose own string values
    happen to contain brace-like text (e.g. "the config is {mode:
    fast}") could never be recovered by regex, even though the object
    is otherwise perfectly well-formed. json.JSONDecoder.raw_decode
    parses a real, balanced JSON value starting at a given position —
    it correctly treats braces inside a quoted string as ordinary
    string content, not structure — so scanning for every '{' and
    trying raw_decode from there recovers cases the regex categorically
    cannot. This runs *in addition to* the regex pass above, not
    instead of it: the regex stays first since it's cheap and covers
    the common case; this is a more thorough, more expensive fallback.
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

    # 0.4.9 item 5: track why each rejected candidate failed, so a
    # total parse failure carries a real reason in Attempt.error
    # instead of being silent about which of several possible schema
    # violations actually happened.
    last_reason: Optional[str] = None

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

        # 0.4.9 item 4: numeric and boolean answers are legitimate
        # scalar values a model might return (e.g. {"answer": 42}) and
        # are coerced to their string form for the normalized .answer
        # field — the raw value is still preserved untouched in
        # .parsed, same split already used for confidence. Structured
        # values (dict/list) are still rejected outright: coercing
        # those via str() would produce a Python repr disguised as a
        # trustworthy answer, the exact bug fixed in 0.4.8.
        if isinstance(answer, (dict, list)):
            last_reason = "'answer' was a dict/list, not a scalar value"
            continue
        if not isinstance(answer, str):
            answer = str(answer)

        if isinstance(confidence, bool):  # bool is an int subclass; reject before float()
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

        # 0.4.9 item 1: an empty or whitespace-only answer is a
        # degenerate response and must not silently pass just because
        # confidence happened to be high. AMBIGUOUS attempts are
        # exempt — the model may legitimately leave answer blank while
        # flagging ambiguity and providing interpretations instead, so
        # this guard must not discard that case.
        if not ambiguous and not answer.strip():
            last_reason = "'answer' was empty or whitespace-only"
            continue

        interpretations = obj.get("interpretations") or []
        if not isinstance(interpretations, list):
            interpretations = []
        interpretations = [str(i) for i in interpretations]
        chosen = obj.get("chosen_interpretation")
        chosen = str(chosen) if chosen is not None else None  # `is not None`, not truthy: keep 0/""/False

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
    """True for native bool and numpy's boolean scalar, checked by type
    name (not importing numpy). Covers both numpy's pre-2.0 "bool_" and
    >=2.0 "bool" names."""
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

    if inspect.iscoroutine(result):
        result.close()  # avoid leaking a "never awaited" RuntimeWarning
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
    # 0.4.8: max_retries=1.5 previously passed this check silently and
    # crashed deep inside range(max_retries + 1) with an unhelpful
    # TypeError far from the actual mistake.
    if not isinstance(max_retries, int):
        raise TypeError(f"max_retries must be an int, got {type(max_retries).__name__}")
    if max_retries < 0:
        raise ValueError(f"max_retries must be >= 0, got {max_retries}")


def _validate_evidence_args(evidence_threshold: float) -> None:
    # 0.4.9 item 6: a string or None previously produced Python's
    # generic comparison TypeError deep inside `0.0 <= evidence_threshold`,
    # the same footgun max_retries had before 0.4.8 fixed it there.
    # bool is explicitly rejected too (unlike max_retries, where
    # True=1/False=0 retries is a harmless, arguably intentional
    # reading) — a bool threshold silently meaning "require a perfect
    # 1.0 score" or "accept anything" is far more likely to be a
    # caller mistake than a deliberate choice.
    if isinstance(evidence_threshold, bool) or not isinstance(evidence_threshold, (int, float)):
        raise TypeError(
            f"evidence_threshold must be a real number, got {type(evidence_threshold).__name__}"
        )
    if not 0.0 <= evidence_threshold <= 1.0:
        raise ValueError(
            f"evidence_threshold must be between 0.0 and 1.0, got {evidence_threshold}"
        )


def _is_empty_evidence(evidence) -> bool:
    """0.4.9 item 3: `not evidence` raises ValueError for a multi-element
    numpy array ("the truth value of an array is ambiguous"), so a
    caller passing evidence=np.array([...]) crashed instead of being
    evaluated normally. len() works correctly for anything sized
    (list, tuple, numpy array, str) without ever consulting __bool__;
    anything without a length (a bare generator, say) falls back to
    the previous truthiness check rather than raising."""
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

    # 0.4.9 item 3: a non-str, non-None answer (e.g. an int or a list)
    # previously crashed with AttributeError on `answer.strip()` below
    # instead of failing predictably. `answer=None` is left as-is —
    # it already short-circuits safely via `not answer` and returning
    # UNCERTAIN for a missing answer is reasonable, existing behavior.
    if answer is not None and not isinstance(answer, str):
        raise TypeError(f"answer must be a str, got {type(answer).__name__}")

    if not answer or not answer.strip() or _is_empty_evidence(evidence):
        return BoothResult(answer=answer or None, status=UNCERTAIN, confidence=None)

    try:
        raw_result = compare_fn(answer, evidence)
    except Exception:
        return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)

    # 0.4.9 item 3: an async compare_fn (or a sync wrapper that itself
    # returns a coroutine, e.g. `lambda a, e: some_async_fn(a, e)`)
    # doesn't raise when called — it just hands back an un-awaited
    # coroutine object. That previously either crashed confusingly
    # inside float(raw_result) or silently fell through, and either
    # way leaked a "coroutine was never awaited" RuntimeWarning.
    # Detected and rejected explicitly instead, the same discipline
    # _run_validator() already applies to an async validator.
    if inspect.iscoroutine(raw_result):
        raw_result.close()
        raise TypeError(
            "compare_fn must be synchronous and return bool or float "
            "directly, not a coroutine. check_with_evidence() does "
            "not support an async compare_fn."
        )

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

    status = ACCEPTED if passed else BLOCKED
    return BoothResult(
        answer=answer,
        status=status,
        confidence=score,
        evidence_agreement=score,
    )


def _call_fn_to_attempt(raw) -> Optional[Attempt]:
    """0.4.8: call_fn succeeded but didn't return a string (None, a
    dict, etc.). Treated the same as a call_fn exception: a failed
    Attempt, not a crash deep inside the parser. Returns None if raw
    IS a string, meaning normal parsing should proceed."""
    if isinstance(raw, str):
        return None
    return Attempt(
        raw_text=repr(raw),
        answer=None,
        confidence=None,
        parse_ok=False,
        error=f"call_fn returned {type(raw).__name__}, expected str",
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
    # 0.4.8: check() previously had no defense against an async
    # call_fn — it would return a coroutine, which _parse_response()
    # then tried to .strip() as text, crashing with AttributeError
    # and leaking an unawaited-coroutine RuntimeWarning. acheck()
    # already rejected the opposite (sync) direction symmetrically;
    # check() now does too.
    if _is_async_callable(call_fn):
        raise TypeError(
            "check() requires a synchronous call_fn. Use acheck() for "
            "an async call_fn (async def ... -> str, or an object "
            "with an async def __call__)."
        )
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
            attempt = Attempt(
                raw_text=f"{type(e).__name__}: {e}",
                answer=None,
                confidence=None,
                parse_ok=False,
                error=str(e),
            )
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
    if not _is_async_callable(call_fn):
        raise TypeError(
            "acheck() requires an async call_fn (async def ... -> str, "
            "or an object with an async def __call__). Use check() for "
            "a synchronous call_fn."
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