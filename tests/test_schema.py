import json
from decimal import Decimal

from dataset_checker.schema import SchemaError, load_schema, parse_schema, schema_document

from helpers import TemporaryFiles, column, document


class SchemaTests(TemporaryFiles):
    def test_required_and_nullable_are_independent(self):
        schema = self.schema(column("location", nullable=True), column("optional", required=False))
        self.assertTrue(schema.columns[0].required)
        self.assertTrue(schema.columns[0].nullable)
        self.assertFalse(schema.columns[1].required)
        self.assertFalse(schema.columns[1].nullable)

    def test_duplicate_names_missing_flags_invalid_type_and_unknown_fields(self):
        for value, message in (
            (document(column(), column()), "duplicate column names"),
            (document({"name": "x", "type": "string", "required": True}), "nullable"),
            (document(column(kind="float")), "must be one of"),
            (document(column(required=1)), "must be a boolean"),
            (document(column(), extra=True), "unknown fields"),
            (document(column(constraints={"minumum": 1})), "unknown fields"),
            ({"version": True, "columns": [column()]}, "unsupported schema version"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(SchemaError, message):
                parse_schema(value)

    def test_rejects_contradictory_constraints(self):
        cases = (
            column(kind="integer", constraints={"minimum": 5, "maximum": 2}),
            column(constraints={"min_length": 5, "max_length": 2}),
            column(constraints={"nonempty_after_trim": True, "max_length": 0}),
            column(kind="integer", constraints={"max_length": 2}),
            column(constraints={"minimum": 1}),
            column(kind="integer", constraints={"enum": [1, 1]}),
            column(kind="integer", constraints={"enum": [1], "minimum": 2}),
            column(whitespace="trim", constraints={"enum": [" padded "]}),
            column(constraints={"enum": []}),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(SchemaError):
                parse_schema(document(value))

    def test_primary_key_requires_existing_required_nonnullable_columns(self):
        for columns, key in (([column()], ["missing"]), ([column(nullable=True)], ["id"]),
                             ([column(required=False)], ["id"]), ([column()], ["id", "id"])):
            with self.subTest(columns=columns, key=key), self.assertRaises(SchemaError):
                parse_schema(document(*columns, primary_key=key))

    def test_boolean_formats_reject_ambiguous_spellings(self):
        for value in (
            {"true_values": ["yes"], "false_values": ["yes"]},
            {"true_values": ["YES", "yes"], "false_values": ["no"], "case_sensitive": False},
            {"true_values": [], "false_values": ["no"]},
        ):
            with self.subTest(value=value), self.assertRaises(SchemaError):
                parse_schema(document(column(kind="boolean", boolean=value)))

    def test_exact_decimal_schema_load_and_normalized_round_trip(self):
        self.schema_file.write_text('''{"version":1,"columns":[{"name":"price","type":"decimal",
            "required":true,"nullable":false,"constraints":{
            "minimum":0.12345678901234567890123456789,"enum":[0.12345678901234567890123456789]}}]}''', encoding="utf-8")
        loaded = load_schema(self.schema_file)
        self.assertEqual(loaded.columns[0].constraints.minimum, Decimal("0.12345678901234567890123456789"))
        self.assertEqual(parse_schema(schema_document(loaded)), loaded)

    def test_duplicate_keys_nonstandard_constants_and_malformed_json(self):
        for text in ('{"version":1,"version":1}', '{"version":NaN}', '{', '\xff'):
            self.schema_file.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaisesRegex(SchemaError, "invalid schema"):
                load_schema(self.schema_file)

    def test_csv_conventions_and_row_limits_are_validated(self):
        for changes in ({"csv": {"delimiter": ",", "quotechar": ","}},
                        {"csv": {"delimiter": "\n"}}, {"min_rows": 2, "max_rows": 1},
                        {"max_rows": False}):
            with self.subTest(changes=changes), self.assertRaises(SchemaError):
                parse_schema(document(**changes))
