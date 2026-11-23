# Changelog

All notable changes to BOOTH are documented here. Versions follow
[Semantic Versioning](https://semver.org/): additive, backward-compatible
changes bump the minor version; fixes, docs and tests bump the patch version.
Contributors are credited in the release their work shipped in.

## [Unreleased]

## [v0.6.0] — 2026-11-23 — control the prompt suffix

You can now replace the output instructions BOOTH appends to your prompt. The default prompt and default behaviour are unchanged, byte for byte.

### Added
- **`suffix=`** (keyword-only) on `check()` and `acheck()`. It replaces the whole default suffix and is used verbatim, so include your own leading newline. It must be a non-empty `str` (`TypeError` or `ValueError` otherwise), and it is checked before any model call. The same suffix is sent on the first call and on every retry: low confidence, parse failure, validation failure and a failed call.
- **`DEFAULT_SUFFIX`**: the current default prompt, now public. **`REASONING_SUFFIX`**: the same JSON schema, but the model may work the question out first as long as the JSON object comes last. Both are exported from `booth`. `_CONFIDENCE_SUFFIX` stays as an alias.
- **`Attempt.pre_json_text`**: the text before the JSON object the parser selected, stripped (`""` if the object starts the reply). `None` when the parse failed or a custom `parse_fn` was used. It also appears in `to_dict()`.

### Changed
- **The validator now runs on ambiguous attempts too.** Before, `passed_validation` was always `True` on an ambiguous attempt because the validator never ran. Now it is honest. The result is still `AMBIGUOUS`, `ok` is still `False`, and nothing is retried. **Code that relied on the validator being skipped for ambiguous attempts will now see it called.**
- **The parse-failure retry wording depends on the suffix.** With the default suffix it is the exact 0.5.x text. With any other suffix it no longer says "no commentary before or after it", which would contradict a suffix that asks for reasoning.

### Why
On GSM8K, Qwen 7B scored 97.5% plain but 35.0% under the JSON-only prompt, and recovered to 92.5% when given room to reason (`examples/Vedantgitbot_latency_accuracy/`). Gemma 3 12B did not show the same collapse (#38). `suffix=` makes the prompt a choice instead of a fixed cost.

### Tests
- New `tests/test_v060_suffix.py`: default prompts pinned byte for byte, `check()`/`acheck()` parity, custom suffix on every retry type, validator on ambiguous attempts, `pre_json_text`, and long-reply parsing.
- The two validator tests that pinned "never runs on an ambiguous attempt" were renamed and updated because the behaviour changed on purpose. 527 tests pass.

### Internal
- `_iter_top_level_objects_with_pos` added; `_iter_top_level_objects` kept as a wrapper. The prompt builders take an optional `suffix` argument.

### Docs
- TUTORIAL: suffix, templates and the ambiguous-attempt behaviour.

### Credits
@camerontjs-dot (Gemma 3 12B replication #38, numeric comparison #39, format limits #40), @gal-a (edge-case tests #42, #43, #45, and the [qikly](https://github.com/gal-a/qikly) mutation-testing runs that found the gaps), @rk042 (calibration example #37, scope feedback in Discussion #34).

## [v0.5.9] — 2026-11-13 — parser: last valid top-level JSON object wins

- The last valid top-level JSON object is used, not the first. Nested objects are never candidates. Parse errors describe the last object.
- Internal: `_iter_raw_decoded_objects` is now `_iter_top_level_objects`; `_JSON_RE` and `_try_json` removed.
- Docs: TUTORIAL §3.8 (parser rules), TROUBLESHOOTING entry 10, README Featured section.
- Example: `examples/Vedantgitbot_latency_accuracy/` (plain vs BOOTH, with a reasoning-room arm).
- Credits: @rk042 (parser regression tests, #35).

## [v0.5.8] — 2026-11-01 — malformed model output no longer crashes

- Malformed numbers, oversized integers and JSON nested deeper than 1024 levels now give an ordinary parse-failure attempt instead of raising. Fixes #30.
- Examples: Ollama Qwen 3B (#27) and independent sample agreement (#29).
- Credits: @Kaan081 (fix, #31), @rk042 (examples).

## [v0.5.7] — 2026-10-29 — `parse_fn`

- `parse_fn=` on `check()`/`acheck()`: a synchronous hook for provider-specific structured output. Its result goes through the normal validation, retry and `BoothResult` pipeline. Fixes #6.
- CI: mypy job against the Python 3.9 target (`typecheck` extra).
- Credits: @rk042 (#25, #26).

## [v0.5.6] — 2026-10-20 — type hint and docs

- `evidence` is now typed `Iterable[str]` (generators were already accepted). No runtime change.
- README links made absolute for PyPI; leftover dev comments removed.

## [v0.5.5] — 2026-10-20 — evidence iterators, validator check, CI

- `check_with_evidence()` converts one-shot iterators to a list once, so empty generators hit `NO_EVIDENCE` and `compare_fn` can't exhaust the input.
- A non-callable `validator` now raises `TypeError` upfront, before any model call. Before, it burned every retry and returned `UNCERTAIN`.
- CI matrix covers Python 3.9–3.15.
- Examples: `compare_fn` NLI comparison (#23), LangChain + FLAN-T5 (#22). TROUBLESHOOTING (#14).
- Credits: @camerontjs-dot (#23), @Harithalakshmikt (#22), @AkashGoswamy (TROUBLESHOOTING, #14).

## [v0.5.4] — 2026-10-08 — `call_failed`

- `Attempt.call_failed` and `BoothResult.call_failed` tell a failed `call_fn` (bad key, network, quota) apart from a model that answered badly. `status` and `method` are unchanged. Reported in #9.
- After a failed call, the retry re-sends the original prompt instead of "could not be parsed".
- `py.typed` marker (PEP 561). Credit: @AK-Lmn (#16).

## [v0.5.3] — 2026-10-05

- `on_attempt` is validated as callable upfront. SPDX license metadata; setuptools >= 77.
- Examples and docs: README overhaul (#7, @sohanpal17), Gemini (#8, @AkashGoswamy), Ollama (#10, @Maintythehuman; #13, @sohanpal17), Anthropic (#11, @opencode13241-eng).

## [v0.5.2] — 2026-09-27

- `check_with_evidence()`: whitespace-only answers give `answer=None`; a boolean `compare_fn` rejection gets an accurate `detail`.
- `check()`/`acheck()` raise a clear `TypeError` for a non-`str` prompt or non-callable `call_fn`.

## [v0.5.1] — 2026-09-25

- `BoothResult.reason`, `.detail` and `.checker_failed` on `check_with_evidence()` results, with five reason codes (`EMPTY_ANSWER`, `NO_EVIDENCE`, `COMPARE_FAILED`, `INVALID_SCORE`, `EVIDENCE_DISAGREES`).

## [v0.5.0] — 2026-09-22

- `BoothResult.unwrap()`, `unwrap_or()` and `BoothRejected`. Development Status moves to Beta.
- Added the `examples/` directory (Groq example first), plus CODE_OF_CONDUCT, CONTRIBUTING, SECURITY and issue/PR templates.

## [v0.4.9] — 2026-09-18

- Empty answers are rejected (except when ambiguous). A valid JSON object inside prose is recovered even when its answer contains braces. Numeric and boolean answers are coerced to strings.
- `check_with_evidence()` handles a non-str answer, numpy evidence and an async `compare_fn` cleanly. `evidence_threshold` is type-checked. Every parse failure records `Attempt.error`.

## [v0.4.8] — 2026-09-13 — BREAKING

- **`VERIFIED` renamed to `ACCEPTED`**, with no alias. The status string changed too.
- `check()` rejects an async `call_fn`; a non-string `call_fn` return becomes a failed attempt; non-int `max_retries` raises; a dict/list `answer` is rejected instead of stringified.

## [v0.4.7] — 2026-09-10

- Async `on_attempt` detection fixed (objects with `async def __call__`). Added `BoothResult.to_dict()`.

## [v0.4.6] — 2026-09-07

- `acheck()` accepts objects with `async def __call__`. An async `validator` no longer leaks a "never awaited" warning.

## [v0.4.5] — 2026-09-05

- `numpy.bool_` recognised in `check_with_evidence()` and across numpy 1.x/2.x. Whitespace-only answers no longer reach `compare_fn`.

## [v0.4.4] — 2026-09-01

- A boolean `confidence` is rejected (it used to become 1.0). `ambiguous: "false"` is no longer read as true. `ValidatorFn` exported. Falsy `chosen_interpretation` values kept. Validators may return `(True, None)` or a list.

## [v0.4.3] — 2026-08-29

- `Attempt.parsed` and `BoothResult.parsed`: the model's JSON exactly as parsed, before coercion.

## [v0.4.2] — 2026-08-26

- `validator=` on `check()`/`acheck()`, with its own retry prompt and `method == "validation"`. `Attempt.passed_validation` and `validation_error`. GitHub Actions CI added.

## [v0.4.1] — 2026-08-24

- `BoothResult.method` (`"ambiguity"`, `"evidence"`, `"parse_failure"`, `"confidence"`).

## [v0.4.0] — 2026-08-23

- `check_with_evidence()` and the `BLOCKED` status: checks an answer against caller-supplied evidence with a caller-supplied `compare_fn`. No LLM or network calls.

## [v0.3.1] — 2026-08-23

- Distinct retry prompt for unparseable replies; `BoothResult.all_parse_failed`.

## [v0.3.0] — 2026-08-23

- `acheck()`, the async twin of `check()`, sharing one decision step.

## [v0.2.0] — 2026-08-22

- Ambiguity detection and the `AMBIGUOUS` status (never retried). PyPI package renamed `boothpy`. Added TUTORIAL.md.

## [v0.1.0] — 2026-08-22

- Initial release: `check()` with self-reported confidence and a reconsideration retry.

[Unreleased]: https://github.com/Vedantgitbot/booth/compare/v0.6.0...HEAD
[v0.6.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.6.0
[v0.5.9]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.9
[v0.5.8]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.8
[v0.5.7]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.7
[v0.5.6]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.6
[v0.5.5]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.5
[v0.5.4]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.4
[v0.5.3]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.3
[v0.5.2]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.2
[v0.5.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.1
[v0.5.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.5.0
[v0.4.9]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.9
[v0.4.8]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.8
[v0.4.7]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.7
[v0.4.6]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.6
[v0.4.5]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.5
[v0.4.4]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.4
[v0.4.3]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.3
[v0.4.2]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.2
[v0.4.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.1
[v0.4.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.0
[v0.3.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.1
[v0.3.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.0