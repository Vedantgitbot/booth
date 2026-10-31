# BOOTH Tutorial

A practical guide to BOOTH's public API and how each function, type, property, and method works. This version documents `v0.5.7`.

BOOTH is a lightweight checkpoint layer for LLM outputs. It takes an LLM call, evaluates the returned response for parsing, ambiguity, confidence, and optional application-specific validation, and gives your application a structured `BoothResult`.

This tutorial focuses on **how BOOTH works and how to use its API**. Guidance about when BOOTH is appropriate, when it is unnecessary, and its broader limitations belongs in `USECASES.md`.

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
pip install -e ".[dev,typecheck]"
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
   call_fn  ──►  LLM  ──►  response (a string)
      │
      ▼
 parse_fn (optional) or BOOTH's default JSON extraction
      │
      ├── valid format?
      ├── ambiguous?
      ├── custom validator?
      └── confidence >= threshold?
      │
      ▼
  BoothResult
```

The application owns the LLM client. BOOTH does not require a particular provider.

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
    parse_fn=None,
)
```

It runs an LLM call, evaluates the response, optionally retries it, and returns a `BoothResult`.

## Basic example

```python
import booth

def call_llm(prompt: str) -> str:
    return your_llm_client(prompt)

result = booth.check(call_llm, "What is the capital of France?")

if result.ok:
    print(result.answer)
else:
    print(result.status)
```

---

## 3.1 `call_fn`

`call_fn` is the function BOOTH uses to communicate with your LLM.

It receives the generated prompt and must return the model's response as a **string**. If a provider uses a format that BOOTH's default JSON extraction does not understand, keep returning that string from `call_fn` and use `parse_fn` (§3.7) to convert it into a structured dictionary.

```python
def call_llm(prompt: str) -> str:
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
```

It can be any synchronous callable. A callable object is valid:

```python
class MyClient:
    def __call__(self, prompt: str) -> str:
        return self._client.chat.completions.create(...).choices[0].message.content

result = booth.check(MyClient(), "What is the capital of France?")
```

`check()` requires a synchronous callable. An `async def` function, or an object whose `__call__` is `async def`, raises `TypeError` immediately; use `acheck()` for those (§6).

As of `v0.5.2`, a non-callable `call_fn` raises `TypeError` immediately, rather than crashing inside the retry loop:

```python
booth.check("not_callable", "What is the capital of France?")
# TypeError: call_fn must be callable, got str
```

If `call_fn` itself raises while BOOTH is running (a bad API key, a retired model name, a network error), BOOTH does not propagate the exception. It records the error on the attempt, retries if retries remain, and returns a normal `UNCERTAIN` result. Use `result.call_failed` (§17.1) to tell that apart from a model that simply answered badly.

If `call_fn` returns something that is not a string (`None`, a dictionary, a list), that is also a call failure, not a parse failure. If your provider gives you a dictionary, return `json.dumps(d)`, or return the raw string and decode it in `parse_fn`.

---

## 3.2 `prompt`

`prompt` is the question or instruction sent through BOOTH to the model.

```python
result = booth.check(call_llm, "Explain how TCP works.")
```

The prompt can be any application-specific LLM instruction. BOOTH appends its own instructions asking the model for a JSON object with `ambiguous`, `interpretations`, `chosen_interpretation`, `answer`, and `confidence`.

As of `v0.5.2`, a non-`str` `prompt` raises `TypeError` immediately:

```python
booth.check(call_llm, 123)
# TypeError: prompt must be a str, got int
```

---

## 3.3 `threshold`

`threshold` controls the minimum confidence required for an otherwise acceptable answer.

```python
result = booth.check(call_llm, "What is 2 + 2?", threshold=0.8)
```

The default is `booth.DEFAULT_THRESHOLD`, currently `0.7`. A value outside `[0.0, 1.0]` raises `ValueError`. Confidence exactly equal to the threshold passes (the comparison is `>=`).

The confidence value is **reported by the model itself**. BOOTH does not independently calibrate or verify that probability.

---

## 3.4 `max_retries`

`max_retries` specifies how many additional attempts BOOTH may make after the initial attempt.

```python
booth.check(call_llm, prompt, max_retries=2)
```

```text
max_retries=0  → 1 total attempt
max_retries=1  → up to 2 total attempts
max_retries=2  → up to 3 total attempts
```

The default is `booth.DEFAULT_MAX_RETRIES` (`1`).

`max_retries` must be an `int`. A non-integer such as `1.5` raises `TypeError` immediately, and a negative value raises `ValueError`. (`True`/`False` are accepted and mean 1 and 0.)

The retry prompt depends on what went wrong:

```text
Low confidence
    → ask the model to reconsider

Parse failure
    → ask the model to correct its response format

Validator failure
    → show the validation failure and ask for a correction

Call failure (call_fn raised or returned a non-string)
    → ask again with the original prompt
```

As of `v0.5.4`, a failed call is retried with the original prompt, exactly as in the first attempt.

Ambiguity is different: an ambiguous attempt is returned immediately rather than retried.

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

