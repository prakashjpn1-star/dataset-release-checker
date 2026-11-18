"""Compare published schemas for changes to their CSV validation contracts."""

from dataclasses import dataclass
from typing import Literal

from .models import Column, DatasetSchema
from .types import boolean_key

Impact = Literal["breaking", "compatible", "metadata"]


@dataclass(frozen=True)
class SchemaChange:
    code: str
    impact: Impact
    message: str
    column: str | None = None


@dataclass(frozen=True)
class SchemaComparison:
    changes: tuple[SchemaChange, ...]

    @property
    def compatible(self) -> bool:
        return all(change.impact != "breaking" for change in self.changes)

    @property
    def summary(self) -> dict[str, int]:
        return {
            impact: sum(change.impact == impact for change in self.changes)
            for impact in ("breaking", "compatible", "metadata")
        }


def _change(code: str, message: str, column: Column, impact: Impact = "breaking") -> SchemaChange:
    return SchemaChange(code, impact, message, column.name)


def _presence_changes(before: Column, after: Column) -> list[SchemaChange]:
    changes = []
    if before.required != after.required:
        impact: Impact = "breaking" if after.required else "compatible"
        changes.append(_change("required_changed", f"required header changed to {after.required}", after, impact))
    if before.nullable != after.nullable:
        impact = "compatible" if after.nullable else "breaking"
        changes.append(_change("nullable_changed", f"nullable cells changed to {after.nullable}", after, impact))
    if before.whitespace != after.whitespace:
        changes.append(_change("whitespace_changed", "cell whitespace normalization changed", after))
    if before.description != after.description:
        changes.append(_change("description_changed", "column description changed", after, "metadata"))
    return changes


def _range_changes(before: Column, after: Column) -> list[SchemaChange]:
    changes = []
    for key in ("minimum", "maximum", "min_length", "max_length"):
        old = getattr(before.constraints, key)
        new = getattr(after.constraints, key)
        if old == new:
            continue
        if new is None:
            tightened = False
        elif old is None:
            tightened = True
        elif key in ("minimum", "min_length"):
            tightened = new > old
        else:
            tightened = new < old
        impact: Impact = "breaking" if tightened else "compatible"
        changes.append(_change(f"{key}_changed", f"{key} constraint changed", after, impact))
    return changes


def _enum_changes(before: Column, after: Column) -> list[SchemaChange]:
    old = before.constraints.enumeration
    new = after.constraints.enumeration
    if old == new or (old is not None and new is not None and set(old) == set(new)):
        return []
    if new is None:
        impact: Impact = "compatible"
    elif old is None or not set(old).issubset(new):
        impact = "breaking"
    else:
        impact = "compatible"
    return [_change("enum_changed", "allowed enumeration values changed", after, impact)]


def _boolean_changes(before: Column, after: Column) -> list[SchemaChange]:
    if before.boolean_format == after.boolean_format:
        return []
    old = before.boolean_format
    new = after.boolean_format
    if old.case_sensitive and not new.case_sensitive:
        # All previously allowed spellings still need to map to the same truth value.
        same_true = {boolean_key(value, new) for value in old.true_values}.issubset(
            {boolean_key(value, new) for value in new.true_values}
        )
        same_false = {boolean_key(value, new) for value in old.false_values}.issubset(
            {boolean_key(value, new) for value in new.false_values}
        )
    elif old.case_sensitive == new.case_sensitive:
        same_true = {boolean_key(value, old) for value in old.true_values}.issubset(
            {boolean_key(value, new) for value in new.true_values}
        )
        same_false = {boolean_key(value, old) for value in old.false_values}.issubset(
            {boolean_key(value, new) for value in new.false_values}
        )
    else:
        same_true = same_false = False
    impact: Impact = "compatible" if same_true and same_false else "breaking"
    return [_change("boolean_format_changed", "accepted boolean spellings or case rules changed", after, impact)]


def _column_changes(before: Column, after: Column) -> list[SchemaChange]:
    changes = _presence_changes(before, after)
    if before.type != after.type:
        changes.append(_change("type_changed", f"type changed from {before.type} to {after.type}", after))
        return changes
    changes.extend(_range_changes(before, after))
    changes.extend(_enum_changes(before, after))
    if after.type == "boolean":
        changes.extend(_boolean_changes(before, after))
    for attribute in ("unique", "nonempty_after_trim"):
        old = getattr(before.constraints, attribute)
        new = getattr(after.constraints, attribute)
        if old != new:
            impact: Impact = "breaking" if new else "compatible"
            changes.append(_change(f"{attribute}_changed", f"{attribute} changed to {new}", after, impact))
    return changes


def _csv_changes(before: DatasetSchema, after: DatasetSchema) -> list[SchemaChange]:
    changes = []
    for name in ("delimiter", "quotechar"):
        if getattr(before.csv, name) != getattr(after.csv, name):
            changes.append(SchemaChange(f"csv_{name}_changed", "breaking", f"CSV {name} changed"))
    if before.csv.allow_extra_columns != after.csv.allow_extra_columns:
        impact: Impact = "compatible" if after.csv.allow_extra_columns else "breaking"
        changes.append(SchemaChange("extra_columns_changed", impact, "extra-column acceptance changed"))
    if before.csv.enforce_column_order != after.csv.enforce_column_order:
        impact = "breaking" if after.csv.enforce_column_order else "compatible"
        changes.append(SchemaChange("column_order_changed", impact, "column order enforcement changed"))
    elif after.csv.enforce_column_order:
        shared = set(before.by_name).intersection(after.by_name)
        old_order = [column.name for column in before.columns if column.name in shared]
        new_order = [column.name for column in after.columns if column.name in shared]
        if old_order != new_order:
            changes.append(SchemaChange("columns_reordered", "breaking", "enforced shared-column order changed"))
    return changes


def _dataset_changes(before: DatasetSchema, after: DatasetSchema) -> list[SchemaChange]:
    changes = _csv_changes(before, after)
    if before.primary_key != after.primary_key:
        impact: Impact = "compatible" if not after.primary_key else "breaking"
        changes.append(SchemaChange("primary_key_changed", impact, "primary key definition changed"))
    if before.min_rows != after.min_rows:
        impact = "breaking" if after.min_rows > before.min_rows else "compatible"
        changes.append(SchemaChange("min_rows_changed", impact, "minimum data-record count changed"))
    if before.max_rows != after.max_rows:
        tightened = after.max_rows is not None and (before.max_rows is None or after.max_rows < before.max_rows)
        impact = "breaking" if tightened else "compatible"
        changes.append(SchemaChange("max_rows_changed", impact, "maximum data-record count changed"))
    if before.title != after.title:
        changes.append(SchemaChange("title_changed", "metadata", "dataset title changed"))
    return changes


def compare_schemas(before: DatasetSchema, after: DatasetSchema) -> SchemaComparison:
    """Flag tightened rules and removed contracts that need release review."""
    old = before.by_name
    new = after.by_name
    changes = _dataset_changes(before, after)
    for name in sorted(old.keys() | new.keys()):
        if name not in new:
            changes.append(_change("column_removed", "published column was removed", old[name]))
        elif name not in old:
            impact: Impact = "breaking" if new[name].required else "compatible"
            changes.append(_change("column_added", "new column was added", new[name], impact))
        else:
            changes.extend(_column_changes(old[name], new[name]))
    return SchemaComparison(tuple(sorted(changes, key=lambda change: (change.column or "", change.code))))
