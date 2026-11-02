# BOOTH Use Cases

BOOTH is a checkpoint layer for LLM applications. It is designed for situations where an LLM response should **not simply be accepted because the model returned something**.

BOOTH can check whether a response:

- can be parsed into the expected structure,
- identifies meaningful ambiguity,
- satisfies an application-defined validator,
- reports enough confidence,
- can be improved through a retry,
- or agrees with evidence supplied by your application.

BOOTH does **not** independently establish that an answer is true. That distinction is important.

This document covers when BOOTH fits and when it does not. For how each function, type, and property works, see the [Tutorial](TUTORIAL.md). This version describes `v0.5.8`.

---

# 1. What BOOTH Is Good At

> **BOOTH is a checkpoint around an LLM response, not a source of truth.**

An ordinary LLM call looks like:

```text
prompt → LLM → answer
```

BOOTH changes the application flow to:

```text
prompt
  ↓
LLM
  ↓
response
  ↓
BOOTH checkpoint
  ├── parse?
  ├── ambiguous?
  ├── application validation?
  ├── confidence threshold?
  └── retry if appropriate
  ↓
BoothResult
```

This makes BOOTH useful when your application needs a structured decision about whether an LLM response should be accepted, retried, or rejected.

---

# 2. Good Use Case: Structured LLM Outputs

One of the most direct uses for BOOTH is when an LLM is expected to return a predictable JSON structure.

For example, your application asks:

```text
Classify this support ticket.
```

BOOTH expects the model to return a JSON object such as:

```json
{
  "ambiguous": false,
  "interpretations": [],
  "chosen_interpretation": null,
  "answer": "billing",
  "confidence": 0.94
}
```

BOOTH checks whether the response can be parsed and whether the required values are usable. This lets your application distinguish a valid response from a malformed one, rather than passing raw model text downstream.

If your provider has its own response format (JSON mode, tool calling, or a custom string encoding), pass a synchronous `parse_fn` to `check()` or `acheck()` to turn the returned string into the `answer` and `confidence` dictionary BOOTH expects. The result still goes through the same validation, retry, confidence, and ambiguity checks. Two limits to keep in mind: `call_fn` must still return a string, and BOOTH still sends its own JSON instructions in the prompt, so `parse_fn` changes parsing, not what the model is asked.

### Good fit

Use BOOTH when malformed model output would otherwise cause problems in your application:

- classification
- extraction
- routing
- structured decisions
- categorization
- lightweight agent decisions
- machine-readable LLM outputs

---

# 3. Good Use Case: Ambiguous User Questions

BOOTH explicitly supports ambiguity detection.

```text
What's the capital of Georgia?
```

There are at least two reasonable interpretations: Georgia the country and Georgia the US state. BOOTH allows the model to report:

```json
{
  "ambiguous": true,
  "interpretations": ["Georgia the country", "Georgia the US state"],
  "chosen_interpretation": "Georgia the country",
  "answer": "Tbilisi",
  "confidence": 0.82
}
```

The application can then decide what to do:

```python
if result.status == booth.AMBIGUOUS:
    ask_user_to_clarify(result.interpretations)
```

This is a good use of BOOTH because ambiguity is something an ordinary LLM call may hide behind a confident-looking answer. See section 26 for its limits.

---

# 4. Good Use Case: Application-Specific Validation

BOOTH becomes particularly useful when your application knows a rule that the model itself does not reliably enforce.

```python
def validate_order_id(answer):
    return answer.startswith("ORD-")

result = booth.check(
    call_llm,
    "What is the order ID?",
    validator=validate_order_id,
)
```

Other examples:

```python
def validate_country_code(answer):
    return len(answer) == 2

def validate_category(answer):
    return answer in {"billing", "technical", "shipping", "other"}

def validate_number(answer):
    try:
        float(answer)
        return True
    except ValueError:
        return False
```

This is one of BOOTH's strongest use cases because the application, rather than the model, defines what constitutes an acceptable output.

---

# 5. Good Use Case: Repairing Bad LLM Outputs

BOOTH can retry an answer that failed a checkpoint.

```python
result = booth.check(call_llm, prompt, max_retries=1)
```

