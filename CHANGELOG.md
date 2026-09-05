# Changelog

All notable changes to BOOTH are documented here. Versions follow
[Semantic Versioning](https://semver.org/): additive, backward-compatible
changes bump the minor version; small fixes/polish with no new public
surface bump the patch version.

## [Unreleased]

Nothing yet.

## [v0.4.5] — bugfix batch: check_with_evidence() boolish handling, whitespace-answer guard

Two confirmed bugs in `check_with_evidence()`, fixed together as one
release. Both are behavioral fixes to existing functionality — nothing
here adds a new public function or parameter. As with `v0.4.4`, every
fix here was verified by writing a failing test against the actual
behavior first, not assumed from reading the code, and a third,
version-compatibility issue was caught only because of that same
verification step.

- **`compare_fn` returning `numpy.bool_` not recognized as boolean.**
  `check_with_evidence()` used a bare `isinstance(raw_result, bool)`
  check, while `validator`'s equivalent check (`_is_boolish()`, added in
  `v0.4.4`) already correctly widened this to also accept `numpy.bool_`.
  A `compare_fn` written with numpy or pandas — a natural choice for
  numeric or array-based similarity comparisons — that returned
  `numpy.bool_(False)` fell through to the float-coercion branch
  instead, was coerced to `0.0`, and at `evidence_threshold=0.0` could
  resolve to `VERIFIED` instead of `BLOCKED` — a silent false-positive
  in the exact failure mode this library exists to prevent. Fixed by
  reusing the shared `_is_boolish()` helper in `check_with_evidence()`
  instead of the bare `isinstance` check, so both entry points now share
  one boolish-detection implementation instead of two independent ones
  that could drift apart.
- **`_is_boolish()` itself did not recognize numpy's boolean scalar type
  across numpy versions (found while writing the regression test for
  the fix above).** numpy 2.0 renamed the scalar boolean type, so that
  `type(np.bool_(x)).__name__` is `"bool"` on numpy >=2.0 but was
  `"bool_"` on numpy <2.0. The `v0.4.4` implementation of
  `_is_boolish()` only matched the pre-2.0 name, so on current numpy
  installs it silently failed to recognize `numpy.bool_` values at all
  — meaning the intended `v0.4.4` widening for `validator` was already
  not taking effect on numpy >=2.0 before this fix, in addition to the
  bug above. `_is_boolish()` now accepts both `"bool_"` and `"bool"`
  under the `numpy` module, verified directly against an installed
  numpy 2.4.4 in addition to the new regression test.
- **Whitespace-only `answer` bypassing the empty-input guard.**
  `check_with_evidence()`'s guard was `if not answer or not evidence`,
  which correctly catches `""` but not a whitespace-only string like
  `" "`, since `bool(" ")` is `True` in Python. A whitespace-only answer
  was silently passed through to the caller's `compare_fn` instead of
  being treated as missing input. Fixed by additionally checking
  `not answer.strip()`. Lower severity than the two bugs above — it
  does not reopen a previously-protected failure mode, since the
  outcome for a degenerate `" "` input was already undefined territory
  dependent on the caller's own `compare_fn` — but a one-line fix worth
  including in the same batch.
- **One candidate issue considered and deliberately not fixed:**
  `evidence` containing only blank or whitespace-only strings (e.g.
  `evidence=[" ", ""]`) is not specially detected; only a fully empty
  `evidence` sequence is rejected. This is structurally similar to the
  whitespace-`answer` bug above, but `evidence` content quality is
  explicitly the caller's documented responsibility (README, "Important:
  What Evidence Checking Means"), unlike `answer`, which BOOTH itself
  hands to `compare_fn` as the thing being judged. No test demonstrates
  this as an actual failure for any caller. Treated the same way the
  `v0.4.4` batch treated the (rejected) markdown-fence-stripping
  suggestion: a structurally-plausible-sounding fix is not the same as
  a confirmed bug, and speculative hardening here would exceed BOOTH's
  stated scope rather than fix something broken.

## [v0.4.4] — bugfix batch: silent-coercion fixes, missing export, validator-contract widening

Six confirmed bugs, fixed together as one release. All are behavioral
fixes to existing 0.4.x functionality — nothing here adds a new public
function or parameter. Verified in a live Python shell before fixing
(`bool("false") == True`, `float(True) == 1.0`), not assumed from
inspection, and every fix has a dedicated regression test.

