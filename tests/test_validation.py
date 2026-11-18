from decimal import Decimal

from dataset_checker.models import ValidationOptions
from dataset_checker.reporting import report_document
from dataset_checker.validation import validate_file, validate_files

from helpers import TemporaryFiles, column


class ValidationTests(TemporaryFiles):
    def check(self, schema, options=ValidationOptions()):
        return validate_file(self.csv, schema, options=options)

    def test_required_nullable_location_and_optional_nonnullable_column(self):
        schema = self.schema(column(), column("location", nullable=True), column("notes", required=False))
        self.write_csv("id,location\nA,\nB,NULL\n")
        report = self.check(schema)
        self.assertTrue(report.ok)
        self.assertEqual((report.accepted, report.rejected), (2, 0))
        self.assertEqual(report.columns[1].null_cells, 1)
        self.assertFalse(report.columns[2].present)
        self.write_csv("id\nA\n")
        report = self.check(schema)
        self.assertEqual(report.error_counts, {"missing_column": 1})
        self.assertEqual(report.errors[0].location.column, "location")
        self.assertEqual((report.accepted, report.rejected), (0, 1))

    def test_header_failures_are_reported_without_ambiguous_cell_checks(self):
        schema = self.schema(column(), column("quantity", "integer"))
        self.write_csv("id,id,unknown\nA,B,4\n")
        report = self.check(schema)
        self.assertEqual(report.error_counts, {"duplicate_header": 1, "missing_column": 1, "unexpected_column": 1})
        self.assertEqual((report.accepted, report.rejected), (0, 1))
        duplicate = report.errors[0]
        self.assertEqual(duplicate.first_occurrence.column_index, 1)
        self.assertEqual(duplicate.location.column_index, 2)

    def test_multiple_cell_errors_reject_a_record_once(self):
        schema = self.schema(column("name", constraints={"nonempty_after_trim": True}),
                             column("quantity", "integer", constraints={"minimum": 0}),
                             column("location", constraints={"max_length": 3}))
        self.write_csv("name,quantity,location\n   ,-1,long\nGood,2,Lab\n")
        report = self.check(schema)
        self.assertEqual((report.accepted, report.rejected, report.error_count), (1, 1, 3))
        self.assertTrue(report.complete)
        self.assertEqual([error.location.column for error in report.errors], ["name", "quantity", "location"])
        self.assertTrue(all(error.location.record == 2 for error in report.errors))

    def test_composite_typed_primary_keys_and_column_uniqueness(self):
        schema = self.schema(column("id", "integer"), column("site"),
                             column("serial", nullable=True, constraints={"unique": True}), primary_key=["id", "site"])
        self.write_csv("id,site,serial\n01,A,\n1,B,\n+1,A,S-1\n2,C,S-1\n")
        report = self.check(schema)
        self.assertEqual((report.accepted, report.rejected), (2, 2))
        self.assertEqual(report.error_counts, {"duplicate_key": 1, "duplicate_value": 1})
        self.assertEqual(report.errors[0].first_occurrence.record, 2)
        self.assertEqual(report.errors[1].first_occurrence.record, 4)

    def test_bad_nonkey_cells_still_reserve_a_valid_key_for_duplicate_detection(self):
        schema = self.schema(column(), column("n", "integer"), primary_key=["id"])
        self.write_csv("id,n\nA,bad\nA,2\n")
        report = self.check(schema)
        self.assertEqual(report.error_counts, {"duplicate_key": 1, "invalid_integer": 1})
        self.assertEqual(report.errors[1].first_occurrence.record, 2)

    def test_field_counts_blank_records_and_multiline_provenance(self):
        schema = self.schema(column(), column("name"))
        self.write_csv('id,name\nA,"two\nlines"\nB\n\nC,good\n')
        report = self.check(schema)
        self.assertEqual((report.accepted, report.rejected), (2, 2))
        self.assertEqual(report.errors[0].location.record, 3)
        self.assertEqual(report.errors[0].location.physical_line_start, 4)
        self.assertEqual(report.errors[1].location.record, 4)
        self.assertEqual(report.error_counts, {"field_count": 2})

    def test_fatal_syntax_reports_partial_totals_and_column_name(self):
        schema = self.schema(column(), column("name"))
        self.write_csv('id,name\nA,good\nB,"unclosed\n')
        report = self.check(schema)
        self.assertFalse(report.complete)
        self.assertEqual((report.accepted, report.rejected), (1, 1))
        self.assertEqual(report.errors[0].location.column, "name")

    def test_empty_file_header_only_and_row_limits(self):
        schema = self.schema(column(), min_rows=1, max_rows=2)
        self.write_csv("")
        self.assertEqual(self.check(schema).error_counts, {"empty_file": 1})
        self.write_csv("id\n")
        self.assertEqual(self.check(schema).error_counts, {"too_few_rows": 1})
        self.write_csv("id\nA\nB\nC\n")
        report = self.check(schema)
        self.assertEqual(report.error_counts, {"too_many_rows": 1})
        self.assertEqual(report.accepted, 3)

    def test_error_cap_does_not_change_counts_and_strict_stops_between_records(self):
        schema = self.schema(column("n", "integer"))
        self.write_csv("n\nbad\nbad\n3\n")
        report = self.check(schema, ValidationOptions(max_errors=0))
        self.assertEqual((report.accepted, report.rejected, report.omitted_errors), (1, 2, 2))
        strict = self.check(schema, ValidationOptions(strict=True, max_errors=0))
        self.assertEqual((strict.accepted, strict.rejected), (0, 1))
        self.assertTrue(strict.stopped_early)
        self.assertFalse(strict.complete)

    def test_profiles_preserve_decimal_precision_in_json(self):
        schema = self.schema(column("price", "decimal"), column("flag", "boolean"))
        self.write_csv("price,flag\n0.12345678901234567890123456789,true\n2.000,false\n")
        report = self.check(schema)
        self.assertEqual(report.columns[0].minimum_value, Decimal("0.12345678901234567890123456789"))
        structured = report_document(report)
        self.assertEqual(structured["columns"][0]["minimum_value"], "0.12345678901234567890123456789")
        self.assertEqual(structured["columns"][1]["false_cells"], 1)

    def test_batch_keeps_independent_key_scopes_and_strict_skips_later_files(self):
        schema = self.schema(column(), primary_key=["id"])
        self.write_csv("id\nA\n")
        second = self.root / "second.csv"
        second.write_text("id\nA\n", encoding="utf-8")
        batch = validate_files([self.csv, second], schema)
        self.assertTrue(batch.ok)
        self.assertEqual(batch.accepted, 2)
        self.write_csv("id\n\n")
        batch = validate_files([self.csv, second], schema, options=ValidationOptions(strict=True))
        self.assertEqual(len(batch.reports), 1)
