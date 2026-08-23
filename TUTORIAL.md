# BOOTH Tutorial

This walks through everything in BOOTH's public API, then shows how to wire it into a real application from scratch. If you just want the shape of the API, see the README. This is the "explain every piece, step by step" version.

---

## 1. Install

```bash
pip install git+https://github.com/Vedantgitbot/booth.git
```

or, for local development against a cloned copy:

```bash
git clone https://github.com/Vedantgitbot/booth.git
cd booth
pip install -e .
```

Confirm it's there:

```python
import booth
print(booth.__version__)   # 0.2.0
```

---

## 2. The one function you need: `booth.check()`

```python
def check(
    call_fn: Callable[[str], str],
    prompt: str,
    threshold: float = 0.7,
    max_retries: int = 1,
    on_attempt: Optional[Callable[[int, "Attempt"], Any]] = None,
) -> "BoothResult":
    ...
```

That's the entire surface area of BOOTH v0.2.0. Everything else in this tutorial is either an argument to this function or a field on what it returns.

### `call_fn` — the thing BOOTH wraps

This is **your** function, not BOOTH's. BOOTH doesn't know about OpenAI, Anthropic, Groq, or any specific provider — it only knows how to call a plain Python function that takes a prompt string and returns a text string.

```python
def call_fn(prompt: str) -> str:
    # do whatever you'd normally do to call your model
    response = some_client.chat.completions.create(
        model="...",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
```

**Why a plain function instead of a client object?** Because it keeps BOOTH provider-agnostic. Whatever quirks your provider's SDK has (message format, auth, streaming, etc.) live entirely inside `call_fn` — BOOTH never needs to know about them. It just needs "string in, string out."

**Important:** `call_fn` will be called **more than once** if the first attempt is low-confidence or errors out (up to `max_retries + 1` times total). BOOTH appends its own confidence/ambiguity-reporting instructions to whatever prompt it passes to `call_fn` — you don't need to (and shouldn't) build that JSON-format instruction yourself.

### `prompt` — your actual question

Just the plain text of what you want answered. BOOTH internally appends formatting instructions before calling `call_fn` — you write this exactly like you would for a normal, unwrapped LLM call.

```python
result = booth.check(call_fn, "What is the capital of France?")
```

### `threshold` — how sure is sure enough

A float between `0.0` and `1.0`. If the model's self-reported confidence is at or above this, BOOTH accepts the answer without retrying. Default is `0.7`.

**This number is a starting guess, not a validated constant.** Different models self-report confidence differently — some are well-calibrated, some overstate, some understate. Before trusting a threshold in anything user-facing, log real (question, status, confidence, actually-correct?) data using `on_attempt` (below) and see where accuracy actually crosses your comfort bar for that specific model.

```python
result = booth.check(call_fn, prompt, threshold=0.85)  # stricter
result = booth.check(call_fn, prompt, threshold=0.5)   # more lenient
```

### `max_retries` — how many extra chances

Number of retries **after** the first attempt.

- `max_retries=0` → exactly 1 call to `call_fn`, no retry, ever.
- `max_retries=1` (default) → up to 2 calls: the original, plus one reconsideration if the first was low-confidence.
- `max_retries=2` → up to 3 calls.

Retries are **not** blind resampling. On retry, BOOTH builds a new prompt that shows the model its own previous answer and confidence, and explicitly asks it to reconsider:

```text
On a previous attempt you answered: "Lyon" with confidence 0.3.
Reconsider carefully. If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

This gives the model a real chance to catch its own mistake, rather than just re-rolling the dice on the same question with no memory of the last attempt.

**Ambiguous questions are never retried**, regardless of `max_retries`. If a question is genuinely ambiguous as asked, asking the model to "reconsider" doesn't resolve the ambiguity — BOOTH returns `AMBIGUOUS` immediately on the attempt that flags it.

### `on_attempt` — watching every call happen

An optional callback, called after *every* attempt (successful, low-confidence, unparseable, or errored) — not just the final result.

```python
def log_it(index: int, attempt: booth.Attempt):
    print(f"attempt {index}: confidence={attempt.confidence}, ambiguous={attempt.ambiguous}")

result = booth.check(call_fn, prompt, on_attempt=log_it)
```

This is how you build the calibration dataset mentioned above — log every attempt to a file or database, and later cross-reference `attempt.confidence` against whether the answer was actually correct, to find out if your chosen `threshold` is doing anything meaningful for your model.

---

## 3. What comes back: `BoothResult`

```python
result = booth.check(call_fn, "What is the capital of France?")
```

| Field | Type | Meaning |
|---|---|---|
| `result.answer` | `str \| None` | The answer text. `None` only if every attempt failed to parse or errored. |
| `result.status` | `str` | One of `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED` (see below). |
| `result.confidence` | `float \| None` | The confidence of whichever attempt produced the final answer. |
| `result.attempts` | `list[Attempt]` | Every attempt made, in order — useful for debugging and logging. |
| `result.n_attempts` | `int` | `len(result.attempts)`, as a convenience property. |
| `result.ok` | `bool` | `True` only for `VERIFIED`/`REPAIRED`. Use this as your quick "is it safe to show" check. |
| `result.ambiguous` | `bool` | `True` only when `status == AMBIGUOUS`. |
| `result.interpretations` | `list[str]` | The different valid readings the model identified, when ambiguous. Empty otherwise. |

### The five statuses, and what to actually do with each

```python
result = booth.check(call_fn, prompt)

