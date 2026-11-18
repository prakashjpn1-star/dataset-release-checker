# Test plan

GitHub Actions installs the package on Ubuntu with Python 3.10 and 3.14, checks the console entry point, and runs the standard-library unittest suite. Tests use temporary files and synthetic records.

```bash
python -m pip install .
dataset-check --help
python -m unittest discover -s tests -v
```

| Test module | Coverage |
| --- | --- |
| [`test_schema.py`](../../tests/test_schema.py) | Required versus nullable, duplicate names, unknown keys and types, contradictory bounds and enums, primary-key references, exact decimal schema loading, and normalized round trips |
| [`test_csv_reader.py`](../../tests/test_csv_reader.py) | Quoted commas, multiline fields, doubled quotes, record numbering, BOM, custom delimiters, field framing, encoding failures, and byte limits |
| [`test_types.py`](../../tests/test_types.py) | Null conventions, trimming, integer syntax, decimal precision, boolean spellings, and Gregorian dates |
| [`test_validation.py`](../../tests/test_validation.py) | Missing and duplicate headers, invalid values, composite keys, nullable unique fields, profiles, strict mode, row limits, and independent batch files |
| [`test_comparison.py`](../../tests/test_comparison.py) | Removed and typed columns, tighter or looser constraints, boolean changes, and primary-key or CSV changes |
| [`test_output.py`](../../tests/test_output.py) | Atomic report failure and temporary-file cleanup |
| [`test_cli.py`](../../tests/test_cli.py) | Text and JSON agreement, saved reports, source protection, end-to-end inventory checks, exit codes, and comparison |

## Baseline acceptance

Validate [the clean inventory](../../fixtures/inventory.csv) against [its schema](../../fixtures/inventory.schema.json). Expect three accepted data records, zero errors, and exit `0`. The record containing a multiline name remains logical record 3 even though it occupies two physical lines. The nullable `location` header remains present. The literal location `NULL` stays text.

Validate [the invalid inventory](../../fixtures/inventory-invalid.csv) in text and JSON and save a report. Expect one accepted and three rejected records, six errors, and exit `1`. Confirm the duplicate key references logical records 3 and 2. Read the saved JSON and verify that its counts equal stdout. Inspect the schema with `schema --format json` and load the normalized result again. Compare identical schemas and expect no changes.