- If the first response cannot be parsed, BOOTH asks the model to produce the required format.
- If validation fails, BOOTH gives the model the validation failure and asks it to correct the answer.
- If confidence is below the threshold, BOOTH asks the model to reconsider.
- If the call itself failed, BOOTH asks again with the original prompt.

```text
LLM attempt → failed checkpoint → repair prompt → LLM retry → checkpoint again
```

If the retry succeeds, BOOTH returns `REPAIRED`. This is useful when a small number of additional model calls can improve the reliability of a workflow.

---

# 6. Good Use Case: Evidence-Gated Answers

BOOTH also provides `check_with_evidence()`, which is useful when your application already has evidence and wants to compare an answer against it.

```python
answer = "The refund period is 30 days."
evidence = ["Customers may request a refund within 30 days of purchase."]
```

Your application supplies a comparison function:

```python
def compare(answer, evidence):
    ...
```

BOOTH turns the comparison result into a structured result. This is useful for:

- document question answering
- policy assistants
- internal knowledge systems
- retrieval-based applications
- evidence-supported summarization
- grounded extraction

However, there is a very important limitation.

---

# 7. Evidence Does Not Automatically Mean Truth

`check_with_evidence()` does **not** retrieve, verify, or authenticate evidence. You provide `answer`, `evidence`, and `compare_fn`, and BOOTH calls your `compare_fn`. Therefore:

```text
bad evidence → bad comparison → bad decision
```

is still possible. If your comparison function simply returns `True`, BOOTH will accept the answer. BOOTH cannot know that your comparison function is meaningless. Likewise, if your evidence comes from an unreliable source, BOOTH does not establish that the source is authoritative.

So "BOOTH accepted it" should not be read as "BOOTH proved it is true." It means the answer passed the checkpoint your application configured.

A `check_with_evidence()` result carries `result.reason`, `result.detail`, and the computed `result.checker_failed`. These separate "your `compare_fn` itself broke" (`COMPARE_FAILED` or `INVALID_SCORE`, with `checker_failed` `True`) from "the comparison ran and the answer disagreed" (`EVIDENCE_DISAGREES`). They cannot tell you whether a *passing* comparison is trustworthy. A comparator that always returns `True` never sets `reason`, because from BOOTH's perspective nothing went wrong.

---

# 8. Good Use Case: Human-in-the-Loop Systems

BOOTH can handle straightforward cases automatically while escalating uncertain ones.

```python
result = booth.check(call_llm, prompt, threshold=0.8, max_retries=1)

if result.status in (booth.ACCEPTED, booth.REPAIRED):
    return result.answer

if result.status == booth.AMBIGUOUS:
    return ask_user_for_clarification()

return escalate_to_human()
```

This gives the application explicit states instead of treating every model response as equivalent. A useful policy might be:

```text
ACCEPTED   → continue automatically
REPAIRED   → continue automatically, possibly with logging
AMBIGUOUS  → ask the user
UNCERTAIN  → escalate or fail safely
BLOCKED    → do not accept the answer
```

The exact policy is application-specific.

For `check()` results, `result.call_failed` is a useful routing signal on top of `status`: `True` means your model call is broken (bad key, retired model, network) and belongs on an engineering alert, while `UNCERTAIN` with `call_failed` `False` means the model answered but not acceptably.

For `check_with_evidence()` results, `result.checker_failed` plays the same role: `True` usually belongs on an engineering alert queue (your comparator broke), while a `checker_failed=False` `UNCERTAIN` or `BLOCKED` result (incomplete input, or a real disagreement) usually belongs on a human-review or retry queue.

---

# 9. Good Use Case: Logging and Evaluation

BOOTH exposes individual attempts through `result.attempts`. Each `Attempt` contains:

```python
attempt.raw_text
attempt.answer
attempt.confidence
attempt.parse_ok
attempt.error
attempt.ambiguous
attempt.interpretations
attempt.passed_validation
attempt.validation_error
attempt.call_failed
attempt.parsed
```

This can be useful for debugging prompts, measuring retry rates, evaluating model behavior, investigating validation failures, monitoring malformed outputs, comparing models, and building internal evaluation datasets.

```python
for attempt in result.attempts:
    log({
        "confidence": attempt.confidence,
        "parse_ok": attempt.parse_ok,
        "call_failed": attempt.call_failed,
        "validation": attempt.passed_validation,
        "error": attempt.error,
    })
```

