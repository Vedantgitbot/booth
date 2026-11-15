"""Measure confidence against a fixed, self-authored arithmetic sample.

Uses a custom short prompt and Ollama's JSON schema. BOOTH evaluates the cached
model response; BOOTH's default prompt is not sent to the model. Stdlib plus
boothpy; Ollama and the model must already be installed. Results are
saved under output/; no questions or model calls require internet access.
"""
import json
import platform
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import booth

HOST = 'http://127.0.0.1:11434'
MODEL = 'qwen2.5-coder:7b'
TEMPERATURE = 0.2
SEED = 101
TIMEOUT = 90
THRESHOLDS = (0.5, 0.7, 0.9)
SCHEMA = {'type': 'object', 'properties': {
    'answer': {'type': 'string'},
    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
}, 'required': ['answer', 'confidence']}
# Fixed before the study; operands are distinct from our recorded pilots.
# Division problems have integer results. References are computed, not model-generated.
ITEMS = (
    ('add', 31, 27), ('add', 43, 29), ('add', 58, 16), ('add', 72, 19),
    ('add', 36, 48), ('add', 54, 37), ('add', 67, 25), ('add', 81, 34),
    ('subtract', 93, 47), ('subtract', 86, 38), ('subtract', 120, 54),
    ('subtract', 175, 89), ('subtract', 141, 58), ('subtract', 99, 46),
    ('subtract', 162, 75), ('subtract', 134, 68),
    ('multiply', 13, 8), ('multiply', 16, 6), ('multiply', 21, 4),
    ('multiply', 18, 5), ('multiply', 24, 3), ('multiply', 12, 7),
    ('multiply', 17, 4),
    ('divide', 96, 8), ('divide', 154, 11), ('divide', 156, 12),
    ('divide', 81, 9), ('divide', 84, 7), ('divide', 120, 10), ('divide', 110, 11),
)


def make_question(kind, left, right):
    if kind == 'add':
        return f'What is {left} plus {right}?', left + right
    if kind == 'subtract':
        return f'What is {left} minus {right}?', left - right
    if kind == 'multiply':
        return f'What is {left} multiplied by {right}?', left * right
    if kind == 'divide' and right and left % right == 0:
        return f'What is {left} divided by {right}?', left // right
    raise ValueError('Invalid arithmetic question')


