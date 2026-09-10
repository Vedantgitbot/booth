# BOOTH Tutorial

A concise guide to using BOOTH's current public API.

BOOTH is a lightweight checkpoint library for LLM outputs. It sits between your application and an LLM call and provides structured results for confidence, ambiguity, custom validation, retries, and evidence agreement.

---

## 1. Install

```bash
pip install boothpy
```

For local development:

```bash
git clone https://github.com/Vedantgitbot/booth.git
cd booth
pip install -e .
```

Check the installed version:

```python
import booth

print(booth.__version__)
# 0.4.7
```

---

## 2. Basic Usage

The simplest BOOTH workflow uses `check()`:

```python
import booth


def call_llm(prompt: str) -> str:
    return your_llm_client(prompt)


result = booth.check(
    call_llm,
    "What is the capital of France?"
)

if result.ok:
    print(result.answer)
else:
    print(result.status)
```

BOOTH calls your function, parses the model's response, checks its reported confidence and ambiguity, and returns a structured `BoothResult`.

BOOTH does not require a specific LLM provider. Your `call_fn` is responsible for communicating with OpenAI, Anthropic, Groq, a local model, or any other provider.

---

## 3. `booth.check()`

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

### `call_fn`

A synchronous function that receives a prompt and returns the model's response:

```python
def call_llm(prompt: str) -> str:
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
```

`call_fn` doesn't have to be a plain function — any synchronous callable works, including a class instance with a `__call__` method:

```python
class MyClient:
    def __call__(self, prompt: str) -> str:
        return self._client.chat.completions.create(...).choices[0].message.content

result = booth.check(MyClient(), "What is the capital of France?")
```

