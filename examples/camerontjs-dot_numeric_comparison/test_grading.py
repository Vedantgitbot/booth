"""Independent rational reference-grader checks and synthetic fixture audit."""

from fractions import Fraction
import json
from pathlib import Path
import unittest

from grade_answers import grade_answer, _quantity


DATA = json.loads(Path(__file__).with_name("cases.json").read_text())
CASES = DATA["cases"]
BY_ID = {case["id"]: case for case in CASES}


def half_up(value, places):
    """Independent integer/rational half-up calculation (ties away from zero)."""
    scaled = abs(value) * 10 ** places
    rounded = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    return Fraction(rounded if value >= 0 else -rounded, 10 ** places)


class ReferenceGradingTests(unittest.TestCase):
    def assert_label(self, case, answer, label):
        result = grade_answer(case, answer)
        self.assertEqual(set(result), {"label", "detail"})
        self.assertIsInstance(result["detail"], str)
        self.assertTrue(result["detail"])
        self.assertEqual(result["label"], label, repr(answer))

    def test_all_authored_controls(self):
        for case in CASES + DATA["smoke_cases"]:
            with self.subTest(case=case["id"]):
                self.assert_label(case, case["correct_answer"], "correct")
                self.assert_label(case, case["wrong_answer"], "wrong")

    def test_exact_values_without_answer_rounding(self):
        for name, answer in [
            ("round_half_up", "12.345 CAD"),
            ("round_even_trap", "2.225 USD"),
            ("round_down", "9.994 EUR"),
            ("round_negative", "-2.225 CAD"),
            ("invoice_total", "1356.000000000000000000000001 CAD"),
        ]:
            with self.subTest(case=name):
                self.assert_label(BY_ID[name], answer, "wrong")

    def test_equivalent_supported_formats(self):
        checks = {
            "invoice_total": ["1,356.00 CAD", "CAD 1356", "CAD1356", "+1356 CAD", "1.356 thousand CAD"],
            "negative_cash_flow": ["(42.50) USD", "USD (42.50)", "USD(42.50)", "(42.50 USD)", "(USD 42.50)"],
            "million_scale": ["1.25 million CAD", "1250 thousand CAD", "CAD 1.25 million"],
            "fraction_to_percent": ["0.075 fraction", ".075 fraction", "7.5%", "7.500 percent"],
            "percent_not_fraction": ["0.125 fraction", "12.5 percent"],
            "points_not_percent": ["2 percentage points", "2 percentage point", "2.000 percentage   points"],
            "days_not_months": ["30 day", "30 days"],
            "items_not_currency": ["12 item", "12 items"],
        }
        for name, answers in checks.items():
            for answer in answers:
                with self.subTest(case=name, answer=answer):
                    self.assert_label(BY_ID[name], answer, "correct")

    def test_numeric_mutations_for_every_case(self):
        for case in CASES:
            reference = case["reference"]
            value = Fraction(reference["value"])
            # All references are terminating decimals; adding one changes the
            # value while retaining a supported explicit unit.
            mutated = int(value) + 1 if value.denominator == 1 else reference["value"] + "1"
            with self.subTest(case=case["id"]):
                self.assert_label(case, f"{mutated} {reference['unit']}", "wrong")

    def test_currency_and_unit_swaps(self):
        for answer in ["1356 USD", "1356 EUR", "1356 days", "1356 items"]:
            self.assert_label(BY_ID["invoice_total"], answer, "wrong")
        self.assert_label(BY_ID["days_not_months"], "30 months", "wrong")
        self.assert_label(BY_ID["items_not_currency"], "12 days", "wrong")

    def test_singular_units_and_money_only_scaling(self):
        self.assert_label({"reference": {"value": "3", "unit": "months"}}, "3 month", "correct")
        self.assert_label(BY_ID["million_scale"], "CAD1.25 million", "correct")
        for answer in ["0.03 thousand days", "0.00003 million days", "0.012 thousand items",
                       "0.005 thousand percent", "0.000005 million fraction",
                       "0.002 thousand percentage points", "1 million months"]:
            with self.subTest(answer=answer):
                self.assert_label(BY_ID["days_not_months"], answer, "unscoreable")

    def test_rates_and_points_remain_distinct(self):
        for answer in ["0.075 percent", "7.5 fraction", "7.5 percentage points"]:
            self.assert_label(BY_ID["fraction_to_percent"], answer, "wrong")
        self.assert_label(BY_ID["points_not_percent"], "0.02 fraction", "wrong")
        self.assert_label(BY_ID["percent_not_points"], "0.05 fraction", "correct")
        self.assert_label(BY_ID["percent_not_points"], "0.05 percentage points", "wrong")

    def test_missing_and_unsupported(self):
        for answer in [None, "", " \n\t"]:
            self.assert_label(BY_ID["invoice_total"], answer, "no_answer")
        for answer in [
            "$1356", "1356 $", "CAD $1356", "1,35,6 CAD", "13,56 CAD",
            "1,356, CAD", "1,,356 CAD", "1 356 CAD", "1.356,00 CAD",
            "1356 CAD and 0 CAD", "1356 CAD / 1356 CAD", "1356 CAD USD",
            "The total is 1356 CAD", "1356 CAD.", "**1356 CAD**", "1356",
            "NaN CAD", "Inf CAD", "-Infinity CAD", "1e3 CAD", "1356/1 CAD",
            "(-1356) CAD", "(+1356) CAD", "((1356)) CAD", "((1356 CAD))",
            "1 billion CAD", "1356 yen", "No answer", 1356, False, {}, [],
        ]:
            with self.subTest(answer=answer):
                self.assert_label(BY_ID["invoice_total"], answer, "unscoreable")

    def test_reference_only_and_invalid_reference(self):
        self.assert_label({"reference": {"value": "12.35", "unit": "CAD"},
                           "source": "malformed source", "round_places": 0,
                           "correct_answer": "wrong"}, "12.35 CAD", "correct")
        for case in [{}, {"reference": {}}, {"reference": {"value": "NaN", "unit": "CAD"}},
                     {"reference": {"value": 1356, "unit": "CAD"}}]:
            self.assert_label(case, "1356 CAD", "unscoreable")