`result.to_dict()` gives the whole result, including attempts, as a JSON-serializable dictionary.

`check_with_evidence()` results have no attempts (the list is always empty), so the equivalent logging fields for that path are `result.reason` and `result.detail`:

```python
if result.method == "evidence" and not result.ok:
    log({
        "status": result.status,
        "reason": result.reason,
        "detail": result.detail,
        "checker_failed": result.checker_failed,
    })
```

---

# 10. Good Use Case: Lightweight LLM Classification

BOOTH can work well for narrow classification tasks.

```text
Is this ticket: billing, technical, shipping, or other?
```

Combined with a validator:

```python
VALID_CATEGORIES = {"billing", "technical", "shipping", "other"}

def validate(answer):
    return answer in VALID_CATEGORIES
```

The application now has both model judgment and an application constraint. This is substantially more useful than relying on confidence alone.

---

# 11. Good Use Case: Routing Decisions

Another useful pattern is using an LLM to choose which workflow should handle a request: `billing`, `technical_support`, `sales`, or `human_agent`.

BOOTH can ensure that the response is parseable, that the answer satisfies a validator, that ambiguity is surfaced, and that low-confidence responses can be retried.

```python
def validate_route(answer):
    return answer in {"billing", "technical_support", "sales", "human_agent"}
```

This can be a practical checkpoint before sending the request into an automated workflow.

---

# 12. Good Use Case: Cheap First-Level Guardrails

BOOTH can sit between the LLM and your application logic without owning the rest of the system. It suits applications that already have:

- an LLM client,
- their own retrieval system,
- their own validators,
- their own business logic,
- their own logging,
- their own retry policy outside BOOTH where necessary.

BOOTH does not require you to replace those components.

---

# 13. Where BOOTH Is NOT Enough

This is the more important part. BOOTH should **not** be treated as a general-purpose reliability guarantee for LLM output. There are several things BOOTH does not independently establish.

---

# 14. BOOTH Does Not Prove Factual Correctness

This is the biggest limitation.

The confidence value comes from the model. BOOTH asks the model to estimate "What is the probability that my answer is correct?", and does not independently calculate that probability. Therefore `confidence = 0.99` does **not** mean "99% objectively verified." It means the model reported a confidence of `0.99`.

A model can be confidently wrong, and BOOTH cannot eliminate that problem.

A small local-model run shows this: [`examples/rk042_ollama_qwen-3b/`](examples/rk042_ollama_qwen-3b/RESULTS.md) had a 3B model (`qwen2.5-coder:3b`) accept `"object"` as the name of an unknown next-door neighbor at confidence 1.0, even with schema-constrained output. It is a four-question run on one model, not a benchmark, and it records a different arithmetic result in an earlier exploratory run, so it illustrates a failure mode rather than measuring how often it occurs.

---

# 15. Do Not Use BOOTH as a Truth Oracle

Avoid architectures like:

```python
result = booth.check(call_llm, question, threshold=0.95)

if result.ok:
    assume_fact_is_true()
```

A passing result means the response satisfied BOOTH's configured checks. It does not mean an external authority has confirmed the fact.

---

# 16. Do Not Rely on Confidence Alone for High-Stakes Decisions

Confidence is a useful signal. It should not be treated as proof.

Be especially careful with applications involving:

- medical decisions
- legal conclusions
- financial decisions
- safety-critical systems
- identity or access decisions
- employment decisions
- high-impact eligibility decisions
- irreversible automated actions

In these situations, a high model-reported confidence should not be the only reason an application takes action. Use authoritative data, deterministic rules, domain-specific validation, and human review where required. BOOTH can still be one component of such a system, but it should not be the final authority.

---

# 17. Do Not Use BOOTH as a Retrieval System

BOOTH does not search the web, query a database, retrieve documents, find citations, fetch APIs, or look up records. If your application needs evidence, your application must obtain it:

```text
retrieval system → evidence → BOOTH → comparison
```

not:

```text
BOOTH → find evidence
```

---

# 18. Do Not Use BOOTH as a RAG Framework

BOOTH can be used **inside** a RAG application. It is not itself a RAG framework.

