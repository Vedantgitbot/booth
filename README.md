<p align="center">
  <img src="https://raw.githubusercontent.com/Vedantgitbot/booth/main/assets/Booth_logo.png" alt="BOOTH logo" width="220">
</p>

<h1 align="center">BOOTH</h1>

<p align="center">
  <strong>A lightweight checkpoint layer for AI.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/boothpy/"><img src="https://img.shields.io/pypi/v/boothpy" alt="PyPI Package"></a>
  <a href="https://pypi.org/project/boothpy/"><img src="https://img.shields.io/pypi/pyversions/boothpy" alt="Python Versions"></a>
  <a href="https://github.com/Vedantgitbot/booth/actions/workflows/tests.yml"><img src="https://github.com/Vedantgitbot/booth/actions/workflows/tests.yml/badge.svg" alt="Tests Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Vedantgitbot/booth" alt="MIT License"></a>
</p>

<p align="center">
  <a href="TUTORIAL.md"><strong>Tutorial</strong></a> •
  <a href="USECASES.md"><strong>Use Cases</strong></a> •
  <a href="CHANGELOG.md"><strong>Changelog</strong></a> •
  <a href="CONTRIBUTING.md"><strong>Contributing</strong></a> •
  <a href="https://github.com/Vedantgitbot/booth/issues"><strong>Issues</strong></a>
</p>

---

## ⚡ Quickstart

Install BOOTH via PyPI:

```bash
pip install boothpy
```

### Basic Checkpoint (`booth.check`)

Every application built on an LLM has to answer: **Should my application trust this LLM output?**

BOOTH sits between your application and an LLM call, handing back a structured decision (`BoothResult`) instead of just whatever text the model returned:

```python
import booth

# Pass your existing LLM function into BOOTH
result = booth.check(call_llm, "What is the capital of France?")

if result.ok:
    print(result.answer)                       # "Paris" (confident & unambiguous)
else:
    print(f"BOOTH returned {result.status}")    # AMBIGUOUS / UNCERTAIN — don't ship blind
```

---

## 🎯 Highlighted Example: Grounding Answers with Evidence

Same model, same question, asked with and without BOOTH. This is an actual comparison run, not a constructed demo:

| | Response Output | Application Result |
|---|---|---|
| **Without BOOTH** | `"90 days"` (fabricated, no such number exists in policy) | Hallucinated answer sent blindly to user |
| **With `booth.check_with_evidence()`** | `"45 days"` (matches real policy document exactly) | **`BLOCKED`** or **`ACCEPTED`** defensible decision |

No amount of self-reported confidence catches that first answer. Only checking it against something real does:

```python
import booth

result = booth.check_with_evidence(
    answer=llm_answer,
    evidence=retrieved_docs,
    compare_fn=your_comparison_function,
)

if result.status == booth.BLOCKED:
    print(f"The answer doesn't agree with what was actually retrieved: {result.detail}")
else:
    print(f"Grounded Answer: {result.answer}")
```

