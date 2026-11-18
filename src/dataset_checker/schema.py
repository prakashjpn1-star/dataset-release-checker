"""Load the versioned dataset schema and reject ambiguous definitions."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    COLUMN_TYPES,
    BooleanFormat,
    Column,
    Constraints,
    CsvConventions,
    DatasetSchema,
    Scalar,
)
from .types import boolean_key, constraint_failures, parse_decimal, scalar_json, schema_scalar

SCHEMA_VERSION = 1
_TOP_FIELDS = {"version", "title", "columns", "primary_key", "csv", "min_rows", "max_rows"}
_COLUMN_FIELDS = {
    "name", "type", "required", "nullable", "whitespace", "constraints", "boolean", "description",
}
_CONSTRAINT_FIELDS = {
    "minimum", "maximum", "min_length", "max_length", "nonempty_after_trim", "enum", "unique",
}


class SchemaError(ValueError):
    """A schema cannot be read or used as a validation contract."""


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{location} must be an object")
    return value


def _array(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaError(f"{location} must be an array")
    return value


def _known_fields(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data).difference(allowed))
    if unknown:
        raise SchemaError(f"{location} contains unknown fields {', '.join(unknown)}")


def _required(data: dict[str, Any], key: str, location: str) -> Any:
    if key not in data:
        raise SchemaError(f"{location} is missing required field {key!r}")
    return data[key]


def _bool(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise SchemaError(f"{location} must be a boolean")
    return value


def _nonnegative(value: Any, location: str) -> int:
    if type(value) is not int or value < 0:
        raise SchemaError(f"{location} must be a nonnegative integer")
    return value


def _name(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or not value.isprintable():
        raise SchemaError(f"{location} must be a printable nonempty name without surrounding whitespace")
    return value


def _optional_description(data: dict[str, Any], key: str, location: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{location}.{key} must be a nonempty string")
    return value


def _spellings(value: Any, location: str) -> tuple[str, ...]:
    items = _array(value, location)
    if not items:
        raise SchemaError(f"{location} must contain at least one spelling")
    result = tuple(_name(item, location) for item in items)
    if len(set(result)) != len(result):
        raise SchemaError(f"{location} contains duplicate spellings")
    return result


def _boolean_format(value: Any, location: str) -> BooleanFormat:
    data = _object(value, location)
    _known_fields(data, {"true_values", "false_values", "case_sensitive"}, location)
    true_values = _spellings(_required(data, "true_values", location), f"{location}.true_values")
    false_values = _spellings(_required(data, "false_values", location), f"{location}.false_values")
    sensitive = _bool(data.get("case_sensitive", True), f"{location}.case_sensitive")
    format = BooleanFormat(true_values, false_values, sensitive)
    true_keys = [boolean_key(item, format) for item in true_values]
    false_keys = [boolean_key(item, format) for item in false_values]
    if len(set(true_keys)) != len(true_keys) or len(set(false_keys)) != len(false_keys):
        raise SchemaError(f"{location} contains spellings that collide under case folding")
    if set(true_keys).intersection(false_keys):
        raise SchemaError(f"{location} assigns the same spelling to true and false")
    return format


def _csv_conventions(value: Any) -> CsvConventions:
    data = _object(value, "csv")
    _known_fields(data, {"delimiter", "quotechar", "allow_extra_columns", "enforce_column_order"}, "csv")
    characters = {}
    for field, default in (("delimiter", ","), ("quotechar", '"')):
        value = data.get(field, default)
        if not isinstance(value, str) or len(value) != 1 or value in "\r\n\0":
            raise SchemaError(f"csv.{field} must be one character other than a newline or NUL")
        if field == "delimiter" and not value.isprintable() and value != "\t":
            raise SchemaError("csv.delimiter must be printable or a tab")
        if field == "quotechar" and not value.isprintable():
            raise SchemaError("csv.quotechar must be printable")
        characters[field] = value
    if characters["delimiter"] == characters["quotechar"]:
        raise SchemaError("csv.delimiter and csv.quotechar must differ")
    return CsvConventions(
        **characters,
        allow_extra_columns=_bool(data.get("allow_extra_columns", False), "csv.allow_extra_columns"),
        enforce_column_order=_bool(data.get("enforce_column_order", False), "csv.enforce_column_order"),
    )


def _bound(data: dict[str, Any], key: str, column: Column, location: str) -> Scalar | None:
    if key not in data:
        return None
    try:
        return schema_scalar(data[key], column.type, column.boolean_format)
    except ValueError as error:
        raise SchemaError(f"{location}.{key}: {error}") from error


def _constraints(value: Any, column: Column, location: str) -> Constraints:
    data = _object(value, location)
    _known_fields(data, _CONSTRAINT_FIELDS, location)
    length_fields = {"min_length", "max_length", "nonempty_after_trim"}
    if column.type != "string" and set(data).intersection(length_fields):
        raise SchemaError(f"{location} length and trimming constraints require a string column")
    if column.type not in {"integer", "decimal", "date"} and set(data).intersection({"minimum", "maximum"}):
        raise SchemaError(f"{location} ranges require an integer, decimal, or date column")

    minimum = _bound(data, "minimum", column, location)
    maximum = _bound(data, "maximum", column, location)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise SchemaError(f"{location}.minimum exceeds maximum")
    minimum_length = None
    maximum_length = None
    if "min_length" in data:
        minimum_length = _nonnegative(data["min_length"], f"{location}.min_length")
    if "max_length" in data:
        maximum_length = _nonnegative(data["max_length"], f"{location}.max_length")
    if minimum_length is not None and maximum_length is not None and minimum_length > maximum_length:
        raise SchemaError(f"{location}.min_length exceeds max_length")
    nonempty = _bool(data.get("nonempty_after_trim", False), f"{location}.nonempty_after_trim")
    if nonempty and maximum_length == 0:
        raise SchemaError(f"{location} cannot require nonempty text with max_length zero")
    result = Constraints(
        minimum=minimum,
        maximum=maximum,
        min_length=minimum_length,
        max_length=maximum_length,
        nonempty_after_trim=nonempty,
        unique=_bool(data.get("unique", False), f"{location}.unique"),
    )
    if "enum" not in data:
        return result

    values = _array(data["enum"], f"{location}.enum")
    if not values:
        raise SchemaError(f"{location}.enum must contain at least one value")
    parsed = []
    for index, value in enumerate(values):
        try:
            scalar = schema_scalar(value, column.type, column.boolean_format)
        except ValueError as error:
            raise SchemaError(f"{location}.enum[{index}]: {error}") from error
        if scalar in parsed:
            raise SchemaError(f"{location}.enum contains duplicate typed values")
        if column.type == "string" and column.whitespace == "trim" and scalar != scalar.strip():
            raise SchemaError(f"{location}.enum contains text inconsistent with whitespace=trim")
        if column.type == "string" and column.whitespace == "preserve" and scalar == "":
            raise SchemaError(f"{location}.enum contains empty text, which represents null in CSV")
        if constraint_failures(scalar, result):
            raise SchemaError(f"{location}.enum[{index}] contradicts the other constraints")
        parsed.append(scalar)
    return replace(result, enumeration=tuple(parsed))


def _column(value: Any, index: int) -> Column:
    location = f"columns[{index}]"
    data = _object(value, location)
    _known_fields(data, _COLUMN_FIELDS, location)
    name = _name(_required(data, "name", location), f"{location}.name")
    kind = _required(data, "type", location)
    if not isinstance(kind, str) or kind not in COLUMN_TYPES:
        raise SchemaError(f"{location}.type must be one of {', '.join(COLUMN_TYPES)}")
    required = _bool(_required(data, "required", location), f"{location}.required")
    nullable = _bool(_required(data, "nullable", location), f"{location}.nullable")
    whitespace = data.get("whitespace", "preserve")
    if whitespace not in ("preserve", "trim"):
        raise SchemaError(f"{location}.whitespace must be preserve or trim")
    if kind != "boolean" and "boolean" in data:
        raise SchemaError(f"{location}.boolean requires a boolean column")
    if kind == "boolean" and "boolean" not in data:
        raise SchemaError(f"{location}.boolean must define accepted true and false spellings")
    format = _boolean_format(data["boolean"], f"{location}.boolean") if kind == "boolean" else BooleanFormat()
    column = Column(
        name=name,
        type=kind,
        required=required,
        nullable=nullable,
        whitespace=whitespace,
        boolean_format=format,
        description=_optional_description(data, "description", location),
    )
    return replace(column, constraints=_constraints(data.get("constraints", {}), column, f"{location}.constraints"))


def _primary_key(value: Any, columns: tuple[Column, ...]) -> tuple[str, ...]:
    names = _array(value, "primary_key")
    by_name = {column.name: column for column in columns}
    key = []
    for item in names:
        name = _name(item, "primary_key entry")
        if name not in by_name:
            raise SchemaError(f"primary_key references nonexistent column {name!r}")
        if name in key:
            raise SchemaError(f"primary_key repeats column {name!r}")
        if not by_name[name].required or by_name[name].nullable:
            raise SchemaError(f"primary_key column {name!r} must have required=true and nullable=false")
        key.append(name)
    return tuple(key)


def parse_schema(value: Any) -> DatasetSchema:
    data = _object(value, "schema")
    _known_fields(data, _TOP_FIELDS, "schema")
    version = _required(data, "version", "schema")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SchemaError(f"unsupported schema version {version!r}. Expected {SCHEMA_VERSION}")
    columns = tuple(_column(item, index) for index, item in enumerate(
        _array(_required(data, "columns", "schema"), "columns")
    ))
    if not columns:
        raise SchemaError("columns must describe at least one column")
    names = [column.name for column in columns]
    if len(names) != len(set(names)):
        raise SchemaError("columns contains duplicate column names")
    minimum = _nonnegative(data.get("min_rows", 0), "min_rows")
    maximum = _nonnegative(data["max_rows"], "max_rows") if "max_rows" in data else None
    if maximum is not None and minimum > maximum:
        raise SchemaError("min_rows exceeds max_rows")
    return DatasetSchema(
        columns=columns,
        primary_key=_primary_key(data.get("primary_key", []), columns),
        csv=_csv_conventions(data.get("csv", {})),
        min_rows=minimum,
        max_rows=maximum,
        title=_optional_description(data, "title", "schema"),
    )


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON object field {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise SchemaError(f"nonstandard JSON numeric constant {value!r}")


def load_schema(path: Path) -> DatasetSchema:
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(
                stream,
                parse_float=parse_decimal,
                parse_constant=_invalid_constant,
                object_pairs_hook=_unique_keys,
            )
        return parse_schema(value)
    except OSError as error:
        raise SchemaError(f"cannot read schema {str(path)!r}: {error.strerror or error}") from error
    except (ValueError, RecursionError) as error:
        raise SchemaError(f"invalid schema {str(path)!r}: {error}") from error


def schema_document(schema: DatasetSchema) -> dict[str, Any]:
    """Produce a normalized schema that can be loaded again without losing precision."""
    columns = []
    for column in schema.columns:
        rules = column.constraints
        constraints = {"unique": rules.unique}
        for key in ("minimum", "maximum", "min_length", "max_length"):
            value = getattr(rules, key)
            if value is not None:
                constraints[key] = scalar_json(value)
        if column.type == "string":
            constraints["nonempty_after_trim"] = rules.nonempty_after_trim
        if rules.enumeration is not None:
            constraints["enum"] = [scalar_json(value) for value in rules.enumeration]
        item = {
            "name": column.name,
            "type": column.type,
            "required": column.required,
            "nullable": column.nullable,
            "whitespace": column.whitespace,
            "constraints": constraints,
        }
        if column.description is not None:
            item["description"] = column.description
        if column.type == "boolean":
            item["boolean"] = {
                "true_values": list(column.boolean_format.true_values),
                "false_values": list(column.boolean_format.false_values),
                "case_sensitive": column.boolean_format.case_sensitive,
            }
        columns.append(item)
    result = {
        "version": SCHEMA_VERSION,
        "columns": columns,
        "primary_key": list(schema.primary_key),
        "min_rows": schema.min_rows,
        "csv": {
            "delimiter": schema.csv.delimiter,
            "quotechar": schema.csv.quotechar,
            "allow_extra_columns": schema.csv.allow_extra_columns,
            "enforce_column_order": schema.csv.enforce_column_order,
        },
    }
    if schema.title is not None:
        result["title"] = schema.title
    if schema.max_rows is not None:
        result["max_rows"] = schema.max_rows
    return result
