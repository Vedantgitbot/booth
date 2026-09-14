# BOOTH Use Cases

BOOTH is a checkpoint layer for LLM applications.

It is designed for situations where an LLM response should **not simply be accepted because the model returned something**.

BOOTH can check whether a response:

* can be parsed into the expected structure,
* identifies meaningful ambiguity,
* satisfies an application-defined validator,
* reports enough confidence,
* can be improved through a retry,
* or agrees with evidence supplied by your application.

BOOTH does **not** independently establish that an answer is true.

That distinction is important.

---

# 1. What BOOTH Is Good At

The simplest way to think about BOOTH is:

> **BOOTH is a checkpoint around an LLM response, not a source of truth.**

An ordinary LLM call often looks like:

```text
prompt
  ↓
LLM
  ↓
answer
```

BOOTH changes the application flow to:

```text
prompt
  ↓
LLM
  ↓
structured response
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

BOOTH expects the model to return a JSON object containing fields such as:

```json
{
  "ambiguous": false,
  "interpretations": [],
  "chosen_interpretation": null,
  "answer": "billing",
  "confidence": 0.94
}
```

BOOTH checks whether the response can be parsed and whether the required values are usable.

This is useful when your application needs to distinguish:

```text
valid response
        vs.
malformed response
```

rather than blindly passing raw model text downstream.

### Good fit

Use BOOTH when malformed model output would otherwise cause problems in your application.

Examples:

* classification
* extraction
* routing
* structured decisions
* categorization
* lightweight agent decisions
* machine-readable LLM outputs

---

# 3. Good Use Case: Ambiguous User Questions

BOOTH explicitly supports ambiguity detection.

For example:

```text
What's the capital of Georgia?
```

There are at least two reasonable interpretations:

```text
Georgia the country
Georgia the US state
```

BOOTH allows the model to report:

```json
{
  "ambiguous": true,
  "interpretations": [
    "Georgia the country",
    "Georgia the US state"
  ],
  "chosen_interpretation": "Georgia the country",
  "answer": "Tbilisi",
  "confidence": 0.82
}
```

The application can then decide what to do.

For example:

```python
if result.status == booth.AMBIGUOUS:
    ask_user_to_clarify(result.interpretations)
```

This is a good use of BOOTH because ambiguity is something an ordinary LLM call may otherwise hide behind a confident-looking answer.

---

# 4. Good Use Case: Application-Specific Validation

BOOTH becomes particularly useful when your application knows a rule that the model itself does not reliably enforce.

For example:

```python
def validate_order_id(answer):
    return answer.startswith("ORD-")
```

Then:

```python
result = booth.check(
    call_llm,
    "What is the order ID?",
    validator=validate_order_id,
)
```

The validator provides an application-level constraint.

Other examples:

```python
def validate_country_code(answer):
    return len(answer) == 2
```

```python
def validate_category(answer):
    return answer in {
        "billing",
        "technical",
        "shipping",
        "other",
    }
```

```python
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

For example:

```python
result = booth.check(
    call_llm,
    prompt,
    max_retries=1,
)
```

If the first response cannot be parsed, BOOTH asks the model to produce the required format.

If validation fails, BOOTH gives the model the validation failure and asks it to correct the answer.

If confidence is below the configured threshold, BOOTH asks the model to reconsider.

This creates a useful pattern:

```text
LLM attempt
    ↓
failed checkpoint
    ↓
repair prompt
    ↓
LLM retry
    ↓
checkpoint again
```

If the retry succeeds, BOOTH returns:

```python
REPAIRED
```

This is useful when a small number of additional model calls can improve the reliability of a workflow.

---

# 6. Good Use Case: Evidence-Gated Answers

BOOTH also provides:

```python
check_with_evidence()
```

This is useful when your application already has evidence and wants to compare an answer against it.

For example:

```python
answer = "The refund period is 30 days."

evidence = [
    "Customers may request a refund within 30 days of purchase."
]
```

Your application supplies a comparison function:

```python
def compare(answer, evidence):
    ...
```

BOOTH then turns the comparison result into a structured result.

This is useful for workflows such as:

* document question answering
* policy assistants
* internal knowledge systems
* retrieval-based applications
* evidence-supported summarization
* grounded extraction

However, there is a very important limitation.

---

