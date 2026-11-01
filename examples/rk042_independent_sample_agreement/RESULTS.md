# Independent-sample agreement: results

This example compares three fresh local-model samples using BOOTH's
`check_with_evidence()` against a confidence threshold on the first sample.
The current script contains ten self-authored integer-arithmetic questions
held out from all earlier runs. The dataset is small and not representative
of general usage.

## Held-out run: 2026-11-01

Ten new self-authored arithmetic questions were run once each with three
samples, using boothpy 0.5.7, Ollama 0.24.0, qwen2.5-coder:7b, temperature
0.2 and seeds 101/102/103. The full model digest and platform are in the
output. The confidence threshold was 0.7, with no retries.

Eight of ten questions were eligible for paired comparison. Two were excluded:
question 1 had three non-integer answers, and question 2 had a non-integer
first answer. Across all 30 calls, 26 answers passed validation, four did not,
and no API calls failed. Excluded questions are not counted as successes or
failures of either comparison method.

| Among the 8 eligible questions | Agreement | Confidence |
| --- | ---: | ---: |
| Wrong first answers rejected | 2 of 2 | 0 of 2 |
| Correct first answers rejected | 1 of 6 | 0 of 6 |
| Wrong first answers accepted | 0 of 2 | 2 of 2 |

Per wrong first answer:

| Question | Expected | Samples in seed order | Agreement | First confidence |
| --- | ---: | --- | --- | ---: |
| 28 + 57 | 85 | 35, 45, 35 | Disagreed; wrong first answer blocked | 1.0 |
| 72 / 8 | 9 | 18, 4, 4 | Disagreed; wrong first answer blocked | 1.0 |

No eligible case had three matching wrong answers; such an answer would be
accepted by this agreement rule. There was one wrong block: for 18 × 8 the
first answer was correct (144), but the samples were 144, 576, 144.

The run made 30 calls, versus 10 for a one-sample-per-question baseline:
20 extra calls. The observed elapsed time was 385.0 seconds. The first calls
summed to 231.0 seconds *within this interleaved run*; this is only a timing
proxy, not an independently measured single-sample run. Execution order,
model warm-up and machine load affect timing.

The held-out set was not used when choosing the model and settings, but it is
only ten self-authored arithmetic questions. The model, temperature and N were
selected or retained after earlier pilots. Samples can share systematic errors;
agreement is not a factual verification, and the dataset is too small to infer
general accuracy.

### Full held-out output

````text
Run UTC: 2026-11-01T05:26:17.440008+00:00
Python: 3.12.3; OS: Linux-7.0.0-42-generic-x86_64-with-glibc2.39
boothpy: 0.5.7; Ollama server: 0.24.0
Model: qwen2.5-coder:7b; digest: dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364
Dataset: 10 self-authored integer-arithmetic questions
N: 3; temperature: 0.2; seeds: (101, 102, 103); retries: 0
Confidence threshold: 0.7; timeout: 180s
Agreement: all normalized integer answers equal; confidence applies to first answer.