**Robustness note (0.4.6):** a callable object whose `__call__` is *synchronous* but internally returns an awaitable (e.g. `def __call__(self, prompt): return some_async_operation(prompt)`) is intentionally not treated as an async `call_fn` for `acheck()` — there's no reliable way to detect that pattern from the callable's signature alone, without actually calling it. See [section 10](#10-async-usage) for what `acheck()` does support.

### `prompt`

The question or instruction you want the model to answer.

### `threshold`

Minimum model-reported confidence required to accept an unambiguous, validator-passing answer.

Default:

```python
0.7
```

Example:

```python
result = booth.check(
    call_llm,
    "What is 2 + 2?",
    threshold=0.8,
)
```

Confidence is self-reported by the model. BOOTH does not independently calibrate it.

### `max_retries`

Number of additional attempts after the first attempt.

```text
max_retries=0  -> 1 total call
max_retries=1  -> up to 2 total calls
max_retries=2  -> up to 3 total calls
```

For a low-confidence answer, BOOTH asks the model to reconsider its previous response. If the previous response could not be parsed, BOOTH instead asks the model to correct its response format. If a `validator` was supplied and the answer failed it, BOOTH shows the model the specific validation failure instead of either of those.

### `on_attempt`

Optional callback called after every attempt:

```python
def log_attempt(index, attempt):
    print(
        index,
        attempt.confidence,
        attempt.parse_ok,
        attempt.ambiguous,
        attempt.passed_validation,
        attempt.parsed,
    )


result = booth.check(
    call_llm,
    "What is the capital of France?",
    on_attempt=log_attempt,
)
```

This is useful for logging, debugging, and evaluating model behavior. On `check()`, `on_attempt` must always be synchronous — an async one raises `TypeError` immediately, the same as an async `validator` is rejected. On `acheck()`, `on_attempt` may be synchronous or asynchronous; see the note below for exactly which async shapes are recognized.

**Robustness note (0.4.7):** `on_attempt` async detection used to rely on a bare `inspect.iscoroutinefunction(on_attempt)` check — the same check that missed an object whose `__call__` is itself `async def` for `call_fn`, before that was fixed for `call_fn` in `v0.4.6`. The `on_attempt` path had the identical gap, just never patched at the same time. A callback wrapped in a class (`class Logger: async def __call__(self, index, attempt): ...` — a natural pattern for a batching or rate-limited logger) was silently misdetected: on `acheck()` it was called without being awaited, so the coroutine was created and immediately discarded instead of actually running; on `check()` it slipped past the synchronous-only guard instead of raising `TypeError` as documented. Both entry points now reuse the same `_is_async_callable()` helper `call_fn` already uses, so `on_attempt` recognizes a plain `async def` function, a `functools.partial` wrapping one, and an object with `async def __call__` — identically to `call_fn`.

### `validator` (keyword-only)

Optional custom validation rule, checked after ambiguity but before confidence. Covered in full in section 6 below.

---

## 4. Ambiguity

BOOTH asks the model to identify whether a question has multiple valid interpretations.

For example:

```python
result = booth.check(
    call_llm,
    "What is the capital of Georgia?"
)
```

The model may identify:

```text
Georgia the country
Georgia the US state
```

and return:

```python
result.status == booth.AMBIGUOUS
```

The detected interpretations are available through:

```python
result.interpretations
```

Ambiguous results are not automatically retried, and a `validator` is never even invoked on an ambiguous attempt — reconsidering the same question, or checking it against a custom rule, does not resolve ambiguity in the question itself.

**Robustness note (0.4.4):** the model is expected to return a real JSON boolean for `ambiguous`, but BOOTH also correctly recognizes the literal strings `"true"`/`"false"` (case-insensitively) if a model outputs those instead. Any other value — a number, an unrecognized string — is treated as a parse failure rather than guessed at, since naively converting an unexpected value with Python's `bool()` can silently produce the wrong answer (`bool("false")` is `True` in Python, since any non-empty string is truthy).

---

## 5. Confidence and Retries

If the response is not ambiguous but its confidence is below the configured threshold, BOOTH can ask the model to reconsider it.

```python
result = booth.check(
    call_llm,
    "What is the capital of France?",
    threshold=0.8,
    max_retries=1,
)
```

If the first attempt is below the threshold but a retry produces an acceptable answer, the result is:

```python
result.status == booth.REPAIRED
```

If the initial answer already meets the requirements:

```python
result.status == booth.VERIFIED
```

**Robustness note (0.4.4):** `confidence` is expected to be a number. If a model ever outputs a JSON boolean (`true`/`false`) for this field instead — a plausible mix-up after seeing `true`/`false` used for `ambiguous` earlier in the same schema — BOOTH rejects it rather than accepting it, because Python's `float(True) == 1.0` and `float(False) == 0.0` would otherwise silently convert it into a valid-looking confidence score. A genuine numeric string like `"0.95"` is still accepted and converted normally; only an actual boolean value is rejected.

---

## 6. Custom Validation with `validator`

Sometimes "confident and unambiguous" isn't enough — you also need the answer to satisfy a rule specific to your application (a required format, an allowed set of values, a business constraint). `validator` lets you plug that rule directly into BOOTH's existing retry loop, rather than checking `result.answer` yourself afterward and manually deciding whether to re-run `check()`.

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

result = booth.check(
    call_llm,
    "What is the order ID for this request?",
    validator=is_valid_order_id,
)
```

`validator` receives the answer text and returns one of:

**A plain boolean:**

```python
result = booth.check(call_llm, prompt, validator=lambda a: a.isdigit())
```

`False` produces a generic failure message shown to the model on retry.

**A `(bool, str)` tuple, with a specific reason:**

```python
def validate_amount(answer: str):
    if not answer.replace(".", "", 1).isdigit():
        return False, "The answer must be a plain numeric amount, e.g. 42.50"
    return True, ""

result = booth.check(call_llm, prompt, validator=validate_amount, max_retries=1)
```

The reason string is shown to the model verbatim on the retry prompt — a much more specific correction signal than a generic "try again."

**Two additional accepted shapes (0.4.4+), because both are natural mistakes rather than edge cases:**

```python
# A None message where you don't have anything specific to say:
def validate_simple(answer: str):
    return (True, None) if answer else (False, None)

# A list instead of a tuple — an easy habit to fall into:
def validate_as_list(answer: str):
    return [False, "must be numeric"]
```

Both are accepted with the identical contract as `(bool, str)`. If the second element is `None` and the validation failed, BOOTH supplies a generic fallback message, the same as a bare `False` return.

**numpy/pandas booleans (0.4.4+, cross-version-safe as of 0.4.5):** if your validation logic touches numpy or pandas, a `numpy.bool_` return is accepted anywhere a plain Python `bool` is — recognized by type identity, not by importing numpy (BOOTH stays zero-dependency either way). numpy 2.0 renamed the underlying scalar type so that `type(np.bool_(x)).__name__` is `"bool"` instead of the pre-2.0 `"bool_"`; BOOTH's detection recognizes both names, so this works regardless of your installed numpy version.

### Where validation fits in the order of checks

For each attempt, BOOTH checks, in this order:

1. **Is it ambiguous?** If so, return `AMBIGUOUS` immediately — `validator` is never called.
2. **Did it parse?** If not, retry with a parse-failure prompt — `validator` is never called (nothing to validate yet).
3. **Does it pass `validator`** (if one was supplied)? If not, retry with a prompt showing the specific validation failure — the confidence check is never reached this round.
4. **Is confidence at or above `threshold`?** If so, accept.

This means a highly confident, unambiguous answer can still be rejected and retried if it fails your `validator` — validation is checked *before* confidence, not after.

### Error handling

If `validator` raises an exception, or returns anything other than one of the accepted shapes above, BOOTH treats that as a failed validation — it never crashes `check()`/`acheck()`:

```python
def broken_validator(answer):
    raise RuntimeError("oops")

result = booth.check(call_llm, prompt, validator=broken_validator, max_retries=0)
# result.status == booth.UNCERTAIN
# result.attempts[0].validation_error contains the exception message
```

A genuinely malformed shape — a 3-element list, a tuple whose first element isn't boolean-like — is still correctly rejected as an invalid type; the 0.4.4 widening only covers the two specific natural-mistake cases above, not an open-ended acceptance of anything.

**Robustness note (0.4.6):** `validator` must always be synchronous (see the "Async" subsection below). If you accidentally pass an `async def` validator, BOOTH detects the resulting coroutine, closes it, and rejects it as a clean validation failure with a specific message telling you the validator must be synchronous. Earlier versions already rejected this correctly as an invalid return type, but left the coroutine unclosed, which leaked a `RuntimeWarning: coroutine '...' was never awaited` to stderr on every occurrence — that warning no longer appears.

### `validator=None` is a true no-op

If you never pass `validator`, behavior is identical to pre-0.4.2 BOOTH — every code path this parameter introduces is simply unreachable.

### Type-hinting your own validator

```python
from booth import ValidatorFn

def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

my_validator: ValidatorFn = is_valid_order_id
```

`ValidatorFn` is importable directly from the top-level `booth` package (fixed in 0.4.4 — it was defined in `booth.core` since 0.4.2 but not exported from the public package until now).

### Async

`acheck()` supports `validator` identically. `validator` itself must always be **synchronous** for both `check()` and `acheck()` — if your validation logic needs to await something (an API call, a database lookup), resolve it yourself first and pass a plain sync closure in:

```python
async def call_llm(prompt: str) -> str:
    response = await async_client(...)
    return response

result = await booth.acheck(
    call_llm,
    "What is the order ID?",
    validator=is_valid_order_id,   # still a plain sync function
)
```

---

## 7. Seeing the Model's Raw Response with `parsed`

BOOTH coerces the model's response into consistent types for you — `answer` becomes a `str`, `confidence` becomes a `float`, `interpretations` becomes a `list[str]`. Most of the time that's exactly what you want. But sometimes you need to see exactly what the model actually sent, uncoerced — for logging, for debugging a model that's behaving oddly, or because you asked it to include your own extra field alongside BOOTH's schema.

`result.parsed` (and the per-attempt `attempt.parsed`) gives you that raw object:

```python
result = booth.check(call_llm, "What's the refund window?")

print(result.answer)      # "30 days"           — coerced string
print(result.confidence)  # 0.95                — coerced float
print(result.parsed)      # {"answer": "30 days", "confidence": "0.95", ...} — raw, as returned
```

Notice `result.parsed["confidence"]` can legitimately be the **string** `"0.95"` even though `result.confidence` is the **float** `0.95` — BOOTH coerced one and kept the other untouched. That's intentional, not a bug: `parsed` is a transparency layer over the raw object, not a second copy of the already-coerced fields.

### Extra fields survive untouched

If you ask the model to include something BOOTH doesn't itself use — a citation, a source document name, an internal reasoning tag — it shows up in `parsed` even though BOOTH never reads it:

```python
result = booth.check(call_llm, prompt)  # prompt asks the model to also include "source"
print(result.parsed.get("source"))      # whatever the model put there, untouched
```

BOOTH does not validate or sanitize that extra content — treat it with the same skepticism you'd apply to any other model output that hasn't been checked.

### Which attempt `parsed` reflects

* `VERIFIED` / `REPAIRED` / `AMBIGUOUS`: the winning attempt.
* `UNCERTAIN`: the **last successfully-parsed** attempt, even if a later attempt then failed to parse.
* `None`: only if every single attempt failed to parse.

```python
if result.status == booth.UNCERTAIN and result.parsed is not None:
    print("At least one attempt parsed; here's what it actually said:", result.parsed)
```

`check_with_evidence()` results always have `parsed=None` — there's no LLM JSON parse on that path at all.

---

## 8. `BoothResult`

`check()`, `acheck()`, and `check_with_evidence()` return a `BoothResult`.

Useful fields are:

```python
result.answer
result.status
result.confidence
result.evidence_agreement
result.attempts
result.n_attempts
result.ok
result.ambiguous
result.interpretations
result.all_parse_failed
result.method
result.parsed
```

### `answer`

The resulting answer. It can be `None` when no usable answer was obtained.

### `status`

One of `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`.

### `confidence`

For `check()` and `acheck()`, this is the model's reported confidence. For `check_with_evidence()`, it contains the comparison score when one is available.

### `evidence_agreement`

The evidence comparison score produced by `check_with_evidence()`. It is `None` for normal LLM checks.

### `attempts`

List of all LLM attempts. Each attempt contains:

```python
attempt.raw_text
attempt.answer
attempt.confidence
attempt.parse_ok
attempt.error
attempt.ambiguous
attempt.interpretations
attempt.chosen_interpretation  # preserved even when falsy (0, ""), fixed in 0.4.4
attempt.passed_validation      # always True if no validator was supplied
attempt.validation_error       # always None if no validator was supplied, or if it passed
attempt.parsed                 # this attempt's raw JSON object, None if it failed to parse
```

### `n_attempts`

Number of attempts: `len(result.attempts)`.

### `ok`

A convenient way to check whether the result passed:

```python
if result.ok:
    print(result.answer)
```

`ok` is `True` only for `VERIFIED` / `REPAIRED`.

### `all_parse_failed`

Useful for diagnosing `UNCERTAIN` results:

```python
if result.status == booth.UNCERTAIN:
    if result.all_parse_failed:
        print("No attempt produced a valid response format.")
    else:
        print("The model remained uncertain, or a validator kept rejecting the answer.")
```

`result.method` (below) gives you a more precise breakdown than `all_parse_failed` alone.

### `method`

Which of BOOTH's mechanisms actually produced the result:

```python
result.method
# "ambiguity"      — status is AMBIGUOUS
# "evidence"       — result came from check_with_evidence()
# "parse_failure"  — UNCERTAIN, every attempt failed to parse
# "validation"     — UNCERTAIN, the last attempt parsed and was
#                     confident enough, but failed your validator
# "confidence"     — the ordinary case
```

Most useful for telling `UNCERTAIN` results apart, since they otherwise look identical from `status` alone:

```python
if result.status == booth.UNCERTAIN:
    if result.method == "parse_failure":
        print("Fix call_fn / prompt formatting — nothing ever parsed.")
    elif result.method == "validation":
        print("The model never satisfied your validator.")
    else:
        print("The model tried, but confidence never reached the threshold.")
```

`method` reflects the **last** attempt's determining factor in a mixed history — not a full record of every attempt's individual outcome. For that level of detail, inspect `result.attempts` directly.

### `parsed`

The raw, uncoerced JSON object the model returned, from whichever attempt determined the result. See section 7 above for the full contract. `None` if every attempt failed to parse, or for any `check_with_evidence()` result.

### `to_dict()`

New in 0.4.7. Returns a plain `dict` representation of the entire result — every field listed above, plus the computed properties (`ok`, `method`) that plain `dataclasses.asdict()` would silently drop, since they're properties rather than dataclass fields. Each entry in `attempts` is itself converted via `dataclasses.asdict()`, so the whole thing round-trips cleanly through `json.dumps()`:

```python
import json

result = booth.check(call_llm, "What's the refund window?")

payload = result.to_dict()
payload["ok"]       # True/False — not silently missing, unlike dataclasses.asdict(result)
payload["method"]   # "confidence", "validation", etc.

json.dumps(payload)  # works — every value is a JSON-serializable type
```

This is the recommended way to log a `BoothResult`, put it on a queue, or send it to a monitoring/eval pipeline — reach for `to_dict()` instead of `dataclasses.asdict(result)` any time you need the full picture, including whether the result actually passed.

---

## 9. Handling Results

A simple application can use:

```python
result = booth.check(call_llm, prompt)

if result.ok:
    print(result.answer)

elif result.status == booth.AMBIGUOUS:
    print("Ambiguous:", result.interpretations)

else:
    print("Unable to produce an acceptable answer.")
```

For more detailed handling:

```python
if result.status == booth.VERIFIED:
    print(result.answer)

elif result.status == booth.REPAIRED:
    print(result.answer)

elif result.status == booth.AMBIGUOUS:
    print(result.interpretations)

elif result.status == booth.UNCERTAIN:
    print(f"No acceptable result ({result.method}).")

elif result.status == booth.BLOCKED:
    print("Answer did not agree with the supplied evidence.")
```

---

## 10. Async Usage

BOOTH provides `acheck()` for asynchronous applications.

```python
import booth


async def call_llm(prompt: str) -> str:
    response = await async_client(...)
    return response


async def ask(prompt: str):
    result = await booth.acheck(
        call_llm,
        prompt,
        threshold=0.7,
        max_retries=1,
    )

    if result.ok:
        return result.answer

    return "Unable to provide an acceptable answer."
```

The async function has the same behavior as `check()` but expects an async `call_fn`. `on_attempt` can also be asynchronous when using `acheck()`. `validator`, as covered in section 6, must always be synchronous regardless of which entry point you use. `result.parsed` behaves identically on both.

### What counts as an async `call_fn` (0.4.6)

`acheck()` accepts, in addition to a plain `async def` function:

```python
import functools

# functools.partial wrapping an async function — already worked
# correctly before 0.4.6, since inspect.iscoroutinefunction unwraps
# functools.partial internally (a stdlib behavior since Python 3.8):
async def call_llm(prompt: str, system: str = "") -> str:
    ...

wrapped = functools.partial(call_llm, system="be concise")
result = await booth.acheck(wrapped, "What is the capital of France?")

# An object whose __call__ is itself `async def` — a common pattern
# for a rate-limited or stateful client wrapper (fixed in 0.4.6; a
# plain inspect.iscoroutinefunction(obj) check misses this, since obj
# itself is a normal instance, not a coroutine function):
class MyAsyncClient:
    async def __call__(self, prompt: str) -> str:
        return await self._client.chat.completions.create(...)

result = await booth.acheck(MyAsyncClient(), "What is the capital of France?")
```

**What's intentionally not supported:** a callable object with a *synchronous* `__call__` that happens to return an awaitable internally (`def __call__(self, prompt): return some_coroutine`). There's no way to detect that from the callable's signature alone without actually calling it first, which `acheck()` deliberately doesn't do speculatively. Use an `async def __call__` or a plain `async def` function instead — `acheck()` will raise `TypeError` immediately for a sync callable of any kind, rather than accepting it and misbehaving later.

### What counts as an async `on_attempt` (0.4.7)

`on_attempt` is checked with the exact same detection `call_fn` uses above — a plain `async def` function, `functools.partial` wrapping one, and an object with `async def __call__` are all recognized and correctly awaited by `acheck()`:

```python
class AsyncLogger:
    async def __call__(self, index, attempt):
        await self._flush_to_queue(index, attempt)

result = await booth.acheck(
    call_llm,
    "What is the capital of France?",
    on_attempt=AsyncLogger(),   # correctly awaited as of 0.4.7
)
```

Before 0.4.7, this specific shape — an async-`__call__` object passed as `on_attempt` — was silently mishandled: called without being awaited on `acheck()`, and not rejected with `TypeError` on `check()` as documented. A plain `async def` function or a `functools.partial` of one as `on_attempt` was already handled correctly before this fix; only the `__call__`-object case was affected. `on_attempt` on `check()` must still always be synchronous — passing any of the async shapes above to `check()` now correctly raises `TypeError` immediately, rather than slipping through.

---

## 11. Evidence Checking

BOOTH can also check an answer against evidence already retrieved by your application:

```python
result = booth.check_with_evidence(
    answer="Paris is the capital of France.",
    evidence=[
        "France's capital city is Paris."
    ],
    compare_fn=compare_answer_to_evidence,
)
```

The comparison function is supplied by you:

```python
def compare_answer_to_evidence(answer, evidence):
    ...
```

It can return a boolean:

```text
True  -> VERIFIED
False -> BLOCKED
```

or a score from `0.0` to `1.0`, compared against `evidence_threshold`:

```python
def compare_answer_to_evidence(answer, evidence):
    return 0.87

result = booth.check_with_evidence(
    answer,
    evidence,
    compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

A score of `0.87` produces `VERIFIED`; a score below `0.8` produces `BLOCKED`. Boolean results are always treated as strict pass/fail values — `evidence_threshold` is not applied to them. This applies equally to a `numpy.bool_` returned from `compare_fn` (0.4.5+): if your comparison logic is written with numpy or pandas, a `numpy.bool_(False)` is treated as a strict fail rather than being coerced into a `0.0` score and re-checked against `evidence_threshold`. This recognition is cross-version-safe — numpy 2.0 renamed the underlying scalar type, and BOOTH accounts for both the old and new names.

An `answer` that is empty or entirely whitespace is treated as missing: `check_with_evidence()` returns `UNCERTAIN` without calling `compare_fn` at all (0.4.5+; previously only a fully empty string like `""` was caught, not a whitespace-only string like `" "`).

### A concrete example: a document that disagrees with the model

The point of `check_with_evidence()` is easiest to see with a case where the model gets it wrong. Say your RAG pipeline retrieved the actual termination clause of a contract, and the model was asked to summarize the notice period:

```python
evidence = [
    "Either party may terminate this Agreement upon ninety (90) "
    "days written notice to the other party."
]

def compare_answer_to_evidence(answer: str, evidence: list) -> bool:
    return "90" in answer  # a real implementation would do something smarter

result = booth.check_with_evidence(
    answer="You need to give 45 days' notice to cancel.",
    evidence=evidence,
    compare_fn=compare_answer_to_evidence,
)

result.status               # BLOCKED — the answer contradicts the evidence
result.evidence_agreement   # False, straight from compare_fn
```

Without this check, `"45 days"` is just a string your application has no particular reason to doubt — it reads like a normal, confident answer. `check_with_evidence()` is what turns "the model said 45 days" into "the model said 45 days, and that disagrees with the 90-day clause we actually retrieved" — a materially different, and much more actionable, thing for your application to know before it reaches a user.

### Important

`check_with_evidence()` does not retrieve or verify the evidence itself, and has no `validator` or `parsed` of its own — it is a single-purpose comparison gate. It:

* makes no LLM calls
* makes no network calls
* performs no retrieval
* performs no retries

The application is responsible for retrieving the evidence and deciding how evidence should be compared. Passing evidence to a model as RAG context and then separately confirming the answer agrees with it does not establish that the evidence itself was correct — a wrong document can produce a confident, evidence-consistent, still-wrong answer.

This also means BOOTH does not filter or judge the *content* of the `evidence` sequence you pass in — for example, a list containing blank or whitespace-only strings is not specially detected; only a fully empty sequence (`[]`) is rejected. Deciding what counts as usable evidence remains your application's responsibility, same as retrieval itself.

---

## 12. Complete Example

```python
import booth


def call_llm(prompt: str) -> str:
    # Connect this to your preferred LLM provider.
    return llm_client(prompt)


def is_valid_answer(answer: str):
    if len(answer.strip()) == 0:
        return False, "Answer cannot be empty"
    return True, ""


def ask(prompt: str):
    result = booth.check(
        call_llm,
        prompt,
        threshold=0.7,
        max_retries=1,
        validator=is_valid_answer,
    )

    if result.status == booth.AMBIGUOUS:
        return {
            "status": result.status,
            "interpretations": result.interpretations,
        }

    if result.ok:
        return {
            "status": result.status,
            "answer": result.answer,
            "raw": result.parsed,
        }

    return {
        "status": result.status,
        "method": result.method,
        "answer": None,
    }


print(ask("What is the capital of France?"))
```

---

## 13. Limitations

BOOTH is a checkpoint layer, not a guarantee of factual correctness. This section is the honest, complete account — if you're deciding whether BOOTH fits your use case, this is the place to read closely.

### What BOOTH does not do

BOOTH does **not**:

* guarantee factual correctness or independently establish truth
* automatically browse the web, perform RAG, retrieve evidence, or choose a vector database or comparison method
* retry evidence retrieval, or manage a tool-calling loop
* compare multiple independent LLMs against each other
* provide calibrated confidence probabilities — a model's self-reported `0.9` is not a real 90% chance of correctness
* guarantee that retrieved evidence is correct, complete, relevant, or current
* filter, deduplicate, or otherwise judge the quality of `evidence` content — including blank or empty-but-present entries — beyond checking that the sequence itself isn't empty
* guarantee that a custom `validator` is itself correct — a validator can pass a wrong answer or reject a correct one, same as any other application-supplied rule
* validate or enforce a schema on `result.parsed` — it is exposed as-is, entirely unvalidated
* detect a synchronous callable that happens to return an awaitable internally — see [section 10](#10-async-usage) for why this is intentionally out of scope
* replace application-specific validation or safety systems (though `validator` gives you a documented hook to plug your own logic into BOOTH's retry loop rather than reimplementing that loop yourself)

BOOTH is a **checkpoint library**, not an LLM framework, search engine, RAG framework, or autonomous verification system.

### What evidence checking actually means

`check_with_evidence()` checks **agreement with the evidence supplied to it** — it does not establish that the evidence itself is true.

If your application retrieves an incorrect document (e.g. `"Digital downloads are never eligible for refunds."`) and your `compare_fn` determines the answer agrees with it, BOOTH can return `VERIFIED`. That means the answer passed the supplied comparison — it does **not** mean BOOTH independently confirmed the evidence was correct.

This holds with equal force when evidence is baked into a prompt as RAG context and then separately checked: the model can produce a highly confident, unambiguous, evidence-agreeing answer that is still simply wrong, if the retrieved evidence itself was wrong. Neither `check()`'s confidence check nor `check_with_evidence()`'s agreement check can catch that — only the quality of your retrieval can. The same applies to evidence *content* quality more generally: a list containing blank or whitespace-only strings is not specially detected by BOOTH; only a fully empty sequence (`[]`) is rejected. Deciding what counts as usable evidence remains your application's responsibility.

### No automatic reconciliation between check() and check_with_evidence()

`check_with_evidence()` is a standalone evidence checkpoint. It does not automatically consume or modify the result of a prior `check()` or `acheck()` call. If you use both together, your application decides how to combine the two results — including whether a `BLOCKED` evidence result should override an otherwise-`VERIFIED` text-confidence result. BOOTH's own `max_retries` only bounds a single `check()`/`acheck()` call; it has no visibility into retries you build across multiple calls.

```python
b_result = booth.check(call_llm, prompt)

if b_result.ok:
    a_result = booth.check_with_evidence(b_result.answer, evidence, compare_fn)
    if a_result.ok:
        print(a_result.answer)
```

**This is the single most common point of confusion in practice**, so it's worth being explicit: if you log or display `b_result.status` and `a_result.status` side by side, you can end up with something that reads like a contradiction — `status: VERIFIED` next to `evidence_status: BLOCKED` — even though nothing is actually wrong. They are two independent `BoothResult` objects from two independent checks, not one combined verdict. If you want a single final status, you need to compute it yourself, e.g.:

```python
final_status = a_result.status if not a_result.ok else b_result.status
```

BOOTH deliberately doesn't make this decision for you, because the right combination policy depends on your application (should a weak `compare_fn` score be allowed to override a confident, well-formed answer? that's a call only you can make for your use case).

### Other limitations

* model confidence is self-reported and not independently calibrated
* ambiguity detection depends on the model recognizing the ambiguity — it can also mistake its own uncertainty for ambiguity
* a confident model can still be wrong; retries do not guarantee correction
* `result.parsed` exposes the model's raw output exactly as sent — BOOTH does not validate or sanitize any extra fields it contains
* the quality of `compare_fn` directly affects evidence-checking results
* each retry can increase LLM cost and latency — this applies to validator-driven retries the same as confidence-driven ones

### When BOOTH is (and isn't) the right tool

BOOTH earns its keep on tasks where correctness is fuzzy, subjective, or genuinely hard to check cheaply — open-ended factual QA, summarization, extraction, RAG-answer grounding. It adds a self-reported confidence signal and a genuine reconsideration loop where you otherwise have no cheap way to know if an answer is trustworthy.

It is very likely the wrong tool for tasks with a deterministic, checkable answer — algorithmic problems, exact string/numeric matches, anything you can verify with a one-line assertion. Wrapping an LLM's guess for something like a Two Sum solution in `booth.check()` gets you a self-reported confidence score for a problem that has no ambiguity worth detecting and no fuzziness worth reconsidering — `assert result == expected` will catch a wrong answer faster and more reliably than a confidence threshold ever will, because a model can be confidently wrong and BOOTH has no way to know that (see "What evidence checking actually means" above — the same principle applies to confidence checking).

---

## 14. Current API

The main public functions are:

```python
booth.check()
booth.acheck()
booth.check_with_evidence()
```

The main public result and types include:

```python
booth.Attempt
booth.BoothResult
booth.CompareFn
booth.ValidatorFn
```

`BoothResult` also exposes `result.to_dict()` (0.4.7) for a fully JSON-serializable representation of a result, including its computed properties — see [section 8](#8-boothresult).

Status constants:

```python
booth.VERIFIED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

BOOTH is intentionally small and provider-agnostic, leaving LLM providers, retrieval systems, evidence sources, and application-specific validation under the application's control.