result = booth.check(call_llm, "What is the capital of France?", on_attempt=log_attempt)
```

The callback receives `index` (the attempt number, starting at 0) and `attempt` (an `Attempt` object, §13).

For `check()`, `on_attempt` must be synchronous. Passing an asynchronous callback raises `TypeError`. This applies to a plain `async def` function and to an object whose `__call__` is `async def`.

As of `v0.5.3`, a non-callable `on_attempt` raises `TypeError` immediately in both `check()` and `acheck()`, before any LLM call is made:

```python
booth.check(call_llm, "What is the capital of France?", on_attempt="not_callable")
# TypeError: on_attempt must be callable, got str
```

---

## 3.6 `validator`

`validator` is an optional application-defined validation function.

It is useful when an answer must satisfy a rule that BOOTH's normal ambiguity and confidence checks cannot express.

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

result = booth.check(call_llm, "What is the order ID?", validator=is_valid_order_id)
```

The validator receives the answer text.

As of `v0.5.5`, a non-callable validator raises `TypeError` immediately, before any LLM call is made. Passing `validator=is_valid(answer)` instead of the function itself is rejected upfront:

```python
booth.check(call_llm, "What is the order ID?", validator="not_callable")
# TypeError: validator must be callable, got str
```

### Boolean return

The simplest validator returns a boolean. `True` means validation passed and `False` means it failed. If retries remain, BOOTH tells the model that validation failed and asks it to correct the answer.

```python
def validate(answer: str) -> bool:
    return answer.isdigit()
```

### Returning a reason

A validator can also return `(bool, str)`:

```python
def validate_amount(answer: str):
    if not answer.replace(".", "", 1).isdigit():
        return False, "The answer must be a numeric amount, e.g. 42.50"
    return True, ""
```

The reason is included in the retry prompt, which gives the model a specific correction signal.

### `None` as the reason

A validator may return `(True, None)` or `(False, None)`. When validation fails and the reason is `None`, BOOTH uses a generic failure message.

### Lists are also accepted

```python
return [False, "must be numeric"]
```

The supported return forms are `True`, `False`, `(True, "reason")`, `(False, "reason")`, `(True, None)`, `(False, None)`, and the same six as two-element lists. Numpy booleans are treated like native booleans. Anything else is a failed validation.

### Evaluation order

For every attempt, BOOTH evaluates the response in this order:

```text
1. Parsing        (default extraction, or parse_fn)
2. Ambiguity      (an ambiguous attempt is returned immediately)
3. Validator
4. Confidence
```

Validation therefore occurs **before confidence**. A highly confident answer can still fail the validator and be retried. The validator never runs on an attempt that failed to parse or was flagged ambiguous.

### Validator exceptions

If the validator raises an exception, BOOTH treats validation as failed rather than crashing the whole check.

```python
def broken_validator(answer):
    raise RuntimeError("oops")

result = booth.check(call_llm, prompt, validator=broken_validator, max_retries=0)
```

The result becomes `UNCERTAIN`, and the attempt records the validation error.

### Validators are synchronous

Validators must be synchronous in both `check()` and `acheck()`. An `async def` validator produces a failed validation with a message saying so. If your validation needs asynchronous work, resolve that work before calling BOOTH.

---

## 3.7 `parse_fn`

`parse_fn` is an optional, synchronous parser added in `v0.5.7` for providers that return a string in a format the default JSON extraction should not interpret.

```python
parse_fn(raw: str) -> Optional[dict]
```

It receives the raw string returned by `call_fn` and must return the structured dictionary that BOOTH normally extracts, or `None` when parsing fails.

```python
from typing import Optional

def parse_provider_response(raw: str) -> Optional[dict]:
    provider_response = provider_decode(raw)
    return {
        "answer": provider_response.answer,
        "confidence": provider_response.confidence,
    }

result = booth.check(
    call_llm,
    "What is the capital of France?",
    parse_fn=parse_provider_response,
)
```

### What changes and what does not

- **Replaces extraction.** When `parse_fn` is supplied it fully replaces BOOTH's regex and `raw_decode` extraction. It is not layered on top of it.
- **Same validation.** The returned dictionary follows the rules of a normally parsed response. `answer` and `confidence` are required, `confidence` must be a number in `[0.0, 1.0]` (a boolean is rejected), a `dict` or `list` `answer` is rejected, an empty `answer` is rejected unless the attempt is ambiguous, and `ambiguous` is coerced from a boolean or `"true"`/`"false"`. Extra fields stay available in `result.parsed`.
- **Same pipeline.** The result feeds the existing validator, retry, confidence, ambiguity, and `BoothResult` handling.
- **The prompt is unchanged.** BOOTH still appends its JSON instructions to your prompt. `parse_fn` changes parsing only.
- **Parse failures, not call failures.** A parser exception, a `None` result, a non-dict result, or a dictionary that fails validation is reported as a parse failure, and `call_failed` stays `False`.
- **Error messages.** The attempt's `error` reads `parse_fn raised <ExceptionType>: <message>` for an exception, or `parsed response was <type>, expected dict` for a non-dict result.
- **Retry prompts are unchanged.** A failed `parse_fn` result gets the existing JSON-style parse-failure retry prompt. If that does not suit your provider-native format, use `max_retries=0` and retry in your own code.
- **`call_fn` still returns a string.** A non-`str` return is a call failure and never reaches `parse_fn`.

### Validation

`parse_fn` must be callable and synchronous. In both `check()` and `acheck()`, a non-callable or `async def` `parse_fn` raises `TypeError` immediately, before any LLM call:

```python
booth.check(call_llm, "q", parse_fn="not-callable")
# TypeError: parse_fn must be callable, got str
```

Resolve asynchronous provider decoding before calling BOOTH.

`parse_fn=None` (the default) is a true no-op, and `parse_fn` is not used by `check_with_evidence()`.

---

# 4. Ambiguity

BOOTH can detect when a question has multiple possible interpretations.

```python
result = booth.check(call_llm, "What is the capital of Georgia?")
```

"Georgia" could refer to the country or the US state. An ambiguous response has:

```python
result.status == booth.AMBIGUOUS
```

The interpretations are available through `result.interpretations`:

```python
if result.status == booth.AMBIGUOUS:
    print(result.interpretations)
```

Ambiguous attempts are not automatically retried, because reconsidering the same question does not necessarily resolve the ambiguity in the question itself. A validator is not invoked on an ambiguous attempt.

Ambiguity detection depends on the model noticing the ambiguity. Some models pick one interpretation without flagging it.

---

# 5. Confidence and Retries

For a non-ambiguous, successfully parsed response that passes the validator, BOOTH checks the model's reported confidence.

```python
result = booth.check(call_llm, "What is the capital of France?", threshold=0.8, max_retries=1)
```

If the first attempt has sufficient confidence, `result.status == booth.ACCEPTED`. If the first attempt fails but a retry produces an acceptable answer, `result.status == booth.REPAIRED`.

```text
Attempt 1: confidence 0.55
        │
        ▼
below threshold → retry
        │
        ▼
Attempt 2: confidence 0.91
        │
        ▼
REPAIRED
```

---

# 6. `acheck()`

`acheck()` is the asynchronous equivalent of `check()`. It accepts the same arguments, including `parse_fn` (§3.7); its async `call_fn` must still return a string.

```python
result = await booth.acheck(call_fn, prompt)
```

```python
import booth

async def call_llm(prompt: str) -> str:
    return await async_client(prompt)

async def ask(prompt: str):
    result = await booth.acheck(call_llm, prompt, threshold=0.7, max_retries=1)
    if result.ok:
        return result.answer
    return "Unable to provide an acceptable answer."
```

The behavior is otherwise the same as `check()`, including the argument validation described in §3. A non-`str` `prompt`, a non-callable `call_fn`, a non-callable `on_attempt`, a non-callable `validator`, and a non-callable or `async def` `parse_fn` all raise `TypeError` immediately.

---

## 6.1 Async `call_fn`

`acheck()` requires an asynchronous callable.

```python
async def call_llm(prompt: str) -> str:
    return await async_client(prompt)
```

A `functools.partial` wrapping an async function works:

```python
import functools

async def call_llm(prompt: str, system: str = "") -> str:
    ...

wrapped = functools.partial(call_llm, system="be concise")
result = await booth.acheck(wrapped, "What is the capital of France?")
```

An object whose `__call__` is `async def` works:

```python
class MyAsyncClient:
    async def __call__(self, prompt: str) -> str:
        return await self._client.chat.completions.create(...)

result = await booth.acheck(MyAsyncClient(), "What is the capital of France?")
```

A synchronous callable whose `__call__` happens to return an awaitable is intentionally not treated as async. Use a real `async def`.

Passing a synchronous `call_fn` to `acheck()` raises `TypeError`, and passing an async one to `check()` does as well, rather than returning an unawaited coroutine.

---

## 6.2 Async `on_attempt`

With `acheck()`, `on_attempt` may be synchronous or asynchronous.

```python
async def log_attempt(index, attempt):
    await save_attempt(index, attempt)

class AsyncLogger:
    async def __call__(self, index, attempt):
        await self._flush_to_queue(index, attempt)

result = await booth.acheck(call_llm, "What is the capital of France?", on_attempt=AsyncLogger())
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
    evidence_threshold=DEFAULT_THRESHOLD,
)
```

Unlike `check()`, this function does not make an LLM call. Your application supplies the answer, the evidence, and a comparison function.

```python
result = booth.check_with_evidence(
    answer="Paris is the capital of France.",
    evidence=["France's capital city is Paris."],
    compare_fn=compare_answer_to_evidence,
)
```

As of `v0.5.1`, every non-`ACCEPTED` result also carries a specific `reason` code and a human-readable `detail` string (§7.8). `check()` and `acheck()` results always have `reason` and `detail` set to `None`.

---

## 7.1 `answer`

`answer` is the answer that you want to compare against the supplied evidence.

An empty, whitespace-only, or `None` answer is treated as missing. BOOTH returns:

```python
result.status == booth.UNCERTAIN
result.reason == booth.EMPTY_ANSWER
result.answer is None
result.detail == "answer was empty or whitespace-only"
```

and does not call `compare_fn`. (As of `v0.5.2`, `.answer` is `None` for the whitespace-only case as well as the empty-string case.)

Any other non-`str` value (an `int`, a `list`) is a caller mistake and raises `TypeError` immediately:

```python
booth.check_with_evidence(answer=123, evidence=["e"], compare_fn=my_compare_fn)
# TypeError: answer must be a str, got int
```

---

## 7.2 `evidence`

`evidence` is the evidence your application has already retrieved.

```python
evidence = [
    "Either party may terminate this Agreement upon ninety (90) days written notice."
]
```

