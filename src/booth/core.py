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
    # Both default to "validation never applied" — True/None — so a
    # caller who never passes validator= sees zero change in behavior:
    # this branch of _evaluate()/_next_prompt()/method can never fire
    # for them, since "not passed_validation" is always False.
    passed_validation: bool = True
    validation_error: Optional[str] = None


@dataclass
class BoothResult:
    answer: Optional[str]
    status: str
    confidence: Optional[float] = None
    attempts: List[Attempt] = field(default_factory=list)
    ambiguous: bool = False
    interpretations: List[str] = field(default_factory=list)
    evidence_agreement: Optional[float] = None

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
        """Which of BOOTH's mechanisms produced this result. Purely
        derived from existing fields; no new stored state.

            "ambiguity"      — status is AMBIGUOUS
            "evidence"       — result came from check_with_evidence()
                                (attempts == [])
            "parse_failure"  — check()/acheck() UNCERTAIN because every
                                attempt failed to parse or raised
            "validation"     — check()/acheck() UNCERTAIN because the
                                LAST attempt parsed fine but failed a
                                caller-supplied validator (0.4.2+) —
                                distinct from "parse_failure" and from
                                "confidence": the model produced usable
                                output and was confident, but a custom
                                rule rejected it every retry
            "confidence"     — the ordinary case: VERIFIED/REPAIRED, or
                                UNCERTAIN from persistent low confidence
                                on an attempt that DID parse and DID
                                pass validation (or no validator was
                                supplied)

        Checked in the same order the pipeline itself evaluates an
        attempt (ambiguity -> parse -> validation -> confidence), so
        for any mixed attempt history this reflects the LAST attempt's
        actual determining factor, same rule all_parse_failed already
        established — not a full history, just the final word. Only
        meaningful for results actually returned by check(), acheck(),
        or check_with_evidence(); a hand-built BoothResult with an
        unusual field combination falls through these branches in an
        undefined way, same caveat as ok/all_parse_failed."""
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
    """Shown only when the previous attempt parsed fine and was not
    ambiguous, but a caller-supplied validator rejected it. Distinct
    from _build_retry_prompt (which is about low self-reported
    confidence) — this shows the SPECIFIC validation_error, a stronger
    and more concrete correction signal than confidence ever is,
    similar in spirit to how _build_evidence_reconsideration_prompt in
    examples/ai.py shows real evidence rather than vague uncertainty."""
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
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if not 0.0 <= confidence <= 1.0:
            continue

        ambiguous = bool(obj.get("ambiguous", False))
        interpretations = obj.get("interpretations") or []
        if not isinstance(interpretations, list):
            interpretations = []
        interpretations = [str(i) for i in interpretations]
        chosen = obj.get("chosen_interpretation")
        chosen = str(chosen) if chosen else None

        return Attempt(
            raw_text=raw_text,
            answer=str(answer),
            confidence=confidence,
            parse_ok=True,
            ambiguous=ambiguous,
            interpretations=interpretations,
            chosen_interpretation=chosen,
        )

    return Attempt(raw_text=raw_text, answer=None, confidence=None, parse_ok=False)


