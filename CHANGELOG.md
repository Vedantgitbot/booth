# Changelog

All notable changes to BOOTH are documented here. Versions follow
[Semantic Versioning](https://semver.org/): additive, backward-compatible
changes bump the minor version; small fixes/polish with no new public
surface bump the patch version.

## [Unreleased]

Nothing yet.

## [v0.4.3] — Attempt.parsed / result.parsed

- Added `parsed: Optional[dict]` to `Attempt` and `BoothResult`: the
  model's raw JSON object exactly as parsed, before any of BOOTH's own
  coercion (`str(answer)`, `float(confidence)`, forcing
  `interpretations` into a list of strings, etc.). A transparency layer,
  not a second validation layer — every accept/retry decision was
  already made from the coerced fields by the time `parsed` is
  populated.
- `parsed` can legitimately disagree in representation with BOOTH's own
  coerced fields — e.g. `parsed["confidence"]` may be the string
  `"0.95"` while `.confidence` is the float `0.95`. That divergence is
  the intended contract, not a bug. Any extra field a caller asks the
  model to include alongside BOOTH's own schema survives untouched in
  `parsed`, even though BOOTH itself never reads it.
- `Attempt.parsed` is `None` only when that attempt failed to parse.
  `BoothResult.parsed` mirrors the winning attempt for
  `VERIFIED`/`REPAIRED`/`AMBIGUOUS`, the last successfully-parsed
  attempt for `UNCERTAIN` (even if a later attempt then failed to
  parse), and `None` only if every attempt failed to parse.
- `check_with_evidence()` results always have `parsed=None` — there is
  no LLM JSON parse involved on that path at all, the same reason
  `evidence_agreement` stays `None` on `check()`/`acheck()` results.
- Metadata-only follow-up: the PyPI package description (separate from
  this README) was also simplified from a Path-A/Path-B-specific
  summary to a shorter, feature-agnostic line, so it doesn't need
  updating every time a new mechanism is added.

## [v0.4.2] — validator=

- Added `validator=`, an optional keyword-only parameter on `check()` and
  `acheck()`: a caller-supplied `Callable[[str], bool | tuple[bool, str]]`
  that runs against an attempt's answer after the ambiguity check and
  before the confidence check. A validation failure gets its own distinct
  retry prompt (shows the specific failure reason) and reuses the existing
  `max_retries` budget rather than adding a separate one — a successful
  retry still reports `REPAIRED`; no new status was added.
- `validator` never runs on an attempt that failed to parse or was flagged
  ambiguous. An exception raised inside `validator`, or a return value
  that isn't `bool` or `(bool, str)`, is treated as a failed validation —
  it never propagates out of `check()`/`acheck()`.
- `validator=None` (the default) is a true no-op: every code path this
  parameter introduces is unreachable if it's never passed, so existing
  calls are unaffected. `validator` is keyword-only specifically so that
  adding it could not change the meaning of any existing positional call.
- `Attempt` gained `passed_validation: bool` (default `True`) and
  `validation_error: Optional[str]` (default `None`).
- `result.method` can now be `"validation"` — an `UNCERTAIN` result where
  the last attempt parsed fine and was confident enough, but never
  satisfied the supplied validator. Distinct from `"parse_failure"`
  (nothing usable was ever produced) and from `"confidence"` (the model
  was confident and no validator was involved, or it passed).
- Added GitHub Actions CI: the test suite now runs automatically on every
  push and pull request, across Python 3.9–3.12.

## [v0.4.1] — result.method

- Added `result.method`, a read-only property on `BoothResult` derived
  entirely from existing fields (`status`, `attempts`,
  `all_parse_failed`) — no new stored state. Identifies which mechanism
  actually produced a result: `"ambiguity"`, `"evidence"`,
  `"parse_failure"`, or `"confidence"`.
- For a mixed attempt history (e.g. a parse failure followed by a
  low-confidence answer), `method` reflects the *last* attempt's
  determining factor, the same rule `all_parse_failed` already follows —
  it summarizes the final outcome, not a full per-attempt history
  (`result.attempts` remains the source of truth for that).

## [v0.4.0] — check_with_evidence() / Path A

- Added `check_with_evidence()`: a standalone, pure, non-retrying
  function that checks whether an `answer` agrees with caller-supplied
  `evidence`, via a caller-supplied `compare_fn`. Makes no LLM calls, no
  network calls, and performs no retrieval — the caller's own RAG/tool
  pipeline owns retrieval; BOOTH only checks agreement once it's handed
  the result.
- `compare_fn` may return `bool` (strict pass/fail — `evidence_threshold`
  is ignored entirely for boolean returns) or a `float` score in
  `[0.0, 1.0]` (compared against `evidence_threshold`). An out-of-range
  score, a non-numeric return, or an exception raised inside
  `compare_fn` is treated as a failed comparison (`UNCERTAIN`), never
  silently clamped and never propagated.
- Added the `BLOCKED` status — reachable only from `check_with_evidence()`
  (a comparison that explicitly failed), never from `check()`/`acheck()`.
- Added `result.evidence_agreement`: the numeric comparison score, `None`
  for ordinary `check()`/`acheck()` results.
- `check_with_evidence()` has no relationship to a prior `check()`/
  `acheck()` result and does not read or mutate one — composing the two
  is left to the caller.

## [v0.3.1] — parse-failure handling

- Added a retry prompt distinct from the confidence-reconsideration
  prompt for responses that failed to parse at all (no valid JSON,
  missing keys, out-of-range confidence). Previously an unparseable
  response silently repeated the original prompt unchanged, giving a
  model with a stable formatting habit (markdown fences, a chatty
  preamble) no reason to correct course on retry.
- Added `result.all_parse_failed`: `True` only if *every* attempt failed
  to parse, distinguishing "nothing usable was ever produced" from
  "the model tried repeatedly but stayed under the confidence threshold"
  — different problems, different fixes.

## [v0.3.0] — acheck() / async support

- Added `acheck()`, the async twin of `check()`, for callers whose model
  client is async (`Callable[[str], Awaitable[str]]`). Passing a
  synchronous `call_fn` to `acheck()` (or an async `on_attempt` to
  `check()`) raises `TypeError` immediately rather than misbehaving
  silently.
- Internally refactored the accept/retry decision into a single shared
  `_evaluate()` step called identically by both `check()` and `acheck()`,
  so the two can't drift apart as future changes are made.
- Documented that both functions are stateless (no shared/module-level
  mutable state), so concurrent calls — many simultaneous users — don't
  interfere with each other.

## [v0.2.0]

- Added ambiguity detection: the model is asked to report `ambiguous`
  and `interpretations` *before* `answer` in the requested JSON schema.
  Because JSON is generated token-by-token left to right, this forces a
  real ambiguity judgment before the answer text is generated, not a
  self-audit added after the fact.
- Added the `AMBIGUOUS` status: returned immediately, regardless of
  confidence, and never retried — a question that's ambiguous as asked
  isn't fixed by asking the model to reconsider.
- Renamed the PyPI package to `boothpy` (the name `booth` was rejected by
  PyPI as disallowed).
- Added `TUTORIAL.md`.

## [v0.1.0]

- Initial release. `check()`: wraps an LLM call, requests a self-reported
  confidence score, and retries with a genuine reconsideration prompt
  (not blind resampling) when confidence is below a configurable
  threshold. `VERIFIED` / `REPAIRED` / `UNCERTAIN` statuses.

[Unreleased]: https://github.com/Vedantgitbot/booth/compare/v0.4.3...HEAD
[v0.4.3]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.3
[v0.4.2]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.2
[v0.4.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.1
[v0.4.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.0
[v0.3.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.1
[v0.3.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.0