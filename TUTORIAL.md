# BOOTH Tutorial

A practical guide to BOOTH's public API and how each function, type, property, and method works.

BOOTH is a lightweight checkpoint layer for LLM outputs. It takes an LLM call, evaluates the returned response for parsing, ambiguity, confidence, and optional application-specific validation, and gives your application a structured `BoothResult`.

This tutorial focuses on **how BOOTH works and how to use its API**.

Guidance about when BOOTH is appropriate, when it is unnecessary, and its broader limitations belongs in `use-cases.md`.

---

## 1. Installation

Install BOOTH from PyPI:

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
```

---

## 2. The BOOTH Model

The normal BOOTH flow looks like this:

```text
Your application
      │
      ▼
   booth.check()
      │
      ▼
    call_fn
      │
      ▼
      LLM
      │
      ▼
 LLM response
      │
      ▼
 BOOTH parses response
      │
      ├── ambiguous?
      ├── valid format?
      ├── custom validator?
      └── confidence >= threshold?
      │
      ▼
  BoothResult
```

The application owns the LLM client. BOOTH does not require a particular provider.

For example:

```python
def call_llm(prompt: str) -> str:
    return your_llm_client(prompt)
```

BOOTH calls this function whenever it needs an LLM attempt.

---

# 3. `check()`

`check()` is the primary synchronous BOOTH API.

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

It runs an LLM call, evaluates the response, optionally retries it, and returns a `BoothResult`.

## Basic example

```python
import booth

def call_llm(prompt: str) -> str:
    return your_llm_client(prompt)

result = booth.check(
    call_llm,
    "What is the capital of France?",
)

if result.ok:
    print(result.answer)
else:
    print(result.status)
```

---

## 3.1 `call_fn`

`call_fn` is the function BOOTH uses to communicate with your LLM.

It receives the generated prompt and must return the model's response.

```python
def call_llm(prompt: str) -> str:
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
```

It can be any synchronous callable.

For example, a callable object is valid:

```python
class MyClient:
    def __call__(self, prompt: str) -> str:
        return self._client.chat.completions.create(
            ...
        ).choices[0].message.content

result = booth.check(
    MyClient(),
    "What is the capital of France?",
)
```

The important requirement is that `check()` receives a synchronous callable.

---

## 3.2 `prompt`

`prompt` is the question or instruction sent through BOOTH to the model.

```python
result = booth.check(
    call_llm,
    "Explain how TCP works.",
)
```

The prompt can be any application-specific LLM instruction.

---

## 3.3 `threshold`

`threshold` controls the minimum confidence required for an otherwise acceptable answer.

```python
result = booth.check(
    call_llm,
    "What is 2 + 2?",
    threshold=0.8,
)
```

The default threshold is:

```python
booth.DEFAULT_THRESHOLD
```

Currently:

```python
0.7
```

The confidence value is **reported by the model itself**. BOOTH does not independently calibrate or verify that probability.

---

## 3.4 `max_retries`

`max_retries` specifies how many additional attempts BOOTH may make after the initial attempt.

```python
booth.check(
    call_llm,
    prompt,
    max_retries=2,
)
```

The number of total possible calls is:

```text
max_retries=0  → 1 total attempt
max_retries=1  → up to 2 total attempts
max_retries=2  → up to 3 total attempts
```

The default is:

```python
booth.DEFAULT_MAX_RETRIES
```

`max_retries` must be a genuine `int`. A non-integer value such as `1.5` raises `TypeError` immediately, rather than failing deep inside the retry loop.

Retries are used to give the model a chance to repair an unacceptable response.

The retry prompt depends on what went wrong:

```text
Low confidence
    → ask the model to reconsider

Parse failure
    → ask the model to correct its response format

Validator failure
    → show the validation failure and ask for a correction
```

Ambiguity is different: an ambiguous attempt is returned immediately rather than automatically retried.

---

## 3.5 `on_attempt`

`on_attempt` is an optional callback executed after each attempt.

```python
def log_attempt(index, attempt):
    print("Attempt:", index)
    print("Confidence:", attempt.confidence)
    print("Parsed:", attempt.parse_ok)
    print("Ambiguous:", attempt.ambiguous)
    print("Validation:", attempt.passed_validation)

result = booth.check(
    call_llm,
    "What is the capital of France?",
    on_attempt=log_attempt,
)
```

The callback receives:

```python
index
attempt
```

`index` identifies the attempt, while `attempt` is an `Attempt` object.

For `check()`, `on_attempt` must be synchronous.

Passing an asynchronous callback to `check()` raises `TypeError`. This applies to a plain `async def` function and to an object whose `__call__` is itself `async def`.

---

## 3.6 `validator`

`validator` is an optional application-defined validation function.

It is useful when an answer must satisfy a rule that BOOTH's normal ambiguity and confidence checks cannot express.

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

result = booth.check(
    call_llm,
    "What is the order ID?",
    validator=is_valid_order_id,
)
```

The validator receives the answer text.

### Boolean return

The simplest validator returns a boolean:

```python
def validate(answer: str) -> bool:
    return answer.isdigit()
```

`True` means validation passed.

`False` means validation failed.

If retries remain, BOOTH tells the model that validation failed and asks it to correct the answer.

### Returning a reason

A validator can also return:

```python
(bool, str)
```

For example:

```python
def validate_amount(answer: str):
    if not answer.replace(".", "", 1).isdigit():
        return False, "The answer must be a numeric amount, e.g. 42.50"

    return True, ""
```

