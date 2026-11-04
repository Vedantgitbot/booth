"""BOOTH latency / accuracy example (stdlib only, Ollama provider).

Four arms, run on the same questions:

  plain         the model, asked directly, free to reason, "Final answer:" extraction
  json_nogate   BOOTH's exact prompt (question + its JSON suffix), NO checking
  booth_def     booth.check() with default settings
  booth_reason  booth.check(), but the model may reason before the JSON

Reading the results:
  json_nogate low, plain high      -> the prompt hurts, not the gate
  booth_reason recovers accuracy   -> BOOTH's suffix leaves no room to reason
  json_nogate ~ plain              -> the gate (AMBIGUOUS rejections) is the cost

Defaults: 100 questions, 1 repetition (temperature 0 + fixed seed makes
repetitions identical, so extra reps add nothing).
"""
import argparse
import json
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Use the installed booth package if there is one; otherwise fall back to this
# repository's src/ directory (examples/<name>/ -> repo root -> src).
try:
    import booth
except ImportError:
    sys.path.insert(0, str(HERE.parents[1] / "src"))
    import booth
from booth import core

ARMS = ["plain", "json_nogate", "booth_def", "booth_reason"]
ARM_LABELS = {
    "plain": "Plain model",
    "json_nogate": "BOOTH prompt, no gate",
    "booth_def": "BOOTH (default)",
    "booth_reason": "BOOTH + reasoning room",
}

HF_BASE = os.environ.get("HF_DATASETS_SERVER", "https://datasets-server.huggingface.co")

# (name, share of questions, dataset id, config, split, licence)
DATASETS = [
    ("triviaqa", 0.3, "mandarjoshi/trivia_qa", "rc.nocontext", "validation", "Apache-2.0"),
    ("truthfulqa", 0.3, "EleutherAI/truthful_qa_mc", "multiple_choice", "validation", "Apache-2.0"),
    ("gsm8k", 0.4, "openai/gsm8k", "main", "test", "MIT"),
]
# Used only if the primary TruthfulQA-MC source cannot be read.
TRUTHFULQA_FALLBACK = ("truthfulqa/truthful_qa", "multiple_choice", "validation")

# --------------------------------------------------------------------------
# Reasoning-friendly suffix, derived from BOOTH's own suffix at import time so
# the schema stays identical. Only the "JSON only" instruction is replaced.
# --------------------------------------------------------------------------
_JSON_ONLY = "Output ONLY the JSON object, nothing else."
_REASON_INSTR = ("First think the problem through step by step in plain text. Then, as the LAST "
                 "thing in your reply, output the JSON object described above.")
if _JSON_ONLY not in core._CONFIDENCE_SUFFIX:
    sys.exit("core._CONFIDENCE_SUFFIX changed; update _JSON_ONLY in this script.")
REASON_SUFFIX = core._CONFIDENCE_SUFFIX.replace(_JSON_ONLY, _REASON_INSTR)


def extract_json_object(text):
    """Outermost {...} span, tolerating code fences and leading prose."""
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i != -1 and j > i else text


class ReasonFirst:
    """call_fn wrapper for the booth_reason arm: swap BOOTH's suffix for the
    reasoning-friendly one, then hand BOOTH only the final JSON object."""

    def __init__(self, prov):
        self.prov = prov

    def __call__(self, prompt):
        if core._CONFIDENCE_SUFFIX not in prompt:
            raise RuntimeError("BOOTH suffix not found in prompt; suffix swap did not apply")
        text = self.prov(prompt.replace(core._CONFIDENCE_SUFFIX, REASON_SUFFIX))
        i = text.rfind("{")  # schema has no nested objects: last '{' starts the answer JSON
        return text[i:] if i != -1 else text


