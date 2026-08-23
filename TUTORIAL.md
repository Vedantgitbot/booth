# BOOTH Tutorial

This walks through everything in BOOTH's public API, then shows how to wire it into a real application from scratch. If you just want the shape of the API, see the README. This is the "explain every piece, step by step" version.

---

## 1. Install

```bash
pip install boothpy
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
print(booth.__version__)   # 0.3.1
```

---

## 2. The core function: `booth.check()`

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

That's the whole surface area for synchronous use. There's also an async twin, `booth.acheck()`, covered in section 7 — everything below about `threshold`, `max_retries`, `on_attempt`, and the result object applies identically to both.

### `call_fn` — the thing BOOTH wraps

This is **your** function, not BOOTH's. BOOTH doesn't know about OpenAI, Anthropic, Groq, or any specific provider — it only knows how to call a plain Python function that takes a prompt string and returns a text string.

```python
def call_fn(prompt: str) -> str:
    response = some_client.chat.completions.create(
        model="...",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
```

**Why a plain function instead of a client object?** Because it keeps BOOTH provider-agnostic. Whatever quirks your provider's SDK has (message format, auth, streaming, etc.) live entirely inside `call_fn` — BOOTH never needs to know about them. It just needs "string in, string out."

**Important:** `call_fn` will be called **more than once** if the first attempt is low-confidence, unparseable, or errors out (up to `max_retries + 1` times total). BOOTH appends its own confidence/ambiguity-reporting instructions to whatever prompt it passes to `call_fn` — you don't need to (and shouldn't) build that JSON-format instruction yourself.

### `prompt` — your actual question

Just the plain text of what you want answered. BOOTH internally appends formatting instructions before calling `call_fn`.

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
- `max_retries=1` (default) → up to 2 calls.
- `max_retries=2` → up to 3 calls.

There are actually **two different retry prompts**, depending on what went wrong on the previous attempt:

**If the previous attempt parsed but was low-confidence**, BOOTH shows the model its own previous answer and confidence, and asks it to reconsider:

```text
On a previous attempt you answered: "Lyon" with confidence 0.3.
Reconsider carefully. If that answer is correct, restate it.
If it is wrong, give the corrected answer.
```

**If the previous attempt didn't parse at all** (no valid JSON, missing keys, out-of-range confidence), there's nothing meaningful to show the model back — instead, BOOTH tells it plainly that its last output didn't parse and restates the format contract:

```text
Your previous response could not be parsed: it did not contain a
valid JSON object with the required keys. Output your response as
a single JSON object with exactly the required keys, and nothing
else — no markdown code fences, no commentary before or after it.
```

This distinction matters in practice: without it, a model with a stable formatting habit (always wraps JSON in markdown fences, always adds a chatty preamble) would fail the same way on every single retry, burning your whole `max_retries` budget for nothing, with no signal telling it to change behavior.

**Ambiguous questions are never retried**, regardless of `max_retries`. If a question is genuinely ambiguous as asked, asking the model to "reconsider" doesn't resolve the ambiguity — BOOTH returns `AMBIGUOUS` immediately on the attempt that flags it.

### `on_attempt` — watching every call happen

An optional callback, called after *every* attempt (successful, low-confidence, unparseable, or errored) — not just the final result.

```python
def log_it(index: int, attempt: booth.Attempt):
    print(f"attempt {index}: confidence={attempt.confidence}, ambiguous={attempt.ambiguous}, parse_ok={attempt.parse_ok}")

result = booth.check(call_fn, prompt, on_attempt=log_it)
```

This is how you build the calibration dataset mentioned above — log every attempt to a file or database, and later cross-reference `attempt.confidence` against whether the answer was actually correct, to find out if your chosen `threshold` is doing anything meaningful for your model.

For `check()`, `on_attempt` must be a plain synchronous function — passing a coroutine function (`async def`) raises `TypeError` immediately, since `check()` has no way to await it. Use `acheck()` if you need an async callback (see section 7).

---

## 3. What comes back: `BoothResult`

```python
result = booth.check(call_fn, "What is the capital of France?")
```

| Field | Type | Meaning |
|---|---|---|
| `result.answer` | `str \| None` | The answer text. `None` only if every attempt failed to parse or errored. |
| `result.status` | `str` | One of `VERIFIED`, `REPAIRED`, `AMBIGUOUS`, `UNCERTAIN`, `BLOCKED`. |
| `result.confidence` | `float \| None` | The confidence of whichever attempt produced the final answer. |
| `result.attempts` | `list[Attempt]` | Every attempt made, in order — useful for debugging and logging. |
| `result.n_attempts` | `int` | `len(result.attempts)`, as a convenience property. |
| `result.ok` | `bool` | `True` only for `VERIFIED`/`REPAIRED`. Use this as your quick "is it safe to show" check. |
| `result.ambiguous` | `bool` | `True` only when `status == AMBIGUOUS`. |
| `result.interpretations` | `list[str]` | The different valid readings the model identified, when ambiguous. Empty otherwise. |
| `result.all_parse_failed` | `bool` | `True` only if `status == UNCERTAIN` **and** every single attempt failed to parse. See below for why this is worth checking separately. |

### Why `all_parse_failed` exists

`UNCERTAIN` is overloaded — it covers two operationally different situations:

