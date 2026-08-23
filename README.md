# BOOTH

**A lightweight checkpoint layer for LLM outputs.**

BOOTH sits between your application and an LLM call and decides whether an answer should pass through, be reconsidered, be flagged as resting on an unstated assumption, or be marked uncertain.

The name comes from the idea of a **ticket booth, toll booth, or parking/payment booth**: a booth doesn't need to know everything about what is happening beyond it. It checks whether the required condition has been met before allowing something to pass.

BOOTH follows the same idea for LLM outputs.

> **BOOTH does not claim to know the truth. It checks whether an output meets a defined acceptance condition.**

---

## Current Status

**v0.2.0 — Path B only**

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

There is currently **no RAG, tool invocation, or independent evidence checking** in Path B.

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
Previous answer: "Lyon"
Previous confidence: 0.3

Reconsider carefully.
If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

If the reconsidered answer reaches the confidence threshold, BOOTH returns `REPAIRED`. If the model remains below the threshold after all allowed attempts, BOOTH returns `UNCERTAIN`.

---

## Why?

A normal LLM call looks like:

```python
answer = call_llm(prompt)
```

The application has to decide what to do with that answer, and has no way to know whether the question itself had more than one valid reading.

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

The application gets a structured result instead of having to implement the retry, parsing, confidence handling, ambiguity handling, and attempt tracking itself.

**Real example**, from testing against a live model:

> **Question:** "What's the best-selling book?"
>
> **Without BOOTH:** *"The best-selling book of all time is the Bible, with estimates of over 5 billion copies sold worldwide."* — stated as plain fact, no hint that the question is contested.
>
> **With BOOTH:** `status: AMBIGUOUS, confidence: 0.88`, answer: "The Bible", with four listed interpretations — worldwide including religious texts, best-selling *novel*, best-selling *non-religious* book, and best-selling book *this year*. Same underlying model, same underlying "best guess" answer — but only one of the two tells the user the question was contested at all.

---

## Installation

Not yet published to PyPI. Install directly from GitHub:

```bash
pip install git+https://github.com/Vedantgitbot/booth.git
```

Or clone and install locally (editable, so local edits take effect immediately):

```bash
git clone https://github.com/Vedantgitbot/booth.git
cd booth
pip install -e .
```

---

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

## Result Statuses

BOOTH currently exposes five statuses:

### `VERIFIED`

The question was not flagged ambiguous, and the **first attempt** met the configured confidence threshold.

```text
ambiguous = false
confidence = 0.91, threshold = 0.70

→ VERIFIED
```

`VERIFIED` means the output passed BOOTH's Path B acceptance condition. It does **not** mean that BOOTH independently proved the answer correct.

---

### `REPAIRED`

The question was not flagged ambiguous. The first attempt was below the threshold, but a later reconsideration reached the threshold.

```text
Attempt 1: answer = "Lyon", confidence = 0.30
        ↓ reconsider
Attempt 2: answer = "Paris", confidence = 0.92

→ REPAIRED
```

"Repaired" means **recovered through reconsideration**, not "checked against external evidence and proved correct."

---

### `AMBIGUOUS`

The model flagged the question as having more than one valid, meaningfully different interpretation — different named entities sharing a name, different metrics, different time periods, or similar. Returned **immediately, regardless of confidence**, and never retried, since reconsideration doesn't resolve a question that's ambiguous as asked.

```text
Question: "What is the capital of Georgia?"
ambiguous = true
interpretations = ["Georgia (US state) -> Atlanta", "Georgia (country) -> Tbilisi"]
chosen_interpretation = "Georgia (country) -> Tbilisi"
answer = "Tbilisi"
confidence = 0.93

→ AMBIGUOUS
```

`result.answer` still contains the model's best-guess answer under its silently-chosen interpretation, but `result.ok` is `False` for `AMBIGUOUS` — callers should check `result.interpretations` before showing the answer as if it were a settled fact.

**Known limitation:** ambiguity detection catches *structural* ambiguity (a term or name that admits multiple readings) reliably. It is weaker on *convention-based* ambiguity, where the split only exists because of a domain norm the model has to already know about — testing found this improves with the ordered-JSON schema but is not guaranteed to catch every case a domain expert would flag. See Non-Goals.

---

### `UNCERTAIN`

BOOTH could not obtain an answer that satisfied the acceptance condition. This can happen when every attempt remains below the confidence threshold, every model response is unparseable, or every call fails.

```text
Attempt 1 → confidence 0.40
Attempt 2 → confidence 0.51

→ UNCERTAIN
```

The caller can use this status to avoid silently presenting a low-confidence answer as if it were reliable.

---

### `BLOCKED`

Reserved for the broader BOOTH design and **not reachable from the current Path B implementation**. Exposed so applications can pattern-match against the complete BOOTH status vocabulary when Path A is eventually implemented.

---

