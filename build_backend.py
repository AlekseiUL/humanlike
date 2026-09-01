"""Setuptools PEP 517 backend with deterministic, owner-neutral source archives."""

from __future__ import annotations

import gzip
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from setuptools.build_meta import (
    build_editable,
    build_wheel,
    get_requires_for_build_editable,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel,
)
from setuptools.build_meta import (
    build_sdist as _setuptools_build_sdist,
)


def _source_date_epoch() -> int:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "0")
    try:
        epoch = int(raw)
    except ValueError as error:
        raise RuntimeError("SOURCE_DATE_EPOCH must be an integer") from error
    if not 0 <= epoch <= 2**32 - 1:
        raise RuntimeError("SOURCE_DATE_EPOCH is outside the supported range")
    return epoch


def _normalize_sdist(archive_path: Path, *, epoch: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        dir=archive_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with (
            tarfile.open(archive_path, mode="r:gz") as source,
            temporary_path.open("wb") as raw_output,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=epoch) as compressed,
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target,
        ):
            for member in source.getmembers():
                member.uid = 0
                member.gid = 0
                member.uname = ""
                member.gname = ""
                member.mtime = epoch
                if member.isdir():
                    member.mode = 0o755
                elif member.isfile():
                    member.mode = 0o755 if member.mode & 0o111 else 0o644
                elif member.issym() or member.islnk():
                    member.mode = 0o777
                else:
                    member.mode = 0o600
                member.pax_headers = {
                    key: value
                    for key, value in member.pax_headers.items()
                    if key not in {"atime", "ctime", "mtime"}
                }
                payload = source.extractfile(member) if member.isfile() else None
                target.addfile(member, payload)
        temporary_path.chmod(0o644)
        os.replace(temporary_path, archive_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """Build with setuptools, then remove host identity and clock variance."""
    filename = _setuptools_build_sdist(sdist_directory, config_settings)
    _normalize_sdist(Path(sdist_directory) / filename, epoch=_source_date_epoch())
    return filename


__all__ = [
    "build_editable",
    "build_sdist",
    "build_wheel",
    "get_requires_for_build_editable",
    "get_requires_for_build_sdist",
    "get_requires_for_build_wheel",
    "prepare_metadata_for_build_editable",
    "prepare_metadata_for_build_wheel",
]
