"""MCO Format 1 container: header, table of contents and chunks.

This module knows nothing about what a chunk means. It writes and validates the
byte layout of ``docs/mco/format-1.md`` sections 3 to 5 and reads one chunk at
a time. Standard library only; no code from a file is ever executed.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import struct
from typing import Any, BinaryIO, Optional, Union
import zlib

from ..errors import IntegrityError, ModelFormatError, ModelNotFoundError, UnsupportedFormatError

__all__ = [
    "MAGIC", "MAJOR", "MINOR", "HEADER", "ENTRY", "HEADER_SIZE", "ENTRY_SIZE", "MAX_CHUNKS", "MAX_RAW",
    "NONE", "ZLIB", "Chunk", "ChunkEntry", "Container", "encode", "write_file", "header_digest",
]

MAGIC = b"\x89MCO\r\n\x1a\n"
MAJOR, MINOR = 1, 0
#: magic, major, minor, header_size, flags, toc_count, toc_offset, toc_size,
#: file_size, toc_entry_size, reserved, header_sha256, reserved
HEADER = struct.Struct("<8sHHIIIQQQII32s8s")
#: type, chunk_version, chunk_flags, compression, offset, length, raw_length, sha256
ENTRY = struct.Struct("<4sHBBQQQ32s")
HEADER_SIZE, ENTRY_SIZE = HEADER.size, ENTRY.size
assert (HEADER_SIZE, ENTRY_SIZE) == (96, 64)
MAX_CHUNKS = 65_536
MAX_RAW = 1 << 28                   # 256 MiB, stored or decompressed
MAX_U63 = (1 << 63) - 1
NONE, ZLIB = 0, 1
REQUIRED_FLAG = 0x01
HEADER_REQUIRED_FLAGS = 0x0000FFFF
KNOWN_HEADER_FLAGS = 0              # none defined in 1.0
_TYPE = re.compile(rb"[A-Z0-9]{4}")

PathLike = Union[str, "os.PathLike[str]"]


def _align8(value: int) -> int:
    return (value + 7) & ~7


def header_digest(header: bytes, toc: bytes) -> bytes:
    """SHA-256 of header bytes [0, 56) + [88, 96) + the TOC: the header checksum."""
    return hashlib.sha256(header[:56] + header[88:96] + toc).digest()


@dataclass(frozen=True)
class Chunk:
    """A chunk to write. ``compression=None`` picks zlib only when it is smaller."""

    type: str
    data: bytes
    version: int = 1
    required: bool = True
    compression: Optional[int] = None


@dataclass(frozen=True)
class ChunkEntry:
    """One validated TOC entry."""

    index: int
    type: str
    version: int
    required: bool
    compression: int
    offset: int
    length: int
    raw_length: int
    sha256: bytes
    flags: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "type": self.type, "version": self.version, "required": self.required,
                "compression": {NONE: "none", ZLIB: "zlib"}.get(self.compression, str(self.compression)),
                "offset": self.offset, "length": self.length, "raw_length": self.raw_length,
                "sha256": self.sha256.hex()}


# --- writing ---------------------------------------------------------------------------

def _store(chunk: Chunk) -> tuple[int, bytes]:
    if not isinstance(chunk.type, str) or not _TYPE.fullmatch(chunk.type.encode("ascii", "replace")):
        raise ValueError(f"chunk type must be four characters A-Z or 0-9: {chunk.type!r}")
    if not 1 <= chunk.version <= 0xFFFF:
        raise ValueError(f"chunk version out of range: {chunk.version}")
    data = bytes(chunk.data)
    if len(data) > MAX_RAW:
        raise ValueError(f"chunk {chunk.type} is larger than {MAX_RAW} bytes")
    if chunk.compression == NONE or not data:
        return NONE, data
    if chunk.compression not in (None, ZLIB):
        raise ValueError(f"unknown compression {chunk.compression}")
    packed = zlib.compress(data, 9)
    if chunk.compression is None and len(packed) >= len(data):
        return NONE, data
    return ZLIB, packed


def encode(chunks: Iterable[Chunk], *, flags: int = 0, major: int = MAJOR, minor: int = MINOR) -> bytes:
    """The bytes of a Format 1 file holding ``chunks`` in order. Deterministic."""
    body = bytearray()
    toc = bytearray()
    position = HEADER_SIZE
    count = 0
    for chunk in chunks:
        compression, stored = _store(chunk)
        entry_flags = REQUIRED_FLAG if chunk.required else 0
        toc += ENTRY.pack(chunk.type.encode("ascii"), chunk.version, entry_flags, compression, position,
                          len(stored), len(chunk.data), hashlib.sha256(stored).digest())
        body += stored
        padded = _align8(position + len(stored))
        body += b"\x00" * (padded - position - len(stored))
        position = padded
        count += 1
    if count > MAX_CHUNKS:
        raise ValueError(f"more than {MAX_CHUNKS} chunks")
    file_size = position + len(toc)
    header = HEADER.pack(MAGIC, major, minor, HEADER_SIZE, flags, count, position, len(toc), file_size,
                         ENTRY_SIZE, 0, b"\x00" * 32, b"\x00" * 8)
    header = header[:56] + header_digest(header, bytes(toc)) + header[88:]
    return header + bytes(body) + bytes(toc)


def write_file(path: PathLike, data: bytes) -> None:
    """Write ``data`` atomically (temporary file, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# --- reading -----------------------------------------------------------------------------

class Container:
    """A validated Format 1 container over a seekable binary stream.

    Opening reads the 96-byte header and the TOC only, and validates them
    (sections 4 and 5 of the specification). :meth:`read` then reads exactly
    one chunk. ``known`` maps the chunk types the caller understands to the
    highest chunk version it supports: a required chunk outside it is refused.
    """

    def __init__(self, stream: BinaryIO, size: int, *, name: str = "<stream>",
                 known: Optional[Mapping[str, int]] = None, owns: bool = False) -> None:
        self._stream = stream
        self._owns = owns
        self.name = name
        self.size = size
        self._known = dict(known or {})
        try:
            self._open()
        except BaseException:
            self.close()
            raise

    @classmethod
    def open(cls, path: PathLike, *, known: Optional[Mapping[str, int]] = None) -> "Container":
        path = Path(path)
        try:
            stream = path.open("rb")
        except FileNotFoundError as exc:
            raise ModelNotFoundError(f"model not found: {path}") from exc
        except IsADirectoryError as exc:
            raise ModelFormatError(f"{path} is a directory") from exc
        size = os.fstat(stream.fileno()).st_size
        return cls(stream, size, name=str(path), known=known, owns=True)

    @classmethod
    def from_bytes(cls, data: bytes, *, name: str = "<bytes>",
                   known: Optional[Mapping[str, int]] = None) -> "Container":
        return cls(io.BytesIO(data), len(data), name=name, known=known, owns=True)

    def close(self) -> None:
        if self._owns and not self._stream.closed:
            self._stream.close()

    def __enter__(self) -> "Container":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- validation ----------------------------------------------------------------------

    def _fail(self, message: str, cls: type = ModelFormatError) -> Exception:
        return cls(f"{self.name}: {message}")

    def _read_at(self, offset: int, length: int, what: str) -> bytes:
        self._stream.seek(offset)
        data = self._stream.read(length)
        if len(data) != length:
            raise self._fail(f"truncated: {what} needs {length} bytes at offset {offset}, file has {len(data)}")
        return data

    def _open(self) -> None:
        if self.size < len(MAGIC):
            raise self._fail(f"truncated: {self.size} bytes is shorter than the magic")
        magic = self._read_at(0, len(MAGIC), "magic")
        if magic != MAGIC:
            raise self._fail("not an MCO Format 1 file (bad magic)")
        if self.size < 12:
            raise self._fail("truncated: the header is incomplete")
        major, minor = struct.unpack("<HH", self._read_at(8, 4, "version"))
        self.major, self.minor = major, minor
        if major == 0:
            raise self._fail("format major version 0 is not valid")
        if major > MAJOR:
            raise self._fail(f"format version {major}.{minor} is newer than this reader ({MAJOR}.x)",
                             UnsupportedFormatError)
        if self.size < HEADER_SIZE:
            raise self._fail(f"truncated: the header needs {HEADER_SIZE} bytes, the file has {self.size}")
        header = self._read_at(0, HEADER_SIZE, "header")
        (_magic, _major, _minor, header_size, flags, toc_count, toc_offset, toc_size, file_size,
         entry_size, reserved, digest, reserved2) = HEADER.unpack(header)
        if header_size != HEADER_SIZE or entry_size != ENTRY_SIZE:
            raise self._fail(f"header_size {header_size} / toc_entry_size {entry_size} are not 96 / 64")
        if reserved or reserved2 != b"\x00" * 8:
            raise self._fail("reserved header fields are not zero")
        if file_size > MAX_U63 or toc_offset > MAX_U63 or toc_size > MAX_U63:
            raise self._fail("header offset or size overflows")
        if file_size > self.size:
            raise self._fail(f"truncated: header declares {file_size} bytes, the file has {self.size}")
        if file_size < self.size:
            raise self._fail(f"{self.size - file_size} trailing bytes after the declared end of file")
        if toc_count > MAX_CHUNKS:
            raise self._fail(f"absurd chunk count {toc_count} (limit {MAX_CHUNKS})")
        if toc_size != toc_count * ENTRY_SIZE:
            raise self._fail(f"toc_size {toc_size} is not {toc_count} x {ENTRY_SIZE}")
        if toc_offset % 8 or toc_offset < HEADER_SIZE:
            raise self._fail(f"toc_offset {toc_offset} is misaligned or inside the header")
        if toc_offset + toc_size != file_size:
            raise self._fail(f"TOC [{toc_offset}, {toc_offset + toc_size}) lies outside the file "
                             f"or does not end it ({file_size} bytes)")
        toc = self._read_at(toc_offset, toc_size, "TOC")
        if header_digest(header, toc) != digest:
            raise self._fail("header checksum mismatch (header or TOC damaged)", IntegrityError)
        unknown_required = flags & HEADER_REQUIRED_FLAGS & ~KNOWN_HEADER_FLAGS
        if unknown_required:
            raise self._fail(f"unknown required header flags 0x{unknown_required:04x}", UnsupportedFormatError)
        self.flags = flags
        self.toc_offset = toc_offset
        self.entries = self._entries(toc, toc_count, toc_offset)

    def _entries(self, toc: bytes, count: int, toc_offset: int) -> list[ChunkEntry]:
        entries: list[ChunkEntry] = []
        expected = HEADER_SIZE
        for index in range(count):
            raw_type, version, flags, compression, offset, length, raw_length, sha = \
                ENTRY.unpack_from(toc, index * ENTRY_SIZE)
            where = f"chunk {index}"
            if not _TYPE.fullmatch(raw_type):
                raise self._fail(f"{where}: invalid type bytes {raw_type!r}")
            kind = raw_type.decode("ascii")
            where = f"chunk {index} ({kind})"
            if version == 0:
                raise self._fail(f"{where}: chunk version 0 is not valid")
            if offset > MAX_U63 or length > MAX_U63 or raw_length > MAX_U63:
                raise self._fail(f"{where}: offset or length overflows")
            if length > MAX_RAW or raw_length > MAX_RAW:
                raise self._fail(f"{where}: size {max(length, raw_length)} is over the {MAX_RAW}-byte cap")
            if offset % 8:
                raise self._fail(f"{where}: offset {offset} is not a multiple of 8")
            if offset < expected:
                raise self._fail(f"{where}: overlaps the previous chunk or the header "
                                 f"(starts at {offset}, expected {expected})")
            if offset > expected:
                raise self._fail(f"{where}: leaves a gap (starts at {offset}, expected {expected})")
            if offset + length > toc_offset:
                raise self._fail(f"{where}: [{offset}, {offset + length}) runs past the TOC at {toc_offset}")
            if length == 0 and (compression != NONE or raw_length != 0):
                raise self._fail(f"{where}: an empty chunk must be uncompressed with raw_length 0")
            if compression == NONE and length != raw_length:
                raise self._fail(f"{where}: uncompressed but length {length} != raw_length {raw_length}")
            required = bool(flags & REQUIRED_FLAG)
            entry = ChunkEntry(index, kind, version, required, compression, offset, length, raw_length, sha, flags)
            if required and not self.understands(entry):
                if kind in self._known:
                    raise self._fail(f"{where}: required chunk version {version} is newer than this reader "
                                     f"({self._known[kind]})", UnsupportedFormatError)
                raise self._fail(f"{where}: unknown required chunk type", UnsupportedFormatError)
            entries.append(entry)
            expected = _align8(offset + length)
        if expected != toc_offset:
            raise self._fail(f"the TOC starts at {toc_offset}, expected {expected} after the last chunk")
        return entries

    # -- access ----------------------------------------------------------------------------

    def understands(self, entry: ChunkEntry) -> bool:
        return entry.type in self._known and entry.version <= self._known[entry.type]

    def of_type(self, kind: str) -> list[ChunkEntry]:
        return [e for e in self.entries if e.type == kind]

    def read_stored(self, entry: ChunkEntry) -> bytes:
        """The stored bytes of ``entry``, checksum verified."""
        stored = self._read_at(entry.offset, entry.length, f"chunk {entry.index} ({entry.type})")
        if hashlib.sha256(stored).digest() != entry.sha256:
            raise self._fail(f"chunk {entry.index} ({entry.type}): checksum mismatch", IntegrityError)
        return stored

    def read(self, entry: Union[ChunkEntry, int]) -> bytes:
        """The decompressed bytes of one chunk. Reads only that chunk."""
        if isinstance(entry, int):
            entry = self.entries[entry]
        stored = self.read_stored(entry)
        where = f"chunk {entry.index} ({entry.type})"
        if entry.compression == NONE:
            return stored
        if entry.compression != ZLIB:
            raise self._fail(f"{where}: unknown compression {entry.compression}", UnsupportedFormatError)
        inflater = zlib.decompressobj()
        try:
            raw = inflater.decompress(stored, entry.raw_length + 1)
        except zlib.error as exc:
            raise self._fail(f"{where}: bad zlib stream ({exc})") from exc
        if len(raw) > entry.raw_length:
            raise self._fail(f"{where}: decompresses past its declared raw_length {entry.raw_length}")
        if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
            raise self._fail(f"{where}: incomplete zlib stream or bytes after its end")
        if len(raw) != entry.raw_length:
            raise self._fail(f"{where}: decompressed {len(raw)} bytes, raw_length says {entry.raw_length}")
        return raw

    def verify_all(self) -> None:
        """Full verification: every chunk's checksum and size, and zero padding."""
        for entry in self.entries:
            self.read(entry) if entry.compression in (NONE, ZLIB) else self.read_stored(entry)
            end = entry.offset + entry.length
            pad = _align8(end) - end
            if pad and self._read_at(end, pad, "padding") != b"\x00" * pad:
                raise self._fail(f"chunk {entry.index} ({entry.type}): nonzero padding")
