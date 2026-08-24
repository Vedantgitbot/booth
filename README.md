# BOOTH

**A lightweight checkpoint library for LLM outputs.**

BOOTH sits between your application and an LLM call and provides structured checkpoints for deciding whether an output should pass through, be reconsidered, be flagged as ambiguous, or be checked against evidence supplied by your application.

> **BOOTH does not claim to know the truth. It checks whether an output meets a defined acceptance condition.**

The name comes from the idea of a **ticket booth, toll booth, or parking/payment booth**: a booth doesn't need to know everything about what is happening beyond it. It checks whether the required condition has been met before allowing something to pass.

---

## Current Status

**v0.4.0**

BOOTH currently provides:

* ambiguity detection
* self-reported confidence checking
* reconsideration retries for low-confidence answers
* separate retry handling for unparseable model responses
* synchronous and asynchronous LLM checkpoint functions
* evidence-agreement checking against evidence supplied by the caller
* configurable confidence and evidence thresholds
* structured result objects
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

BOOTH then applies its configured acceptance rules to that response.

If the question is identified as ambiguous, BOOTH returns `AMBIGUOUS`.

If it is not ambiguous but the reported confidence is below the configured threshold, BOOTH can ask the model to reconsider its previous answer.

If the model reaches the threshold after reconsideration, the result is `REPAIRED`.

If BOOTH cannot obtain an acceptable result, it returns `UNCERTAIN`.

BOOTH also provides `check_with_evidence()` for applications that already have evidence from their own RAG, search, database, or tool pipeline.

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

Ambiguity takes priority over confidence. A highly confident answer can still be returned as `AMBIGUOUS` if the model identifies multiple valid readings.

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

A value of:

```python
True
```

means that every attempt failed to produce a valid BOOTH response.

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

Both APIs use the same decision logic. The difference is how the supplied LLM function is called.

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

The comparison function can return either:

```python
True
```

or:

```python
False
```

for a simple pass/fail comparison.

It can also return a float between `0.0` and `1.0`:

```python
0.87
```

When a float is returned, BOOTH compares it with:

```python
evidence_threshold
```

For example:

```python
result = booth.check_with_evidence(
    answer=answer,
    evidence=evidence,
    compare_fn=compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

A score of `0.87` passes.

A score of `0.62` does not.

Boolean comparison results are treated as strict pass/fail values. `evidence_threshold` is not applied to boolean results.

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

That means:

> The answer passed the supplied evidence comparison.

It does **not** mean:

> BOOTH independently established that the evidence is correct.

The quality, relevance, completeness, freshness, and correctness of retrieved evidence remain the responsibility of the application.

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
)
```

Checks an LLM response using ambiguity detection, confidence checking, and reconsideration.

#### `call_fn`

A synchronous function:

```python
Callable[[str], str]
```

It receives a prompt and returns the model's raw response.

#### `prompt`

The original application or user prompt.

#### `threshold`

Minimum self-reported confidence required to accept an unambiguous answer.

Default:

```python
0.7
```

Must be between `0.0` and `1.0`.

#### `max_retries`

Number of retries after the initial attempt.

Default:

```python
1
```

#### `on_attempt`

Optional callback invoked after each attempt.

---

### `booth.acheck()`

```python
await booth.acheck(
    call_fn,
    prompt,
    threshold=0.7,
    max_retries=1,
    on_attempt=None,
)
```

Asynchronous equivalent of `check()`.

The supplied `call_fn` must be asynchronous:

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

Checks an answer against caller-supplied evidence.

It:

* makes no LLM calls
* makes no network calls
* performs no retrieval
* performs no retries
* does not modify a previous `BoothResult`
* uses the caller's `compare_fn`

#### `answer`

The answer being checked.

#### `evidence`

A sequence of evidence strings already retrieved by the application.

#### `compare_fn`

A caller-supplied comparison function:

```python
Callable[[str, Sequence[str]], bool | float]
```

It receives:

```python
answer
evidence
```

and returns either a boolean or a score from `0.0` to `1.0`.

#### `evidence_threshold`

Minimum score required when `compare_fn` returns a float.

Default:

```python
0.7
```