class FixtureAuditTests(unittest.TestCase):
    # Manually transcribed source quantities before requested rounding. This
    # audit covers every main fixture; it is distinct from correctness grading,
    # whose API reads no source facts.
    SOURCE_VALUES = {
        "invoice_total": ("1356", "CAD"),
        "amount_due": ("42.75", "EUR"),
        "negative_cash_flow": ("-42.50", "USD"),
        "negative_credit": ("-125", "CAD"),
        "round_half_up": ("12.345", "CAD"),
        "round_even_trap": ("2.225", "USD"),
        "round_down": ("9.994", "EUR"),
        "round_negative": ("-2.225", "CAD"),
        "cad_not_usd": ("800", "CAD"),
        "eur_not_usd": ("90", "EUR"),
        "million_scale": ("1250000", "CAD"),
        "thousand_scale": ("250000", "USD"),
        "days_not_months": ("30", "days"),
        "items_not_currency": ("12", "items"),
        "percent_not_points": ("5", "percent"),
        "points_not_percent": ("2", "percentage points"),
        "fraction_to_percent": ("7.5", "percent"),
        "shipping_not_gross": ("25", "CAD"),
        "account_scope": ("80", "CAD"),
        "percent_not_fraction": ("12.5", "percent"),
    }

    def test_all_twenty_sources_questions_and_references(self):
        self.assertEqual(len(CASES), 20)
        self.assertEqual(len(BY_ID), 20)
        self.assertEqual(set(BY_ID), set(self.SOURCE_VALUES))
        for case in CASES:
            with self.subTest(case=case["id"]):
                value_text, unit = self.SOURCE_VALUES[case["id"]]
                source_value = Fraction(value_text)
                target_lines = [line.split(":", 1)[1].strip()
                                for line in case["source"].splitlines()
                                if line.startswith(case["target"] + ":")]
                self.assertEqual(len(target_lines), 1)
                self.assertEqual(_quantity(target_lines[0]), _quantity(value_text + " " + unit))
                self.assertIn('"' + case["target"] + '"', case["question"])
                if case["round_places"] is not None:
                    places = case["round_places"]
                    self.assertIn(f"Round to {places} decimal places using half-up rounding.", case["question"])
                    expected = half_up(source_value, places)
                else:
                    self.assertNotIn("Round to", case["question"])
                    expected = source_value
                self.assertEqual(Fraction(case["reference"]["value"]), expected)
                self.assertEqual(case["reference"]["unit"], unit)

    def test_rational_rounding_boundaries(self):
        for before, after in [("2.225", "2.23"), ("-2.225", "-2.23"),
                              ("9.994", "9.99"), ("9.995", "10"),
                              ("-9.995", "-10"), ("0.005", "0.01")]:
            self.assertEqual(half_up(Fraction(before), 2), Fraction(after))

    def test_explicit_cross_field_arithmetic(self):
        # The authored invoice sum and percentage-point change also agree
        # with their component facts; most other fields are direct lookups.
        invoice_fields = dict(line.split(": ", 1) for line in
                              BY_ID["invoice_total"]["source"].splitlines()[1:])
        subtotal, subtotal_unit = _quantity(invoice_fields["Subtotal"])
        tax, tax_unit = _quantity(invoice_fields["Tax"])
        total, total_unit = _quantity(invoice_fields["Invoice total"])
        self.assertEqual((subtotal_unit, tax_unit, total_unit), ("CAD", "CAD", "CAD"))
        self.assertEqual(subtotal + tax, total)
        rate_fields = dict(line.split(": ", 1) for line in
                           BY_ID["points_not_percent"]["source"].splitlines()[1:])
        prior, prior_unit = _quantity(rate_fields["Prior rate"])
        new, new_unit = _quantity(rate_fields["New rate"])
        change, change_unit = _quantity(rate_fields["Rate change"])
        self.assertEqual((prior_unit, new_unit, change_unit),
                         ("rate", "rate", "percentage points"))
        self.assertEqual((new - prior) * 100, change)


if __name__ == "__main__":
    unittest.main()
