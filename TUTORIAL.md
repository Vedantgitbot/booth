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

Passing an asynchronous callback to `check()` raises `TypeError`.

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
result.status == booth.VERIFIED
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
```

and does not call `compare_fn`.

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

is rejected.

The content of the evidence is otherwise the application's responsibility.

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

---

## 7.4 Boolean comparison

`compare_fn` may return a boolean:

```python
True
```

produces:

```python
VERIFIED
```

while:

```python
False
```

produces:

```python
BLOCKED
```

Boolean results are treated as strict pass/fail results.

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
result.status == booth.VERIFIED
```

because:

```text
0.87 >= 0.8
```

A score below the threshold produces:

```python
BLOCKED
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

when no usable answer was obtained.

---

## 8.2 `status`

`status` tells you the final BOOTH outcome.

Possible values are:

```python
booth.VERIFIED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

### `VERIFIED`

The answer passed the relevant checks on the successful attempt.

### `REPAIRED`

An earlier attempt failed, but a retry produced an acceptable result.

### `AMBIGUOUS`

The model identified multiple interpretations of the question.

### `UNCERTAIN`

BOOTH could not obtain an acceptable result.

### `BLOCKED`

The answer failed the evidence comparison performed by `check_with_evidence()`.

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
    booth.VERIFIED,
    booth.REPAIRED,
)
```

For other statuses it is `False`.

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

---

## `Attempt.error`

Contains parsing or other attempt-level error information when applicable.

```python
print(attempt.error)
```

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

For the complete history, inspect:

```python
result.attempts
```

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
VERIFIED
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
```

This is important because:

```python
dataclasses.asdict(result)
```

does not automatically include properties such as `ok` and `method`.

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
booth.VERIFIED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

Use these constants instead of relying on hard-coded status strings.

Example:

```python
if result.status == booth.VERIFIED:
    print(result.answer)
```

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

---

# 29. Public API

The public package exports the following:

```python
from booth import (
    Attempt,
    BoothResult,
    check,
    acheck,
    check_with_evidence,
    CompareFn,
    ValidatorFn,
    VERIFIED,
    REPAIRED,
    AMBIGUOUS,
    BLOCKED,
    UNCERTAIN,
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
booth.CompareFn
booth.ValidatorFn
```

The status constants are:

```python
booth.VERIFIED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
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

| Type          | Purpose                                |
| ------------- | -------------------------------------- |
| `Attempt`     | Represents one LLM attempt             |
| `BoothResult` | Represents the final result            |
| `CompareFn`   | Type for evidence comparison functions |
| `ValidatorFn` | Type for custom answer validators      |

## Result statuses

| Status      | Meaning                                        |
| ----------- | ---------------------------------------------- |
| `VERIFIED`  | Accepted on the current attempt                |
| `REPAIRED`  | Accepted after a retry                         |
| `AMBIGUOUS` | Question has multiple detected interpretations |
| `UNCERTAIN` | No acceptable result was produced              |
| `BLOCKED`   | Evidence comparison failed                     |

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
```

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
  ├── receive answer
  ├── receive evidence
  ├── call compare_fn
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
