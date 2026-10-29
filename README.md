<p align="center">
  <img
    src="https://raw.githubusercontent.com/Vedantgitbot/booth/main/assets/Booth_logo.png"
    alt="BOOTH logo"
    width="220"
  >
</p>

<h1 align="center">BOOTH</h1>

<p align="center">
  <strong>A lightweight checkpoint layer for AI.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/boothpy/">
    <img src="https://img.shields.io/pypi/v/boothpy" alt="PyPI Package">
  </a>
  <a href="https://pypi.org/project/boothpy/">
    <img src="https://img.shields.io/pypi/pyversions/boothpy" alt="Python Versions">
  </a>
  <a href="https://github.com/Vedantgitbot/booth/actions/workflows/tests.yml">
    <img src="https://github.com/Vedantgitbot/booth/actions/workflows/tests.yml/badge.svg" alt="Tests Status">
  </a>
  <a href="https://github.com/Vedantgitbot/booth/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/Vedantgitbot/booth" alt="MIT License">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Vedantgitbot/booth/blob/main/TUTORIAL.md">Tutorial</a> &bull;
  <a href="https://github.com/Vedantgitbot/booth/blob/main/USECASES.md">Use Cases</a> &bull;
  <a href="https://github.com/Vedantgitbot/booth/blob/main/CHANGELOG.md">Changelog</a> &bull;
  <a href="https://github.com/Vedantgitbot/booth/blob/main/CONTRIBUTING.md">Contributing</a> &bull;
  <a href="https://github.com/Vedantgitbot/booth/issues">Issues</a>
</p>

---

## ⚡ Quickstart

Every application built on an LLM has to answer one question:

> Should my application trust this LLM output?

BOOTH adds a checkpoint between an LLM response and your application's next action. It returns a structured `BoothResult` so your application can decide whether to proceed, reject, or handle uncertainty.

Install BOOTH from PyPI:

```bash
pip install boothpy
```

### Basic checkpoint

Pass your existing model-calling function to `booth.check()`:

```python
import booth

# call_llm is your existing model-calling function.
result = booth.check(call_llm, "What is the capital of France?")

if result.ok:
    print(result.answer)
else:
    print(f"BOOTH returned {result.status}")
```

An accepted result means the configured checks passed. It does not prove that the answer is factually correct.

---

## 🎯 Grounding Answers with Evidence

A model can sound confident while giving an answer that contradicts your documents. Self-reported confidence alone cannot establish whether an answer agrees with a policy, retrieved passage, or other source.

`booth.check_with_evidence()` checks a supplied answer against evidence using a comparison function you provide.

### Example: refund-policy answers

In a documented comparison run, the model produced a fabricated `"90 days"` answer without grounding. The policy stated `"45 days"`.

| Answer being evaluated | Relationship to the policy | Intended checkpoint decision |
| :--- | :--- | :--- |
| `"90 days"` | Contradicts the policy's 45-day period | `BLOCKED` if the comparator detects the disagreement |
| `"45 days"` | Matches the policy's stated period | `ACCEPTED` if the comparator confirms agreement |

The checkpoint does not turn `"90 days"` into `"45 days"`. It evaluates the answer your application supplies.

```python
import booth

result = booth.check_with_evidence(
    answer=llm_answer,
    evidence=retrieved_docs,
    compare_fn=your_comparison_function,
)

if result.ok:
    print(f"Grounded answer: {result.answer}")
else:
    print(f"Evidence check returned {result.status}: {result.detail}")
```

> The specific fabricated number can vary between model runs. The important distinction is whether the answer agrees with the supplied evidence.

### The comparator matters

`check_with_evidence()` runs the `compare_fn` you provide. A weak comparator gives a weak check.

The examples include a keyword matcher and an NLI model evaluated on the same inputs, along with failure cases and limitations. NLI, or natural language inference, is used here to assess whether evidence supports or contradicts an answer.

