# Ollama (Llama 3.2) + BOOTH Integration & Benchmark Results

## Overview

This document records the empirical results and observations of running **BOOTH v0.5.2** against a local instance of **Ollama** running the **Llama 3.2 (3.2B)** model.

---

## Environment & Run Details

| Parameter | Value / Detail |
|---|---|
| **Provider** | Ollama (Local REST API) |
| **Model Name & Version** | `llama3.2:latest` (Llama 3.2 3B instruction-tuned model) |
| **Run Date** | October 4, 2026 |
| **BOOTH Version** | `0.5.2` (`pip show boothpy`) |
| **Python Version** | Python 3.11.9 |
| **Operating System** | Windows 11 (win32) |
| **BOOTH Functions Tested** | `booth.check()`, `booth.acheck()`, `booth.check_with_evidence()` |

---

## Execution Summary & Metrics

| Metric | Result |
|---|---|
| **Total Test Runs** | 5 evaluation test cases (2 sync `check()`, 1 async `acheck()`, 2 RAG `check_with_evidence()`) |
| **Successful Verifications** | 5 / 5 (100% expected behavior) |
| **JSON Format Compliance** | 100% (No malformed output parse errors) |
| **Confidence Calibration** | Factual queries returned confidence `0.90` |

---

## Actual Console Output

```text
======================================================================
BOOTH + Ollama (llama3.2:latest) Integration Example
======================================================================
BOOTH Version : 0.5.2
Ollama Server : http://localhost:11434
Ollama Model  : llama3.2:latest

======================================================================
DEMO 1: Synchronous Checkpoint (booth.check)
======================================================================

Prompt: What is the capital of France?
--------------------------------------------------
Status       : ACCEPTED
Passed (ok)  : True
Answer       : Paris
Confidence   : 0.9
Method       : confidence
Attempts     : 1

Prompt: What is the capital of New York State?
--------------------------------------------------
Status       : ACCEPTED
Passed (ok)  : True
Answer       : Albany
Confidence   : 0.9
Method       : confidence
Attempts     : 1

======================================================================
DEMO 2: Asynchronous Checkpoint (booth.acheck)
======================================================================

Async Prompt: What is 15 multiplied by 12?
--------------------------------------------------
Status       : ACCEPTED
Passed (ok)  : True
Answer       : 180
Confidence   : 0.9
Method       : confidence

======================================================================
DEMO 3: Evidence Grounding (booth.check_with_evidence)
======================================================================

Policy Context:
 - Standard subscription plans are eligible for a full refund within 30 days of purchase.
 - After 30 days, Standard plans are non-refundable.
 - Enterprise plans are strictly non-refundable once activated.

Test 1 (Accurate Answer): 'Standard plans can be refunded within 30 days of purchase.'
Status       : ACCEPTED
Passed (ok)  : True

Test 2 (Hallucinated Answer): 'Enterprise plans can be fully refunded anytime within 90 days.'
Status       : BLOCKED
Passed (ok)  : False
Reason       : EVIDENCE_DISAGREES
Detail       : compare_fn returned False

======================================================================
All Ollama + BOOTH integration demos completed successfully!
======================================================================
```

---

## Key Observations & What Worked Well

1. **Structured Output Adherence**:
   - `llama3.2:latest` followed BOOTH's formatted JSON instructions consistently without hallucinating invalid JSON keys or missing required fields (`ambiguous`, `interpretations`, `chosen_interpretation`, `answer`, `confidence`).

2. **Self-Reported Confidence Calibration**:
   - For factual questions (e.g. *"What is the capital of France?"*, *"What is 15 multiplied by 12?"*), Llama 3.2 reported consistent confidence scores of `0.9` (above default threshold `0.7`), allowing queries to pass on attempt 1 (`ACCEPTED`).

3. **Asynchronous Checkpointing (`booth.acheck`)**:
   - `booth.acheck()` worked seamlessly with `asyncio` event loops when wrapping model execution in non-blocking executors, returning identical structured results without blocking main application loops.

4. **Evidence Grounding (`booth.check_with_evidence`)**:
   - Hallucinated answers (e.g. claims contradicting refund eligibility windows) were correctly caught and flagged with status `BLOCKED` and reason `EVIDENCE_DISAGREES`.

---

## Instructions for Reproducing

1. **Install and start Ollama**:
   Download from [https://ollama.com](https://ollama.com) and start the service (`ollama serve`).

2. **Pull the Llama 3.2 model**:
   ```bash
   ollama pull llama3.2
   ```

3. **Install BOOTH & dependencies**:
   ```bash
   pip install boothpy requests
   ```

4. **Execute the example script**:
   ```bash
   python run_example.py
   ```