BOOTH does not retrieve the evidence itself and does not determine whether it is correct.

An empty evidence sequence is rejected with `status == UNCERTAIN` and `reason == NO_EVIDENCE`.

As of `v0.5.5`, one-shot iterables (generators, iterators, `map`, `filter`) are accepted. BOOTH converts them to a list once, before the empty check, and `compare_fn` receives that list. As of `v0.5.6`, the type hint for `evidence` is `Iterable[str]`.

Anything with a length (a list, tuple, set, or numpy array) is passed to `compare_fn` as the same object. An exception raised inside your own generator while it is being converted propagates to the caller; it is not reported as `COMPARE_FAILED`.

---

## 7.3 `compare_fn`

`compare_fn` decides whether the answer agrees with the evidence.

```python
def compare_answer_to_evidence(answer, evidence):
    ...
```

It receives `answer` and `evidence`. The comparison logic belongs to your application. For example, a deliberately simple comparator:

```python
def compare_answer_to_evidence(answer, evidence):
    return "90" in answer
```

A real application would normally use a more appropriate comparison method.

`compare_fn` must be synchronous. An `async def compare_fn`, or a synchronous function that returns an un-awaited coroutine, is rejected with `TypeError` (as of `v0.4.9`). If your comparison needs to await something, resolve it before calling `check_with_evidence()`.

If `compare_fn` raises any other exception, BOOTH does not propagate it:

```python
result.status == booth.UNCERTAIN
result.reason == booth.COMPARE_FAILED
result.checker_failed is True
```

`result.detail` contains the exception type and a message truncated to 200 characters. See §7.8.

---

## 7.4 Boolean comparison

`compare_fn` may return a boolean. `True` produces `ACCEPTED`. `False` produces:

```python
result.status == booth.BLOCKED
result.reason == booth.EVIDENCE_DISAGREES
result.detail == "compare_fn returned False"
```

Boolean results are strict pass/fail. This includes `numpy.bool_`. `evidence_threshold` is not applied to boolean results, which is why the `detail` for a boolean `False` does not mention a threshold (as of `v0.5.2`).

---

## 7.5 Score comparison

`compare_fn` can instead return a score between `0.0` and `1.0`.

```python
def compare_answer_to_evidence(answer, evidence):
    return 0.87

result = booth.check_with_evidence(
    answer, evidence, compare_answer_to_evidence, evidence_threshold=0.8
)
# 0.87 >= 0.8  →  ACCEPTED
```

A score below the threshold produces `BLOCKED` with `reason == EVIDENCE_DISAGREES` and a `detail` such as `"score 0.62 below evidence_threshold 0.8"`.

A value that can be converted to a float, such as the string `"0.8"`, is accepted as a score. A return value that cannot be used as a score (non-numeric, or numeric but outside `[0.0, 1.0]`) is a different failure from a genuine disagreement:

```python
result.status == booth.UNCERTAIN
result.reason == booth.INVALID_SCORE
result.checker_failed is True
```

`evidence_threshold` must be a real number. A `str`, `None`, or `bool` raises `TypeError` immediately, and a value outside `[0.0, 1.0]` raises `ValueError`. `bool` is rejected deliberately: a threshold silently becoming "require a perfect score" or "accept anything" is far more likely to be a mistake than a choice.

```python
booth.check_with_evidence(answer, evidence, compare_fn, evidence_threshold="0.8")
# TypeError: evidence_threshold must be a real number, got str
```

---

## 7.6 Evidence result

The comparison score or boolean result is available through `result.evidence_agreement`. A boolean `True` is `1.0` and a boolean `False` is `0.0`. For `check()` and `acheck()` results this field is `None`.

---

## 7.7 What `check_with_evidence()` does not do

```text
does not make LLM calls
does not make network calls
does not retrieve evidence
does not retry
does not use a validator
does not use parse_fn
does not produce parsed LLM JSON
```

It is an evidence comparison gate.

---

## 7.8 `reason`, `detail`, and `checker_failed`

Before `v0.5.1`, `check_with_evidence()` returned `UNCERTAIN` for four unrelated causes with no way to tell them apart. `reason` fixes that.

`reason` is one of five fixed string codes, set only by `check_with_evidence()`:

| Code | Status | Meaning | `checker_failed` |
| --- | --- | --- | --- |
| `EMPTY_ANSWER` | `UNCERTAIN` | `answer` was empty, whitespace-only, or `None` | `False` |
| `NO_EVIDENCE` | `UNCERTAIN` | `evidence` was an empty sequence | `False` |
| `COMPARE_FAILED` | `UNCERTAIN` | `compare_fn` raised an exception | `True` |
| `INVALID_SCORE` | `UNCERTAIN` | `compare_fn` returned something unusable as a score | `True` |
| `EVIDENCE_DISAGREES` | `BLOCKED` | a real comparison ran, and the answer was rejected | `False` |

`result.detail` is free text with the specifics of the case. Treat `reason` as the thing to branch on programmatically and `detail` as the thing to log or show a human. The exact wording of `detail` is not part of the stable API.

`checker_failed` is a computed property:

```python
@property
def checker_failed(self) -> bool:
    return self.reason in (COMPARE_FAILED, INVALID_SCORE)
```

