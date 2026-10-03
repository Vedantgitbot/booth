# BOOTH + Anthropic (Claude 3.5 Haiku) Integration Test Results

## Overview

| Parameter          | Value                                 |
| ------------------ | ------------------------------------- |
| **Provider**       | Anthropic                             |
| **Model**          | `claude-3-5-haiku-20241022`           |
| **Date**           | October 3, 2026                       |
| **BOOTH Version**  | 0.5.2 (`boothpy`)                     |
| **BOOTH Function** | `check_with_evidence()`               |
| **Environment**    | Python 3.12 · Linux                   |

## Test Results

| Test Case         | Scenario                                                    | Model Output                                                                                           | BOOTH Result           |
| ----------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------- |
| **Q1**            | Standard plan purchased 10 days ago — refund eligibility    | *“Yes, a customer can get a refund for a Standard plan purchased 10 days ago, as it is within the 30-day window.”* | `ACCEPTED` (`ok=True`) |
| **Q2**            | Activated Enterprise plan — refund eligibility              | *“No, Enterprise plans are non-refundable after activation, regardless of how long the plan has been active.”*     | `ACCEPTED` (`ok=True`) |
| **Q3**            | Enterprise plan purchased 3 months ago — refund eligibility | *“No refund is due. Enterprise plans are non-refundable once activated.”*                              | `ACCEPTED` (`ok=True`) |
| **Hallucination** | Injected false claim of a prorated Enterprise refund        | *“The Enterprise customer should receive a prorated refund for the remaining 9 months of their subscription.”*      | `BLOCKED` (`ok=False`) |

## Key Observations

### 1. Correct Policy Compliance
BOOTH accurately accepted responses that conformed to the policy rules. All three valid questions passed with:
```text
ok=True
status=ACCEPTED
```

### 2. Hallucination Guardrail
The simulated hallucination test presented an unsupported prorated refund claim for an activated Enterprise plan. BOOTH successfully caught and rejected it:
```text
ok=False
status=BLOCKED
```

### 3. Anthropic Integration
Claude 3.5 Haiku provides concise, structured answers that align naturally with `check_with_evidence()`, allowing fast and deterministic validation without added complexity.

## Evaluation Heuristic & Limitations

### Comparison Logic (`compare_fn`)
The evaluation function `check_answer()` verifies whether the generated response strictly follows the policy evidence provided:
1. **Refundable Scenarios (e.g. Q1 Standard within 30 days):** Evaluates if the response correctly confirms eligibility using approved phrases (`"within 30 days"`, `"eligible for a refund"`, `"can get a refund"`).
2. **Non-Refundable Scenarios (e.g. Q2/Q3 Enterprise plans):** Evaluates if the response correctly declares non-refundability using explicit denial phrases (`"no refund"`, `"non-refundable"`, `"not eligible"`).
3. **Hallucination Blocking:** When an answer falsely claims that an Enterprise customer receives a prorated refund, it contradicts policy statement #2 (`Enterprise plans are non-refundable after activation...`) and is blocked (`status=BLOCKED`, `ok=False`).

### Limitations
- **Lexical/Phrase-Based Matching:** The heuristic matches key phrase patterns against normalized text rather than running a secondary LLM judge.
- **Single-Turn Scope:** The example is scoped to single-turn policy QA; multi-turn negotiation or complex credit adjustments would require contextual state tracking.

## Summary
The integration confirms that `check_with_evidence()` works effectively with Anthropic's Claude 3.5 Haiku as an evidence-grounded verification layer.
