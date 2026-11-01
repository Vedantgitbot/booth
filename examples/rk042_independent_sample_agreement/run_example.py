"""Compare independent-sample agreement with model-reported confidence.

Requires Python 3.9+, Ollama, local model qwen2.5-coder:7b and boothpy 0.5.7.
The documented run used Ollama 0.24.0 and the model digest below.
From this folder (after starting Ollama):

    ollama pull qwen2.5-coder:7b
    python -m venv .venv
    .venv/bin/python -m pip install boothpy==0.5.7
    .venv/bin/python run_example.py

No API keys or environment variables are needed. Calls use Python's standard
library. This run makes 30 local model calls and may take several minutes.
"""

import json
import math
import platform
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from urllib.request import Request, urlopen

try:
    import booth
except ImportError:
    sys.exit("Install the dependency: python -m pip install boothpy==0.5.7")

HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5-coder:7b"
MODEL_DIGEST = "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"
OLLAMA_VERSION = "0.24.0"
TEMPERATURE = 0.2
SEEDS = (101, 102, 103)
CONFIDENCE_THRESHOLD = 0.7
TIMEOUT_SECONDS = 180
# Fresh self-authored questions, distinct from all earlier pilot questions.
QUESTIONS = (
    ("What is 16 multiplied by 7?", 112),
    ("What is 13 multiplied by 9?", 117),
    ("What is 18 multiplied by 8?", 144),
    ("What is 135 plus 48?", 183),
    ("What is 92 minus 36?", 56),
    ("What is 132 divided by 11?", 12),
    ("What is 28 plus 57?", 85),
    ("What is 11 multiplied by 14?", 154),
    ("What is 250 minus 86?", 164),
    ("What is 72 divided by 8?", 9),
)
SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["answer", "confidence"],
}


def request_json(path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def preflight():
    version = metadata.version("boothpy")
    if version != "0.5.7":
        sys.exit("This example requires boothpy==0.5.7; install it in a separate virtual environment.")
    try:
        server_version = request_json("/api/version")["version"]
        models = request_json("/api/tags")["models"]
        model = next(item for item in models if item.get("name") == MODEL)
        digest = model["digest"]
    except Exception as exc:
        sys.exit(f"Cannot inspect Ollama or find {MODEL}: {type(exc).__name__}: {exc}")
    if server_version != OLLAMA_VERSION or digest != MODEL_DIGEST:
        print(f"Warning: documented run used Ollama {OLLAMA_VERSION} and model digest "
              f"{MODEL_DIGEST}; this run uses Ollama {server_version} and model digest "
              f"{digest}. Results may differ.")
    print(f"Run UTC: {datetime.now(timezone.utc).isoformat()}")
    print(f"Python: {platform.python_version()}; OS: {platform.platform()}")
    print(f"boothpy: {version}; Ollama server: {server_version}")
    print(f"Model: {MODEL}; digest: {digest}")
    print(f"Dataset: {len(QUESTIONS)} self-authored integer-arithmetic questions")
    print(f"N: {len(SEEDS)}; temperature: {TEMPERATURE}; seeds: {SEEDS}; retries: 0")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}; timeout: {TIMEOUT_SECONDS}s")
    print("Agreement: all normalized integer answers equal; confidence applies to first answer.")


def sample(question, seed):
    prompt = (
        f"{question}\nReturn a JSON object with answer as an integer written "
        "as a string and confidence as your estimated probability of correctness "
        "between 0 and 1."
    )
    payload = {"model": MODEL, "prompt": prompt, "stream": False, "format": SCHEMA,
               "options": {"temperature": TEMPERATURE, "seed": seed}}
    started = time.monotonic()
    try:
        response = request_json("/api/generate", payload, timeout=TIMEOUT_SECONDS)
    except Exception as exc:
        return {"kind": "call_failure", "error": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.monotonic() - started, 1)}

    raw = response.get("response") if isinstance(response, dict) else None
    info = {"raw": raw, "done_reason": response.get("done_reason") if isinstance(response, dict) else None,
            "seconds": round(time.monotonic() - started, 1)}
    try:
        if not isinstance(raw, str):
            raise ValueError("API response has no text response field")
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("model response is not a JSON object")
        answer = obj.get("answer")
        if not isinstance(answer, str) or not re.fullmatch(r"[+-]?[0-9]+", answer.strip()):
            raise ValueError("answer is not an integer string")
        confidence = obj.get("confidence")
        valid_confidence = (not isinstance(confidence, bool) and isinstance(confidence, (int, float))
                            and math.isfinite(confidence) and 0 <= confidence <= 1)
        info.update(kind="valid_answer", answer=str(int(answer)),
                    confidence=confidence if valid_confidence else None)
        if not valid_confidence:
            info["confidence_error"] = "confidence is missing or outside [0, 1]"
    except (ValueError, TypeError) as exc:
        info.update(kind="invalid_response", error=str(exc))
    return info