It is `True` only when the checker itself is at fault (a broken `compare_fn`, or one returning garbage), as opposed to incomplete input or a real disagreement. `checker_failed=True` usually means "alert an engineer", while the other reasons usually mean "this input or answer didn't check out". It does not detect a comparator that runs without error but has bad logic.

`check()` and `acheck()` results are unaffected: `reason` and `detail` are `None` and `checker_failed` is `False`.

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
from booth import EMPTY_ANSWER, NO_EVIDENCE, EVIDENCE_DISAGREES, COMPARE_FAILED, INVALID_SCORE
```

---

# 8. `BoothResult`

`check()`, `acheck()`, and `check_with_evidence()` return a `BoothResult`.

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
result.call_failed
result.method
result.parsed
result.reason
result.detail
result.checker_failed
```

---

## 8.1 `answer`

The resulting answer.

It may be `None` when no usable answer was obtained. This includes the case where the model returned a `dict` or `list` for `answer` instead of a scalar: BOOTH rejects that as a schema violation rather than stringifying it into a misleading result.

A numeric or boolean `answer` (for example `{"answer": 42}`) is not rejected. Since `v0.4.9` it is coerced to its string form (`"42"`), while `result.parsed` keeps the original value.

An empty or whitespace-only `answer` is rejected (as of `v0.4.9`) regardless of how high the reported confidence is. The one exception is an `AMBIGUOUS` attempt: the model may legitimately leave `answer` blank while `interpretations` carries the content.

On a rejected result (`AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`), `.answer` may still hold the last parsed answer, for debugging. Use `result.ok` or `unwrap()` before trusting it.

---

## 8.2 `status`

`status` is the final BOOTH outcome: `booth.ACCEPTED`, `booth.REPAIRED`, `booth.AMBIGUOUS`, `booth.UNCERTAIN`, or `booth.BLOCKED`.

- **`ACCEPTED`**: the answer passed the relevant checks on the first attempt.
- **`REPAIRED`**: an earlier attempt failed, but a retry produced an acceptable result.
- **`AMBIGUOUS`**: the model identified multiple interpretations of the question.
- **`UNCERTAIN`**: BOOTH could not obtain an acceptable result. From `check_with_evidence()`, check `result.reason` (§7.8). From `check()`, check `result.method` and `result.call_failed`.
- **`BLOCKED`**: the answer failed the evidence comparison performed by `check_with_evidence()`. `result.reason` is `EVIDENCE_DISAGREES`.

---

# 9. `BoothResult.ok`

`ok` is the convenient success check.

```python
if result.ok:
    print(result.answer)
```

`ok` is `True` only when `result.status` is `ACCEPTED` or `REPAIRED`.

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

It uses the same predicate as `.ok`, so the two cannot disagree. It does not change `.answer`, which stays populated on rejected results for debugging.

The benefit is ergonomic: `.answer` is typed `Optional[str]`, so a type checker forces `None` handling at every call site. `unwrap()` returns a plain `str` because rejection becomes an exception instead of a value you might forget to check.

### `BoothRejected`

`BoothRejected` carries the full `BoothResult` as `.result`, so nothing diagnostic is lost:

```python
try:
    answer = result.unwrap()
except booth.BoothRejected as e:
    print(e.result.status)     # e.g. "UNCERTAIN"
    print(e.result.method)     # e.g. "parse_failure"
    print(e.result.reason)     # e.g. "EMPTY_ANSWER", from check_with_evidence()
    print(e.result.attempts)   # full attempt history
```

The exception's message (`str(e)`) intentionally does not include the rejected answer text, because exception messages tend to end up in logs. Read the text explicitly from `e.result.answer` if you need it.

## 9.2 `BoothResult.unwrap_or()`

`unwrap_or(default)` behaves like `unwrap()` but returns `default` instead of raising:

```python
answer = result.unwrap_or("Sorry, I don't have a reliable answer for that.")
```

## 9.3 `BoothResult.checker_failed`

`checker_failed` is `True` only on a `check_with_evidence()` result whose `reason` is `COMPARE_FAILED` or `INVALID_SCORE`. It is always `False` on `check()` and `acheck()` results. See §7.8.

```python
if result.checker_failed:
    alert_engineering(result.detail)
```

---

# 10. `BoothResult.confidence`

For `check()` and `acheck()`, `confidence` is the model-reported confidence. For `check_with_evidence()` it is the comparison score when one is available.

---

# 11. `BoothResult.evidence_agreement`

The result produced by the evidence comparison. It is `None` for `check()` and `acheck()` results.

---

# 12. `BoothResult.attempts`

`attempts` contains every LLM attempt made during `check()` or `acheck()`, as `Attempt` objects.

```python
for attempt in result.attempts:
    print(attempt)
```

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
attempt.call_failed
```

`check_with_evidence()` results always have `attempts == []`. That is why `result.reason` and `result.detail` (§7.8) exist: they are the diagnostic surface for a path with no attempt history.

---

# 13. `Attempt`

`Attempt` represents one individual LLM attempt. It is useful when you need to inspect what happened across retries.

```python
for index, attempt in enumerate(result.attempts):
    print("Attempt:", index)
    print("Answer:", attempt.answer)
    print("Confidence:", attempt.confidence)
    print("Parsed:", attempt.parse_ok)
