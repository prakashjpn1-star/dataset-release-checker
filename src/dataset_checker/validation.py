"""Reconcile headers, validate cells, and enforce key constraints."""

from collections.abc import Iterable, Iterator
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path

from .csv_reader import read_csv
from .models import (
    Column,
    ColumnStats,
    BatchReport,
    CsvRecord,
    DatasetSchema,
    Diagnostic,
    ErrorCollector,
    Location,
    Scalar,
    ValidationOptions,
    ValidationReport,
)
from .types import CellValueError, constraint_failures, parse_cell

_OPERATIONAL_CODES = frozenset({"file_unreadable", "invalid_encoding"})


@dataclass
class _CellStats:
    examined: int = 0
    nulls: int = 0
    invalid: int = 0
    parsed_nonnull: int = 0
    minimum: Scalar | None = None
    maximum: Scalar | None = None
    shortest: int | None = None
    longest: int | None = None
    true_count: int = 0
    false_count: int = 0

    def observe(self, value: Scalar) -> None:
        self.parsed_nonnull += 1
        if isinstance(value, str):
            length = len(value)
            self.shortest = length if self.shortest is None else min(self.shortest, length)
            self.longest = length if self.longest is None else max(self.longest, length)
        elif type(value) is bool:
            if value:
                self.true_count += 1
            else:
                self.false_count += 1
        else:
            self.minimum = value if self.minimum is None else min(self.minimum, value)
            self.maximum = value if self.maximum is None else max(self.maximum, value)

    def snapshot(self, name: str, present: bool) -> ColumnStats:
        return ColumnStats(
            name=name,
            present=present,
            cells_examined=self.examined,
            null_cells=self.nulls,
            invalid_cells=self.invalid,
            parsed_nonnull_cells=self.parsed_nonnull,
            minimum_value=self.minimum,
            maximum_value=self.maximum,
            shortest_length=self.shortest,
            longest_length=self.longest,
            true_cells=self.true_count,
            false_cells=self.false_count,
        )


@dataclass
class _State:
    schema: DatasetSchema
    file: str
    options: ValidationOptions
    collector: ErrorCollector
    header: CsvRecord | None = None
    bindings: tuple[tuple[int, Column], ...] = ()
    header_errors: bool = False
    accepted: int = 0
    rejected: int = 0
    complete: bool = False
    stopped: bool = False
    operational: bool = False
    key_locations: dict[tuple[Scalar, ...], Location] = field(default_factory=dict)
    unique_locations: dict[str, dict[Scalar, Location]] = field(default_factory=dict)
    stats: dict[str, _CellStats] = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return self.accepted + self.rejected

    def add(self, diagnostic: Diagnostic) -> None:
        self.collector.add(diagnostic)
        self.operational |= diagnostic.code in _OPERATIONAL_CODES


def _check_header(state: _State, record: CsvRecord) -> None:
    state.header = record
    names = record.cells
    by_name = state.schema.by_name
    seen = {}
    for index, name in enumerate(names, start=1):
        location = record.location(state.file, name or None, index)
        if not name:
            state.add(Diagnostic("empty_header", location, "header name is empty"))
        elif not name.isprintable() or name.strip() != name:
            state.add(Diagnostic("invalid_header", location, "header must be printable with no surrounding whitespace"))
        elif name in seen:
            state.add(Diagnostic("duplicate_header", location, "header name appears more than once", seen[name]))
        seen.setdefault(name, location)
        if name and name not in by_name and not state.schema.csv.allow_extra_columns:
            state.add(Diagnostic("unexpected_column", location, "column is outside the published schema"))

    if not names:
        state.add(Diagnostic("empty_header", record.location(state.file), "header record has no fields"))
    for column in state.schema.columns:
        if column.required and column.name not in seen:
            state.add(Diagnostic(
                "missing_column", record.location(state.file, column.name),
                "required column is missing from the CSV header",
            ))
        state.stats[column.name] = _CellStats()
        if column.constraints.unique:
            state.unique_locations[column.name] = {}

    if state.schema.csv.enforce_column_order:
        actual = tuple(name for name in names if name in by_name)
        expected = tuple(column.name for column in state.schema.columns if column.name in seen)
        if actual != expected:
            state.add(Diagnostic("header_order", record.location(state.file), "schema columns occur in the wrong order"))

    state.header_errors = bool(state.collector.counts)
    if not state.header_errors:
        state.bindings = tuple((index, by_name[name]) for index, name in enumerate(names) if name in by_name)


def _cell_values(state: _State, record: CsvRecord) -> tuple[dict[str, Scalar | None], set[str]]:
    values = {}
    invalid = set()
    for index, column in state.bindings:
        stats = state.stats[column.name]
        stats.examined += 1
        if record.cells[index] == "":
            stats.nulls += 1
        location = record.location(state.file, column.name, index + 1)
        try:
            parsed = parse_cell(record.cells[index], column)
        except CellValueError as error:
            state.add(Diagnostic(error.code, location, str(error)))
            stats.invalid += 1
            invalid.add(column.name)
            continue
        values[column.name] = parsed.value
        if parsed.is_null:
            continue
        stats.observe(parsed.value)
        problems = constraint_failures(parsed.value, column.constraints)
        for code, message in problems:
            state.add(Diagnostic(code, location, message))
        if problems:
            stats.invalid += 1
            invalid.add(column.name)
    return values, invalid