The reason is included in the retry prompt.

This gives the model a specific correction signal.

### `None` as the reason

A validator may return:

```python
(True, None)
```

or:

```python
(False, None)
```

When validation fails and the reason is `None`, BOOTH uses a generic validation failure message.

### Lists are also accepted

The equivalent list form is accepted:

```python
return [False, "must be numeric"]
```

The supported validation-result forms are therefore:

```python
True
False

(True, "specific reason")
(False, "specific reason")

(True, None)
(False, None)

[True, "specific reason"]
[False, "specific reason"]

[True, None]
[False, None]
```

### Validation order

For every attempt, BOOTH evaluates the response in this order:

```text
1. Ambiguity
2. Parsing
3. Validator
4. Confidence
```

That means validation occurs **before confidence**.

A highly confident answer can therefore still fail:

```python
validator(answer) == False
```

and be retried.

### Validator exceptions

If the validator raises an exception, BOOTH treats validation as failed rather than crashing the whole check.

```python
def broken_validator(answer):
    raise RuntimeError("oops")

result = booth.check(
    call_llm,
    prompt,
    validator=broken_validator,
    max_retries=0,
)
```

The result becomes `UNCERTAIN`, and the attempt records the validation error.

### Validators are synchronous

Validators must always be synchronous.

This applies to both:

```python
booth.check()
```

and:

```python
booth.acheck()
```

If your application needs asynchronous work for validation, perform that work before creating the synchronous validator or otherwise resolve the required information first.

---

# 4. Ambiguity

BOOTH can detect when a question has multiple possible interpretations.

For example:

```python
result = booth.check(
    call_llm,
    "What is the capital of Georgia?",
)
```

"Georgia" could refer to:

```text
Georgia the country
Georgia the US state
```

An ambiguous response has:

```python
result.status == booth.AMBIGUOUS
```

The interpretations are available through:

```python
result.interpretations
```

For example:

```python
if result.status == booth.AMBIGUOUS:
    print(result.interpretations)
```

Ambiguous attempts are not automatically retried.

The reason is that reconsidering the same question does not necessarily resolve the ambiguity in the question itself.

A validator is also not invoked when the attempt is ambiguous.

---

# 5. Confidence and Retries

For a non-ambiguous, successfully parsed response, BOOTH checks the model's reported confidence.

```python
result = booth.check(
    call_llm,
    "What is the capital of France?",
    threshold=0.8,
    max_retries=1,
)
```

If the first attempt has sufficient confidence:

```python
result.status == booth.ACCEPTED
```

If the first attempt fails the requirements but a retry produces an acceptable answer:

```python
result.status == booth.REPAIRED
```

For example:

```text
Attempt 1
confidence = 0.55
        │
        ▼
below threshold
        │
        ▼
retry
        │
        ▼
Attempt 2
confidence = 0.91
        │
        ▼
REPAIRED
```

---

# 6. `acheck()`

`acheck()` is the asynchronous equivalent of `check()`.

```python
result = await booth.acheck(
    call_fn,
    prompt,
)
```

Example:

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

The behavior is otherwise the same as `check()`.

---

## 6.1 Async `call_fn`

`acheck()` expects an asynchronous callable.

A normal async function works:

```python
async def call_llm(prompt: str) -> str:
    return await async_client(prompt)
```

A `functools.partial` wrapping an async function also works:

```python
import functools

async def call_llm(prompt: str, system: str = "") -> str:
    ...

wrapped = functools.partial(
    call_llm,
    system="be concise",
)

result = await booth.acheck(
    wrapped,
    "What is the capital of France?",
)
```

An object whose `__call__` is asynchronous also works:

```python
class MyAsyncClient:
    async def __call__(self, prompt: str) -> str:
        return await self._client.chat.completions.create(...)

result = await booth.acheck(
    MyAsyncClient(),
    "What is the capital of France?",
)
```

A synchronous callable whose `__call__` happens to return an awaitable is intentionally not treated as an async callable.

Use an actual `async def` function or an object with:

```python
async def __call__(...)
```

instead.

Conversely, `check()` expects a synchronous `call_fn`. Passing an `async def` function, or an object whose `__call__` is `async def`, raises `TypeError` immediately rather than returning an unawaited coroutine.

---

## 6.2 Async `on_attempt`

With `acheck()`, `on_attempt` may be either synchronous or asynchronous.

An async function works:

```python
async def log_attempt(index, attempt):
    await save_attempt(index, attempt)
```

An object with an async `__call__` also works:

```python
class AsyncLogger:
    async def __call__(self, index, attempt):
        await self._flush_to_queue(index, attempt)

result = await booth.acheck(
    call_llm,
    "What is the capital of France?",
    on_attempt=AsyncLogger(),
)
```

BOOTH awaits recognized asynchronous callbacks.

---

# 7. `check_with_evidence()`

`check_with_evidence()` is BOOTH's evidence-agreement checkpoint.

```python
booth.check_with_evidence(
    answer,
    evidence,
    compare_fn,
    evidence_threshold=0.8,
)
```

Unlike `check()`, this function does not make an LLM call.

Your application supplies:

1. The answer to check
2. The evidence
3. A comparison function

Example:

```python
result = booth.check_with_evidence(
    answer="Paris is the capital of France.",
    evidence=[
        "France's capital city is Paris."
    ],
    compare_fn=compare_answer_to_evidence,
)
```

