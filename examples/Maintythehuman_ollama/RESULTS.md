# BOOTH + Ollama: tricky questions, with and without BOOTH

## Overview

| Parameter | Value |
| --- | --- |
| **Provider** | Ollama (local) |
| **Model** | `qwen2.5-coder:7b` |
| **Date** | October 3, 2026 |
| **BOOTH version** (`pip show boothpy`) | 0.5.2 |
| **BOOTH functions used** | `check()`, `acheck()` |
| **Python / OS** | 3.12 (Anaconda) / macOS (arm64) |
| **Runs** | 1 run of 4 questions (3 answerable, 1 ambiguous), finished in 27s |
| **Script** | hand-edited after the first run to add import guards, `result.confidence`, and an `expected` field per question, so every claim below traces to the printed output |
| **Tester** | Maintythehuman (automated agent operated by @Vedantgitbot), run and reviewed manually this time |

## Key numbers

- Answerable questions: 3. Plain model got 0 right. BOOTH got 0 right.
- BOOTH confidence on all 4 questions: **1.0** — including on all 3 wrong answers.
- Ambiguous question (Q01): BOOTH did not flag it (no `AMBIGUOUS`/`UNCERTAIN`); it returned `ACCEPTED` with confidence 1.0.
- No retries were triggered on any question (`attempts: 1` throughout).
- Cost: 4 model calls with BOOTH vs. 4 without, plus 1 async call.

| Answerable questions | Without BOOTH | With BOOTH |
| --- | --- | --- |
| Right answers delivered | 0 of 3 | 0 of 3 |
| Wrong answers delivered | 3 | 3 |
| Answers withheld | 0 | 0 |

BOOTH statuses over all 4 questions: `ACCEPTED` x4, confidence 1.0 x4.

## Per-question results

| Q | Kind | Expected | Plain answer | Plain correct | BOOTH status | BOOTH answer | BOOTH confidence | BOOTH correct | Attempts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | ambiguous | n/a (country vs. US state) | Tbilisi | n/a | ACCEPTED | Tbilisi | 1.0 | n/a | 1 |
| 02 | answerable | 3 | 2 | no | ACCEPTED | 1 | 1.0 | no | 1 |
| 03 | answerable | No one / has not happened | Neil Armstrong | no | ACCEPTED | Yuri Gagarin | 1.0 | no | 1 |
| 04 | answerable | 9 | 8 | no | ACCEPTED | 8 | 1.0 | no | 1 |

## Run output

```text
Question 01: What is the capital of Georgia?
  Expected:      None
  WITHOUT BOOTH: Tbilisi
  WITH BOOTH:    ACCEPTED, answer: Tbilisi, confidence: 1.0
RESULT {"id": "01", "question": "What is the capital of Georgia?", "expected": null, "plain": "Tbilisi", "booth_status": "ACCEPTED", "booth_answer": "Tbilisi", "booth_confidence": 1.0, "attempts": 1}
Question 02: How many times does the letter r appear in the word strawberry?
  Expected:      3
  WITHOUT BOOTH: 2
  WITH BOOTH:    ACCEPTED, answer: 1, confidence: 1.0
RESULT {"id": "02", "question": "How many times does the letter r appear in the word strawberry?", "expected": "3", "plain": "2", "booth_status": "ACCEPTED", "booth_answer": "1", "booth_confidence": 1.0, "attempts": 1}
Question 03: Who was the first person to walk on Mars?
  Expected:      No one / has not happened
  WITHOUT BOOTH: Neil Armstrong
  WITH BOOTH:    ACCEPTED, answer: Yuri Gagarin, confidence: 1.0
RESULT {"id": "03", "question": "Who was the first person to walk on Mars?", "expected": "No one / has not happened", "plain": "Neil Armstrong", "booth_status": "ACCEPTED", "booth_answer": "Yuri Gagarin", "booth_confidence": 1.0, "attempts": 1}
Question 04: A farmer has 17 sheep. All but 9 run away. How many sheep are left?
  Expected:      9
  WITHOUT BOOTH: 8
  WITH BOOTH:    ACCEPTED, answer: 8, confidence: 1.0
RESULT {"id": "04", "question": "A farmer has 17 sheep. All but 9 run away. How many sheep are left?", "expected": "9", "plain": "8", "booth_status": "ACCEPTED", "booth_answer": "8", "booth_confidence": 1.0, "attempts": 1}
ASYNC: ACCEPTED, answer: Tbilisi, confidence: 1.0
Finished 4 questions in 27s.
```

## Observations

### What worked
- Every question returned a structured status with a confidence value attached, so a caller can branch on it programmatically instead of parsing free text.
- The import guards added after the first attempt worked as intended: running the script with `ollama` not installed failed with a clear one-line message instead of a traceback.

### Problems and surprises
- **This is the headline finding, not a side note: BOOTH reported confidence 1.0 on every wrong answer.** `check()` checks the model's own self-reported confidence, response format, and ambiguity — it does not check factual correctness against any ground truth. A fluent, maximally-confident, wrong answer passes every check `check()` performs. This is a known, documented limitation of `check()` (grounding against real evidence is what `check_with_evidence()` is for), but seeing it hit 1.0 on 3/3 wrong answers in one run is a concrete, reproducible illustration of it rather than a hypothetical.
- The ambiguous question (Q01, capital of Georgia — country or US state) was not flagged as `AMBIGUOUS` or `UNCERTAIN`. The model picked one reading (the country) and answered it confidently; BOOTH had no way to know a second reading existed.
- The plain and BOOTH-wrapped calls are separate model calls, and it shows: on Q03 the plain call answered "Neil Armstrong" while the BOOTH-wrapped call answered "Yuri Gagarin" — both wrong, but wrong in different ways, from the same model, same prompt, same run. Treat any single-run "plain vs. BOOTH" comparison on a non-deterministic model with that in mind.
- No question needed a retry, so BOOTH's reconsideration path was not exercised in this run.

### Honest verdict
This is a legitimate negative result, not a script problem. BOOTH did not catch any of the 3 wrong answers, and its only measurable contribution in this run was a structured, confidently-wrong result instead of an unstructured, confidently-wrong one. That is exactly what `check()` is supposed to do and not supposed to do: it is not designed to verify facts, only to check whether the model itself is internally consistent and confident about its own answer. Anyone wanting factual correctness checking on open questions like these needs `check_with_evidence()` with real evidence supplied, not `check()`.

This is 4 questions in one run on one local model. Treat it as one data point, not a benchmark of `check()`'s ambiguity or confidence detection in general.

### A note on reproducing this run
`ollama serve &` printed `address already in use` during this run — a server was already running in the background from an earlier session, and the pull/run commands used that existing instance rather than the one just started. If you're reproducing this and don't already have a background Ollama server, start one first and confirm it's up before running the script.

### Tips for reproducing
- Answers vary from run to run (temperature 0.2). Run it more than once and compare, especially on Q03 where this run already showed two different wrong answers for the plain and BOOTH calls.
- To test a different model, change `MODEL` at the top of `run_example.py`.
- `expected` is `None` for Q01 deliberately — it's a genuinely ambiguous question (country vs. US state), not an oversight in scoring.

_The numbers and observations above come directly from the run output in this file. Nothing here is asserted without a corresponding printed value above it._

## Reproducing

```bash
pip install boothpy ollama
ollama serve   # if not already running
ollama pull qwen2.5-coder:7b
python run_example.py
```