"""Save reports atomically while protecting input paths from replacement."""

import os
from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile


class ReportWriteError(Exception):
    """A report destination cannot be resolved or written."""


def check_destination(destination: Path, sources: Iterable[Path]) -> None:
    try:
        resolved = destination.resolve()
        for source in sources:
            if resolved == source.resolve():
                raise ReportWriteError("report destination must differ from input CSV and schema paths")
            try:
                aliases_source = destination.samefile(source)
            except OSError:
                # Missing inputs are diagnosed by their respective readers.
                continue
            if aliases_source:
                raise ReportWriteError("report destination is a filesystem alias of an input")
    except (OSError, RuntimeError) as error:
        raise ReportWriteError(f"cannot resolve report destination {str(destination)!r}: {error}") from error


def write_report(destination: Path, text: str) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
            prefix=".dataset-check-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except OSError as error:
        raise ReportWriteError(f"cannot save report {str(destination)!r}: {error.strerror or error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
