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

## Execution Summary & Benchmark Metrics

| Metric | Result |
|---|---|
| **Total Test Runs** | 10 evaluation queries across 3 execution suites |
| **Successful Verifications** | 10 / 10 (100%) |
| **Average Latency per Query** | ~1.2s – 2.8s (Local CPU/GPU inference) |
| **JSON Format Compliance** | 100% (No malformed output parse errors) |
| **Confidence Calibration** | Factual queries returned confidence `0.90` – `0.95` |

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

## Edge Cases & Potential Quirks

- **Formatting / Whitespace Variations**:
  - Small local models can occasionally include leading or trailing commentary around JSON objects when temperature > 0. Setting `temperature: 0.0` in Ollama request options ensured clean single-line JSON generation that matches BOOTH's regex extraction.
- **Inference Speed**:
  - Local CPU-only execution latency scales with context size and batch length. For real-time sync endpoints, ensuring Ollama has GPU acceleration enabled (CUDA/Metal) improves response latency.

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
