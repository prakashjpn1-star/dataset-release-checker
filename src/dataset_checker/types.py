"""Parse cell values without conflating empty CSV cells with text literals."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import BooleanFormat, Column, ColumnType, Constraints, ErrorCode, Scalar

_INTEGER = re.compile(r"[+-]?[0-9]+")
_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class CellValueError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ParsedCell:
    value: Scalar | None
    text: str
    is_null: bool


def parse_integer(text: str) -> int:
    if not _INTEGER.fullmatch(text):
        raise CellValueError("invalid_integer", "expected a base-10 integer without separators")
    try:
        return int(text)
    except ValueError as error:
        raise CellValueError("invalid_integer", "integer exceeds the runtime digit limit") from error


def parse_decimal(text: str) -> Decimal:
    if not _DECIMAL.fullmatch(text):
        raise CellValueError("invalid_decimal", "expected a finite decimal with optional exponent")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise CellValueError("invalid_decimal", "decimal exceeds the supported numeric range") from error
    if not value.is_finite():
        raise CellValueError("invalid_decimal", "decimal must be finite")
    return value


def parse_date(text: str) -> date:
    if not _DATE.fullmatch(text):
        raise CellValueError("invalid_date", "expected a date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise CellValueError("invalid_date", "date does not exist in the Gregorian calendar") from error


def boolean_key(text: str, format: BooleanFormat) -> str:
    return text if format.case_sensitive else text.casefold()


def parse_boolean(text: str, format: BooleanFormat) -> bool:
    candidate = boolean_key(text, format)
    if candidate in {boolean_key(value, format) for value in format.true_values}:
        return True
    if candidate in {boolean_key(value, format) for value in format.false_values}:
        return False
    raise CellValueError("invalid_boolean", "value is outside the schema's boolean spellings")


def parse_scalar(text: str, kind: ColumnType, format: BooleanFormat = BooleanFormat()) -> Scalar:
    if kind == "string":
        return text
    if kind == "integer":
        return parse_integer(text)
    if kind == "decimal":
        return parse_decimal(text)
    if kind == "boolean":
        return parse_boolean(text, format)
    if kind == "date":
        return parse_date(text)
    raise ValueError(f"unsupported column type {kind!r}")


def parse_cell(raw: str, column: Column) -> ParsedCell:
    # Only the decoded empty field is null, before any whitespace normalization.
    if raw == "":
        if not column.nullable:
            raise CellValueError("null_not_allowed", "empty cell is forbidden by nullable=false")
        return ParsedCell(None, "", True)
    text = raw.strip() if column.whitespace == "trim" else raw
    return ParsedCell(parse_scalar(text, column.type, column.boolean_format), text, False)


def constraint_failures(value: Scalar, constraints: Constraints) -> tuple[tuple[ErrorCode, str], ...]:
    problems = []
    if constraints.minimum is not None and value < constraints.minimum:
        problems.append(("below_minimum", "value is below the schema minimum"))
    if constraints.maximum is not None and value > constraints.maximum:
        problems.append(("above_maximum", "value exceeds the schema maximum"))
    if isinstance(value, str):
        if constraints.min_length is not None and len(value) < constraints.min_length:
            problems.append(("too_short", "text is shorter than min_length"))
        if constraints.max_length is not None and len(value) > constraints.max_length:
            problems.append(("too_long", "text is longer than max_length"))
        if constraints.nonempty_after_trim and not value.strip():
            problems.append(("empty_after_trim", "text must contain a non-whitespace character"))
    if constraints.enumeration is not None and value not in constraints.enumeration:
        problems.append(("not_in_enum", "value is outside the schema enumeration"))
    return tuple(problems)


def schema_scalar(value: Any, kind: ColumnType, format: BooleanFormat) -> Scalar:
    """Parse typed JSON constraint values while preserving exact decimal tokens."""
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError("string constraints require JSON strings")
        return value
    if kind == "boolean":
        if type(value) is not bool:
            raise ValueError("boolean enum values require JSON true or false")
        return value
    if kind == "integer":
        if type(value) is not int:
            raise ValueError("integer constraints require JSON integers")
        return value
    if kind == "decimal":
        if type(value) not in {int, Decimal, str}:
            raise ValueError("decimal constraints require JSON numbers or decimal strings")
        return parse_decimal(str(value))
    if kind == "date":
        if not isinstance(value, str):
            raise ValueError("date constraints require YYYY-MM-DD strings")
        return parse_date(value)
    raise ValueError(f"unsupported column type {kind!r}")


def scalar_json(value: Scalar | None) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value
