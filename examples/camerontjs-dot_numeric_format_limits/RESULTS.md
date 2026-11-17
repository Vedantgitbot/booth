# Format limits of the frozen numeric checker

Both numeric checkpoints withheld 26 of 30 main replies at format validation. That included four of the eight replies the reference grader marked correct. The four accepted replies reached numeric comparison and matched the requested quantity. The result describes format support on this set of harder cases. [Issue #36 follow-up](https://github.com/Vedantgitbot/booth/issues/36#issuecomment-6952270262)

## Method

A separate Codex task authored 30 synthetic main cases and three disjoint smoke cases without access to the original checker or study. The cases deliberately include forms outside the original grammar. Each case supplies a target field and, where applicable, a rounding rule. Codex helped implement, run and review the study. [Case provenance](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/CASE_PROVENANCE.json)

The run used the frozen comparator from PR #39 with BOOTH 0.5.9 and local Ollama 0.40.16. Gemma 3 12B Q4_K_M ran at temperature 0 and seed 42, with a 1,024-token output limit, 4,096-token context and 300-second timeout. The smoke phase used three calls. Once its saved evidence verified, the main phase used 30. Counts include zero warm-ups and zero retries. [PR #39](https://github.com/Vedantgitbot/booth/pull/39) · [Run manifest](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/recorded/main/manifest.json)

For each question, plain `check()` called Gemma once with BOOTH's default prompt. The numeric validator replayed the exact raw reply. Both evidence checkpoints used the same parsed answer. The two numeric paths share the same rule. The separate frozen follow-up grader uses exact rational arithmetic and requires an explicit supported quantity format. [Frozen protocol](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/PROTOCOL.md)

## Saved main results

The grader assigned **8 correct, 1 wrong and 21 unscoreable**. All 30 replies parsed as BOOTH JSON, with zero provider or checker failures.

| Checkpoint | Accepted / 30 | Correct withheld / 8 | Wrong accepted / 1 | Unscoreable accepted / 21 |
|---|---:|---:|---:|---:|
| Plain check | 30 | 0 | 1 | 21 |
| Numeric validator | 4 | 4 | 0 | 0 |
| Keyword evidence | 27 | 0 | 1 | 18 |
| Numeric evidence | 4 | 4 | 0 | 0 |

The validator returned `UNCERTAIN` and numeric evidence returned `BLOCKED` on the same 26 replies. The saved reasons were 13 unsupported quantity formats and 13 missing explicit units. Correct replies were withheld on cases involving Unicode minus in the source or reply, thin-space grouping and JPY.

For `main_17`, the source gave `0.000004 billion GBP` (4,000 GBP). Plain check accepted this reply, and keyword evidence accepted its answer.

```json
{"ambiguous": false, "interpretations": [], "chosen_interpretation": null, "answer": "40000 GBP", "confidence": 0.95}
```

The numeric checkpoints stopped at unsupported source syntax before comparing the amounts. In this case, withholding the wrong reply demonstrates the format gate's behavior.

## Post-hoc review of the 21 unscoreable replies

Nineteen replies were bare numbers and two used fraction forms outside the reference grader's grammar. A post-hoc contextual review found 18 matching magnitudes when the question supplied the unit or made the fraction interpretable. The other three missed the requested half-up rounding. The raw answers were `-9.9`, `-12.5` and `8.5`. The expected quantities were `-10.0 GBP`, `-13 CAD` and `9 EUR`. All 21 retain their primary unscoreable labels. [Case-by-case review](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/contextual_review.json)

The model received the source and question with the default JSON suffix. The case's `answer_format` field was stored as metadata. The difference between what the prompt asked for and what the grader required limits the interpretation of the unscoreable count. A follow-up can put the format contract in the prompt and report unsupported sources separately.

The smoke phase had one correct and two unscoreable replies. The archive also includes 60 authored answer candidates. Those are separate from the main table. [Smoke records](https://github.com/camerontjs-dot/booth/tree/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/recorded/smoke) · [Authored candidates](https://github.com/camerontjs-dot/booth/tree/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/recorded/authored-main)

## Inspect and verify

The reply file contains all 33 exact reply strings with their source, question, reference, declared grade and saved checkpoint decisions. It is a compact projection of the full traces. [Reply file](replies.jsonl)

Run this command from the repository root.

```sh
python3 examples/camerontjs-dot_numeric_format_limits/verify.py
```

The standard-library script checks the snapshot and reply hashes, links decoded answers to the recorded fields, recounts the saved verdicts and verifies the table. It uses LF line endings for the snapshot hash. For offline replay through BOOTH, the complete saved data and original verifier are available at the pinned archive commit. [Full saved run](https://github.com/camerontjs-dot/booth/tree/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/recorded) · [Full replay verifier](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/verify_followup.py) · [Verification receipts](https://github.com/camerontjs-dot/booth/blob/f7938965efdbb74c5ba252162cd3188b17be733c/examples/camerontjs-dot_numeric_comparison/followup/verification.json)
