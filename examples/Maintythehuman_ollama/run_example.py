"""
This script demonstrates how to use the local Ollama model `qwen2.5-coder:7b` to answer 4 tricky questions
both plainly (WITHOUT BOOTH) and through `booth.check()` (WITH BOOTH). It also makes one `booth.acheck()` call.

Usage: python run_example.py

Requirements:
- pip install boothpy ollama
- A running Ollama server with the model pulled (`ollama pull qwen2.5-coder:7b`)
- No API keys or environment variables are needed.
"""

import sys
import time
import json
import asyncio

try:
    import ollama
except ImportError:
    sys.exit("The Ollama SDK is not installed. Run: pip install ollama")

try:
    import booth
except ImportError:
    sys.exit("BOOTH is not installed. Run: pip install boothpy")

MODEL = "qwen2.5-coder:7b"
OPTIONS = {"temperature": 0.2, "num_ctx": 4096}
SUFFIX = " Reply with just the final answer, no explanation."

# (id, question, expected answer or None if genuinely ambiguous / no single correct answer)
QUESTIONS = [
    ('01', 'What is the capital of Georgia?', None),  # ambiguous: country vs. US state
    ('02', 'How many times does the letter r appear in the word strawberry?', '3'),
    ('03', 'Who was the first person to walk on Mars?', 'No one / has not happened'),
    ('04', 'A farmer has 17 sheep. All but 9 run away. How many sheep are left?', '9'),
]


def call_llm(prompt: str) -> str:           # SYNC. For the plain call AND for booth.check()
    r = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt}], options=OPTIONS)
    return r["message"]["content"]


async def acall_llm(prompt: str) -> str:    # ASYNC. ONLY for booth.acheck()
    r = await ollama.AsyncClient().chat(model=MODEL, messages=[{"role": "user", "content": prompt}], options=OPTIONS)
    return r["message"]["content"]


def main():
    try:
        ollama.list()
    except Exception:
        raise SystemExit("Is Ollama running? Start it with `ollama serve`.")
    start = time.time()
    for qid, question, expected in QUESTIONS:
        prompt = question + SUFFIX            # the SAME prompt for the plain call and for BOOTH
        plain = call_llm(prompt)
        result = booth.check(call_llm, prompt, max_retries=1)
        print(f"Question {qid}: {question}")
        print(f"  Expected:      {expected}")
        print(f"  WITHOUT BOOTH: {plain}")
        print(f"  WITH BOOTH:    {result.status}, answer: {result.answer}, confidence: {result.confidence}")
        print("RESULT " + json.dumps({
            "id": qid,
            "question": question,
            "expected": expected,
            "plain": plain,
            "booth_status": result.status,
            "booth_answer": result.answer,
            "booth_confidence": result.confidence,
            "attempts": result.n_attempts,
        }))
    asyncio.run(async_demo())
    print(f"Finished {len(QUESTIONS)} questions in {time.time() - start:.0f}s.")


async def async_demo():
    result = await booth.acheck(acall_llm, QUESTIONS[0][1] + SUFFIX, max_retries=1)
    print(f"ASYNC: {result.status}, answer: {result.answer}, confidence: {result.confidence}")


if __name__ == "__main__":
    main()