```

## `Attempt.raw_text`

The raw text returned by the model (or, for a raised `call_fn`, `"<ExceptionType>: <message>"`; for a non-string return, its `repr`).

## `Attempt.answer`

The normalized answer extracted from the parsed response.

## `Attempt.confidence`

The normalized confidence value for that attempt.

## `Attempt.parse_ok`

Whether BOOTH successfully parsed the attempt.

```python
if not attempt.parse_ok:
    print("The attempt failed to parse.")
```

A call whose `call_fn` succeeded but returned a non-string (for example `None`, a dictionary, or a list) is also recorded as a failed attempt rather than raising. Check `attempt.error` for the reason.

## `Attempt.error`

Contains parsing or other attempt-level error information when applicable.

As of `v0.4.9`, a parse failure always carries a specific, human-readable reason (for example `"'confidence' 17.0 is out of the [0.0, 1.0] range"` or `"'answer' was empty or whitespace-only"`). `call_fn` exceptions and non-string returns also populate it. When `parse_fn` is used, a parser exception is recorded as `parse_fn raised <ExceptionType>: <message>`, and a non-dict result as `parsed response was <type>, expected dict`.

## `Attempt.call_failed`

Added in `v0.5.4`. `True` when `call_fn` raised an exception, or returned something other than a string, so there was no response to parse.

```python
if attempt.call_failed:
    print("The call itself failed:", attempt.error)
```

A garbage response is not a call failure: `parse_ok` is `False` but `call_failed` is also `False`. When `call_failed` is `True`, `parse_ok` is always `False`. For the result-level flag, see §17.1.

## `Attempt.ambiguous`

Whether the attempt was identified as ambiguous.

## `Attempt.interpretations`

The interpretations detected for an ambiguous question.

## `Attempt.chosen_interpretation`

The interpretation selected by the model when applicable. Falsy-but-present values such as `0` or `""` are preserved (as strings), not discarded.

## `Attempt.passed_validation`

Whether the custom validator passed. When no validator was supplied, this is always `True`.

## `Attempt.validation_error`

The validation failure information when validation fails; `None` when no validator is supplied or validation succeeds.

## `Attempt.parsed`

The raw parsed object for that attempt, before BOOTH's own coercion. When `parse_fn` is used, this is the dictionary your parser returned. If parsing failed, `attempt.parsed` is `None`.

---

# 14. `BoothResult.n_attempts`

The number of attempts BOOTH performed. It is equivalent to `len(result.attempts)`. With `max_retries=2` the maximum is `3`.

---

# 15. `BoothResult.ambiguous`

A convenient indication of whether the result is ambiguous. Use it alongside `result.interpretations`.

```python
if result.ambiguous:
    print("The question has multiple interpretations.")
    print(result.interpretations)
```

---

# 16. `BoothResult.interpretations`

The interpretations detected for an ambiguous result.

```text
["Georgia the country", "Georgia the US state"]
```

---

# 17. `BoothResult.all_parse_failed`

Helps distinguish different kinds of `UNCERTAIN` results.

```python
if result.status == booth.UNCERTAIN:
    if result.all_parse_failed:
        print("No attempt produced a valid response format.")
```

If `all_parse_failed` is false, the model may have produced parseable responses that were rejected for another reason, such as validation or insufficient confidence.

This property is specific to `check()` and `acheck()` results. A `check_with_evidence()` result has no attempts, so use `result.reason` (§7.8) there.

---

## 17.1 `BoothResult.call_failed`

`call_failed` is a computed property added in `v0.5.4`. It is `True` when **every** attempt failed because `call_fn` itself failed: it raised an exception (a bad API key, a retired model name, a network error), or returned something other than a string.

```python
result = booth.check(call_llm, "What is the capital of France?")

if result.call_failed:
    alert_engineering(result.attempts[-1].error)
elif result.status == booth.UNCERTAIN:
    print("The model answered, but not acceptably:", result.method)
```

Before `v0.5.4`, a failed call looked exactly like a model that returned garbage: `UNCERTAIN`, `method == "parse_failure"`, `all_parse_failed == True`. Those values are unchanged, so existing code keeps working, but `call_failed` now separates the two cases. The error text is on `result.attempts[-1].error`, and `attempt.call_failed` (§13) says which individual attempts failed.

Like `all_parse_failed`, it looks at the whole history:

- If a call fails once and a retry succeeds, the result is `REPAIRED` and `result.call_failed` is `False`. The first attempt still has `call_failed == True`.
- If a model answers with low confidence and the retry call then fails, `result.call_failed` is `False`. Check the last attempt's `call_failed` in that case.

BOOTH cannot tell a temporary failure from a permanent one without knowing each provider's error types, so a 401 is retried like any other failure. If you expect configuration errors, check `result.call_failed` and stop, or pass `max_retries=0`.

A `parse_fn` failure is not a call failure. Always `False` on `check_with_evidence()` results.

---

# 18. `BoothResult.method`

`method` explains which BOOTH mechanism determined the result: `"ambiguity"`, `"evidence"`, `"parse_failure"`, `"validation"`, or `"confidence"`.

```python
if result.status == booth.UNCERTAIN:
    if result.method == "parse_failure":
        print("No attempt could be parsed.")
    elif result.method == "validation":
        print("The answer never passed validation.")
    elif result.method == "confidence":
        print("Confidence never reached the threshold.")
