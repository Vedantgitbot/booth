# Changelog

All notable changes to BOOTH are documented here. Versions follow
[Semantic Versioning](https://semver.org/): additive, backward-compatible
changes bump the minor version; small fixes/polish with no new public
surface bump the patch version.

## [Unreleased]

Nothing yet.

## [v0.5.0] — BoothResult.unwrap() / unwrap_or() / BoothRejected; Development Status: Beta

The first `0.x` release that's purely additive rather than a bugfix
batch — no existing behavior changed, no existing test needed to
change. `pyproject.toml`'s `Development Status` classifier moves from
`3 - Alpha` to `4 - Beta`: ten releases in, with a consistent
reproduce-first fix discipline and 208 tests carried forward with zero
regressions across the whole run, BOOTH has moved past the
"exploratory hack" stage this classifier is meant to signal.

- **Added `BoothResult.unwrap()`.** `.answer` is typed
  `Optional[str]` and stays populated even on a rejected result
  (`AMBIGUOUS`/`UNCERTAIN`/`BLOCKED`) — deliberately, for debugging
  and logging visibility — which means a caller who forgets to check
  `.ok` or `.status` first can silently ship a rejected answer with no
  error at all. `unwrap()` returns `.answer` as a plain `str` when the
  result is ok, and raises `BoothRejected` otherwise. It uses exactly
  the same predicate as `.ok` — it literally calls `self.ok`
  internally rather than reimplementing the check — so the two can
  never drift apart from each other. This is purely additive: `.answer`
  is completely unchanged, on every status, for every existing caller.
  `unwrap()` is a stricter, opt-in accessor layered on top, not a
  replacement.
- **Added `BoothRejected`**, the exception `unwrap()` raises. Carries
  the full original `BoothResult` as `.result`, so catching it loses
  no diagnostic information — `.result.status`, `.result.method`,
  `.result.attempts`, everything is still reachable from inside the
  `except` block. The exception's own string message deliberately
  excludes the raw rejected answer text: exception messages routinely
  end up in logs, and a rejected answer is exactly the kind of content
  that shouldn't be logged by default just because someone called
  `unwrap()`. The message does include `status` and `method`; the
  rejected text itself is reachable explicitly via `e.result.answer`
  if actually needed.
- **Added `BoothResult.unwrap_or(default)`.** Same idea as `unwrap()`,
  but returns `default` instead of raising when the result isn't ok —
  for callers who'd rather write a plain fallback value than a
  `try`/`except` at the call site.
- **New regression test file** (`test_v050_regressions.py`, 20 tests)
  covering: `unwrap()` returning the answer on `ACCEPTED` and
  `REPAIRED`, from both `check()` and `acheck()` results, and from
  `check_with_evidence()`; `unwrap()` raising `BoothRejected` on
  `AMBIGUOUS`, `UNCERTAIN`, and `BLOCKED`; a parity test asserting
  `unwrap()`'s predicate matches `.ok` exactly across every reachable
  status, constructed as a single scenario matrix rather than five
  separate near-duplicate tests; `.answer` confirmed still populated
  on rejected results even after `unwrap()` has been called on the
  same result object; `BoothRejected.result` carrying the exact same
  object the caller already had; a planted "secret-looking" answer
  string confirmed absent from `str(BoothRejected)` while still
  reachable via `e.result.answer`; `unwrap_or()` returning the real
  answer when ok and the default otherwise, and confirmed to never
  raise regardless of status; and two defensive tests against a
  hand-built `BoothResult` (not reachable through the public API) to
  confirm `unwrap()` can't return `None` from a function typed to
  return `str`.
- Verified against the full test suite carried forward unmodified from
  `v0.4.9` (208 tests across `test_acheck.py`, `test_core.py`,
  `test_evidence.py`, `test_method.py`, `test_parsed.py`,
  `test_validator.py`, and `test_v045_regressions.py` through
  `test_v049_regressions.py`) — 228 total, zero modifications to any
  existing test.

## [v0.4.9] — bugfix batch: empty-answer guard, brace-parsing fallback, check_with_evidence() robustness, numeric/bool answers, error reasons, evidence_threshold validation

Six fixes, shipped together in the order below. All were reproduced
against the actual `v0.4.8` release before being fixed here, and all
208 tests (177 carried over unmodified, 31 new) pass with zero
regressions to any existing test.

- **An empty or whitespace-only `answer` was silently accepted as
  `ACCEPTED` at high confidence.** Nothing in `_parse_response()`
  rejected `{"answer": "", "confidence": 0.99}` — a blank answer with
  no content at all could pass every check purely because the
  self-reported confidence was high. Now rejected the same way an
  out-of-range confidence already is, with one deliberate exemption:
  an `AMBIGUOUS` attempt is exempt from this guard, since the model
  may legitimately leave `answer` blank while relying on
  `interpretations` to carry the real content instead.
- **Brace-like content inside `answer` could defeat the fallback JSON
  extractor.** The flat `_JSON_RE` regex (`\{[^{}]*\}`) only matches an
  object with no nested braces at all, so a *complete, valid* JSON
  object embedded in surrounding commentary — where the object's own
  `answer` string happens to contain brace-like text, e.g. `"the
  config is {mode: fast, retries: 3}"` — could never be recovered by
  regex alone, even though nothing about the object was actually
  malformed. `json.JSONDecoder.raw_decode` is now tried as a further
  fallback, scanning for every `{` in the text and attempting a real,
  balanced parse from that position — it correctly treats braces
  inside a JSON string value as ordinary content rather than
  structure, which a flat regex fundamentally cannot do. This runs in
  addition to the existing regex pass, not instead of it: the regex
  stays first since it's cheap and covers the common case, and
  `raw_decode` is the slower, more thorough fallback. Genuinely
  malformed JSON (e.g. a response missing its closing brace entirely)
  still correctly fails to parse — this fix recovers *valid* objects
  that were previously unreachable, it does not start inferring
  results out of broken input.
- **`check_with_evidence()` crashed instead of failing predictably on
  three different malformed inputs.** All three are now handled
  explicitly:
  - A non-`str`, non-`None` `answer` (an `int`, a `list`, etc.)
    previously crashed with `AttributeError` on `answer.strip()`. Now
    raises `TypeError` immediately, naming the offending type.
    `answer=None` is unaffected — it already short-circuited safely
    and still returns `UNCERTAIN`.
  - `evidence` passed as a multi-element `numpy` array crashed the
    emptiness check (`not evidence`) with `ValueError: the truth value
    of an array is ambiguous`. A new `_is_empty_evidence()` helper uses
    `len()` instead, which works correctly for anything sized —
    `numpy` arrays included — without ever consulting `__bool__`.
  - An `async def compare_fn`, or a synchronous wrapper that itself
    returns a coroutine (e.g. `lambda a, e: some_async_fn(a, e)`),
    doesn't raise when called — it just hands back an un-awaited
    coroutine object. This previously either crashed confusingly
    inside the later `float()` conversion or silently fell through to
    `UNCERTAIN`, and either way leaked a "coroutine was never awaited"
    `RuntimeWarning`. Now detected explicitly and rejected with a
    clear `TypeError`, the same discipline `_run_validator()` already
    applies to an async `validator`.
- **Numeric and boolean `answer` values are now accepted instead of
  treated as parse failures.** A model returning `{"answer": 42}` was
  previously rejected outright by the `v0.4.8` non-string-answer guard,
  which was written to stop a `dict`/`list` `answer` from being
  silently `str()`-coerced into a misleading Python repr. That guard
  was correct for structured values but too broad — a genuine scalar
  like an `int`, `float`, or `bool` is not the same failure mode. `int`,
  `float`, and `bool` answers are now coerced to their string form
  (`42` → `"42"`) for the normalized `.answer` field, the same split
  already used for `confidence` (`.confidence` is coerced,
  `.parsed["confidence"]` keeps the raw value) — `.parsed["answer"]`
  keeps the original, uncoerced type. `dict` and `list` values are
  still rejected exactly as before; only the scalar case changed.
- **`Attempt.error` was left `None` on most parse failures**, even
  though a `call_fn` exception or a non-string `call_fn` return already
  populated it with a specific reason. Every rejection path inside
  `_parse_response()` (missing keys, wrong types, out-of-range
  confidence, unrecognized `ambiguous` value, empty answer, no JSON
  found at all) now records a specific, human-readable reason — e.g.
  `"'confidence' 17.0 is out of the [0.0, 1.0] range"` — instead of
  leaving the field blank on total parse failure.
- **`evidence_threshold` had no type validation**, unlike `max_retries`
  (fixed in `v0.4.8`). A `str` or `None` value produced Python's
  generic comparison `TypeError` deep inside `0.0 <= evidence_threshold`
  instead of a clear error at the call site. Now raises `TypeError`
  immediately for anything that isn't a real number. Deliberately
  stricter than `max_retries` on one point: `bool` is also rejected
  here, not treated as harmless — a threshold silently becoming
  "require a perfect 1.0" or "accept anything" is far more likely to
  be a caller mistake than an intentional choice, unlike `max_retries`
  where `True`/`False` meaning 1/0 retries is a reasonable reading.
- **New regression test file** (`test_v049_regressions.py`, 31 tests)
  covering all six items above, plus: the empty-answer guard correctly
  exempting `AMBIGUOUS` attempts; the `raw_decode` fallback recovering
  a nested-brace answer embedded in prose while a genuinely incomplete
  JSON object (missing closing brace) still correctly fails safe;
  `check_with_evidence()`'s non-str-`answer` and async-`compare_fn`
  fixes producing zero leaked `RuntimeWarning`s (verified by promoting
  `RuntimeWarning` to a raised exception for the duration of that
  assertion); numeric/float/boolean `answer` values all coercing
  correctly while `.parsed` keeps the raw type; and
  `evidence_threshold` rejecting `str`/`None`/`bool` while still
  accepting a plain `int` and still raising `ValueError` (not silently
  swallowed by the new type check) for an in-type but out-of-range
  value like `1.5`.
- Verified against the actual published `v0.4.8` sdist pulled from
  PyPI: all 177 existing tests across `test_acheck.py`,
  `test_bugfixes_0_4_4.py`, `test_core.py`, `test_evidence.py`,
  `test_method.py`, `test_parsed.py`, `test_v045_regressions.py`,
  `test_v046_regressions.py`, `test_v047_regressions.py`, and
  `test_validator.py` pass unmodified against the new `core.py` — no
  existing test needed to change to accommodate this batch.

## [v0.4.8] — BREAKING: VERIFIED renamed to ACCEPTED; bugfix batch: async call_fn/non-str return/max_retries/non-str answer

**BREAKING CHANGE:** `VERIFIED` is renamed to `ACCEPTED`. There is no
backward-compatible alias, per explicit decision: fix the naming early,
while BOOTH has few real dependents, rather than carry a misleading
name forward. `from booth import VERIFIED` now raises `ImportError`;
every caller must move to `booth.ACCEPTED`. The underlying status
*string* also changed, from `"VERIFIED"` to `"ACCEPTED"` — not just the
importable constant — so any code comparing against a hardcoded
`"VERIFIED"` string literal (rather than the exported constant) will
silently stop matching. This was always the wrong pattern to rely on;
the constant was always the documented interface.

Four confirmed bugs, fixed together as one release, all reproduced
against the actual v0.4.7 tag before being fixed here:

- **`check()` had no defense against an async `call_fn`.** `acheck()`
  already rejected the opposite (sync `call_fn` passed to `acheck()`)
  direction symmetrically, but `check()` had no equivalent guard: an
  async `call_fn` passed to `check()` returned a coroutine object,
  which `_parse_response()` then tried to `.strip()` as text, crashing
  with `AttributeError` and leaking an unawaited-coroutine
  `RuntimeWarning`. `check()` now raises `TypeError` immediately, with
  a message pointing the caller to `acheck()`, mirroring how `acheck()`
  already handles a mistakenly-sync `call_fn`.
- **`call_fn` succeeding but returning something other than a string
  crashed instead of failing gracefully.** A `call_fn` that returns
  `None`, a `dict`, or any other non-string value (e.g. a misconfigured
  or mocked client) previously crashed deep inside `_parse_response()`
  with an unhelpful `AttributeError`, rather than being treated as a
  failed attempt the way a `call_fn` exception already was. New
  `_call_fn_to_attempt()` helper checks the return type before parsing
  begins: a non-string return now produces a proper failed `Attempt`
  (`parse_ok=False`, a descriptive `error` naming the offending type)
  and participates normally in the retry loop, in both `check()` and
  `acheck()`.
- **`max_retries=1.5` (or any non-int) passed validation silently, then
  crashed far from the real mistake.** `_validate_args()` only checked
  `max_retries >= 0`, so a float slipped through and later crashed
  inside `range(max_retries + 1)` with a generic `TypeError` that gave
  no indication the problem was the `max_retries` argument itself.
  `_validate_args()` now explicitly rejects any `max_retries` that
  isn't an `int`, raising `TypeError` immediately at the call site.
  `bool` is deliberately still accepted (it's an `int` subclass and a
  harmless case here — `True`/`False` just mean 1 or 0 retries) —
  unlike the dangerous bool-as-confidence case fixed in `v0.4.4`, this
  one was left alone on purpose.
- **A non-string `answer` field was silently `str()`-coerced into a
  misleading, high-confidence `ACCEPTED` result.** `_parse_response()`
  called `str(answer)` unconditionally, so a model returning a `dict`
  or `list` for `answer` (a schema violation, not a genuine string) was
  silently turned into a Python `repr` — not even valid JSON — and
  reported as a normal, trustworthy answer at whatever confidence the
  model claimed. This is the same class of bug as the `v0.4.4` boolean-
  confidence fix: a schema violation quietly disguised as a real
  result instead of being rejected. A non-string `answer` is now
  rejected before parsing succeeds, with the same discipline already
  applied to `confidence`; `interpretations`' existing non-list-to-`[]`
  coercion is explicitly left untouched (informational field, doesn't
  drive status, benign default).
- **New regression test file** (`tests/test_v048_regressions.py`)
  covering: `booth.ACCEPTED == "ACCEPTED"` importable from both the
  package root and `booth.core`; `VERIFIED` no longer present anywhere
  on the module and `from booth import VERIFIED` raising `ImportError`;
  `check()`/`check_with_evidence()`/`to_dict()` all reporting
  `"ACCEPTED"` post-rename; `REPAIRED` still distinct from `ACCEPTED`
  and still `ok`; `check()` rejecting both a plain async function and
  an `async def __call__` object with `TypeError` and zero leaked
  coroutine warnings, while a plain sync `call_fn` is unaffected; a
  `None` or `dict` return from both `check()` and `acheck()` producing
  a proper `UNCERTAIN` with a descriptive error instead of crashing,
  including recovery to `REPAIRED` when a bad first attempt is followed
  by a good retry; `max_retries=1.5` raising `TypeError`,
  `max_retries=False` still working normally, and `max_retries=-1`
  still correctly raising `ValueError` (not superseded by the new
  type check); and a `dict`- or `list`-valued `answer` being rejected
  into `UNCERTAIN` with `result.answer is None`, alongside a
  confirmation that a genuine string `answer` still works exactly as
  before.
- All existing test files (`test_acheck.py`, `test_bugfixes_0_4_4.py`,
  `test_core.py`, `test_evidence.py`, `test_method.py`, `test_parsed.py`,
  `test_v045_regressions.py`, `test_v046_regressions.py`,
  `test_v047_regressions.py`, `test_validator.py`) were updated in
  place to reference `bth.ACCEPTED`/`booth.ACCEPTED` instead of the
  removed `VERIFIED`, including test names and print messages
  (`test_verified_first_try` → `test_accepted_first_try`, etc.) — no
  behavioral changes in those files beyond the rename itself.

## [v0.4.7] — bugfix batch: on_attempt async-callable detection, BoothResult.to_dict()

Two confirmed fixes, released together: one closes a detection gap in
`on_attempt` handling that mirrors the `call_fn` bug fixed in `v0.4.6`
but was never applied to the callback path, and the other adds a
serialization convenience for `BoothResult`.

- **`on_attempt` async-callable detection missed the same cases
  `call_fn` did before `v0.4.6`.** Both `check()` and `acheck()` still
  used a bare `inspect.iscoroutinefunction(on_attempt)` check to decide
  whether the callback needed to be awaited (`acheck()`) or rejected
  with `TypeError` (`check()`, which only ever accepted a synchronous
  `on_attempt`) — the same check already known to miss an object whose
  `__call__` is itself `async def`. A callback wrapped in a class
  (e.g. `class Logger: async def __call__(self, index, attempt): ...`,
  a natural pattern for a rate-limited or batching logger) was silently
  misdetected: passed to `acheck()`, it was called without being
  awaited, producing an unawaited coroutine and a silently-skipped
  callback instead of running correctly; passed to `check()`, it
  slipped past the synchronous-only guard instead of raising
  `TypeError` immediately, as documented. Both entry points now reuse
  the `_is_async_callable()` helper introduced in `v0.4.6` for
  `call_fn`, so `on_attempt` and `call_fn` are checked identically and
  can no longer drift apart from each other.
- **Added `BoothResult.to_dict()`.** `dataclasses.asdict(result)` looks
  like the obvious way to serialize a result for logging or a message
  queue, but `BoothResult`'s most useful fields — `ok`, `method` — are
  computed properties, not dataclass fields, so `asdict()` silently
  drops them. `to_dict()` returns a plain `dict` containing every
  documented `BoothResult` field *and* every computed property, and
  converts each `Attempt` in `attempts` via `dataclasses.asdict()` as
  well, so a full result — including its attempt history — is
  JSON-serializable in one call.
- **New regression test file** (`test_v047_regressions.py`) covering:
  an `async def __call__` object and a `functools.partial`-wrapped
  async function both working correctly as `on_attempt` for `acheck()`;
  the same two shapes correctly raising `TypeError` when passed as
  `on_attempt` to `check()`; a plain synchronous `on_attempt` still
  working on both entry points, unaffected by the detection change; and
  `to_dict()` round-tripping through `json.dumps()` for a result from
  each of `check()`, `acheck()`, and `check_with_evidence()`, confirming
  `ok`, `method`, and every nested `Attempt` are present and
  JSON-serializable.

## [v0.4.6] — bugfix batch: callable compatibility hardening

Two confirmed bugs in async-callable dispatch, fixed together as one
release, themed around Python calling-convention edge cases rather than
BOOTH's own decision logic. No new public function, parameter, or
status. As with `v0.4.4`/`v0.4.5`, every fix here was verified against
actual Python behavior before being written, and two related
candidates were investigated and explicitly declined rather than
folded in speculatively.

- **`acheck()` rejecting an object whose `__call__` is itself
  `async def`.** `inspect.iscoroutinefunction(call_fn)` returns `False`
  for a class instance implementing `async def __call__`, even though
  calling the instance does produce a coroutine — the check only
  recognizes the function/method itself as a coroutine function, not
  an instance whose dunder method is one. A caller wrapping an async
  LLM client in a class (a common pattern — e.g. a stateful or
  rate-limited client wrapper) was incorrectly rejected with
  `TypeError`. Fixed with a new `_is_async_callable()` helper, used in
  place of the bare `inspect.iscoroutinefunction()` check in `acheck()`:
  recognizes a plain `async def` function, `functools.partial` wrapping
  one, and an object with `async def __call__`.
- **Leaked `RuntimeWarning` when an `async def` validator is passed by
  mistake.** `_run_validator()` already correctly rejected a coroutine
  return value as an invalid type — the validation *contract* was never
  broken — but the coroutine object was created and then discarded
  without being awaited or closed, so Python emitted
  `RuntimeWarning: coroutine '...' was never awaited` to stderr on every
  occurrence. Fixed by detecting `inspect.iscoroutine(result)`
  explicitly, closing it, and returning a specific, actionable message
  ("validator must be synchronous...") instead of the generic
  invalid-type one. Behavior (`False`, a message) is unchanged; only
  the warning noise and message specificity changed.
- **Two related candidates investigated and explicitly declined:**
  - `functools.partial` wrapping an async function was suspected as a
    possible cross-version compatibility gap (BOOTH supports Python
    3.9–3.12). Verified directly against CPython's `inspect` source:
    `inspect.iscoroutinefunction()` already unwraps `functools.partial`
    internally via `functools._unwrap_partial()`, a behavior present
    since Python 3.8 — predating BOOTH's entire supported range. No fix
    needed; a positive regression test locks this in against a future
    change accidentally breaking it, rather than treating it as newly
    fixed.
  - A callable object with a *synchronous* `__call__` that internally
    returns an awaitable (`def __call__(self, prompt): return
    some_coroutine`) was considered for detection. Confirmed there is
    no signature-level way to distinguish this from an ordinary sync
    callable without actually invoking it — which `acheck()`
    deliberately does not do speculatively, since that would call a
    real function just to inspect its dispatch type. Documented as
    intentionally unsupported (Tutorial §3, §10) rather than fixed.
- **New regression test file** (`test_v046_regressions.py`) covering,
  as explicit pass/fail assertions rather than just static inspection:
  plain async function, `async def __call__` object, and
  `functools.partial(async_fn)` all working with `acheck()`; plain sync
  function, sync `__call__` object, and `functools.partial(sync_fn)`
  all correctly rejected; `check()`'s sync path unaffected by any of
  the `acheck()` changes; and an `async def` validator producing a
  clean `UNCERTAIN`/`"validation"` result with zero `RuntimeWarning`
  emitted, verified by promoting `RuntimeWarning` to a raised exception
  for the duration of that specific assertion.

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

[Unreleased]: https://github.com/Vedantgitbot/booth/compare/v0.5.0...HEAD
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