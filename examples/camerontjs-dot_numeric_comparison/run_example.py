"""BOOTH issue #36: matched numeric checkpoints on synthetic cases and Gemma.

Requirements: Python 3.9+, boothpy==0.5.9, local Ollama and gemma3:12b.
No provider SDK, API key, or extra BOOTH dependency is needed.

From the repository root, install the checkout in a clean environment:
    python -m pip install -e '.[dev]'
    python examples/camerontjs-dot_numeric_comparison/run_example.py --smoke
    python examples/camerontjs-dot_numeric_comparison/run_example.py

Use --out PATH for a fresh output directory, --controls-only to exercise
authored fixtures without a model, and --expected-digest SHA to require a
particular installed model. See PROTOCOL.md for settings, denominators,
the bounded source/answer grammar and the live-versus-control distinction.
The validator arm replays the same first reply; retry repair is not tested.
Raw provider request/response text is written before parsing or grading.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import booth
except ImportError as exc:
    raise SystemExit("Install the BOOTH checkout: python -m pip install -e '.[dev]'") from exc

from grade_answers import grade_answer

HERE = Path(__file__).resolve().parent
ARMS = ("check", "validator", "keyword_evidence", "numeric_evidence")
NUMBER = r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
QUANTITY = re.compile(
    r"(?:(?P<prefix>CAD|USD|EUR)\s*)?"
    r"(?P<amount>[-+]?" + NUMBER + r"|\(" + NUMBER + r"\))"
    r"\s*(?:(?P<scale>thousand|million)\s+)?"
    r"(?P<unit>CAD|USD|EUR|%|percent|fraction|percentage points?|days?|months?|items?)?",
    re.IGNORECASE,
)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def append_jsonl(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def parse_quantity(text):
    """Parse one supported, explicitly unit-bearing quantity; no free prose."""
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("expected a short quantity string")
    text = text.strip()
    whole_negative = text.startswith("(") and text.endswith(")")
    if whole_negative:
        text = text[1:-1].strip()
    match = QUANTITY.fullmatch(text)
    if match is None:
        raise ValueError("unsupported quantity grammar")
    prefix, suffix = match.group("prefix"), match.group("unit")
    if prefix and suffix:
        raise ValueError("currency/unit supplied twice")
    unit = (prefix or suffix or "").casefold()
    if not unit:
        raise ValueError("explicit unit or currency required")
    amount = match.group("amount").replace(",", "")
    if whole_negative:
        if amount.startswith(("-", "+", "(")):
            raise ValueError("signed or nested amount inside negative parentheses")
        amount = "-" + amount
    if amount.startswith("("):
        amount = "-" + amount[1:-1]
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    scale = {None: Decimal(1), "thousand": Decimal(1000), "million": Decimal(1000000)}[
        (match.group("scale") or "").casefold() or None
    ]
    if scale != 1 and unit not in ("cad", "usd", "eur"):
        raise ValueError("scales supported for currencies only")
    with localcontext() as context:
        context.prec = 256
        value *= scale
        if unit in ("%", "percent"):
            value /= 100
            dimension = "rate"
        elif unit == "fraction":
            dimension = "rate"
        elif unit in ("percentage point", "percentage points"):
            dimension = "percentage_points"
        elif unit in ("cad", "usd", "eur"):
            dimension = unit.upper()
        else:
            dimension = unit.rstrip("s") + "s"
    return value, dimension


def numeric_decision(answer, evidence, target, round_places=None):
    """Read the requested source field, never a fixture reference or label."""
    matches = []
    for passage in evidence:
        if not isinstance(passage, str):
            return {"passed": False, "reason": "non-text source"}
        for line in passage.splitlines():
            label, separator, value = line.partition(":")
            if separator and label.strip().casefold() == target.casefold():
                matches.append(value.strip())
    if len(matches) != 1:
        return {"passed": False, "reason": "target field missing or duplicated"}
    try:
        expected, dimension = parse_quantity(matches[0])
        actual, actual_dimension = parse_quantity(answer)
        if round_places is not None:
            if dimension not in ("CAD", "USD", "EUR"):
                raise ValueError("explicit rounding supported for currencies only")
            if not isinstance(round_places, int) or not 0 <= round_places <= 6:
                raise ValueError("unsupported rounding precision")
            with localcontext() as context:
                context.prec = 256
                expected = expected.quantize(Decimal(1).scaleb(-round_places), rounding=ROUND_HALF_UP)
    except (ValueError, InvalidOperation) as exc:
        return {"passed": False, "reason": str(exc)}
    passed = dimension == actual_dimension and actual == expected
    return {
        "passed": passed,
        "reason": "quantity matches requested source field" if passed else "value or unit differs from requested source field",
        "source_value": str(expected), "source_dimension": dimension,
        "answer_value": str(actual), "answer_dimension": actual_dimension,
    }


def keyword_overlap(answer, evidence):
    words = set(re.findall(r"[A-Za-z0-9]+", (answer or "").casefold()))
    source_words = set(re.findall(r"[A-Za-z0-9]+", " ".join(evidence).casefold()))
    return len(words & source_words) / len(words) if words else 0.0


def prompt_for(case):
    return (
        "Use only the synthetic source below to answer the question.\n"
        "Source:\n" + case["source"] + "\n\nQuestion: " + case["question"]
    )


def replay_check(raw, prompt, validator=None, expected_prompt=None):
    def replay(actual_prompt):
        if expected_prompt is not None and actual_prompt != expected_prompt:
            raise RuntimeError("replay prompt differs from actual provider prompt")
        return raw
    return booth.check(replay, prompt, threshold=0.7, max_retries=0, validator=validator)


def checkpoints(case, raw, first=None, provider_prompt=None):
    prompt = prompt_for(case)
    first = first if first is not None else replay_check(raw, prompt)
    evidence = [case["source"]]

    def validator(answer):
        decision = numeric_decision(answer, evidence, case["target"], case["round_places"])
        return decision["passed"], decision["reason"]

    def numeric(answer, supplied_evidence):
        return numeric_decision(answer, supplied_evidence, case["target"], case["round_places"])["passed"]

    results = {
        "check": first,
        "validator": replay_check(raw, prompt, validator, provider_prompt),
        "keyword_evidence": booth.check_with_evidence(first.answer, evidence, keyword_overlap, evidence_threshold=0.5),
        "numeric_evidence": booth.check_with_evidence(first.answer, evidence, numeric),
    }
    return {
        "case_id": case["id"], "category": case["category"], "answer": first.answer,
        "grade": grade_answer(case, first.answer),
        "numeric_rule": numeric_decision(first.answer, evidence, case["target"], case["round_places"]),
        "arms": {name: result.to_dict() for name, result in results.items()},
    }


class ProviderFailure(RuntimeError):
    pass


class Provider:
    def __init__(self, host, model, options, timeout, out):
        self.host, self.model = host.rstrip("/"), model
        self.options, self.timeout, self.out = options, timeout, out
        self.case_id, self.calls, self.last = None, 0, None

    def __call__(self, prompt):
        payload = {"model": self.model, "prompt": prompt, "stream": False, "keep_alive": "5m", "options": self.options}
        request_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        request = urllib.request.Request(self.host + "/api/generate", data=request_text.encode(), headers={"Content-Type": "application/json"})
        record = {"case_id": self.case_id, "started_utc": utc(), "request_text": request_text, "request_sha256": sha_bytes(request_text.encode())}
        started = time.monotonic()
        self.calls += 1
        raw_http = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                try:
                    raw_http = response.read()
                except http.client.IncompleteRead as exc:
                    raw_http = exc.partial
                    raise
            record["response_text"] = raw_http.decode("utf-8")
            record["response_sha256"] = sha_bytes(raw_http)
            data = json.loads(record["response_text"])
            record["raw_reply"] = data.get("response")
            record["done"] = data.get("done")
            record["done_reason"] = data.get("done_reason")
            if data.get("error"):
                raise ProviderFailure(str(data["error"]))
            if data.get("done") is not True or data.get("done_reason") == "length":
                raise ProviderFailure("incomplete or token-limited generation")
            if not isinstance(record["raw_reply"], str):
                raise ProviderFailure("provider response is not text")
            record["error"] = None
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    raw_http = exc.read()
                except http.client.IncompleteRead as partial:
                    raw_http = partial.partial
            record["error"] = type(exc).__name__ + ": " + str(exc)
        if raw_http is not None:
            record["response_base64"] = base64.b64encode(raw_http).decode("ascii")
            record["response_text"] = raw_http.decode("utf-8", errors="replace")
            record["response_sha256"] = sha_bytes(raw_http)
        record["elapsed_s"] = time.monotonic() - started
        self.last = record
        append_jsonl(self.out / "provider_calls.jsonl", record)
        if record["error"]:
            raise ProviderFailure(record["error"])
        return record["raw_reply"]


def get_json(host, endpoint):
    with urllib.request.urlopen(host.rstrip("/") + "/api/" + endpoint, timeout=15) as response:
        return json.load(response)


def model_identity(host, model):
    tags = get_json(host, "tags")
    found = [item for item in tags["models"] if item["name"] == model]
    if len(found) != 1:
        raise ProviderFailure("exact installed model tag not found: " + model)
    selected = found[0]
    return {"name": selected["name"], "digest": selected["digest"], "size": selected["size"], "details": selected.get("details", {})}


def git_value(*args):
    return subprocess.check_output(["git", "-C", str(HERE), *args], text=True).strip()


def hardware():
    result = {"machine": platform.machine(), "processor": platform.processor()}
    if platform.system() == "Darwin":
        for key in ("hw.memsize", "hw.ncpu", "machdep.cpu.brand_string"):
            try:
                result[key] = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
            except (OSError, subprocess.CalledProcessError):
                result[key] = "UNKNOWN"
    return result


def summarize(records):
    summary = {}
    for layer in sorted({row["layer"] for row in records}):
        rows = [row for row in records if row["layer"] == layer]
        by_arm = {}
        for arm in ARMS:
            counts = Counter()
            statuses = Counter()
            for row in rows:
                result, label = row["arms"][arm], row["grade"]["label"]
                accepted = result["ok"]
                counts["attempted"] += 1
                counts[label] += 1
                counts[label + ("_accepted" if accepted else "_withheld")] += 1
                statuses[result["status"]] += 1
                counts["call_failed"] += bool(result["call_failed"])
                counts["all_parse_failed"] += bool(result["all_parse_failed"])
                counts["checker_failed"] += bool(result["checker_failed"])
            keys = ("attempted", "correct", "wrong", "unscoreable", "no_answer", "correct_accepted", "correct_withheld", "wrong_accepted", "wrong_withheld", "unscoreable_accepted", "unscoreable_withheld", "no_answer_accepted", "no_answer_withheld", "call_failed", "all_parse_failed", "checker_failed")
            by_arm[arm] = {key: counts[key] for key in keys}
            by_arm[arm]["statuses"] = dict(sorted(statuses.items()))
        summary[layer] = by_arm
    return summary


def report_markdown(summary, manifest, complete):
    lines = ["# Generated numeric checkpoint results", "", "Generated from records.jsonl; authored controls and live Gemma replies are separate.", "", "## Configuration", "", "- Run status: " + complete["status"], "- BOOTH: " + manifest["booth_version"], "- Source commit: `" + manifest["source_commit"] + "`", "- Model: `" + str(manifest.get("model", {}).get("name", "not invoked")) + "`", "- Model digest: `" + str(manifest.get("model", {}).get("digest", "not invoked")) + "`", "- Live provider calls: " + str(complete["live_case_calls"]) + "; warm-up calls: " + str(complete["warmup_calls"]), "- Questions: " + str(len(manifest["case_order"])) + "; one repetition; retries disabled.", ""]
    for layer, arms in summary.items():
        lines += ["## " + layer, "", "| Metric | check | validator | keyword evidence | numeric evidence |", "|---|---:|---:|---:|---:|"]
        metrics = [("All answer-checks", "attempted"), ("Correct answers", "correct"), ("Wrong answers", "wrong"), ("Unscoreable answers", "unscoreable"), ("Missing answers", "no_answer"), ("Wrong accepted", "wrong_accepted"), ("Wrong withheld", "wrong_withheld"), ("Correct accepted", "correct_accepted"), ("Correct withheld", "correct_withheld"), ("Unscoreable accepted", "unscoreable_accepted"), ("Unscoreable withheld", "unscoreable_withheld"), ("Call failures", "call_failed"), ("All-parse-failed", "all_parse_failed"), ("Checker failures", "checker_failed")]
        for title, key in metrics:
            lines.append("| " + title + " | " + " | ".join(str(arms[a][key]) for a in ARMS) + " |")
        for status in ("ACCEPTED", "REPAIRED", "BLOCKED", "UNCERTAIN", "AMBIGUOUS"):
            lines.append("| Status " + status + " | " + " | ".join(str(arms[a]["statuses"].get(status, 0)) for a in ARMS) + " |")
        lines += ["", "All answer-checks remain in the attempted denominator. Wrong-withheld rates use the wrong-answer count; correct-withheld rates use the correct-answer count. Unscoreable/missing answers are separate, never silently removed. 'Withheld' includes every non-ok status; literal BLOCKED is shown separately.", ""]
    lines += ["## Limits", "", "One authored synthetic demonstration, one model and one seed. The validator replays the first raw reply; no retry recovery or independent model-arm latency is measured. The numeric rule uses explicit labelled source fields and a bounded quantity grammar, not general financial-language understanding. See PROTOCOL.md.", ""]
    return "\n".join(lines)


def run(args):
    out = Path(args.out).resolve() if args.out else HERE / "output" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True, exist_ok=False)
    started, start_clock = utc(), time.monotonic()
    records = []
    calls, warmup_calls = 0, 0
    manifest = None
    try:
        fixtures = json.loads((HERE / "cases.json").read_text())
        cases = fixtures["smoke_cases" if args.smoke else "cases"]
        cases = list(cases)
        random.Random(args.seed).shuffle(cases)
        manifest = {
            "schema": 1, "started_utc": started, "phase": "smoke" if args.smoke else "main",
            "controls_only": args.controls_only, "source_commit": git_value("rev-parse", "HEAD"),
            "source_tree": git_value("rev-parse", "HEAD^{tree}"),
            "booth_version": booth.__version__, "installed_distribution": importlib.metadata.version("boothpy"),
            "python": platform.python_version(), "os": platform.platform(), "hardware": hardware(),
            "file_hashes": {name: sha_bytes((HERE / name).read_bytes()) for name in ("run_example.py", "grade_answers.py", "cases.json", "PROTOCOL.md")},
            "booth_core_sha256": sha_bytes(Path(booth.core.__file__).read_bytes()),
            "settings": {"temperature": 0.0, "seed": args.seed, "num_predict": args.num_predict, "num_ctx": 4096, "timeout_s": args.timeout, "max_retries": 0, "confidence_threshold": 0.7, "keyword_threshold": 0.5},
            "case_order": [case["id"] for case in cases], "cases": cases,
            "non_claims": ["authored controls are not model outputs", "B replays A's first reply", "no retry repair", "bounded source grammar", "no finance or compliance suitability"],
        }
        if manifest["booth_version"] != "0.5.9" or manifest["installed_distribution"] != "0.5.9":
            raise ProviderFailure("this frozen protocol requires boothpy 0.5.9")
        if not args.controls_only:
            manifest["model"] = model_identity(args.host, args.model)
            if args.expected_digest and manifest["model"]["digest"] != args.expected_digest:
                raise ProviderFailure("installed model digest differs from required digest")
            manifest["ollama_version"] = get_json(args.host, "version")["version"]
        write_json(out / "manifest.json", manifest)
        for case in cases:
            for control, label in (("correct_answer", "correct"), ("wrong_answer", "wrong")):
                raw = json.dumps({"ambiguous": False, "interpretations": [], "chosen_interpretation": None, "answer": case[control], "confidence": 0.99})
                row = checkpoints(case, raw)
                if row["grade"]["label"] != label:
                    raise RuntimeError("authored control disagrees with reference grader: " + case["id"])
                row.update(layer="authored_controls", control=label, fixture_reply=raw, provider_calls=0)
                append_jsonl(out / "records.jsonl", row)
                records.append(row)
        if not args.controls_only:
            options = {"temperature": 0.0, "seed": args.seed, "num_predict": args.num_predict, "num_ctx": 4096}
            provider = Provider(args.host, args.model, options, args.timeout, out)
            provider.case_id = "__warmup__"
            original_options = provider.options
            provider.options = dict(options, num_predict=8)
            provider("Reply with ready.")
            warmup_calls = 1
            provider.options = original_options
            for case in cases:
                provider.case_id = case["id"]
                first = booth.check(provider, prompt_for(case), threshold=0.7, max_retries=0)
                calls += 1
                if provider.last is None or provider.last.get("error"):
                    raise ProviderFailure("provider failed for case " + case["id"])
                row = checkpoints(case, provider.last["raw_reply"], first, json.loads(provider.last["request_text"])["prompt"])
                row.update(layer="live_gemma", provider_calls=1, provider_trace_index=provider.calls - 1)
                append_jsonl(out / "records.jsonl", row)
                records.append(row)
                print(json.dumps({"case_completed": case["id"], "completed": calls, "planned": len(cases)}), flush=True)
            after = model_identity(args.host, args.model)
            write_json(out / "model_after.json", after)
            if after["digest"] != manifest["model"]["digest"]:
                raise ProviderFailure("model digest changed during the run")
        completion = {"status": "completed", "finished_utc": utc(), "elapsed_s": time.monotonic() - start_clock, "live_case_calls": calls, "warmup_calls": warmup_calls, "records": len(records)}
        summary = summarize(records)
        write_json(out / "summary.json", summary)
        (out / "summary.md").write_text(report_markdown(summary, manifest, completion), encoding="utf-8")
        write_json(out / "completion.json", completion)
        write_json(out / "checksums.json", {p.name: sha_bytes(p.read_bytes()) for p in sorted(out.iterdir()) if p.is_file()})
        print(json.dumps({"status": "completed", "output": str(out), "live_case_calls": calls, "warmup_calls": warmup_calls}), flush=True)
        return 0
    except Exception as exc:
        failure = {"status": "blocked", "failed_utc": utc(), "error": type(exc).__name__ + ": " + str(exc), "live_case_calls_attempted": calls, "warmup_calls_completed": warmup_calls, "live_records_saved": sum(row["layer"] == "live_gemma" for row in records), "partial_records": len(records)}
        write_json(out / "failure.json", failure)
        print(json.dumps(failure), file=sys.stderr, flush=True)
        return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="gemma3:12b")
    parser.add_argument("--expected-digest")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-predict", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--out")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--controls-only", action="store_true")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