def request_json(path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = Request(HOST + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read(4096).decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from exc


def score(answer, reference):
    """Grade integer strings only; do not guess what malformed text meant."""
    if not isinstance(answer, str) or not re.fullmatch(r'[+-]?[0-9]+', answer.strip()):
        return None
    return int(answer.strip()) == reference


def run_one(index, question, reference):
    prompt = (f'{question}\nReturn a JSON object with answer as an integer written '
              'as a string and confidence as your estimated probability of correctness '
              'between 0 and 1.')
    payload = {'model': MODEL, 'prompt': prompt, 'stream': False, 'format': SCHEMA,
               'options': {'temperature': TEMPERATURE, 'seed': SEED}}
    record = {'index': index, 'question': question, 'reference': reference,
              'raw': None, 'done': None, 'done_reason': None, 'eval_count': None,
              'status': None, 'method': None, 'call_failed': None, 'answer': None,
              'confidence': None, 'correct': None, 'error': None, 'exclusion': None}
    started = time.monotonic()
    try:
        response = request_json('/api/generate', payload, timeout=TIMEOUT)
        record.update(raw=response.get('response'), done=response.get('done'),
                      done_reason=response.get('done_reason'), eval_count=response.get('eval_count'))
        if record['done'] is not True:
            record['exclusion'] = 'response incomplete or completion unknown'
        elif not isinstance(record['raw'], str):
            record['exclusion'] = 'response text missing'
        else:
            # The model call has already happened. BOOTH parses and gates the cached response.
            result = booth.check(lambda _: record['raw'], question, max_retries=0)
            record.update(status=result.status, method=result.method,
                          call_failed=result.call_failed, answer=result.answer,
                          confidence=result.confidence, error=result.attempts[0].error)
            if not result.attempts[0].parse_ok:
                record['exclusion'] = 'BOOTH parse failure'
            else:
                record['correct'] = score(result.answer, reference)
                if record['correct'] is None:
                    record['exclusion'] = 'answer is not an integer string'
                elif result.confidence is None:
                    record['exclusion'] = 'confidence missing'
    except TimeoutError as exc:
        record.update(error=f'{type(exc).__name__}: {exc}', exclusion='client timeout')
    except Exception as exc:
        record.update(error=f'{type(exc).__name__}: {exc}', exclusion='request or processing error')
    record['seconds'] = round(time.monotonic() - started, 3)
    return record


def summarize(records, planned):
    eligible = [r for r in records if r['exclusion'] is None and r['correct'] is not None]
    print(f'Planned: {planned}; attempted: {len(records)}; eligible: {len(eligible)}; '
          f'excluded: {len(records) - len(eligible)}')
    print('Exclusions:', dict(Counter(r['exclusion'] for r in records if r['exclusion'])))
    print('BOOTH statuses:', dict(Counter(str(r['status']) for r in records if r['status'] is not None)))
    print('Bins: range, count, mean confidence, observed accuracy')
    ece = 0.0
    for i in range(10):
        group = [r for r in eligible if min(int(r['confidence'] * 10), 9) == i]
        if group:
            mean = sum(r['confidence'] for r in group) / len(group)
            accuracy = sum(r['correct'] for r in group) / len(group)
            ece += len(group) / len(eligible) * abs(mean - accuracy)
            print(f"  [{i/10:.1f}, {(i+1)/10:.1f}{']' if i == 9 else ')'}: "
                  f'{len(group)}, {mean:.3f}, {accuracy:.3f}')
    print(f'ECE: {ece:.3f}' if eligible else 'ECE: unavailable (no eligible answers)')
    print('Confidence thresholds: threshold, retained, coverage of attempted, retained accuracy')
    for threshold in THRESHOLDS:
        retained = [r for r in eligible if r['confidence'] >= threshold]
        coverage = len(retained) / len(records) if records else 0.0
        accuracy = (f"{sum(r['correct'] for r in retained) / len(retained):.3f}"
                    if retained else 'unavailable')
        print(f'  {threshold:.1f}: {len(retained)}, {coverage:.3f}, {accuracy}')
    print('ECE uses scoreable responses only; coverage uses all attempted calls.')
    print('Thresholds use confidence alone and do not measure BOOTH ambiguity handling.')


def main():
    version = metadata.version('boothpy')
    if version != '0.5.8':
        print(f'Warning: the documented study used boothpy 0.5.8; '
              f'this run uses {version}. Results may differ.', file=sys.stderr, flush=True)
    try:
        server = request_json('/api/version')['version']
        model = next(m for m in request_json('/api/tags')['models'] if m.get('name') == MODEL)
    except Exception as exc:
        sys.exit(f'Cannot reach Ollama or find {MODEL}: {type(exc).__name__}: {exc}')
    questions = [make_question(*item) for item in ITEMS]
    config = {'boothpy': version, 'ollama': server, 'model': MODEL,
              'model_digest': model.get('digest'), 'python': platform.python_version(),
              'os': platform.platform(), 'temperature': TEMPERATURE, 'seed': SEED,
              'timeout_seconds': TIMEOUT, 'max_retries': 0, 'questions': len(questions),
              'dataset': 'fixed self-authored integer arithmetic',
              'prompt': 'custom short JSON-schema prompt; BOOTH checks cached response'}
    output = Path(__file__).resolve().parent / 'output' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'manifest.json').write_text(json.dumps({'config': config, 'questions': questions}, indent=2), encoding='utf-8')
    print(json.dumps(config, indent=2), flush=True)
    print(f'Raw records: {output / "records.jsonl"}', flush=True)
    records = []
    started = time.monotonic()
    with (output / 'records.jsonl').open('x', encoding='utf-8') as handle:
        for index, (question, reference) in enumerate(questions, 1):
            print(f'{index}/{len(questions)}: {question}', flush=True)
            record = run_one(index, question, reference)
            records.append(record)
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            handle.flush()
            print(json.dumps(record, ensure_ascii=False), flush=True)
            if record['exclusion'] in ('client timeout', 'request or processing error',
                                       'response incomplete or completion unknown', 'response text missing'):
                print('Stopping early after a request or completion failure.', flush=True)
                break
    print(f'\nElapsed seconds: {time.monotonic() - started:.1f}; model calls: {len(records)}')
    summarize(records, len(questions))
    if len(records) != len(questions):
        sys.exit('Study incomplete; retain the partial records and investigate before rerunning.')


if __name__ == '__main__':
    main()
