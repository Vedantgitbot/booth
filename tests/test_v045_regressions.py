"""
Regression tests for the v0.4.5 bugfix batch.

Both bugs live in check_with_evidence():
  1. numpy.bool_ from compare_fn wasn't recognized as boolish, so it
     fell through to the float() branch and could pass at
     evidence_threshold=0.0 instead of being treated as a strict fail.
  2. A whitespace-only answer (" ") slipped past the `not answer`
     guard and was passed straight into compare_fn.
"""

import pytest

from booth.core import check_with_evidence, VERIFIED, BLOCKED, UNCERTAIN

np = pytest.importorskip("numpy")


def test_numpy_bool_false_is_blocked_at_zero_threshold():
    def compare_fn(answer, evidence):
        return np.bool_(False)

    result = check_with_evidence(
        answer="Paris is the capital of France.",
        evidence=["France's capital city is Paris."],
        compare_fn=compare_fn,
        evidence_threshold=0.0,
    )

    assert result.status == BLOCKED
    assert result.evidence_agreement == 0.0


def test_numpy_bool_true_matches_native_true():
    def compare_fn_numpy(answer, evidence):
        return np.bool_(True)

    def compare_fn_native(answer, evidence):
        return True

    result_numpy = check_with_evidence(
        answer="Paris is the capital of France.",
        evidence=["France's capital city is Paris."],
        compare_fn=compare_fn_numpy,
    )
    result_native = check_with_evidence(
        answer="Paris is the capital of France.",
        evidence=["France's capital city is Paris."],
        compare_fn=compare_fn_native,
    )

    assert result_numpy.status == result_native.status == VERIFIED
    assert result_numpy.evidence_agreement == result_native.evidence_agreement == 1.0


def test_is_boolish_accepts_both_numpy_bool_spellings():
    # numpy >=2.0 renamed the scalar bool type's __name__ from
    # "bool_" to "bool" (np.bool_ is now just an alias). Both must
    # be recognized regardless of installed numpy version.
    from booth.core import _is_boolish

    assert _is_boolish(np.bool_(True)) is True
    assert _is_boolish(np.bool_(False)) is True
    assert type(np.bool_(False)).__name__ in ("bool_", "bool")


def test_native_bool_false_still_blocked_at_zero_threshold():
    def compare_fn(answer, evidence):
        return False

    result = check_with_evidence(
        answer="Some answer.",
        evidence=["Some evidence."],
        compare_fn=compare_fn,
        evidence_threshold=0.0,
    )

    assert result.status == BLOCKED


def test_evidence_threshold_not_applied_to_numpy_bool():
    # Boolean-shaped results (native or numpy) are strict pass/fail —
    # evidence_threshold must not be consulted for them.
    def compare_fn(answer, evidence):
        return np.bool_(True)

    result = check_with_evidence(
        answer="Some answer.",
        evidence=["Some evidence."],
        compare_fn=compare_fn,
        evidence_threshold=0.99,
    )

    assert result.status == VERIFIED


def test_whitespace_only_answer_is_uncertain_and_compare_fn_not_called():
    called = {"value": False}

    def compare_fn(answer, evidence):
        called["value"] = True
        return True

    result = check_with_evidence(
        answer="   ",
        evidence=["Some evidence."],
        compare_fn=compare_fn,
    )

    assert result.status == UNCERTAIN
    assert called["value"] is False


def test_empty_string_answer_still_uncertain():
    def compare_fn(answer, evidence):
        return True

    result = check_with_evidence(
        answer="",
        evidence=["Some evidence."],
        compare_fn=compare_fn,
    )

    assert result.status == UNCERTAIN


def test_non_whitespace_answer_unaffected():
    def compare_fn(answer, evidence):
        return True

    result = check_with_evidence(
        answer="Paris",
        evidence=["Paris is the capital of France."],
        compare_fn=compare_fn,
    )

    assert result.status == VERIFIED