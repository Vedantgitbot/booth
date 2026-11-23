# Troubleshooting

Known gotchas collected from real integration runs in `examples/`. Each entry follows the same shape: **symptom → cause → what to do**, with a link to where it was observed.

The runs behind these entries used BOOTH 0.4.9 to 0.5.4. Entries 1, 3 and 4 were updated for v0.5.4, which added `call_failed`; entry 9 describes v0.5.5. Entry 10 comes from the benchmark in issues #32 and #33 (BOOTH 0.5.8, with the parser change from 0.5.9) and was rewritten for v0.6.0, which added `suffix=`. If a later release changes behavior, the [CHANGELOG](CHANGELOG.md) is the source of truth.

## Contents

1. [`check()` returns `UNCERTAIN` with `answer=None` and no visible error](#1-check-returns-uncertain-with-answernone-and-no-visible-error)

2. [Wrong answers come back `ACCEPTED` with confidence 1.0](#2-wrong-answers-come-back-accepted-with-confidence-10)

3. [404 / "model not found" from the provider](#3-404--model-not-found-from-the-provider)

4. [401 with a new-style API key](#4-401-with-a-new-style-api-key)

5. [An ambiguous question was not flagged `AMBIGUOUS`](#5-an-ambiguous-question-was-not-flagged-ambiguous)

6. [`check_with_evidence()` accepts answers it should block](#6-check_with_evidence-accepts-answers-it-should-block)

7. [A correct short answer is `BLOCKED` by an NLI comparator](#7-a-correct-short-answer-is-blocked-by-an-nli-comparator)

8. [Conflicting evidence still comes back `ACCEPTED`](#8-conflicting-evidence-still-comes-back-accepted)

9. [`TypeError: validator must be callable`](#9-typeerror-validator-must-be-callable)

10. [Accuracy drops on reasoning-heavy tasks](#10-accuracy-drops-on-reasoning-heavy-tasks-maths-multi-step-questions)

---

## 1. `check()` returns `UNCERTAIN` with `answer=None` and no visible error

**Symptom.** Every call returns `status="UNCERTAIN"`, `answer=None`, `confidence=None`, often with `attempts=2`. Nothing is raised or printed, so a real failure can look the same as the model genuinely being unsure.

**Cause.** If `call_fn` raises (bad API key, retired model name, network error, quota), `check()` / `acheck()` catch the exception, treat it as a failed attempt, retry, and finally return `UNCERTAIN`. Before v0.5.4 nothing on the result told you this had happened (see [#9](https://github.com/Vedantgitbot/booth/issues/9) for the history). From v0.5.4, `result.call_failed` is `True` when `call_fn` itself failed.

**What to do.** Check `result.call_failed` first:

```python

result = booth.check(call_llm, "What is the capital of France?")

if result.call_failed:

    print("call_fn failed (bad key, retired model, network error?), not a model judgment")

elif not result.ok:

    print(f"Genuinely rejected: status={result.status}, method={result.method}")

```

To see the actual error text, pass `on_attempt=` and print each attempt's error:

```python

def show_error(i, attempt):

    if attempt.error:

        print(f"[attempt {i + 1}] {attempt.error}")

result = booth.check(call_llm, "What is the capital of France?", on_attempt=show_error)

```

If you are on v0.5.3 or earlier, upgrade (`pip install -U boothpy`), or use the rule of thumb: `UNCERTAIN` with `answer=None` and `attempts > 1` usually means an exception inside `call_fn`, so look there before blaming the model. In any version you can also call your `call_fn` once directly, outside BOOTH, to see the raw error.

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini) (401 for a bad key, 404 for a retired model; see also [#8](https://github.com/Vedantgitbot/booth/pull/8)). That run was on 0.5.2, before `call_failed` existed.

---

## 2. Wrong answers come back `ACCEPTED` with confidence 1.0

**Symptom.** The model gives a factually wrong answer, and `check()` returns `ACCEPTED` with `confidence=1.0`.

**Cause.** The confidence value is self-reported by the model; BOOTH does not verify it. `check()` checks format and internal consistency (parseable output, confidence above the threshold, no ambiguity flag), not facts. This is expected behavior, not a bug. In one run on a local 7B model (`qwen2.5-coder:7b`), all three wrong answers still came back with `confidence: 1.0`.

**What to do.** Do not treat `ok=True` from `check()` as "the answer is true". If you have ground truth, use `check_with_evidence()` to compare the answer against it.

**Seen in:** [`examples/Maintythehuman_ollama`](examples/Maintythehuman_ollama).

---

## 3. 404 / "model not found" from the provider

**Symptom.** An example copied from another folder or an older tutorial fails with a 404 or "model not found", often looking like a plain `UNCERTAIN` (see entry 1).

**Cause.** Provider model names get retired. During the Gemini example, `gemini-2.5-flash-lite` stopped being available to new users, and the API returned a 404 pointing to `gemini-3.5-flash-lite` instead.

**What to do.** Do not assume a model name in an older example is still valid. Check the provider's current model list, and make the model configurable (for example through an environment variable) so a rename is a one-line change. If `result.call_failed` is `True`, the problem is in your `call_fn` (model name, key, network), not in BOOTH.

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini).

---

## 4. 401 with a new-style API key

**Symptom.** `401 UNAUTHENTICATED` (for example `ACCESS_TOKEN_TYPE_UNSUPPORTED`) even though the key was copied correctly.

**Cause.** Newer provider key formats may not be understood by older SDK versions. In the Gemini example, a new-style key (prefix `AQ.` instead of `AIza`) worked after upgrading the SDK, although the tester notes a deleted key may also have been the cause, so the exact fix is not certain. A deleted or wrong key also returns a 401, so rule that out first.

**What to do.** Upgrade the provider SDK (`pip install -U <sdk>`), confirm the key is the one currently loaded in your environment, and run it once outside BOOTH to separate a key problem from a BOOTH problem. Inside BOOTH, `result.call_failed` (entry 1) tells you the failure came from `call_fn`, and `on_attempt=` shows the error text.

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

**What to do.** Test your `compare_fn` on its own with answers you know should pass and fail, including a deliberately wrong one, before wiring it in. Simple keyword or stance checks are fine for demos; use an embedding, entailment, or LLM-judge comparison for real use. See entries 7 and 8 for what to watch for with entailment comparators.

**Seen in:** [`examples/AkashGoswamy_gemini`](examples/AkashGoswamy_gemini) (simple refund-stance check) and [`examples/opencode13241-eng_anthropic`](examples/opencode13241-eng_anthropic) (lexical phrase matching), whose RESULTS.md files both list their comparison logic as a limitation.

---

## 7. A correct short answer is `BLOCKED` by an NLI comparator

**Symptom.** With an entailment-based `compare_fn`, answers like `"No"` or `"9 AM to 5 PM"` are `BLOCKED` with a score near zero, even though they are correct. Correct full sentences that need a small inference can also score low (one run scored `"The library closes at 5 PM"` at 0.168 against evidence saying it is open 9 AM to 5 PM).

**Cause.** NLI models judge whether the evidence entails a full-sentence claim. A fragment has no claim to judge, and the question that gives it meaning is not part of the comparison. This is a limit of the comparator, not of BOOTH.

**What to do.** Rewrite short answers into full sentences before comparing (for example by including the question), score against single sentences rather than a whole chunk, and test your comparator on correct answers as well as wrong ones. Do not lower the threshold just to rescue a handful of examples. At a 0.70 threshold, scores of 0.168 and 0.004 both block, so look at the scores before you decide the threshold is wrong.

**Seen in:** [`examples/Harithalakshmikt_langchain_flan`](examples/Harithalakshmikt_langchain_flan).

---

## 8. Conflicting evidence still comes back `ACCEPTED`

**Symptom.** One retrieved passage supports the answer and another contradicts it, yet `check_with_evidence()` returns `ACCEPTED`.

**Cause.** `compare_fn` returns a single number. A comparator that takes the maximum entailment score across passages reports the supporting passage and drops the contradicting one. In the example run, one passage had `p(entail)≈0.994` and another `p(contradict)≈0.997`, and the score handed to BOOTH was 0.994.

**What to do.** Decide how your comparator should treat conflicts and encode it in the score, for example by lowering the score when a passage contradicts the answer. Be careful: evidence that covers other subjects can look like a contradiction to an NLI model (in the same example, a scope-swapped passage was labelled contradiction at about 0.75), so a strict rule can block correct answers. Test it on correct answers as well as wrong ones, and keep a conflicting-evidence case in your own tests.

**Seen in:** [`examples/camerontjs-dot_compare_fn`](examples/camerontjs-dot_compare_fn), where this is kept as a documented failure.

---

## 9. `TypeError: validator must be callable`

**Symptom.** `check()` or `acheck()` raises `TypeError: validator must be callable, got <type>` before any LLM call is made.

**Cause.** From v0.5.5, a non-callable `validator` is rejected upfront. Before that it failed every attempt and returned `UNCERTAIN`, after spending all retries. The usual mistake is passing the result of calling a function (a `bool` or a `tuple`) instead of the function itself.

**What to do.** Pass the function: `validator=is_valid` rather than `validator=is_valid(answer)`.

---

## 10. Accuracy drops on reasoning-heavy tasks (maths, multi-step questions)

**Symptom.** `booth.check()` gets fewer questions right than the same model called directly, mostly on questions that need working out (maths word problems, multi-step reasoning).

**Cause.** BOOTH's prompt ends with "Output ONLY the JSON object, nothing else." A small model may skip its step-by-step reasoning and answer straight away. In the benchmark in `examples/Vedantgitbot_latency_accuracy` on `qwen2.5:7b`, GSM8K accuracy fell from 97.5% to 35.0% under the JSON-only prompt, and replies shrank from about 261 to 36 tokens. Letting the model reason before the JSON brought GSM8K back to 92.5%. On `gemma3:12b` the shorter replies did not reproduce (about 247 against 220 tokens), and the larger cost was the `AMBIGUOUS` gate: 11 questions were rejected, 10 of them on TruthfulQA. The samples are small, so treat these as a signal and not a measurement. Details are in the example's `RESULTS.md` and in issue [#33](https://github.com/Vedantgitbot/booth/issues/33).

In these runs the model's self-reported confidence and its `AMBIGUOUS` flag did not separate right answers from wrong ones (see entries 2 and 5).

**What to do.**

1. Measure on your own model: `python examples/Vedantgitbot_latency_accuracy/run_example.py --model <tag>`, then compare the plain and BOOTH arms.
2. If your tasks need reasoning, give the model room to reason before the JSON. From v0.6.0, pass `suffix=booth.REASONING_SUFFIX`:

```python
import booth

result = booth.check(
    call_llm,
    "What is half of 12 * 4?",
    suffix=booth.REASONING_SUFFIX,
)
```

`REASONING_SUFFIX` asks for the same JSON object as the default, but lets the model think first and put the JSON last. BOOTH uses the last valid top-level JSON object in the reply, so reasoning text before it is fine, and any draft object inside that reasoning is ignored. The text before the object is kept in `attempt.pre_json_text` if you want to log it.

The same suffix is sent on the first call and on every retry. With a custom suffix, the parse-failure retry no longer says "no commentary", so it does not contradict a suffix that asks for reasoning.

To write your own, pass any non-empty string. It replaces the whole default instruction, including the JSON schema, so it must still ask for a JSON object with `answer` and `confidence`. It is used as given, so start it with a newline (`"\n\n..."`) or it will run into the end of your prompt. `booth.DEFAULT_SUFFIX` shows the default text to copy from.

**Limits.**

- Reasoning replies are longer. If your client caps output tokens, set the limit high enough for the working plus the JSON. A reply cut off before the JSON is a parse failure and spends a retry.
- It is slower: about 1.8 times the plain call's latency on Qwen 7B in the benchmark.
- It did not help trivia or multiple-choice questions in these runs.
- The 92.5% figure above was measured with an equivalent wording before `suffix=` existed. Re-run the benchmark with `REASONING_SUFFIX` to check it on your model.
- On v0.5.9 or earlier there is no `suffix=`. Upgrade, or wrap your `call_fn` and replace BOOTH's closing sentence, which breaks if that wording changes.

**Seen in:** [`examples/Vedantgitbot_latency_accuracy`](examples/Vedantgitbot_latency_accuracy), issues [#32](https://github.com/Vedantgitbot/booth/issues/32) and [#33](https://github.com/Vedantgitbot/booth/issues/33).