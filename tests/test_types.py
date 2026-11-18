from datetime import date
from decimal import Decimal
import unittest

from dataset_checker.schema import parse_schema
from dataset_checker.types import CellValueError, constraint_failures, parse_cell

from helpers import column, document


class TypeTests(unittest.TestCase):
    def parse(self, raw, definition):
        return parse_cell(raw, parse_schema(document(definition)).columns[0])

    def test_empty_is_null_and_null_text_is_literal(self):
        definition = column(nullable=True)
        self.assertTrue(self.parse("", definition).is_null)
        self.assertEqual(self.parse("NULL", definition).value, "NULL")
        self.assertEqual(self.parse("null", definition).value, "null")
        with self.assertRaisesRegex(CellValueError, "nullable=false"):
            self.parse("", column())

    def test_whitespace_is_explicit_and_does_not_create_null(self):
        self.assertEqual(self.parse("  text  ", column()).value, "  text  ")
        result = self.parse("  ", column(whitespace="trim"))
        self.assertFalse(result.is_null)
        self.assertEqual(result.value, "")
        self.assertEqual(self.parse(" 42 ", column(kind="integer", whitespace="trim")).value, 42)
        with self.assertRaises(CellValueError):
            self.parse(" 42 ", column(kind="integer"))

    def test_decimal_precision_and_integer_syntax(self):
        text = "0.123456789012345678901234567890123456789"
        self.assertEqual(self.parse(text, column(kind="decimal")).value, Decimal(text))
        self.assertEqual(self.parse("+00042", column(kind="integer")).value, 42)
        for value in ("1.0", "1_000", "1e3", "\u0661"):
            with self.subTest(value=value), self.assertRaises(CellValueError):
                self.parse(value, column(kind="integer"))
        for value in ("NaN", "Infinity", "1,000"):
            with self.subTest(value=value), self.assertRaises(CellValueError):
                self.parse(value, column(kind="decimal"))

    def test_explicit_boolean_spellings_and_iso_dates(self):
        definition = column(kind="boolean", boolean={"true_values": ["YES"], "false_values": ["NO"], "case_sensitive": False})
        self.assertIs(self.parse("yes", definition).value, True)
        self.assertIs(self.parse("no", definition).value, False)
        with self.assertRaises(CellValueError):
            self.parse("1", definition)
        self.assertEqual(self.parse("2028-02-29", column(kind="date")).value, date(2028, 2, 29))
        for text in ("2027-02-29", "01/02/2028", "2028-2-29"):
            with self.subTest(text=text), self.assertRaises(CellValueError):
                self.parse(text, column(kind="date"))