# --------------------------------------------------------------------------
# Provider: the ONLY place that talks to a model. Swap this to change provider.
# --------------------------------------------------------------------------
class Provider:
    """Ollama over plain HTTP (stdlib). Counts every call it makes."""

    def __init__(self, host, model, temperature, seed, num_predict, timeout):
        self.host = host.rstrip("/")
        self.model = model
        self.options = {"temperature": temperature, "seed": seed, "num_predict": num_predict}
        self.timeout = timeout
        self.reset()

    def reset(self):
        self.calls = 0
        self.failed_calls = 0
        self.out_tokens = 0

    def _post(self, path, payload, timeout):
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def get(self, path, timeout=10):
        with urllib.request.urlopen(self.host + path, timeout=timeout) as r:
            return json.loads(r.read())

    def __call__(self, prompt):
        """call_model(prompt) -> str. Raises on failure (BOOTH records it)."""
        self.calls += 1
        try:
            data = self._post(
                "/api/chat",
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "keep_alive": "60m",
                    "options": self.options,
                },
                self.timeout,
            )
            self.out_tokens += int(data.get("eval_count") or 0)
            return data["message"]["content"]
        except Exception:
            self.failed_calls += 1
            raise


# --------------------------------------------------------------------------
# Datasets (Hugging Face datasets-server, stdlib only) + fixed-seed sampling
# --------------------------------------------------------------------------
def http_json(url, retries=6):
    headers = {"User-Agent": "booth-latency-accuracy-example"}
    if os.environ.get("HF_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def hf_rows(dataset, config, split, offset, length, cache_dir):
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{dataset}__{config}__{split}__{offset}__{length}")
    path = cache_dir / (key + ".json")
    if path.exists():
        return json.loads(path.read_text())
    q = urllib.parse.urlencode(
        {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": length}
    )
    data = http_json(f"{HF_BASE}/rows?{q}")
    path.write_text(json.dumps(data))
    return data


def letters(n):
    return [chr(ord("A") + i) for i in range(n)]


def fmt_choices(choices):
    return "\n".join(f"{l}. {c}" for l, c in zip(letters(len(choices)), choices))


def build_question(name, ds_id, config, split, idx, row, seed):
    """Turn a raw dataset row into a question record (prompt pieces + reference)."""
    if name == "triviaqa":
        ans = row["answer"]
        return {
            "id": row["question_id"],
            "dataset": name, "kind": "trivia", "row_idx": idx,
            "question": row["question"],
            "reference": ans["value"],
            "aliases": sorted(set(ans.get("aliases", []) + ans.get("normalized_aliases", []) + [ans["value"]])),
            "base": "Answer the following trivia question with a short answer "
                    "(a name, place, date, or short phrase).\n\nQuestion: " + row["question"],
            "plain_suffix": "\n\nRespond with only the answer, in the form:\nFinal answer: <answer>",
        }
    if name == "truthfulqa":
        if "mc1_targets" in row:  # fallback source: correct choice listed first -> shuffle deterministically
            choices = list(row["mc1_targets"]["choices"])
            correct = choices[row["mc1_targets"]["labels"].index(1)]
            random.Random(f"{seed}:tqa-shuffle:{idx}").shuffle(choices)
            label = choices.index(correct)
        else:
            choices, label = list(row["choices"]), int(row["label"])
        return {
            "id": f"truthfulqa_mc-{split}-{idx}",
            "dataset": name, "kind": "mc", "row_idx": idx,
            "question": row["question"], "choices": choices,
            "reference": letters(len(choices))[label],
            "base": "Choose the single best answer to the question. Your answer must be "
                    "the letter of one choice.\n\nQuestion: " + row["question"] + "\n" + fmt_choices(choices),
            "plain_suffix": "\n\nRespond with only the letter, in the form:\nFinal answer: <letter>",
        }
    # gsm8k
    return {
        "id": f"gsm8k-{split}-{idx}",
        "dataset": name, "kind": "math", "row_idx": idx,
        "question": row["question"],
        "reference": row["answer"].split("####")[-1].strip().replace(",", ""),
        "base": "Solve this math word problem. Reason step by step, then give the final "
                "numeric answer.\n\nProblem: " + row["question"],
        "plain_suffix": "\n\nEnd your response with a line of the form:\nFinal answer: <number>",
    }


def sample_questions(n, seed, cache_dir):
    shares = [round(n * s) for _, s, *_ in DATASETS]
    shares[-1] = n - sum(shares[:-1])
    questions, sources = [], []
    for (name, _, ds_id, config, split, licence), k in zip(DATASETS, shares):
        used = (ds_id, config, split)
        try:
            total = hf_rows(*used, 0, 1, cache_dir)["num_rows_total"]
        except Exception as e:
            if name != "truthfulqa":
                raise
            print(f"[warn] {ds_id} unavailable ({e}); falling back to {TRUTHFULQA_FALLBACK[0]}", file=sys.stderr)
            used = TRUTHFULQA_FALLBACK
            total = hf_rows(*used, 0, 1, cache_dir)["num_rows_total"]
        idxs = random.Random(f"{seed}:{name}").sample(range(total), k)
        for idx in idxs:
            row = hf_rows(*used, idx, 1, cache_dir)["rows"][0]["row"]
            questions.append(build_question(name, used[0], used[1], used[2], idx, row, seed))
        sources.append({"name": name, "dataset": used[0], "config": used[1], "split": used[2],
                        "licence": licence, "split_size": total, "sampled": k})
        print(f"[data] {name}: {k} of {total} from {used[0]}", file=sys.stderr)
    return questions, sources


# --------------------------------------------------------------------------
# Deterministic grading
# --------------------------------------------------------------------------
def norm_text(s):
    """SQuAD/TriviaQA-style: lowercase, strip punctuation + articles, squeeze spaces."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def extract_final(text):
    """Plain arm: take what follows the last 'Final answer:'; else the whole text."""
    m = re.findall(r"(?is)final answer\s*[:\-]\s*(.+?)(?:\n\s*\n|$)", text)
    return m[-1].strip() if m else text.strip()


NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:/\d+)?")


def last_number(s):
    nums = NUM_RE.findall(s.replace("$", ""))
    if not nums:
        return None
    try:
        return Fraction(nums[-1].replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def grade(q, answer):
    """Return True/False for a predicted answer string."""
    if answer is None or not str(answer).strip():
        return False
    answer = str(answer)
    if q["kind"] == "trivia":
        pred = norm_text(answer)
        if not pred:
            return False
        for alias in {norm_text(a) for a in q["aliases"]}:
            if not alias:
                continue
            if pred == alias:
                return True
            # whole-phrase containment, only for aliases of >= 3 chars
            if len(alias) >= 3 and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", pred):
                return True
        return False
    if q["kind"] == "mc":
        m = re.match(r"^\W*\(?([A-Za-z])\)?(?:[\s.:)\-]|$)", answer.strip())
        return bool(m) and m.group(1).upper() == q["reference"]
    if q["kind"] == "math":
        got = last_number(answer)
        return got is not None and abs(got - Fraction(q["reference"])) <= Fraction(1, 10 ** 6)
    raise ValueError(q["kind"])


# --------------------------------------------------------------------------
# Running one question through one arm
# --------------------------------------------------------------------------
def run_arm(arm, q, provider):
    provider.reset()
    t0 = time.perf_counter()
    rec = {"status": None, "confidence": None, "predicted": None, "raw_correct": None,
           "n_attempts": None, "error": None}
    if arm == "plain":
        try:
            text = provider(q["base"] + q["plain_suffix"])
            pred = extract_final(text)
            rec.update(predicted=pred, raw_correct=grade(q, pred), status="ANSWERED")
            rec["outcome"] = "correct" if rec["raw_correct"] else ("incorrect" if pred else "no_answer")
        except Exception as e:
            rec.update(status="CALL_FAILED", error=f"{type(e).__name__}: {e}"[:200], outcome="call_failed")
    elif arm == "json_nogate":
        # BOOTH's exact prompt, one call, no confidence gate, no retries.
        try:
            text = provider(q["base"] + core._CONFIDENCE_SUFFIX)
        except Exception as e:
            rec.update(status="CALL_FAILED", error=f"{type(e).__name__}: {e}"[:200], outcome="call_failed")
        else:
            try:
                obj = json.loads(extract_json_object(text))
                pred = str(obj["answer"])
                rec.update(predicted=pred, raw_correct=grade(q, pred), status="ANSWERED",
                           confidence=obj.get("confidence"))
                rec["outcome"] = "correct" if rec["raw_correct"] else "incorrect"
            except Exception as e:
                rec.update(status="PARSE_FAILED", error=f"{type(e).__name__}: {e}"[:200],
                           raw_correct=False, outcome="no_answer")
    else:  # booth_def / booth_reason
        fn = ReasonFirst(provider) if arm == "booth_reason" else provider
        res = booth.check(fn, q["base"], max_retries=booth.DEFAULT_MAX_RETRIES)
        rec.update(status=res.status, confidence=res.confidence, predicted=res.answer,
                   n_attempts=res.n_attempts,
                   raw_correct=grade(q, res.answer) if res.answer is not None else False)
        if res.call_failed:
            rec["outcome"] = "call_failed"
            rec["error"] = (res.attempts[-1].raw_text or "")[:200]
        elif res.status == booth.AMBIGUOUS:
            rec["outcome"] = "ambiguous"
        elif res.status == booth.UNCERTAIN:
            rec["outcome"] = "uncertain"
        else:  # ACCEPTED / REPAIRED
            rec["outcome"] = "correct" if rec["raw_correct"] else "incorrect"
    rec["latency_s"] = time.perf_counter() - t0
    rec["model_calls"] = provider.calls
    rec["failed_calls"] = provider.failed_calls
    rec["out_tokens"] = provider.out_tokens
    return rec


# --------------------------------------------------------------------------
# Environment description
# --------------------------------------------------------------------------
def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def hardware():
    cpu = ram = ""
    if sys.platform.startswith("linux"):
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                ram = f"{int(line.split()[1]) / 1024 / 1024:.1f} GiB"
                break
    elif sys.platform == "darwin":
        cpu = sh(["sysctl", "-n", "machdep.cpu.brand_string"])
        mem = sh(["sysctl", "-n", "hw.memsize"])
        ram = f"{int(mem) / 1024 ** 3:.1f} GiB" if mem.isdigit() else ""
    elif sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong)] + [(f"x{i}", ctypes.c_ulonglong) for i in range(7)]
        ms = MS(); ms.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        ram = f"{ms.x0 / 1024 ** 3:.1f} GiB"
        cpu = platform.processor()
    gpu = sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]) if shutil.which("nvidia-smi") else ""
    if not gpu and sys.platform == "darwin" and platform.machine() == "arm64":
        gpu = "Apple Silicon integrated GPU (unified memory)"
    return {"cpu": cpu or platform.processor() or "unknown", "threads": os.cpu_count(),
            "ram": ram or "unknown", "gpu": gpu.replace("\n", "; ") or "none detected"}


def booth_version():
    for dist in ("boothpy", "booth"):
        try:
            from importlib.metadata import version
            return f"{dist} {version(dist)}"
        except Exception:
            pass
    return f"{getattr(booth, '__version__', 'unknown')} (loaded from {Path(booth.__file__).parent})"


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def pct(x):
    return f"{100 * x:.1f}"


def arm_stats(recs, n_per_rep):
    n = len(recs)
    c = lambda o: sum(r["outcome"] == o for r in recs)
    lat = [r["latency_s"] for r in recs]
    answered = c("correct") + c("incorrect") + c("no_answer")
    return {
        "n": n,
        "correct": c("correct"), "incorrect": c("incorrect"), "no_answer": c("no_answer"),
        "ambiguous": c("ambiguous"), "uncertain": c("uncertain"), "call_failed": c("call_failed"),
        "accuracy": c("correct") / n if n else 0,
        "selective_acc": c("correct") / answered if answered else float("nan"),
        "raw_acc": sum(bool(r["raw_correct"]) for r in recs) / n if n else 0,
        "mean_lat": statistics.mean(lat) if lat else 0,
        "median_lat": statistics.median(lat) if lat else 0,
        "runtime": sum(lat),
        "calls": sum(r["model_calls"] for r in recs),
        "failed_calls": sum(r["failed_calls"] for r in recs),
        "tokens": sum(r["out_tokens"] for r in recs),
    }


def table_header(first, arms):
    return "| " + first + " | " + " | ".join(ARM_LABELS[a] for a in arms) + " |\n|---|" + "---|" * len(arms)


def build_summary(cfg, questions, sources, records):
    reps = sorted({r["rep"] for r in records})
    by_arm = {a: [r for r in records if r["arm"] == a] for a in ARMS}
    S = {a: arm_stats(by_arm[a], len(questions)) for a in ARMS}
    out = []
    w = out.append
    w("## Experiment configuration\n")
    if cfg["smoke"]:
        w("> **SMOKE RUN: pipeline check only. Do not report these numbers.**\n")
    w("| Configuration | Value |\n|---|---|")
    for k, v in cfg["table"]:
        w(f"| {k} | {v} |")
    w("\n## Arms\n")
    w("- **Plain model**: question + \"Final answer:\" instruction; the model may reason freely.")
    w("- **BOOTH prompt, no gate**: the question + BOOTH's exact JSON suffix, one call, no confidence "
      "check and no retries. Isolates the effect of the prompt from the effect of the gate.")
    w("- **BOOTH (default)**: `booth.check()` with default settings.")
    w("- **BOOTH + reasoning room**: `booth.check()` with BOOTH's suffix swapped (via `call_fn`) for one "
      "that lets the model reason before the JSON; same schema.")
    w("\n## Benchmark comparison\n")
    w(f"Pooled over {len(reps)} repetition(s) x {len(questions)} questions = {len(questions) * len(reps)} "
      "graded question-runs per arm. Accuracy denominator is ALL question-runs: rejected "
      "(AMBIGUOUS/UNCERTAIN), call-failed and unanswerable runs count as not correct.\n")
    hdr = table_header("Metric", ARMS)
    w(hdr)
    rows = [
        ("Accuracy (%)", lambda s: pct(s["accuracy"])),
        ("Mean latency (s)", lambda s: f"{s['mean_lat']:.2f}"),
        ("Median latency (s)", lambda s: f"{s['median_lat']:.2f}"),
        ("Total runtime (s, all reps)", lambda s: f"{s['runtime']:.1f}"),
        ("Model calls (all reps)", lambda s: str(s["calls"])),
        ("Rejected (AMBIGUOUS + UNCERTAIN)", lambda s: str(s["ambiguous"] + s["uncertain"])),
        ("AMBIGUOUS", lambda s: str(s["ambiguous"])),
        ("UNCERTAIN", lambda s: str(s["uncertain"])),
        ("Call failures (failed HTTP calls)", lambda s: str(s["failed_calls"])),
        ("Questions with no response (all calls failed)", lambda s: str(s["call_failed"])),
        ("Correct / Incorrect / No-answer", lambda s: f"{s['correct']} / {s['incorrect']} / {s['no_answer']}"),
    ]
    for name, f in rows:
        w(f"| {name} | " + " | ".join(f(S[a]) for a in ARMS) + " |")
    w("\nDerived (not part of the required table):\n")
    w(hdr)
    p = S["plain"]
    extra = [
        ("Model calls per question", lambda s: f"{s['calls'] / s['n']:.2f}"),
        ("Mean latency vs plain (x)", lambda s: f"{s['mean_lat'] / p['mean_lat']:.2f}" if p["mean_lat"] else "n/a"),
        ("Output tokens (all reps)", lambda s: str(s["tokens"])),
        ("Accuracy among answered, non-rejected (%)", lambda s: pct(s["selective_acc"]) if s["selective_acc"] == s["selective_acc"] else "n/a"),
        ("Accuracy if rejected answers were still graded (%)", lambda s: pct(s["raw_acc"])),
    ]
    for name, f in extra:
        w(f"| {name} | " + " | ".join(f(S[a]) for a in ARMS) + " |")

    w("\n## Per-repetition results\n")
    w("| Rep | Arm | Accuracy (%) | Mean lat (s) | Median lat (s) | Runtime (s) | Calls | AMBIGUOUS | UNCERTAIN | Call failures |\n|---|---|---|---|---|---|---|---|---|---|")
    for rep in reps:
        for a in ARMS:
            s = arm_stats([r for r in by_arm[a] if r["rep"] == rep], len(questions))
            w(f"| {rep} | {ARM_LABELS[a]} | {pct(s['accuracy'])} | {s['mean_lat']:.2f} | {s['median_lat']:.2f} | "
              f"{s['runtime']:.1f} | {s['calls']} | {s['ambiguous']} | {s['uncertain']} | {s['failed_calls']} |")
    if len(reps) > 1:
        w("\nAccuracy range across repetitions (min-max, %):\n")
        for a in ARMS:
            accs = [arm_stats([r for r in by_arm[a] if r["rep"] == rep], len(questions))["accuracy"] for rep in reps]
            w(f"- {ARM_LABELS[a]}: {pct(min(accs))}-{pct(max(accs))}")

    w("\n## Accuracy by dataset (%, pooled over reps)\n")
    w(table_header("Dataset | Questions", ARMS))
    for src in sources:
        cells = []
        for a in ARMS:
            rs = [r for r in by_arm[a] if r["dataset"] == src["name"]]
            cells.append(pct(arm_stats(rs, 0)["accuracy"]) if rs else "n/a")
        w(f"| {src['name']} | {src['sampled']} | " + " | ".join(cells) + " |")

    w("\n## Mean output tokens per question, by dataset\n")
    w(table_header("Dataset", ARMS))
    for src in sources:
        cells = []
        for a in ARMS:
            rs = [r for r in by_arm[a] if r["dataset"] == src["name"]]
            cells.append(f"{statistics.mean(r['out_tokens'] for r in rs):.0f}" if rs else "n/a")
        w(f"| {src['name']} | " + " | ".join(cells) + " |")

    w("\n## Datasets\n")
    w("| Name | Dataset ID | Config / split | Split size | Sampled | Licence |\n|---|---|---|---|---|---|")
    for s in sources:
        w(f"| {s['name']} | `{s['dataset']}` | {s['config']} / {s['split']} | {s['split_size']} | {s['sampled']} | {s['licence']} |")
    w(f"\nSampling: `random.Random(f\"{{seed}}:{{dataset}}\").sample(...)` with seed {cfg['seed']}. "
      "Question IDs and reference answers are in `output/manifest.json`.\n")
    w("<details><summary>Sampled question IDs</summary>\n")
    for s in sources:
        ids = ", ".join(q["id"] for q in questions if q["dataset"] == s["name"])
        w(f"**{s['name']}**: {ids}\n")
    w("</details>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, choices=[50, 100, 200], default=100, help="number of questions")
    ap.add_argument("--reps", type=int, default=1,
                    help="repetitions (default 1: temperature 0 + fixed seed makes repeats identical)")
    ap.add_argument("--seed", type=int, default=42, help="sampling / order / model seed")
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--num-predict", type=int, default=1024, help="max output tokens per call")
    ap.add_argument("--timeout", type=float, default=300, help="per-call timeout (s)")
    ap.add_argument("--out", default=str(HERE / "output"))
    ap.add_argument("--resume", action="store_true", help="continue an interrupted run")
    ap.add_argument("--smoke", action="store_true", help="10 questions, 1 rep; pipeline check only")
    args = ap.parse_args()
    if not args.host.startswith("http"):
        args.host = "http://" + args.host
    if args.smoke:
        args.n, args.reps = 10, 1  # bypasses the 50/100/200 choice on purpose

    out = Path(args.out)
    cache = HERE / ".cache" / "hf"
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    # ---- setup (not counted as benchmark time) -------------------------
    t_setup = time.perf_counter()
    prov = Provider(args.host, args.model, args.temperature, args.seed, args.num_predict, args.timeout)
    try:
        ollama_version = prov.get("/api/version").get("version", "unknown")
        tags = prov.get("/api/tags")["models"]
    except Exception as e:
        sys.exit(f"Cannot reach Ollama at {args.host} ({e}). Start it with `ollama serve`.")
    entry = next((m for m in tags if m["name"] == args.model or m.get("model") == args.model), None)
    if not entry:
        sys.exit(f"Model {args.model!r} not found locally. Run: ollama pull {args.model}")
    digest = entry.get("digest", "unknown")

    questions, sources = sample_questions(args.n, args.seed, cache)
    (out / "manifest.json").write_text(json.dumps(
        {"seed": args.seed, "n": args.n, "sources": sources, "questions": questions}, indent=2))

    t_warm = time.perf_counter()
    try:
        prov("Reply with the single word: ready")
    except Exception as e:
        sys.exit(f"Warm-up call failed: {e}")
    warmup_s = time.perf_counter() - t_warm
    setup_s = time.perf_counter() - t_setup
    try:
        ps = prov.get("/api/ps").get("models", [])
        mine = next((m for m in ps if m.get("name") == args.model), None)
        placement = (f"{100 * mine['size_vram'] / mine['size']:.0f}% GPU / "
                     f"{100 - 100 * mine['size_vram'] / mine['size']:.0f}% CPU" if mine and mine.get("size") else "unknown")
    except Exception:
        placement = "unknown"

    hw = hardware()
    cfg = {
        "smoke": args.smoke, "seed": args.seed,
        "table": [
            ("BOOTH version", f"{booth_version()} (default max_retries={booth.DEFAULT_MAX_RETRIES}, threshold={booth.DEFAULT_THRESHOLD})"),
            ("Python / OS", f"{platform.python_version()} / {platform.platform()}"),
            ("Provider / Model", f"Ollama {ollama_version} / `{args.model}`"),
            ("Model digest", f"`{digest}`"),
            ("Temperature / Seed", f"{args.temperature} / {args.seed} (num_predict={args.num_predict}, timeout={args.timeout:g}s per call)"),
            ("Dataset versions", "Hugging Face datasets-server, current `main` at run time (" + time.strftime("%Y-%m-%d") + "); see Datasets below"),
            ("Questions / Repetitions", f"{args.n} / {args.reps}"),
            ("Hardware", f"CPU: {hw['cpu']} ({hw['threads']} threads); RAM: {hw['ram']}; GPU: {hw['gpu']}; Ollama placement: {placement}"),
            ("Setup / warm-up (excluded from results)", f"setup {setup_s:.1f}s incl. dataset fetch + model load; warm-up call {warmup_s:.1f}s"),
        ],
    }

    # ---- benchmark ------------------------------------------------------
    results_path = out / "results.jsonl"
    records = []
    if args.resume and results_path.exists():
        records = [json.loads(l) for l in results_path.read_text().splitlines() if l.strip()]
        print(f"[resume] {len(records)} records loaded", file=sys.stderr)
    elif results_path.exists():
        results_path.unlink()
    done = {}
    for r in records:
        done.setdefault((r["rep"], r["qid"]), set()).add(r["arm"])

    t_bench = time.perf_counter()
    with results_path.open("a") as fh:
        for rep in range(1, args.reps + 1):
            rng = random.Random(f"{args.seed}:order:{rep}")
            order = questions[:]
            rng.shuffle(order)  # question order differs per repetition
            for i, q in enumerate(order, 1):
                arms = ARMS[:]
                rng.shuffle(arms)  # arm order randomized per question (cancels cache/thermal drift)
                if done.get((rep, q["id"]), set()) >= set(ARMS):
                    continue
                for pos, arm in enumerate(arms):
                    rec = run_arm(arm, q, prov)
                    rec.update(rep=rep, qid=q["id"], dataset=q["dataset"], arm=arm, position=pos,
                               reference=q["reference"])
                    records.append(rec)
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                print(f"[rep {rep}/{args.reps}] {i}/{len(order)} {q['id']}", file=sys.stderr)
    bench_s = time.perf_counter() - t_bench

    cfg["table"].append(("Benchmark wall-clock this session", f"{bench_s:.0f}s (all arms and reps, includes interleaving; excludes setup)"))
    summary = build_summary(cfg, questions, sources, records)
    (out / "summary.md").write_text(summary)
    print("\n" + summary)
    print(f"Wrote {out/'summary.md'}, {out/'results.jsonl'}, {out/'manifest.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()