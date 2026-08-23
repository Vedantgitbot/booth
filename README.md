# BOOTH

**A lightweight checkpoint layer for LLM outputs.**

BOOTH sits between your application and an LLM call and decides whether an answer should pass through, be reconsidered, be flagged as resting on more than one valid interpretation, or be marked uncertain.

The name comes from the idea of a **ticket booth, toll booth, or parking/payment booth**: a booth doesn't need to know everything about what is happening beyond it. It checks whether the required condition has been met before allowing something to pass.

BOOTH follows the same idea for LLM outputs.

> **BOOTH does not claim to know the truth. It checks whether an output meets a defined acceptance condition.**

---

## Current Status

**v0.3.1 — Path B only**

The current implementation handles a bare LLM call:

```text
Prompt
  ↓
LLM
  ↓
ambiguous? + interpretations + answer + self-reported confidence
  ↓
BOOTH
  ↓
ambiguous == true?
  ├── YES → AMBIGUOUS (returned immediately, no retry)
  └── NO  → confidence ≥ threshold?
                ├── YES → VERIFIED
                └── NO  → reconsider
                              ↓
                           LLM again
                              ↓
                        confidence ≥ threshold?
                           ├── YES → REPAIRED
                           └── NO  → UNCERTAIN
```

There is currently **no RAG, tool invocation, or independent evidence checking** in Path B. Every signal BOOTH acts on — ambiguity, confidence — is the model's own self-report about its own answer. BOOTH structures and enforces that self-report; it does not independently verify anything against outside information. See [The Important Limitation](#the-important-limitation) below before using this in anything higher-stakes than a prototype.