def all_agree(answer, evidence):
    return all(answer == item for item in evidence)


def count_decision(counts, method, correct, accepted):
    key = f"{method}: {'correct' if correct else 'wrong'} first answer {'accepted' if accepted else 'rejected'}"
    counts[key] += 1


def main():
    preflight()
    counts = Counter()
    calls = 0
    eligible = 0
    first_sample_seconds = 0.0
    start = time.monotonic()
    for number, (question, expected) in enumerate(QUESTIONS, 1):
        print(f"\nQuestion {number}: {question} Expected: {expected}", flush=True)
        samples = []
        for seed in SEEDS:
            print(f"Running seed {seed}...", flush=True)
            item = sample(question, seed)
            if seed == SEEDS[0]:
                first_sample_seconds += item["seconds"]
            calls += 1
            counts[f"sample {item['kind']}"] += 1
            if item.get("confidence_error"):
                counts["invalid confidence"] += 1
            samples.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
        first = samples[0]
        if any(item["kind"] != "valid_answer" for item in samples) or first.get("confidence") is None:
            counts["excluded"] += 1
            print("Excluded from paired comparison: invalid answer, call failure, or invalid first confidence.")
            continue
        result = booth.check_with_evidence(
            answer=first["answer"], evidence=[item["answer"] for item in samples[1:]],
            compare_fn=all_agree,
        )
        if result.status not in (booth.ACCEPTED, booth.BLOCKED):
            counts["excluded"] += 1
            print(f"Excluded: agreement check returned {result.status}, reason={result.reason}, detail={result.detail}")
            continue
        eligible += 1
        correct = int(first["answer"]) == expected
        agreement_accepts = result.status == booth.ACCEPTED
        confidence_accepts = first["confidence"] >= CONFIDENCE_THRESHOLD
        count_decision(counts, "agreement", correct, agreement_accepts)
        count_decision(counts, "confidence", correct, confidence_accepts)
        print(f"First answer correct: {correct}")
        if not correct:
            print(f"Wrong first answer samples: {[item['answer'] for item in samples]}; "
                  f"agreed={agreement_accepts}; first confidence={first['confidence']}")
        print(f"Agreement: status={result.status}, reason={result.reason}, detail={result.detail}")
        print(f"Confidence: {'ACCEPT' if confidence_accepts else 'REJECT'}; score={first['confidence']}")

    print(f"\nSummary: questions={len(QUESTIONS)}, eligible={eligible}, excluded={counts['excluded']}")
    print(f"Actual calls={calls}; one-call baseline={len(QUESTIONS)}; extra calls={calls - len(QUESTIONS)}")
    print(f"Elapsed seconds={time.monotonic() - start:.1f}")
    print(f"Sum of first-call durations={first_sample_seconds:.1f}s "
          "(observed within this interleaved run; not a separate baseline run)")
    for kind in ("valid_answer", "invalid_response", "call_failure"):
        print(f"Samples {kind}: {counts['sample ' + kind]}")
    print(f"Samples with valid answers but invalid confidence: {counts['invalid confidence']}")
    for method in ("agreement", "confidence"):
        for correct in (True, False):
            for accepted in (True, False):
                key = f"{method}: {'correct' if correct else 'wrong'} first answer {'accepted' if accepted else 'rejected'}"
                print(f"{key}: {counts[key]}")
    print("Only eligible questions are counted above; agreement and confidence do not prove truth.")


if __name__ == "__main__":
    main()
