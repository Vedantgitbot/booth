
````markdown
# BOOTH Tutorial

A concise guide to using BOOTH's current public API.

BOOTH is a lightweight checkpoint library for LLM outputs. It sits between your application and an LLM call and provides structured results for confidence, ambiguity, retries, and evidence agreement.

---

## 1. Install

```bash
pip install boothpy
````

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
# 0.4.0
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

Minimum model-reported confidence required to accept an unambiguous answer.

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

For a low-confidence answer, BOOTH asks the model to reconsider its previous response.

If the previous response could not be parsed, BOOTH instead asks the model to correct its response format.

### `on_attempt`

Optional callback called after every attempt:

```python
def log_attempt(index, attempt):
    print(
        index,
        attempt.confidence,
        attempt.parse_ok,
        attempt.ambiguous,
    )


result = booth.check(
    call_llm,
    "What is the capital of France?",
    on_attempt=log_attempt,
)
```

This is useful for logging, debugging, and evaluating model behavior.

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

Ambiguous results are not automatically retried because reconsidering the same question does not necessarily resolve the ambiguity.

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

---

## 6. `BoothResult`

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
```

### `answer`

The resulting answer.

It can be `None` when no usable answer was obtained.

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

For `check()` and `acheck()`, this is the model's reported confidence.

For `check_with_evidence()`, it contains the comparison score when one is available.

### `evidence_agreement`

The evidence comparison score produced by `check_with_evidence()`.

It is `None` for normal LLM checks.

### `attempts`

List of all LLM attempts.

Each attempt contains information such as:

```python
attempt.raw_text
attempt.answer
attempt.confidence
attempt.parse_ok
attempt.error
attempt.ambiguous
attempt.interpretations
```

### `n_attempts`

Number of attempts:

```python
len(result.attempts)
```

### `ok`

A convenient way to check whether the result passed:

```python
if result.ok:
    print(result.answer)
```

`ok` is `True` only for:

```text
VERIFIED
REPAIRED
```

### `all_parse_failed`

Useful for diagnosing `UNCERTAIN` results.

```python
if result.status == booth.UNCERTAIN:
    if result.all_parse_failed:
        print("No attempt produced a valid response format.")
    else:
        print("The model remained uncertain.")
```

---

## 7. Handling Results

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
    print("No acceptable result.")

elif result.status == booth.BLOCKED:
    print("Answer did not agree with the supplied evidence.")
```

---

## 8. Async Usage

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

The async function has the same behavior as `check()` but expects an async `call_fn`.

`on_attempt` can also be asynchronous when using `acheck()`.

---

## 9. Evidence Checking

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

```python
True
```

or:

```python
False
```

For a boolean result:

```text
True  -> VERIFIED
False -> BLOCKED
```

It can also return a score from `0.0` to `1.0`:

```python
def compare_answer_to_evidence(answer, evidence):
    return 0.87
```

The score is compared against `evidence_threshold`:

```python
result = booth.check_with_evidence(
    answer,
    evidence,
    compare_answer_to_evidence,
    evidence_threshold=0.8,
)
```

A score of `0.87` produces:

```text
VERIFIED
```

while a score below `0.8` produces:

```text
BLOCKED
```

Boolean results are always treated as strict pass/fail values; `evidence_threshold` is not applied to them.

### Important

`check_with_evidence()` does not retrieve or verify the evidence itself.

It:

* makes no LLM calls
* makes no network calls
* performs no retrieval
* performs no retries

The application is responsible for retrieving the evidence and deciding how evidence should be compared.

---

## 10. Complete Example

```python
import booth


def call_llm(prompt: str) -> str:
    # Connect this to your preferred LLM provider.
    return llm_client(prompt)


def ask(prompt: str):
    result = booth.check(
        call_llm,
        prompt,
        threshold=0.7,
        max_retries=1,
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
        }

    return {
        "status": result.status,
        "answer": None,
    }


print(ask("What is the capital of France?"))
```

---

## 11. Limitations

BOOTH is a checkpoint layer, not a guarantee of factual correctness.

In particular:

* model confidence is self-reported
* ambiguity detection depends on the model
* a confident model can still be wrong
* retries do not guarantee correction
* evidence checking only measures agreement with supplied evidence
* BOOTH does not verify whether the evidence itself is correct
* evidence retrieval is handled by the application
* the quality of `compare_fn` directly affects evidence-checking results
* `check_with_evidence()` does not automatically combine its result with a previous `check()` result
* each retry can increase LLM cost and latency

---

## 12. Current API

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

```

This version is much better suited to **`tutorials.md`**: it explains how to actually use the current API, while keeping the README as the place for the broader project description, design philosophy, limitations, and future plans.
```
 