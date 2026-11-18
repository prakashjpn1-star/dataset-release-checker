"""Produce readable summaries and stable machine-readable report contracts."""

import json
from dataclasses import asdict
from typing import Any, Literal

from .comparison import SchemaComparison
from .models import ERROR_DESCRIPTIONS, BatchReport, Column, ColumnStats, DatasetSchema, Diagnostic, Location, ValidationReport
from .schema import schema_document
from .types import scalar_json

ReportFormat = Literal["text", "json"]
REPORT_VERSION = 1


def render_codes(format: ReportFormat) -> str:
    codes = dict(sorted(ERROR_DESCRIPTIONS.items()))
    if format == "json":
        return _json({"report_version": REPORT_VERSION, "command": "codes", "codes": codes})
    return "\n".join(f"{code}  {description}" for code, description in codes.items())


def _display(value: str) -> str:
    return value if value.isprintable() else repr(value)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False)


def _location(location: Location) -> dict[str, Any]:
    return asdict(location)


def _diagnostic(error: Diagnostic) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        **_location(error.location),
        "first_occurrence": _location(error.first_occurrence) if error.first_occurrence is not None else None,
    }


def _column_stats(column: ColumnStats) -> dict[str, Any]:
    data = asdict(column)
    data["minimum_value"] = scalar_json(column.minimum_value)
    data["maximum_value"] = scalar_json(column.maximum_value)
    return data


def report_document(report: ValidationReport) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "command": "validate",
        "file": report.file,
        "schema": report.schema_file,
        "ok": report.ok,
        "complete": report.complete,
        "stopped_early": report.stopped_early,
        "operational_error": report.operational_error,
        "row_numbering": "logical CSV records, header is record 1",
        "summary": {
            "records_examined": report.records_examined,
            "accepted": report.accepted,
            "rejected": report.rejected,
            "errors": report.error_count,
            "omitted_errors": report.omitted_errors,
        },
        "header": list(report.header) if report.header is not None else None,
        "error_counts": report.error_counts,
        "columns": [_column_stats(column) for column in report.columns],
        "errors": [_diagnostic(error) for error in report.errors],
    }


def location_text(location: Location) -> str:
    parts = [_display(location.file)]
    if location.record is not None:
        parts.append(f"record {location.record}")
    if location.column is not None:
        column = f"column {location.column!r}"
        if location.column_index is not None:
            column += f" (index {location.column_index})"
        parts.append(column)
    elif location.column_index is not None:
        parts.append(f"column index {location.column_index}")
    if location.physical_line_start is not None:
        start = location.physical_line_start
        end = location.physical_line_end
        parts.append(f"physical line {start}" if end in (None, start) else f"physical lines {start}–{end}")
    return ", ".join(parts)


def _profile_lines(report: ValidationReport) -> list[str]:
    lines = ["Column profiles include typed values from examined rows, including constraint failures."]
    for column in report.columns:
        state = "present" if column.present else "absent"
        lines.append(
            f"  {column.name} ({state}), {column.cells_examined} cells, "
            f"{column.null_cells} null, {column.invalid_cells} invalid"
        )
        if column.minimum_value is not None:
            lines.append(
                f"    Observed range {scalar_json(column.minimum_value)} to {scalar_json(column.maximum_value)}"
            )
        if column.shortest_length is not None:
            lines.append(f"    Text lengths {column.shortest_length} to {column.longest_length}")
        if column.true_cells or column.false_cells:
            lines.append(f"    {column.true_cells} true, {column.false_cells} false")
    return lines


