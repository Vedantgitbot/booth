"""
Ollama (Llama 3.2) Integration Example for BOOTH

What it does:
    Demonstrates how to use BOOTH as a lightweight checkpoint layer for local
    LLM inference powered by Ollama and the Llama 3.2 model. Shows synchronous
    checkpointing with booth.check(), asynchronous checkpointing with booth.acheck(),
    and RAG evidence grounding with booth.check_with_evidence().

Provider & Model:
    Provider : Ollama (http://localhost:11434)
    Model    : llama3.2:latest (Llama 3.2 3B instruction model)

How to run:
    1. Ensure Ollama is installed and running:
       https://ollama.com
    2. Pull the Llama 3.2 model:
       ollama pull llama3.2
    3. Run this script:
       python run_example.py

Required Dependencies:
    - boothpy (pip install boothpy)
    - requests (pip install requests)

Environment Variables (Optional):
    - OLLAMA_HOST  : Base URL for Ollama API (default: http://localhost:11434)
    - OLLAMA_MODEL : Model name to use (default: llama3.2:latest)
"""

import asyncio
import os
import sys
import booth

try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required for this example.")
    print("Please install it using: pip install requests")
    sys.exit(1)


# Configuration
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
GENERATE_URL = f"{OLLAMA_HOST}/api/generate"
TAGS_URL = f"{OLLAMA_HOST}/api/tags"


def verify_ollama_connection():
    """Verify that Ollama server is running and the specified model is installed."""
    try:
        response = requests.get(TAGS_URL, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print("=" * 70)
        print("ERROR: Unable to connect to Ollama server.")
        print(f"Server URL : {OLLAMA_HOST}")
        print(f"Details    : {exc}")
        print("-" * 70)
        print("To fix this:")
        print("  1. Make sure Ollama is installed and running (ollama serve).")
        print("  2. Verify OLLAMA_HOST environment variable if using a custom port.")
        print("=" * 70)
        sys.exit(1)

    models_data = response.json().get("models", [])
    installed_models = [m.get("name", "") for m in models_data]

    # Normalize model name check (e.g. 'llama3.2' or 'llama3.2:latest')
    model_found = any(
        OLLAMA_MODEL == m or m.startswith(f"{OLLAMA_MODEL}:") or OLLAMA_MODEL.startswith(f"{m}:")
        for m in installed_models
    )

    if not model_found:
        print("=" * 70)
        print(f"ERROR: Model '{OLLAMA_MODEL}' is not found in your Ollama installation.")
        print(f"Installed models: {', '.join(installed_models) if installed_models else 'None'}")
        print("-" * 70)
        print("To fix this, pull the model by running:")
        print(f"  ollama pull {OLLAMA_MODEL}")
        print("=" * 70)
        sys.exit(1)


def call_ollama(prompt: str) -> str:
    """Synchronous model call to local Ollama generate API."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
        },
    }
    response = requests.post(GENERATE_URL, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


async def acall_ollama(prompt: str) -> str:
    """Async wrapper around Ollama caller for asyncio event loops."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call_ollama, prompt)


# Evidence ground-truth policy documents for RAG example
REFUND_POLICY = [
    "Standard subscription plans are eligible for a full refund within 30 days of purchase.",
    "After 30 days, Standard plans are non-refundable.",
    "Enterprise plans are strictly non-refundable once activated.",
]


def compare_refund_evidence(answer: str, evidence: list) -> bool:
    """Comparison function for check_with_evidence()."""
    ans_lower = answer.lower()
    # If claim says refund within 30 days or non-refundable for enterprise, mark valid
    if "30 days" in ans_lower or "non-refundable" in ans_lower or "eligible" in ans_lower:
        return True
    return False


def run_sync_checkpoint_demo():
    """Demo 1: booth.check() synchronous checkpoint."""
    print("\n" + "=" * 70)
    print("DEMO 1: Synchronous Checkpoint (booth.check)")
    print("=" * 70)

    questions = [
        "What is the capital of France?",
        "What is the capital of New York State?",
    ]

    for q in questions:
        print(f"\nPrompt: {q}")
        print("-" * 50)

        result = booth.check(call_ollama, q)

        print(f"Status       : {result.status}")
        print(f"Passed (ok)  : {result.ok}")
        print(f"Answer       : {result.answer}")
        print(f"Confidence   : {result.confidence}")
        print(f"Method       : {result.method}")
        print(f"Attempts     : {result.n_attempts}")


async def run_async_checkpoint_demo():
    """Demo 2: booth.acheck() asynchronous checkpoint."""
    print("\n" + "=" * 70)
    print("DEMO 2: Asynchronous Checkpoint (booth.acheck)")
    print("=" * 70)

    prompt = "What is 15 multiplied by 12?"
    print(f"\nAsync Prompt: {prompt}")
    print("-" * 50)

    result = await booth.acheck(acall_ollama, prompt)

    print(f"Status       : {result.status}")
    print(f"Passed (ok)  : {result.ok}")
    print(f"Answer       : {result.answer}")
    print(f"Confidence   : {result.confidence}")
    print(f"Method       : {result.method}")


def run_evidence_grounding_demo():
    """Demo 3: booth.check_with_evidence() RAG evidence grounding."""
    print("\n" + "=" * 70)
    print("DEMO 3: Evidence Grounding (booth.check_with_evidence)")
    print("=" * 70)

    print("\nPolicy Context:")
    for p in REFUND_POLICY:
        print(f" - {p}")

    # Case 1: Valid Grounded Answer
    grounded_answer = "Standard plans can be refunded within 30 days of purchase."
    print(f"\nTest 1 (Accurate Answer): '{grounded_answer}'")
    result_valid = booth.check_with_evidence(
        answer=grounded_answer,
        evidence=REFUND_POLICY,
        compare_fn=compare_refund_evidence,
    )
    print(f"Status       : {result_valid.status}")
    print(f"Passed (ok)  : {result_valid.ok}")

    # Case 2: Hallucinated / Disagreeing Answer
    hallucinated_answer = "Enterprise plans can be fully refunded anytime within 90 days."
    print(f"\nTest 2 (Hallucinated Answer): '{hallucinated_answer}'")
    result_blocked = booth.check_with_evidence(
        answer=hallucinated_answer,
        evidence=REFUND_POLICY,
        compare_fn=compare_refund_evidence,
    )
    print(f"Status       : {result_blocked.status}")
    print(f"Passed (ok)  : {result_blocked.ok}")
    print(f"Reason       : {result_blocked.reason}")
    print(f"Detail       : {result_blocked.detail}")


def main():
    print("=" * 70)
    print(f"BOOTH + Ollama ({OLLAMA_MODEL}) Integration Example")
    print("=" * 70)
    print(f"BOOTH Version : {booth.__version__}")
    print(f"Ollama Server : {OLLAMA_HOST}")
    print(f"Ollama Model  : {OLLAMA_MODEL}")

    # Step 1: Health check
    verify_ollama_connection()

    # Step 2: Run Demos
    run_sync_checkpoint_demo()
    asyncio.run(run_async_checkpoint_demo())
    run_evidence_grounding_demo()

    print("\n" + "=" * 70)
    print("All Ollama + BOOTH integration demos completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
