
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

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

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def ok(self) -> bool:
        """True if the result is safe to show to a user as-is, no
        caveats needed. AMBIGUOUS is deliberately NOT ok: a confidently
        answered but silently-chosen interpretation still needs the
        caller to decide how to handle the ambiguity."""
        return self.status in (VERIFIED, REPAIRED)


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

    call_fn: a callable that takes a single prompt string and returns
        the model's raw text response. Callers wire this to whatever
        client/model they use (Anthropic, OpenAI, etc.) and are
        responsible for carrying over any system prompt that belongs
        to the original call BOOTH is wrapping. Exceptions raised by
        call_fn are caught per-attempt and treated as a failed attempt
        — they do not propagate out of check().

    threshold: minimum self-reported confidence (0.0-1.0) required to
        accept an unambiguous answer without retrying.

    max_retries: number of retries AFTER the first attempt, for
        low-confidence (non-ambiguous) answers. E.g. max_retries=1
        means up to 2 total calls to call_fn.

    on_attempt: optional callback invoked as on_attempt(index, attempt)
        after every attempt (including failed/unparseable ones), for
        logging or building calibration data.

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
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
    if max_retries < 0:
        raise ValueError(f"max_retries must be >= 0, got {max_retries}")

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

        if attempt.parse_ok and attempt.ambiguous:
            # Ambiguity is a property of the question, not something a
            # reconsideration retry resolves — return immediately,
            # regardless of confidence.
            return BoothResult(
                answer=attempt.answer,
                status=AMBIGUOUS,
                confidence=attempt.confidence,
                attempts=attempts,
                ambiguous=True,
                interpretations=attempt.interpretations,
            )

        if attempt.parse_ok and attempt.confidence >= threshold:
            status = VERIFIED if i == 0 else REPAIRED
            return BoothResult(
                answer=attempt.answer,
                status=status,
                confidence=attempt.confidence,
                attempts=attempts,
            )

        # Prepare the prompt for the next attempt, if any retries remain.
        if attempt.parse_ok:
            current_prompt = _build_retry_prompt(prompt, attempt)
        else:
            current_prompt = _build_prompt(prompt)

    last_ok = attempts[-1] if attempts[-1].parse_ok else next(
        (a for a in reversed(attempts) if a.parse_ok), None
    )
    return BoothResult(
        answer=last_ok.answer if last_ok else None,
        status=UNCERTAIN,
        confidence=last_ok.confidence if last_ok else None,
        attempts=attempts,
    )