# 7. Evidence Does Not Automatically Mean Truth

`check_with_evidence()` does **not** retrieve, verify, or authenticate evidence.

You provide:

```python
answer
evidence
compare_fn
```

BOOTH calls your `compare_fn`.

Therefore:

```text
bad evidence
    ↓
bad comparison
    ↓
bad decision
```

is still possible.

For example, if your comparison function simply does:

```python
return True
```

BOOTH will accept the answer.

BOOTH cannot know that your comparison function is meaningless.

Likewise, if your evidence comes from an unreliable source, BOOTH does not independently establish that the source is authoritative.

So this:

```text
"BOOTH verified it"
```

should generally **not** be interpreted as:

```text
"BOOTH proved it is true."
```

It means the answer passed the checkpoint that your application configured.

---

# 8. Good Use Case: Human-in-the-Loop Systems

BOOTH can be useful when the application wants to automatically handle straightforward cases while escalating uncertain cases.

For example:

```python
result = booth.check(
    call_llm,
    prompt,
    threshold=0.8,
    max_retries=1,
)

if result.status in (booth.ACCEPTED, booth.REPAIRED):
    return result.answer

if result.status == booth.AMBIGUOUS:
    return ask_user_for_clarification()

return escalate_to_human()
```

This gives the application explicit states instead of treating every model response as equivalent.

A useful policy might be:

```text
ACCEPTED
    → continue automatically

REPAIRED
    → continue automatically, possibly with logging

AMBIGUOUS
    → ask the user

UNCERTAIN
    → escalate or fail safely

BLOCKED
    → do not accept the answer
```

The exact policy is application-specific.

---

# 9. Good Use Case: Logging and Evaluation

BOOTH exposes individual attempts through:

```python
result.attempts
```

Each `Attempt` contains information such as:

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
attempt.parsed
```

This can be useful for:

* debugging prompts
* measuring retry rates
* evaluating model behavior
* investigating validation failures
* monitoring malformed outputs
* comparing models
* building internal evaluation datasets

For example:

```python
for attempt in result.attempts:
    log({
        "confidence": attempt.confidence,
        "parse_ok": attempt.parse_ok,
        "validation": attempt.passed_validation,
        "error": attempt.error,
    })
```

BOOTH therefore works well as an instrumentation point around an LLM workflow.

---

# 10. Good Use Case: Lightweight LLM Classification

BOOTH can work well for relatively narrow classification tasks.

Example:

```text
Is this ticket:
billing, technical, shipping, or other?
```

Combined with a validator:

```python
VALID_CATEGORIES = {
    "billing",
    "technical",
    "shipping",
    "other",
}

def validate(answer):
    return answer in VALID_CATEGORIES
```

The application now has both:

```text
model judgment
+
application constraint
```

This is substantially more useful than relying on confidence alone.

---

# 11. Good Use Case: Routing Decisions

Another useful pattern is using an LLM to choose which workflow should handle a request.

For example:

```text
billing
technical_support
sales
human_agent
```

BOOTH can ensure that:

1. the response is parseable,
2. the answer satisfies a validator,
3. ambiguity is surfaced,
4. low-confidence responses can be retried.

Example:

```python
def validate_route(answer):
    return answer in {
        "billing",
        "technical_support",
        "sales",
        "human_agent",
    }
```

This can be a practical checkpoint before sending the request into an automated workflow.

---

# 12. Good Use Case: Cheap First-Level Guardrails

BOOTH can be useful when you want a relatively small checkpoint layer without introducing a larger orchestration framework.

It can sit between:

```text
LLM
```

and:

```text
application logic
```

without owning the rest of the system.

This makes it suitable for applications that already have:

* an LLM client,
* their own retrieval system,
* their own validators,
* their own business logic,
* their own logging,
* their own retry policy outside BOOTH where necessary.

BOOTH does not require you to replace those components.

---

# 13. Where BOOTH Is NOT Enough

This is the more important part.

BOOTH should **not** be treated as a general-purpose reliability guarantee for LLM output.

There are several things BOOTH does not independently establish.

---

# 14. BOOTH Does Not Prove Factual Correctness

This is the biggest limitation.

The confidence value comes from the model.

BOOTH asks the model to estimate:

```text
"What is the probability that my answer is correct?"
```

It does not independently calculate that probability.

Therefore:

```text
confidence = 0.99
```

does **not** mean:

```text
99% objectively verified
```

It means the model reported a confidence of `0.99`.

A model can be confidently wrong.

BOOTH cannot eliminate that fundamental problem.

---

# 15. Do Not Use BOOTH as a Truth Oracle

Avoid architectures like:

```python
result = booth.check(
    call_llm,
    question,
    threshold=0.95,
)