- **Confidence accepting a JSON boolean (highest severity in this
  batch).** `float(confidence)` never raises on a Python `bool` —
  `float(True) == 1.0` and `float(False) == 0.0` succeed silently,
  because `bool` is a subclass of `int`. A model outputting
  `"confidence": true` (a schema violation, not a genuine numeric
  string like `"0.95"`) was silently accepted as a perfect 1.0
  confidence, producing a false `VERIFIED` — the exact silent-wrong-
  answer failure mode this library exists to prevent. Now rejected
  explicitly, before the `float()` conversion runs, and treated as an
  unparseable attempt like any other schema violation.
- **`ambiguous` accepting a non-boolean string.** `bool(obj.get(
  "ambiguous", False))` used Python's `bool()`, which treats any
  non-empty string as `True` — a model outputting the JSON *string*
  `"false"` (not the boolean `false`) for this field was silently
  flipped to `ambiguous=True`. New `_coerce_ambiguous()` accepts a real
  boolean or a literal `"true"`/`"false"` string (case-insensitive);
  anything else rejects the attempt rather than guessing at it, the
  same principle already applied to out-of-range confidence.
- **`ValidatorFn` missing from the public package.** Defined in
  `booth.core` since `v0.4.2`, but never imported into or exported from
  `booth/__init__.py` — anyone trying to type-hint their own validator
  function (`def my_validator(answer: str) -> ...`) couldn't import the
  alias from the documented public interface. Now exported:
  `from booth import ValidatorFn`.
- **`chosen_interpretation` silently dropping falsy-but-present
  values.** `str(chosen) if chosen else None` used a truthy check, so a
  model returning `0` or `""` for this field — genuinely present, just
  falsy — was silently discarded to `None` as if the field were absent.
  Changed to `is not None`, correctly distinguishing "absent/null" from
  "present but falsy." Lower severity than the two above since this
  field is informational and doesn't drive any status decision, but the
  same class of bug.
- **`validator`'s bool check rejecting `numpy.bool_`.**
  `isinstance(result, bool)` is not guaranteed to be `True` for
  `numpy.bool_` across numpy versions, so a validator using numpy or
  pandas for numeric/tabular checks could have its genuinely correct
  pass/fail silently reinterpreted as an "invalid return type" failure.
  New `_is_boolish()` recognizes `numpy.bool_` by module and class name
  rather than by importing numpy — BOOTH stays zero-dependency. (Note:
  the class-name check here only matched numpy's pre-2.0 naming; see the
  `v0.4.5` entry above for the cross-version fix.)
- **`validator`'s `(bool, str)` tuple check too strict for two natural
  mistakes.** `return True, None` — a natural way to write "passed, no
  message needed" — previously failed because the second element had
  to be a literal `str`, not `None`. Separately, `return [False, "..."]`
  (a list instead of a tuple, an easy habit to fall into) failed
  `isinstance(result, tuple)` outright. Both are now accepted with the
  identical contract as `(bool, str)`; a `False` with no message gets a
  generic fallback message. Genuinely malformed shapes (a 3-element
  list, a non-boolean first element) are still correctly rejected —
  confirmed by a dedicated negative test, not just assumed from the
  widening.
- **Three test-coverage gaps closed**, locking in behavior that was
  previously correct by inspection but unverified: `confidence`
  exactly equal to `threshold` passes on both `check()` and `acheck()`
  (the boundary is `>=`, not `>`); a model wrapping its answer as
  `[{...}]` instead of a bare object still recovers via the existing
  regex fallback; and the actual (previously just assumed) outcome of
  brace-like content inside an answer field colliding with the flat
  regex fallback during a primary-parse failure is now documented by a
  passing test rather than left unverified.

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

[Unreleased]: https://github.com/Vedantgitbot/booth/compare/v0.4.5...HEAD
[v0.4.5]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.5
[v0.4.4]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.4
[v0.4.3]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.3
[v0.4.2]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.2
[v0.4.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.1
[v0.4.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.4.0
[v0.3.1]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.1
[v0.3.0]: https://github.com/Vedantgitbot/booth/releases/tag/v0.3.0