**Gemma 3 12B: local four-arm run, 50 questions**

I ran the existing four-arm benchmark with `gemma3:12b` (`Q4_K_M`) using local Ollama on an M3 MacBook Air with 24 GiB RAM. Codex handled execution and the checks described below.

The source was unchanged upstream `main` at [a51f30c173776bfb6a47781a1e52b03f39b258a2](https://github.com/Vedantgitbot/booth/commit/a51f30c173776bfb6a47781a1e52b03f39b258a2). I used an isolated Python environment with `boothpy 0.5.8` installed from that checkout, and verified that the runner imported that copy.

I followed the [updated run instructions](https://github.com/Vedantgitbot/booth/issues/33#issuecomment-6710510420): smoke first, then four arms and one repetition. The ten-question smoke passed but took 25.8 minutes excluding setup, projecting about 4.3 hours for 100 questions, so I chose the permitted `--n 50` before the full run. The model tag and digest were fixed before inference and stayed unchanged.

This repeats the protocol on a second model with a smaller sample. It does not reproduce the published Qwen run's exact 100-question measurements. All four Gemma arms used the same 50 questions: 15 TriviaQA, 15 TruthfulQA and 20 GSM8K. Their IDs are the ordered per-dataset prefixes of the published list; no dataset fallback occurred.

Commands below use `python` to denote the isolated environment's interpreter; `RUN_DIR` was a fresh absolute evidence directory. Neither command used `--resume`.

```bash
python examples/Vedantgitbot_latency_accuracy/run_example.py --host http://127.0.0.1:11434 --model gemma3:12b --smoke --out "$RUN_DIR/smoke"
python examples/Vedantgitbot_latency_accuracy/run_example.py --host http://127.0.0.1:11434 --model gemma3:12b --n 50 --reps 1 --seed 42 --temperature 0 --num-predict 1024 --timeout 300 --out "$RUN_DIR/full"
```

Codex checked all 200 full-run records for complete, unique `(rep, qid, arm)` coverage, reconstructed the sampled inputs from the retained dataset cache, checked the randomized execution order, independently recomputed the grades, and reconciled the summary. Source, imports and model identity checks passed. All questions, including rejections, remain in the denominator. Raw records, manifests, cached source rows and command logs are retained locally.

**Unedited generated `summary.md` follows.**

<!-- BEGIN UNEDITED GENERATED SUMMARY -->
## Experiment configuration

| Configuration | Value |
|---|---|
| BOOTH version | boothpy 0.5.8 (default max_retries=1, threshold=0.7) |
| Python / OS | 3.12.13 / macOS-27.0-arm64-arm-64bit |
| Provider / Model | Ollama 0.40.15 / `gemma3:12b` |
| Model digest | `f4031aab637d1ffa37b42570452ae0e4fad0314754d17ded67322e4b95836f8a` |
| Temperature / Seed | 0.0 / 42 (num_predict=1024, timeout=300s per call) |
| Dataset versions | Hugging Face datasets-server, current `main` at run time (2026-11-12); see Datasets below |
| Questions / Repetitions | 50 / 1 |
| Hardware | CPU: Apple M3 (8 threads); RAM: 24.0 GiB; GPU: Apple Silicon integrated GPU (unified memory); Ollama placement: 80% GPU / 20% CPU |
| Setup / warm-up (excluded from results) | setup 18.7s incl. dataset fetch + model load; warm-up call 0.7s |
| Benchmark wall-clock this session | 7484s (all arms and reps, includes interleaving; excludes setup) |

## Arms

- **Plain model**: question + "Final answer:" instruction; the model may reason freely.
- **BOOTH prompt, no gate**: the question + BOOTH's exact JSON suffix, one call, no confidence check and no retries. Isolates the effect of the prompt from the effect of the gate.
- **BOOTH (default)**: `booth.check()` with default settings.
- **BOOTH + reasoning room**: `booth.check()` with BOOTH's suffix swapped (via `call_fn`) for one that lets the model reason before the JSON; same schema.

## Benchmark comparison

Pooled over 1 repetition(s) x 50 questions = 50 graded question-runs per arm. Accuracy denominator is ALL question-runs: rejected (AMBIGUOUS/UNCERTAIN), call-failed and unanswerable runs count as not correct.

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Accuracy (%) | 84.0 | 76.0 | 60.0 | 76.0 |
| Mean latency (s) | 23.65 | 37.71 | 36.01 | 52.30 |
| Median latency (s) | 4.60 | 29.94 | 30.43 | 52.47 |
| Total runtime (s, all reps) | 1182.7 | 1885.5 | 1800.5 | 2615.1 |
| Model calls (all reps) | 50 | 50 | 50 | 50 |
| Rejected (AMBIGUOUS + UNCERTAIN) | 0 | 0 | 11 | 4 |
| AMBIGUOUS | 0 | 0 | 11 | 4 |
| UNCERTAIN | 0 | 0 | 0 | 0 |
| Call failures (failed HTTP calls) | 0 | 0 | 0 | 0 |
| Questions with no response (all calls failed) | 0 | 0 | 0 | 0 |
| Correct / Incorrect / No-answer | 42 / 8 / 0 | 38 / 12 / 0 | 30 / 9 / 0 | 38 / 8 / 0 |

Derived (not part of the required table):

| Metric | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| Model calls per question | 1.00 | 1.00 | 1.00 | 1.00 |
| Mean latency vs plain (x) | 1.00 | 1.59 | 1.52 | 2.21 |
| Output tokens (all reps) | 4568 | 6866 | 6866 | 9974 |
| Accuracy among answered, non-rejected (%) | 84.0 | 76.0 | 76.9 | 82.6 |
| Accuracy if rejected answers were still graded (%) | 84.0 | 76.0 | 76.0 | 80.0 |

## Per-repetition results

| Rep | Arm | Accuracy (%) | Mean lat (s) | Median lat (s) | Runtime (s) | Calls | AMBIGUOUS | UNCERTAIN | Call failures |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Plain model | 84.0 | 23.65 | 4.60 | 1182.7 | 50 | 0 | 0 | 0 |
| 1 | BOOTH prompt, no gate | 76.0 | 37.71 | 29.94 | 1885.5 | 50 | 0 | 0 | 0 |
| 1 | BOOTH (default) | 60.0 | 36.01 | 30.43 | 1800.5 | 50 | 11 | 0 | 0 |
| 1 | BOOTH + reasoning room | 76.0 | 52.30 | 52.47 | 2615.1 | 50 | 4 | 0 | 0 |

## Accuracy by dataset (%, pooled over reps)

| Dataset | Questions | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| triviaqa | 15 | 60.0 | 60.0 | 53.3 | 60.0 |
| truthfulqa | 15 | 86.7 | 80.0 | 33.3 | 73.3 |
| gsm8k | 20 | 100.0 | 85.0 | 85.0 | 90.0 |

## Mean output tokens per question, by dataset

| Dataset | Plain model | BOOTH prompt, no gate | BOOTH (default) | BOOTH + reasoning room |
|---|---|---|---|---|
| triviaqa | 7 | 45 | 45 | 94 |
| truthfulqa | 5 | 84 | 84 | 234 |
| gsm8k | 220 | 247 | 247 | 253 |

## Datasets

| Name | Dataset ID | Config / split | Split size | Sampled | Licence |
|---|---|---|---|---|---|
| triviaqa | `mandarjoshi/trivia_qa` | rc.nocontext / validation | 17944 | 15 | Apache-2.0 |
| truthfulqa | `EleutherAI/truthful_qa_mc` | multiple_choice / validation | 684 | 15 | Apache-2.0 |
| gsm8k | `openai/gsm8k` | main / test | 1319 | 20 | MIT |

Sampling: `random.Random(f"{seed}:{dataset}").sample(...)` with seed 42. Question IDs and reference answers are in `output/manifest.json`.

<details><summary>Sampled question IDs</summary>

**triviaqa**: sfq_7483, jp_925, qg_2508, bt_2652, qw_9695, odql_9445, sfq_22425, jp_3307, bt_2624, sfq_380, sfq_23048, qw_6473, wh_326, sfq_4851, odql_389

**truthfulqa**: truthfulqa_mc-validation-600, truthfulqa_mc-validation-267, truthfulqa_mc-validation-248, truthfulqa_mc-validation-179, truthfulqa_mc-validation-323, truthfulqa_mc-validation-163, truthfulqa_mc-validation-51, truthfulqa_mc-validation-318, truthfulqa_mc-validation-632, truthfulqa_mc-validation-151, truthfulqa_mc-validation-236, truthfulqa_mc-validation-280, truthfulqa_mc-validation-641, truthfulqa_mc-validation-312, truthfulqa_mc-validation-21

**gsm8k**: gsm8k-test-948, gsm8k-test-198, gsm8k-test-248, gsm8k-test-1137, gsm8k-test-1071, gsm8k-test-401, gsm8k-test-3, gsm8k-test-467, gsm8k-test-490, gsm8k-test-785, gsm8k-test-1156, gsm8k-test-135, gsm8k-test-888, gsm8k-test-417, gsm8k-test-359, gsm8k-test-396, gsm8k-test-374, gsm8k-test-827, gsm8k-test-1277, gsm8k-test-681

</details>
<!-- END UNEDITED GENERATED SUMMARY -->

**Interpretation, separate from the generated summary**

- **Prompt effect:** plain scored 20/20 on GSM8K; JSON without a gate scored 17/20. Overall scores were 42/50 and 38/50.
- **Checking:** JSON without a gate and default BOOTH produced identical predictions for all 50 questions, with no retries. Default BOOTH rejected 11 answers as AMBIGUOUS, including eight that matched the reference, reducing overall accuracy to 30/50. Ten rejections were TruthfulQA; math stayed at 17/20.
- **Reasoning-first:** delivered math accuracy rose to 18/20 and overall to 38/50. It corrected two math misses but newly rejected one correct math answer, for a net recovery of one question. Mean latency was 52.30s versus 36.01s default (1.45×) and 23.65s plain (2.21×). Every arm used 1.00 model call/question; there were no failed HTTP calls or UNCERTAIN outcomes.
- **Limit:** one model, one seed, one repetition, and twenty math questions. GSM8K mean output tokens were 220 plain versus 247 JSON without a gate, so this run does not show the large token-count collapse reported for Qwen. The runner does not retain raw replies, leaving the reasoning-suppression mechanism unresolved here. The published Qwen aggregate uses 100 questions, so these percentages should not be used as a matched-sample model ranking.

Possible follow-up, **not run**: matched numeric questions that change one unit or comparison, such as percent versus percentage points, while retaining raw replies and rejection reasons.