if result.ok:
    assume_fact_is_true()
```

That is not what BOOTH guarantees.

A passing result means the response satisfied BOOTH's configured checks.

It does not mean that an external authority has confirmed the fact.

---

# 16. Do Not Rely on Confidence Alone for High-Stakes Decisions

Confidence is useful as a signal.

It should not be treated as proof.

Be especially careful with applications involving:

* medical decisions
* legal conclusions
* financial decisions
* safety-critical systems
* identity or access decisions
* employment decisions
* high-impact eligibility decisions
* irreversible automated actions

In these situations, a high model-reported confidence should not be the only reason an application takes action.

Use appropriate authoritative data, deterministic rules, domain-specific validation, and human review where required.

BOOTH can still be one component of such a system, but it should not be the final authority.

---

# 17. Do Not Use BOOTH as a Retrieval System

BOOTH does not retrieve information.

It does not:

```text
search the web
query a database
retrieve documents
find citations
fetch APIs
look up records
```

If your application needs evidence, your application must obtain it.

The architecture is:

```text
retrieval system
       ↓
evidence
       ↓
BOOTH
       ↓
comparison
```

not:

```text
BOOTH
  ↓
find evidence
```

---

# 18. Do Not Use BOOTH as a RAG Framework

BOOTH can be used **inside** a RAG application.

It is not itself a RAG framework.

A RAG application might look like:

```text
user question
      ↓
retriever
      ↓
documents
      ↓
LLM
      ↓
answer
      ↓
BOOTH
      ↓
evidence agreement
```

That is a reasonable architecture.

But BOOTH does not provide the retriever, vector database, document chunking, embeddings, reranking, or citation system.

Those remain application responsibilities.

---

# 19. Do Not Use BOOTH as a Security Boundary

BOOTH is not a security system.

Do not assume that:

```python
result.ok
```

means:

```text
safe to execute arbitrary action
```

For example, BOOTH should not be your only protection before:

* executing shell commands,
* modifying production infrastructure,
* sending money,
* deleting data,
* changing permissions,
* granting access,
* sending irreversible messages,
* performing destructive operations.

Use deterministic authorization and safety controls appropriate to the operation.

An LLM checkpoint is not a replacement for those controls.

---

# 20. Do Not Use BOOTH to Validate Arbitrary Complex Logic

A validator is only as strong as the validator you provide.

This:

```python
def validate(answer):
    return True
```

provides no meaningful protection.

Likewise, a weak validator can accept incorrect answers.

A validator should encode a property that can actually be checked.

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

The second may technically be valid but tells you very little about whether the answer is correct.

---

# 21. Do Not Assume Retry Means Correction

BOOTH can retry an answer.

That does not guarantee the retry is better.

The model may:

```text
make the same mistake
make a different mistake
become less confident
become more confident while remaining wrong
```

For example:

```text
Attempt 1
confidence = 0.62
wrong

