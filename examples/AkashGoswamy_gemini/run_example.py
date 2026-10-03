"""BOOTH + Google Gemini example.

Purpose
    Shows BOOTH checkpointing Gemini output in two ways:
      1. booth.check()               - ambiguity + confidence checks on a
                                       plain question (with retries).
      2. booth.check_with_evidence() - compares a RAG-style answer against
                                       evidence, and blocks a hallucination.

Provider / model
    Google Gemini via the `google-genai` SDK, model: gemini-3.5-flash-lite
    (override with the GEMINI_MODEL environment variable).

Dependencies
    pip install boothpy google-genai

Environment variables
    GEMINI_API_KEY   required. Get a free key at https://aistudio.google.com/apikey
    GEMINI_MODEL     optional. Defaults to gemini-3.5-flash-lite.

Run
    export GEMINI_API_KEY="your-key"      # PowerShell: $env:GEMINI_API_KEY="your-key"
    python run_example.py
"""

import os
import re
import sys

try:
    import booth
except ImportError:
    sys.exit("BOOTH is not installed. Run: pip install boothpy")

try:
    from google import genai
    from google.genai import types
except ImportError:
    sys.exit("The Gemini SDK is not installed. Run: pip install google-genai")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# --- Part 1: check() ---------------------------------------------------------

CHECK_QUESTIONS = [
    "What is the capital of France?",
    "What is the boiling point of water at sea level, in degrees Celsius?",
    "Is it a good idea to buy it?",  # deliberately vague: expect ambiguity
]

# --- Part 2: check_with_evidence() -------------------------------------------

POLICIES = [
    "Standard plans can be refunded within 30 days of the initial purchase. "
    "After 30 days, standard plans are not eligible for a refund.",
    "Enterprise plans are non-refundable after activation, regardless of how "
    "long the plan has been active.",
    "Annual plans may be cancelled at any time, but cancellation does not "
    "automatically create a refund. Refund eligibility follows the rules for "
    "the applicable plan.",
]

# (question, does the evidence allow a refund?)
RAG_QUESTIONS = [
    ("Can a customer get a refund for a Standard plan purchased 10 days ago?", True),
    ("Can an Enterprise customer get a refund after the plan is activated?", False),
]

HALLUCINATED_ANSWER = (
    "Yes, the Enterprise customer will receive a prorated refund for the "
    "remaining 9 months of their subscription."
)

NEGATIONS = ("not", "no ", "non-refundable", "cannot", "can't", "ineligible", "isn't")


def make_client() -> "genai.Client":
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit(
            "GEMINI_API_KEY is not set. Get a key at "
            "https://aistudio.google.com/apikey and run:\n"
            '  export GEMINI_API_KEY="your-key"'
        )
    return genai.Client(api_key=key)


def make_call_fn(client, system_instruction=None):
    """BOOTH only needs a function: str -> str."""

    def call_llm(prompt: str) -> str:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0, system_instruction=system_instruction
            ),
        )
        return response.text or ""

    return call_llm


def says_refundable(text: str) -> bool:
    """Very simple stance detector: does the answer claim a refund is possible?"""
    t = re.sub(r"\s+", " ", text.lower())
    if "refund" not in t and "credit" not in t:
        return False
    return not any(n in t for n in NEGATIONS)


def make_compare_fn(refund_allowed: bool):
    """Deliberately simple compare_fn (returns bool): the answer's stance on
    refunds must match what the evidence allows. Replace it with an
    embedding/NLI/LLM-judge comparison in real use."""

    def compare(answer: str, evidence) -> bool:
        return says_refundable(answer) == refund_allowed

    return compare


def show_attempt_error(i: int, attempt) -> None:
    """check() swallows exceptions from call_fn and retries; print them so a
    bad key / retired model is visible instead of a silent UNCERTAIN."""
    if attempt.error:
        print(f"  [attempt {i + 1} error] {attempt.error[:200]}")


def run_check(client) -> list:
    print("=" * 70)
    print(f"PART 1: booth.check()   model={MODEL}")
    print("=" * 70)
    call_llm = make_call_fn(client)
    results = []
    for q in CHECK_QUESTIONS:
        result = booth.check(call_llm, q, on_attempt=show_attempt_error)
        results.append(result)
        print(f"\nQ: {q}")
        print(f"  status   : {result.status}  (ok={result.ok})")
        print(f"  answer   : {result.answer}")
        print(f"  conf.    : {result.confidence}")
        print(f"  attempts : {result.n_attempts}")
        if result.interpretations:
            print(f"  readings : {result.interpretations}")
    return results


def run_evidence(client) -> list:
    print("\n" + "=" * 70)
    print(f"PART 2: booth.check_with_evidence()   model={MODEL}")
    print("=" * 70)
    numbered = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(POLICIES))
    call_llm = make_call_fn(
        client, "Answer strictly using only the supplied policy evidence. Be brief."
    )
    results = []
    for question, allowed in RAG_QUESTIONS:
        answer = call_llm(f"Policies:\n{numbered}\n\nQuestion: {question}")
        result = booth.check_with_evidence(
            answer=answer, evidence=POLICIES, compare_fn=make_compare_fn(allowed)
        )
        results.append(result)
        print(f"\nQ: {question}")
        print(f"  Gemini   : {answer.strip()}")
        print(f"  status   : {result.status}  (ok={result.ok}, reason={result.reason})")

    # Simulated hallucination: this should be BLOCKED.
    result = booth.check_with_evidence(
        answer=HALLUCINATED_ANSWER,
        evidence=POLICIES,
        compare_fn=make_compare_fn(False),  # Enterprise = non-refundable
    )
    results.append(result)
    print("\nInjected hallucination:")
    print(f"  answer   : {HALLUCINATED_ANSWER}")
    print(f"  status   : {result.status}  (ok={result.ok}, reason={result.reason})")
    return results


def main() -> None:
    client = make_client()
    try:
        check_results = run_check(client)
        evidence_results = run_evidence(client)
    except Exception as exc:  # network, quota, bad key, etc.
        sys.exit(f"\nGemini call failed: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, rs in (("check()", check_results), ("check_with_evidence()", evidence_results)):
        print(f"{name:24s}: {sum(r.ok for r in rs)}/{len(rs)} ok, "
              f"statuses={[r.status for r in rs]}")


if __name__ == "__main__":
    main()
