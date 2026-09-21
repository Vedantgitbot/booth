# BOOTH + Groq Integration Test Results

## Overview

| Parameter          | Value                     |
| ------------------ | ------------------------- |
| **Provider**       | Groq                      |
| **Model**          | `llama-3.3-70b-versatile` |
| **Date**           | September 21, 2026        |
| **BOOTH Version**  | 0.4.9 (`boothpy`)         |
| **BOOTH Function** | `check_with_evidence()`   |
| **Environment**    | Python 3.12 · macOS       |

## Test Results

| Test Case         | Scenario                                                    | Model Output                                                             | BOOTH Result           |
| ----------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------- |
| **Q1**            | Standard plan purchased 10 days ago — refund eligibility    | *“Yes, a Standard plan purchased 10 days ago is eligible for a refund.”* | `ACCEPTED` (`ok=True`) |
| **Q2**            | Activated Enterprise plan — refund eligibility              | *“No. Enterprise plans are non-refundable after activation.”*            | `ACCEPTED` (`ok=True`) |
| **Q3**            | Enterprise plan purchased 3 months ago — refund eligibility | *“No refund is due.”*                                                    | `ACCEPTED` (`ok=True`) |
| **Hallucination** | Injected false claim of a prorated Enterprise refund        | *“The Enterprise customer should receive a prorated refund...”*          | `BLOCKED` (`ok=False`) |

## Key Observations

### 1. Correct Policy Compliance

BOOTH correctly accepted model responses that were consistent with the supplied policy evidence. All three valid scenarios returned:

```text
ok=True
```

This demonstrates that `check_with_evidence()` can validate policy-grounded outputs rather than simply accepting model-generated responses.

### 2. Hallucination Detection

The hallucination test introduced a false claim that an Enterprise customer was entitled to a prorated refund. BOOTH rejected the response:

```text
ok=False
```

This indicates that the evidence-checking layer successfully identified a contradiction between the generated answer and the authoritative policy evidence.

### 3. Groq Integration

The integration successfully executed the full generation-and-verification flow using Groq's `llama-3.3-70b-versatile` model with BOOTH 0.4.9.

### 4. Performance

The test run completed rapidly with no measurable additional latency attributed to the verification step in this test environment.

## Summary

The integration test demonstrates that **BOOTH's `check_with_evidence()` function can act as an effective evidence-based guardrail for Groq-generated responses**.

Across the tested scenarios:

* Valid, policy-consistent responses were **accepted**.
* An intentionally hallucinated policy claim was **blocked**.
* The Groq + BOOTH pipeline operated successfully in the tested Python 3.12/macOS environment.
* No measurable verification latency was observed during the test run.

### Result

**Overall integration status: `PASS`**

The results support further testing with a broader set of policies, edge cases, conflicting evidence, ambiguous questions, and additional hallucination scenarios before using the guardrail in production.