Question 1: What is 16 multiplied by 7? Expected: 112
Running seed 101...
{"raw": "{\n\"answer\": \".json\",\n  \"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 77.2, "kind": "invalid_response", "error": "answer is not an integer string"}
Running seed 102...
{"raw": "{\n\"answer\": \"{\\\"result\\\": 112,\\\"confidence\\\":1.}\"\n\n,\"confidence\":1.0}", "done_reason": "stop", "seconds": 12.4, "kind": "invalid_response", "error": "answer is not an integer string"}
Running seed 103...
{"raw": "{\n\"answer\": \"{\\\"result\\\": 112,\\\"confidence\\\":1}\"\n\n,\n\n\"confidence\":1}", "done_reason": "stop", "seconds": 11.1, "kind": "invalid_response", "error": "answer is not an integer string"}
Excluded from paired comparison: invalid answer, call failure, or invalid first confidence.

Question 2: What is 13 multiplied by 9? Expected: 117
Running seed 101...
{"raw": "{\n\"answer\": \"integer\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 15.8, "kind": "invalid_response", "error": "answer is not an integer string"}
Running seed 102...
{"raw": "{\n\"answer\": \"3\"\n   , \"confidence\": 1\n}", "done_reason": "stop", "seconds": 7.4, "kind": "valid_answer", "answer": "3", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"117\",\n\"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 7.3, "kind": "valid_answer", "answer": "117", "confidence": 1}
Excluded from paired comparison: invalid answer, call failure, or invalid first confidence.

Question 3: What is 18 multiplied by 8? Expected: 144
Running seed 101...
{"raw": "{\n\"answer\": \"144\",\n   \"confidence\": 1.0\n}", "done_reason": "stop", "seconds": 17.3, "kind": "valid_answer", "answer": "144", "confidence": 1.0}
Running seed 102...
{"raw": "{\n\"answer\": \"576\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "576", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"144\",\n\"confidence\": 1.0\n }", "done_reason": "stop", "seconds": 7.8, "kind": "valid_answer", "answer": "144", "confidence": 1.0}
First answer correct: True
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1.0

Question 4: What is 135 plus 48? Expected: 183
Running seed 101...
{"raw": "{\n  \"answer\": \"183\",\n      \"confidence\": 1.0\n  }", "done_reason": "stop", "seconds": 18.4, "kind": "valid_answer", "answer": "183", "confidence": 1.0}
Running seed 102...
{"raw": "{\n  \"answer\": \"183\",\n      \"confidence\": 1\n  }", "done_reason": "stop", "seconds": 8.2, "kind": "valid_answer", "answer": "183", "confidence": 1}
Running seed 103...
{"raw": "{\n  \"answer\": \"183\",\n      \"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 7.7, "kind": "valid_answer", "answer": "183", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1.0

Question 5: What is 92 minus 36? Expected: 56
Running seed 101...
{"raw": "{\n\"answer\": \"56\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 16.4, "kind": "valid_answer", "answer": "56", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"56\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "56", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"56\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "56", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 6: What is 132 divided by 11? Expected: 12
Running seed 101...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\": 1.0\n\n}", "done_reason": "stop", "seconds": 18.4, "kind": "valid_answer", "answer": "12", "confidence": 1.0}
Running seed 102...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\":0.95\n\n}\n", "done_reason": "stop", "seconds": 8.6, "kind": "valid_answer", "answer": "12", "confidence": 0.95}
Running seed 103...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\": 1\n }", "done_reason": "stop", "seconds": 7.3, "kind": "valid_answer", "answer": "12", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1.0

Question 7: What is 28 plus 57? Expected: 85
Running seed 101...
{"raw": "{\n\"answer\": \"35\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 16.3, "kind": "valid_answer", "answer": "35", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"45\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 6.9, "kind": "valid_answer", "answer": "45", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"35\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 6.9, "kind": "valid_answer", "answer": "35", "confidence": 1}
First answer correct: False
Wrong first answer samples: ['35', '45', '35']; agreed=False; first confidence=1
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Question 8: What is 11 multiplied by 14? Expected: 154
Running seed 101...
{"raw": "{\n  \"answer\": \"154\",\n  \"confidence\": 1.0\n\n}", "done_reason": "stop", "seconds": 18.6, "kind": "valid_answer", "answer": "154", "confidence": 1.0}
Running seed 102...
{"raw": "{\n  \"answer\": \"154\",\n  \"confidence\":1\n}", "done_reason": "stop", "seconds": 7.3, "kind": "valid_answer", "answer": "154", "confidence": 1}
Running seed 103...
{"raw": "{\n  \"answer\": \"154\",\n  \"confidence\": 1\n }", "done_reason": "stop", "seconds": 7.7, "kind": "valid_answer", "answer": "154", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1.0

Question 9: What is 250 minus 86? Expected: 164
Running seed 101...
{"raw": "{\n\"answer\": \"164\",\n\"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 16.6, "kind": "valid_answer", "answer": "164", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"164\",\n\"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 6.9, "kind": "valid_answer", "answer": "164", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"164\",\n\"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "164", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 10: What is 72 divided by 8? Expected: 9
Running seed 101...
{"raw": "{\n\"answer\": \"18\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 16.0, "kind": "valid_answer", "answer": "18", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"4\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 6.2, "kind": "valid_answer", "answer": "4", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"4\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 6.2, "kind": "valid_answer", "answer": "4", "confidence": 1}
First answer correct: False
Wrong first answer samples: ['18', '4', '4']; agreed=False; first confidence=1
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Summary: questions=10, eligible=8, excluded=2
Actual calls=30; one-call baseline=10; extra calls=20
Elapsed seconds=385.0
Sum of first-call durations=231.0s (observed within this interleaved run; not a separate baseline run)
Samples valid_answer: 26
Samples invalid_response: 4
Samples call_failure: 0
Samples with valid answers but invalid confidence: 0
agreement: correct first answer accepted: 5
agreement: correct first answer rejected: 1
agreement: wrong first answer accepted: 0
agreement: wrong first answer rejected: 2
confidence: correct first answer accepted: 6
confidence: correct first answer rejected: 0
confidence: wrong first answer accepted: 2
confidence: wrong first answer rejected: 0
Only eligible questions are counted above; agreement and confidence do not prove truth.
````


## Earlier 10-question exploratory run

The earlier run used the published boothpy 0.5.6, Ollama server 0.24.0, Python
3.12.3 on Linux, and `qwen2.5-coder:7b` (full digest in the output below).
Each question had three calls, temperature 0.2, seeds 101/102/103, and no
retries. Responses were requested using an Ollama JSON schema. Integer strings
were normalized to integers; agreement required all three answers to match.
The confidence baseline accepted the first answer at confidence >= 0.7.

All ten questions had complete usable samples. Of four wrong first answers,
agreement blocked four and confidence rejected zero. Of six correct first
answers, neither check rejected any. All first-sample confidence scores were
1.0. There were 30 calls, 20 more than a one-call-per-question baseline, and
the run took 340.8 seconds.

These are observations on this specific small dataset, not estimates of
general accuracy. The first two questions and model settings were explored in
earlier pilots before this run, and the 7B model was selected after the
3B model produced unusable responses. This selection limits the interpretation
of the results. Separate calls can have correlated errors; agreement can accept
the same wrong answer repeatedly, and strict equality can reject equivalent
answers expressed differently. The schema and `ACCEPTED` status do not prove
correctness. The comparison applies only to complete sets with a valid first
confidence; invalid responses and failures are reported separately.

## All earlier pilots and selection

- **3B, temperature 0.7, two questions, N=3:** six calls, one response valid
  under the pilot's strict rule, zero complete sets. Non-integer answers and
  out-of-range confidence prevented comparison. No API failures were reported.
- **3B, temperature 0.2, the same two questions, N=3:** six calls, two valid
  responses under the strict rule, zero complete sets. The first answer was
  empty for one question and the first confidence was 2 for the other. No API
  failures were reported.
- **7B, temperature 0.2, the same two questions, N=3:** six valid responses,
  two complete sets, approximately 114.1 seconds. Agreement blocked the one
  wrong first answer (`51` vs expected `102`) and accepted the correct `96`;
  confidence 1.0 accepted both.
- **7B, temperature 0.2, ten exploratory questions, N=3:** the separate
  30-call run detailed below, with four wrong first answers blocked and no
  correct first answers blocked. Its first two questions overlap the pilots.

The 7B model and temperature 0.2 were selected after exploratory pilots;
N=3 was used in those pilots and retained as the final setting after them.
The held-out set was run once with these fixed settings and boothpy 0.5.7.
Earlier results are not held-out results. The early pilot's
stricter validation required confidence on every sample; the final script
requires valid confidence only on the first sample.

## Full output from the earlier 10-question exploratory run

````text
Run UTC: 2026-10-30T11:13:40.157092+00:00
Python: 3.12.3; OS: Linux-7.0.0-42-generic-x86_64-with-glibc2.39
boothpy: 0.5.6; Ollama server: 0.24.0
Model: qwen2.5-coder:7b; digest: dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364
Dataset: 10 self-authored integer-arithmetic questions
N: 3; temperature: 0.2; seeds: (101, 102, 103); retries: 0
Confidence threshold: 0.7; timeout: 180s
Agreement: all normalized integer answers equal; confidence applies to first answer.

Question 1: What is 17 multiplied by 6? Expected: 102
Running seed 101...
{"raw": "{\n\"answer\": \"51\",\n\"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 42.5, "kind": "valid_answer", "answer": "51", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"102\",\n   \"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 7.5, "kind": "valid_answer", "answer": "102", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"102\",\n\"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "102", "confidence": 1}
First answer correct: False
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Question 2: What is 12 multiplied by 8? Expected: 96
Running seed 101...
{"raw": "{\n\"answer\": \"96\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 15.9, "kind": "valid_answer", "answer": "96", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"96\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 6.6, "kind": "valid_answer", "answer": "96", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"96\",\n   \"confidence\": 1\n }", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "96", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 3: What is 14 multiplied by 7? Expected: 98
Running seed 101...
{"raw": "{\n\"answer\": \"98\",\n   \"confidence\": 1\n}", "done_reason": "stop", "seconds": 16.2, "kind": "valid_answer", "answer": "98", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"98\",\n\"confidence\": 1.0\n}", "done_reason": "stop", "seconds": 8.2, "kind": "valid_answer", "answer": "98", "confidence": 1.0}
Running seed 103...
{"raw": "{\n\"answer\": \"98\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 6.6, "kind": "valid_answer", "answer": "98", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 4: What is 125 plus 37? Expected: 162
Running seed 101...
{"raw": "{\n  \"answer\": \"162\",\n      \"confidence\": 1.0\n  }", "done_reason": "stop", "seconds": 18.4, "kind": "valid_answer", "answer": "162", "confidence": 1.0}
Running seed 102...
{"raw": "{\n  \"answer\": \"162\",\n      \"confidence\": 1\n }", "done_reason": "stop", "seconds": 7.8, "kind": "valid_answer", "answer": "162", "confidence": 1}
Running seed 103...
{"raw": "{\n  \"answer\": \"162\",\n      \"confidence\": 1\n  }", "done_reason": "stop", "seconds": 8.2, "kind": "valid_answer", "answer": "162", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1.0

Question 5: What is 84 minus 29? Expected: 55
Running seed 101...
{"raw": "{\n\n\"answer\": \"55\",\n\"confidence\":1\n\n}", "done_reason": "stop", "seconds": 16.5, "kind": "valid_answer", "answer": "55", "confidence": 1}
Running seed 102...
{"raw": "{\n\n  \"answer\": \"55\",\n  \"confidence\":1\n\n  }", "done_reason": "stop", "seconds": 8.2, "kind": "valid_answer", "answer": "55", "confidence": 1}
Running seed 103...
{"raw": "{\n\n  \"answer\": \"55\",\n  \"confidence\":1\n\n  }", "done_reason": "stop", "seconds": 8.2, "kind": "valid_answer", "answer": "55", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 6: What is 144 divided by 12? Expected: 12
Running seed 101...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 17.3, "kind": "valid_answer", "answer": "12", "confidence": 1}
Running seed 102...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\":1.0\n}", "done_reason": "stop", "seconds": 7.8, "kind": "valid_answer", "answer": "12", "confidence": 1.0}
Running seed 103...
{"raw": "{\n  \"answer\": \"12\",\n  \"confidence\": 1.0\n}\n", "done_reason": "stop", "seconds": 8.1, "kind": "valid_answer", "answer": "12", "confidence": 1.0}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1

Question 7: What is 19 plus 46? Expected: 65
Running seed 101...
{"raw": "{\n\"answer\": \"55\",\n\"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 15.8, "kind": "valid_answer", "answer": "55", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"35\",\n\"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 6.7, "kind": "valid_answer", "answer": "35", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"35\",\n   \"confidence\": 1.0\n}", "done_reason": "stop", "seconds": 7.7, "kind": "valid_answer", "answer": "35", "confidence": 1.0}
First answer correct: False
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Question 8: What is 9 multiplied by 13? Expected: 117
Running seed 101...
{"raw": "{\n\"answer\": \"57\",\n   \"confidence\": 1\n}", "done_reason": "stop", "seconds": 16.4, "kind": "valid_answer", "answer": "57", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"27\",\n   \"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "27", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"27\",\n   \"confidence\": 1\n}\n", "done_reason": "stop", "seconds": 7.0, "kind": "valid_answer", "answer": "27", "confidence": 1}
First answer correct: False
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Question 9: What is 200 minus 73? Expected: 127
Running seed 101...
{"raw": "{\n  \"answer\": \"127\",\n  \"confidence\":1.0\n}", "done_reason": "stop", "seconds": 17.9, "kind": "valid_answer", "answer": "127", "confidence": 1.0}
Running seed 102...
{"raw": "{\n  \"answer\": \"127\",\n  \"confidence\": 1\n }\n", "done_reason": "stop", "seconds": 7.8, "kind": "valid_answer", "answer": "127", "confidence": 1}
Running seed 103...
{"raw": "{\n  \"answer\": \"127\",\n  \"confidence\":1\n  }", "done_reason": "stop", "seconds": 7.8, "kind": "valid_answer", "answer": "127", "confidence": 1}
First answer correct: True
Agreement: status=ACCEPTED, reason=None, detail=None
Confidence: ACCEPT; score=1.0

Question 10: What is 63 divided by 7? Expected: 9
Running seed 101...
{"raw": "{\n\"answer\": \"1\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 15.6, "kind": "valid_answer", "answer": "1", "confidence": 1}
Running seed 102...
{"raw": "{\n\"answer\": \"42\",\n\"confidence\": 1\n}", "done_reason": "stop", "seconds": 6.6, "kind": "valid_answer", "answer": "42", "confidence": 1}
Running seed 103...
{"raw": "{\n\"answer\": \"5\",\n\"confidence\": 1\n\n}", "done_reason": "stop", "seconds": 6.6, "kind": "valid_answer", "answer": "5", "confidence": 1}
First answer correct: False
Agreement: status=BLOCKED, reason=EVIDENCE_DISAGREES, detail=compare_fn returned False
Confidence: ACCEPT; score=1

Summary: questions=10, eligible=10, excluded=0
Actual calls=30; one-call baseline=10; extra calls=20
Elapsed seconds=340.8
Samples valid_answer: 30
Samples invalid_response: 0
Samples call_failure: 0
Samples with valid answers but invalid confidence: 0
agreement: correct first answer accepted: 6
agreement: correct first answer rejected: 0
agreement: wrong first answer accepted: 0
agreement: wrong first answer rejected: 4
confidence: correct first answer accepted: 6
confidence: correct first answer rejected: 0
confidence: wrong first answer accepted: 4
confidence: wrong first answer rejected: 0
Only eligible questions are counted above; agreement and confidence do not prove truth.
````
