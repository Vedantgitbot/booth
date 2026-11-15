# Confidence calibration on local arithmetic

The model receives a custom short prompt plus an Ollama JSON schema; BOOTH
only parses and evaluates the saved model reply. These results describe the
model's stated confidence under constrained decoding, not BOOTH's default
prompt flow.

## 30-question study: observed results

Run 2026-11-15, UTC; 30 planned and attempted calls, 514.1 seconds. All 30
responses completed, and BOOTH reported `ACCEPTED` / `confidence` for all 30.
There were 27 scoreable answers: **12 correct and 15 wrong**. Three were
excluded under the pre-specified integer-only rule. Among scoreable responses,
all reported confidence 1.0; accuracy was 12/27 = 0.444 and the ten-bin ECE
was 15/27 = 0.556. These describe this sample, not general model calibration.

Final run environment: boothpy 0.5.8, Ollama 0.24.0, Python 3.12.3,
Linux 7.0.0-43-generic x86_64 (glibc 2.39), and qwen2.5-coder:7b with digest
`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`.

```text
Planned: 30; attempted: 30; eligible: 27; excluded: 3
Exclusions: {'answer is not an integer string': 3}
BOOTH statuses: {'ACCEPTED': 30}
Bins: range, count, mean confidence, observed accuracy
  [0.9, 1.0]: 27, 1.000, 0.444
ECE: 0.556
Confidence thresholds: threshold, retained, coverage of attempted, retained accuracy
  0.5: 27, 0.900, 0.444
  0.7: 27, 0.900, 0.444
  0.9: 27, 0.900, 0.444
```

All scoreable answers had the same confidence, so the threshold sweep did
not distinguish between them. The three excluded replies were `:97`
(reference 87), `{"result":96,"confidence":1}` inside an answer string
(reference 96), and `1.5` (reference 13). The nested result contains the
correct reference, but the fixed integer-only rule does not interpret it.
Thus the 27-answer accuracy is conditional on that rule, not accuracy over all
30 questions. BOOTH acceptance means its output checks passed; it does not
verify factual correctness.

ECE is the weighted average of the absolute differences between each
confidence bin's mean confidence and observed accuracy; lower is better on
the evaluated sample. Here there is only one populated bin: |1.0 - 12/27|.
The reported 90% threshold coverage counts only scoreable answers that meet
the threshold, divided by all 30 attempts. All 30 responses reported 1.0;
the other three are excluded because their answers could not be scored, not
because their confidence was below the threshold.

The raw model replies below are pasted from the actual run. Their `raw` values
are JSON-escaped strings and can be recovered with a JSON parser. Locally, the
full records and manifest are in ignored `output/20261115T045922348251Z/`.


## Setup

- Python 3.9+, `boothpy`, Ollama, and the `qwen2.5-coder:7b` model. The
  recorded run used boothpy 0.5.8. Other installed versions are recorded in
  the manifest, and the script warns that results may differ.
- Standard-library HTTP; no new BOOTH dependencies. The questions are
  self-authored integer arithmetic and their labels are computed locally.
- Fixed 30-question study, temperature 0.2, seed 101, no retries. The 30
  questions were chosen after the pilots, and are distinct from the recorded
  pilot and Issue #19 questions.
- This is a small, hand-selected arithmetic set with one model and one seed;
  it is smaller than the issue's suggested 100 questions per model. Results
  cannot be generalized to other questions, models, prompts or settings.
- Ollama receives a short custom prompt and JSON schema; BOOTH checks the
  returned response. **The model does not receive BOOTH's default prompt.**
  This example does not compare default and reasoning prompts.
- The scorer accepts integer strings only. Non-integer answers, parser
  failures and incomplete calls are reported and excluded from calibration.
  Confidence-bin accuracy and ECE are calculated only on scoreable responses;
  threshold coverage uses all attempted calls as its denominator. Incomplete
  study runs report both planned and attempted counts.
- An API failure, timeout or incomplete response stops the run; partial raw
  records are preserved. A new run makes a new output directory.

