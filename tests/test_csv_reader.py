import csv
import io
import os
import unittest

from dataset_checker.csv_reader import read_csv
from dataset_checker.models import CsvConventions, CsvRecord, Diagnostic

from helpers import TemporaryFiles


class CsvReaderTests(TemporaryFiles):
    def test_quoted_commas_multiline_fields_and_doubled_quotes(self):
        self.write_csv('id,name\r\n1,"Microscope, shared"\r\n2,"Pump\r\nwith ""controller"""\r\n')
        records = list(read_csv(self.csv))
        self.assertEqual([row.number for row in records], [1, 2, 3])
        self.assertEqual(records[1].cells, ("1", "Microscope, shared"))
        self.assertEqual(records[2].cells, ("2", 'Pump\r\nwith "controller"'))
        self.assertEqual((records[2].physical_line_start, records[2].physical_line_end), (3, 4))

    def test_parser_matches_standard_csv_for_synthetic_valid_records(self):
        cases = [[], [""], ["a", "", "b"], ["quoted,comma", 'double"quote', "line\nline"],
                 [" ", "NULL", "\u00e9quipement"], ["last", ""]]
        for cells in cases:
            stream = io.StringIO(newline="")
            csv.writer(stream).writerow(cells)
            self.write_csv(stream.getvalue())
            with self.subTest(cells=cells):
                result = list(read_csv(self.csv))
                self.assertEqual(result[0].cells, tuple(cells))

    def test_bom_no_final_newline_and_custom_delimiter(self):
        self.write_csv(b'\xef\xbb\xbfid;name\n1;\'shared; microscope\'')
        result = list(read_csv(self.csv, CsvConventions(delimiter=";", quotechar="'")))
        self.assertEqual([row.cells for row in result], [("id", "name"), ("1", "shared; microscope")])

    def test_malformed_quoting_stops_with_record_and_column(self):
        for text in ('id,name\n1,plain"quote\n2,good\n', 'id,name\n1,"name" extra\n', 'id,name\n1,"unclosed\n'):
            self.write_csv(text)
            result = list(read_csv(self.csv))
            with self.subTest(text=text):
                self.assertEqual(len(result), 2)
                self.assertIsInstance(result[0], CsvRecord)
                self.assertIsInstance(result[1], Diagnostic)
                self.assertEqual(result[1].code, "malformed_csv")
                self.assertEqual((result[1].location.record, result[1].location.column_index), (2, 2))

    def test_encoding_and_record_limit_failures_are_localized(self):
        self.write_csv(b'id\n\xff\n')
        issue = list(read_csv(self.csv))[-1]
        self.assertEqual((issue.code, issue.location.record), ("invalid_encoding", 2))
        self.write_csv('id\n"123\n456"\n')
        issue = list(read_csv(self.csv, max_record_bytes=8))[-1]
        self.assertEqual((issue.code, issue.location.record), ("record_too_large", 2))
        self.assertEqual(issue.location.physical_line_end, 3)

    def test_empty_file_blank_record_and_unreadable_path(self):
        self.write_csv("")
        self.assertEqual(list(read_csv(self.csv)), [])
        self.write_csv("\n")
        self.assertEqual(list(read_csv(self.csv))[0].cells, ())
        for path in (self.root / "missing", self.root):
            self.assertEqual(list(read_csv(path))[0].code, "file_unreadable")

    def test_byte_limit_includes_bom_and_does_not_split_a_physical_line(self):
        self.write_csv(b"\xef\xbb\xbfid\n")
        records = list(read_csv(self.csv, max_record_bytes=4))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].code, "record_too_large")
        self.write_csv(b"\xef\xbb\xbf")
        self.assertEqual(list(read_csv(self.csv)), [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_fifo_is_rejected_without_reading(self):
        os.mkfifo(self.csv)
        self.assertEqual(list(read_csv(self.csv))[0].code, "file_unreadable")
