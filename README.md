# Dataset Release Checker

Check a CSV release against a published column schema before distributing it. The local Python CLI validates headers and cells and reports errors by logical CSV record and column. It uses the standard library at runtime and targets Ubuntu with Python 3.10 or later.

## Install on Ubuntu

```bash
sudo apt install python3-venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
dataset-check --help
```

Run the synthetic inventory fixtures from the repository root.

```bash
dataset-check validate fixtures/inventory.csv --schema fixtures/inventory.schema.json
dataset-check validate fixtures/inventory-invalid.csv --schema fixtures/inventory.schema.json --format json
dataset-check validate fixtures/inventory-invalid.csv --schema fixtures/inventory.schema.json --report validation.json
```

The clean export has three accepted records, including a quoted comma, a multiline name, a null location, and the literal string `NULL`. The invalid export has one accepted and three rejected records, with six errors covering duplicate keys, whitespace-only names, range and length violations, an invalid boolean, and a forbidden null.

## Schema conventions

The v1 schema is a JSON document with a `columns` array. Each column explicitly declares `name`, `type`, `required`, and `nullable`. `required` controls whether the header must contain the column. `nullable` controls whether a present column's cells may be empty. A required nullable column such as `location` must always appear in the header and may contain empty cells. An absent optional column is skipped, including when its cells would be non-nullable if present.

Types are `string`, `integer`, `decimal`, `boolean`, and `date`. An empty decoded field, including `""`, represents null. Text such as `NULL`, `null`, and `N/A` remains literal text. Whitespace is preserved by default. Set `whitespace` to `trim` to trim nonempty values before parsing. A whitespace-only field becomes an empty string under trimming and keeps its non-null identity. Dates use `YYYY-MM-DD`. Booleans require explicit true and false spellings in the schema. Decimal values use `decimal.Decimal` and preserve precision.

CSV input uses UTF-8 with an optional initial BOM, LF or CRLF record endings, schema-defined delimiter and quote characters, and doubled quote escaping. Quotes must begin at the start of a field. Headers match exactly and remain case-sensitive. Record 1 is the header. Multiline quoted cells stay within one logical record. Physical line ranges are labeled separately.

## Inspect release contracts

```bash
dataset-check schema fixtures/inventory.schema.json --format json
dataset-check validate fixtures/inventory.csv --schema fixtures/inventory.schema.json --profile
dataset-check validate january.csv february.csv --schema inventory.schema.json --report validation.json
dataset-check compare january.schema.json february.schema.json --format json
dataset-check codes --format json
```

Column profiles report null and invalid counts and observed typed ranges or text lengths. Schema comparison flags removed columns and tightened validation rules for review. The design specs describe its compatibility interpretation.

`--strict` stops after the first invalid record or header and skips remaining input files. `--max-errors N` bounds retained error details per input while preserving totals. `--max-record-bytes N` bounds a logical record's encoded size. CSV syntax and encoding failures stop inspection because record framing is uncertain. Reports indicate whether EOF was reached.

| Exit | Meaning |
| --- | --- |
| `0` | Valid CSV, valid schema display, or comparison without breaking changes |
| `1` | Dataset validation errors or breaking schema changes |
| `2` | Usage, schema, encoding, or file I/O failure |

Reports go to stdout. Usage, schema, and report-write failures go to stderr. `--report` saves the same JSON result atomically, including failed validation results. Report destinations must differ from input paths. No credentials are required. Paths and schema conventions are configurable, examples use synthetic data, and local environment files are ignored by Git.

## Tests and design

```bash
python -m unittest discover -s tests -v
```

- [High-level design](docs/specs/high-level-design.md)
- [Low-level design](docs/specs/low-level-design.md)
- [Component specification](docs/specs/components.md)
- [Schema and CLI contracts](docs/specs/schema-and-cli-contracts.md)
- [Ubuntu test plan](docs/specs/test-plan.md)

Released under the [MIT License](LICENSE).