```text
user question → retriever → documents → LLM → answer → BOOTH → evidence agreement
```

That is a reasonable architecture. But BOOTH does not provide the retriever, vector database, document chunking, embeddings, reranking, or citation system. Those remain application responsibilities.

---

# 19. Do Not Use BOOTH as a Security Boundary

BOOTH is not a security system. Do not assume that `result.ok` means "safe to execute an arbitrary action."

BOOTH should not be your only protection before executing shell commands, modifying production infrastructure, sending money, deleting data, changing permissions, granting access, sending irreversible messages, or performing destructive operations. Use deterministic authorization and safety controls appropriate to the operation. An LLM checkpoint is not a replacement for those controls.

---

# 20. Do Not Use BOOTH to Validate Arbitrary Complex Logic

A validator is only as strong as the validator you provide. This provides no meaningful protection:

```python
def validate(answer):
    return True
```

A weak validator can accept incorrect answers. A validator should encode a property that can actually be checked.

Good:

```python
def validate(answer):
    return answer in VALID_VALUES
```

Potentially weak:

```python
def validate(answer):
    return len(answer) > 2
```

The second may technically pass but tells you very little about whether the answer is correct.

---

# 21. Do Not Assume Retry Means Correction

BOOTH can retry an answer. That does not guarantee the retry is better. The model may make the same mistake, make a different mistake, become less confident, or become more confident while remaining wrong.

```text
Attempt 1: confidence 0.62, wrong
Attempt 2: confidence 0.94, still wrong
```

BOOTH can report the second attempt as acceptable if it satisfies the configured checks. Retries are best understood as **an opportunity for the model to reconsider, not an independent verification process.**

---

# 22. Do Not Assume Multiple Attempts Are Independent

With `max_retries=3` you should not think of four independent opinions. The retry prompt explicitly asks the model to reconsider the previous response, so the attempts are related. A retry can improve formatting or correct an obvious mistake, but repeated model calls do not automatically provide independent evidence.

---

# 23. Do Not Use BOOTH When Deterministic Logic Is Better

If a rule can be implemented directly in code, prefer code. Do not ask an LLM "Is 37 greater than 20?" and then validate the answer with BOOTH if your application can simply compute `37 > 20`.

Deterministic validation is preferable for numeric constraints, enums, dates with known formats, required fields, permissions, business rules, state transitions, and schema constraints. BOOTH is most useful around the parts where an LLM is actually being used.

---

# 24. Do Not Use BOOTH Just Because an LLM Is Present

Not every LLM call needs BOOTH. If your application is generating a poem, a marketing slogan, a casual reply, or a creative story, there may be no meaningful notion of accepted, repaired, or blocked unless your application has a concrete acceptance criterion. BOOTH becomes valuable when the output needs to pass a meaningful checkpoint.

---

# 25. Creative Generation Is Usually a Poor Fit

BOOTH's strongest model is question, then answer, then checkpoint. Creative generation is different. For "Write a funny story about a cat" there is no universal confidence threshold that establishes that one story is "correct."

You could build a validator for properties such as "under 500 words," "contains a cat," or "contains no prohibited terms," and BOOTH may then be useful as part of the workflow. But the value comes from those concrete constraints, not from BOOTH determining whether the story is good.

---

# 26. Ambiguity Detection Is Not Perfect

BOOTH's ambiguity mechanism depends on the LLM correctly identifying multiple reasonable interpretations. It can miss ambiguity, and it can flag ambiguity where your application does not care. `AMBIGUOUS` should be treated as a useful signal, not a complete ambiguity detector.

In the Ollama examples, a local model answered the Georgia question without flagging the ambiguity (see [TROUBLESHOOTING](TROUBLESHOOTING.md) entry 5). For particularly important inputs, deterministic disambiguation rules or explicit user clarification may be better.

---

# 27. Evidence Agreement Is Only as Good as `compare_fn`

This deserves special emphasis. With `check_with_evidence(answer, evidence, compare_fn)`, BOOTH delegates the actual comparison to `compare_fn`. If the function is strong, the checkpoint can be useful. If it is weak, the checkpoint is weak. For example:

```python
def compare(answer, evidence):
    return 0.9
```

produces a high score regardless of the relationship between answer and evidence. BOOTH cannot fix a bad comparator.

