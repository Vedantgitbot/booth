# Ollama Qwen 2.5 Coder 3B: schema comparison

Run on 2026-10-30 using the published `boothpy==0.5.6` wheel, Python 3.12.3,
Linux 7.0.0-42, Ollama server 0.24.0, and `qwen2.5-coder:3b` with digest
`f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225`.
Four questions were each sent once per format, for eight calls. Both formats
used temperature 0.2, seed 42 and `max_retries=0`; the schema was the only
format-setting difference. Calls are separate generations, so this is a small
comparison, not a controlled accuracy benchmark.

The four default-format responses were malformed and returned `UNCERTAIN`,
`method=parse_failure`, `call_failed=False`. All were nonempty responses from
successful API calls; none was a timeout or API error. The example reported
`done_reason` as `None` for those responses and cannot tell why generation ended.

All four schema-format responses were parseable. BOOTH accepted the correct
Paris answer and also accepted `object` as the name of an unknown neighbor,
with confidence 1.0. It marked the arithmetic answer `1` (the correct answer
is `102`) and the Georgia response `Tbilisi` uncertain because their reported
confidence was zero. The model did not flag the possible Georgia ambiguity.
No model response was empty in this final run. The schema constrained output
shape, not factual correctness, and acceptance did not establish truth.

## Full output from the final script

````text
boothpy: 0.5.6
Python: 3.12.3
OS: Linux-7.0.0-42-generic-x86_64-with-glibc2.39
Ollama server: 0.24.0
Model: qwen2.5-coder:3b
Model digest: f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225
Temperature: 0.2; seed: 42; max_retries: 0
Questions: 4; planned calls: 8

Each question uses one fresh call per format; no retries.

Running Simple fact (default)...

[Simple fact] format=default
Question: What is the capital of France?
Status: UNCERTAIN; method: parse_failure; call_failed: False
Answer: None; confidence: None; interpretations: []
Elapsed seconds: 52.8
API error: None; done_reason: None
Empty response text: False
Attempt error: 'no candidate contained a valid JSON object'
Raw response: '```{"ambiguous": false, "interpretations": ["<reading Q>", "<< Q>", ...chosen_interpretATION": "< < Q>", "answer": "< < Q>", "confidence": <float Q> Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q'

Running Simple fact (schema)...

[Simple fact] format=schema
Question: What is the capital of France?
Status: ACCEPTED; method: confidence; call_failed: False
Answer: 'Paris'; confidence: 1.0; interpretations: []
Elapsed seconds: 9.9
API error: None; done_reason: 'stop'
Empty response text: False
Attempt error: None
Raw response: '{\n  "ambiguous": false,\n "interpretations": [],\n  "chosen_interpretation": "Paris",\n  "answer": "Paris",\n "confidence": 1\n\n}\n\n   '

Running Arithmetic (default)...

[Arithmetic] format=default
Question: What is 17 multiplied by 6?
Status: UNCERTAIN; method: parse_failure; call_failed: False
Answer: None; confidence: None; interpretations: []
Elapsed seconds: 37.1
API error: None; done_reason: None
Empty response text: False
Attempt error: 'no candidate contained a valid JSON object'
Raw response: ': {\n    ambiguous": falsefalse,\ninterpretations> Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q'

Running Arithmetic (schema)...

[Arithmetic] format=schema
Question: What is 17 multiplied by 6?
Status: UNCERTAIN; method: confidence; call_failed: False
Answer: '1'; confidence: 0.0; interpretations: []
Elapsed seconds: 16.7
API error: None; done_reason: 'stop'
Empty response text: False
Attempt error: None
Raw response: '{\n  "ambiguous": false,\n  "interpretations": [\n    "<reading Q>",\n "<reading Q>"\n],\n  "chosen_interpretation": "<reading Q>",\n  "answer": "1",\n  "confidence": 0\n\n }\n\n                    '

Running Potential ambiguity (default)...

[Potential ambiguity] format=default
Question: What is the capital of Georgia?
Status: UNCERTAIN; method: parse_failure; call_failed: False
Answer: None; confidence: None; interpretations: []
Elapsed seconds: 42.8
API error: None; done_reason: None
Empty response text: False
Attempt error: 'no candidate contained a valid JSON object'
Raw response: '```{"ambiguous": false, "interpretations": ["<reading Q>", "<"< Q>", ...], "chosen_interpretATION": "< "<objects Q chosen>", "answer": "< "<object Q Q>", Q], Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q Q'

Running Potential ambiguity (schema)...

[Potential ambiguity] format=schema
Question: What is the capital of Georgia?
Status: UNCERTAIN; method: confidence; call_failed: False
Answer: 'Tbilisi'; confidence: 0.0; interpretations: []
Elapsed seconds: 16.2
API error: None; done_reason: 'stop'
Empty response text: False
Attempt error: None
Raw response: '{\n  "ambiguous": false,\n "interpretations": ["Tbilisi"],\n  "chosen_interpretation": "Tbilisi",\n             "answer": "Tbilisi",\n  "confidence": 0\n              }\n'

Running Unanswerable (default)...

[Unanswerable] format=default
Question: What is the name of my next-door neighbor?
Status: UNCERTAIN; method: parse_failure; call_failed: False
Answer: None; confidence: None; interpretations: []
Elapsed seconds: 41.3
API error: None; done_reason: None
Empty response text: False
Attempt error: 'no candidate contained a valid JSON object'
Raw response: '\n```: What "ambiguous": falsefalse", "interpretations": ["My next door neighbor is John." " object " {"choseninterpretinterpret": "interpretinterpret":interpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpretinterpret'

Running Unanswerable (schema)...

[Unanswerable] format=schema
Question: What is the name of my next-door neighbor?
Status: ACCEPTED; method: confidence; call_failed: False
Answer: 'object'; confidence: 1.0; interpretations: []
Elapsed seconds: 10.5
API error: None; done_reason: 'stop'
Empty response text: False
Attempt error: None
Raw response: '{"ambiguous": false,"interpretations": ["My next is name is my", "Your estimate object name object"], "chosen_interpretation": null, "answer": "object", "confidence": 1}'
````

## Earlier arithmetic observation

In an earlier exploratory run using a different local script, the same model
answered `17 × 6` with `" Q, "`, reported confidence 1.0, and BOOTH returned
`ACCEPTED` with `call_failed=False`. That script used the schema, temperature
0, no explicitly set seed, and an editable BOOTH checkout reporting version
0.5.6. Its output did not record `method` or the model digest, so those details
cannot be independently confirmed for that run. It was not part of the final
eight-call comparison above. The recorded raw model output was:

```text
'{"ambiguous": false,"interpretations": ["42", "3 Q"], "chosen_interpretation": " Q", "answer": " Q, ", "confidence": 1}'
```

The result illustrates a possible failure mode, not an estimate of how often
it occurs. Running the same prompt again can yield different output.

In another exploratory schema-formatted call, the neighbor question produced
an empty `answer` field, not an empty HTTP response. BOOTH returned
`UNCERTAIN`, `call_failed=False`, and the error `'answer' was empty or
whitespace-only`. The earlier probe did not print `result.method` or API
completion metadata, so those details were not recorded. Its raw response was:

```text
'{"ambiguous": false,"interpretations": ["My next is name is my name", "My neighbor\'s name name object"], "chosen_interpretation": "My neighbor\'s name object", "answer": "", "confidence": 0}'
```
