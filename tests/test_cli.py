import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import get_args

from dataset_checker.models import ErrorCode

from helpers import TemporaryFiles, column

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "fixtures/inventory.schema.json"
CLEAN = ROOT / "fixtures/inventory.csv"
INVALID = ROOT / "fixtures/inventory-invalid.csv"


class CliTests(TemporaryFiles):
    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "dataset_checker", *map(str, arguments)],
            cwd=self.root, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False, capture_output=True, encoding="utf-8", timeout=20,
        )

    def test_clean_and_invalid_baselines_match_text_and_json(self):
        clean = self.cli("validate", CLEAN, "--schema", SCHEMA)
        self.assertEqual(clean.returncode, 0, clean.stderr + clean.stdout)
        self.assertIn("3 accepted, 0 rejected, 0 errors", clean.stdout)
        for format in ("text", "json"):
            result = self.cli("validate", INVALID, "--schema", SCHEMA, "--format", format)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stderr, "")
            if format == "text":
                self.assertIn("1 accepted, 3 rejected, 6 errors", result.stdout)
                self.assertIn("record 3", result.stdout)
                self.assertIn("column 'equipment_id'", result.stdout)
            else:
                data = json.loads(result.stdout)
                self.assertEqual(data["summary"], {
                    "records_examined": 4, "accepted": 1, "rejected": 3, "errors": 6, "omitted_errors": 0,
                })
                self.assertEqual(data["errors"][0]["first_occurrence"]["record"], 2)

    def test_error_code_catalog_covers_the_report_contract(self):
        result = self.cli("codes", "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        codes = json.loads(result.stdout)["codes"]
        self.assertEqual(set(codes), set(get_args(ErrorCode)))
        self.assertEqual(list(codes), sorted(codes))

    def test_saved_report_matches_json_stdout_and_protects_both_inputs(self):
        output = self.root / "report.json"
        result = self.cli("validate", INVALID, "--schema", SCHEMA, "--report", output, "--format", "json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, output.read_text(encoding="utf-8"))
        for source in (CLEAN, SCHEMA):
            original = source.read_bytes()
            result = self.cli("validate", CLEAN, "--schema", SCHEMA, "--report", source)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must differ", result.stderr)
            self.assertEqual(source.read_bytes(), original)

    def test_schema_display_round_trip_and_comparison(self):
        normalized = self.root / "normalized.json"
        display = self.cli("schema", SCHEMA, "--report", normalized, "--format", "json")
        self.assertEqual(display.returncode, 0, display.stderr)
        self.assertEqual(json.loads(display.stdout)["primary_key"], ["equipment_id"])
        same = self.cli("compare", SCHEMA, normalized, "--format", "json")
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertEqual(json.loads(same.stdout)["changes"], [])
        definition = json.loads(normalized.read_bytes())
        definition["columns"][2]["constraints"]["minimum"] = 1
        normalized.write_text(json.dumps(definition), encoding="utf-8")
        changed = self.cli("compare", SCHEMA, normalized)
        self.assertEqual(changed.returncode, 1, changed.stderr)
        self.assertIn("minimum_changed", changed.stdout)

    def test_batch_profiles_caps_and_strict_cli_paths(self):
        batch = self.cli("validate", CLEAN, INVALID, "--schema", SCHEMA, "--max-errors", 0, "--format", "json")
        self.assertEqual(batch.returncode, 1, batch.stderr)
        data = json.loads(batch.stdout)
        self.assertEqual(data["summary"], {"files_examined": 2, "accepted": 4, "rejected": 3, "errors": 6})
        self.assertEqual(data["files"][1]["summary"]["omitted_errors"], 6)
        strict = self.cli("validate", INVALID, CLEAN, "--schema", SCHEMA, "--strict", "--format", "json")
        self.assertEqual(strict.returncode, 1)
        self.assertTrue(json.loads(strict.stdout)["stopped_early"])
        profile = self.cli("validate", CLEAN, "--schema", SCHEMA, "--profile")
        self.assertEqual(profile.returncode, 0)
        self.assertIn("Observed range 0 to 2", profile.stdout)

    def test_invalid_schema_arguments_and_unreadable_data_exit_two(self):
        self.schema(column())
        for args, expected in (
            (("validate", CLEAN, "--schema", self.root / "missing.json"), "cannot read schema"),
            (("validate", CLEAN, "--schema", SCHEMA, "--max-errors", -1), "nonnegative"),
            (("validate", CLEAN, "--schema", SCHEMA, "--report", self.root / "missing/report.json"), "cannot save report"),
        ):
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(expected, result.stderr)
        missing = self.cli("validate", self.csv, "--schema", self.schema_file, "--format", "json")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error_counts"], {"file_unreadable": 1})
        self.write_csv(b"id\n\xff\n")
        encoding = self.cli("validate", self.csv, "--schema", self.schema_file, "--format", "json")
        self.assertEqual(encoding.returncode, 2)
        self.assertEqual(json.loads(encoding.stdout)["summary"]["rejected"], 1)