if result.status == booth.VERIFIED:
    # First attempt was confident and unambiguous. Show it.
    show(result.answer)

elif result.status == booth.REPAIRED:
    # Model reconsidered and fixed a shaky first answer. Show it —
    # but if you're logging for calibration, note this cost 2 calls.
    show(result.answer)

elif result.status == booth.AMBIGUOUS:
    # The question itself has more than one valid reading.
    # Don't just show result.answer as a settled fact — either ask
    # the user to disambiguate, or show all readings explicitly.
    show(f"This could mean a few things: {result.interpretations}")

elif result.status == booth.UNCERTAIN:
    # Model never got confident, or nothing parsed, or every call
    # failed. Don't show result.answer as reliable.
    show("I'm not confident enough to answer that.")

elif result.status == booth.BLOCKED:
    # Not reachable in the current Path B implementation — reserved
    # for when Path A (evidence-based checking) ships. Included here
    # so your code doesn't need special-casing later.
    pass
```

A shorter version, if you only care about "safe to show or not":

```python
if result.ok:
    show(result.answer)
else:
    show("Couldn't verify a confident, unambiguous answer.")
```

### Inspecting individual attempts

Each entry in `result.attempts` is an `Attempt`:

```python
@dataclass
class Attempt:
    raw_text: str                          # the model's full raw response
    answer: Optional[str]
    confidence: Optional[float]
    parse_ok: bool                         # did BOOTH manage to parse this response?
    error: Optional[str] = None            # set if call_fn raised an exception
    ambiguous: bool = False
    interpretations: List[str] = ...
    chosen_interpretation: Optional[str] = None
```

Useful when something looks wrong and you want to see exactly what the model said on each try, not just the final answer:

```python
for i, attempt in enumerate(result.attempts):
    print(f"attempt {i}: parse_ok={attempt.parse_ok}, "
          f"confidence={attempt.confidence}, error={attempt.error}")
```

---

## 4. Full worked example — wiring BOOTH into Groq

This is a trimmed version of what's in `examples/ai.py`.

```python
import os
from groq import Groq
import booth

client = Groq(api_key=os.environ["GROQ_API_KEY"])

def call_fn(prompt: str) -> str:
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "You are a helpful, accurate assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content or ""

def ask(prompt: str) -> str:
    result = booth.check(call_fn, prompt, threshold=0.7, max_retries=1)

    if result.status == booth.AMBIGUOUS:
        readings = "\n".join(f"- {r}" for r in result.interpretations)
        return f"That question has multiple valid readings:\n{readings}\n\nBest guess: {result.answer}"

    if result.ok:
        return result.answer

    return "I'm not confident enough in an answer to that."

print(ask("What is the capital of France?"))
print(ask("What is the capital of Georgia?"))
print(ask("Who discovered the exact chemical structure of phlogiston in 1847?"))
```

Run it — the three questions above should reliably demonstrate `VERIFIED`, `AMBIGUOUS`, and `UNCERTAIN` respectively, since they're the same categories tested during development. See `examples/app.py` for the same logic wired into a NiceGUI chat interface with status badges.

---

## 5. Building your own calibration test

Before trusting any `threshold` value in production, run this against your own model:

```python
import csv
import booth

TEST_SET = [
    ("What is the capital of France?", "Paris"),
    ("What is the capital of Japan?", "Tokyo"),
    # ... 20-30 more, mix of easy and hard, plus a few known-ambiguous ones
]

rows = []

def log_attempt(i, attempt):
    rows.append({
        "attempt_index": i,
        "answer": attempt.answer,
        "confidence": attempt.confidence,
        "ambiguous": attempt.ambiguous,
        "parse_ok": attempt.parse_ok,
    })

for question, expected in TEST_SET:
    result = booth.check(call_fn, question, on_attempt=log_attempt)
    correct = result.answer == expected if result.answer else None
    rows.append({
        "question": question,
        "expected": expected,
        "final_status": result.status,
        "final_confidence": result.confidence,
        "correct": correct,
    })

with open("calibration.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
```

Open `calibration.csv`, bucket by confidence, and check: does accuracy actually go up as confidence goes up, for your model? That answer — not a number I write in a README — is what should set your real `threshold`.

---

## 6. Known limitations, restated plainly

- **`VERIFIED` is not proof.** A model that is confidently wrong about something unambiguous will pass with `VERIFIED`. Path B has no independent evidence source to catch that class of error.
- **`AMBIGUOUS` catches structural ambiguity reliably** (shared names, competing metrics) but is **weaker on convention-based ambiguity** that requires domain knowledge to recognize as a split at all.
- **Confidence is self-reported, not calibrated.** Don't assume a model saying `0.9` means "90% likely correct" without checking against real data for that model.
- **Every check costs at least one extra LLM call** versus an unwrapped request, and up to `max_retries + 1` calls in the worst case. Factor that into cost/latency budgets before wiring BOOTH into every request in a high-traffic app.