From this folder, after installing Ollama and the model:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install boothpy
.venv/bin/python run_example.py
```

Raw records and the manifest are stored under the ignored `output/` directory.
They include model replies and questions; review before sharing. The exact
model digest and Ollama version are printed and saved in the manifest.

## Exploratory pilots

The approach and study settings were chosen after local feasibility tests;
these results are not a held-out evaluation.

- GSM8K pilot, qwen2.5-coder:7b, temperature 0: 10 calls using BOOTH's
  default and reasoning prompts; 0 scoreable responses. The previous script
  did not record completion status, so it cannot determine completion for all
  responses. A later completion-check pilot stopped after an empty completed
  reply and an incomplete reply.
- GSM8K short-schema pilot, 7B, temperature 0.2: the first call timed out after
  180 seconds. A 3B short-schema pilot attempted three questions: two completed
  but were not scoreable as integers, and one was incomplete.
- Short-schema arithmetic feasibility pilot, 7B, temperature 0.2, seed 101:
  three previously used questions yielded one correct and two wrong scoreable
  answers, all confidence 1.0.
- Ten new self-authored arithmetic pilot questions, same 7B settings: all ten
  responses completed; nine were scoreable, with five correct and four wrong,
  all confidence 1.0. One answer, `:83`, was excluded by the integer-only
  scorer even though the reference was 83. For the nine scoreable responses,
  pilot ECE was 4/9 (approximately 0.444). The ten calls took 166.1 seconds.

Pilot machine: boothpy 0.5.8, Ollama 0.24.0, qwen2.5-coder:7b digest
`dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`,
Python 3.12.3, Linux x86_64. Pilot prompts, datasets and selection changed;
there is no controlled comparison between them. The models and settings were
selected after inspecting the pilots. The final run must remain separate.

## Raw study responses

Each line is a JSON object containing the question number, question, reference
answer and exact model response text. All replies had `done: true`; detailed
BOOTH status and grading appear in the saved records.

```jsonl
{"index": 1, "question": "What is 31 plus 27?", "reference": 58, "raw": "{\n\"answer\": \"58\",\n\"confidence\": 1.0\n}"}
{"index": 2, "question": "What is 43 plus 29?", "reference": 72, "raw": "{\n\"answer\": \"62\",\n\"confidence\": 1\n}"}
{"index": 3, "question": "What is 58 plus 16?", "reference": 74, "raw": "{\n\"answer\": \"24\",\n\"confidence\": 1\n\n}"}
{"index": 4, "question": "What is 72 plus 19?", "reference": 91, "raw": "{\n\"answer\": \"131\",\n\"confidence\": 1\n  }"}
{"index": 5, "question": "What is 36 plus 48?", "reference": 84, "raw": "{\n\"answer\": \"120\",\n\"confidence\": 1.0\n}"}
{"index": 6, "question": "What is 54 plus 37?", "reference": 91, "raw": "{\n\"answer\": \"81\",\n   \"confidence\": 1\n}"}
{"index": 7, "question": "What is 67 plus 25?", "reference": 92, "raw": "{\n\"answer\": \"92\",\n\"confidence\": 1\n\n}"}
{"index": 8, "question": "What is 81 plus 34?", "reference": 115, "raw": "{\n\"answer\": \"2\",\n\"confidence\": 1\n}"}
{"index": 9, "question": "What is 93 minus 47?", "reference": 46, "raw": "{\n\"answer\": \"56\",\n   \"confidence\": 1\n}"}
{"index": 10, "question": "What is 86 minus 38?", "reference": 48, "raw": "{\n\"answer\": \"58\",\n   \"confidence\": 1\n\n}"}
{"index": 11, "question": "What is 120 minus 54?", "reference": 66, "raw": "{\n  \"answer\": \"66\",\n      \"confidence\": 1\n }\n"}
{"index": 12, "question": "What is 175 minus 89?", "reference": 86, "raw": "{\n\"answer\": \"36\",\n\"confidence\": 1\n}"}
{"index": 13, "question": "What is 141 minus 58?", "reference": 83, "raw": "{\n  \"answer\": \"83\",\n      \"confidence\": 1\n }"}
{"index": 14, "question": "What is 99 minus 46?", "reference": 53, "raw": "{\n\"answer\": \"53\",\n\"confidence\": 1\n}"}
{"index": 15, "question": "What is 162 minus 75?", "reference": 87, "raw": "{\n\"answer\": \":97\",\n\"confidence\": 1\n}"}
{"index": 16, "question": "What is 134 minus 68?", "reference": 66, "raw": "{\n  \"answer\": \"66\",\n  \"confidence\":1.0\n}"}
{"index": 17, "question": "What is 13 multiplied by 8?", "reference": 104, "raw": "{\n\"answer\": \"56\",\n\"confidence\": 1\n}\n"}
{"index": 18, "question": "What is 16 multiplied by 6?", "reference": 96, "raw": "{\n\"answer\": \"{\\\"result\\\":96,\\\"confidence\\\":1}\"\n\n,\n\n\"confidence\":1\n}"}
{"index": 19, "question": "What is 21 multiplied by 4?", "reference": 84, "raw": "{\n\"answer\": \"84\",\n   \"confidence\": 1\n }\n"}
{"index": 20, "question": "What is 18 multiplied by 5?", "reference": 90, "raw": "{\n\"answer\": \"90\",\n\"confidence\": 1\n\n}"}
{"index": 21, "question": "What is 24 multiplied by 3?", "reference": 72, "raw": "{\n\"answer\": \"8\",\n\"confidence\": 1\n}"}
{"index": 22, "question": "What is 12 multiplied by 7?", "reference": 84, "raw": "{\n\"answer\": \"42\",\n   \"confidence\": 1\n}"}
{"index": 23, "question": "What is 17 multiplied by 4?", "reference": 68, "raw": "{\n\"answer\": \"68\",\n   \"confidence\": 1\n }\n"}
{"index": 24, "question": "What is 96 divided by 8?", "reference": 12, "raw": "{\n\"answer\": \"24\",\n\"confidence\": 1\n\n}"}
{"index": 25, "question": "What is 154 divided by 11?", "reference": 14, "raw": "{\n\"answer\": \"14\",\n\"confidence\": 1\n}"}
{"index": 26, "question": "What is 156 divided by 12?", "reference": 13, "raw": "{\n\"answer\": \"1.5\",\n\"confidence\": 1\n }"}
{"index": 27, "question": "What is 81 divided by 9?", "reference": 9, "raw": "{\n\"answer\": \"3\",\n\"confidence\": 1\n}"}
{"index": 28, "question": "What is 84 divided by 7?", "reference": 12, "raw": "{\n\"answer\": \"6\",\n   \"confidence\": 1\n\n}"}
{"index": 29, "question": "What is 120 divided by 10?", "reference": 12, "raw": "{\n\"answer\": \"12\",\n\"confidence\": 1\n}"}
{"index": 30, "question": "What is 110 divided by 11?", "reference": 10, "raw": "{\n\"answer\": \"10\",\n\"confidence\": 1\n}"}
```