Attempt 2
confidence = 0.94
still wrong
```

BOOTH can report the second attempt as acceptable if it satisfies the configured checks.

Therefore retries are best understood as:

> **an opportunity for the model to reconsider, not an independent verification process.**

---

# 22. Do Not Assume Multiple Attempts Are Independent

If you configure:

```python
max_retries=3
```

you should not interpret that as:

```text
four independent opinions
```

The retry prompt explicitly asks the model to reconsider the previous response.

The attempts are therefore related.

A retry can improve formatting or correct an obvious mistake, but repeated model calls do not automatically provide independent evidence.

---

# 23. Do Not Use BOOTH When Deterministic Logic Is Better

If a rule can be implemented directly in code, prefer code.

For example, do not ask an LLM:

```text
Is 37 greater than 20?
```

and then use BOOTH to validate the answer if your application can simply do:

```python
37 > 20
```

Likewise, deterministic validation is preferable for:

* numeric constraints
* enums
* dates with known formats
* required fields
* permissions
* business rules
* state transitions
* schema constraints

BOOTH is most useful around the parts where an LLM is actually being used.

---

# 24. Do Not Use BOOTH Just Because an LLM Is Present

Not every LLM call needs BOOTH.

For example, if your application is generating:

```text
a poem
a marketing slogan
a casual reply
a creative story
```

there may be no meaningful notion of:

```text
verified
repaired
blocked
```

unless your application has a concrete acceptance criterion.

BOOTH becomes valuable when the output needs to pass a meaningful checkpoint.

---

# 25. Creative Generation Is Usually a Poor Fit

BOOTH's strongest model is:

```text
question
→ answer
→ checkpoint
```

Creative generation is often different.

For example:

```text
Write a funny story about a cat.
```

There is no universal confidence threshold that establishes that one story is "correct."

You could still build a validator for properties such as:

```text
must be under 500 words
must contain a cat
must contain no prohibited terms
```

In that case BOOTH may be useful as part of the workflow.

But the value comes from those concrete constraints, not from BOOTH somehow determining whether the story is good.

---

# 26. Ambiguity Detection Is Not Perfect

BOOTH's ambiguity mechanism depends on the LLM correctly identifying multiple reasonable interpretations.

That means it can miss ambiguity.

It can also identify ambiguity where your application does not care.

Therefore:

```text
AMBIGUOUS
```

should be treated as a useful signal, not a mathematically complete ambiguity detector.

For particularly important inputs, deterministic disambiguation rules or explicit user clarification may be better.

---

# 27. Evidence Agreement Is Only as Good as `compare_fn`

This deserves special emphasis.

With:

```python
check_with_evidence(
    answer,
    evidence,
    compare_fn,
)
```

BOOTH delegates the actual comparison to:

```python
compare_fn
```

If the function is strong, the checkpoint can be useful.

If the function is weak, the checkpoint is weak.

For example:

```python
def compare(answer, evidence):
    return 0.9
```

will produce a high score regardless of the actual relationship between answer and evidence.

BOOTH cannot fix a bad comparator.

---

# 28. `BLOCKED` Does Not Mean "Factually False"

When `check_with_evidence()` produces:

```python
BLOCKED
```

it means the supplied comparison did not meet the configured evidence threshold.

It does not necessarily mean:

```text
the answer is definitely false
```

Possible explanations include:

```text
the answer is wrong
the evidence is insufficient
the evidence is irrelevant
the comparator is too strict
the comparator is poorly designed
the threshold is too high
```

Your application needs to distinguish these cases if they matter.

---

# 29. `UNCERTAIN` Is Not a Diagnosis

Similarly,:

```python
UNCERTAIN
```

means BOOTH could not accept the result.

It does not tell you that the answer is definitely wrong.

For example, an answer can become `UNCERTAIN` because:

```text
the model returned malformed JSON
```

or:

```text
the validator failed
```

or:

```text
confidence never reached the threshold
```

or:

```text
the model call failed
```

Inspect:

```python
result.method
result.attempts
```

when your application needs to understand why.

---

# 30. Be Careful With High Latency or Cost Requirements

Retries mean additional LLM calls.

For example:

```python
max_retries=2
```

can result in up to:

```text
3 model calls
```

Therefore BOOTH can increase:

* latency
* token usage
* API cost

Use retries deliberately.

If your application is extremely latency-sensitive, you may prefer:

```python
max_retries=0
```

and handle failures elsewhere.

---

# 31. Streaming Applications May Not Fit Naturally

BOOTH operates around a completed response.

If your application is fundamentally built around token-by-token streaming, BOOTH is not a streaming validation framework.

A common architecture is:

```text
LLM stream
    ↓
collect final response
    ↓
BOOTH checkpoint
```

rather than attempting to checkpoint every token.

---

# 32. BOOTH Does Not Replace Schema Validation

BOOTH's parsing mechanism checks whether the model returned a usable JSON object with the expected core fields.

It should not be confused with a complete schema-validation framework.

If your application requires a strict schema such as:

```json
{
  "customer_id": "...",
  "amount": 0,
  "currency": "...",
  "items": [...]
}
```

you should still use an appropriate deterministic schema validator.

BOOTH can sit before or around that validation.

For example:

```text
LLM
 ↓
