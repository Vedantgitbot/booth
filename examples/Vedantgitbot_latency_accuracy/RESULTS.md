# BOOTH latency and accuracy overhead: 100 questions, local model

Same 100 questions, same local model, four ways of calling it: a plain model call, BOOTH's exact prompt with no checking, `booth.check()` with default settings, and `booth.check()` with a prompt that lets the model reason first. All numbers below come from one real run of `run_example.py` (`output/summary.md`). Nothing here is illustrative or edited.

**Read this first:** with BOOTH's default prompt, `qwen2.5:7b-instruct` scored 42.0% against 82.0% for the plain call. Most of that gap comes from BOOTH's prompt, which tells the model to output only JSON and so removes its step-by-step reasoning. It does not come from BOOTH's accept/reject logic. Letting the model reason before the JSON recovered GSM8K from 35.0% to 92.5%, but it did not help TruthfulQA or TriviaQA, and it made BOOTH slower than the plain call. Results from 100 questions, one model and one seed are illustrative and are not a general performance claim.

## Experiment configuration

| Configuration | Value |
|---|---|
| BOOTH version | boothpy 0.5.8 (default max_retries=1, threshold=0.7) |
| Python / OS | 3.12.7 / macOS-15.6.1-arm64-arm-64bit |
| Provider / Model | Ollama 0.35.0 / `qwen2.5:7b-instruct` |
| Model digest | `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` |
| Temperature / Seed | 0.0 / 42 (num_predict=1024, timeout=300s per call) |
| Dataset versions | Hugging Face datasets-server, current `main` at run time (2026-11-03); see Datasets below |
| Questions / Repetitions | 100 / 1 |
| Hardware | CPU: Apple M3 (8 threads); RAM: 16.0 GiB; GPU: Apple Silicon integrated GPU (unified memory); Ollama placement: 100% GPU / 0% CPU |
| Setup / warm-up (excluded from results) | setup 55.2s incl. dataset fetch + model load; warm-up call 0.2s |
| Benchmark wall-clock | 3990s (all arms, interleaved; excludes setup) |

## The four arms

| Arm | What it does |
|---|---|
| **Plain model** | The question plus a `Final answer:` instruction. The model may reason freely. |
| **BOOTH prompt, no gate** | The question plus BOOTH's exact JSON suffix, one call, no confidence check, no retries. This isolates the effect of the prompt from the effect of the gate. |
| **BOOTH (default)** | `booth.check()` with default settings. |
| **BOOTH + reasoning room** | `booth.check()`, with BOOTH's suffix swapped (through `call_fn`, no change to BOOTH itself) for one that asks the model to think step by step first and then output the same JSON object. |

## Benchmark comparison

100 graded question-runs per arm. The accuracy denominator is **all** questions: rejected (AMBIGUOUS/UNCERTAIN), call-failed and unanswerable runs count as not correct. Nothing is silently excluded.

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Accuracy (%) | 82.0 | 50.0 | 42.0 | 65.0 |
| Mean latency (s) | 10.60 | 5.11 | 4.92 | 19.27 |
| Median latency (s) | 1.26 | 4.26 | 4.30 | 17.74 |
| Total runtime (s) | 1059.6 | 510.6 | 492.3 | 1926.9 |
| Model calls | 100 | 100 | 100 | 101 |
| Rejected (AMBIGUOUS + UNCERTAIN) | 0 | 0 | 15 | 15 |
| AMBIGUOUS | 0 | 0 | 15 | 15 |
| UNCERTAIN | 0 | 0 | 0 | 0 |
| Call failures (failed HTTP calls) | 0 | 0 | 0 | 0 |
| Questions with no response | 0 | 0 | 0 | 0 |
| Correct / Incorrect / No-answer | 82 / 18 / 0 | 50 / 50 / 0 | 42 / 43 / 0 | 65 / 20 / 0 |

Derived metrics:

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Model calls per question | 1.00 | 1.00 | 1.00 | 1.01 |
| Mean latency vs plain (x) | 1.00 | 0.48 | 0.46 | 1.82 |
| Output tokens | 10780 | 4169 | 4169 | 18580 |
| Accuracy among answered, non-rejected (%) | 82.0 | 50.0 | 49.4 | 76.5 |
| Accuracy if rejected answers were still graded (%) | 82.0 | 50.0 | 50.0 | 71.0 |

Accuracy by dataset (%):

| Dataset | Questions | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|---|
| triviaqa | 30 | 66.7 | 63.3 | 63.3 | 56.7 |
| truthfulqa | 30 | 76.7 | 56.7 | 30.0 | 36.7 |
| gsm8k | 40 | 97.5 | 35.0 | 35.0 | 92.5 |

Mean output tokens per question:

| Dataset | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| triviaqa | 7 | 35 | 35 | 119 |
| truthfulqa | 5 | 56 | 56 | 144 |
| gsm8k | 261 | 36 | 36 | 267 |

## Observations, failures, and limitations

**What the numbers show**