```

| Method | Meaning |
| --- | --- |
| `ambiguity` | The result was returned because of ambiguity |
| `evidence` | The result came from `check_with_evidence()` |
| `parse_failure` | Every attempt failed to parse (this includes failed `call_fn` calls and failed `parse_fn` results; see §17.1) |
| `validation` | The final determining failure was validation |
| `confidence` | The final determining failure was insufficient confidence |

`method` describes the determining mechanism, not the full history. For a `check()` or `acheck()` result, inspect `result.attempts`. For a `check_with_evidence()` result, inspect `result.reason` and `result.detail`.

---

# 19. `BoothResult.parsed`

`parsed` exposes the raw, uncoerced object returned by the model (or, when `parse_fn` is used, the dictionary your parser returned).

```python
result = booth.check(call_llm, "What's the refund window?")

print(result.answer)
print(result.confidence)
print(result.parsed)
```

BOOTH normalizes `answer` to `str`, `confidence` to `float`, and `interpretations` to `list[str]`, but `parsed` preserves the original values. If the model returns `{"answer": "30 days", "confidence": "0.95"}`, then `result.confidence` is `0.95` while `result.parsed["confidence"]` stays `"0.95"`. This is intentional.

## 19.1 Extra fields

Additional fields remain available through `parsed`:

```python
result.parsed.get("source")
```

BOOTH does not validate or sanitize these extra fields.

## 19.2 Which attempt supplies `parsed`?

For `ACCEPTED`, `REPAIRED`, and `AMBIGUOUS`, `parsed` comes from the winning attempt. For `UNCERTAIN` it comes from the last successfully parsed attempt, even if a later attempt failed to parse. If every attempt failed to parse, `result.parsed is None`. For `check_with_evidence()` it is always `None`.

---

# 20. `BoothResult.to_dict()`

`to_dict()` returns a plain dictionary containing the complete result.

```python
payload = result.to_dict()
```

It includes the normal fields and the computed properties `ok`, `method`, `all_parse_failed`, `call_failed`, `n_attempts`, and `checker_failed`. This matters because `dataclasses.asdict(result)` does not include computed properties.

```python
import json

payload = result.to_dict()
print(payload["ok"])
print(payload["method"])
json.dumps(payload)
```

`payload` always contains `"reason"` and `"detail"` (as of `v0.5.1`) and `"call_failed"` (as of `v0.5.4`), and each entry in `payload["attempts"]` is a plain dictionary that includes `call_failed`.

`to_dict()` is useful for logging, queues, monitoring, evaluation pipelines, and JSON serialization.

---

# 21. Status Constants

BOOTH exposes five status constants: `booth.ACCEPTED`, `booth.REPAIRED`, `booth.AMBIGUOUS`, `booth.UNCERTAIN`, `booth.BLOCKED`.

Use these constants instead of hard-coded strings.

```python
if result.status == booth.ACCEPTED:
    print(result.answer)
```

**Note (v0.4.8):** `ACCEPTED` was previously named `VERIFIED`, with no backward-compatible alias. `from booth import VERIFIED` raises `ImportError`, and the status string itself changed (`"VERIFIED"` to `"ACCEPTED"`).

## 21.1 Reason Codes

As of `v0.5.1`, BOOTH exposes five reason codes, set only on `check_with_evidence()` results (§7.8): `booth.EMPTY_ANSWER`, `booth.NO_EVIDENCE`, `booth.EVIDENCE_DISAGREES`, `booth.COMPARE_FAILED`, `booth.INVALID_SCORE`.

These narrow down why a `check_with_evidence()` result came back `UNCERTAIN` or `BLOCKED`; they do not replace `status`.

---

# 22. Default Constants

```python
booth.DEFAULT_THRESHOLD     # 0.7
booth.DEFAULT_MAX_RETRIES   # 1
```

Useful when building application configuration around BOOTH.

---

# 23. `CompareFn`

`CompareFn` is the public type for evidence comparison functions.

```python
from booth import CompareFn

def compare(answer, evidence):
    return 0.9

compare_fn: CompareFn = compare
```

It receives the answer and a sequence of evidence strings, and returns a boolean or a numeric score according to the `check_with_evidence()` contract. Because one-shot iterables are converted to a list first, `compare_fn` always receives a sequence.

---

# 24. `ValidatorFn`

`ValidatorFn` is the public type for custom validators.

```python
from booth import ValidatorFn

def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

my_validator: ValidatorFn = is_valid_order_id
```

Useful when type-checking application code that supplies validators to BOOTH.

## 24.1 `ParseFn`

`ParseFn` is the public type for a synchronous parser used with `parse_fn`, added in `v0.5.7`. It accepts the raw string returned by `call_fn` and returns a dictionary, or `None` when parsing fails.

```python
from typing import Optional
from booth import ParseFn

def parse_provider_response(raw: str) -> Optional[dict]:
    return {"answer": "Paris", "confidence": 0.9}

parser: ParseFn = parse_provider_response
```

---

# 25. Complete Synchronous Example

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
        return {"status": result.status, "interpretations": result.interpretations}

    if result.ok:
        return {"status": result.status, "answer": result.answer, "raw": result.parsed}

    return {"status": result.status, "method": result.method, "answer": None}
```