Note the distinction from `result.checker_failed`: that property is `True` when `compare_fn` *crashes* or returns something unusable as a score, a broken comparator BOOTH can detect. A comparator that runs without error but is badly designed, like the `return 0.9` example, produces a normal-looking `ACCEPTED` or `BLOCKED` result with `checker_failed=False`.

Two real runs in `examples/` show what a better comparator buys you, and where it still falls short:

- [`examples/camerontjs-dot_compare_fn/`](examples/camerontjs-dot_compare_fn/RESULTS.md) runs a keyword matcher and an NLI model on the same 10 hand-written cases. The keyword matcher accepted "90 days" against a 30-day policy; the NLI model blocked it. It also shows a limit: when one passage supported the claim and another contradicted it, a comparator that returns only the best entailment score hid the contradiction and BOOTH returned `ACCEPTED`. That is a property of the comparator, not of BOOTH, but a single returned number makes it easy to do. Decide how your comparator treats conflicting passages.
- [`examples/Harithalakshmikt_langchain_flan/`](examples/Harithalakshmikt_langchain_flan/RESULTS.md) shows the opposite failure: an over-strict NLI comparator blocked correct short answers. Test an entailment comparator on correct answers as well as wrong ones.

Both are small, hand-built demonstrations, not accuracy benchmarks.

---

# 28. `BLOCKED` Does Not Mean "Factually False"

When `check_with_evidence()` produces `BLOCKED`, it means the supplied comparison did not meet the configured evidence threshold (or a boolean comparator returned `False`). This case always carries `result.reason == booth.EVIDENCE_DISAGREES`.

It does not necessarily mean the answer is definitely false. Possible explanations include:

- the answer is wrong
- the evidence is insufficient
- the evidence is irrelevant
- the comparator is too strict
- the comparator is poorly designed
- the threshold is too high

`result.detail` gives you the numeric score and threshold for a score-based comparator (for example `"score 0.62 below evidence_threshold 0.8"`), which is a start, but it cannot tell you which explanation is true. That judgment requires your own domain knowledge of the comparator and the evidence.

---

# 29. `UNCERTAIN` Is Not a Diagnosis

`UNCERTAIN` means BOOTH could not accept the result. It does not tell you that the answer is definitely wrong.

For `check()` and `acheck()` results, `UNCERTAIN` can happen because:

- the model returned malformed JSON (or your `parse_fn` rejected the response),
- the validator failed,
- confidence never reached the threshold,
- or the model call failed.

Inspect `result.method`, `result.call_failed`, and `result.attempts` when you need to understand why.

For a `check_with_evidence()` result, `UNCERTAIN` means one of four things: the answer was empty, the evidence was empty, `compare_fn` crashed, or `compare_fn` returned something unusable as a score. These are distinguishable via `result.reason` (`EMPTY_ANSWER`, `NO_EVIDENCE`, `COMPARE_FAILED`, `INVALID_SCORE`). As always, a specific `reason` tells you *why BOOTH couldn't accept the result*, not whether the underlying answer was correct.

---

# 30. Be Careful With High Latency or Cost Requirements

Retries mean additional LLM calls. `max_retries=2` can result in up to 3 model calls, so BOOTH can increase latency, token usage, and API cost. Use retries deliberately. If your application is extremely latency-sensitive, you may prefer `max_retries=0` and handle failures elsewhere.

Small local models can also be slow on a malformed response: in the 3B Ollama run, default-format calls took 37 to 53 seconds against 10 to 17 for schema-constrained calls. That is one model on one machine, so measure your own setup.

---

# 31. Streaming Applications May Not Fit Naturally

BOOTH operates around a completed response. If your application is built around token-by-token streaming, BOOTH is not a streaming validation framework. A common architecture is:

```text
LLM stream → collect final response → BOOTH checkpoint
```

rather than attempting to checkpoint every token.

---

# 32. BOOTH Does Not Replace Schema Validation

BOOTH's parsing checks whether the model returned a usable JSON object with the expected core fields. It should not be confused with a complete schema-validation framework. If your application requires a strict schema such as:

```json
{
  "customer_id": "...",
  "amount": 0,
  "currency": "...",
  "items": [...]
}
```