As of `v0.5.1`, every non-`ACCEPTED` result from `check_with_evidence()` also carries a specific `reason` code and a human-readable `detail` string explaining exactly which of five distinct causes produced it — see §7.8 below. Ordinary `check()`/`acheck()` results are unaffected: their `reason` and `detail` are always `None`.

---

## 7.1 `answer`

`answer` is the answer that you want to compare against the supplied evidence.

```python
answer = "Paris is the capital of France."
```

An empty or whitespace-only answer is treated as missing.

In that case BOOTH returns:

```python
result.status == booth.UNCERTAIN
result.reason == booth.EMPTY_ANSWER
```

and does not call `compare_fn`.

`answer=None` is treated the same way — a missing answer, `UNCERTAIN` with `reason=booth.EMPTY_ANSWER`, no call to `compare_fn`. Any other non-`str` value (an `int`, a `list`, etc.) is a genuine caller mistake rather than a "missing" case, and as of `v0.4.9` raises `TypeError` immediately instead of crashing later with a confusing `AttributeError`:

```python
booth.check_with_evidence(answer=123, evidence=["e"], compare_fn=my_compare_fn)
# TypeError: answer must be a str, got int
```

---

## 7.2 `evidence`

`evidence` is the evidence your application has already retrieved.

For example:

```python
evidence = [
    "Either party may terminate this Agreement upon ninety (90) days written notice."
]
```

BOOTH does not retrieve the evidence itself.

It also does not determine whether the evidence is correct.

The evidence sequence must not be empty:

```python
[]
```

is rejected, with:

```python
result.status == booth.UNCERTAIN
result.reason == booth.NO_EVIDENCE
```

The content of the evidence is otherwise the application's responsibility.

`evidence` does not have to be a plain `list`. Anything with a length — a `tuple`, or a `numpy` array of strings, for example — works the same way. Prior to `v0.4.9`, a multi-element `numpy` array specifically crashed the emptiness check with `ValueError: the truth value of an array is ambiguous`, rather than being evaluated normally; that's fixed.

---

## 7.3 `compare_fn`

`compare_fn` is the function that decides whether the answer agrees with the evidence.

```python
def compare_answer_to_evidence(answer, evidence):
    ...
```

It receives:

```python
answer
evidence
```

The comparison logic belongs to your application.

For example:

```python
def compare_answer_to_evidence(answer, evidence):
    return "90" in answer
```

A real application would normally use a more appropriate comparison method.

`compare_fn` must be synchronous. An `async def compare_fn`, or a synchronous function that internally calls an async comparator and returns the resulting coroutine without awaiting it, is rejected with `TypeError` as of `v0.4.9` — previously this either crashed confusingly or silently fell through to `UNCERTAIN`, and either way leaked a "coroutine was never awaited" warning. This mirrors the treatment `validator` already gets in `check()`/`acheck()`: if your comparison needs to await something, resolve it before calling `check_with_evidence()` and pass a plain sync function.

If `compare_fn` raises any other exception, BOOTH does not propagate it. It's caught and turned into:

```python
result.status == booth.UNCERTAIN
result.reason == booth.COMPARE_FAILED
result.checker_failed == True
```

with `result.detail` containing the exception type and a truncated message, e.g. `"ValueError: division by zero"`. As of `v0.5.1`, this is the fault of the comparator, not the answer — `checker_failed` is `True` here so your application can distinguish "the checker itself broke" from "the answer just didn't hold up" without string-matching `detail`. See §7.8.

---

## 7.4 Boolean comparison

`compare_fn` may return a boolean:

```python
True
```

produces:

```python
ACCEPTED
```

while:

```python
False
```

produces:

```python
BLOCKED
result.reason == booth.EVIDENCE_DISAGREES
```

Boolean results are treated as strict pass/fail results. This includes `numpy.bool_`, recognized the same way as a native `bool`.

`evidence_threshold` is not applied to boolean results.

---

## 7.5 Score comparison

`compare_fn` can instead return a score between `0.0` and `1.0`.

```python
def compare_answer_to_evidence(answer, evidence):
    return 0.87
```

Then:

```python
result = booth.check_with_evidence(
    answer,
    evidence,
    compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

produces:

```python
result.status == booth.ACCEPTED
```

because:

```text
0.87 >= 0.8
```

A score below the threshold produces:

```python
BLOCKED
result.reason == booth.EVIDENCE_DISAGREES
result.detail  # e.g. "score 0.62 below evidence_threshold 0.8"
```

A return value that can't be used as a score at all — non-numeric, or numeric but outside `[0.0, 1.0]` — is a different failure from a genuine disagreement, and gets its own reason:

```python
result.status == booth.UNCERTAIN
result.reason == booth.INVALID_SCORE
result.checker_failed == True
```

`evidence_threshold` must be a real number (`int` or `float`). As of `v0.4.9`, a `str`, `None`, or `bool` value raises `TypeError` immediately — the same treatment `max_retries` already got in `v0.4.8` — rather than failing later with a confusing generic comparison error. `bool` is rejected here specifically (unlike `max_retries`, where `True`/`False` are harmlessly treated as 1/0): a threshold silently becoming "require a perfect 1.0 score" or "accept anything" is far more likely to be a caller mistake than an intentional choice.

```python
booth.check_with_evidence(answer, evidence, compare_fn, evidence_threshold="0.8")
# TypeError: evidence_threshold must be a real number, got str
```

---

## 7.6 Evidence result

The comparison score or boolean result is available through:

```python
result.evidence_agreement
```

For example:

```python
print(result.evidence_agreement)
```

For normal `check()` and `acheck()` results, this field is:

```python
None
```

---

## 7.7 What `check_with_evidence()` does not do

`check_with_evidence()`:

```text
does not make LLM calls
does not make network calls
does not retrieve evidence
does not retry
does not use a validator
does not produce parsed LLM JSON
```

It is simply an evidence comparison gate.

---

## 7.8 `reason`, `detail`, and `checker_failed`

Before `v0.5.1`, `check_with_evidence()` returned `UNCERTAIN` from a single construction site reused for four unrelated causes — a blank answer, empty evidence, a crashing `compare_fn`, and a malformed score — with `status` alone giving no way to tell them apart. `reason` fixes that.

`reason` is one of five fixed string codes, set only by `check_with_evidence()`:

| Code                  | Status       | Meaning                                                          | `checker_failed` |
| --------------------- | ------------ | ----------------------------------------------------------------- | ----------------- |
| `EMPTY_ANSWER`         | `UNCERTAIN`  | `answer` was empty, whitespace-only, or `None`                    | `False`           |
| `NO_EVIDENCE`          | `UNCERTAIN`  | `evidence` was an empty sequence                                  | `False`           |
| `COMPARE_FAILED`       | `UNCERTAIN`  | `compare_fn` raised an exception                                  | `True`            |
| `INVALID_SCORE`        | `UNCERTAIN`  | `compare_fn` returned something unusable as a score               | `True`            |
| `EVIDENCE_DISAGREES`   | `BLOCKED`    | a real comparison ran, and the answer scored below the threshold  | `False`           |

`result.detail` is a free-text string with the specifics of that particular case — for example, which exception type and message caused a `COMPARE_FAILED`, or what the score and threshold were for `EVIDENCE_DISAGREES`. Treat `reason` as the thing to branch on programmatically, and `detail` as the thing to log or show a human — `detail`'s exact wording isn't part of the stable API.

`checker_failed` is a computed property:

```python
@property
def checker_failed(self) -> bool:
    return self.reason in (COMPARE_FAILED, INVALID_SCORE)
```

It's `True` only when the *checker itself* is at fault — a broken `compare_fn`, or one returning garbage — as opposed to the caller's input being incomplete (`EMPTY_ANSWER`/`NO_EVIDENCE`) or the comparison producing a real, meaningful verdict (`EVIDENCE_DISAGREES`). This is a useful triage signal: `checker_failed=True` usually means "alert an engineer, your comparator is broken," while the other reasons usually mean "this specific input/answer didn't check out."

`check()` and `acheck()` results are unaffected. `reason` and `detail` default to `None` and `checker_failed` is always `False` on those results — no code runs to set them, it's just the dataclass default.

Example: branching on `reason` instead of trying to interpret `status` alone.

```python
result = booth.check_with_evidence(
    answer=llm_answer,
    evidence=retrieved_docs,
    compare_fn=my_compare_fn,
)

if result.ok:
    use(result.answer)
elif result.checker_failed:
    log.error(f"compare_fn broke: {result.detail}")
    escalate_to_engineer(result)
elif result.reason == booth.EVIDENCE_DISAGREES:
    log.info(f"Answer didn't match evidence: {result.detail}")
    escalate_to_human_review(result)
elif result.reason in (booth.EMPTY_ANSWER, booth.NO_EVIDENCE):
    log.warning(f"Incomplete input: {result.detail}")
    retry_upstream_pipeline()
```

Import the codes from the package root:

```python
from booth import (
    EMPTY_ANSWER,
    NO_EVIDENCE,
    EVIDENCE_DISAGREES,
    COMPARE_FAILED,
    INVALID_SCORE,
)
```

---

# 8. `BoothResult`

`check()`, `acheck()`, and `check_with_evidence()` return a:

```python
BoothResult
```

A result provides structured information about what happened.

The main fields are:

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
result.reason
result.detail
result.checker_failed
```

---

## 8.1 `answer`

The resulting answer.

```python
print(result.answer)
```

It may be:

```python
None
```

when no usable answer was obtained. This includes the case where the model returned a dict or list `answer` field instead of a scalar value — BOOTH rejects that as a schema violation rather than silently stringifying it into a misleading result.

A numeric or boolean `answer` (for example `{"answer": 42}`) is not rejected the same way. Since `v0.4.9`, these are coerced to their string form (`"42"`) for `result.answer`, the same treatment `confidence` already gets in the other direction — only `dict`/`list` values are schema violations.

An empty or whitespace-only `answer` (for example `{"answer": ""}` or `{"answer": "   "}`) is also rejected as of `v0.4.9`, regardless of how high the reported confidence is — a blank answer at high confidence was previously accepted as `ACCEPTED`. The one exception is an `AMBIGUOUS` attempt: the model may legitimately leave `answer` blank while relying on `interpretations` to carry the real content, so this guard does not apply when `ambiguous` is `true`.

---

## 8.2 `status`

`status` tells you the final BOOTH outcome.

Possible values are:

```python
booth.ACCEPTED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

### `ACCEPTED`

The answer passed the relevant checks on the successful attempt.

### `REPAIRED`

An earlier attempt failed, but a retry produced an acceptable result.

### `AMBIGUOUS`

The model identified multiple interpretations of the question.

### `UNCERTAIN`

BOOTH could not obtain an acceptable result. From `check_with_evidence()`, check `result.reason` (§7.8) to see which of `EMPTY_ANSWER`, `NO_EVIDENCE`, `COMPARE_FAILED`, or `INVALID_SCORE` produced it.

### `BLOCKED`

The answer failed the evidence comparison performed by `check_with_evidence()`. `result.reason` is `EVIDENCE_DISAGREES` here.

---

# 9. `BoothResult.ok`

`ok` is the convenient success check.

```python
if result.ok:
    print(result.answer)
```

It is equivalent to checking whether the status represents an accepted answer.

`ok` is `True` only when:

```python
result.status in (
    booth.ACCEPTED,
    booth.REPAIRED,
)
```

For other statuses it is `False`.

---

## 9.1 `BoothResult.unwrap()`

`unwrap()` is a stricter accessor added in `v0.5.0`. It returns `.answer` as a plain `str` when the result is ok, and raises `BoothRejected` otherwise:

```python
try:
    answer = result.unwrap()
except booth.BoothRejected as e:
    print(f"Rejected: {e.result.status} ({e.result.method})")
    answer = None
```

It uses exactly the same predicate as `.ok` — internally, `unwrap()` literally checks `self.ok` — so the two can never disagree.

This does **not** change `.answer` itself. `.answer` stays populated on rejected results (`AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`) exactly as before, intentionally, so you can still inspect what got rejected for debugging or logging. `unwrap()` is a stricter, opt-in accessor layered on top of that existing field, not a replacement for it.

The main benefit is ergonomic: `.answer` is typed `Optional[str]`, so a type checker forces `None`-handling at every call site even though it can't tell "populated but rejected" from "genuinely missing." `unwrap()` returns a plain `str` — no `Optional` handling needed — because rejection becomes an exception instead of a value you might forget to check.

### `BoothRejected`

`BoothRejected` is the exception `unwrap()` raises. It carries the full `BoothResult` as `.result`, so you don't lose any diagnostic information by catching it:

```python
try:
    answer = result.unwrap()
except booth.BoothRejected as e:
    print(e.result.status)       # e.g. "UNCERTAIN"
    print(e.result.method)       # e.g. "parse_failure"
    print(e.result.reason)       # e.g. "EMPTY_ANSWER", from check_with_evidence()
    print(e.result.attempts)     # full attempt history, still there
```

The exception's own string message (`str(e)`) intentionally does **not** include the raw rejected answer text — exception messages routinely end up in logs, and BOOTH doesn't assume you want a rejected answer logged just because someone called `unwrap()`. If you need the rejected text itself, read it explicitly from `e.result.answer`.

## 9.2 `BoothResult.unwrap_or()`

`unwrap_or(default)` behaves like `unwrap()` but returns `default` instead of raising:

```python
answer = result.unwrap_or("Sorry, I don't have a reliable answer for that.")
```

Useful when a plain fallback value is simpler than a `try`/`except` at the call site.

## 9.3 `BoothResult.checker_failed`

`checker_failed` is a computed property, `True` only on a `check_with_evidence()` result whose `reason` is `COMPARE_FAILED` or `INVALID_SCORE` — i.e. the comparator itself broke, rather than the answer failing a real comparison. Always `False` on `check()`/`acheck()` results. See §7.8 for the full breakdown and a triage example.

```python
if result.checker_failed:
    alert_engineering(result.detail)
```

---

# 10. `BoothResult.confidence`

For:

```python
check()
acheck()
```

`confidence` contains the model-reported confidence.

```python
print(result.confidence)
```

For:

```python
check_with_evidence()
```

it contains the comparison score when one is available.

---

# 11. `BoothResult.evidence_agreement`

This field contains the result produced by the evidence comparison.

```python
print(result.evidence_agreement)
```

For normal LLM checks:

```python
result.evidence_agreement is None
```

For evidence checks, it contains the comparison result when available.

---

# 12. `BoothResult.attempts`

`attempts` contains every LLM attempt made during `check()` or `acheck()`.

```python
for attempt in result.attempts:
    print(attempt)
```

Each item is an:

```python
Attempt
```

object.

An attempt contains:

```python
attempt.raw_text
attempt.answer
attempt.confidence
attempt.parse_ok
attempt.error
attempt.ambiguous
attempt.interpretations
attempt.chosen_interpretation
attempt.passed_validation
attempt.validation_error
attempt.parsed
```

`check_with_evidence()` results always have `attempts == []` — that path never populates `Attempt` objects at all, which is exactly why `result.reason`/`result.detail` (§7.8) exist: they're the equivalent diagnostic surface for a path that has no attempt history to inspect.

---

# 13. `Attempt`

`Attempt` represents one individual LLM attempt.

It is useful when you need to inspect what happened across retries.

For example:

```python
for index, attempt in enumerate(result.attempts):
    print("Attempt:", index)
    print("Answer:", attempt.answer)
    print("Confidence:", attempt.confidence)
    print("Parsed:", attempt.parse_ok)
```

## `Attempt.raw_text`

The raw text returned by the model.

```python
attempt.raw_text
```

This lets you inspect the original response.

---

## `Attempt.answer`

The normalized answer extracted from the parsed response.

```python
attempt.answer
```

---

## `Attempt.confidence`

The normalized confidence value for that attempt.

```python
attempt.confidence
```

---

## `Attempt.parse_ok`

Whether BOOTH successfully parsed the attempt.

```python
if not attempt.parse_ok:
    print("The attempt failed to parse.")
