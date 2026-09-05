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
# 0.4.5
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

This is useful for logging, debugging, and evaluating model behavior.

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

BOOTH is a checkpoint layer, not a guarantee of factual correctness.

In particular:

* model confidence is self-reported
* ambiguity detection depends on the model
* a confident model can still be wrong
* retries do not guarantee correction
* a `validator` is only as correct as the logic you give it — BOOTH enforces it consistently, but cannot judge whether the rule itself is right for your use case
* `result.parsed` exposes the model's raw output exactly as sent — BOOTH does not validate or sanitize any extra fields it contains
* evidence checking only measures agreement with supplied evidence
* BOOTH does not verify whether the evidence itself is correct — including when that evidence was fed to the model as RAG context before the model answered
* evidence retrieval is handled by the application, including filtering out low-quality entries such as blank or near-empty evidence strings — BOOTH only rejects a fully empty evidence sequence
* the quality of `compare_fn` directly affects evidence-checking results
* `check_with_evidence()` does not automatically combine its result with a previous `check()` result, and has no `validator` or `parsed` of its own
* each retry can increase LLM cost and latency — this applies to validator-driven retries the same as confidence-driven ones

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

Status constants:

```python
booth.VERIFIED
booth.REPAIRED
booth.AMBIGUOUS
booth.UNCERTAIN
booth.BLOCKED
```

BOOTH is intentionally small and provider-agnostic, leaving LLM providers, retrieval systems, evidence sources, and application-specific validation under the application's control.