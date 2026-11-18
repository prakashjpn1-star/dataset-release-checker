"""Read strict quoted CSV with logical record and physical line provenance."""

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

from .models import CsvConventions, CsvRecord, Diagnostic, Location

_BOM = b"\xef\xbb\xbf"
State = Literal["start", "plain", "quoted", "closed"]


class CsvSyntaxError(ValueError):
    def __init__(self, column_index: int, message: str) -> None:
        self.column_index = column_index
        super().__init__(message)


@dataclass
class _RecordBuilder:
    conventions: CsvConventions
    number: int
    line_start: int
    cells: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    state: State = "start"
    byte_count: int = 0
    has_text: bool = False

    @property
    def column_index(self) -> int:
        return len(self.cells) + 1

    def _end_cell(self) -> None:
        self.cells.append("".join(self.characters))
        self.characters.clear()
        self.state = "start"

    def consume(self, text: str) -> None:
        for character in text:
            self.has_text = True
            if character == "\0":
                raise CsvSyntaxError(self.column_index, "NUL characters are forbidden in CSV")
            if character == "\r" and self.state != "quoted":
                raise CsvSyntaxError(self.column_index, "use LF or CRLF record endings")
            if self.state == "quoted":
                if character == self.conventions.quotechar:
                    self.state = "closed"
                else:
                    self.characters.append(character)
                continue
            if self.state == "closed":
                if character == self.conventions.quotechar:
                    self.characters.append(character)
                    self.state = "quoted"
                elif character == self.conventions.delimiter:
                    self._end_cell()
                else:
                    raise CsvSyntaxError(self.column_index, "expected a delimiter or record ending after a closing quote")
                continue
            if character == self.conventions.delimiter:
                self._end_cell()
            elif character == self.conventions.quotechar:
                if self.state != "start":
                    raise CsvSyntaxError(self.column_index, "a quoted field must begin with the quote character")
                self.state = "quoted"
            else:
                self.characters.append(character)
                self.state = "plain"

    def finish(self, physical_line_end: int) -> CsvRecord:
        if self.has_text:
            self._end_cell()
        return CsvRecord(self.number, self.line_start, physical_line_end, tuple(self.cells))


def _body_and_ending(text: str) -> tuple[str, str]:
    if text.endswith("\r\n"):
        return text[:-2], "\r\n"
    if text.endswith("\n"):
        return text[:-1], "\n"
    return text, ""


def _read_stream(
    source: BinaryIO,
    file: str,
    conventions: CsvConventions,
    max_record_bytes: int,
) -> Iterator[CsvRecord | Diagnostic]:
    physical_line = 0
    builder = _RecordBuilder(conventions, 1, 1)
    while True:
        remaining = max_record_bytes - builder.byte_count
        raw = source.readline(remaining + 1)
        if not raw:
            if builder.state == "quoted":
                yield Diagnostic(
                    "malformed_csv",
                    Location(file, builder.number, builder.line_start, physical_line, column_index=builder.column_index),
                    "quoted field reaches EOF before its closing quote",
                )
            return
        physical_line += 1
        builder.byte_count += len(raw)
        location = Location(file, builder.number, builder.line_start, physical_line)
        if builder.byte_count > max_record_bytes:
            yield Diagnostic("record_too_large", location, f"logical record exceeds {max_record_bytes} bytes")
            return
        if physical_line == 1 and raw.startswith(_BOM):
            raw = raw[len(_BOM):]
            if not raw:
                continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            yield Diagnostic("invalid_encoding", location, "CSV must be UTF-8, optionally with an initial BOM")
            return
        body, ending = _body_and_ending(text)
        try:
            builder.consume(body)
        except CsvSyntaxError as error:
            yield Diagnostic(
                "malformed_csv",
                Location(file, builder.number, builder.line_start, physical_line, column_index=error.column_index),
                str(error),
            )
            return
        if builder.state == "quoted":
            builder.characters.append(ending)
            continue
        yield builder.finish(physical_line)
        builder = _RecordBuilder(conventions, builder.number + 1, physical_line + 1)


def read_csv(
    path: Path,
    conventions: CsvConventions = CsvConventions(),
    *,
    max_record_bytes: int = 8 * 1024 * 1024,
) -> Iterator[CsvRecord | Diagnostic]:
    """Stop on structural syntax or encoding failures because framing is uncertain."""
    if type(max_record_bytes) is not int or max_record_bytes < 1:
        raise ValueError("record byte limit must be positive")
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            yield Diagnostic("file_unreadable", Location(str(path)), "input must be a regular file")
            return
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            yield from _read_stream(source, str(path), conventions, max_record_bytes)
    except OSError as error:
        yield Diagnostic("file_unreadable", Location(str(path)), error.strerror or str(error))
    finally:
        if descriptor is not None:
            os.close(descriptor)