```

A call whose `call_fn` succeeded but returned something other than a string (for example `None`, or a `dict`) is also recorded here as a failed attempt rather than raising — check `attempt.error` for the reason.

---

## `Attempt.error`

Contains parsing or other attempt-level error information when applicable.

```python
print(attempt.error)
```

As of `v0.4.9`, a parse failure always carries a specific, human-readable reason here (for example `"'confidence' 17.0 is out of the [0.0, 1.0] range"` or `"'answer' was empty or whitespace-only"`) instead of leaving `error` as `None`. `call_fn` exceptions and non-string `call_fn` returns already populated this field in earlier versions; this extends the same discipline to every parse-rejection path inside `_parse_response()`.

---

## `Attempt.ambiguous`

Indicates whether the attempt was identified as ambiguous.

```python
if attempt.ambiguous:
    print(attempt.interpretations)
```

---

## `Attempt.interpretations`

Contains the interpretations detected for an ambiguous question.

```python
print(attempt.interpretations)
```

---

## `Attempt.chosen_interpretation`

Stores the interpretation selected by the model when applicable.

The value is preserved even when it is falsy, such as:

```python
0
```

or:

```python
""
```

---

## `Attempt.passed_validation`

Indicates whether the custom validator passed.

```python
attempt.passed_validation
```

When no validator was supplied, this is always:

```python
True
```

---

## `Attempt.validation_error`

Contains the validation failure information when validation fails.

When no validator is supplied, or validation succeeds:

```python
attempt.validation_error is None
```

---

## `Attempt.parsed`

Contains the raw parsed JSON object for that attempt.

If parsing failed:

```python
attempt.parsed is None
```

---

# 14. `BoothResult.n_attempts`

`n_attempts` is the number of attempts BOOTH performed.

It is equivalent to:

```python
len(result.attempts)
```

Example:

```python
print(result.n_attempts)
```

If:

```python
max_retries=2
```

the maximum possible value is:

```text
3
```

---

# 15. `BoothResult.ambiguous`

`ambiguous` provides a convenient indication of whether the result is ambiguous.

It can be used alongside:

```python
result.interpretations
```

For example:

```python
if result.ambiguous:
    print("The question has multiple interpretations.")
    print(result.interpretations)
```

---

# 16. `BoothResult.interpretations`

This contains the interpretations detected for an ambiguous result.

```python
if result.status == booth.AMBIGUOUS:
    print(result.interpretations)
```

For example:

```text
[
    "Georgia the country",
    "Georgia the US state"
]
```

---

# 17. `BoothResult.all_parse_failed`

This property helps distinguish different kinds of `UNCERTAIN` results.

```python
if result.status == booth.UNCERTAIN:
    if result.all_parse_failed:
        print("No attempt produced a valid response format.")
```

If `all_parse_failed` is false, the model may have produced parseable responses that were rejected for another reason, such as validation or insufficient confidence.

This property is specific to `check()`/`acheck()` results — a `check_with_evidence()` result has no attempts to inspect, so use `result.reason` (§7.8) there instead.

---

# 18. `BoothResult.method`

`method` explains which BOOTH mechanism determined the result.

Possible values include:

```text
"ambiguity"
"evidence"
"parse_failure"
"validation"
"confidence"
```

For example:

```python
if result.status == booth.UNCERTAIN:
    if result.method == "parse_failure":
        print("No attempt could be parsed.")

    elif result.method == "validation":
        print("The answer never passed validation.")

    elif result.method == "confidence":
        print("Confidence never reached the threshold.")
```

The meanings are:

| Method          | Meaning                                                   |
| --------------- | --------------------------------------------------------- |
| `ambiguity`     | The result was blocked by ambiguity                       |
| `evidence`      | The result came from `check_with_evidence()`              |
| `parse_failure` | Every attempt failed to parse                             |
| `validation`    | The final determining failure was validation              |
| `confidence`    | The final determining failure was insufficient confidence |

`method` describes the determining mechanism rather than being a complete history of every attempt.

For the complete history on a `check()`/`acheck()` result, inspect `result.attempts`. For a `check_with_evidence()` result — where `method` is always `"evidence"` and there's no attempt history — inspect `result.reason` and `result.detail` instead (§7.8) for the equivalent level of detail.

---

# 19. `BoothResult.parsed`

`parsed` exposes the raw, uncoerced JSON object returned by the model.

For example:

```python
result = booth.check(
    call_llm,
    "What's the refund window?",
)

