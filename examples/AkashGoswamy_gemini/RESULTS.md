# BOOTH + Google Gemini results

| Item | Value |
| --- | --- |
| Provider | Google Gemini (`google-genai` SDK) |
| Model | `gemini-3.5-flash-lite` |
| Date run | 2026-10-03 |
| BOOTH version | 0.5.2 (`boothpy`) |
| BOOTH functions | `check()`, `check_with_evidence()` |
| Python / OS | Python 3.11.9 / Windows |
| Runs | 1 full run of `run_example.py` (after fixing setup problems, see below) |

## Results

| Case | Function | Status | Notes |
| --- | --- | --- | --- |
| Capital of France | `check()` | ACCEPTED | answer "Paris", confidence 1.0, 1 attempt |
| Boiling point of water (C) | `check()` | ACCEPTED | answer "100", confidence 1.0, 1 attempt |
| Vague: "Is it a good idea to buy it?" | `check()` | AMBIGUOUS | 2 interpretations returned (unnamed stock/crypto, unnamed consumer product) |
| Standard plan, 10 days | `check_with_evidence()` | ACCEPTED | "Yes. Standard plans can be refunded within 30 days..." |
| Enterprise, activated | `check_with_evidence()` | ACCEPTED | "No, Enterprise plans are non-refundable after activation." |
| Injected hallucination (prorated Enterprise refund) | `check_with_evidence()` | BLOCKED | reason `EVIDENCE_DISAGREES` |

All 6 cases behaved as expected (6/6). No retries were needed in the final run; every `check()` call used 1 attempt.

## What worked well

- Gemini returned the JSON shape BOOTH asks for on the first try every time, with no markdown-fence or parsing problems.
- Ambiguity detection worked: the vague question was flagged AMBIGUOUS with sensible interpretations.
- The injected hallucination was blocked.

## Problems / surprises

- **Original model retired.** `gemini-2.5-flash-lite` returned `404 NOT_FOUND: no longer available to new users`; Google suggests `gemini-3.5-flash-lite`. The example uses the new model (override with `GEMINI_MODEL`).
- **`check()` hides API errors.** With a rejected key (401) and with the retired model (404), `check()` did not raise. It retried once and returned `UNCERTAIN`, `answer=None`, `attempts=2`, with no visible error. Passing `on_attempt=` and printing `attempt.error` exposes the real cause, and this example does so. Worth knowing for anyone debugging a bad key or model name.
- **New-style API keys.** My key started with `AQ.` rather than `AIza`. It worked with the current `google-genai` SDK after `pip install -U google-genai`; before the update I saw a 401 `ACCESS_TOKEN_TYPE_UNSUPPORTED` (this may also have been caused by using a deleted key at the time, so I can't say for certain which).
- The SDK prints an "automatic function calling" notice on the first call. It is harmless.
- The ambiguous case put an explanation in `.answer` with confidence 1.0; check `.ambiguous`/`.status`, not confidence, to detect it.
- `compare_fn` in this example is a simple refund-stance check, not a real semantic comparison.

## Reproducing

```bash
pip install -U boothpy google-genai
export GEMINI_API_KEY="your-key"   # PowerShell: $env:GEMINI_API_KEY="your-key"
python run_example.py
```