- **BOOTH's prompt, not its checks, caused most of the accuracy gap.** BOOTH's exact prompt with no gate scored 50.0%, against 82.0% for the plain call. The gap is concentrated in GSM8K (97.5% to 35.0%), where the model wrote about 36 tokens per answer under BOOTH's prompt against 261 for the plain call. The prompt says "Output ONLY the JSON object, nothing else", which leaves the model no room to work through a maths problem.
- **Giving the model room to reason fixes maths.** With the reasoning-friendly suffix, GSM8K recovered to 92.5% (267 tokens per question, close to plain). This was done through `call_fn` and works with BOOTH 0.5.8 as released.
- **It does not fix the other datasets.** TruthfulQA stayed low (36.7% against 76.7% plain) and TriviaQA slipped to 56.7% (17 correct out of 30, against 20 for plain, so within noise at this sample size). Reasoning room is not a general improvement.
- **The AMBIGUOUS gate cost about 8 points.** Going from "no gate" to the default arm took accuracy from 50.0% to 42.0%. All 15 rejections were AMBIGUOUS (14 TruthfulQA, 1 TriviaQA). Of those 15 rejected answers, 8 would have been graded correct. For the same 15 questions, the plain call answered 13 correctly.
- **Self-reported confidence did not separate right from wrong.** In the default arm, 28 of the 43 accepted wrong answers had confidence of 0.95 or higher. In the reasoning arm, 18 of the 20 accepted wrong answers did. Calibration is out of scope for this example (tracked separately).
- **Retries almost never fired.** The default arm made exactly 100 calls (no retries, no UNCERTAIN). The reasoning arm made 101 calls: one retry, on one TriviaQA question, which ended REPAIRED and still wrong.
- **Latency depends on which statistic you read, and on the arm.** BOOTH's default prompt has a lower mean (4.92s against 10.60s) only because it skips reasoning; its median is higher (4.30s against 1.26s) because it always emits a JSON object, which costs time on short questions. With reasoning room, BOOTH was slower than the plain call on both statistics (mean 19.27s against 10.60s, 1.82x), because it produces the reasoning plus the JSON. The lower mean of the default arm should not be read as BOOTH being faster in general.
- **Failures:** 0 failed HTTP calls and 0 questions without a response, in all arms. No timeouts occurred.

**Limitations**

- One model (`qwen2.5:7b-instruct`, 7B), one machine, one sampling seed, 100 questions, one repetition. TriviaQA and TruthfulQA have 30 questions each, so differences of a few questions there are noise. A larger model, or one that reasons by default, may behave differently under BOOTH's prompt.
- The arms do not use identical prompts, by design: BOOTH adds its own JSON instructions, and the reasoning arm replaces them. The task text is identical; the output-format instructions differ.
- Repetitions are not used. At temperature 0 with a fixed seed, an earlier 3-repetition run of the plain and default arms gave identical accuracy in every repetition (82.0% and 42.0%, with 15 AMBIGUOUS per repetition), so repeating adds timing information but no statistical power. This run uses one repetition.
- The order of arms was randomised per question and the order of questions was shuffled, but Ollama's prompt caching was not controlled for.
- Total runtime per arm is the sum of per-question wall-clock times. Because arms were interleaved, it is not a separate end-to-end run of each arm.
- Grading is strict and deterministic. TriviaQA accepts a normalised exact match or a whole-phrase alias match, so correct answers worded differently from every alias are marked wrong. This affects all arms equally but lowers absolute TriviaQA accuracy. TruthfulQA is scored as multiple choice (the model must pick a letter), which is easier than free-form truthfulness. GSM8K compares the last number in the answer.
- The reasoning arm swaps BOOTH's prompt suffix from outside the library and keeps BOOTH's JSON schema. It is one way to test the idea, not a proposal for what BOOTH should ship.
- The optional `check_with_evidence()` arm was not run: these datasets provide no evidence passages.
- Only the default confidence threshold (0.7) was tested.

## Grading and normalisation methodology

Grading is deterministic; no LLM judge is used.

- **Accuracy denominator:** all 100 questions. A run counts as correct only if the arm returned an answer that matches the reference. For BOOTH arms, "returned an answer" means status ACCEPTED or REPAIRED. AMBIGUOUS and UNCERTAIN results are counted as rejected (not correct) and reported separately. A question where every model call failed is counted as "no response" (not correct) and also reported separately.
- **Extra accuracy views** (derived table): accuracy among accepted/answered runs only, and accuracy if rejected answers were still graded, so the effect of rejection is visible.
- **Plain arm answer extraction:** the text after the last `Final answer:`; if absent, the whole response.
- **BOOTH prompt, no gate arm:** the `answer` field of the JSON object in the reply. A reply that cannot be parsed counts as no answer.
- **BOOTH arms:** the `answer` field of the returned `BoothResult`.
- **TriviaQA:** lowercase, remove punctuation and articles (a, an, the), collapse whitespace. Correct if the normalised answer equals a normalised alias, or contains an alias (3 or more characters) as a whole phrase.
- **TruthfulQA (multiple choice):** the choices are shown as lettered options; the first letter of the answer is compared with the reference letter. In this run every multiple-choice answer in every arm was a single letter.
- **GSM8K:** the reference is the number after `####` with commas removed. The prediction is the last number in the answer (commas and `$` removed), compared as an exact fraction with a tolerance of 1e-6. For example `300.0` equals `300`.