print(result.answer)
print(result.confidence)
print(result.parsed)
```

BOOTH normalizes fields such as:

```text
answer       → str
confidence   → float
interpretations → list[str]
```

But `parsed` preserves the original values.

For example, the model might return:

```json
{
    "answer": "30 days",
    "confidence": "0.95"
}
```

Then:

```python
result.confidence
```

can be:

```python
0.95
```

while:

```python
result.parsed["confidence"]
```

remains:

```python
"0.95"
```

This is intentional.

---

## 19.1 Extra fields

Additional fields returned by the model remain available through `parsed`.

For example, if the model returns:

```json
{
    "answer": "30 days",
    "confidence": 0.95,
    "source": "refund-policy.pdf"
}
```

you can access:

```python
result.parsed.get("source")
```

BOOTH does not validate or sanitize these extra fields.

---

## 19.2 Which attempt supplies `parsed`?

For:

```text
ACCEPTED
REPAIRED
AMBIGUOUS
```

`parsed` comes from the winning attempt.

For:

```text
UNCERTAIN
```

it comes from the last successfully parsed attempt, even if a later attempt failed to parse.

If every attempt failed to parse:

```python
result.parsed is None
```

For:

```python
check_with_evidence()
```

`parsed` is always:

```python
None
```

because that path does not parse an LLM JSON response.

---

# 20. `BoothResult.to_dict()`

`to_dict()` returns a plain dictionary containing the complete result.

```python
payload = result.to_dict()
```

It includes the normal result fields as well as computed properties such as:

```python
payload["ok"]
payload["method"]
payload["checker_failed"]
```

This is important because:

```python
dataclasses.asdict(result)
```

does not automatically include properties such as `ok`, `method`, and `checker_failed`.

Example:

```python
import json

result = booth.check(
    call_llm,
    "What's the refund window?",
)

payload = result.to_dict()

print(payload["ok"])
print(payload["method"])

json.dumps(payload)
```

As of `v0.5.1`, `payload` also always contains `"reason"` and `"detail"` — `None` for `check()`/`acheck()` results, populated for `check_with_evidence()` results (§7.8).

`to_dict()` is useful for:

* logging
* queues
* monitoring
* evaluation pipelines
* JSON serialization
* storing BOOTH results

---

# 21. Status Constants

BOOTH exposes five status constants:

```python
booth.ACCEPTED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

Use these constants instead of relying on hard-coded status strings.

Example:

```python
if result.status == booth.ACCEPTED:
    print(result.answer)
```

**Note (v0.4.8):** this status was previously named `VERIFIED`. It has been renamed to `ACCEPTED`, with no backward-compatible alias. `from booth import VERIFIED` now raises `ImportError`, and the status *string* itself changed too (`"VERIFIED"` → `"ACCEPTED"`), so any code comparing against a hardcoded string literal instead of the exported constant needs updating as well.

## 21.1 Reason Codes

As of `v0.5.1`, BOOTH also exposes five reason codes, set only on `check_with_evidence()` results (§7.8):

```python
booth.EMPTY_ANSWER
booth.NO_EVIDENCE
booth.EVIDENCE_DISAGREES
booth.COMPARE_FAILED
booth.INVALID_SCORE
```

These are a distinct, smaller set from the status constants above — `reason` narrows down *why* a `check_with_evidence()` result came back `UNCERTAIN` or `BLOCKED`, it doesn't replace `status`. Use `result.status` for the coarse ACCEPTED/BLOCKED/UNCERTAIN outcome, and `result.reason` for the specific cause.

---

# 22. Default Constants

BOOTH exposes its default configuration values:

```python
booth.DEFAULT_THRESHOLD
booth.DEFAULT_MAX_RETRIES
```

These can be useful when building application configuration around BOOTH.

Example:

```python
threshold = booth.DEFAULT_THRESHOLD
max_retries = booth.DEFAULT_MAX_RETRIES
```

---

# 23. `CompareFn`

`CompareFn` is the public type used for evidence comparison functions.

```python
from booth import CompareFn
```

A comparison function receives:

```python
answer
evidence
```

For example:

```python
def compare(answer, evidence):
    return 0.9

compare_fn: CompareFn = compare
```

It can return either a boolean or a numeric comparison score according to the `check_with_evidence()` contract.

---

# 24. `ValidatorFn`

`ValidatorFn` is the public type used for custom validators.

```python
from booth import ValidatorFn
```

Example:

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

my_validator: ValidatorFn = is_valid_order_id
```

This is useful when type-checking application code that supplies validators to BOOTH.

---

# 25. Complete Synchronous Example

The following example combines the main BOOTH features:

```python
import booth


def call_llm(prompt: str) -> str:
    return llm_client(prompt)


def validate_answer(answer: str):
    if not answer.strip():
        return False, "Answer cannot be empty"

    return True, ""


