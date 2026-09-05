# BOOTH

**A lightweight checkpoint library for LLM outputs.**

BOOTH sits between your application and an LLM call and provides structured checkpoints for deciding whether an output should pass through, be reconsidered, be flagged as ambiguous, be checked against a custom validation rule, or be checked against evidence supplied by your application.

> **BOOTH does not claim to know the truth. It checks whether an output meets a defined acceptance condition.**

The name comes from the idea of a **ticket booth, toll booth, or parking/payment booth**: a booth doesn't need to know everything about what is happening beyond it. It checks whether the required condition has been met before allowing something to pass.

---

## Current Status

**v0.4.5**

BOOTH currently provides:

* ambiguity detection
* self-reported confidence checking
* reconsideration retries for low-confidence answers
* separate retry handling for unparseable model responses
* an optional caller-supplied `validator` for custom pass/fail rules on `check()`/`acheck()`, with its own distinct retry prompt
* synchronous and asynchronous LLM checkpoint functions
* evidence-agreement checking against evidence supplied by the caller
* configurable confidence and evidence thresholds
* structured result objects, including `result.method` to identify which mechanism produced a result, and `result.parsed` to expose the model's raw JSON response
* attempt history
* explicit `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, and `BLOCKED` statuses

BOOTH is provider-agnostic. It does not require a particular LLM provider, retrieval system, vector database, or framework.

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

BOOTH asks the model to provide structured information about its response, including:

```json
{
  "ambiguous": false,
  "interpretations": [],
  "chosen_interpretation": null,
  "answer": "Paris",
  "confidence": 0.95
}
```

BOOTH then applies its configured acceptance rules to that response, in this order:

1. If the question is identified as ambiguous, BOOTH returns `AMBIGUOUS` immediately.
2. If a `validator` was supplied and the answer fails it, BOOTH asks the model to reconsider, showing it the specific validation failure.
3. If the reported confidence is below the configured threshold, BOOTH can ask the model to reconsider its previous answer.

If the model reaches the threshold (and passes validation, if supplied) after reconsideration, the result is `REPAIRED`.

If BOOTH cannot obtain an acceptable result, it returns `UNCERTAIN`.

BOOTH also provides `check_with_evidence()` for applications that already have evidence from their own RAG, search, database, or tool pipeline.

**On robustness to malformed model output:** every field BOOTH extracts from the model's JSON response is validated against its expected type before being trusted, not just parsed and used as-is. A model returning the JSON string `"false"` instead of the boolean `false` for `ambiguous`, or the boolean `true` instead of a number for `confidence`, is rejected and treated as an unparseable attempt rather than silently coerced into the wrong value — the same discipline BOOTH has always applied to an out-of-range confidence score, now applied consistently across every coerced field. See the [Changelog](CHANGELOG.md)'s `v0.4.4` entry for the specific cases this covers.

**On robustness in `check_with_evidence()`:** the same "recognize duck-typed booleans, don't silently miscategorize them" discipline that `validator` got in `v0.4.4` now also applies to `compare_fn`'s return value — a `numpy.bool_` result is treated as a strict pass/fail, not coerced through `float()` into a score, and this holds across numpy versions despite numpy 2.0 renaming the underlying scalar type. A whitespace-only `answer` is also now treated as empty input, the same as `""`. See the [Changelog](CHANGELOG.md)'s `v0.4.5` entry.

---

## Features

### Ambiguity detection

BOOTH asks the model to identify whether the question has multiple valid interpretations before accepting the answer.

For example:

```text
What is the capital of Georgia?
```

could refer to:

```text
Georgia (the country) -> Tbilisi
Georgia (the US state) -> Atlanta
```

BOOTH can return:

```text
AMBIGUOUS
```

with the detected interpretations available through:

```python
result.interpretations
```

Ambiguity takes priority over everything else BOOTH checks. A highly confident, validator-passing answer can still be returned as `AMBIGUOUS` if the model identifies multiple valid readings — and a `validator` is never even invoked on an ambiguous attempt.

---

### Confidence checking

BOOTH uses the model's reported confidence as an acceptance signal.

The default threshold is:

```python
0.7
```

You can configure it:

```python
result = booth.check(
    call_llm,
    prompt,
    threshold=0.8
)
```

The confidence value is **self-reported by the model**. BOOTH does not calibrate or independently validate that probability.

---

### Reconsideration retries

When an answer is not ambiguous but its confidence is below the configured threshold, BOOTH can ask the model to reconsider its previous answer.

For example:

```text
Previous answer: "Lyon"
Previous confidence: 0.3

