"""Dependency-free, deterministic PEP 517 backend for the bounded root facade."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable

NAME = "triadicbrain"
VERSION = "0.1.0a0.dev2"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
SDIST_ROOT = f"{NAME}-{VERSION}"
WHEEL_NAME = f"{NAME}-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"{SDIST_ROOT}.tar.gz"
ROOT = Path(__file__).resolve().parent
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
INHERITED_SOURCE_ROOTS = (
    Path("components/CoherenceLattice/python/src"),
    Path("components/Sophia/python/src"),
    Path("components/uvlm-publications/python/src"),
)
EXPECTED_INHERITED_FILE_COUNT = 62
MPL_LICENSE_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
LICENSE_FILES = (
    ("LICENSE", MPL_LICENSE_SHA256),
    ("licenses/Unicode-3.0.txt", UNICODE_LICENSE_SHA256),
)
SDIST_DOCUMENTS = (
    "AI_ASSISTANCE_DISCLOSURE.md",
    "CONTRIBUTORS.md",
    "DEPENDENCIES.md",
    "LICENSE",
    "LICENSE_SCOPE.md",
    "NOTICE",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "licenses/Unicode-3.0.txt",
)


def _metadata() -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        "Name: triadicbrain\n"
        "Version: 0.1.0a0.dev2\n"
        "Summary: Private, offline alpha-staging facade for bounded Triadic Brain review\n"
        "Requires-Python: >=3.12\n"
        "License-Expression: MPL-2.0\n"
        "License-File: LICENSE\n"
        "License-File: licenses/Unicode-3.0.txt\n"
        "Classifier: Development Status :: 2 - Pre-Alpha\n"
        "Classifier: License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)\n"
        "Classifier: Programming Language :: Python :: 3.12\n"
        "Classifier: Operating System :: OS Independent\n"
        "\n"
    ).encode("utf-8")


def _wheel_metadata() -> bytes:
    return (
        "Wheel-Version: 1.0\n"
        "Generator: triadicbrain-stdlib-backend\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("ascii")


def _entry_points() -> bytes:
    return b"[console_scripts]\ntriadicbrain = triadicbrain.cli:main\n"


def _facade_files() -> list[tuple[str, bytes]]:
    root = ROOT / "src" / "triadicbrain"
    rows: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(ROOT / "src").as_posix()
        if (
            "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
            or any(part.endswith((".egg-info", ".dist-info")) for part in path.parts)
        ):
            continue
        if path.suffix not in {".py", ".json"}:
            raise RuntimeError(f"unexpected package member: {relative}")
        rows.append((relative, path.read_bytes()))
    names = [name for name, _ in rows]
    if not rows or names != sorted(names) or len(names) != len(set(name.casefold() for name in names)):
        raise RuntimeError("package member topology invalid")
    return rows


def _inherited_files() -> list[tuple[str, str, bytes]]:
    rows: list[tuple[str, str, bytes]] = []
    for relative_root in INHERITED_SOURCE_ROOTS:
        source_root = ROOT / relative_root
        if not source_root.is_dir() or source_root.is_symlink():
            raise RuntimeError(f"inherited package root unavailable: {relative_root.as_posix()}")
        for path in sorted(source_root.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not path.is_file():
                continue
            wheel_name = path.relative_to(source_root).as_posix()
            source_name = path.relative_to(ROOT).as_posix()
            if (
                "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
                or any(part.endswith((".egg-info", ".dist-info")) for part in path.parts)
            ):
                continue
            if path.suffix not in {".py", ".json"}:
                raise RuntimeError(f"unexpected inherited package member: {source_name}")
            rows.append((source_name, wheel_name, path.read_bytes()))
    rows.sort(key=lambda row: row[1])
    wheel_names = [wheel_name for _, wheel_name, _ in rows]
    if (
        len(rows) != EXPECTED_INHERITED_FILE_COUNT
        or wheel_names != sorted(wheel_names)
        or len(wheel_names) != len(set(name.casefold() for name in wheel_names))
        or {name.split("/", 1)[0] for name in wheel_names} != {"atlas", "coherence", "sophia"}
    ):
        raise RuntimeError("inherited package boundary mismatch")
    return rows


def _package_files() -> list[tuple[str, bytes]]:
    rows = _facade_files()
    rows.extend((wheel_name, payload) for _, wheel_name, payload in _inherited_files())
    names = [name for name, _ in rows]
    if len(names) != len(set(name.casefold() for name in names)):
        raise RuntimeError("wheel member collision")
    return sorted(rows)


def _license_files() -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    for relative, expected_sha256 in LICENSE_FILES:
        path = ROOT.joinpath(*relative.split("/"))
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"license input unavailable: {relative}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RuntimeError(f"license input identity mismatch: {relative}")
        rows.append((relative, payload))
    return rows


def _record_hash(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}"


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits = 0
    return info


def _wheel_rows() -> list[tuple[str, bytes]]:
    rows = _package_files()
    rows.extend(
        (f"{DIST_INFO}/licenses/{relative}", payload)
        for relative, payload in _license_files()
    )
    rows.extend(
        [
            (f"{DIST_INFO}/METADATA", _metadata()),
            (f"{DIST_INFO}/WHEEL", _wheel_metadata()),
            (f"{DIST_INFO}/entry_points.txt", _entry_points()),
        ]
    )
    record_name = f"{DIST_INFO}/RECORD"
    record = "".join(
        f"{name},{_record_hash(payload)},{len(payload)}\n" for name, payload in sorted(rows)
    )
    record += f"{record_name},,\n"
    rows.append((record_name, record.encode("utf-8")))
    return sorted(rows)


def _write_wheel(path: Path) -> None:
    with zipfile.ZipFile(path, "w", allowZip64=False) as archive:
        archive.comment = b""
        for name, payload in _wheel_rows():
            archive.writestr(_zip_info(name), payload)


def _sdist_files() -> list[tuple[str, bytes]]:
    rows = [
        ("_triadicbrain_build_backend.py", (ROOT / "_triadicbrain_build_backend.py").read_bytes()),
        ("pyproject.toml", (ROOT / "pyproject.toml").read_bytes()),
    ]
    for name, payload in _facade_files():
        rows.append((f"src/{name}", payload))
    for source_name, _wheel_name, payload in _inherited_files():
        rows.append((source_name, payload))
    tests = ROOT / "tests"
    if tests.is_dir():
        for path in sorted(tests.rglob("test_*.py"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("test source topology invalid")
            rows.append((path.relative_to(ROOT).as_posix(), path.read_bytes()))
    for relative in SDIST_DOCUMENTS:
        path = ROOT.joinpath(*relative.split("/"))
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"sdist document unavailable: {relative}")
        rows.append((relative, path.read_bytes()))
    rows.append(("PKG-INFO", _metadata()))
    return sorted(rows)


def _tar_bytes(rows: Iterable[tuple[str, bytes]]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for relative, payload in rows:
            name = f"{SDIST_ROOT}/{relative}"
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(payload))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, compresslevel=9, mtime=0) as stream:
        stream.write(raw.getvalue())
    return compressed.getvalue()


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    return []


def get_requires_for_build_sdist(config_settings=None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None) -> str:
    target = Path(metadata_directory) / DIST_INFO
    target.mkdir(parents=True, exist_ok=False)
    (target / "METADATA").write_bytes(_metadata())
    (target / "WHEEL").write_bytes(_wheel_metadata())
    (target / "entry_points.txt").write_bytes(_entry_points())
    return DIST_INFO


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None) -> str:
    target = Path(wheel_directory)
    target.mkdir(parents=True, exist_ok=True)
    output = target / WHEEL_NAME
    if os.path.lexists(output):
        raise RuntimeError("wheel output already exists")
    _write_wheel(output)
    return WHEEL_NAME


def build_sdist(sdist_directory, config_settings=None) -> str:
    target = Path(sdist_directory)
    target.mkdir(parents=True, exist_ok=True)
    output = target / SDIST_NAME
    if os.path.lexists(output):
        raise RuntimeError("sdist output already exists")
    output.write_bytes(_tar_bytes(_sdist_files()))
    return SDIST_NAME