def _run_validator(
    validator: Optional[ValidatorFn], answer: Optional[str]
) -> Tuple[bool, Optional[str]]:
    """Normalizes every possible validator outcome (bool, (bool, str),
    an invalid return type, or an exception) into a single
    (passed, error_message) pair. Never lets a broken validator crash
    check()/acheck() — same discipline check_with_evidence() already
    applies to compare_fn. validator=None or answer=None short-circuits
    to (True, None): nothing to validate, so nothing can fail — this is
    what makes validator=None a true no-op rather than a special case
    threaded through the rest of the pipeline.

    validator must be SYNCHRONOUS, same constraint as compare_fn in
    check_with_evidence(). If your validation logic needs to await
    something (an API call, a DB lookup), resolve it yourself and pass
    the already-resolved bool/(bool, str) result in via a plain sync
    closure — calling an async validator here returns an unawaited
    coroutine object, which is neither a bool nor a (bool, str) tuple
    and is therefore correctly, if unhelpfully, treated as an invalid
    return type rather than crashing."""
    if validator is None or answer is None:
        return True, None
    try:
        result = validator(answer)
    except Exception as e:
        return False, f"Validator raised {type(e).__name__}: {e}"

    if isinstance(result, bool):
        return result, (None if result else "Validator returned False")
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], bool)
        and isinstance(result[1], str)
    ):
        return result[0], result[1]
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
    """Shared decision step, called identically from check() and
    acheck() after every attempt (and after validation, if a validator
    was supplied). Returns a BoothResult if the loop should stop here,
    or None if the caller should proceed to the next attempt (or, if
    out of attempts, to _finalize_uncertain).

    Check order, matching the pipeline's own diagram: ambiguity first
    (short-circuits regardless of validation or confidence — a question
    that's ambiguous as asked isn't something a validator or a
    confidence retry can fix), THEN validation (an attempt that parsed
    fine but fails a caller's own rule doesn't even get a chance at the
    confidence gate — no point checking self-reported confidence on an
    answer the caller has already said is unacceptable), THEN
    confidence, unchanged from before."""
    if attempt.parse_ok and attempt.ambiguous:
        return BoothResult(
            answer=attempt.answer,
            status=AMBIGUOUS,
            confidence=attempt.confidence,
            attempts=attempts,
            ambiguous=True,
            interpretations=attempt.interpretations,
        )

    if attempt.parse_ok and not attempt.passed_validation:
        # Reject without a special status — falls through to a
        # validation-failure retry via _next_prompt(), or to
        # _finalize_uncertain() (UNCERTAIN, method="validation") if
        # retries are exhausted. No new status, per design: validation
        # failure is a reason a normal accept/retry decision came out
        # the way it did, not a new outcome of its own.
        return None

    if attempt.parse_ok and attempt.confidence >= threshold:
        status = VERIFIED if attempt_index == 0 else REPAIRED
        return BoothResult(
            answer=attempt.answer,
            status=status,
            confidence=attempt.confidence,
            attempts=attempts,
        )

    return None


def _next_prompt(original_prompt: str, attempt: Attempt) -> str:
    """Three-way branch, in the same order _evaluate() checks:
    unparseable -> validation-failed -> low-confidence. Each gets its
    own distinct retry prompt, because each represents a genuinely
    different reason the previous attempt didn't clear the bar, and
    conflating them (as _next_prompt() used to conflate parse failure
    with confidence failure, before 0.3.1) gives the model no reason to
    correct the SPECIFIC thing that was actually wrong."""
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

    if not answer or not evidence:
        return BoothResult(answer=answer or None, status=UNCERTAIN, confidence=None)

    try:
        raw_result = compare_fn(answer, evidence)
    except Exception:
        return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)

    if isinstance(raw_result, bool):
        score = 1.0 if raw_result else 0.0
        passed = raw_result
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
    """
    Run `prompt` through `call_fn`, requesting a self-reported
    confidence score and an ambiguity check, and retry-with-
    reconsideration on low confidence, an unparseable response, or (if
    `validator` is supplied) a failed custom validation check.

    call_fn: see previous versions' docs — unchanged.

    threshold / max_retries / on_attempt: unchanged from prior
    versions.

    validator (0.4.2+, keyword-only): optional Callable[[str], bool |
        tuple[bool, str]]. Runs on an attempt's answer only after that
        attempt has parsed successfully AND was not flagged ambiguous
        — never on a parse failure (nothing to validate) and never on
        an ambiguous answer (a question that's ambiguous as asked
        isn't something a validator should be judging). Deliberately
        SYNCHRONOUS, same constraint as check_with_evidence()'s
        compare_fn — resolve any async work yourself before passing a
        plain sync validator in.

        Return bool: True passes, False fails with a generic message.
        Return (bool, str): pass/fail plus your own explanation, shown
            to the model verbatim on the retry prompt if it fails.
        Any other return type, or an exception raised inside
            validator, is treated as a failed validation — never
            propagates out of check(), same discipline compare_fn gets
            in check_with_evidence().

        validator=None (the default) makes this entirely a no-op:
        Attempt.passed_validation defaults to True and is never set to
        anything else, so every code path introduced by this parameter
        is provably unreachable for existing callers. Zero behavior
        change if you don't pass it.

    Returns a BoothResult. All fields behave as documented previously.
    Two additions relevant to validator:

        result.attempts[i].passed_validation / .validation_error —
            per-attempt validation outcome, always True/None if
            validator was never supplied.
        result.method may now be "validation" — set when the FINAL
            attempt parsed fine, was not ambiguous, but failed
            validation and retries were exhausted (status UNCERTAIN).
            Distinct from "parse_failure" (nothing usable was ever
            produced) and from "confidence" (the model was confident
            but never met a custom rule) — different fixes apply to
            each.
    """
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
    """
    Async twin of check(). Identical contract, including validator
    (0.4.2+, keyword-only, same sync-only constraint — see check()'s
    docstring for the full validator contract). Both functions call
    the same internal _evaluate()/_next_prompt()/_run_validator() so
    they can't drift apart.
    """
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