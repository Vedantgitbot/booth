
BOOTH — lightweight verification wrapper around LLM calls.

PATH B ONLY, current scope:

    Bare call, no RAG/tools (just system context + temperature).
    Ask the model for its answer plus a self-reported confidence score.
    If confidence < threshold, retry — showing the model its previous
    answer and confidence and asking it to reconsider, not a blind
    resample. If confidence stays low after retries, return UNCERTAIN
    rather than silently passing through a shaky answer.

Path A (re-invoking an existing RAG/tool and comparing evidence) is a
separate module with a different call shape (a re-invocable retriever/
tool handle, not a plain prompt string) and is not implemented here.

STATUS SEMANTICS FOR PATH B:

    VERIFIED  — first attempt met the confidence threshold.
    REPAIRED  — first attempt was below threshold; a later attempt,
                after being shown its own prior answer, met the
                threshold. "Repaired" means "fixed via reconsideration,"
                not "corrected against evidence" — there is no evidence
                in Path B.
    UNCERTAIN — every attempt stayed below threshold, every attempt's
                output was unparseable, or call_fn raised on every
                attempt.
    BLOCKED   — not reachable from Path B. Exposed as a constant only
                for API symmetry with Path A, so calling code can
                pattern-match on all four statuses without a KeyError.

HONEST LIMITATION: this is a self-consistency check, not a correctness
guarantee. A model that is confidently wrong will report high
confidence and BOOTH will return VERIFIED on a wrong answer. Path B has
no independent evidence to catch that class of error — see the BOOTH
scope doc, non-goals.
