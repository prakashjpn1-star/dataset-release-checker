"""Schema, source-location, and validation report records."""

import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

ColumnType = Literal["string", "integer", "decimal", "boolean", "date"]
COLUMN_TYPES: tuple[ColumnType, ...] = ("string", "integer", "decimal", "boolean", "date")
Scalar = str | int | Decimal | bool | date
ErrorCode = Literal[
    "file_unreadable", "invalid_encoding", "empty_file", "malformed_csv",
    "record_too_large", "empty_header", "duplicate_header", "invalid_header",
    "missing_column", "unexpected_column", "header_order", "field_count",
    "null_not_allowed", "invalid_integer", "invalid_decimal", "invalid_boolean",
    "invalid_date", "below_minimum", "above_maximum", "too_short", "too_long",
    "empty_after_trim", "not_in_enum", "duplicate_key", "duplicate_value",
    "too_few_rows", "too_many_rows",
]
ERROR_DESCRIPTIONS: dict[ErrorCode, str] = {
    "file_unreadable": "The input path cannot be read as a regular file.",
    "invalid_encoding": "The input contains bytes outside UTF-8.",
    "empty_file": "The input lacks a CSV header record.",
    "malformed_csv": "CSV quoting or record syntax is invalid.",
    "record_too_large": "A logical record exceeds the configured byte limit.",
    "empty_header": "A header name or the whole header record is empty.",
    "duplicate_header": "A header name appears more than once.",
    "invalid_header": "A header contains controls or surrounding whitespace.",
    "missing_column": "A required header is absent.",
    "unexpected_column": "An undeclared header is forbidden by the schema.",
    "header_order": "Declared columns violate the configured header order.",
    "field_count": "The data record has a different field count from the header.",
    "null_not_allowed": "An empty cell is forbidden for this column.",
    "invalid_integer": "A non-null cell fails integer parsing.",
    "invalid_decimal": "A non-null cell fails finite decimal parsing.",
    "invalid_boolean": "A cell does not match a declared boolean spelling.",
    "invalid_date": "A cell fails YYYY-MM-DD calendar date parsing.",
    "below_minimum": "A typed value is below the inclusive lower bound.",
    "above_maximum": "A typed value exceeds the inclusive upper bound.",
    "too_short": "Text is shorter than the declared minimum length.",
    "too_long": "Text exceeds the declared maximum length.",
    "empty_after_trim": "Text has no non-whitespace characters.",
    "not_in_enum": "A typed value is absent from the declared enumeration.",
    "duplicate_key": "A typed primary key repeats an earlier key in this file.",
    "duplicate_value": "A non-null typed value violates column uniqueness.",
    "too_few_rows": "The completed file has too few data records.",
    "too_many_rows": "The completed file has too many data records.",
}


@dataclass(frozen=True)
class BooleanFormat:
    true_values: tuple[str, ...] = ("true",)
    false_values: tuple[str, ...] = ("false",)
    case_sensitive: bool = True


@dataclass(frozen=True)
class Constraints:
    minimum: int | Decimal | date | None = None
    maximum: int | Decimal | date | None = None
    min_length: int | None = None
    max_length: int | None = None
    nonempty_after_trim: bool = False
    enumeration: tuple[Scalar, ...] | None = None
    unique: bool = False


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType
    required: bool
    nullable: bool
    whitespace: Literal["preserve", "trim"] = "preserve"
    constraints: Constraints = Constraints()
    boolean_format: BooleanFormat = BooleanFormat()
    description: str | None = None


@dataclass(frozen=True)
class CsvConventions:
    delimiter: str = ","
    quotechar: str = '"'
    allow_extra_columns: bool = False
    enforce_column_order: bool = False


@dataclass(frozen=True)
class DatasetSchema:
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    csv: CsvConventions = CsvConventions()
    min_rows: int = 0
    max_rows: int | None = None
    title: str | None = None

    @property
    def by_name(self) -> dict[str, Column]:
        return {column.name: column for column in self.columns}


@dataclass(frozen=True)
class Location:
    file: str
    record: int | None = None
    physical_line_start: int | None = None
    physical_line_end: int | None = None
    column: str | None = None
    column_index: int | None = None


@dataclass(frozen=True)
class Diagnostic:
    code: ErrorCode
    location: Location
    message: str
    first_occurrence: Location | None = None


@dataclass(frozen=True)
class CsvRecord:
    number: int
    physical_line_start: int
    physical_line_end: int
    cells: tuple[str, ...]

    def location(self, file: str, column: str | None = None, index: int | None = None) -> Location:
        return Location(
            file=file,
            record=self.number,
            physical_line_start=self.physical_line_start,
            physical_line_end=self.physical_line_end,
            column=column,
            column_index=index,
        )


@dataclass(frozen=True)
class ColumnStats:
    name: str
    present: bool
    cells_examined: int
    null_cells: int
    invalid_cells: int
    parsed_nonnull_cells: int = 0
    minimum_value: Scalar | None = None
    maximum_value: Scalar | None = None
    shortest_length: int | None = None
    longest_length: int | None = None
    true_cells: int = 0
    false_cells: int = 0


@dataclass(frozen=True)
class BatchReport:
    reports: tuple["ValidationReport", ...]

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.reports)

    @property
    def operational_error(self) -> bool:
        return any(report.operational_error for report in self.reports)

    @property
    def accepted(self) -> int:
        return sum(report.accepted for report in self.reports)

    @property
    def rejected(self) -> int:
        return sum(report.rejected for report in self.reports)

    @property
    def error_count(self) -> int:
        return sum(report.error_count for report in self.reports)


@dataclass(frozen=True)
class ValidationOptions:
    strict: bool = False
    max_errors: int | None = None
    max_record_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_errors is not None and (type(self.max_errors) is not int or self.max_errors < 0):
            raise ValueError("--max-errors must be a nonnegative integer")
        if type(self.max_record_bytes) is not int or not 1 <= self.max_record_bytes < sys.maxsize:
            raise ValueError(f"--max-record-bytes must be between 1 and {sys.maxsize - 1}")


@dataclass(frozen=True)
class ValidationReport:
    file: str
    schema_file: str
    accepted: int
    rejected: int
    header: tuple[str, ...] | None
    complete: bool
    stopped_early: bool
    operational_error: bool
    error_counts: dict[str, int]
    errors: tuple[Diagnostic, ...]
    columns: tuple[ColumnStats, ...] = ()

    @property
    def records_examined(self) -> int:
        return self.accepted + self.rejected

    @property
    def error_count(self) -> int:
        return sum(self.error_counts.values())

    @property
    def omitted_errors(self) -> int:
        return self.error_count - len(self.errors)

    @property
    def ok(self) -> bool:
        return self.complete and self.error_count == 0


@dataclass
class ErrorCollector:
    limit: int | None
    counts: dict[str, int] = field(default_factory=dict)
    details: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> None:
        self.counts[diagnostic.code] = self.counts.get(diagnostic.code, 0) + 1
        if self.limit is None or len(self.details) < self.limit:
            self.details.append(diagnostic)
