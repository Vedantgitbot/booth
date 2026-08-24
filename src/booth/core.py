import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Union

# check_with_evidence()'s comparison function: takes an answer and the
# evidence it's being checked against, returns either a bool (pass/fail,
# bypasses evidence_threshold entirely) or a float score in [0.0, 1.0]
# (compared against evidence_threshold). Deliberately not built into
# BOOTH itself — see check_with_evidence()'s docstring for why.
CompareFn = Callable[[str, Sequence[str]], Union[bool, float]]

VERIFIED = "VERIFIED"
REPAIRED = "REPAIRED"
AMBIGUOUS = "AMBIGUOUS"
BLOCKED = "BLOCKED"
UNCERTAIN = "UNCERTAIN"

DEFAULT_THRESHOLD = 0.7
DEFAULT_MAX_RETRIES = 1

# Field order matters: ambiguous / interpretations / chosen_interpretation
# come BEFORE answer / confidence. Since JSON is generated token-by-token
# left to right, asking for these fields first forces the model to commit
# to an ambiguity judgment before it generates the answer text — not as
# a self-audit tacked on after the fact.
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

# Matches flat (non-nested) {...} blocks. Good enough for our schema,
# which has no braces nested inside string values; does not attempt to
# handle those if a model ever produces them.
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


@dataclass
class BoothResult:
    answer: Optional[str]
    status: str
    confidence: Optional[float] = None
    attempts: List[Attempt] = field(default_factory=list)
    ambiguous: bool = False
    interpretations: List[str] = field(default_factory=list)
    # Populated only by check_with_evidence() (Path A's evidence gate).
    # None for any result coming from check()/acheck() (Path B). Holds
    # the same numeric value as `confidence` for evidence results — the
    # duplication is deliberate: `confidence` keeps a uniform meaning
    # ("how strongly does BOOTH stand behind this answer") across both
    # paths so callers can branch on result.ok/.status generically,
    # while `evidence_agreement` makes it explicit, when present, that
    # this particular number came from an evidence comparison rather
    # than the model's own self-report.
    evidence_agreement: Optional[float] = None

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def ok(self) -> bool:
        """True if the result is safe to show to a user as-is, no
        caveats needed. AMBIGUOUS is deliberately NOT ok: a confidently
        answered but silently-chosen interpretation still needs the
        caller to decide how to handle the ambiguity. For
        check_with_evidence() results, BLOCKED (evidence disagreed) and
        UNCERTAIN (empty input / compare_fn error) are both correctly
        NOT ok via this same status check — no separate logic needed."""
        return self.status in (VERIFIED, REPAIRED)

    @property
    def all_parse_failed(self) -> bool:
        """True if every attempt failed to parse into the expected
        schema — i.e. UNCERTAIN was reached because the model never
        produced usable output, not because it reported low
        confidence. This distinction matters operationally: a caller
        seeing UNCERTAIN because of low confidence might reasonably
        retry at a lower threshold or accept the answer with a
        caveat, but that response makes no sense here — there is no
        answer to fall back on. A caller in this state more likely
        needs to relax its format instructions, check that call_fn is
        wired up correctly, or try a different model. Undefined
        (False) if there were no attempts at all."""
        return bool(self.attempts) and all(not a.parse_ok for a in self.attempts)


def _build_prompt(user_prompt: str) -> str:
    return user_prompt.rstrip() + _CONFIDENCE_SUFFIX


def _build_retry_prompt(original_prompt: str, previous: Attempt) -> str:
    """Show the model its own prior answer and confidence, and ask it
    to reconsider — a genuine second look, not a blind resample. Only
    used for confidence retries; AMBIGUOUS short-circuits before this
    is ever called, since reconsideration doesn't resolve a question
    that's ambiguous as asked."""
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"On a previous attempt you answered: \"{previous.answer}\" "
        f"with confidence {previous.confidence}.\n"
        f"Reconsider carefully. If that answer is correct, restate it. "
        f"If it is wrong, give the corrected answer."
        f"{_CONFIDENCE_SUFFIX}"
    )


