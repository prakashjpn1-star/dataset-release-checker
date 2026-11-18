# Component specification

| Module | Interfaces | Responsibilities |
| --- | --- | --- |
| `models.py` | `Column`, `DatasetSchema`, `Location`, `Diagnostic`, `ValidationOptions`, `ValidationReport`, `BatchReport` | Immutable contracts, stable error codes, report totals, and diagnostic collection |
| `schema.py` | `load_schema`, `parse_schema`, `schema_document` | Validate schema structure and constraints and serialize normalized definitions |
| `csv_reader.py` | `read_csv` | Strict quoted CSV framing with logical record and physical line positions |
| `types.py` | `parse_cell`, `parse_scalar`, `schema_scalar`, `constraint_failures` | Null detection, exact typed parsing, and cell constraints |
| `validation.py` | `validate_file`, `validate_files` | Header reconciliation, cell validation, uniqueness, profiles, and final outcomes |
| `comparison.py` | `compare_schemas` | Classify differences between published validation contracts |
| `reporting.py` | `render_validation`, `render_batch`, `render_schema`, `render_comparison`, `render_codes` | Text and JSON presentation from shared records |
| `output.py` | `check_destination`, `write_report` | Protect source paths and atomically save JSON reports |
| `cli.py` | `main` | Parse options, dispatch commands, route output, and determine exit status |

The `dataset-check` console entry point and `python -m dataset_checker` both invoke `main()`. The schema loader and CSV reader own input access. Validation combines the loaded schema and streamed records. Reporting returns strings, and the CLI writes stdout or requests a saved report. See the [schema and CLI contracts](schema-and-cli-contracts.md) for external fields and flags.