It is separate from `check()`'s `threshold` because the two values represent different things.

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
```

### `answer`

The answer produced by the model or supplied to the evidence checker.

May be `None` when no usable answer exists.

### `status`

One of:

```text
VERIFIED
REPAIRED
AMBIGUOUS
UNCERTAIN
BLOCKED
```

### `confidence`

For normal LLM checks, this contains the model's self-reported confidence.

For evidence checks, it contains the comparison score when available.

### `evidence_agreement`

The comparison score produced by `check_with_evidence()`.

It is `None` for normal `check()` / `acheck()` results.

### `attempts`

The full history of LLM attempts made by `check()` or `acheck()`.

Evidence checks do not make attempts, so their attempt list is empty.

### `n_attempts`

Number of recorded attempts.

### `ok`

Returns:

```python
True
```

only for:

```text
VERIFIED
REPAIRED
```

It is `False` for:

```text
AMBIGUOUS
UNCERTAIN
BLOCKED
```

### `ambiguous`

Whether the model marked the question as ambiguous.

### `interpretations`

The interpretations reported when the model marks a question as ambiguous.

### `all_parse_failed`

Indicates that all LLM attempts failed to produce a parseable BOOTH response.

This is useful for distinguishing a formatting/integration problem from persistent model uncertainty.

---

## Result Statuses

### `VERIFIED`

The result passed BOOTH's acceptance condition on the relevant check.

For normal LLM checking, this means the answer was not marked ambiguous and met the confidence threshold on the initial attempt.

For evidence checking, this means the supplied comparison passed.

`VERIFIED` does **not** mean independently proven true.

---

### `REPAIRED`

The initial LLM answer did not meet the confidence requirement, but a reconsideration attempt produced an acceptable result.

---

### `AMBIGUOUS`

The model identified multiple valid interpretations of the question.

BOOTH returns this immediately rather than using a confidence retry to resolve it.

---

### `UNCERTAIN`

BOOTH could not obtain an acceptable result.

This can occur because:

* the model remained below the confidence threshold
* every response failed to parse
* the answer or evidence supplied to `check_with_evidence()` was empty
* the evidence comparison function raised an exception
* the evidence comparison function returned an invalid score

---

### `BLOCKED`

The supplied evidence comparison did not pass.

For example, a float comparison score below the configured `evidence_threshold` produces:

```text
BLOCKED
```

A boolean `False` from `compare_fn` also produces:

```text
BLOCKED
```

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
* replace application-specific validation or safety systems

BOOTH is a **checkpoint library**, not an LLM framework, search engine, RAG framework, or autonomous verification system.

---

## Current Limitations

### Self-reported confidence

Confidence in normal LLM checking comes from the model itself.

A model can report:

```json
{
  "confidence": 0.99
}
```

and still be wrong.

BOOTH does not independently calibrate that number.

---

### Self-reported ambiguity

Ambiguity detection also depends on the model recognizing the ambiguity.

BOOTH can detect useful structural ambiguities, but it cannot guarantee that every possible interpretation is identified.

A model can also mistake its own uncertainty for ambiguity.

---

### Evidence quality

Evidence checking is only as useful as the evidence and comparison function supplied by the application.

If the evidence is wrong, incomplete, outdated, or unrelated, BOOTH does not independently detect that.

Likewise, a weak `compare_fn` can produce a misleading result.

---

### No automatic retrieval

`check_with_evidence()` deliberately does not retrieve documents.

The application owns retrieval:

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

---

### No automatic reconciliation

`check_with_evidence()` is a standalone evidence checkpoint.

It does not automatically consume or modify the result of `check()` or `acheck()`.

If an application wants to use multiple BOOTH checks together, the application decides how those results should be combined.

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

The test suite covers the core checkpoint behavior, asynchronous API, parsing behavior, ambiguity handling, reconsideration, and evidence checking.

The evidence-checking tests include cases for:

* passing float scores
* failing float scores
* boolean comparison
* boolean `False` with a zero threshold
* empty answers
* empty evidence
* comparison exceptions
* invalid comparison scores
* non-numeric comparison results
* invalid evidence thresholds
* result-field behavior
* independent evidence thresholds

---

## Design Principles

1. **Keep the checkpoint small.** BOOTH should provide a reusable decision layer rather than become another full LLM framework.

2. **Make uncertainty explicit.** When an output does not meet the configured acceptance condition, return a structured status instead of silently passing it through.

3. **Treat ambiguity separately from confidence.** A confident answer can still be ambiguous if the question has multiple valid interpretations.

4. **Reconsider instead of blindly resampling.** Retries give the model an opportunity to examine its previous response.

5. **Keep evidence retrieval outside BOOTH.** Applications remain free to use their own RAG, search, database, or tool infrastructure.

6. **Do not pretend agreement is truth.** Agreement with an answer, confidence value, or retrieved evidence is not the same as independently proving the claim.

7. **Stay provider-agnostic.** BOOTH works with different LLM providers because the application supplies the model-calling function.

---

## License

This is the official BOOTH repository — Vedant Brahmbhatt

BOOTH is released under the MIT License.

See [`LICENSE`](LICENSE) for the full license text.
