"""Compare Ollama Qwen 2.5 Coder 3B responses with and without a JSON schema.

Run from a fresh clone with a local Ollama server and qwen2.5-coder:3b:

    python -m venv .venv
    .venv/bin/python -m pip install boothpy==0.5.6
    .venv/bin/python run_example.py

Install and start Ollama separately, then run: ollama pull qwen2.5-coder:3b
Only boothpy is required in the Python environment; HTTP uses the standard
library. The server must be reachable at http://127.0.0.1:11434. No environment
variables or API keys are required. The example makes eight model calls.
"""

import json
import platform
import sys
import time
from importlib import metadata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import booth
except ImportError:
    sys.exit("Missing boothpy. Install it with: python -m pip install boothpy==0.5.6")

HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5-coder:3b"
TEMPERATURE = 0.2
SEED = 42
TIMEOUT_SECONDS = 180
MAX_RETRIES = 0
QUESTIONS = (
    ("Simple fact", "What is the capital of France?"),
    ("Arithmetic", "What is 17 multiplied by 6?"),
    ("Potential ambiguity", "What is the capital of Georgia?"),
    ("Unanswerable", "What is the name of my next-door neighbor?"),
)
SCHEMA = {
    "type": "object",
    "properties": {
        "ambiguous": {"type": "boolean"},
        "interpretations": {"type": "array", "items": {"type": "string"}},
        "chosen_interpretation": {"type": ["string", "null"]},
        "answer": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["ambiguous", "interpretations", "chosen_interpretation", "answer", "confidence"],
}


def request_json(path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def verify_setup():
    dist = metadata.distribution("boothpy")
    direct_url = dist.read_text("direct_url.json")
    if dist.version != "0.5.6" or (direct_url and json.loads(direct_url).get("dir_info", {}).get("editable")):
        sys.exit("Use a separate environment with the published boothpy==0.5.6 (not an editable install).")
    try:
        version = request_json("/api/version")["version"]
        models = request_json("/api/tags")["models"]
    except (URLError, HTTPError, TimeoutError, ValueError, KeyError) as exc:
        sys.exit(f"Cannot read Ollama server metadata at {HOST}: {type(exc).__name__}: {exc}")
    model = next((entry for entry in models if entry.get("name") == MODEL), None)
    if model is None or not model.get("digest"):
        sys.exit(f"Model {MODEL} or its digest was not found. Run: ollama pull {MODEL}")
    print(f"boothpy: {dist.version}")
    print(f"Python: {platform.python_version()}")
    print(f"OS: {platform.platform()}")
    print(f"Ollama server: {version}")
    print(f"Model: {MODEL}")
    print(f"Model digest: {model['digest']}")
    print(f"Temperature: {TEMPERATURE}; seed: {SEED}; max_retries: {MAX_RETRIES}")
    print(f"Questions: {len(QUESTIONS)}; planned calls: {len(QUESTIONS) * 2}")


def run_case(label, question, use_schema):
    call_info = {}

    def call_llm(prompt):
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": TEMPERATURE, "seed": SEED},
        }
        if use_schema:
            payload["format"] = SCHEMA
        try:
            response = request_json("/api/generate", payload, timeout=TIMEOUT_SECONDS)
            if not isinstance(response, dict) or not isinstance(response.get("response"), str):
                raise ValueError("Ollama response did not contain a text response field")
        except Exception as exc:
            call_info["error"] = f"{type(exc).__name__}: {exc}"
            raise
        call_info["error"] = None
        call_info["done_reason"] = response.get("done_reason")
        call_info["response_empty"] = not response["response"].strip()
        return response["response"]

    started = time.monotonic()
    result = booth.check(call_llm, question, max_retries=MAX_RETRIES)
    print(f"\n[{label}] format={'schema' if use_schema else 'default'}")
    print(f"Question: {question}")
    print(f"Status: {result.status}; method: {result.method}; call_failed: {result.call_failed}")
    print(f"Answer: {result.answer!r}; confidence: {result.confidence}; interpretations: {result.interpretations!r}")
    print(f"Elapsed seconds: {time.monotonic() - started:.1f}")
    print(f"API error: {call_info.get('error')!r}; done_reason: {call_info.get('done_reason')!r}")
    print(f"Empty response text: {call_info.get('response_empty')!r}")
    if result.attempts:
        attempt = result.attempts[-1]
        print(f"Attempt error: {attempt.error!r}")
        print(f"Raw response: {attempt.raw_text!r}")
    return result


def main():
    verify_setup()
    print("\nEach question uses one fresh call per format; no retries.", flush=True)
    for label, question in QUESTIONS:
        for use_schema in (False, True):
            print(f"\nRunning {label} ({'schema' if use_schema else 'default'})...", flush=True)
            run_case(label, question, use_schema)


if __name__ == "__main__":
    main()