1. The model produced usable answers every time, but confidence never reached your threshold. This is a genuine "the model isn't sure" outcome.
2. The model's output never parsed into the expected schema at all — wrong format, missing keys, garbage text. This usually isn't about the model's certainty; it's a format/integration problem (bad `call_fn` wiring, a model that ignores instructions, or a model that isn't good at structured output).

These call for different fixes: (1) might mean lowering your threshold, trying a different model, or accepting the answer with a caveat; (2) means checking your `call_fn`, your prompt, or trying a model better at following format instructions. `result.all_parse_failed` tells you which one you're looking at without manually inspecting `result.attempts`.

```python
if result.status == booth.UNCERTAIN:
    if result.all_parse_failed:
        print("Nothing ever parsed — check call_fn / prompt formatting.")
    else:
        print("Model tried, but never reached the confidence threshold.")
```

### The five statuses, and what to actually do with each

```python
result = booth.check(call_fn, prompt)

if result.status == booth.VERIFIED:
    # First attempt was confident and unambiguous. Show it.
    show(result.answer)

elif result.status == booth.REPAIRED:
    # Model reconsidered and fixed a shaky first answer. Show it —
    # but if you're logging for calibration, note this cost 2+ calls.
    show(result.answer)

elif result.status == booth.AMBIGUOUS:
    # The question itself has more than one valid reading — or the
    # model is uncertain about a fact and hedging between two similar
    # wrong answers, which currently looks identical from the outside.
    # Don't just show result.answer as a settled fact.
    show(f"This could mean a few things: {result.interpretations}")

elif result.status == booth.UNCERTAIN:
    # Model never got confident, or nothing parsed, or every call
    # failed. Don't show result.answer as reliable.
    show("I'm not confident enough to answer that.")

elif result.status == booth.BLOCKED:
    # Not reachable in the current Path B implementation — reserved
    # for when Path A (evidence-based checking) ships.
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

Useful when something looks wrong and you want to see exactly what the model said on each try:

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

Run it — the three questions above should reliably demonstrate `VERIFIED`, `AMBIGUOUS`, and `UNCERTAIN` respectively. See `examples/app.py` for the same logic wired into a NiceGUI chat interface with status badges.

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

Open `calibration.csv`, bucket by confidence, and check: does accuracy actually go up as confidence goes up, for your model? That answer — not a number in this doc — is what should set your real `threshold`.

---

## 6. Known limitations, restated plainly

- **`VERIFIED` is not proof.** A model that is confidently wrong about something unambiguous will pass with `VERIFIED`. Path B has no independent evidence source to catch that class of error.
- **`AMBIGUOUS` catches structural ambiguity reliably** (shared names, competing metrics) but is **weaker on convention-based ambiguity** that requires domain knowledge to recognize as a split at all.
- **`AMBIGUOUS` can also fire on a fabricated premise, not just a genuinely contested question.** If a model doesn't actually know the answer to something (a specific real-world fact, a recent event), it can generate two similarly-worded "interpretations" around its own uncertainty rather than a real reading split. From the outside this looks identical to genuine ambiguity. Treat `AMBIGUOUS` results about specific factual claims with extra scrutiny — this is an observed behavior, not a hypothetical edge case.
- **Confidence is self-reported, not calibrated.** Don't assume a model saying `0.9` means "90% likely correct" without checking against real data for that model.
- **Every check costs at least one extra LLM call** versus an unwrapped request, and up to `max_retries + 1` calls in the worst case. Factor that into cost/latency budgets before wiring BOOTH into every request in a high-traffic app.
- **BOOTH only checks a model's self-assessment of itself.** It is not evidence-based verification. If you need "does this answer actually match an external source," that's the planned Path A, not something Path B does — see the README's Path A section for exactly what that will and won't cover once it exists.

---

## 7. Async: `booth.acheck()`

If your app is already async (FastAPI, Starlette, an async model client), use `booth.acheck()` instead of running `check()` in a thread pool. It has an identical contract — same `threshold`/`max_retries`/`on_attempt` parameters, same `BoothResult` shape, same retry and ambiguity logic (both functions are driven by the same internal decision step) — the only difference is `call_fn` must be an `async def`.

```python
import asyncio
import booth

async def call_fn(prompt: str) -> str:
    response = await async_client.chat.completions.create(
        model="...",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

async def ask(prompt: str) -> str:
    result = await booth.acheck(call_fn, prompt, threshold=0.7, max_retries=1)
    if result.ok:
        return result.answer
    return "I'm not confident enough in an answer to that."

asyncio.run(ask("What is the capital of France?"))
```

**Passing a sync `call_fn` to `acheck()` raises `TypeError` immediately** rather than silently misbehaving — same for passing a sync `check()` an async `on_attempt`. If you get one of these errors, you're using the wrong entry point for your function.

**`on_attempt` for `acheck()`** may be either sync or async — `acheck()` only awaits it if it's a coroutine function, so an existing sync logging callback works unchanged:

```python
async def on_attempt(i, attempt):
    await db.log(i, attempt.confidence, attempt.ambiguous)

result = await booth.acheck(call_fn, prompt, on_attempt=on_attempt)
```

**Concurrency:** both `check()` and `acheck()` hold no shared or module-level mutable state, so many simultaneous `acheck()` calls (e.g. one per incoming request) don't interfere with each other. What limits you under load is your model provider's rate limits and how your own `call_fn` handles concurrent calls — not anything inside BOOTH.

If you're in an async app but your model client is sync-only, don't call `check()` directly inside an `async def` — it blocks the event loop for the duration of every `call_fn` call. Run it in a thread pool:

```python
from concurrent.futures import ThreadPoolExecutor
import functools

executor = ThreadPoolExecutor(max_workers=20)

async def handler():
    loop = asyncio.get_event_loop()
    fn = functools.partial(booth.check, call_fn, prompt, threshold=0.8)
    result = await loop.run_in_executor(executor, fn)
```