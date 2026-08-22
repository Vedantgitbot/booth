"""
BOOTH — a recheck layer for LLM outputs.

Current scope: Path B only (no RAG/tools — bare LLM calls, verified via
self-reported confidence and reconsideration retries). See core.py for
full design notes and honest limitations.

    import booth as bth

    result = bth.check(call_fn, "What's the capital of the USA?")
    if result.ok:
        return result.answer
    else:
        return "Not confident enough to answer that."
"""

from booth.core import (
    Attempt,
    BoothResult,
    check,
    VERIFIED,
    REPAIRED,
    BLOCKED,
    UNCERTAIN,
    DEFAULT_THRESHOLD,
    DEFAULT_MAX_RETRIES,
)

__version__ = "0.1.0"

__all__ = [
    "Attempt",
    "BoothResult",
    "check",
    "VERIFIED",
    "REPAIRED",
    "BLOCKED",
    "UNCERTAIN",
    "DEFAULT_THRESHOLD",
    "DEFAULT_MAX_RETRIES",
]