def ask(prompt: str):
    result = booth.check(
        call_llm,
        prompt,
        threshold=0.7,
        max_retries=1,
        validator=validate_answer,
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
```

---

# 26. Complete Async Example

```python
import booth


async def call_llm(prompt: str) -> str:
    return await async_llm_client(prompt)


def validate_answer(answer: str) -> bool:
    return bool(answer.strip())


async def ask(prompt: str):
    result = await booth.acheck(
        call_llm,
        prompt,
        threshold=0.7,
        max_retries=1,
        validator=validate_answer,
    )

    if result.ok:
        return result.answer

    return None
```

---

# 27. Combining Text Checking and Evidence Checking

`check()` and `check_with_evidence()` are separate operations.

For example:

```python
b_result = booth.check(
    call_llm,
    prompt,
)

if b_result.ok:
    evidence_result = booth.check_with_evidence(
        b_result.answer,
        evidence,
        compare_fn,
    )
```

The two calls produce two independent `BoothResult` objects.

BOOTH does not automatically combine them.

Your application decides what the final policy should be.

For example:

```python
if b_result.ok and evidence_result.ok:
    final_answer = b_result.answer
elif evidence_result.checker_failed:
    final_answer = None
    alert_engineering(evidence_result.detail)
else:
    final_answer = None
```

---

# 28. Inspecting Every Attempt

When debugging or evaluating model behavior, inspect `attempts`:

```python
result = booth.check(
    call_llm,
    prompt,
    max_retries=2,
)

for index, attempt in enumerate(result.attempts):
    print("Attempt:", index)
    print("Raw:", attempt.raw_text)
    print("Answer:", attempt.answer)
    print("Confidence:", attempt.confidence)
    print("Parsed:", attempt.parse_ok)
    print("Ambiguous:", attempt.ambiguous)
    print("Validation:", attempt.passed_validation)
    print()
```

This gives you more information than `result.status` alone.

For a `check_with_evidence()` result, there's no attempt history to loop over — go straight to `result.reason` and `result.detail` instead (§7.8).

---

# 29. Public API

The public package exports the following:

```python
from booth import (
    Attempt,
    BoothResult,
    BoothRejected,
    check,
    acheck,
    check_with_evidence,
    CompareFn,
    ValidatorFn,
    ACCEPTED,
    REPAIRED,
    AMBIGUOUS,
    BLOCKED,
    UNCERTAIN,
    EMPTY_ANSWER,
    NO_EVIDENCE,
    EVIDENCE_DISAGREES,
    COMPARE_FAILED,
    INVALID_SCORE,
    DEFAULT_THRESHOLD,
    DEFAULT_MAX_RETRIES,
)
```

The three primary functions are:

```python
booth.check()
booth.acheck()
booth.check_with_evidence()
```

The primary result and type objects are:

```python
booth.Attempt
booth.BoothResult
booth.BoothRejected
booth.CompareFn
booth.ValidatorFn
```

The status constants are:

```python
booth.ACCEPTED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

The reason codes (`check_with_evidence()` results only, added `v0.5.1`) are:

```python
booth.EMPTY_ANSWER
booth.NO_EVIDENCE
booth.EVIDENCE_DISAGREES
booth.COMPARE_FAILED
booth.INVALID_SCORE
```

The default configuration constants are:

```python
booth.DEFAULT_THRESHOLD
booth.DEFAULT_MAX_RETRIES
```

---

# 30. Quick Reference

## Functions

| Function                | Purpose                                              |
| ----------------------- | ---------------------------------------------------- |
| `check()`               | Run a synchronous LLM checkpoint                     |
| `acheck()`              | Run an asynchronous LLM checkpoint                   |
| `check_with_evidence()` | Compare an existing answer against supplied evidence |

## Main types

| Type            | Purpose                                |
| --------------- | --------------------------------------- |
| `Attempt`       | Represents one LLM attempt             |
| `BoothResult`   | Represents the final result            |
| `BoothRejected` | Raised by `unwrap()` on a non-ok result |
| `CompareFn`     | Type for evidence comparison functions |
| `ValidatorFn`   | Type for custom answer validators      |

## Result statuses

| Status      | Meaning                                        |
| ----------- | ----------------------------------------------- |
| `ACCEPTED`  | Accepted on the current attempt                |
| `REPAIRED`  | Accepted after a retry                         |
| `AMBIGUOUS` | Question has multiple detected interpretations |
| `UNCERTAIN` | No acceptable result was produced              |
| `BLOCKED`   | Evidence comparison failed                     |

## `check_with_evidence()` reason codes (v0.5.1+)

| Reason                | Status      | `checker_failed` |
| ---------------------- | ----------- | ----------------- |
| `EMPTY_ANSWER`          | `UNCERTAIN` | `False`            |
| `NO_EVIDENCE`           | `UNCERTAIN` | `False`            |
| `COMPARE_FAILED`        | `UNCERTAIN` | `True`             |
| `INVALID_SCORE`         | `UNCERTAIN` | `True`             |
| `EVIDENCE_DISAGREES`    | `BLOCKED`   | `False`            |

See §7.8 for the full breakdown.

## Important result properties

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
result.reason
result.detail
result.checker_failed
```

## Strict accessors

```python
result.unwrap()             # str, or raises BoothRejected
result.unwrap_or(default)   # str, or `default` if not ok
```

Use these when you want a plain `str` back instead of handling `Optional[str]` at every call site — see §9.1/§9.2.

## Result serialization

```python
result.to_dict()
```

Use `to_dict()` when you need the complete result in a JSON-compatible dictionary.

---

# 31. The Core Mental Model

The easiest way to understand BOOTH is:

```text
check()
  │
  ├── call the LLM
  │
  ├── parse the response
  │
  ├── detect ambiguity
  │
  ├── run validator (if supplied)
  │
  ├── check confidence
  │
  ├── retry when appropriate
  │
  └── return BoothResult
```

For evidence:

```text
check_with_evidence()
  │
  ├── receive answer         → empty/whitespace? reason=EMPTY_ANSWER
  ├── receive evidence       → empty sequence?   reason=NO_EVIDENCE
  ├── call compare_fn        → raised?           reason=COMPARE_FAILED
  ├── interpret the result   → unusable score?   reason=INVALID_SCORE
  ├── compare to threshold   → below threshold?  reason=EVIDENCE_DISAGREES
  └── return BoothResult
```

And for asynchronous applications:

```text
acheck()
  │
  └── same checkpoint process as check()
      using asynchronous LLM calls
```

BOOTH therefore provides the checkpoint and retry mechanics while leaving the LLM provider, evidence retrieval, comparison logic, and application-specific validation under your application's control.