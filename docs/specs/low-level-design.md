# Low-level design

## Schema preparation

`load_schema()` reads UTF-8 JSON and parses numeric decimal tokens directly as `Decimal`. It rejects duplicate JSON keys, unsupported versions, unknown fields, invalid column definitions, contradictory bounds, empty or inconsistent enumerations, and ambiguous boolean spellings. Primary-key columns must exist, have required headers, and disallow null cells. `schema_document()` serializes typed decimal constraints as decimal strings and dates as ISO strings so a normalized schema preserves its values when loaded again.

## CSV records and locations

`read_csv()` opens a regular file for reading and feeds physical LF or CRLF lines to a strict quoting state machine. The states are start of field, unquoted field, quoted field, and closed quote. Inside a quoted field, a doubled quote appends one quote character, delimiters become content, and physical line endings remain part of the decoded value. After a closing quote, the next character must be a delimiter, a doubled quote, or the end of the record. Quotes embedded in unquoted fields are errors.

Each emitted `CsvRecord` contains a one-based logical record number, its physical line range, and decoded fields. The header is record 1. Blank physical records remain records with zero fields. The reader bounds each logical record's encoded size, including BOM and line endings, without changing Python's global CSV field limit. Syntax, encoding, and oversized-record failures terminate the stream because later record boundaries may be uncertain. A malformed data record contributes one rejection. A file I/O failure has no assumed data-record count.

## Header and cell validation

The header is checked for empty, invalid, and duplicate names, missing required columns, forbidden extra columns, and optional order enforcement. An invalid header prevents assigning data cells to unambiguous schema columns. Data records are counted as rejected under that header, with header diagnostics explaining the file failure. Field-count mismatches produce their own record errors.

For a structurally valid row, map each declared present header to its schema column. Empty decoded fields are null before whitespace handling. For nonempty fields, apply the column's preserve or trim rule, parse the typed value, and apply the applicable constraints. Multiple cell failures create multiple diagnostics while the data record contributes only one rejection.

Each non-null, valid key component is represented by its typed value. A composite primary key is indexed by a tuple. Per-column uniqueness uses separate indexes. Typed equivalence means integer keys `01`, `+1`, and `1` agree. Nulls are skipped for optional unique-column checks. A valid key is reserved by its first occurrence even if another cell in that row is invalid. This exposes later duplicates in the export. Duplicate diagnostics retain the first logical and physical source location.

Strict mode finishes checking the current record and then stops. It skips remaining files in a batch. Collect mode continues after cell and field-count errors. A detail limit changes retained error objects while counts and pass/fail outcomes remain exact. Dataset row-count limits are evaluated at EOF and count all examined data records, including rejected records.

## Profiles and reports

Profiles count examined cells, raw empty cells, invalid cells, successfully parsed non-null values, numeric or date extrema, string lengths, and boolean counts. Typed profiles include values that later fail constraints or uniqueness. Invalid headers and wrong field counts prevent cell-level profiling for affected records. Decimal profile extrema serialize as strings to preserve precision.

The report writer creates a temporary sibling, writes the complete JSON report, flushes and synchronizes it, and replaces the destination. It checks resolved paths and existing filesystem aliases against the CSV and schema inputs. A failed write retains the previous report and attempts temporary-file cleanup. Directory-entry power-loss durability is outside the write contract.

## Schema comparison

Comparison reports removed columns, added required columns, type changes, tightened bounds, narrower enums, stricter uniqueness, new primary keys, changed CSV syntax, and tighter order rules as breaking changes. Relaxed constraints and optional column additions are compatible changes. Descriptions and titles are metadata changes. Column removals are conservatively breaking even when permissive extra-column handling would accept some old files. Normalization changes require review. The result evaluates individual contract changes and does not prove all interactions or consumer assumptions compatible.

## Complexity

Validation scans each file once. Working memory grows with one logical record, retained diagnostics, and distinct key values. Column statistics have fixed size per schema column. Multiple files have independent key scopes. File reports are retained for the final batch output, and error caps apply to each file separately.
