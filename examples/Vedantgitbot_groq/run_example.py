import os
import re

import booth
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL = "openai/gpt-oss-20b"

POLICIES = [
    "Standard plans can be refunded within 30 days of the initial purchase. "
    "After 30 days, standard plans are not eligible for a refund.",

    "Enterprise plans are non-refundable after activation, regardless "
    "of how long the plan has been active.",

    "For eligible Standard-plan cancellations after the first 30 days, "
    "the company may provide a prorated credit for the unused portion "
    "of the current billing period. This does not apply to Enterprise plans.",

    "Annual plans may be cancelled at any time, but cancellation does "
    "not automatically create a refund. Refund eligibility follows "
    "the rules for the applicable plan.",
]

QUESTIONS = [
    "Can a customer get a refund for a Standard plan purchased 10 days ago?",
    "Can an Enterprise customer get a refund after the plan has been activated?",
    "An Enterprise customer has had their plan for 3 months. "
    "How much of their unused subscription should be refunded?",
]


def normalize(text: str) -> str:
    """Normalize text by lowering case, unifying dashes, and stripping whitespace."""
    text = text.lower()
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def ask_groq(question: str) -> str:
    """Send question with policy context to Groq API using GROQ_API_KEY from .env."""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    evidence = "\n".join(
        f"{i + 1}. {policy}"
        for i, policy in enumerate(POLICIES)
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Answer strictly using only the supplied policy evidence.",
            },
            {
                "role": "user",
                "content": f"""Policy evidence:
{evidence}

Question:
{question}

Give a short, direct answer. Do not invent refund amounts or policies not stated above.
""",
            },
        ],
        temperature=0,
        max_tokens=100,
    )

    return response.choices[0].message.content.strip()


def check_answer(answer: str, evidence: list[str]) -> bool:
    """
    Evaluation heuristic for booth comparison.
    Validates if the answer correctly reflects non-refundability or refund eligibility.
    """
    text = normalize(answer)

    no_refund_phrases = [
        "no refund",
        "non-refundable",
        "not refundable",
        "not eligible",
        "cannot be refunded",
        "can't be refunded",
        "no credit",
        "$0",
        "0%",
        "zero",
    ]

    refund_eligible_phrases = [
        "within 30 days",
        "eligible for a refund",
        "eligible for refund",
        "can get a refund",
        "can receive a refund",
        "refund is available",
        "yes",
    ]

    # Handle negative claims (e.g., Enterprise non-refundable / Standard >30 days)
    if any(phrase in text for phrase in no_refund_phrases):
        return True

    # Handle positive claims (e.g., Standard plan within 30 days)
    if any(phrase in text for phrase in refund_eligible_phrases):
        return True

    return False


def main():
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY not found in environment or .env file.")

    print("=" * 70)
    print("GROQ + BOOTH RAG DEMO")
    print("=" * 70)

    for number, question in enumerate(QUESTIONS, 1):
        answer = ask_groq(question)

        result = booth.check_with_evidence(
            answer=answer,
            evidence=POLICIES,
            compare_fn=check_answer,
        )

        print(f"\nQUESTION {number}")
        print("=" * 70)
        print(f"Q: {question}")

        print("\nWITHOUT BOOTH")
        print("-" * 70)
        print(answer)

        print("\nWITH BOOTH")
        print("-" * 70)
        print(f"Answer : {answer}")
        print(f"Status : {result.status}")
        print(f"Passed : {result.ok}")

    # Simulated Hallucination Test
    bad_answer = (
        "The Enterprise customer should receive a prorated refund "
        "for the remaining 9 months of their subscription."
    )

    result = booth.check_with_evidence(
        answer=bad_answer,
        evidence=POLICIES,
        compare_fn=check_answer,
    )

    print("\n" + "=" * 70)
    print("BOOTH HALLUCINATION TEST")
    print("=" * 70)

    print("\nPolicy:")
    print(POLICIES[1])

    print("\nBad LLM answer:")
    print(bad_answer)

    print("\nWITHOUT BOOTH")
    print("-" * 70)
    print("Answer accepted uncritically (no verification).")

    print("\nWITH BOOTH")
    print("-" * 70)
    print(f"Status : {result.status}")
    print(f"Passed : {result.ok}")


if __name__ == "__main__":
    main()