## Datasets

| Name | Dataset ID | Config / split | Split size | Sampled | Licence |
|---|---|---|---|---|---|
| triviaqa | `mandarjoshi/trivia_qa` | rc.nocontext / validation | 17944 | 30 | Apache-2.0 |
| truthfulqa | `EleutherAI/truthful_qa_mc` | multiple_choice / validation | 684 | 30 | Apache-2.0 |
| gsm8k | `openai/gsm8k` | main / test | 1319 | 40 | MIT |

Licences are as recorded in `run_example.py`. Check them against each dataset card before relying on them. Datasets are downloaded at run time from Hugging Face and are not redistributed here. Please cite the original datasets (TriviaQA, TruthfulQA, GSM8K) when reusing the questions.

Sampling: `random.Random(f"{seed}:{dataset}").sample(...)` with seed 42. The sampled question IDs are listed below. Running the script with the same seed recreates the full manifest (IDs and reference answers) in `output/manifest.json`; the dataset source is read live, so a later change to a dataset upstream could alter it.

<details><summary>Sampled question IDs</summary>

**triviaqa**: sfq_7483, jp_925, qg_2508, bt_2652, qw_9695, odql_9445, sfq_22425, jp_3307, bt_2624, sfq_380, sfq_23048, qw_6473, wh_326, sfq_4851, odql_389, bb_5633, odql_10351, wh_527, bb_4034, qw_15572, jp_2940, sfq_18532, bb_8713, sfq_16955, bb_5563, odql_2399, odql_5971, qw_817, qw_16531, qb_498

**truthfulqa**: truthfulqa_mc-validation-600, truthfulqa_mc-validation-267, truthfulqa_mc-validation-248, truthfulqa_mc-validation-179, truthfulqa_mc-validation-323, truthfulqa_mc-validation-163, truthfulqa_mc-validation-51, truthfulqa_mc-validation-318, truthfulqa_mc-validation-632, truthfulqa_mc-validation-151, truthfulqa_mc-validation-236, truthfulqa_mc-validation-280, truthfulqa_mc-validation-641, truthfulqa_mc-validation-312, truthfulqa_mc-validation-21, truthfulqa_mc-validation-5, truthfulqa_mc-validation-30, truthfulqa_mc-validation-170, truthfulqa_mc-validation-519, truthfulqa_mc-validation-73, truthfulqa_mc-validation-572, truthfulqa_mc-validation-467, truthfulqa_mc-validation-543, truthfulqa_mc-validation-328, truthfulqa_mc-validation-194, truthfulqa_mc-validation-31, truthfulqa_mc-validation-233, truthfulqa_mc-validation-131, truthfulqa_mc-validation-196, truthfulqa_mc-validation-189

**gsm8k**: gsm8k-test-948, gsm8k-test-198, gsm8k-test-248, gsm8k-test-1137, gsm8k-test-1071, gsm8k-test-401, gsm8k-test-3, gsm8k-test-467, gsm8k-test-490, gsm8k-test-785, gsm8k-test-1156, gsm8k-test-135, gsm8k-test-888, gsm8k-test-417, gsm8k-test-359, gsm8k-test-396, gsm8k-test-374, gsm8k-test-827, gsm8k-test-1277, gsm8k-test-681, gsm8k-test-516, gsm8k-test-506, gsm8k-test-156, gsm8k-test-635, gsm8k-test-415, gsm8k-test-789, gsm8k-test-393, gsm8k-test-1097, gsm8k-test-893, gsm8k-test-1276, gsm8k-test-209, gsm8k-test-763, gsm8k-test-469, gsm8k-test-579, gsm8k-test-520, gsm8k-test-861, gsm8k-test-593, gsm8k-test-1101, gsm8k-test-426, gsm8k-test-434

</details>

## Reproduce

```
ollama pull qwen2.5:7b-instruct
python examples/Vedantgitbot_latency_accuracy/run_example.py            # 100 questions, 1 repetition
python examples/Vedantgitbot_latency_accuracy/run_example.py --n 200    # other sizes (50, 100, 200)
python examples/Vedantgitbot_latency_accuracy/run_example.py --smoke    # pipeline check only
```

The script writes raw per-call records to `output/results.jsonl`, the sampled questions to `output/manifest.json` and the tables to `output/summary.md`. The `output/` folder is not committed, so the raw per-call records of the run reported above are not in this repository; the tables in this file are taken from that run's `summary.md`. Provider access is isolated in the `Provider` class, so switching provider means changing that one class.