Reconsider carefully. If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

If the reconsidered answer reaches the threshold, BOOTH returns:

```text
REPAIRED
```

You can control the number of retries:

```python
result = booth.check(
    call_llm,
    prompt,
    max_retries=2
)
```

`max_retries=0` means only the initial model call is made.

---

### Parse-failure handling

LLM responses do not always follow the requested format.

BOOTH handles parse failures separately from low-confidence answers.

When a response cannot be parsed, the retry prompt tells the model that its previous response failed to meet the required format rather than simply repeating the original request.

You can determine whether an `UNCERTAIN` result occurred because no response could ever be parsed:

```python
result.all_parse_failed
```

A value of `True` means that every attempt failed to produce a valid BOOTH response.

---

### Custom validation with `validator`

BOOTH can run a caller-supplied validation rule against each attempt's answer, in addition to (and checked separately from) ambiguity and confidence.

```python
def is_valid_order_id(answer: str) -> bool:
    return answer.strip().upper().startswith("ORD-")

result = booth.check(
    call_llm,
    "What is the order ID for this request?",
    validator=is_valid_order_id,
)
```

`validator` receives the attempt's answer and returns one of:

* `True` / `False` — a plain pass/fail. `False` produces a generic failure message.
* `(bool, str)` — pass/fail plus a specific reason, shown to the model verbatim on the retry prompt:

```python
def validate_amount(answer: str):
    if not answer.replace(".", "", 1).isdigit():
        return False, "The answer must be a plain numeric amount, e.g. 42.50"
    return True, ""

result = booth.check(call_llm, prompt, validator=validate_amount)
```

* `(bool, None)`, or the equivalent as a **list** rather than a tuple (`[bool, str]` / `[bool, None]`) — accepted with the identical contract as the tuple form above (0.4.4+). `return True, None` is a natural way to write "passed, no message needed," and `[passed, message]` is an easy habit to fall into; both previously triggered an "invalid return type" rejection even though the intent was clear. A `False` with no message gets a generic fallback message, same as bare `False`.
* `numpy.bool_` (and other duck-typed booleans) are accepted anywhere a plain `bool` is (0.4.4+), recognized by type identity rather than by importing `numpy` — BOOTH stays zero-dependency. This recognition works across numpy versions, including numpy >=2.0's renamed scalar type (0.4.5+).

**Ordering:** an attempt is only run through `validator` if it parsed successfully **and** was not flagged ambiguous — a question that's ambiguous as asked isn't something a validator should be judging, and there is nothing to validate if the response never parsed. A validation failure is checked *before* the confidence gate: an answer that fails your validator does not get a chance to pass purely on high self-reported confidence.

An exception raised inside `validator`, or a return value that isn't one of the accepted shapes above, is treated as a failed validation — it never propagates out of `check()`/`acheck()`.

`validator=None` (the default) is a true no-op: every code path this parameter introduces is unreachable if you never pass it, so existing calls are unaffected.

`validator` must be **synchronous**, for both `check()` and `acheck()`. If your validation logic needs to await something (an API call, a DB lookup), resolve it yourself first and pass a plain sync closure in.

The type alias for a validator function, `ValidatorFn`, is importable from the top-level package (`from booth import ValidatorFn`) for type-hinting your own validator functions.

---

### `result.method`

Tells you which of BOOTH's mechanisms actually determined a result, derived entirely from existing fields:

```python
result.method
# "ambiguity"     — status is AMBIGUOUS
# "evidence"      — result came from check_with_evidence()
# "parse_failure" — UNCERTAIN because every attempt failed to parse
# "validation"    — UNCERTAIN because the last attempt parsed fine
#                    and was confident enough, but failed your validator
# "confidence"    — the ordinary case: VERIFIED / REPAIRED, or
#                    UNCERTAIN from persistent low confidence on an
#                    attempt that did parse and did pass validation
```

This is most useful for `UNCERTAIN` results, where it distinguishes genuinely different problems that call for different fixes:

```python
if result.status == booth.UNCERTAIN:
    if result.method == "parse_failure":
        print("Model never produced a parseable response — check call_fn / prompt formatting.")
    elif result.method == "validation":
        print("Model was confident, but never satisfied the custom validator.")
    else:
        print("Model tried, but confidence never reached the threshold.")
```

`method` reflects the **last** attempt's determining factor for a mixed history (e.g. a parse failure followed by a validation failure reports `"validation"`), the same rule `all_parse_failed` already follows — it is not a full history of every attempt's outcome.

---

### `result.parsed`

Exposes the model's **raw JSON response object**, exactly as returned — before any of BOOTH's own coercion (`str(answer)`, `float(confidence)`, forcing `interpretations` into a list of strings, and so on).

```python
result = booth.check(call_llm, "What is the order ID for this request?")

result.answer         # BOOTH's normalized answer, e.g. "ORD-4471"
result.parsed          # the raw dict the model returned, unmodified
```

This is a **transparency layer, not a second validation layer** — BOOTH already decided `answer`/`confidence`/`ambiguous` from this same object; `parsed` exists so you can see exactly what the model said, including fields BOOTH itself doesn't use:

```python
def call_llm(prompt: str) -> str:
    # imagine the model, prompted to also include a source field,
    # returns:
    # {"answer": "30 days", "confidence": "0.95", "ambiguous": false,
    #  "source_document": "policy.pdf"}
    ...

result = booth.check(call_llm, prompt)

result.confidence             # 0.95 (float — BOOTH coerced it)
result.parsed["confidence"]   # "0.95" (str — the raw value, untouched)
result.parsed["source_document"]  # "policy.pdf" — a field BOOTH never asked for or uses
```

That type divergence between `result.confidence` and `result.parsed["confidence"]` is deliberate, not a bug — `parsed` is meant to show you precisely what came back, even where BOOTH normalized it for its own use.

`parsed` reflects the attempt that determined the result: the winning attempt for `VERIFIED`/`REPAIRED`/`AMBIGUOUS`, the last *successfully parsed* attempt for `UNCERTAIN`, or `None` if no attempt ever parsed. `check_with_evidence()` results always have `parsed=None` — there is no LLM JSON parse involved on that path at all.

---

### Synchronous and asynchronous APIs

BOOTH provides both:

```python
booth.check()
```

and:

```python
await booth.acheck()
```

The synchronous version accepts:

```python
Callable[[str], str]
```

The asynchronous version accepts:

```python
Callable[[str], Awaitable[str]]
```

Example:

```python
import asyncio
import booth


async def call_llm(prompt: str) -> str:
    response = await async_client(...)
    return response


async def main():
    result = await booth.acheck(
        call_llm,
        "What is the capital of France?"
    )

    if result.ok:
        print(result.answer)


asyncio.run(main())
```

Both APIs use the same decision logic, including `validator` and `parsed`. The difference is how the supplied LLM function is called.

---

### Evidence agreement checking

BOOTH also provides:

```python
booth.check_with_evidence()
```

This checks whether an answer agrees with evidence that **your application has already retrieved**.

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

The comparison function belongs to the caller:

```python
def compare_answer_to_evidence(answer, evidence):
    ...
```

BOOTH does not choose a retrieval system or comparison algorithm for you.

The comparison function can return either `True`/`False` for a simple pass/fail comparison, or a float between `0.0` and `1.0`:

```python
0.87
```

When a float is returned, BOOTH compares it with `evidence_threshold`:

```python
result = booth.check_with_evidence(
    answer=answer,
    evidence=evidence,
    compare_fn=compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

A score of `0.87` passes. A score of `0.62` does not.

Boolean comparison results are treated as strict pass/fail values. `evidence_threshold` is not applied to boolean results. This includes `numpy.bool_` and other duck-typed booleans (0.4.5+) — a `compare_fn` written with numpy or pandas is treated identically to one that returns a plain Python `bool`, regardless of numpy version.

An `answer` that is empty or made up entirely of whitespace is treated as missing input: `check_with_evidence()` returns `UNCERTAIN` without ever calling `compare_fn` (0.4.5+; previously only a fully empty string was caught, so a whitespace-only string like `" "` slipped through and reached `compare_fn`).

`check_with_evidence()` has no `validator` concept, and its results always have `parsed=None` — it is a standalone, single-purpose comparison gate, untouched by either the `validator` or `parsed` additions.

---

## Important: What Evidence Checking Means

`check_with_evidence()` checks **agreement with the evidence supplied to it**.

It does not establish that the evidence itself is true.

For example, if your application retrieves an incorrect document:

```text
Digital downloads are never eligible for refunds.
```

and your comparison function determines that the answer agrees with that document, BOOTH can return:

```text
VERIFIED
```

That means the answer passed the supplied evidence comparison. It does **not** mean BOOTH independently established that the evidence is correct.

The quality, relevance, completeness, freshness, and correctness of retrieved evidence remain the responsibility of the application. This applies with equal force when evidence is baked into a prompt as RAG context and then separately checked — the model can produce a highly confident, unambiguous, evidence-agreeing answer that is still simply wrong, if the retrieved evidence itself was wrong. Neither `check()`'s confidence check nor `check_with_evidence()`'s agreement check can catch that; only the quality of retrieval can.

Note that this responsibility covers the *content* of the evidence, not how BOOTH interprets your `compare_fn`'s return value — the latter is BOOTH's job, and is what the `v0.4.5` fixes address. A list of blank or empty-but-present evidence strings is still a retrieval-quality question for your application to decide how to handle; BOOTH does not filter or judge evidence content.

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

Checks an LLM response using ambiguity detection, confidence checking, reconsideration, and (if supplied) a custom validator.

#### `call_fn`

A synchronous function, `Callable[[str], str]`, that receives a prompt and returns the model's raw response.

#### `prompt`

The original application or user prompt.

#### `threshold`

Minimum self-reported confidence required to accept an unambiguous, validator-passing answer. Default `0.7`. Must be between `0.0` and `1.0`.

#### `max_retries`

Number of retries after the initial attempt. Default `1`.

#### `on_attempt`

Optional callback invoked after each attempt.

#### `validator` (keyword-only, 0.4.2+)

Optional `ValidatorFn` — `Callable[[str], bool | tuple[bool, str]]`. Runs on an attempt's answer only if that attempt parsed successfully and was not ambiguous. See [Custom validation with `validator`](#custom-validation-with-validator) above for the full accepted-shape contract (widened in 0.4.4 to also accept `(bool, None)`, list forms, and `numpy.bool_`; the `numpy.bool_` recognition was made cross-version-safe in 0.4.5). Must be synchronous. Default `None` — a true no-op.

---

### `booth.acheck()`

```python
await booth.acheck(
    call_fn,
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,
    *,
    validator=None,
)
```

Asynchronous equivalent of `check()`, including full `validator` support (still required to be synchronous itself). The supplied `call_fn` must be asynchronous:

```python
async def call_llm(prompt: str) -> str:
    ...