## The Important Limitation

BOOTH's current Path B is **not a correctness guarantee**. It is a self-consistency and reconsideration mechanism, plus a self-assessed ambiguity check. The model is evaluating its own answer and its own question.

For example, a model could produce:

```json
{"ambiguous": false, "answer": "The Earth is flat.", "confidence": 0.99}
```

BOOTH would return `VERIFIED`, because the model's reported confidence satisfies the threshold and it wasn't flagged ambiguous. BOOTH has no independent evidence in Path B that could establish that the answer is actually true.

Therefore:

> **VERIFIED means "passed BOOTH's current acceptance condition," not "mathematically or factually proven correct."**
>
> **AMBIGUOUS means "the model recognized more than one valid reading," not "BOOTH has enumerated every possible reading."**

This distinction is fundamental to the project.

---

## Path A — Future Scope

A separate Path A is planned for situations where an existing retriever or tool can be invoked again and its output can be compared against the LLM's answer:

```text
Question → LLM answer → RAG / tool / evidence → BOOTH → compare → VERIFIED / REPAIRED / AMBIGUOUS / UNCERTAIN / BLOCKED
```

Path A is **not implemented in the current release**. It will have a different call shape from Path B because it needs access to a re-invocable retriever/tool rather than only a plain prompt string.

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

**`call_fn`** — `Callable[[str], str]`. Receives a prompt, returns the model's raw response. BOOTH does not manage your model provider or API credentials.

**`prompt`** — the original user/application prompt. BOOTH appends its confidence/ambiguity-reporting instructions internally.

**`threshold`** — minimum self-reported confidence required to accept an unambiguous answer. Default `0.7`. Must be between `0.0` and `1.0`. **Not independently calibrated** — validate against your own test set before trusting a specific value in production; see `examples/` for a way to log real (question, status, confidence) data.

**`max_retries`** — number of reconsideration attempts after the initial call, for low-confidence *unambiguous* answers. `max_retries=0` means one total call; `max_retries=2` allows up to three.

**`on_attempt`** — optional `Callable[[int, Attempt], Any]`, invoked after every attempt (including failed/unparseable ones), for logging, debugging, and calibration.

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
```

```python
if result.status == booth.AMBIGUOUS:
    print("This question has multiple readings:", result.interpretations)
elif result.ok:
    print(result.answer)
else:
    print("BOOTH could not verify an answer.")
```

---

## Why the Checkpoint Metaphor?

A ticket booth doesn't know whether the movie is good. A toll booth doesn't know where you're ultimately going. They check a **specific condition**.

BOOTH applies the same principle to AI systems: it does not know everything, it checks whether the required condition has been met. In Path B, that condition is currently:

```text
Is this question answerable as a single, unambiguous claim,
and does the model report confidence at or above the configured threshold?
```

In future evidence-based paths, the condition can become stronger: does the answer agree with the available evidence?

---

## Design Principles

1. **Don't silently pass through uncertainty or unstated ambiguity.** If the model can't clear the bar, say so — `UNCERTAIN` or `AMBIGUOUS`, not a confident-looking guess.
2. **Reconsider rather than blindly resample.** A retry should give the model an opportunity to examine its previous answer.
3. **Ask "is this even answerable as asked" before "how confident are you."** Field order in the schema forces this sequencing, not just the prompt wording.
4. **Don't pretend confidence is proof.** Self-reported confidence and self-reported ambiguity are useful signals, not independent evidence.
5. **Stay provider-agnostic.** BOOTH works above different LLM providers rather than locking applications to one API.
6. **Keep the core API small.** A checkpoint layer, not another full LLM framework.

---

## Current Non-Goals

BOOTH Path B does **not** currently:

- guarantee factual correctness
- independently verify claims against external evidence
- browse the web, perform RAG, or invoke external tools
- compare multiple independent models
- provide calibrated confidence probabilities (self-reported confidence is a signal, not a calibrated statistic — validate against your own data before trusting a threshold)
- reliably catch **convention-based** ambiguity that requires specific domain knowledge to recognize as a split (e.g. bestseller-list conventions excluding religious texts) — it is meaningfully better than no check, tested and confirmed working on **structural** ambiguity (shared names, competing metrics), but is not exhaustive
- replace application-specific safety or validation logic

Those may be addressed by future paths or integrations.

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
├── examples/
│   ├── ai.py
│   └── app.py
└── tests/
    └── test_core.py
```

```bash
pip install -e ".[dev]"
pytest
```

Tests use mock `call_fn` implementations so core BOOTH behavior can be tested without making real LLM API calls. See `examples/ai.py` and `examples/app.py` for a working end-to-end test against a live model (Groq), including a NiceGUI chat frontend that displays status, confidence, and interpretations per response.

---

## License

This is the official BOOTH repository — Vedant Brahmbhatt

MIT. See [`LICENSE`](LICENSE).