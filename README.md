<p align="center">
  <img src="assets/Booth_logo.png" alt="BOOTH logo" width="220">
</p>

# BOOTH

*A lightweight checkpoint layer for AI.*

[![PyPI](https://img.shields.io/pypi/v/boothpy)](https://pypi.org/project/boothpy/)
[![Python Versions](https://img.shields.io/pypi/pyversions/boothpy)](https://pypi.org/project/boothpy/)
[![License](https://img.shields.io/github/license/Vedantgitbot/booth)](LICENSE)

**Should my application trust this LLM output?**

[Tutorial](TUTORIAL.md) · [Use Cases](USECASES.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/Vedantgitbot/booth/issues)

Every app built on an LLM call has to answer that question eventually, usually the hard way, after a confidently wrong answer has already reached a user. BOOTH is the checkpoint that answers it first. It sits between your application and an LLM call, and hands you back a structured, defensible decision instead of just whatever fluent text the model gave you.

```bash
pip install boothpy
```

```python
import booth

result = booth.check(call_llm, "What is the capital of France?")

if result.ok:
    print(result.answer)                       # "Paris", confident and unambiguous
else:
    print(f"BOOTH returned {result.status}")    # AMBIGUOUS / UNCERTAIN, don't ship it blind
```

---

## Why BOOTH exists

A few months ago, a person working an airport gate helped me find mine after I'd gotten lost, boarding pass in hand, signs everywhere, still at the wrong gate. She didn't know where I'd flown in from, how the aircraft was built, or anything about my itinerary beyond that one boarding pass. She didn't need to. She knew the airport, and she knew what to check.

That's the idea BOOTH is built around. The industry's default answer to "the model got it wrong" has mostly been to make the model know more: more context, more compute, bigger models, more tools bolted around it. And the problem still happens, because it isn't always a knowledge problem. Sometimes what's missing isn't more information going in. It's something whose only job is checking whether what came out actually meets the bar.

BOOTH doesn't try to know more than your model does. It just knows what to check.

I wrote the longer version of this on Substack: **["Knowing less, but knowing what matters"](https://substack.com/home/post/p-215310975)**.

---

## A real example, not a hypothetical

Same model, same question, asked with and without BOOTH. This is an actual comparison run, not a constructed demo.

| | Answer |
|---|---|
| Without BOOTH | "90 days" (fabricated, no such number exists in the actual policy) |
| With `booth.check_with_evidence()` | "45 days" (matches the real policy document exactly) |

No amount of self-reported confidence catches that first answer. Only checking it against something real does.

```python
result = booth.check_with_evidence(
    answer=llm_answer,
    evidence=retrieved_docs,
    compare_fn=your_comparison_function,
)

if result.status == booth.BLOCKED:
    print("The answer doesn't agree with what was actually retrieved.")
```

(The specific fabricated number will vary from run to run, that's just uncalibrated sampling. The pattern is the reliable part.)

---

## Philosophy

1. **Keep the checkpoint small.** A reusable decision layer, not another full LLM framework.
2. **Make uncertainty explicit.** Return a structured status instead of silently passing an unacceptable output through.
3. **Treat ambiguity, validation, and confidence as separate, ordered checks.** A confident, validator-passing answer can still be ambiguous.
4. **Reconsider instead of blindly resampling.** The reason an attempt failed determines what the model is actually shown on retry.
5. **Expose, don't reinterpret.** `result.parsed` shows the model's raw response rather than deciding what it should mean.
6. **Reject invalid data, don't silently coerce it.** An out-of-range confidence or an unrecognized boolean-ish value is a reason to reject the attempt, never guess at.
7. **Keep evidence retrieval outside BOOTH.** Applications own their own RAG, search, database, or tool infrastructure.
8. **Do not pretend agreement is truth.** Agreement with a validator, confidence value, or retrieved evidence is not the same as proving a claim.
9. **Stay provider-agnostic.** BOOTH works with any LLM provider because your application supplies the model-calling function.

---

## What BOOTH provides today

**v0.5.0**, zero-dependency, provider-agnostic, works with any LLM client you already have:

* ambiguity detection, confidence checking with genuine reconsideration retries, and an optional caller-supplied `validator`
* `check_with_evidence()` for grounding an answer against evidence your own RAG pipeline already retrieved
* sync and async APIs (`check()` / `acheck()`) with consistent callable-object support on both
* structured results, including `result.method`, `result.parsed`, `result.to_dict()`, and `result.unwrap()` for a plain `str` (or a raised `BoothRejected`) instead of `Optional[str]` handling at every call site

---

## Learn more

* **[TUTORIAL.md](TUTORIAL.md)**: every function, every field, how it all works
* **[USECASES.md](USECASES.md)**: where BOOTH fits, and just as importantly, where it doesn't
* **[CHANGELOG.md](CHANGELOG.md)**: what changed in each release, and why

```bash
pip install boothpy
# or: pip install git+https://github.com/Vedantgitbot/booth.git
```

---

## Contributing

BOOTH is small on purpose. That's a design constraint, not a lack of ambition. Bug reports and confirmed edge cases are the most valuable kind of contribution right now.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for how to report a bug well, what a good reproduction looks like, and what BOOTH's "small on purpose" stance means for feature PRs specifically.

---

## License

This is the official BOOTH repository, maintained by Vedant Brahmbhatt.

BOOTH is released under the MIT License. See [`LICENSE`](LICENSE) for the full text.