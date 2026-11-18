# Schema and CLI contracts

## Commands

```text
dataset-check validate <csv-file> [<csv-file> ...] --schema <schema-file>
              [--format text|json] [--report <json-file>] [--strict] [--profile]
              [--max-errors N] [--max-record-bytes N]
dataset-check schema <schema-file> [--format text|json] [--report <json-file>]
dataset-check compare <before-schema> <after-schema> [--format text|json] [--report <json-file>]
dataset-check codes [--format text|json]
```

Angle-bracketed values are runtime placeholders. Text is the default stdout format. `--report` independently saves JSON. The default record limit is 8 MiB, including encoded line endings and an initial BOM. A zero diagnostic cap retains counts and omits all details. Strict mode stops after the first invalid header or data record and skips subsequent files. Report parents must exist.

## Dataset schema v1

This project defines a versioned column contract represented as JSON. It uses its own `version` and `columns` fields. Unknown schema keys are rejected to catch misspellings.

| Top-level field | Contract |
| --- | --- |
| `version` | Required integer `1` |
| `columns` | Required nonempty array of column objects with unique names |
| `primary_key` | Optional array of distinct existing column names, default empty |
| `csv` | Optional object with `delimiter`, `quotechar`, `allow_extra_columns`, and `enforce_column_order` |
| `min_rows`, `max_rows` | Optional nonnegative data-record bounds. Default minimum is zero and maximum is unlimited. |
| `title` | Optional nonempty descriptive string |

CSV delimiter defaults to comma and quote character defaults to `"`. Extras and order enforcement default to false. Delimiter and quote character must differ. Input is UTF-8 with an optional initial BOM and LF or CRLF separators. Doubled quotes escape quotes inside a quoted cell. Whitespace after a closing quote is invalid.

| Column field | Contract |
| --- | --- |
| `name` | Required case-sensitive printable header name, with no surrounding whitespace |
| `type` | Required `string`, `integer`, `decimal`, `boolean`, or `date` |
| `required` | Required boolean governing header presence |
| `nullable` | Required boolean governing decoded empty cells |
| `whitespace` | Optional `preserve` or `trim`, default preserve |
| `constraints` | Optional object of applicable rules |
| `boolean` | Required for boolean columns. Contains nonempty `true_values` and `false_values` arrays and optional `case_sensitive`, default true. |
| `description` | Optional descriptive string |

Supported constraints are inclusive `minimum` and `maximum` for integers, decimals, and dates, `min_length`, `max_length`, and `nonempty_after_trim` for strings, and `enum` and `unique` for all types. Length counts Python Unicode code points. Nullable cells bypass non-null constraints. Unique nullable columns can have multiple nulls. Primary-key columns must be required and non-nullable.

Only an empty decoded CSV field is null. Literal `NULL` remains text. Trimming applies after null detection and never changes a nonempty field into null. An integer is an optional sign followed by ASCII digits. Decimals accept a decimal point and optional exponent, forbid NaN and infinity, and use exact decimal values. Dates use Gregorian `YYYY-MM-DD`. Boolean spellings and case rules come entirely from the column schema. Enum values are typed JSON values, with decimal and date strings accepted for exact representation. Null enums are invalid because nullability is configured separately.

## Locations and reports

Validation reports use `report_version: 1`. An individual report has `command`, `file`, `schema`, `ok`, `complete`, `stopped_early`, `operational_error`, `row_numbering`, `summary`, `header`, `error_counts`, `columns`, and `errors`. Summary contains `records_examined`, `accepted`, `rejected`, `errors`, and `omitted_errors`. Logical record 1 is the header and is excluded from data-record totals. `accepted + rejected = records_examined`. File or header errors can make a result fail even when no data rows exist.

Each error has `code`, `message`, `file`, `record`, `physical_line_start`, `physical_line_end`, `column`, `column_index`, and `first_occurrence`. Record and column indexes are one-based. Inapplicable positions are null. Duplicate keys and headers include the first occurrence. Error messages omit cell contents. Errors appear in encounter order and fields follow header order. `dataset-check codes --format json` returns the complete code catalog.

Column profiles include presence, cell totals, null and invalid counts, parsed non-null counts, observed extrema, text lengths, and true/false counts. JSON always includes profiles. Text displays them with `--profile`. Date extrema serialize as ISO strings and decimal extrema as decimal strings.

For multiple examined files, the outer report has combined `summary`, `ok`, `operational_error`, and a `files` array of individual reports in input order. One examined file uses the individual report format, including when strict mode skips later files. Keys and uniqueness are scoped independently to each CSV.

Schema inspection returns normalized schema JSON that can be loaded again. Comparison JSON includes earlier and later schema paths, `compatible`, counts by impact, and ordered `changes` with code, impact, message, and optional column name.

## Exit statuses

Exit `0` means a clean validation, valid schema display, code catalog, or comparison with no breaking changes. Exit `1` means dataset errors or breaking schema changes. Exit `2` means invalid invocation, invalid schema, encoding failure, input I/O failure, or report-write failure. The command handler returns `130` on keyboard interruption. Operational failures take precedence over validation failures. CSV input failures appear in reports on stdout. Schema and output failures appear on stderr.
