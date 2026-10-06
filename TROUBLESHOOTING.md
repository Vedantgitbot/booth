# Troubleshooting

Known gotchas collected from real integration runs in `examples/`. Each entry follows the same shape: **symptom → cause → what to do**, with a link to where it was observed.

Facts below were checked against BOOTH v0.5.3. If a later release changes behavior, the [CHANGELOG](CHANGELOG.md) is the source of truth.

## Contents

1. [`check()` returns `UNCERTAIN` with `answer=None` and no error](#1-check-returns-uncertain-with-answernone-and-no-error)
2. [Wrong answers come back `ACCEPTED` with confidence 1.0](#2-wrong-answers-come-back-accepted-with-confidence-10)
3. [404 / "model not found" from the provider](#3-404--model-not-found-from-the-provider)
4. [401 with a new-style API key](#4-401-with-a-new-style-api-key)
5. [An ambiguous question was not flagged `AMBIGUOUS`](#5-an-ambiguous-question-was-not-flagged-ambiguous)
6. [`check_with_evidence()` accepts answers it should block](#6-check_with_evidence-accepts-answers-it-should-block)

---

## 1. `check()` returns `UNCERTAIN` with `answer=None` and no error

**Symptom.** Every call returns `status="UNCERTAIN"`, `answer=None`, `confidence=None`, usually with `attempts=2`. Nothing is raised or printed, so a real failure looks the same as the model genuinely being unsure.

**Cause.** If `call_fn` raises (bad API key, retired model name, network error, quota), `check()` / `acheck()` catch the exception, treat it as a failed attempt, retry, and finally return a normal-looking `UNCERTAIN`. As of v0.5.3 the exception is not surfaced on the result (see [#9](https://github.com/Vedantgitbot/booth/issues/9)).

**What to do.** Pass `on_attempt=` and print the attempt's error:

```python
def show_error(i, attempt):
    if attempt.error:
        print(f"[attempt {i + 1}] {attempt.error}")

result = booth.check(call_llm, "What is the capital of France?", on_attempt=show_error)
```

Rule of thumb: if you see `UNCERTAIN` with `answer=None` and `attempts > 1`, look for an exception inside `call_fn` before blaming the model. You can also call your `call_fn` once directly, outside BOOTH, to see the raw error.

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini) (401 for a bad key, 404 for a retired model; see also [#8](https://github.com/Vedantgitbot/booth/pull/8)).

---

## 2. Wrong answers come back `ACCEPTED` with confidence 1.0

**Symptom.** The model gives a factually wrong answer, and `check()` returns `ACCEPTED` with `confidence=1.0`.

**Cause.** The confidence value is self-reported by the model; BOOTH does not verify it. `check()` checks format and internal consistency (parseable output, confidence above the threshold, no ambiguity flag), not facts. This is expected behavior, not a bug. In one run on a local 7B model, all three wrong answers still came back with `confidence: 1.0`.

**What to do.** Do not treat `ok=True` from `check()` as "the answer is true". If you have ground truth, use `check_with_evidence()` to compare the answer against it. Smaller models tend to over-report confidence.

**Seen in:** [`examples/Maintythehuman_ollama`](examples/Maintythehuman_ollama).

---

## 3. 404 / "model not found" from the provider

**Symptom.** An example copied from another folder or an older tutorial fails with a 404 or "model not found", often hidden behind entry 1 above.

**Cause.** Provider model names get retired. During the Gemini example, `gemini-2.5-flash-lite` stopped being available to new users, and the API returned a 404 pointing to `gemini-3.5-flash-lite` instead.

**What to do.** Do not assume a model name in an older example is still valid. Check the provider's current model list, and make the model configurable (for example through an environment variable) so a rename is a one-line change.

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini).

---

## 4. 401 with a new-style API key

**Symptom.** `401 UNAUTHENTICATED` (for example `ACCESS_TOKEN_TYPE_UNSUPPORTED`) even though the key was copied correctly.

**Cause.** Newer provider key formats may not be understood by older SDK versions. In the Gemini example, a new-style key (prefix `AQ.` instead of `AIza`) worked only after upgrading the SDK. A deleted or wrong key also returns a 401, so rule that out first.

**What to do.** Upgrade the provider SDK (`pip install -U <sdk>`), confirm the key is the one currently loaded in your environment, and run it once outside BOOTH to separate a key problem from a BOOTH problem. Remember that `check()` hides the error unless you use `on_attempt=` (entry 1).

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini).

---

## 5. An ambiguous question was not flagged `AMBIGUOUS`

**Symptom.** The same kind of ambiguous question is flagged `AMBIGUOUS` in one setup and passes through unflagged in another. For example, "What is the capital of Georgia?" (the country or the US state) was not flagged against a local 7B model, which simply picked one interpretation, while a vague question in the Gemini example was flagged correctly.

**Cause.** Ambiguity detection relies on the model noticing the ambiguity and saying so in its response. It is model-dependent and not guaranteed. This is a limitation of the approach, not inconsistent behavior from BOOTH itself.

**What to do.** Do not rely on `AMBIGUOUS` as a complete safety net for vague input. Check `result.status` or `result.ambiguous`, not `confidence`, when detecting it: in one run the ambiguous case came back with `confidence=1.0` and the explanation sitting in `.answer`. Where it matters, disambiguate the question before sending it.

**Seen in:** [`examples/Maintythehuman_ollama`](examples/Maintythehuman_ollama) (Georgia question not flagged), [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini) (a different vague question flagged `AMBIGUOUS`).

---

## 6. `check_with_evidence()` accepts answers it should block

**Symptom.** An answer that contradicts your evidence is `ACCEPTED`.

**Cause.** `check_with_evidence()` only runs the `compare_fn` you give it. A weak comparator gives a weak checkpoint. BOOTH can detect a `compare_fn` that crashes or returns something unusable (`result.checker_failed`), but not one that runs fine with bad logic. See [USECASES.md §27](USECASES.md).

**What to do.** Test your `compare_fn` on its own with answers you know should pass and fail, including a deliberately wrong one, before wiring it in. Simple keyword or stance checks are fine for demos; use an embedding, entailment, or LLM-judge comparison for real use.

**Seen in:** nearly every example, for instance [`examples/Vedantgitbot_groq`](examples/Vedantgitbot_groq) and the Anthropic example, whose RESULTS.md lists lexical phrase matching as a limitation.