def _build_parse_failure_prompt(original_prompt: str, previous: Attempt) -> str:
    """Used when the previous attempt's raw text could not be parsed
    into the expected schema (missing/invalid keys, no JSON found at
    all, etc). Deliberately distinct from _build_retry_prompt: there
    is no previous answer/confidence worth showing the model back, so
    instead of silently repeating the original prompt — which gives a
    model with a stable formatting habit (markdown fences, a chatty
    preamble, ignoring "output ONLY JSON") no reason to change it —
    this explicitly names the failure and restates the format
    contract. Without this, a model with a consistent formatting quirk
    can burn every retry attempt failing the same way for the same
    reason, and the caller only ever sees a generic UNCERTAIN with no
    hint that parsing, not confidence, was the actual problem."""
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"Your previous response could not be parsed: it did not "
        f"contain a valid JSON object with the required keys. Output "
        f"your response as a single JSON object with exactly the "
        f"required keys, and nothing else — no markdown code fences, "
        f"no commentary before or after it."
        f"{_CONFIDENCE_SUFFIX}"
    )


def _try_json(candidate: str) -> Optional[dict]:
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _parse_response(raw_text: str) -> Attempt:
    """Try, in order: the whole trimmed text as JSON; the last
    non-empty line as JSON; any flat {...} substring found anywhere in
    the text. Real models don't always follow "output ONLY JSON"
    perfectly, so this tolerates commentary before/after the JSON."""
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
            # Out-of-range confidence (e.g. 17, -3, 4.7) violates the
            # contract we asked for. Treat it as unparseable rather than
            # clamping — clamping would turn a broken response into a
            # falsely maximal-confidence one, which is worse than
            # surfacing the failure honestly.
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


