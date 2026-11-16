# Numeric comparison protocol

Issue: https://github.com/Vedantgitbot/booth/issues/36

This is an authored synthetic demonstration, implemented and run with Codex. It is not a held-out benchmark, financial advice, or a compliance check.

## Question and scope

For the same numeric answers, which of four BOOTH checkpoints accepts or withholds them? The example uses 20 short, synthetic source/question cases. Each also supplies one authored correct and one authored incorrect answer as deterministic controls. A separate live Gemma pass answers the 20 questions.

Only this example folder is changed. BOOTH core and dependencies remain unchanged. The code uses Python's standard library and the installed BOOTH package.

## Four checkpoints

A. `booth.check()`, threshold 0.7, max_retries=0.
B. The same `booth.check()` with a strict numeric validator, threshold 0.7, max_retries=0.
C. `check_with_evidence()` with unique answer-word coverage, threshold 0.5.
D. `check_with_evidence()` with the strict numeric comparator (boolean).

The strict validator and strict evidence comparator share the same comparison rule. Their integration with BOOTH differs: the check() path also applies BOOTH's ambiguity and confidence checks. This is not a comparison of two independently designed numeric algorithms.

## Matched inputs and two result layers

**Authored controls:** each case's correct and incorrect candidate is placed in an explicitly authored, parseable BOOTH response with confidence 0.99 and ambiguous=false. The actual BOOTH functions execute on these fixtures. These are controlled checkpoint demonstrations, not model outputs or calibration observations.

**Live Gemma:** A makes one real Ollama call with BOOTH's unmodified default prompt. B replays that exact provider reply through BOOTH with the validator; C and D check A's parsed answer against the source. All arms therefore assess the same first answer. B makes no new model call. No repair or retry benefit is measured.

Raw provider replies are saved before BOOTH parsing. Received HTTP bytes are retained as base64 with a SHA-256 hash, including available partial or invalid-UTF-8 response bytes on failure. No schema-constrained decoding, reasoning suffix, answer substitution, or JSON extraction wrapper is used. Provider errors and incomplete generations stop the run with partial traces preserved. Completed but unparsable replies remain reported.

## Data and numeric rule

The 20 case IDs, sources, questions, reference quantities, positive controls and negative controls are fixed in cases.json before inference. Three different smoke cases are excluded from the main results.

Source facts use labelled lines, such as `Invoice total: 1356.00 CAD`. The application supplies the requested field label and any explicit rounding instruction. The checker parses that source field; it never reads the case's reference answer or control labels. Missing, duplicated or unsupported target facts fail closed. It does not solve unrestricted language, infer missing facts, or resolve conflicting sources.

Answers must contain one quantity with an explicit supported unit. Supported forms include decimal numbers (including leading-dot decimals), valid comma grouping, parentheses around a negative amount or complete quantity, CAD/USD/EUR before or after the value, thousand/million scaling for currencies only, percent/fraction, percentage points, days, months and items. Singular unit forms are accepted. Bare dollar signs are ambiguous and unsupported. Percentage points are distinct from rates; a fraction of 0.075 is equivalent to 7.5 percent. Days and months are not treated as interchangeable.

Numeric values use exact decimal arithmetic. There is no blanket tolerance. When the question explicitly requests rounding of a currency amount, the source value is rounded once using decimal ROUND_HALF_UP; the answer must equal that rounded value. Rounding other dimensions is unsupported and fails closed. Supported-format failures are reported separately from wrong numeric values. This bounded grammar can withhold a semantically correct free-form answer.

Reference grading uses the declared reference quantity, separate from source-field checking. An additional audit rechecks the saved data and outcomes before publication. Unsupported answers stay unscoreable; no silent exclusions or post-run rescoring-rule changes are permitted.

## Frozen execution settings

- Provider: local Ollama; model gemma3:12b, Q4_K_M.
- Required digest for the planned run: f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a.
- BOOTH: source checkout at eceb8bae03fcc47c9ab08f9f4f6d112a088ff4d4, version 0.5.9; the added runner commit/tree is recorded separately.
- Temperature 0, seed 42, num_predict 1024, num_ctx 4096, timeout 300 seconds.
- One repetition; case order randomized with Python random.Random(42).
- One separately recorded short warm-up call; warm-up excluded from per-case metrics.
- No parallel model calls and no resume into an interrupted run. A new attempt gets a fresh directory.
- Source, fixture, grading and protocol hashes; model digest; provider/Python/OS/hardware versions; exact requests and raw HTTP response text are retained.
- Code, fixtures, grading and thresholds freeze before the main run. Any repair after inference starts requires a new candidate/run, preserving the prior attempt.

## Outcomes and denominators

For each layer and arm, report all attempted answer-checks. Report correct, wrong, unscoreable and missing answers; accepted and withheld counts; the exact BOOTH statuses; wrong accepted, wrong withheld, correct accepted, correct withheld; parse/call/checker failures. Also show literal BLOCKED separately: check() can withhold via UNCERTAIN or AMBIGUOUS rather than BLOCKED.

Wrong-withheld rates use all scoreable wrong answers in that layer as denominator; correct-withheld rates use all scoreable correct answers. Unscoreable and missing answers are displayed separately against the full attempted denominator. Authored control correctness is declared in advance; live answer correctness comes from reference grading. Live and control results are never pooled.

This is a checkpoint-decision study with one model, one seed and authored development cases. It does not establish general numeric reliability, calibration, safety, finance suitability, latency comparisons between independent model runs, or retry recovery.

## Checks before publication

Run the example's comparator/grading tests and the unchanged BOOTH suite. Check positive and negative controls, malformed and conflicting evidence, unit/currency and percentage-point mutations, rounding boundaries and backend disconnection. Verify raw-reply preservation, unique complete coverage, provenance hashes, actual call counts, case order, source/model identity and report reconstruction from records. Retain failures and negative findings. Publish only after checking the saved results.
