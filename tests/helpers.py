import json
import tempfile
import unittest
from pathlib import Path

from dataset_checker.schema import parse_schema


def column(name="id", kind="string", **changes):
    result = {"name": name, "type": kind, "required": True, "nullable": False}
    if kind == "boolean":
        result["boolean"] = {"true_values": ["true"], "false_values": ["false"]}
    return {**result, **changes}


def document(*columns, **changes):
    return {"version": 1, "columns": list(columns) or [column()], **changes}


class TemporaryFiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.csv = self.root / "input.csv"
        self.schema_file = self.root / "schema.json"

    def write_csv(self, contents):
        self.csv.write_bytes(contents.encode("utf-8") if isinstance(contents, str) else contents)
        return self.csv

    def schema(self, *columns, **changes):
        definition = document(*columns, **changes)
        self.schema_file.write_text(json.dumps(definition), encoding="utf-8")
        return parse_schema(definition)