you should still use an appropriate deterministic schema validator. BOOTH can sit before or around that validation:

```text
LLM → BOOTH parsing → application schema validation → business rules
```

Likewise, a provider's schema-constrained output (for example Ollama's `format`) constrains the *shape* of the response, not whether the answer is correct. In the 3B Ollama example every schema-formatted response parsed, while one wrong answer was still accepted at confidence 1.0.

---

# 33. BOOTH Does Not Protect Against Prompt Injection by Itself

BOOTH does not provide a complete prompt-injection defense. If an LLM is processing untrusted content such as web pages, emails, documents, or user-provided text, BOOTH does not make that content safe. You still need appropriate prompt isolation, tool authorization, data-flow controls, output validation, least-privilege access, and deterministic security checks. BOOTH can validate the resulting answer, but it is not a complete agent-security solution.

---

# 34. A Practical Decision Rule

A useful question to ask is:

> **What concrete property do I want to check after the LLM responds?**

If you can answer that clearly, BOOTH may be useful.

| Question | Fit |
| --- | --- |
| "Is the response parseable?" | Good fit |
| "Did the model identify that the question is ambiguous?" | Good fit |
| "Does the answer satisfy my application rule?" | Good fit |
| "Did the answer meet my evidence comparator?" | Good fit |
| "Can BOOTH tell me whether this fact is objectively true?" | No |
| "Can BOOTH guarantee the model will not hallucinate?" | No |
| "Can BOOTH make an autonomous agent safe?" | No |
| "Can BOOTH replace authorization checks?" | No |

---

# 35. A Good Architecture

A strong use of BOOTH is to make it **one checkpoint among several**.

```text
        ┌──────────────────┐
        │   User Request   │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │       LLM        │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │      BOOTH       │
        │ • parse          │
        │ • ambiguity      │
        │ • validator      │
        │ • confidence     │
        │ • retry          │
        └────────┬─────────┘
                 ▼
     ┌────────────────────────┐
     │ Application Validation │
     └───────────┬────────────┘
                 ▼
        ┌──────────────────┐
        │  Business Rules  │
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │ Authorized Action│
        └──────────────────┘
```

BOOTH should usually be **part of the control system**, not the entire control system.

---

# 36. When BOOTH Is Probably Worth Adding

BOOTH is a good candidate when several of these are true:

- You already use an LLM.
- The response needs a machine-readable structure.
- Ambiguous questions are a meaningful problem.
- You have application-specific validation rules.
- A retry can realistically repair common failures.
- You want a structured result instead of raw model text.
- You want to inspect individual attempts.
- You have evidence and a meaningful comparison function.
- Occasional additional LLM calls are acceptable.
- You want a lightweight checkpoint without adopting a larger orchestration system.

---

# 37. When BOOTH Is Probably Not Worth Adding

BOOTH may be unnecessary when:

- The output is purely creative.
- There is no meaningful acceptance criterion.
- A deterministic function can solve the problem directly.
- You already have a complete validation or checkpoint system.
- Additional LLM calls are unacceptable.
- You only need basic JSON or schema validation.
- You need a retrieval system rather than an output checkpoint.
- You need authoritative fact verification.
- You need a security or authorization boundary.
- The application cannot tolerate the possibility of model-reported confidence being wrong.

---

# 38. BOOTH in One Sentence

> **BOOTH is a lightweight checkpoint layer that helps an application decide whether to accept, retry, inspect, or reject an LLM response based on parsing, ambiguity, application-defined validation, model-reported confidence, and optional evidence agreement.**

And equally important:

> **BOOTH does not independently prove that an LLM answer is true, safe, authorized, or fit for a high-stakes decision.**

---

# 39. Final Guidance

Use BOOTH when you want **a checkpoint around an LLM**. Do not use BOOTH as a substitute for truth, retrieval, authorization, security, schema validation, business logic, domain expertise, or human judgment.

The strongest BOOTH architecture is not:

```text
LLM → BOOTH → trust everything
```

It is:

```text
LLM → BOOTH checkpoint → deterministic/application checks → business policy → appropriate human or automated action
```

BOOTH is most valuable when it makes uncertainty and failure **explicit**, rather than pretending that an LLM response has become guaranteed simply because it passed a checkpoint.