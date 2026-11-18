"""Expose schema validation and CSV release checks to terminal users."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .comparison import compare_schemas
from .models import ValidationOptions
from .output import ReportWriteError, check_destination, write_report
from .reporting import render_batch, render_codes, render_comparison, render_schema
from .schema import SchemaError, load_schema
from .validation import validate_files

SUCCESS = 0
DATA_ERRORS = 1
COMMAND_ERROR = 2


def _format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="stdout report format (default: text)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataset-check",
        description="Check a CSV release against its published dataset schema.",
        epilog="Exit codes: 0 valid, 1 dataset errors, 2 schema, input, or output failure.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a CSV file and report row and column errors")
    validate.add_argument("files", type=Path, nargs="+", metavar="FILE", help="CSV datasets to inspect independently")
    validate.add_argument("--schema", required=True, type=Path, help="published JSON schema")
    validate.add_argument("--report", type=Path, help="also save the JSON report atomically")
    validate.add_argument("--strict", action="store_true", help="stop after the first invalid header or data record")
    validate.add_argument("--profile", action="store_true", help="include observed column ranges and counts in text output")
    validate.add_argument("--max-errors", type=int, metavar="N", help="retain at most N detailed errors while counting all failures")
    validate.add_argument(
        "--max-record-bytes", type=int, default=8 * 1024 * 1024, metavar="N",
        help="maximum bytes per logical record, including line endings (default: 8388608)",
    )
    _format_option(validate)
    validate.set_defaults(run=_validate)

    schema = commands.add_parser("schema", help="validate and display a normalized schema")
    schema.add_argument("file", type=Path, help="JSON schema to inspect")
    schema.add_argument("--report", type=Path, help="save the normalized JSON schema atomically")
    _format_option(schema)
    schema.set_defaults(run=_schema)

    compare = commands.add_parser("compare", help="check changes between two published schemas")
    compare.add_argument("before", type=Path, help="earlier JSON schema")
    compare.add_argument("after", type=Path, help="later JSON schema")
    compare.add_argument("--report", type=Path, help="also save the JSON comparison")
    _format_option(compare)
    compare.set_defaults(run=_compare)

    codes = commands.add_parser("codes", help="list the stable dataset validation error codes")
    _format_option(codes)
    codes.set_defaults(run=_codes)
    return parser


def _validate(args: argparse.Namespace) -> int:
    options = ValidationOptions(
        strict=args.strict,
        max_errors=args.max_errors,
        max_record_bytes=args.max_record_bytes,
    )
    if args.report is not None:
        check_destination(args.report, (*args.files, args.schema))
    schema = load_schema(args.schema)
    report = validate_files(args.files, schema, schema_file=str(args.schema), options=options)
    if args.report is not None:
        structured = render_batch(report, "json")
        write_report(args.report, structured)
        print(structured if args.format == "json" else render_batch(report, "text", profile=args.profile))
    else:
        print(render_batch(report, args.format, profile=args.profile))
    if report.operational_error:
        return COMMAND_ERROR
    return SUCCESS if report.ok else DATA_ERRORS


def _schema(args: argparse.Namespace) -> int:
    if args.report is not None:
        check_destination(args.report, (args.file,))
    schema = load_schema(args.file)
    if args.report is not None:
        document = render_schema(schema, "json")
        write_report(args.report, document)
        print(document if args.format == "json" else render_schema(schema, "text"))
    else:
        print(render_schema(schema, args.format))
    return SUCCESS


def _compare(args: argparse.Namespace) -> int:
    if args.report is not None:
        check_destination(args.report, (args.before, args.after))
    before = load_schema(args.before)
    after = load_schema(args.after)
    result = compare_schemas(before, after)
    if args.report is not None:
        structured = render_comparison(result, str(args.before), str(args.after), "json")
        write_report(args.report, structured)
        print(structured if args.format == "json" else render_comparison(result, str(args.before), str(args.after), "text"))
    else:
        print(render_comparison(result, str(args.before), str(args.after), args.format))
    return SUCCESS if result.compatible else DATA_ERRORS


def _codes(args: argparse.Namespace) -> int:
    print(render_codes(args.format))
    return SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (SchemaError, ReportWriteError, ValueError) as error:
        print(f"dataset-check: {error}", file=sys.stderr)
        return COMMAND_ERROR
    except KeyboardInterrupt:
        print("dataset-check: interrupted", file=sys.stderr)
        return 130