```

---

### `booth.check_with_evidence()`

```python
booth.check_with_evidence(
    answer,
    evidence,
    compare_fn,
    evidence_threshold=0.7,
)
```

Checks an answer against caller-supplied evidence. It:

* makes no LLM calls
* makes no network calls
* performs no retrieval
* performs no retries
* does not modify a previous `BoothResult`
* has no `validator` parameter — it is a standalone comparison gate
* always returns `parsed=None` — there is no LLM JSON response involved
* uses the caller's `compare_fn`

#### `answer`

The answer being checked. Treated as missing (returns `UNCERTAIN` without calling `compare_fn`) if it's empty or entirely whitespace (0.4.5+).

#### `evidence`

A sequence of evidence strings already retrieved by the application.

#### `compare_fn`

A caller-supplied comparison function, `Callable[[str, Sequence[str]], bool | float]`. Receives `answer` and `evidence`, returns either a boolean (including `numpy.bool_`, recognized across numpy versions as of 0.4.5) or a score from `0.0` to `1.0`.

#### `evidence_threshold`

Minimum score required when `compare_fn` returns a float. Default `0.7`. Separate from `check()`'s `threshold` because the two values represent different things. Never applied to a boolean-shaped `compare_fn` result, native or `numpy.bool_`.

---

## Result Object

BOOTH returns a `BoothResult`.

Important fields include:

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

The answer produced by the model or supplied to the evidence checker. May be `None` when no usable answer exists.

### `status`

One of `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`.

### `confidence`

For normal LLM checks, the model's self-reported confidence. For evidence checks, the comparison score when available.

### `evidence_agreement`

The comparison score produced by `check_with_evidence()`. `None` for normal `check()` / `acheck()` results.

### `attempts`

The full history of LLM attempts made by `check()` or `acheck()`, each including per-attempt `passed_validation` / `validation_error` (always `True` / `None` if no `validator` was supplied) and `parsed` (the raw JSON object for that specific attempt, `None` if it failed to parse). Evidence checks do not make attempts, so their attempt list is empty.

### `n_attempts`

Number of recorded attempts.

### `ok`

`True` only for `VERIFIED` / `REPAIRED`. `False` for `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`.

### `ambiguous`

Whether the model marked the question as ambiguous.

### `interpretations`

The interpretations reported when the model marks a question as ambiguous.

### `all_parse_failed`

`True` if every LLM attempt failed to produce a parseable BOOTH response. Useful for distinguishing a formatting/integration problem from persistent model uncertainty or validation failure.

### `method` (0.4.2+)

Which mechanism produced the result — `"ambiguity"`, `"evidence"`, `"parse_failure"`, `"validation"`, or `"confidence"`. See [`result.method`](#resultmethod) above.

### `parsed` (0.4.3+)

The model's raw, uncoerced JSON response object. See [`result.parsed`](#resultparsed) above.

---

## Result Statuses

### `VERIFIED`

The result passed BOOTH's acceptance condition on the relevant check. For normal LLM checking, the answer was not ambiguous, passed validation (if supplied), and met the confidence threshold on the initial attempt. For evidence checking, the supplied comparison passed. `VERIFIED` does **not** mean independently proven true.

### `REPAIRED`

The initial LLM answer did not meet the confidence or validation requirement, but a reconsideration attempt produced an acceptable result.

### `AMBIGUOUS`

The model identified multiple valid interpretations of the question. BOOTH returns this immediately rather than using a confidence retry or a validator to resolve it.

### `UNCERTAIN`

BOOTH could not obtain an acceptable result. This can occur because:

* the model remained below the confidence threshold
* every response failed to parse
* an answer that did parse and was confident enough still failed the supplied `validator` on every attempt
* the `answer` or `evidence` supplied to `check_with_evidence()` was empty, or `answer` was whitespace-only (0.4.5+)
* the evidence comparison function raised an exception
* the evidence comparison function returned an invalid score

Check `result.method` to tell these apart.

### `BLOCKED`

The supplied evidence comparison did not pass — a float score below `evidence_threshold`, or a boolean `False` (native or `numpy.bool_`) from `compare_fn`.

---

## What BOOTH Does Not Do

BOOTH currently does **not**:

* guarantee factual correctness
* independently establish truth
* automatically browse the web
* automatically perform RAG
* automatically retrieve evidence
* automatically choose a vector database
* automatically choose an evidence-comparison method
* retry evidence retrieval
* manage a tool-calling loop
* compare multiple independent LLMs
* provide calibrated confidence probabilities
* guarantee that retrieved evidence is correct, complete, relevant, or current
* filter, deduplicate, or otherwise judge the quality of `evidence` content — including blank or empty-but-present entries — beyond checking that the sequence itself isn't empty
* guarantee that a custom `validator` is itself correct — a validator can pass a wrong answer or reject a correct one, same as any other application-supplied rule
* validate or enforce a schema on `result.parsed` — it is exposed as-is, entirely unvalidated
* replace application-specific validation or safety systems (though `validator` gives you a documented hook to plug your own logic into BOOTH's retry loop rather than reimplementing that loop yourself)

BOOTH is a **checkpoint library**, not an LLM framework, search engine, RAG framework, or autonomous verification system.

---

## Current Limitations

### Self-reported confidence

A model can report `{"confidence": 0.99}` and still be wrong. BOOTH does not independently calibrate that number.

### Self-reported ambiguity

Ambiguity detection depends on the model recognizing the ambiguity. BOOTH can detect useful structural ambiguities, but it cannot guarantee every possible interpretation is identified. A model can also mistake its own uncertainty for ambiguity.

### Custom validator correctness

`validator` is exactly as reliable as the logic you give it. BOOTH enforces that a validator's decision is respected consistently in the retry loop — it does not, and cannot, check whether the validator's own logic is actually correct for your use case.

### `result.parsed` is unvalidated

`result.parsed` is the model's raw JSON object, exposed as-is. BOOTH does not validate its shape, enforce a schema on it, or guarantee any field beyond the five it extracts for itself (`answer`, `confidence`, `ambiguous`, `interpretations`, `chosen_interpretation`) is present or well-typed. Reading extra fields from `parsed` is entirely the caller's responsibility, including handling missing keys or unexpected types.

### Evidence quality

Evidence checking is only as useful as the evidence and comparison function supplied by the application. If the evidence is wrong, incomplete, outdated, unrelated, or made up of blank/near-empty entries, BOOTH does not independently detect or filter that — only a fully empty `evidence` sequence is rejected. Likewise, a weak `compare_fn` can produce a misleading result. This includes the case where retrieved evidence is baked into the model's own prompt as RAG context — a wrong document can make the model's answer both more *confident* and more evidence-*consistent*, without becoming more correct.

### No automatic retrieval

`check_with_evidence()` deliberately does not retrieve documents. The application owns retrieval:

```text
Application
    ↓
