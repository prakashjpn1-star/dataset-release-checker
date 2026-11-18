from unittest.mock import patch

from dataset_checker.output import ReportWriteError, write_report

from helpers import TemporaryFiles


class OutputTests(TemporaryFiles):
    def test_atomic_failure_preserves_previous_report_and_removes_temporary_file(self):
        path = self.root / "report.json"
        path.write_bytes(b"original")
        with patch("dataset_checker.output.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaisesRegex(ReportWriteError, "locked"):
                write_report(path, "{}")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(self.root.iterdir()), [path])
