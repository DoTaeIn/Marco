"""Model file formats: detection, reading and writing, with no backend imports.

Three on-disk forms are recognised:

``mco-compat`` (container version 0)
    The interim ``.mco`` file this release writes. A deterministic ZIP holding
    exactly two members: ``mco.json`` (the MCO manifest) and ``payload.kgpack``
    (an unmodified MARCO pack). It is **not** MCO Format 1: it exists so that
    user code can adopt ``.mco`` paths and the ``mco`` API before the native
    binary specification is final. The manifest records which backend runs it.

``kgpack``
    A bare MARCO ``.kgpack`` (ZIP with ``manifest.json``), accepted directly.

``mco-native``
    MCO Format 1 (``docs/mco/format-1.md``), read and written by
    :mod:`mco.native`. Identified by the magic prefix :data:`NATIVE_MAGIC`. A
    file this reader recognises but cannot run (a newer major version, an
    unknown required chunk or runtime feature) is still detected, with the
    reason in :attr:`ModelFile.refusal`, so ``inspect`` can describe it and
    ``load`` refuses it with :class:`~mco.errors.UnsupportedFormatError`.

Integrity checks here re-implement the kgpack size/SHA-256 rules on purpose, so
``mco.inspect`` works without the MARCO runtime installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Union
import zipfile

from .errors import CompileError, IntegrityError, ModelFormatError, ModelNotFoundError, UnsupportedFormatError

__all__ = [
    "NATIVE_MAGIC",
    "COMPAT_CONTAINER",
    "COMPAT_VERSION",
    "ModelFile",
    "detect",
    "write_compat",
    "write_native",
]

PathLike = Union[str, "os.PathLike[str]"]

#: Magic prefix of native MCO files (the full Format 1 magic is ``mco.native.MAGIC``).
NATIVE_MAGIC = b"\x89MCO"
COMPAT_CONTAINER = "compat-zip"
COMPAT_VERSION = 0
MANIFEST_NAME = "mco.json"
PAYLOAD_NAME = "payload.kgpack"
_ZIP_MAGIC = b"PK\x03\x04"
_FROZEN_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ModelFile:
    """A detected model file. Internal; user code sees :class:`~mco.info.ModelInfo`."""

    path: Path
    kind: str                      # "mco-compat" | "kgpack" | "mco-native"
    version: Optional[int]
    size_bytes: int
    sha256: str
    manifest: dict[str, Any] = field(default_factory=dict)        # mco.json (compat only)
    pack_manifest: dict[str, Any] = field(default_factory=dict)   # kgpack manifest.json
    verified: bool = False
    native: dict[str, Any] = field(default_factory=dict)          # Format 1 header, chunks, members
    refusal: Optional[str] = None  # why this reader cannot run a recognised file

    def payload_bytes(self) -> bytes:
        """The embedded ``.kgpack`` bytes (compat), the file itself (kgpack), or
        the pack rebuilt from a Format 1 file's chunks (native)."""
        if self.kind == "kgpack":
            return self.path.read_bytes()
        if self.kind == "mco-compat":
            with zipfile.ZipFile(self.path) as zf:
                return zf.read(PAYLOAD_NAME)
        if self.kind == "mco-native":
            if self.refusal:
                raise UnsupportedFormatError(self.refusal)
            from .native.pack import NativeModel
            with NativeModel.open(self.path) as model:
                return model.kgpack_bytes()
        raise ModelFormatError(f"{self.kind} has no kgpack payload")