With a provider-native response format:

```python
result = booth.check(
    call_llm,
    prompt,
    parse_fn=parse_provider_response,
    max_retries=0,
)
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

```python
b_result = booth.check(call_llm, prompt)

if b_result.ok:
    evidence_result = booth.check_with_evidence(b_result.answer, evidence, compare_fn)
```

The two calls produce two independent `BoothResult` objects. BOOTH does not combine them; your application decides the final policy.

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
result = booth.check(call_llm, prompt, max_retries=2)

for index, attempt in enumerate(result.attempts):
    print("Attempt:", index)
    print("Raw:", attempt.raw_text)
    print("Answer:", attempt.answer)
    print("Confidence:", attempt.confidence)
    print("Parsed:", attempt.parse_ok)
    print("Call failed:", attempt.call_failed)
    print("Ambiguous:", attempt.ambiguous)
    print("Validation:", attempt.passed_validation)
    print("Error:", attempt.error)
    print()
```

For a `check_with_evidence()` result there is no attempt history; use `result.reason` and `result.detail` (§7.8).

---

# 29. Public API

The public package exports:

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
    ParseFn,
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

The three primary functions are `booth.check()`, `booth.acheck()`, and `booth.check_with_evidence()`.

The primary result and type objects are `booth.Attempt`, `booth.BoothResult`, `booth.BoothRejected`, `booth.CompareFn`, `booth.ValidatorFn`, and `booth.ParseFn`.

The status constants are `ACCEPTED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, and `BLOCKED`. The reason codes (`check_with_evidence()` results only) are `EMPTY_ANSWER`, `NO_EVIDENCE`, `EVIDENCE_DISAGREES`, `COMPARE_FAILED`, and `INVALID_SCORE`. The default configuration constants are `DEFAULT_THRESHOLD` and `DEFAULT_MAX_RETRIES`.

---

# 30. Quick Reference (v0.5.2 to v0.5.7)

## Functions

| Function | Purpose |
| --- | --- |
| `check()` | Run a synchronous LLM checkpoint |
| `acheck()` | Run an asynchronous LLM checkpoint |
| `check_with_evidence()` | Compare an existing answer against supplied evidence |

## Main types

| Type | Purpose |
| --- | --- |
| `Attempt` | Represents one LLM attempt |
| `BoothResult` | Represents the final result |
| `BoothRejected` | Raised by `unwrap()` on a non-ok result |
| `CompareFn` | Type for evidence comparison functions |
| `ValidatorFn` | Type for custom answer validators |
| `ParseFn` | Type for synchronous response parsers (v0.5.7) |

## Result statuses

| Status | Meaning |
| --- | --- |
| `ACCEPTED` | Accepted on the first attempt |
| `REPAIRED` | Accepted after a retry |
| `AMBIGUOUS` | Question has multiple detected interpretations |
| `UNCERTAIN` | No acceptable result was produced |
| `BLOCKED` | Evidence comparison failed |

## `check_with_evidence()` reason codes (v0.5.1+)

| Reason | Status | `checker_failed` |
| --- | --- | --- |
| `EMPTY_ANSWER` | `UNCERTAIN` | `False` |
| `NO_EVIDENCE` | `UNCERTAIN` | `False` |
| `COMPARE_FAILED` | `UNCERTAIN` | `True` |
| `INVALID_SCORE` | `UNCERTAIN` | `True` |
| `EVIDENCE_DISAGREES` | `BLOCKED` | `False` |

See §7.8 for the full breakdown.

## Entry-point argument validation

These arguments raise a clear, specific error at the call site, before any LLM call:

| Argument | Functions | Invalid raises |
| --- | --- | --- |
| `prompt` | `check()`, `acheck()` | `TypeError` if not `str` (v0.5.2) |
| `call_fn` | `check()`, `acheck()` | `TypeError` if not callable (v0.5.2); `check()` rejects an async one and `acheck()` a sync one |
| `threshold` | `check()`, `acheck()` | `ValueError` if outside `[0.0, 1.0]` |
| `max_retries` | `check()`, `acheck()` | `TypeError` if not `int`; `ValueError` if negative |
| `on_attempt` | `check()`, `acheck()` | `TypeError` if not callable (v0.5.3); `check()` also rejects an async one |
| `validator` | `check()`, `acheck()` | `TypeError` if not callable (v0.5.5) |
| `parse_fn` | `check()`, `acheck()` | `TypeError` if not callable or if `async def` (v0.5.7) |
| `answer` | `check_with_evidence()` | `TypeError` if not `str`/`None` (v0.4.9) |
| `evidence_threshold` | `check_with_evidence()` | `TypeError` if not a real number; `ValueError` if outside `[0.0, 1.0]` |

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
result.call_failed
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

Use these when you want a plain `str` back instead of handling `Optional[str]` at every call site (§9.1, §9.2).

## Result serialization

```python
result.to_dict()
```

---

# 31. The Core Mental Model

```text
check()
  │
  ├── call the LLM (call_fn returns a string)
  │
  ├── parse the response (default extraction, or parse_fn)
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
  └── same checkpoint process as check(), using asynchronous LLM calls
```

BOOTH provides the checkpoint and retry mechanics while leaving the LLM provider, evidence retrieval, comparison logic, and application-specific validation under your application's control.