BOOTH parsing
 ↓
application schema validation
 ↓
business rules
```

---

# 33. BOOTH Does Not Protect Against Prompt Injection by Itself

BOOTH does not provide a complete prompt-injection defense.

If an LLM is processing untrusted content, such as:

```text
web pages
emails
documents
user-provided text
```

BOOTH does not automatically make that content safe.

You still need appropriate:

* prompt isolation,
* tool authorization,
* data-flow controls,
* output validation,
* least-privilege access,
* deterministic security checks.

BOOTH can validate the resulting answer, but it is not a complete agent-security solution.

---

# 34. A Practical Decision Rule

A useful question to ask is:

> **What concrete property do I want to check after the LLM responds?**

If you can answer that clearly, BOOTH may be useful.

For example:

```text
"Is the response parseable?"
```

Good fit.

```text
"Did the model identify that the question is ambiguous?"
```

Good fit.

```text
"Does the answer satisfy my application rule?"
```

Good fit.

```text
"Did the answer meet my evidence comparator?"
```

Good fit.

But:

```text
"Can BOOTH tell me whether this fact is objectively true?"
```

No.

```text
"Can BOOTH guarantee the model will not hallucinate?"
```

No.

```text
"Can BOOTH make an autonomous agent safe?"
```

No.

```text
"Can BOOTH replace authorization checks?"
```

No.

---

# 35. A Good Architecture

A strong use of BOOTH is to make it **one checkpoint among several**.

For example:

```text
                    ┌──────────────────┐
                    │   User Request   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │      LLM         │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │      BOOTH       │
                    │                  │
                    │ • parse          │
                    │ • ambiguity      │
                    │ • confidence     │
                    │ • retry          │
                    │ • validator      │
                    └────────┬─────────┘
                             │
                             ▼
                 ┌────────────────────────┐
                 │ Application Validation │
                 └───────────┬────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Business Rules   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Authorized Action│
                    └──────────────────┘
```

The important idea is that BOOTH should usually be **part of the control system**, not the entire control system.

---

# 36. When BOOTH Is Probably Worth Adding

BOOTH is a good candidate when several of these are true:

* You already use an LLM.
* The response needs a machine-readable structure.
* Ambiguous questions are a meaningful problem.
* You have application-specific validation rules.
* A retry can realistically repair common failures.
* You want a structured result instead of raw model text.
* You want to inspect individual attempts.
* You have evidence and a meaningful comparison function.
* Occasional additional LLM calls are acceptable.
* You want a lightweight checkpoint without adopting a larger orchestration system.

---

# 37. When BOOTH Is Probably Not Worth Adding

BOOTH may be unnecessary when:

* The output is purely creative.
* There is no meaningful acceptance criterion.
* A deterministic function can solve the problem directly.
* You already have a complete validation/checkpoint system.
* Additional LLM calls are unacceptable.
* You only need basic JSON/schema validation.
* You need a retrieval system rather than an output checkpoint.
* You need authoritative fact verification.
* You need a security or authorization boundary.
* The application cannot tolerate the possibility of model-reported confidence being wrong.

---

# 38. BOOTH in One Sentence

If you need a concise description of what BOOTH is for:

> **BOOTH is a lightweight checkpoint layer that helps an application decide whether to accept, retry, inspect, or reject an LLM response based on parsing, ambiguity, application-defined validation, model-reported confidence, and optional evidence agreement.**

And equally important:

> **BOOTH does not independently prove that an LLM answer is true, safe, authorized, or fit for a high-stakes decision.**

That second sentence is just as important as the first.

---

# 39. Final Guidance

Use BOOTH when you want **a checkpoint around an LLM**.

Do not use BOOTH as a substitute for:

```text
truth
retrieval
authorization
security
schema validation
business logic
domain expertise
human judgment
```

The strongest BOOTH architecture is therefore not:

```text
LLM
 ↓
BOOTH
 ↓
Trust everything
```

It is:

```text
LLM
 ↓
BOOTH checkpoint
 ↓
deterministic/application checks
 ↓
business policy
 ↓
appropriate human or automated action
```

BOOTH is most valuable when it makes uncertainty and failure **explicit**, rather than pretending that an LLM response has become guaranteed simply because it passed a checkpoint.