def render_validation(report: ValidationReport, format: ReportFormat, *, profile: bool = False) -> str:
    if format == "json":
        return _json(report_document(report))
    status = "PASS" if report.ok else "FAIL"
    lines = [
        f"{status} {_display(report.file)}",
        f"{report.accepted} accepted, {report.rejected} rejected, {report.error_count} errors.",
        "Row references use logical CSV records. The header is record 1.",
    ]
    if not report.complete:
        lines.append("Inspection ended before EOF. Totals cover the examined portion.")
    for error in report.errors:
        lines.append(f"  [{error.code}] {location_text(error.location)}")
        lines.append(f"    {_display(error.message)}")
        if error.first_occurrence is not None:
            lines.append(f"    First occurrence at {location_text(error.first_occurrence)}")
    if report.omitted_errors:
        lines.append(f"{report.omitted_errors} error details omitted. Error totals include them.")
    if report.error_counts:
        lines.append("Error counts " + ", ".join(f"{code}={count}" for code, count in report.error_counts.items()))
    if profile:
        lines.extend(_profile_lines(report))
    return "\n".join(lines)


def render_batch(batch: BatchReport, format: ReportFormat, *, profile: bool = False) -> str:
    if len(batch.reports) == 1:
        return render_validation(batch.reports[0], format, profile=profile)
    if format == "json":
        return _json({
            "report_version": REPORT_VERSION,
            "command": "validate",
            "ok": batch.ok,
            "operational_error": batch.operational_error,
            "summary": {
                "files_examined": len(batch.reports),
                "accepted": batch.accepted,
                "rejected": batch.rejected,
                "errors": batch.error_count,
            },
            "files": [report_document(report) for report in batch.reports],
        })
    lines = [
        f"{len(batch.reports)} files examined. {batch.accepted} accepted, {batch.rejected} rejected, {batch.error_count} errors.",
    ]
    for report in batch.reports:
        lines.append(render_validation(report, "text", profile=profile))
    return "\n\n".join(lines)


def _constraint_text(column: Column) -> str:
    rules = column.constraints
    parts = []
    for name in ("minimum", "maximum", "min_length", "max_length"):
        value = getattr(rules, name)
        if value is not None:
            parts.append(f"{name}={scalar_json(value)}")
    if rules.nonempty_after_trim:
        parts.append("nonempty_after_trim")
    if rules.unique:
        parts.append("unique")
    if rules.enumeration is not None:
        parts.append("enum=" + json.dumps([scalar_json(value) for value in rules.enumeration], ensure_ascii=True))
    return ", ".join(parts) if parts else "none"


def render_schema(schema: DatasetSchema, format: ReportFormat) -> str:
    if format == "json":
        return _json(schema_document(schema))
    lines = [schema.title or "Dataset schema", f"{len(schema.columns)} columns."]
    for column in schema.columns:
        lines.append(
            f"  {column.name} ({column.type}), required={str(column.required).lower()}, "
            f"nullable={str(column.nullable).lower()}, whitespace={column.whitespace}"
        )
        lines.append(f"    Constraints {_constraint_text(column)}")
        if column.type == "boolean":
            format_rules = column.boolean_format
            lines.append(f"    True {format_rules.true_values!r}, false {format_rules.false_values!r}")
        if column.description:
            lines.append(f"    {_display(column.description)}")
    if schema.primary_key:
        lines.append("Primary key " + ", ".join(schema.primary_key))
    return "\n".join(lines)


def render_comparison(result: SchemaComparison, before: str, after: str, format: ReportFormat) -> str:
    if format == "json":
        return _json({
            "report_version": REPORT_VERSION,
            "command": "compare",
            "before": before,
            "after": after,
            "compatible": result.compatible,
            "summary": result.summary,
            "changes": [asdict(change) for change in result.changes],
        })
    summary = result.summary
    lines = [
        f"{summary['breaking']} breaking, {summary['compatible']} compatible, {summary['metadata']} metadata changes.",
        "Compatibility describes validation-rule changes that require release review.",
    ]
    if not result.changes:
        lines.append("Schema contracts agree.")
    for change in result.changes:
        target = f"column {change.column!r}" if change.column is not None else "dataset"
        lines.append(f"  [{change.impact}] {target} [{change.code}] {_display(change.message)}")
    return "\n".join(lines)
