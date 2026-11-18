from dataset_checker.comparison import compare_schemas
from dataset_checker.schema import parse_schema

from helpers import TemporaryFiles, column, document


class ComparisonTests(TemporaryFiles):
    def compare(self, before, after):
        return compare_schemas(parse_schema(before), parse_schema(after))

    def test_identical_schemas_and_metadata_changes(self):
        before = document()
        self.assertTrue(self.compare(before, before).compatible)
        result = self.compare(before, document(title="New title"))
        self.assertEqual(result.summary, {"breaking": 0, "compatible": 0, "metadata": 1})

    def test_removed_added_and_typed_columns(self):
        before = document(column(), column("old"))
        after = document(column(kind="integer"), column("optional", required=False))
        result = self.compare(before, after)
        self.assertEqual([(change.column, change.code) for change in result.changes], [
            ("id", "type_changed"), ("old", "column_removed"), ("optional", "column_added"),
        ])
        self.assertFalse(result.compatible)

    def test_range_enum_and_nullability_direction(self):
        before = document(column("n", "integer", nullable=True, constraints={"minimum": 0, "enum": [0, 1, 2]}))
        after = document(column("n", "integer", nullable=False, constraints={"minimum": 1, "enum": [1, 2]}))
        result = self.compare(before, after)
        self.assertEqual(result.summary["breaking"], 3)
        self.assertTrue(self.compare(after, before).compatible)

    def test_boolean_case_expansion_preserves_prior_spellings(self):
        before = document(column(kind="boolean"))
        after = document(column(kind="boolean", boolean={
            "true_values": ["true", "yes"], "false_values": ["false", "no"], "case_sensitive": False,
        }))
        self.assertTrue(self.compare(before, after).compatible)
        self.assertFalse(self.compare(after, before).compatible)

    def test_csv_rules_and_primary_key_changes(self):
        before = document(column(), column("other"), csv={"enforce_column_order": True})
        after = document(column("other"), column(), primary_key=["id"], csv={"enforce_column_order": True})
        result = self.compare(before, after)
        self.assertEqual({change.code for change in result.changes}, {"columns_reordered", "primary_key_changed"})