*(The specific fabricated number will vary from run to run; that's uncalibrated sampling. The pattern is the reliable part.)*

---

## Why BOOTH exists

A few months ago, a person working an airport gate helped me find mine after I'd gotten lost, boarding pass in hand, signs everywhere, still at the wrong gate. She didn't know where I'd flown in from, how the aircraft was built, or anything about my itinerary beyond that one boarding pass. She didn't need to. She knew the airport, and she knew what to check.

That's the idea BOOTH is built around. The industry's default answer to "the model got it wrong" has mostly been to make the model know more: more context, more compute, bigger models, more tools bolted around it. And the problem still happens, because it isn't always a knowledge problem. Sometimes what's missing isn't more information going in. It's something whose only job is checking whether what came out actually meets the bar.

BOOTH doesn't try to know more than your model does. It just knows what to check.

I wrote the longer version of this on Substack: **["Knowing less, but knowing what matters"](https://substack.com/home/post/p-215310975)**.

---

## 🛠️ Checkpoint Modes

BOOTH provides three primary APIs tailored to your application's workflow:

| Function | Mode | Description |
|---|---|---|
| `booth.check()` | Synchronous | Evaluates LLM calls for parsing, ambiguity, confidence, and optional custom validator. Retries with reconsideration if needed. |
| `booth.check_with_evidence()` | Synchronous | Grounds an answer against application-retrieved evidence (e.g. RAG pipeline output). Does not execute LLM calls. |
| `booth.acheck()` | Asynchronous | Async equivalent of `check()`, fully supporting async model callables and async execution loops. |

---

## 🚦 Status Codes & Result Inspection

`booth.check()` and `booth.check_with_evidence()` return a structured `BoothResult` object.

### Status Codes

| Status Code | Type | Description |
|---|---|---|
| `ACCEPTED` | Success | Answer passed all checks (unambiguous, confidence threshold met, validator passed). |
| `REPAIRED` | Success | Initially failed or was ambiguous, but passed after a reconsideration retry. |
| `AMBIGUOUS` | Reject | The response contains unresolved ambiguity or multiple conflicting readings. |
| `UNCERTAIN` | Reject | Model confidence fell below the configured threshold (`default=0.7`). |
| `BLOCKED` | Reject | Evidence check failed — the answer disagrees with provided evidence documents. |
| `INVALID_FORMAT` | Reject | Model response could not be parsed into the expected checkpoint structure. |

### Result Inspection

```python
result = booth.check(call_llm, "Categorize ticket: Server unreachable")

# 1. Quick status check
if result.ok:
    print("Answer:", result.answer)

# 2. Safe unwrapping (returns str if ok, raises BoothRejected otherwise)
try:
    answer = result.unwrap()
except booth.BoothRejected as e:
    print(f"Rejected with status={e.result.status}, method={e.result.method}")

# 3. Rich diagnostic attributes
print(result.status)          # Status string (e.g. ACCEPTED, UNCERTAIN, AMBIGUOUS)
print(result.confidence)      # Confidence score float (0.0 to 1.0)
print(result.method)          # Check failure category ('ambiguity', 'confidence', 'validation', 'parse_failure')
print(result.attempts)        # List of Attempt objects detailing each retry
```

---

## 🔌 Provider Integrations

BOOTH is **zero-dependency** and **provider-agnostic**. Because your application supplies the model-calling function, it works with any LLM client or provider:

### OpenAI

```python
from openai import OpenAI
import booth

client = OpenAI()

def call_openai(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

result = booth.check(call_openai, "What is the capital of Japan?")
```

### Anthropic

```python
import anthropic
import booth

client = anthropic.Anthropic()

def call_anthropic(prompt: str) -> str:
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

result = booth.check(call_anthropic, "Summarize user feedback")
```

### Ollama / Local Models

```python
import requests
import booth

def call_ollama(prompt: str) -> str:
    res = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3", "prompt": prompt, "stream": False}
    )
    return res.json()["response"]

result = booth.check(call_ollama, "Explain quantum entanglement in one sentence.")
```

---

## 💡 Philosophy

1. **Keep the checkpoint small.** A reusable decision layer, not another full LLM framework.
2. **Make uncertainty explicit.** Return a structured status instead of silently passing an unacceptable output through.
3. **Treat ambiguity, validation, and confidence as separate, ordered checks.** A confident, validator-passing answer can still be ambiguous.
4. **Reconsider instead of blindly resampling.** The reason an attempt failed determines what the model is actually shown on retry.
5. **Expose, don't reinterpret.** `result.parsed` shows the model's raw response rather than deciding what it should mean.
6. **Reject invalid data, don't silently coerce it.** An out-of-range confidence or an unrecognized boolean-ish value is a reason to reject the attempt, never guess at.
7. **Keep evidence retrieval outside BOOTH.** Applications own their own RAG, search, database, or tool infrastructure.
8. **Do not pretend agreement is truth.** Agreement with a validator, confidence value, or retrieved evidence is not the same as proving a claim.
9. **Stay provider-agnostic.** BOOTH works with any LLM provider because your application supplies the model-calling function.
10. **Don't collapse distinct failures into one bucket.** A blank input, a crashing dependency, and a genuine disagreement are different problems and should be distinguishable without reading BOOTH's own source.

---

## 📚 Learn More

* **[TUTORIAL.md](TUTORIAL.md)** — Complete reference for every function, type, property, and method in BOOTH's API.
* **[USECASES.md](USECASES.md)** — Detailed guide on where BOOTH fits in your architecture and where it doesn't.
* **[CHANGELOG.md](CHANGELOG.md)** — Release notes and history of features, bug fixes, and API evolution.

---

## 🤝 Contributing

BOOTH is small on purpose. That's a design constraint, not a lack of ambition. Bug reports and confirmed edge cases are the most valuable kind of contribution right now.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for how to report a bug well, what a good reproduction looks like, and what BOOTH's "small on purpose" stance means for feature PRs specifically.

---

## 📄 License

This is the official BOOTH repository, maintained by Vedant Brahmbhatt.

BOOTH is released under the MIT License. See [`LICENSE`](LICENSE) for the full text.