Retrieve evidence
    ↓
BOOTH.check_with_evidence()
    ↓
VERIFIED / BLOCKED / UNCERTAIN
```

This keeps BOOTH small and provider-agnostic.

### No automatic reconciliation

`check_with_evidence()` is a standalone evidence checkpoint. It does not automatically consume or modify the result of `check()` or `acheck()`. If an application wants to use multiple BOOTH checks together — including building a reconsideration loop that runs `check()` again after a `BLOCKED` evidence result — the application decides how those results should be combined and how many extra attempts that composition is allowed to cost. BOOTH's own `max_retries` only bounds a single `check()`/`acheck()` call; it has no visibility into, or control over, retries you build on top across multiple calls.

For example:

```python
b_result = booth.check(call_llm, prompt)

if b_result.ok:
    a_result = booth.check_with_evidence(
        b_result.answer,
        evidence,
        compare_fn,
    )

    if a_result.ok:
        print(a_result.answer)
```

The composition logic remains under application control.

---

## Future Plans

Future BOOTH development may explore:

* stronger evidence adequacy checks
* better handling of evidence completeness
* improved detection of convention-based ambiguity
* methods for distinguishing genuine ambiguity from model uncertainty
* additional evidence-comparison strategies
* richer composition of multiple checkpoint results
* better evaluation and calibration tooling
* additional integrations with retrieval and tool systems
* an optional, lightweight structured-schema gate on top of `result.parsed` — deferred deliberately until there's a clear, minimal shape for it, rather than reaching for a general schema/validation dependency

These are future directions, not capabilities currently guaranteed by the library.

---

## Installation

```bash
pip install boothpy
```

BOOTH is also installable directly from GitHub:

```bash
pip install git+https://github.com/Vedantgitbot/booth.git
```

---

## Development

Clone the repository and install the development dependencies:

```bash
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest
```

The test suite covers the core checkpoint behavior, asynchronous API, parsing behavior, ambiguity handling, reconsideration, custom validation, evidence checking, raw-response exposure via `result.parsed`, a dedicated regression suite for the `v0.4.4` bugfix batch, and a dedicated regression suite for the `v0.4.5` bugfix batch. CI runs the full suite on push/PR across Python 3.9–3.12.

The `v0.4.4` regression tests specifically verify: a JSON string `"false"` for `ambiguous` is not misread as `True`; a JSON boolean for `confidence` is rejected rather than silently accepted as `1.0`/`0.0`; `ValidatorFn` is importable from the top-level package; a falsy-but-present `chosen_interpretation` (`0`, `""`) is preserved rather than discarded to `None`; `numpy.bool_`-shaped validator returns are accepted; `(bool, None)` and list-shaped validator returns are accepted while genuinely malformed shapes are still rejected; confidence exactly equal to `threshold` passes on both `check()` and `acheck()`; list-wrapped JSON (`[{...}]`) still recovers via the parsing fallback; and the previously-unverified nested-brace edge case's actual behavior is now locked in by a test rather than assumed.

The `v0.4.5` regression tests specifically verify: a `numpy.bool_(False)` result from `compare_fn` produces `BLOCKED`, not `VERIFIED`, at `evidence_threshold=0.0`; the shared boolish-detection helper recognizes numpy's boolean scalar type under both its pre-2.0 and post-2.0 `__name__` (`"bool_"` and `"bool"`), since numpy 2.0 renamed the type and the original 0.4.4 helper only matched the old name; a `numpy.bool_` result from `compare_fn` is never compared against `evidence_threshold`, matching native-`bool` behavior; and a whitespace-only `answer` returns `UNCERTAIN` without `compare_fn` ever being invoked.

---

## Design Principles

1. **Keep the checkpoint small.** BOOTH should provide a reusable decision layer rather than become another full LLM framework.
2. **Make uncertainty explicit.** When an output does not meet the configured acceptance condition, return a structured status instead of silently passing it through.
3. **Treat ambiguity, validation, and confidence as separate, ordered checks.** A confident, validator-passing answer can still be ambiguous; a confident answer can still fail a caller's own validation rule before confidence is ever consulted.
4. **Reconsider instead of blindly resampling.** Retries give the model an opportunity to examine its previous response — and the reason it failed (parse failure, validation failure, or low confidence) determines what the model is actually shown.
5. **Expose, don't reinterpret.** `result.parsed` is a transparency layer over data BOOTH already has, not a second parser or validator — it shows the model's raw response rather than deciding what it should mean.
6. **Reject invalid data, don't silently coerce it.** An out-of-range confidence, a boolean masquerading as a confidence score, or an unrecognized value for `ambiguous` are all treated as reasons to reject the attempt — never guessed at or silently reinterpreted into something that happens not to crash. Applied consistently across every coerced field as of `v0.4.4`, and applied to `check_with_evidence()`'s `compare_fn` return value as of `v0.4.5`.
7. **Keep evidence retrieval outside BOOTH.** Applications remain free to use their own RAG, search, database, or tool infrastructure. This includes evidence *content* quality — BOOTH checks agreement and rejects malformed comparison results, but does not judge or filter the evidence itself.
8. **Do not pretend agreement is truth.** Agreement with an answer, confidence value, custom validator, or retrieved evidence is not the same as independently proving the claim.
9. **Stay provider-agnostic.** BOOTH works with different LLM providers because the application supplies the model-calling function.
10. **Fix confirmed bugs, not plausible-sounding ones.** Every fix in this project starts from a reproduced failure, not an intuition about what "seems like it could be a problem." A change that would only guard against a hypothetical, undemonstrated failure mode is deliberately left out of a release, even when it pattern-matches a fix that was just made elsewhere.

---

## License

This is the official BOOTH repository — Vedant Brahmbhatt

BOOTH is released under the MIT License.

See [`LICENSE`](LICENSE) for the full license text.