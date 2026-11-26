**Qwen3 8B: local four-arm run, 100 questions (BOOTH 0.6.0, issue #46)**

I ran the four-arm benchmark unchanged with `qwen3:8b` using local Ollama on Windows (model 100% on GPU), against BOOTH 0.6.0 from this repository's `src/`. Command: `python run_example.py --model qwen3:8b` (100 questions, 1 repetition, seed 42, temperature 0), after a passing `--smoke` run. Questions were fetched from the Hugging Face datasets-server; no dataset fallback occurred. Raw per-arm records: `results_qwen3-8b.jsonl`. Discussion is in issue #46.

**Read this first:**
- **Thinking was on.** Ollama enables it by default for `qwen3:8b`, and this run did not set it. Thinking tokens count toward `num_predict=1024` but are stripped from the reply, so some replies were cut off. That accounts for all 21 wrong plain answers that hit the cap (accuracy on the other 79 was 82%), all 25 `PARSE_FAILED` rows in the no-gate arm, and all 11 `UNCERTAIN` rows in the BOOTH default arm. No AMBIGUOUS row in the BOOTH default arm was truncated.
- **The AMBIGUOUS gate rejected many correct answers on TruthfulQA.** In the BOOTH default arm, 15 of 30 TruthfulQA questions were rejected as AMBIGUOUS, and 11 of those answers were correct.
- **Results vary between runs.** Even at temperature 0 with a fixed seed, repeated runs of this model give different results, so a single run like this one is not a precise measurement. The spread across repetitions is reported in issue #46.

This run predates the `truncated_calls` and `interpretations` fields, so its records don't have them. Truncation was inferred from `out_tokens` reaching `num_predict` on every call. Results from 100 questions, one model and one seed are illustrative and are not a general performance claim.

Everything below the line is `output/summary.md` from the run, unedited apart from replacing the local path on the BOOTH version line.

---

## Experiment configuration

| Configuration | Value |
|---|---|
| BOOTH version | 0.6.0 (loaded from this repository's `src/booth`) (default max_retries=1, threshold=0.7) |
| Python / OS | 3.14.6 / Windows-11-10.0.26300-SP0 |
| Provider / Model | Ollama 0.40.16 / `qwen3:8b` |
| Model digest | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| Temperature / Seed | 0.0 / 42 (num_predict=1024, timeout=300s per call) |
| Dataset versions | Hugging Face datasets-server, current `main` at run time (2026-11-25); see Datasets below |
| Questions / Repetitions | 100 / 1 |
| Hardware | CPU: AMD64 Family 25 Model 117 Stepping 2, AuthenticAMD (16 threads); RAM: 23.1 GiB; GPU: NVIDIA GeForce RTX 5050 Laptop GPU, 8151 MiB; Ollama placement: 100% GPU / 0% CPU |
| Setup / warm-up (excluded from results) | setup 52.5s incl. dataset fetch + model load; warm-up call 7.6s |
| Benchmark wall-clock this session | 6777s (all arms and reps, includes interleaving; excludes setup) |

## Arms

- **Plain model**: question + "Final answer:" instruction; the model may reason freely.
- **BOOTH prompt, no gate**: the question + BOOTH's exact JSON suffix, one call, no confidence check and no retries. Isolates the effect of the prompt from the effect of the gate.
- **BOOTH (default)**: `booth.check()` with default settings.
- **BOOTH + reasoning room**: `booth.check()` with BOOTH's suffix swapped (via `call_fn`) for one that lets the model reason before the JSON; same schema.

## Benchmark comparison

Pooled over 1 repetition(s) x 100 questions = 100 graded question-runs per arm. Accuracy denominator is ALL question-runs: rejected (AMBIGUOUS/UNCERTAIN), call-failed and unanswerable runs count as not correct.

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Accuracy (%) | 65.0 | 65.0 | 61.0 | 64.0 |
| Mean latency (s) | 14.05 | 14.67 | 19.60 | 19.46 |
| Median latency (s) | 12.17 | 13.48 | 14.15 | 13.93 |
| Total runtime (s, all reps) | 1404.8 | 1467.2 | 1959.8 | 1945.6 |
| Model calls (all reps) | 100 | 100 | 124 | 126 |
| Rejected (AMBIGUOUS + UNCERTAIN) | 0 | 0 | 34 | 31 |
| AMBIGUOUS | 0 | 0 | 23 | 19 |
| UNCERTAIN | 0 | 0 | 11 | 12 |
| Call failures (failed HTTP calls) | 0 | 0 | 0 | 0 |
| Questions with no response (all calls failed) | 0 | 0 | 0 | 0 |
| Correct / Incorrect / No-answer | 65 / 18 / 17 | 65 / 10 / 25 | 61 / 5 / 0 | 64 / 5 / 0 |

Derived (not part of the required table):

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Model calls per question | 1.00 | 1.00 | 1.24 | 1.26 |
| Mean latency vs plain (x) | 1.00 | 1.04 | 1.40 | 1.39 |
| Output tokens (all reps) | 61041 | 64904 | 85283 | 86794 |
| Accuracy among answered, non-rejected (%) | 65.0 | 65.0 | 92.4 | 92.8 |
| Accuracy if rejected answers were still graded (%) | 65.0 | 65.0 | 75.0 | 76.0 |

## Per-repetition results

| Rep | Arm | Accuracy (%) | Mean lat (s) | Median lat (s) | Runtime (s) | Calls | AMBIGUOUS | UNCERTAIN | Call failures |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Plain model | 65.0 | 14.05 | 12.17 | 1404.8 | 100 | 0 | 0 | 0 |
| 1 | BOOTH prompt, no gate | 65.0 | 14.67 | 13.48 | 1467.2 | 100 | 0 | 0 | 0 |
| 1 | BOOTH (default) | 61.0 | 19.60 | 14.15 | 1959.8 | 124 | 23 | 11 | 0 |
| 1 | BOOTH + reasoning room | 64.0 | 19.46 | 13.93 | 1945.6 | 126 | 19 | 12 | 0 |

## Accuracy by dataset (%, pooled over reps)

| Dataset | Questions | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| triviaqa | 30 | 63.3 | 63.3 | 60.0 | 60.0 |
| truthfulqa | 30 | 73.3 | 63.3 | 40.0 | 43.3 |
| gsm8k | 40 | 60.0 | 67.5 | 77.5 | 82.5 |

## Mean output tokens per question, by dataset

| Dataset | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| triviaqa | 380 | 505 | 530 | 672 |
| truthfulqa | 641 | 718 | 929 | 1013 |
| gsm8k | 760 | 705 | 1038 | 906 |

## Datasets

| Name | Dataset ID | Config / split | Split size | Sampled | Licence |
|---|---|---|---|---|---|
| triviaqa | `mandarjoshi/trivia_qa` | rc.nocontext / validation | 17944 | 30 | Apache-2.0 |
| truthfulqa | `EleutherAI/truthful_qa_mc` | multiple_choice / validation | 684 | 30 | Apache-2.0 |
| gsm8k | `openai/gsm8k` | main / test | 1319 | 40 | MIT |

Sampling: `random.Random(f"{seed}:{dataset}").sample(...)` with seed 42. Question IDs and reference answers are in `output/manifest.json`.

<details><summary>Sampled question IDs</summary>

**triviaqa**: sfq_7483, jp_925, qg_2508, bt_2652, qw_9695, odql_9445, sfq_22425, jp_3307, bt_2624, sfq_380, sfq_23048, qw_6473, wh_326, sfq_4851, odql_389, bb_5633, odql_10351, wh_527, bb_4034, qw_15572, jp_2940, sfq_18532, bb_8713, sfq_16955, bb_5563, odql_2399, odql_5971, qw_817, qw_16531, qb_498

**truthfulqa**: truthfulqa_mc-validation-600, truthfulqa_mc-validation-267, truthfulqa_mc-validation-248, truthfulqa_mc-validation-179, truthfulqa_mc-validation-323, truthfulqa_mc-validation-163, truthfulqa_mc-validation-51, truthfulqa_mc-validation-318, truthfulqa_mc-validation-632, truthfulqa_mc-validation-151, truthfulqa_mc-validation-236, truthfulqa_mc-validation-280, truthfulqa_mc-validation-641, truthfulqa_mc-validation-312, truthfulqa_mc-validation-21, truthfulqa_mc-validation-5, truthfulqa_mc-validation-30, truthfulqa_mc-validation-170, truthfulqa_mc-validation-519, truthfulqa_mc-validation-73, truthfulqa_mc-validation-572, truthfulqa_mc-validation-467, truthfulqa_mc-validation-543, truthfulqa_mc-validation-328, truthfulqa_mc-validation-194, truthfulqa_mc-validation-31, truthfulqa_mc-validation-233, truthfulqa_mc-validation-131, truthfulqa_mc-validation-196, truthfulqa_mc-validation-189

**gsm8k**: gsm8k-test-948, gsm8k-test-198, gsm8k-test-248, gsm8k-test-1137, gsm8k-test-1071, gsm8k-test-401, gsm8k-test-3, gsm8k-test-467, gsm8k-test-490, gsm8k-test-785, gsm8k-test-1156, gsm8k-test-135, gsm8k-test-888, gsm8k-test-417, gsm8k-test-359, gsm8k-test-396, gsm8k-test-374, gsm8k-test-827, gsm8k-test-1277, gsm8k-test-681, gsm8k-test-516, gsm8k-test-506, gsm8k-test-156, gsm8k-test-635, gsm8k-test-415, gsm8k-test-789, gsm8k-test-393, gsm8k-test-1097, gsm8k-test-893, gsm8k-test-1276, gsm8k-test-209, gsm8k-test-763, gsm8k-test-469, gsm8k-test-579, gsm8k-test-520, gsm8k-test-861, gsm8k-test-593, gsm8k-test-1101, gsm8k-test-426, gsm8k-test-434

</details>
