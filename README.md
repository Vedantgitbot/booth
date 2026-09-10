# BOOTH

A lightweight checkpoint library for LLM outputs.

**Should my application trust this LLM output?**

Every app built on an LLM call eventually has to answer that question, usually the hard way, after a confidently wrong answer has already reached a user. BOOTH is the checkpoint that answers it first: it sits between your application and an LLM call and gives you a structured decision, pass the output through, ask the model to reconsider, flag it as ambiguous, or check it against your own custom rule or your own retrieved evidence.

The name comes from a **ticket booth, toll booth, or parking/payment booth**: it doesn't need to know everything about what's happening beyond, it just checks whether the required condition has been met before letting something through.

```bash
pip install boothpy
```

---

## See it in 10 seconds

```python
import booth

result = booth.check(call_llm, "What is the capital of France?")

if result.ok:
    print(result.answer)                       # "Paris" — confident, unambiguous
else:
    print(f"BOOTH returned {result.status}")    # AMBIGUOUS / UNCERTAIN — don't ship it blind
```

```
   Your App                       BOOTH                          Your App
 ┌──────────┐    prompt    ┌──────────────────────┐  BoothResult ┌───────────┐
 │          │ ───────────▶ │         LLM          │              │           │
 │  ask()   │              │          │           │              │  branch   │
 │          │              │          ▼           │              │  on:      │
 │          │              │      Checkpoint      │ ───────────▶ │  .ok      │
 │          │              │   ambiguity detection│              │  .status  │
 │          │              │   confidence + retry │              │  .method  │
 │          │              │   custom validator   │              │  .answer  │
 │          │              │   evidence agreement │              │           │
 └──────────┘              └──────────────────────┘              └───────────┘
```

That's the entire mental model: wrap the LLM call you already have, and get back a `BoothResult` with a real `.status` — instead of a raw string your code has no reason to trust.

---

## Current Status

**v0.4.7**

BOOTH currently provides:

* ambiguity detection, so a model doesn't confidently guess at a multi-interpretation question
* self-reported confidence checking, with genuine reconsideration retries — not blind resampling
* an optional caller-supplied `validator` for custom pass/fail rules, with its own dedicated retry prompt
* separate, correctly-targeted retry handling for responses that failed to parse at all
* synchronous and asynchronous APIs (`check()` / `acheck()`), including callable-object support for both — a class instance with a sync `__call__` for `check()`, or an `async def __call__` for `acheck()`
* `check_with_evidence()` for checking an answer against evidence your own RAG/retrieval pipeline already pulled
* structured results, including `result.method` (which mechanism actually produced this outcome) and `result.parsed` (the model's raw, uncoerced JSON)
* `result.to_dict()` for a fully JSON-serializable snapshot of a result — including computed properties like `ok` and `method`, not just the raw dataclass fields
* full attempt history for every retry
* five explicit statuses: `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`

BOOTH is provider-agnostic and zero-dependency — it works with any LLM client you already have, and doesn't require a particular retrieval system or framework.

---

## What BOOTH Does

A normal LLM call might look like:

```python
answer = call_llm(prompt)
```

BOOTH adds a checkpoint around the model call:

```python
import booth

result = booth.check(
    call_llm,
    "What is the capital of France?"
)

if result.ok:
    print(result.answer)
else:
    print(f"BOOTH returned {result.status}")
```

Under the hood, BOOTH asks the model for structured self-report alongside its answer:

```json
{
  "ambiguous": false,
  "interpretations": [],
  "chosen_interpretation": null,
  "answer": "Paris",
  "confidence": 0.95
}
```

and applies your configured acceptance rules to it, in order:

1. If the question is ambiguous, return `AMBIGUOUS` immediately.
2. If a `validator` was supplied and the answer fails it, ask the model to reconsider — showing it the specific failure.
3. If confidence is below threshold, ask the model to reconsider its previous answer.

A reconsidered answer that meets the bar comes back `REPAIRED`. If nothing acceptable is ever produced, you get `UNCERTAIN` — with `result.method` telling you exactly why (parse failure, failed validation, or persistent low confidence).

Every field BOOTH extracts from the model's JSON is validated against its expected type before you ever see it — a model returning `"false"` (a string) where it should return `false` (a boolean), or `true` where it should return a number, gets rejected and retried rather than silently misread. Full detail on this and the `check_with_evidence()` equivalent is in the [Tutorial](TUTORIAL.md) and [Changelog](CHANGELOG.md).

---

## Features

### Ambiguity detection

BOOTH asks the model to identify whether a question has multiple valid interpretations *before* accepting an answer.

```text
What is the capital of Georgia?
```

could mean:

```text
Georgia (the country) -> Tbilisi
Georgia (the US state) -> Atlanta
```

BOOTH returns `AMBIGUOUS` with the detected readings in `result.interpretations`, and this takes priority over everything else BOOTH checks — a confident, validator-passing answer is still returned as `AMBIGUOUS` if the model spots multiple valid readings.

---

### Confidence checking

BOOTH uses the model's self-reported confidence as an acceptance signal, with a configurable threshold (default `0.7`):

```python
result = booth.check(call_llm, prompt, threshold=0.8)
```

---

### Reconsideration retries

When an answer is unambiguous but under-confident, BOOTH shows the model its own previous answer and asks it to genuinely reconsider — not resample blindly:

```text
Previous answer: "Lyon"
Previous confidence: 0.3

Reconsider carefully. If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

A reconsidered answer that clears the threshold comes back `REPAIRED`. Control the retry budget with `max_retries` (default `1`; `max_retries=0` disables retries entirely).

---

### Parse-failure handling

A response that fails to parse gets a distinct retry prompt — one that tells the model its previous output didn't meet the required format — instead of silently repeating the original prompt and hoping. `result.all_parse_failed` tells you if every single attempt failed to produce a valid response.

---

### Custom validation with `validator`

Plug your own pass/fail rule directly into BOOTH's retry loop:

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

result = booth.check(
    call_llm,
    "What is the order ID for this request?",
    validator=is_valid_order_id,
)
```

`validator` can return `True`/`False`, `(bool, str)` with a specific failure reason shown to the model verbatim on retry, or the `(bool, None)` / list-shaped equivalents. `numpy.bool_` and similar duck-typed booleans are recognized natively — BOOTH stays zero-dependency, and this works across numpy versions. `validator` must always be synchronous — an accidentally-`async def` validator is rejected cleanly with a specific message, not silently mishandled.

Validation runs after the ambiguity check and *before* the confidence check — a highly confident answer still gets rejected and retried if it fails your rule.

---

### `result.method`

Tells you which mechanism actually produced a result:

```python
result.method
# "ambiguity"     — status is AMBIGUOUS
# "evidence"      — result came from check_with_evidence()
# "parse_failure" — UNCERTAIN, every attempt failed to parse
# "validation"    — UNCERTAIN, parsed fine and was confident, but failed your validator
# "confidence"    — the ordinary case
```

This is what makes an `UNCERTAIN` result actionable instead of a shrug:

```python
if result.status == booth.UNCERTAIN:
    if result.method == "parse_failure":
        print("Check call_fn / prompt formatting.")
    elif result.method == "validation":
        print("Model was confident, but never satisfied the validator.")
    else:
        print("Model tried, but confidence never reached threshold.")
```

---

### `result.parsed`

The model's raw JSON response, exactly as returned — before any of BOOTH's coercion (`str(answer)`, `float(confidence)`, and so on). Useful for logging, debugging, or reading extra fields you asked the model to include that BOOTH itself doesn't use:

```python
result = booth.check(call_llm, prompt)

result.confidence             # 0.95   — coerced float
result.parsed["confidence"]   # "0.95" — raw value, untouched
result.parsed["source_document"]  # any extra field you asked for, unread by BOOTH
```

---

### Synchronous and asynchronous APIs

```python
booth.check()          # Callable[[str], str]
await booth.acheck()   # Callable[[str], Awaitable[str]]
```

Both share the exact same decision logic — ambiguity, `validator`, confidence, `parsed` — the only difference is how your LLM function gets called:

```python
import asyncio
import booth

async def call_llm(prompt: str) -> str:
    response = await async_client(...)
    return response

async def main():
    result = await booth.acheck(call_llm, "What is the capital of France?")
    if result.ok:
        print(result.answer)

asyncio.run(main())
```

`call_fn` doesn't have to be a plain function — `check()` accepts any synchronous callable, including a class instance with a `__call__` method, and `acheck()` accepts a plain `async def` function, a `functools.partial` wrapping one, or an object whose `__call__` is itself `async def`. `on_attempt` follows the exact same detection rules as `call_fn` on both entry points (fixed in 0.4.7 — see the [Changelog](CHANGELOG.md#v047)). See the [Tutorial](TUTORIAL.md#10-async-usage) for the one case that's intentionally not supported.

---

### Evidence agreement checking

For applications that already have evidence from their own RAG, search, or tool pipeline, `check_with_evidence()` checks the model's answer against the evidence you already retrieved — instead of just trusting that the model read it correctly:

```python
evidence = [
    "Either party may terminate this Agreement upon ninety (90) "
    "days written notice to the other party."
]

result = booth.check_with_evidence(
    answer="You need to give 45 days' notice to cancel.",
    evidence=evidence,
    compare_fn=compare_answer_to_evidence,
)

result.status               # BLOCKED — the answer contradicts the evidence
result.evidence_agreement   # the score/bool your compare_fn returned
```

Without this check, `"45 days"` is just a string your app has no particular reason to doubt — it reads like a normal, confident answer, not a hallucination. `check_with_evidence()` is what turns "the model said 45 days" into "the model said 45 days, and that disagrees with the 90-day clause our own retrieval actually pulled" — a materially different, and far more actionable, thing to know before it ever reaches a user.

You supply `compare_fn` — BOOTH doesn't choose a retrieval system or comparison algorithm for you. It can return `True`/`False` (strict pass/fail, `numpy.bool_` included) or a float `0.0`–`1.0` compared against `evidence_threshold`:

```python
result = booth.check_with_evidence(
    answer=answer,
    evidence=evidence,
    compare_fn=compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

`check_with_evidence()` makes no LLM calls, no network calls, and performs no retrieval — that pipeline is entirely yours. It's a standalone comparison gate with no relationship to a prior `check()`/`acheck()` result unless your application explicitly composes the two; see the [Tutorial](TUTORIAL.md#11-evidence-checking) for the recommended composition pattern and what it does and doesn't guarantee.

---

## API

### `booth.check()`

```python
booth.check(
    call_fn,
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,
    *,
    validator=None,
)
```

* **`call_fn`** — `Callable[[str], str]`, receives a prompt, returns the model's raw response. Any synchronous callable works, including a callable class instance.
* **`prompt`** — the original application or user prompt.
* **`threshold`** — minimum confidence to accept an unambiguous, validator-passing answer. Default `0.7`.
* **`max_retries`** — retries after the initial attempt. Default `1`.
* **`on_attempt`** — optional callback invoked after each attempt. Must be synchronous on `check()`.
* **`validator`** (keyword-only) — optional `ValidatorFn`. See [Custom validation](#custom-validation-with-validator) above. Must be synchronous. Default `None`.

### `booth.acheck()`

```python
await booth.acheck(
    call_fn,   # Callable[[str], Awaitable[str]]
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,
    *,
    validator=None,
)
```

Async equivalent of `check()`. `call_fn` may be a plain `async def` function, a `functools.partial` wrapping one, or an object with an `async def __call__` (0.4.6+). `on_attempt` accepts the same shapes and is correctly awaited (0.4.7+). `validator` itself is always required to be synchronous.

### `booth.check_with_evidence()`

```python
booth.check_with_evidence(
    answer,
    evidence,
    compare_fn,
    evidence_threshold=0.7,
)
```

* **`answer`** — the answer being checked.
* **`evidence`** — a sequence of evidence strings your application already retrieved.
* **`compare_fn`** — `Callable[[str, Sequence[str]], bool | float]`.
* **`evidence_threshold`** — minimum score when `compare_fn` returns a float. Default `0.7`.

Makes no LLM/network calls, performs no retrieval or retries, has no `validator` of its own, and always returns `parsed=None`.

---

## Result Object

```python
result.answer                # str | None
result.status                 # VERIFIED / REPAIRED / AMBIGUOUS / UNCERTAIN / BLOCKED
result.confidence             # self-reported (check/acheck) or comparison score (evidence)
result.evidence_agreement     # comparison score from check_with_evidence(), else None
result.attempts               # full retry history
result.n_attempts             # len(result.attempts)
result.ok                     # True only for VERIFIED / REPAIRED
result.ambiguous              # bool
result.interpretations        # list[str]
result.all_parse_failed       # True if every attempt failed to parse
result.method                 # which mechanism produced this result
result.parsed                 # raw, uncoerced model JSON
result.to_dict()              # full result as a plain, JSON-serializable dict (0.4.7)
```

## Result Statuses

* **`VERIFIED`** — passed BOOTH's acceptance condition on the initial attempt (or the evidence comparison passed).
* **`REPAIRED`** — a reconsideration attempt produced an acceptable result after the first attempt fell short.
* **`AMBIGUOUS`** — the model identified multiple valid interpretations. Returned immediately, never retried.
* **`UNCERTAIN`** — no acceptable result was obtained. Check `result.method` for why.
* **`BLOCKED`** — the evidence comparison explicitly failed. Only reachable from `check_with_evidence()`.

---

## Installation

```bash
pip install boothpy
```

Or directly from GitHub:

```bash
pip install git+https://github.com/Vedantgitbot/booth.git
```

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

CI runs the full suite on push/PR across Python 3.9–3.12. See [CHANGELOG.md](CHANGELOG.md) for what each version's regression tests specifically verify.

---

## Design Principles

1. **Keep the checkpoint small.** A reusable decision layer, not another full LLM framework.
2. **Make uncertainty explicit.** Return a structured status instead of silently passing an unacceptable output through.
3. **Treat ambiguity, validation, and confidence as separate, ordered checks.** A confident, validator-passing answer can still be ambiguous.
4. **Reconsider instead of blindly resampling.** The reason an attempt failed determines what the model is actually shown on retry.
5. **Expose, don't reinterpret.** `result.parsed` shows the model's raw response rather than deciding what it should mean.
6. **Reject invalid data, don't silently coerce it.** An out-of-range confidence or an unrecognized boolean-ish value is a reason to reject the attempt, never guess at.
7. **Keep evidence retrieval outside BOOTH.** Applications own their own RAG, search, database, or tool infrastructure.
8. **Do not pretend agreement is truth.** Agreement with a validator, confidence value, or retrieved evidence is not the same as proving a claim.
9. **Stay provider-agnostic.** BOOTH works with any LLM provider because your application supplies the model-calling function.

For a full account of what BOOTH intentionally does *not* do, its current limitations, and the reasoning behind specific design tradeoffs, see the [Tutorial](TUTORIAL.md#13-limitations).

---

## License

This is the official BOOTH repository — Vedant Brahmbhatt

BOOTH is released under the MIT License. See [`LICENSE`](LICENSE) for the full text.