def _read_pack_manifest(data: bytes, *, verify: bool, where: str) -> dict[str, Any]:
    """Validate a kgpack held in memory; return its manifest."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if names.count("manifest.json") != 1 or len(names) != len(set(names)):
                raise ModelFormatError(f"{where}: kgpack must hold exactly one manifest.json and no duplicates")
            manifest = json.loads(zf.read("manifest.json"))
            if not isinstance(manifest, dict) or manifest.get("format") != "nai-kgpack":
                raise ModelFormatError(f"{where}: not a MARCO kgpack manifest")
            files = manifest.get("files")
            if not isinstance(files, list):
                raise ModelFormatError(f"{where}: kgpack manifest 'files' is not a list")
            listed = set()
            for item in files:
                name = str(item.get("path", "")) if isinstance(item, dict) else ""
                parts = PurePosixPath(name).parts
                if not name or name.startswith("/") or ".." in parts or name not in names or name in listed:
                    raise ModelFormatError(f"{where}: manifest and archive disagree on {name!r}")
                listed.add(name)
                if verify:
                    body = zf.read(name)
                    if len(body) != item.get("bytes") or _sha256(body) != item.get("sha256"):
                        raise IntegrityError(f"{where}: integrity check failed for {name}")
            if set(names) - {"manifest.json"} - listed:
                raise ModelFormatError(f"{where}: archive holds files the manifest does not list")
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
        raise ModelFormatError(f"{where}: unreadable kgpack ({exc})") from exc


def detect(path: PathLike, *, verify: bool = True) -> ModelFile:
    """Identify and validate a model file without executing it."""
    path = Path(path)
    if not path.exists():
        raise ModelNotFoundError(f"model not found: {path}")
    if path.is_dir():
        raise ModelFormatError(f"{path} is a directory; compile it first with mco.compile()")
    size = path.stat().st_size
    with path.open("rb") as handle:
        head = handle.read(8)
    digest = _file_sha256(path)
    if head.startswith(NATIVE_MAGIC):
        return _detect_native(path, size, digest, verify)
    if not head.startswith(_ZIP_MAGIC):
        raise ModelFormatError(f"{path}: not an MCO model (unrecognised header)")
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if MANIFEST_NAME in names:
                return _detect_compat(path, zf, names, size, digest, verify)
            if "manifest.json" in names:
                pack_manifest = _read_pack_manifest(path.read_bytes(), verify=verify, where=str(path))
                return ModelFile(path, "kgpack", pack_manifest.get("version"), size, digest,
                                 pack_manifest=pack_manifest, verified=verify)
    except zipfile.BadZipFile as exc:
        raise ModelFormatError(f"{path}: truncated or corrupt archive ({exc})") from exc
    raise ModelFormatError(f"{path}: ZIP archive without an MCO or kgpack manifest")


def _detect_compat(path: Path, zf: zipfile.ZipFile, names: list[str], size: int,
                   digest: str, verify: bool) -> ModelFile:
    if sorted(names) != sorted([MANIFEST_NAME, PAYLOAD_NAME]):
        raise ModelFormatError(f"{path}: compat .mco must hold exactly {MANIFEST_NAME} and {PAYLOAD_NAME}")
    try:
        manifest = json.loads(zf.read(MANIFEST_NAME))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ModelFormatError(f"{path}: {MANIFEST_NAME} is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "mco":
        raise ModelFormatError(f"{path}: {MANIFEST_NAME} does not declare format 'mco'")
    if manifest.get("container") != COMPAT_CONTAINER:
        raise ModelFormatError(f"{path}: unknown MCO container {manifest.get('container')!r}")
    version = manifest.get("container_version")
    if version != COMPAT_VERSION:
        raise ModelFormatError(f"{path}: compat container version {version!r} is not supported "
                               f"(this mco reads version {COMPAT_VERSION})")
    payload = manifest.get("payload")
    if not isinstance(payload, dict) or payload.get("path") != PAYLOAD_NAME or payload.get("kind") != "kgpack":
        raise ModelFormatError(f"{path}: {MANIFEST_NAME} has no valid kgpack payload entry")
    body = zf.read(PAYLOAD_NAME)
    if verify and (len(body) != payload.get("bytes") or _sha256(body) != payload.get("sha256")):
        raise IntegrityError(f"{path}: payload integrity check failed")
    pack_manifest = _read_pack_manifest(body, verify=verify, where=f"{path}!{PAYLOAD_NAME}")
    return ModelFile(path, "mco-compat", version, size, digest, manifest=manifest,
                     pack_manifest=pack_manifest, verified=verify)


def _detect_native(path: Path, size: int, digest: str, verify: bool) -> ModelFile:
    from .native.pack import NativeModel
    try:
        with NativeModel.open(path) as model:
            if verify:
                model.verify_all()
            return ModelFile(path, "mco-native", model.major, size, digest, manifest=model.manifest,
                             native=model.summary(), verified=verify)
    except UnsupportedFormatError as exc:
        with path.open("rb") as handle:
            head = handle.read(12)
        major = int.from_bytes(head[8:10], "little") if len(head) >= 10 else None
        return ModelFile(path, "mco-native", major, size, digest, refusal=str(exc))


def _zip_write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, _FROZEN_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data)


def write_compat(output: PathLike, payload: bytes, *, name: Optional[str] = None,
                 build_id: Optional[str] = None, backend: str = "marco-kgpack",
                 generator: str = "") -> dict[str, Any]:
    """Wrap a kgpack into a deterministic compat ``.mco``. Returns the manifest.

    The same payload and arguments always produce byte-identical output.
    """
    pack_manifest = _read_pack_manifest(payload, verify=True, where="payload")
    payload_sha = _sha256(payload)
    manifest = {
        "format": "mco",
        "container": COMPAT_CONTAINER,
        "container_version": COMPAT_VERSION,
        "api": 1,
        "name": name,
        "build_id": build_id or "sha256-" + payload_sha[:12],
        "generator": generator,
        "payload": {"kind": "kgpack", "path": PAYLOAD_NAME, "bytes": len(payload),
                    "sha256": payload_sha, "kgpack_version": pack_manifest.get("version")},
        "runtime": {"backend": backend},
        "model": pack_manifest.get("model"),
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.tmp-{os.getpid()}")
    try:
        with zipfile.ZipFile(temporary, "w") as zf:
            _zip_write(zf, MANIFEST_NAME, (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                                      separators=(",", ":")) + "\n").encode("utf-8"))
            _zip_write(zf, PAYLOAD_NAME, payload)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def write_native(output: PathLike, payload: bytes, *, name: Optional[str] = None,
                 build_id: Optional[str] = None, generator: str = "") -> dict[str, Any]:
    """Write the pack ``payload`` as an MCO Format 1 file. Returns its manifest.

    The same payload and arguments always produce byte-identical output.
    """
    from .native.pack import write_model
    pack_manifest = _read_pack_manifest(payload, verify=True, where="payload")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        members = {item["path"]: zf.read(item["path"]) for item in pack_manifest["files"]}
    if not members:
        raise CompileError("the pack has no members")
    return write_model(output, pack_manifest, members, source_sha256=_sha256(payload),
                       source_bytes=len(payload), name=name, build_id=build_id, generator=generator)