See [Provider Integrations and Examples](#-provider-integrations-and-examples) for the documented runs.

---

## Why BOOTH Exists

A few months ago, a person working an airport gate helped me find mine after I'd gotten lost. Boarding pass in hand, signs everywhere, I was still at the wrong gate.

She didn't know where I'd flown in from, how the aircraft was built, or anything about my itinerary beyond that one boarding pass. She didn't need to. She knew the airport, and she knew what to check.

That's the idea BOOTH is built around.

The industry's default answer to "the model got it wrong" has mostly been to make the model know more: more context, more compute, bigger models, and more tools bolted around it.

But the problem still happens, because it isn't always a knowledge problem. Sometimes what's missing isn't more information going in. It's something whose only job is checking whether what came out actually meets the bar.

BOOTH doesn't try to know more than your model does. It just knows what to check.

I wrote the longer version on Substack: ["Knowing less, but knowing what matters"](https://substack.com/home/post/p-215310975).

---

## 🛠️ Checkpoint Modes

BOOTH provides three primary APIs:

| Function | Execution | Purpose |
| :--- | :--- | :--- |
| `booth.check()` | Synchronous | Evaluates model responses for parsing, ambiguity, confidence, and an optional custom validator. Retries with reconsideration when appropriate. |
| `booth.check_with_evidence()` | Synchronous | Evaluates a supplied answer against application-provided evidence using your comparator. Does not call an LLM itself. |
| `booth.acheck()` | Asynchronous | Async equivalent of `check()`, supporting async model callables and async execution loops. |

Your application owns model access, evidence retrieval, and downstream handling. BOOTH provides the checkpoint decision.

---

## 🚦 Status Codes and Result Inspection

Checkpoint results are returned as structured `BoothResult` objects.

### Status codes

| Status | Outcome | Meaning |
| :--- | :--- | :--- |
| `ACCEPTED` | Success | The applicable checks passed. For `check()`, this includes ambiguity, confidence, and any supplied validator. |
| `REPAIRED` | Success | An earlier attempt failed, but a retry passed. |
| `AMBIGUOUS` | Rejected | The model reported multiple reasonable readings of the question. Returned immediately without retrying. |
| `UNCERTAIN` | Rejected | No acceptable result was obtained. Possible causes include low confidence, parsing failure, validator failure, or a failed model call. |
| `BLOCKED` | Rejected | The evidence comparator rejected the answer against the supplied evidence. |

The default confidence threshold for `check()` is `0.7`.

There is no separate status for an unparseable response. A parsing failure is reported as `UNCERTAIN` with `result.method == "parse_failure"`.

For an `UNCERTAIN` result, inspect `result.method` and `result.call_failed` to distinguish the cause.

### Check the result

```python
result = booth.check(call_llm, "Categorize ticket: Server unreachable")

if result.ok:
    print("Answer:", result.answer)
else:
    print("Status:", result.status)
```

### Unwrap an accepted answer

`unwrap()` returns the answer when the result is successful and raises `BoothRejected` otherwise.

```python
try:
    answer = result.unwrap()
except booth.BoothRejected as exc:
    print(
        f"Rejected with status={exc.result.status}, "
        f"method={exc.result.method}"
    )
```

### Inspect diagnostics

```python
print(result.status)       # For example: ACCEPTED, UNCERTAIN, or AMBIGUOUS
print(result.confidence)   # Confidence score
print(result.method)       # Check or failure category
print(result.call_failed)  # Whether the model-calling function failed
print(result.attempts)     # Attempt objects describing the initial call and retries
```

Failure categories include `ambiguity`, `confidence`, `validation`, and `parse_failure`.

`result.call_failed` helps distinguish an unsuccessful model call—such as a network or API error—from a model response that failed the checkpoint.

---

## 🔌 Provider Integrations and Examples

BOOTH has zero dependencies and is provider-agnostic. Your application supplies the model-calling function, so BOOTH does not require a particular LLM client or provider.

[Browse the runnable integration examples →](https://github.com/Vedantgitbot/booth/tree/main/examples)

Each example folder includes runnable code, recorded console output, and findings from an actual run.

### Provider examples

| Provider or runtime | Model(s) | API(s) demonstrated |
| :--- | :--- | :--- |
| Groq | `llama-3.3-70b-versatile` | `check_with_evidence()` |
| Google Gemini | `gemini-3.5-flash-lite` | `check()`, `check_with_evidence()` |
| Anthropic | `claude-3-5-haiku-20241022` | `check_with_evidence()` |
| Ollama / local models | `qwen2.5-coder:7b`, `llama3.2:latest` | `check()`, `acheck()`, `check_with_evidence()` |

These examples cover:

- Groq: evidence-grounded refund-policy QA and hallucination blocking.
- Google Gemini: ambiguity detection, evidence grounding, and an integration issue where failed API calls initially looked like an unsure model. These can now be distinguished with `result.call_failed`.
- Anthropic: evidence-grounded refund-policy QA against Claude.
- Ollama: local-model checks, async execution, evidence checks, and both useful and misleading self-reported confidence.

### RAG and comparator studies

| Example | Stack or comparator | Finding |
| :--- | :--- | :--- |
| Local RAG pipeline | LangChain, FAISS, FLAN-T5, and `cross-encoder/nli-deberta-v3-base` | The comparator blocked the wrong answer, but also blocked two correct answers. |
| Comparator comparison | Keyword matcher vs. `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | On the same 10 authored cases, the comparators matched expectations in 4/10 and 9/10 cases, respectively. A conflicting-evidence case still received `ACCEPTED`. |

These are documented example results, not a general accuracy guarantee.

Each example's `RESULTS.md` records what happened: what worked, what failed, and what was surprising. Negative results are intentional. A confidently wrong result from `check()` alone is as useful to document as a clean pass.

To contribute an integration, see the [open call for provider examples](https://github.com/Vedantgitbot/booth/issues/2). Any provider, any model—PRs welcome.

---

## 💡 Philosophy

1. Keep the checkpoint small.  
   A reusable decision layer, not another full LLM framework.

2. Make uncertainty explicit.  
   Return a structured status instead of silently passing an unacceptable output through.

3. Treat ambiguity, validation, and confidence as separate, ordered checks.  
   A confident answer that passes a validator can still be ambiguous.

4. Reconsider instead of blindly resampling.  
   The reason an attempt failed determines what the model is shown on retry.

5. Expose, don't reinterpret.  
   `result.parsed` exposes the parsed model response rather than deciding what it should mean.

6. Reject invalid data instead of silently coercing it.  
   An out-of-range confidence value or an unrecognized boolean-like value is a reason to reject the attempt, not guess.

7. Keep evidence retrieval outside BOOTH.  
   Applications own their RAG, search, database, and tool infrastructure.

8. Do not pretend agreement is truth.  
   Agreement with a validator, confidence value, or retrieved evidence does not prove a claim.

9. Stay provider-agnostic.  
   BOOTH works with your model-calling function rather than requiring a specific provider.

10. Keep distinct failures distinguishable.  
    A blank input, a crashing dependency, and a genuine disagreement are different problems. You should not have to read BOOTH's source to tell them apart.

---

## 📚 Learn More

| Resource | What it covers |
| :--- | :--- |
| [Tutorial](https://github.com/Vedantgitbot/booth/blob/main/TUTORIAL.md) | Reference for BOOTH's functions, types, properties, and methods. |
| [Use Cases](https://github.com/Vedantgitbot/booth/blob/main/USECASES.md) | Where BOOTH fits in your architecture—and where it does not. |
| [Changelog](https://github.com/Vedantgitbot/booth/blob/main/CHANGELOG.md) | Releases, bug fixes, and API changes. |
| [Examples](https://github.com/Vedantgitbot/booth/tree/main/examples) | Runnable integrations with documented results. |
| [Troubleshooting](https://github.com/Vedantgitbot/booth/blob/main/TROUBLESHOOTING.md) | Known integration issues and fixes. |
| [Contributing](https://github.com/Vedantgitbot/booth/blob/main/CONTRIBUTING.md) | Bug reports, reproductions, and contribution guidelines. |

---

## 🤝 Contributing

BOOTH is small on purpose. That's a design constraint, not a lack of ambition.

Bug reports and confirmed edge cases are especially valuable.

See [CONTRIBUTING.md](https://github.com/Vedantgitbot/booth/blob/main/CONTRIBUTING.md) for:

- How to report a bug.
- What makes a useful reproduction.
- What "small on purpose" means for feature proposals and pull requests.

---

## 📄 License

This is the official BOOTH repository, maintained by Vedant Brahmbhatt.

BOOTH is released under the MIT License. See [LICENSE](https://github.com/Vedantgitbot/booth/blob/main/LICENSE) for the full text.