def _evaluate(
    attempts: List[Attempt],
    attempt: Attempt,
    attempt_index: int,
    threshold: float,
) -> Optional[BoothResult]:
    """Shared decision step, called identically from check() and
    acheck() after every attempt. Returns a BoothResult if the loop
    should stop here (ambiguous, or confidence cleared the threshold),
    or None if the caller should proceed to the next attempt (or, if
    out of attempts, to _finalize_uncertain).

    This is the ONLY place the ambiguous-check / threshold-check /
    VERIFIED-vs-REPAIRED decision lives. check() and acheck() both
    defer to it instead of re-implementing the logic, so a future fix
    here can't be applied to one loop and forgotten in the other.
    """
    if attempt.parse_ok and attempt.ambiguous:
        # Ambiguity is a property of the question, not something a
        # reconsideration retry resolves — return immediately,
        # regardless of confidence. This applies on any attempt, not
        # just the first: if a reconsideration retry causes the model
        # to newly recognize ambiguity it missed the first time, that
        # is still ambiguity, and still short-circuits.
        return BoothResult(
            answer=attempt.answer,
            status=AMBIGUOUS,
            confidence=attempt.confidence,
            attempts=attempts,
            ambiguous=True,
            interpretations=attempt.interpretations,
        )

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
    """Prompt to use for the next attempt, if any retries remain.
    Two distinct retry paths, not one: a parsed-but-low-confidence
    attempt gets the reconsideration prompt (show it its own prior
    answer, ask it to double-check); an unparseable attempt gets the
    format-failure prompt instead (there is no prior answer worth
    showing back, and repeating the original prompt unchanged gives a
    model with a stable formatting quirk no reason to correct it)."""
    if attempt.parse_ok:
        return _build_retry_prompt(original_prompt, attempt)
    return _build_parse_failure_prompt(original_prompt, attempt)


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
    """
    Path A's evidence gate. Checks whether `answer` agrees with
    `evidence` the caller already retrieved (from their own RAG/tool
    pipeline), using a caller-supplied `compare_fn`. A pure function —
    makes no LLM calls, no network calls, and does not retry.

    This is a standalone checkpoint, not an aggregator: it does not
    read or mutate a prior BoothResult from check()/acheck(), and does
    not attempt to reconcile Path B's ambiguity/confidence check with
    this evidence check. That reconciliation is the caller's job. If a
    prior check()/acheck() result was not .ok (UNCERTAIN or AMBIGUOUS),
    there is generally no reason to run this at all — an answer that
    wasn't confident or was ambiguous in the first place isn't made
    more trustworthy by also agreeing with evidence, and callers should
    typically skip straight to handling that Path B outcome instead:

        b_result = check(call_llm, prompt)
        if b_result.ok:
            a_result = check_with_evidence(b_result.answer, docs, compare_fn)
            final_ok = a_result.ok        # both gates passed
        else:
            final_ok = False              # Path B already failed; don't bother

    compare_fn: Callable[[str, Sequence[str]], bool | float]. Receives
        the answer and the evidence sequence, returns either:
          - bool: True/False, pass/fail. `evidence_threshold` is
            IGNORED entirely for bool returns — False always produces
            BLOCKED regardless of what evidence_threshold is set to,
            it is not compared against 0.0 as if it were a score.
          - float: a score, expected in [0.0, 1.0], compared against
            evidence_threshold (score >= evidence_threshold passes).
            A score outside [0.0, 1.0] violates the contract and is
            treated as a comparison failure (UNCERTAIN), the same way
            check()/acheck() refuse to clamp an out-of-range
            self-reported confidence rather than silently accepting it.
        BOOTH does not supply a default compare_fn — how to compare an
        answer against evidence (string match, embedding similarity,
        LLM-judged entailment, something else) is a real design
        decision with real tradeoffs that belongs to the caller, not a
        default this library should quietly pick for you.
        Exceptions raised by compare_fn are caught and treated as
        UNCERTAIN, not propagated.

    evidence_threshold: minimum compare_fn float score required to
        pass. Deliberately a SEPARATE parameter from check()'s
        `threshold` — they measure different things (an evidence
        agreement score here vs. self-reported model confidence there)
        and must not be conflated by sharing one parameter name.
        Default 0.7, same default as `threshold`, but not otherwise
        related to it. Must be between 0.0 and 1.0.

    Returns a BoothResult:
        status = VERIFIED  — compare_fn passed (True, or float >= evidence_threshold)
        status = BLOCKED   — compare_fn failed (False, or float < evidence_threshold)
        status = UNCERTAIN — answer or evidence was empty, compare_fn
                              raised, or compare_fn returned a float
                              outside [0.0, 1.0]
        result.confidence and result.evidence_agreement both hold the
            same numeric score (1.0/0.0 for bool, the raw float
            otherwise); None for UNCERTAIN.
        result.ambiguous, result.interpretations, result.attempts are
            always the Path-B defaults (False / [] / []) — they don't
            apply to this path. result.ok and result.all_parse_failed
            need no special-casing: they're computed from `status` and
            `attempts` respectively via the same properties check()/
            acheck() results use, and already do the right thing here
            (ok is True only for VERIFIED; all_parse_failed is False
            since attempts is always empty).
    """
    _validate_evidence_args(evidence_threshold)

    if not answer or not evidence:
        return BoothResult(answer=answer or None, status=UNCERTAIN, confidence=None)

    try:
        raw_result = compare_fn(answer, evidence)
    except Exception:
        return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)

    if isinstance(raw_result, bool):
        # Bool short-circuits entirely: this is a pass/fail contract,
        # not a 1.0/0.0 score to be compared against
        # evidence_threshold. If it were compared like a float, a
        # caller-set evidence_threshold=0.0 would make False >= 0.0
        # true and incorrectly pass — bools must never be run through
        # the threshold comparison at all, only floats are.
        score = 1.0 if raw_result else 0.0
        passed = raw_result
    else:
        try:
            score = float(raw_result)
        except (TypeError, ValueError):
            return BoothResult(answer=answer, status=UNCERTAIN, confidence=None)
        if not 0.0 <= score <= 1.0:
            # Out-of-range score violates the contract we documented
            # for compare_fn. Treat as a failed comparison rather than
            # silently comparing an invalid number against the
            # threshold — same principle as check()'s refusal to clamp
            # out-of-range self-reported confidence.
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
) -> BoothResult:
    """
    Run `prompt` through `call_fn`, requesting a self-reported
    confidence score and an ambiguity check, and retry-with-
    reconsideration on low confidence (but not on ambiguity, which
    reconsideration can't fix).

    call_fn: a synchronous callable that takes a single prompt string
        and returns the model's raw text response. Callers wire this
        to whatever client/model they use (Anthropic, OpenAI, etc.)
        and are responsible for carrying over any system prompt that
        belongs to the original call BOOTH is wrapping. Exceptions
        raised by call_fn are caught per-attempt and treated as a
        failed attempt — they do not propagate out of check().
        For an async call_fn, use acheck() instead.

    threshold: minimum self-reported confidence (0.0-1.0) required to
        accept an unambiguous answer without retrying.

    max_retries: number of retries AFTER the first attempt, for
        low-confidence (non-ambiguous) or unparseable answers. E.g.
        max_retries=1 means up to 2 total calls to call_fn.

    on_attempt: optional synchronous callback invoked as
        on_attempt(index, attempt) after every attempt (including
        failed/unparseable ones), for logging or building calibration
        data. Must not be a coroutine function — check() cannot await
        it; use acheck() with an async on_attempt instead.

    Calling check() inside an async application (FastAPI, Starlette,
    etc.) will block the event loop for the duration of each call_fn
    call, since check() itself is fully synchronous. Run it in a
    thread pool if you're inside async code:

        result = await loop.run_in_executor(executor, booth.check, call_llm, prompt)

    or, for kwargs beyond the first two positional args:

        import functools
        fn = functools.partial(booth.check, call_llm, prompt, threshold=0.8)
        result = await loop.run_in_executor(executor, fn)

    Returns a BoothResult:
        result.answer          — what you show the user IF result.ok
                                  is True. If status is AMBIGUOUS,
                                  result.answer is the model's answer
                                  under its silently-chosen
                                  interpretation — check
                                  result.interpretations before
                                  showing it as-is.
        result.status           — VERIFIED / REPAIRED / AMBIGUOUS /
                                   UNCERTAIN (BLOCKED is defined but
                                   unreachable from Path B).
        result.ok                — True only for VERIFIED/REPAIRED.
        result.ambiguous         — True if AMBIGUOUS.
        result.interpretations   — list of readings, if ambiguous.
        result.all_parse_failed  — True if UNCERTAIN was reached
                                    because every attempt failed to
                                    parse, as opposed to low confidence.
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
) -> BoothResult:
    """
    Async twin of check(). Identical contract, identical Attempt /
    BoothResult shape, identical retry/ambiguity decision logic (both
    functions call the same internal _evaluate() step) — the only
    difference is that call_fn (and on_attempt, if it's a coroutine
    function) are awaited instead of called directly.

    call_fn: an async callable — `async def call_fn(prompt: str) -> str`.
        Passing a synchronous call_fn raises TypeError immediately;
        use check() for those instead.

    on_attempt: optional callback invoked as on_attempt(index, attempt)
        after every attempt. May be sync or async — acheck() awaits it
        only if it's a coroutine function, so a plain sync logging
        callback works unchanged.

    Exceptions raised by call_fn (including provider rate-limit and
    timeout errors, which matter most under concurrent load) are
    caught per-attempt and recorded as a failed Attempt, exactly as in
    check() — they never propagate out of acheck().

    See check() for the full parameter/return contract (threshold,
    max_retries, and the BoothResult fields all behave identically).
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
            # Same as check(): a dead call becomes a failed Attempt,
            # never an exception that escapes acheck(). This matters
            # more here, not less — this is exactly the path that
            # fires under concurrent-load rate limiting.
            attempt = Attempt(
                raw_text=f"{type(e).__name__}: {e}",
                answer=None,
                confidence=None,
                parse_ok=False,
                error=str(e),
            )
        else:
            attempt = _parse_response(raw)

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