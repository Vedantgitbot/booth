# Numeric checkpoints with local Gemma

In this 20-question synthetic run, Gemma answered 19 questions correctly and missed one explicit rounding instruction. Plain `check()` and keyword evidence matching accepted that answer at confidence 1.0. The numeric validator withheld it as `UNCERTAIN`; the strict evidence comparator returned `BLOCKED`. Neither numeric setup withheld a correct live answer.

This is the example for [issue #36](https://github.com/Vedantgitbot/booth/issues/36). Codex helped author the synthetic cases, implement the example, run local Gemma, and check the saved evidence. The source text deliberately uses labelled fields, and the application supplies the requested field. The numeric rule is a bounded source-field comparison, not a general financial-language solver. These results are not financial advice or a compliance check.

## What was compared

All four checkpoints assess the same answer:

- **A, check:** `booth.check()`, confidence threshold 0.7, `max_retries=0`.
- **B, validator:** the same captured raw reply is replayed through `check()` with a numeric validator. It makes no second model call.
- **C, keyword evidence:** `check_with_evidence()` with unique answer-word coverage at threshold 0.5.
- **D, numeric evidence:** `check_with_evidence()` with a boolean strict numeric comparator.

A sends BOOTH's unmodified default prompt to Gemma. B replays the exact provider reply. C and D receive A's parsed answer and the same source. There is no schema-constrained decoding, suffix substitution, reasoning wrapper, or retry repair in this experiment. B and D share the numeric comparison rule; the BOOTH integration differs.

The rule parses the requested source field and checks exact value, unit/currency and any explicit currency rounding instruction. It reads source facts, not fixture references. Percent and fraction conversions and currency scaling are supported; percentage points remain distinct from rates. Missing, duplicate or unsupported target facts fail closed. Reference grading was implemented separately using rational arithmetic. [Frozen protocol](PROTOCOL.md), [cases and references](cases.json).

## Two separate result layers

**Authored controls:** each of the 20 source/question cases has one correct and one wrong candidate. The 40 explicitly authored JSON fixtures have confidence 0.99 and ambiguous=false. Actual BOOTH functions execute on these fixtures, but they are not model replies or calibration evidence.

On those controls, A accepted all 20 wrong answers. C also accepted all 20 wrong answers and blocked three correct answers involving equivalent rate/scale representations. B and D withheld all 20 wrong answers and accepted all 20 correct answers. These are designed development cases, not held-out estimates of general comparator accuracy.

**Live Gemma:** one real provider call per question, with each reply reused across the four checkpoints. All 20 replies were complete, parseable and scoreable; no responses were excluded. There were no call or checker failures. Only one live answer was wrong, so the observed wrong-answer catch count is one case, not an estimate of a dependable catch rate.

## The live rounding failure

The `round_even_trap` source says `Service fee: 2.225 USD`. The question explicitly requests two decimal places using half-up rounding, so the declared reference is `2.23 USD`. Gemma returned the original unrounded amount:

````text
```json
{"ambiguous": false, "interpretations": [], "chosen_interpretation": null, "answer": "2.225 USD", "confidence": 1.0}
```
````

The keyword score was 1.0 because that unrounded amount appears in the source. The numeric rule applied the question's rounding policy and withheld it. This is one observed missed rounding instruction; it does not show how the model would perform on unrelated arithmetic or financial tasks.

The controlled keyword false blocks were `percent_not_fraction` (`0.125 fraction`), `fraction_to_percent` (`7.5 percent`) and `thousand_scale` (`0.25 million USD`). Each is equivalent to its reference quantity but shares too few literal answer tokens with its source. Their exact scores and checkpoint results are in [the records](recorded/records.jsonl).

## Run identity

| Item | Recorded value |
|---|---|
| Date | 2026-11-16 |
| Upstream BOOTH base | `eceb8bae03fcc47c9ab08f9f4f6d112a088ff4d4` |
| Frozen example source commit | `ea28a68f62affd1b6f36001d181ca4730eea47fa` |
| BOOTH / Python | 0.5.9 / 3.12.13 |
| OS / hardware | macOS-27.0-arm64-arm-64bit; Apple M3, 8 logical CPUs, 24 GiB RAM |
| Provider / model | Ollama 0.40.16; `gemma3:12b`, Q4_K_M |
| Model digest | `f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a` |
| Generation | Temperature 0; seed 42; num_predict 1024; num_ctx 4096; timeout 300s |
| Questions / repetitions | 20 / 1; randomized case order |
| Main provider calls | 20 question calls + 1 separately recorded warm-up |
| Main elapsed time | 170.2s, including warm-up, controls and bookkeeping |
| Separate smoke | 3 different questions + 1 warm-up; 26.9s; excluded from main results |

Exact prompts, request bodies, unedited reply text, complete HTTP response bytes as base64, hashes and provider timings are retained in [provider_calls.jsonl](recorded/provider_calls.jsonl). [The manifest](recorded/manifest.json) records settings, hardware, source and fixture hashes. The smoke trace remains separately retained locally.

## Unedited generated report

The following is the unchanged [generated summary](recorded/summary.md). “Withheld” means any non-ok BOOTH status. Literal `BLOCKED` is shown separately because validator rejection is `UNCERTAIN`.

<!-- BEGIN UNEDITED GENERATED SUMMARY -->
# Generated numeric checkpoint results

Generated from records.jsonl; authored controls and live Gemma replies are separate.

## Configuration

- Run status: completed
- BOOTH: 0.5.9
- Source commit: `ea28a68f62affd1b6f36001d181ca4730eea47fa`
- Model: `gemma3:12b`
- Model digest: `f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a`
- Live provider calls: 20; warm-up calls: 1
- Questions: 20; one repetition; retries disabled.

## authored_controls

| Metric | check | validator | keyword evidence | numeric evidence |
|---|---:|---:|---:|---:|
| All answer-checks | 40 | 40 | 40 | 40 |
| Correct answers | 20 | 20 | 20 | 20 |
| Wrong answers | 20 | 20 | 20 | 20 |
| Unscoreable answers | 0 | 0 | 0 | 0 |
| Missing answers | 0 | 0 | 0 | 0 |
| Wrong accepted | 20 | 0 | 20 | 0 |
| Wrong withheld | 0 | 20 | 0 | 20 |
| Correct accepted | 20 | 20 | 17 | 20 |
| Correct withheld | 0 | 0 | 3 | 0 |
| Unscoreable accepted | 0 | 0 | 0 | 0 |
| Unscoreable withheld | 0 | 0 | 0 | 0 |
| Call failures | 0 | 0 | 0 | 0 |
| All-parse-failed | 0 | 0 | 0 | 0 |
| Checker failures | 0 | 0 | 0 | 0 |
| Status ACCEPTED | 40 | 20 | 37 | 20 |
| Status REPAIRED | 0 | 0 | 0 | 0 |
| Status BLOCKED | 0 | 0 | 3 | 20 |
| Status UNCERTAIN | 0 | 20 | 0 | 0 |
| Status AMBIGUOUS | 0 | 0 | 0 | 0 |

All answer-checks remain in the attempted denominator. Wrong-withheld rates use the wrong-answer count; correct-withheld rates use the correct-answer count. Unscoreable/missing answers are separate, never silently removed. 'Withheld' includes every non-ok status; literal BLOCKED is shown separately.

## live_gemma

| Metric | check | validator | keyword evidence | numeric evidence |
|---|---:|---:|---:|---:|
| All answer-checks | 20 | 20 | 20 | 20 |
| Correct answers | 19 | 19 | 19 | 19 |
| Wrong answers | 1 | 1 | 1 | 1 |
| Unscoreable answers | 0 | 0 | 0 | 0 |
| Missing answers | 0 | 0 | 0 | 0 |
| Wrong accepted | 1 | 0 | 1 | 0 |
| Wrong withheld | 0 | 1 | 0 | 1 |
| Correct accepted | 19 | 19 | 19 | 19 |
| Correct withheld | 0 | 0 | 0 | 0 |
| Unscoreable accepted | 0 | 0 | 0 | 0 |
| Unscoreable withheld | 0 | 0 | 0 | 0 |
| Call failures | 0 | 0 | 0 | 0 |
| All-parse-failed | 0 | 0 | 0 | 0 |
| Checker failures | 0 | 0 | 0 | 0 |
| Status ACCEPTED | 20 | 19 | 20 | 19 |
| Status REPAIRED | 0 | 0 | 0 | 0 |
| Status BLOCKED | 0 | 0 | 0 | 1 |
| Status UNCERTAIN | 0 | 1 | 0 | 0 |
| Status AMBIGUOUS | 0 | 0 | 0 | 0 |

All answer-checks remain in the attempted denominator. Wrong-withheld rates use the wrong-answer count; correct-withheld rates use the correct-answer count. Unscoreable/missing answers are separate, never silently removed. 'Withheld' includes every non-ok status; literal BLOCKED is shown separately.

## Limits

One authored synthetic demonstration, one model and one seed. The validator replays the first raw reply; no retry recovery or independent model-arm latency is measured. The numeric rule uses explicit labelled source fields and a bounded quantity grammar, not general financial-language understanding. See PROTOCOL.md.
<!-- END UNEDITED GENERATED SUMMARY -->

## Checking and reproduction

The unchanged BOOTH suite and the example's numeric, grading and failure-path tests passed: **464 passed, 6 skipped**. The additional tests exercise wrong-field and unit swaps, rounding boundaries, conflicting/missing source facts, backend disconnection, incomplete generations, and retention of partial or invalid-UTF-8 HTTP bytes.

A separately implemented saved-run auditor read the protocol, fixtures, BOOTH core and records; it read runner/grader/test files as hash bytes only. Its 1,026 checks reproduced the grades, checkpoint decisions, raw-byte identities, call counts, case order, provenance and both summaries with zero findings. This is saved-run consistency checking, not blind scientific qualification.

**Verification receipt:** [recorded/audit.json](recorded/audit.json), SHA-256 `2928bbda94f56c6a81198e7d82e5b5642b54815f9046f21403502e55e8b5835d`. [Validation details](validation.json).

From a checkout containing this example, install BOOTH 0.5.9 in a clean Python environment and make the matching Ollama model available:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests examples/camerontjs-dot_numeric_comparison/test_example.py examples/camerontjs-dot_numeric_comparison/test_grading.py -v

python examples/camerontjs-dot_numeric_comparison/run_example.py --smoke --expected-digest f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a --out examples/camerontjs-dot_numeric_comparison/output/smoke-001

python examples/camerontjs-dot_numeric_comparison/run_example.py --expected-digest f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a --out examples/camerontjs-dot_numeric_comparison/output/main-001
```

The original execution used the same flags with absolute local output directories. The checked-in files under `recorded/` are byte-for-byte copies of that main run, plus the audit receipt. Use fresh output paths; an existing directory is rejected. The three smoke questions are distinct from the main 20. No code, fixtures, thresholds or grading rules changed after inference began.

## Limits that matter

This example demonstrates checkpoint behavior on authored synthetic cases using a deliberately bounded numeric grammar. It does not establish general numeric accuracy, calibration, source legitimacy, financial suitability or compliance. The requested field is supplied by the application; unrestricted prose, inferred field relationships, arbitrary currencies, missing units, conflicting facts and general calculations require separate design and evaluation.

Authored high-confidence controls and actual Gemma replies remain separate. B and D use the same numeric rule; B is a replay with retries disabled. There is no model-arm latency comparison, repair-rate measurement or unseen evaluation set. A useful next step would use independently authored cases with a wider answer grammar and explicit source-conflict policies.