def _check_keys(
    state: _State,
    record: CsvRecord,
    values: dict[str, Scalar | None],
    invalid: set[str],
) -> bool:
    failed = False
    for index, column in state.bindings:
        if not column.constraints.unique or column.name in invalid or values.get(column.name) is None:
            continue
        value = values[column.name]
        location = record.location(state.file, column.name, index + 1)
        first = state.unique_locations[column.name].get(value)
        if first is not None:
            state.add(Diagnostic("duplicate_value", location, "non-null value violates column uniqueness", first))
            state.stats[column.name].invalid += 1
            failed = True
        else:
            state.unique_locations[column.name][value] = location

    key = state.schema.primary_key
    if key and not invalid.intersection(key) and all(values.get(name) is not None for name in key):
        composite = tuple(values[name] for name in key)
        location = record.location(state.file, key[0], record_column_index(state, key[0]))
        first = state.key_locations.get(composite)
        if first is not None:
            state.add(Diagnostic("duplicate_key", location, "primary key repeats an earlier typed key", first))
            # A key diagnostic counts the affected leading cell once in cell statistics.
            if not state.schema.by_name[key[0]].constraints.unique:
                state.stats[key[0]].invalid += 1
            failed = True
        else:
            state.key_locations[composite] = location
    return failed


def record_column_index(state: _State, name: str) -> int:
    assert state.header is not None
    return state.header.cells.index(name) + 1


def _check_row(state: _State, record: CsvRecord) -> None:
    assert state.header is not None
    if len(record.cells) != len(state.header.cells):
        state.add(Diagnostic(
            "field_count", record.location(state.file),
            f"expected {len(state.header.cells)} fields but found {len(record.cells)}",
        ))
        state.rejected += 1
        return
    if state.header_errors:
        # An invalid header prevents assigning cells to unambiguous schema columns.
        state.rejected += 1
        return
    values, invalid = _cell_values(state, record)
    duplicate = _check_keys(state, record, values, invalid)
    if invalid or duplicate:
        state.rejected += 1
    else:
        state.accepted += 1


def _consume(state: _State, records: Iterator[CsvRecord | Diagnostic]) -> None:
    for item in records:
        if isinstance(item, Diagnostic):
            diagnostic = item
            if state.header is not None and item.location.column_index is not None:
                index = item.location.column_index
                if index <= len(state.header.cells):
                    diagnostic = replace(item, location=replace(item.location, column=state.header.cells[index - 1]))
            state.add(diagnostic)
            if item.code != "file_unreadable" and item.location.record not in (None, 1):
                state.rejected += 1
            return
        if state.header is None:
            _check_header(state, item)
            if state.options.strict and state.header_errors:
                state.stopped = True
                return
            continue
        previous_errors = sum(state.collector.counts.values())
        _check_row(state, item)
        if state.options.strict and sum(state.collector.counts.values()) > previous_errors:
            state.stopped = True
            return
    state.complete = True


def _finalize(state: _State) -> None:
    if state.header is None and not state.collector.counts:
        state.add(Diagnostic("empty_file", Location(state.file), "CSV must contain a header record"))
    if not state.complete or state.header is None:
        return
    if state.row_count < state.schema.min_rows:
        state.add(Diagnostic("too_few_rows", Location(state.file), f"dataset requires at least {state.schema.min_rows} data records"))
    if state.schema.max_rows is not None and state.row_count > state.schema.max_rows:
        state.add(Diagnostic("too_many_rows", Location(state.file), f"dataset allows at most {state.schema.max_rows} data records"))


def validate_file(
    path: Path,
    schema: DatasetSchema,
    *,
    schema_file: str = "<in-memory-schema>",
    options: ValidationOptions = ValidationOptions(),
) -> ValidationReport:
    state = _State(schema, str(path), options, ErrorCollector(options.max_errors))
    with closing(read_csv(path, schema.csv, max_record_bytes=options.max_record_bytes)) as records:
        _consume(state, records)
    _finalize(state)
    present = set(state.header.cells) if state.header is not None else set()
    columns = []
    for column in schema.columns:
        stats = state.stats.get(column.name, _CellStats())
        columns.append(stats.snapshot(column.name, column.name in present))
    return ValidationReport(
        file=str(path),
        schema_file=schema_file,
        accepted=state.accepted,
        rejected=state.rejected,
        header=state.header.cells if state.header is not None else None,
        complete=state.complete,
        stopped_early=state.stopped,
        operational_error=state.operational,
        error_counts=dict(sorted(state.collector.counts.items())),
        errors=tuple(state.collector.details),
        columns=tuple(columns),
    )


def validate_files(
    paths: Iterable[Path],
    schema: DatasetSchema,
    *,
    schema_file: str = "<in-memory-schema>",
    options: ValidationOptions = ValidationOptions(),
) -> BatchReport:
    """Apply the same contract independently to each supplied release file."""
    reports = []
    for path in paths:
        report = validate_file(path, schema, schema_file=schema_file, options=options)
        reports.append(report)
        if options.strict and not report.ok:
            break
    return BatchReport(tuple(reports))
