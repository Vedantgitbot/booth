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

## Summary
The integration confirms that `check_with_evidence()` works effectively with Anthropic's Claude 3.5 Haiku as an evidence-grounded verification layer.