Available in both a synchronous form (`booth.check`) and an async form (`booth.acheck`) — see [Sync vs. Async](#sync-vs-async). Both are driven by the exact same internal decision logic, so they behave identically given equivalent model responses.

---

## What BOOTH Does

BOOTH asks the model to return, in this exact key order:

```json
{
  "ambiguous": false,
  "interpretations": [],
  "chosen_interpretation": null,
  "answer": "Paris",
  "confidence": 0.95
}
```

**The field order is deliberate, not cosmetic.** JSON is generated token by token, left to right. By requiring `ambiguous` and `interpretations` before `answer`, the model has to commit to an ambiguity judgment *before* it generates the answer text — this is a real constraint on generation order, not a self-audit tacked on after the fact.

If `ambiguous` is `true`, BOOTH returns immediately with status `AMBIGUOUS`, regardless of confidence. A question that's ambiguous as asked isn't fixed by asking the model to reconsider — reconsideration only helps when the question was answerable and the *answer* was shaky, so ambiguous responses skip the retry loop entirely.

If `ambiguous` is `false` and the confidence is below the configured threshold, BOOTH shows the model its previous answer and confidence and asks it to **reconsider**:

```text
On a previous attempt you answered: "Lyon" with confidence 0.3.
Reconsider carefully. If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

If the reconsidered answer reaches the confidence threshold, BOOTH returns `REPAIRED`. If the model remains below the threshold after all allowed attempts, BOOTH returns `UNCERTAIN`.

**If a response doesn't parse at all** (no valid JSON, missing required keys, out-of-range confidence), BOOTH uses a *different* retry prompt than the reconsideration one above — it tells the model its previous output didn't parse and restates the format requirement, rather than silently repeating the original prompt. This matters because a model with a stable formatting habit (markdown fences, a chatty preamble) would otherwise fail the same way on every retry with no reason to correct course. `result.all_parse_failed` tells you, after the fact, whether `UNCERTAIN` happened because of this (nothing ever parsed) versus persistent low confidence (things parsed fine, the model just wasn't sure) — these call for different fixes on your end.

---

## Why?

A normal LLM call looks like:

```python
answer = call_llm(prompt)
```

The application has to decide what to do with that answer, and has no way to know whether the question itself had more than one valid reading, or whether the model was actually confident.

With BOOTH:

```python
result = booth.check(call_llm, prompt)

if result.status == booth.AMBIGUOUS:
    print("Multiple valid readings:", result.interpretations)
elif result.ok:
    answer = result.answer
else:
    answer = "I'm not confident enough to answer that."
```

The application gets a structured result instead of implementing the retry, parsing, confidence handling, ambiguity handling, and attempt tracking itself.

**To be precise about what this buys you:** everything BOOTH surfaces here — the ambiguity flag, the confidence number — is something the underlying model was already capable of reporting if you'd asked it to, in the same request, with the same field ordering. BOOTH's value isn't a new capability the model didn't have; it's a tested, consistent, reusable implementation of asking for it correctly, parsing it reliably even when the model doesn't follow the format perfectly, and giving you a stable result object instead of everyone re-implementing this by hand per project.

**Real example**, from testing against a live model:

> **Question:** "What's the best-selling book?"
>
> **Without BOOTH:** *"The best-selling book of all time is the Bible, with estimates of over 5 billion copies sold worldwide."* — stated as plain fact, no hint that the question is contested.
>
> **With BOOTH:** `status: AMBIGUOUS, confidence: 0.88`, answer: "The Bible", with four listed interpretations — worldwide including religious texts, best-selling *novel*, best-selling *non-religious* book, and best-selling book *this year*. Same underlying model, same underlying "best guess" answer — but only one of the two tells the user the question was contested at all.

**A case where BOOTH doesn't help, worth stating just as plainly:** if a model is simply *wrong* about a settled fact — misremembers a date, states an outdated fact as current, fabricates a detail — and reports high confidence and no ambiguity, BOOTH returns `VERIFIED`. It has no mechanism in Path B to catch this, because there's no independent source it checks against. Worse, if the model hedges between two equally-wrong answers, BOOTH can label that `AMBIGUOUS`, which reads as "the question is genuinely contested" even when the actual problem is that the model doesn't know the answer. This is a known, observed failure mode, not a hypothetical — see [Current Non-Goals](#current-non-goals).

---

## Installation

```bash
pip install boothpy
```

Or install directly from GitHub:

```bash
pip install git+https://github.com/Vedantgitbot/booth.git
```

## Basic Usage

BOOTH is provider-agnostic. You provide a function that takes a prompt and returns the model's raw text response.

```python
import booth


def call_llm(prompt: str) -> str:
    # Connect this to your LLM provider.
    # Return the model's raw text response.
    ...


result = booth.check(
    call_llm,
    "What is the capital of France?"
)

if result.ok:
    print(result.answer)
else:
    print(f"BOOTH marked this {result.status.lower()}.")
```

BOOTH does not require a specific LLM provider. Your `call_fn` can be backed by OpenAI, Anthropic, Groq, Gemini, a local model, or another system. See `examples/ai.py` for a full working example against the Groq API.

---

## Sync vs. Async

| | `booth.check()` | `booth.acheck()` |
|---|---|---|
| `call_fn` signature | `Callable[[str], str]` (sync) | `Callable[[str], Awaitable[str]]` (`async def`) |
| Use when | Scripts, sync codebases, or already running inside a thread/executor | Async web apps calling an async model client directly |

Passing a sync function to `acheck()` (or an async one to `check()`'s `on_attempt`) raises `TypeError` immediately rather than misbehaving silently.

```python
import asyncio
import booth

async def call_llm(prompt: str) -> str:
    response = await async_client.chat.completions.create(...)
    return response.choices[0].message.content

async def main():
    result = await booth.acheck(call_llm, "What is the capital of France?")
    if result.ok:
        print(result.answer)

asyncio.run(main())
```

**Calling `check()` from async code:** `check()` is fully synchronous — calling it directly inside an `async def` route blocks the event loop for the duration of every `call_fn` call. Run it in a thread pool instead:

```python
from concurrent.futures import ThreadPoolExecutor
import asyncio, functools
import booth

executor = ThreadPoolExecutor(max_workers=20)

async def handler():
    loop = asyncio.get_event_loop()
    fn = functools.partial(booth.check, call_llm, prompt, threshold=0.8)
    result = await loop.run_in_executor(executor, fn)
```

**Concurrency note:** both `check()` and `acheck()` are stateless — no module-level mutable state, no shared caching — so concurrent calls don't interfere with each other. What determines whether your app holds up under concurrent load is `call_fn` itself (is your model client safe to call concurrently? are you within provider rate limits?), not BOOTH's internals.

---

## Result Statuses

BOOTH currently exposes five statuses:

### `VERIFIED`
Not flagged ambiguous, and the **first attempt** met the confidence threshold. Means "passed BOOTH's acceptance condition," not "proven correct."

### `REPAIRED`
Not flagged ambiguous. First attempt was below threshold, but a later reconsideration reached it. Means "recovered through reconsideration," not "independently verified."

### `AMBIGUOUS`
The model flagged more than one valid, meaningfully different reading — different entities sharing a name, different metrics, different time periods. Returned **immediately, regardless of confidence**, never retried.

```text
Question: "What is the capital of Georgia?"
interpretations = ["Georgia (US state) -> Atlanta", "Georgia (country) -> Tbilisi"]
→ AMBIGUOUS
```

`result.answer` still contains the model's best-guess answer under its silently-chosen interpretation — check `result.interpretations` before showing it as settled fact.

**Known limitations, both observed in testing, not hypothetical:**
- Catches *structural* ambiguity (a name or term with genuinely different valid referents) reliably. Weaker on *convention-based* ambiguity, where the split only exists because of a domain norm the model has to already know about (e.g. bestseller-list conventions excluding religious texts).
- Can also fire on a *fabricated* premise: if a model isn't sure what actually happened (a real event, a specific fact) it can generate two similar-sounding "interpretations" around its own uncertainty rather than a genuine reading split in the question. This looks identical to real ambiguity in the output and is not currently distinguishable from it. Treat `AMBIGUOUS` on questions about specific real-world facts (current events, exact figures) with extra skepticism until Path A exists to check the premise against something.

### `UNCERTAIN`
BOOTH could not obtain an answer that satisfied the acceptance condition — every attempt stayed below threshold, every response was unparseable, or every call failed. Check `result.all_parse_failed` to tell those cases apart: `True` means nothing ever parsed (a format/integration problem, not a confidence problem); `False` means the model produced usable answers but never reached the threshold.

### `BLOCKED`
Reserved for the broader BOOTH design and **not reachable from Path B**. Exposed so applications can pattern-match against the complete status vocabulary ahead of Path A.

---

## The Important Limitation

BOOTH's current Path B is **not a correctness guarantee**. It is a self-consistency and reconsideration mechanism, plus a self-assessed ambiguity check. The model is evaluating its own answer and its own question — there is no independent check in the loop.

```json
{"ambiguous": false, "answer": "The Earth is flat.", "confidence": 0.99}
```

BOOTH returns `VERIFIED` for this. It has no independent evidence in Path B to catch it.

> **VERIFIED means "passed BOOTH's current acceptance condition," not "proven correct."**
> **AMBIGUOUS means "the model recognized more than one valid reading," not "the question is actually contested."**

This applies equally to `check()` and `acheck()` — the async entry point changes only how `call_fn` is invoked, not what's being checked.

## Disclaimer

BOOTH is provided for informational and software-development purposes and is provided "as is", without warranties of any kind. BOOTH does not guarantee factual correctness, safety, completeness, reliability, or suitability for any particular purpose.

`VERIFIED` does not mean an answer has been independently proven correct. Acceptance in Path B is based entirely on the model's self-reported ambiguity and confidence. Users are responsible for independently testing and validating BOOTH and any outputs produced through it before relying on them, especially in production, safety-critical, financial, medical, legal, or other high-consequence applications.

The authors and contributors are not responsible for claims, decisions, damages, data loss, or other consequences resulting from the use or misuse of BOOTH, to the extent permitted by applicable law.

See the MIT License for the applicable warranty and liability terms.

---

## Path A — Planned, Not a Different Product

Path A is the same checkpoint with **one additional gate**, not a rewrite or a new product. Path B stays exactly as it is — Path A adds a second, independent check alongside it:

```text
Gate 1 (Path B, exists today): is the question ambiguous?
Gate 2 (Path B, exists today): is the model confident?
Gate 3 (Path A, planned):      does the answer agree with evidence
                                the caller already retrieved?
```

**What Path A will and won't do, stated plainly to avoid overscoping it before it's built:**

- BOOTH will **not** perform retrieval itself, call a vector DB, or re-run a search. The caller's own RAG/tool pipeline retrieves evidence exactly as it does today; BOOTH is handed the answer *and* the evidence the pipeline already produced, and checks whether they agree — once, not in a loop. This mirrors how `call_fn` works today: BOOTH doesn't own the LLM call, the caller does; it won't own retrieval either.
- No retry-the-retrieval-until-it-agrees behavior. If the evidence check is inconclusive, that's `UNCERTAIN` or `BLOCKED`, not a prompt to search again — an unbounded "keep trying tools" loop is explicitly out of scope; it would turn a checkpoint into an orchestrator.
- Comparing an answer against retrieved evidence is a genuinely hard, unsolved design problem, not a detail — string match is too brittle, embedding similarity too loose, LLM-judged agreement re-introduces a self-report-style problem one layer removed. The comparison method is **not decided yet** and will likely be pluggable (`compare_fn`) rather than a single built-in choice BOOTH forces on every caller.
- Even a working Gate 3 only proves the answer agrees with what was retrieved — **not that the retrieved evidence itself is correct, current, or complete.** That ceiling will be stated in Path A's own limitations section as plainly as Path B's is stated here.
- This will require a different call shape than `check()`/`acheck()` today, since it needs the evidence handed to it alongside the answer, not just a prompt string.

Path A is not implemented in the current release.

---

## API

```python
booth.check(
    call_fn,
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,
)
```

```python
await booth.acheck(
    call_fn,        # async def call_fn(prompt: str) -> str
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,  # may be sync or async
)
```

**`call_fn`** — for `check()`: `Callable[[str], str]`. For `acheck()`: `Callable[[str], Awaitable[str]]`. Receives a prompt, returns the model's raw response. Exceptions raised by `call_fn` are caught per-attempt and recorded as a failed `Attempt` — they never propagate out.

**`prompt`** — the original user/application prompt. BOOTH appends its confidence/ambiguity-reporting instructions internally.

**`threshold`** — minimum self-reported confidence (`0.0`–`1.0`) required to accept an unambiguous answer without retrying. Default `0.7`. **Not independently calibrated** — validate against your own test set; see `examples/` for a way to log real (question, status, confidence) data.

**`max_retries`** — retries after the first attempt, for low-confidence *unambiguous* answers or unparseable responses. `max_retries=0` means one total call; `max_retries=2` allows up to three.

**`on_attempt`** — optional callback invoked after every attempt (including failed/unparseable ones). For `check()`: must be synchronous, `Callable[[int, Attempt], Any]` — a coroutine function raises `TypeError`. For `acheck()`: may be sync or async.

---

## Result Object

```python
result.answer            # str | None
result.status            # VERIFIED / REPAIRED / AMBIGUOUS / UNCERTAIN / BLOCKED
result.confidence        # float | None
result.attempts          # list[Attempt] — full history of every call made
result.n_attempts        # int
result.ok                # bool — True only for VERIFIED / REPAIRED
result.ambiguous         # bool
result.interpretations   # list[str] — populated only when ambiguous
result.all_parse_failed  # bool — True if UNCERTAIN happened because every
                          #   attempt failed to parse, as opposed to persistent
                          #   low confidence. Different fixes apply to each:
                          #   parse failures usually mean a format/integration
                          #   problem; low confidence means the model genuinely
                          #   wasn't sure.
```

Identical whether the result came from `check()` or `acheck()`.

```python
if result.status == booth.AMBIGUOUS:
    print("This question has multiple readings:", result.interpretations)
elif result.ok:
    print(result.answer)
elif result.all_parse_failed:
    print("BOOTH never got a parseable response — check your call_fn / format instructions.")
else:
    print("BOOTH could not verify a confident answer.")
```

---

## Why the Checkpoint Metaphor?

A ticket booth doesn't know whether the movie is good. A toll booth doesn't know where you're ultimately going. They check a **specific condition**.

BOOTH applies the same principle: it does not know everything, it checks whether the required condition has been met. In Path B, that condition is:

```text
Is this question answerable as a single, unambiguous claim,
and does the model report confidence at or above the configured threshold?
```

In Path A, an additional condition gets added alongside it, not in place of it: does the answer agree with evidence the caller already retrieved?

---

## Design Principles

1. **Don't silently pass through uncertainty or unstated ambiguity.** If the model can't clear the bar, say so.
2. **Reconsider rather than blindly resample.** A retry should give the model a real opportunity to examine its previous answer — and a parse-failure retry should tell the model what went wrong, not just repeat the ask unchanged.
3. **Ask "is this even answerable as asked" before "how confident are you."** Field order in the schema forces this sequencing, not just the prompt wording.
4. **Don't pretend confidence is proof.** Self-reported confidence and self-reported ambiguity are useful signals, not independent evidence.
5. **Stay provider-agnostic.** BOOTH works above different LLM providers rather than locking applications to one API.
6. **Keep the core API small.** A checkpoint layer, not another full LLM framework. Path A adds a gate, not an orchestrator — BOOTH will not own retrieval, retry evidence lookups, or manage a tool-calling loop.

---

## Current Non-Goals

BOOTH Path B does **not** currently:

- guarantee factual correctness
- independently verify claims against external evidence
- browse the web, perform RAG, or invoke external tools
- compare multiple independent models
- provide calibrated confidence probabilities (self-reported confidence is a signal, not a calibrated statistic)
- reliably catch **convention-based** ambiguity requiring domain knowledge to recognize as a split — meaningfully better than no check, confirmed working on **structural** ambiguity, but not exhaustive
- distinguish genuine multi-reading ambiguity from a model hedging between two flavors of the same wrong/fabricated answer — both currently surface as `AMBIGUOUS` and look identical from the outside
- retry with backoff on rate-limit/network errors — a failed `call_fn` attempt is recorded and the loop moves on; there is no separate network-level retry/backoff policy
- replace application-specific safety or validation logic

Those may be addressed by Path A or future work — but as of this version, none of them are solved.

---

## Development

```text
booth/
├── .gitignore
├── LICENSE
├── README.md
├── TUTORIAL.md
├── pyproject.toml
├── src/
│   └── booth/
│       ├── __init__.py
│       └── core.py
└── tests/
    ├── test_core.py
    └── test_acheck.py
```

```bash
pip install -e ".[dev]"
pytest
```

Tests use mock `call_fn` implementations so core BOOTH behavior can be tested without making real LLM API calls. See `examples/ai.py` and `examples/app.py` for a working end-to-end example against a live model (Groq).

---

## License

This is the official BOOTH repository — Vedant Brahmbhatt

MIT. See [`LICENSE`](LICENSE).