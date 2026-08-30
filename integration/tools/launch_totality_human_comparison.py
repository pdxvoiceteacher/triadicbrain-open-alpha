"""Start the raw-first, governed-second loopback usability comparator.

This launcher validates the exact external PRODUCT_TASK_01 evidence and its
unsubmitted comparator before opening anything.  Human observations are
captured by the loopback surface without manual JSON and remain distinct from
an Atlas final decision.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator


RAW_BOUNDARY_POSTURE_SCHEMA = "uvlm.triadic.totality.product_task_raw_boundary.v1"
RAW_BOUNDARY_POSTURE = "RAW_FREE_REVIEW_PROJECTION"
RAW_BOUNDARY_FILENAME = "RAW_BOUNDARY_POSTURE.json"
SEALED_RAW_RELATIVE = "sealed_run/sonya/raw_output.quarantine"
SEALED_RAW_INNER_RELATIVE = "sonya/raw_output.quarantine"
SEALED_ARCHIVE_RELATIVE = "sealed_run.zip"
ROUTE_RECEIPT_SCHEMA_V1 = "uvlm.triadicgate.totality_product_route_receipt.v1"
ROUTE_RECEIPT_SCHEMA_V2 = "uvlm.triadicgate.totality_product_route_receipt.v2"
MAX_REVIEW_MEMBER_BYTES = 16 * 1024 * 1024
MAX_REVIEW_TREE_BYTES = 64 * 1024 * 1024
MAX_REVIEW_MEMBERS = 4096
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
FINAL_DISCLAIMER = (
    "THIS HANDOFF IS BOUNDED LEAD-DEVELOPER EVIDENCE AND A REPAIR COMMISSION. "
    "IT IS NOT SCIENTIFIC CONFIRMATION, CANONIZATION, MERGE AUTHORITY, "
    "PUBLICATION, DEPLOYMENT, TRAINING, MEMORY WRITE, MODEL AUTHORITY, "
    "PUBLIC RELEASE AUTHORITY, OR TRUTH CERTIFICATION."
)
NO_EFFECTS = {
    "canonization": False,
    "deployment": False,
    "memory_write": False,
    "merge": False,
    "model_authority": False,
    "network": False,
    "private_release": False,
    "provider_call": False,
    "public_release": False,
    "publication": False,
    "release": False,
    "training": False,
    "truth_certification": False,
}
HEX_DIGITS = frozenset("0123456789abcdef")


class ComparisonLaunchError(RuntimeError):
    """The human comparison evidence is unsafe, altered, or not ready."""


def _load_task_tool():
    path = Path(__file__).resolve().with_name("run_substantive_totality_task.py")
    spec = importlib.util.spec_from_file_location("_substantive_totality_task", path)
    if spec is None or spec.loader is None:
        raise ComparisonLaunchError("TASK_LAUNCHER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Present one stable public error type from this launcher even though the
    # task helper is loaded by exact file path instead of ambient sys.path.
    module.SubstantiveTaskError = ComparisonLaunchError
    return module


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in HEX_DIGITS for character in value)
    )


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ComparisonLaunchError(f"UNSAFE_RELATIVE_PATH:{label}")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise ComparisonLaunchError(f"UNSAFE_RELATIVE_PATH:{label}")
    return value


def _receipt_artifact_name(
    value: Any,
    *,
    route_schema: Any,
    expected: str,
    label: str,
) -> str:
    """Read portable v2 names and bounded legacy v1 host paths.

    The v1 branch deliberately parses with both path grammars so a predecessor
    receipt made on either operating system can be reviewed on the other.  It
    returns only the expected stable name and therefore cannot re-emit the
    predecessor host path into new evidence.
    """

    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "\r\n\x00")
    ):
        raise ComparisonLaunchError(f"RECEIPT_ARTIFACT_PATH_INVALID:{label}")
    if route_schema == ROUTE_RECEIPT_SCHEMA_V2:
        if (
            value != expected
            or PurePosixPath(value).name != value
            or PureWindowsPath(value).name != value
            or "/" in value
            or "\\" in value
            or ":" in value
        ):
            raise ComparisonLaunchError(f"NONPORTABLE_V2_RECEIPT_PATH:{label}")
        return expected
    if route_schema == ROUTE_RECEIPT_SCHEMA_V1:
        legacy_names = {
            PureWindowsPath(value).name,
            PurePosixPath(value).name,
        }
        if expected not in legacy_names:
            raise ComparisonLaunchError(f"LEGACY_RECEIPT_PATH_INVALID:{label}")
        return expected
    raise ComparisonLaunchError(f"ROUTE_RECEIPT_SCHEMA_UNSUPPORTED:{label}")


def _safe_member(
    root: Path,
    relative: str,
    label: str,
    *,
    must_exist: bool = True,
) -> Path:
    normalized = _safe_relative(relative, label)
    bounded_root = root.resolve(strict=True)
    candidate = bounded_root
    for part in PurePosixPath(normalized).parts:
        candidate = candidate / part
        if os.path.lexists(candidate):
            if _link_like(candidate):
                raise ComparisonLaunchError(f"LINK_OR_JUNCTION_PROHIBITED:{label}")
            try:
                candidate.resolve(strict=True).relative_to(bounded_root)
            except (OSError, ValueError) as exc:
                raise ComparisonLaunchError(f"PATH_ESCAPE_OR_CHANGED:{label}") from exc
        elif candidate != bounded_root / normalized and must_exist:
            raise ComparisonLaunchError(f"INPUT_UNSAFE_OR_MISSING:{label}")
    if must_exist:
        try:
            candidate.resolve(strict=True).relative_to(bounded_root)
        except (OSError, ValueError) as exc:
            raise ComparisonLaunchError(f"INPUT_UNSAFE_OR_MISSING:{label}") from exc
    else:
        try:
            candidate.resolve(strict=False).relative_to(bounded_root)
        except (OSError, ValueError) as exc:
            raise ComparisonLaunchError(f"PATH_ESCAPE_OR_CHANGED:{label}") from exc
    return candidate


def _read_object_member(
    task_tool: Any,
    root: Path,
    relative: str,
    label: str,
) -> tuple[dict[str, Any], bytes]:
    path = _safe_member(root, relative, label)
    return task_tool._read_object(path, label)


def _read_bytes_member(
    task_tool: Any,
    root: Path,
    relative: str,
    label: str,
    maximum: int,
) -> bytes:
    path = _safe_member(root, relative, label)
    return task_tool._read_bytes(path, label, maximum)


def _hash_file(task_tool: Any, root: Path, relative: str, label: str) -> str:
    return task_tool._sha(
        _read_bytes_member(task_tool, root, relative, label, task_tool.MAX_JSON_BYTES)
    )


def _hash_regular_file(path: Path, label: str, maximum: int) -> tuple[str, int]:
    if _link_like(path) or not path.is_file():
        raise ComparisonLaunchError(f"INPUT_UNSAFE_OR_MISSING:{label}")
    before = _fingerprint(path)
    if not stat.S_ISREG(before[2]) or before[3] <= 0 or before[3] > maximum:
        raise ComparisonLaunchError(f"INPUT_SIZE_OR_TYPE_INVALID:{label}")
    digest = hashlib.sha256()
    observed = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                observed += len(chunk)
                if observed > maximum:
                    raise ComparisonLaunchError(
                        f"INPUT_SIZE_OR_TYPE_INVALID:{label}"
                    )
                digest.update(chunk)
    except ComparisonLaunchError:
        raise
    except OSError as exc:
        raise ComparisonLaunchError(f"INPUT_READ_FAILED:{label}") from exc
    if observed != before[3] or _fingerprint(path) != before:
        raise ComparisonLaunchError(f"INPUT_CHANGED_DURING_READ:{label}")
    return digest.hexdigest(), observed


def _fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    details = path.stat(follow_symlinks=False)
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
    )


def _snapshot_tree(root: Path, label: str) -> list[dict[str, Any]]:
    if _link_like(root) or not root.is_dir():
        raise ComparisonLaunchError(f"TREE_ROOT_UNSAFE:{label}")
    bounded = root.resolve(strict=True)
    pending = [bounded]
    records: list[dict[str, Any]] = []
    total_bytes = 0
    while pending:
        directory = pending.pop()
        if _link_like(directory):
            raise ComparisonLaunchError(f"LINK_OR_JUNCTION_PROHIBITED:{label}")
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ComparisonLaunchError(f"TREE_READ_FAILED:{label}") from exc
        descendants: list[Path] = []
        for child in children:
            try:
                relative = child.relative_to(bounded).as_posix()
            except ValueError as exc:
                raise ComparisonLaunchError(f"TREE_MEMBER_ESCAPES:{label}") from exc
            if _link_like(child):
                raise ComparisonLaunchError(f"LINK_OR_JUNCTION_PROHIBITED:{label}/{relative}")
            try:
                resolved = child.resolve(strict=True)
                resolved.relative_to(bounded)
                details = child.stat(follow_symlinks=False)
            except (OSError, ValueError) as exc:
                raise ComparisonLaunchError(f"TREE_MEMBER_CHANGED:{label}/{relative}") from exc
            mode = details.st_mode
            if stat.S_ISDIR(mode):
                kind = "DIRECTORY"
                descendants.append(child)
            elif stat.S_ISREG(mode):
                kind = "FILE"
                if details.st_size > MAX_REVIEW_MEMBER_BYTES:
                    raise ComparisonLaunchError(
                        f"TREE_MEMBER_SIZE_LIMIT_EXCEEDED:{label}/{relative}"
                    )
                total_bytes += details.st_size
                if total_bytes > MAX_REVIEW_TREE_BYTES:
                    raise ComparisonLaunchError(f"TREE_SIZE_LIMIT_EXCEEDED:{label}")
            else:
                raise ComparisonLaunchError(f"IRREGULAR_TREE_MEMBER:{label}/{relative}")
            records.append(
                {
                    "path": relative,
                    "kind": kind,
                    "fingerprint": _fingerprint(child),
                }
            )
            if len(records) > MAX_REVIEW_MEMBERS:
                raise ComparisonLaunchError(f"TREE_MEMBER_LIMIT_EXCEEDED:{label}")
        pending.extend(reversed(descendants))
    return sorted(records, key=lambda row: row["path"])


def _read_bounded_regular(
    path: Path,
    expected_fingerprint: tuple[int, int, int, int, int],
    label: str,
) -> bytes:
    if _link_like(path):
        raise ComparisonLaunchError(f"LINK_OR_JUNCTION_PROHIBITED:{label}")
    before = _fingerprint(path)
    if before != expected_fingerprint or not stat.S_ISREG(before[2]):
        raise ComparisonLaunchError(f"TREE_MEMBER_CHANGED:{label}")
    size = before[3]
    if size > MAX_REVIEW_MEMBER_BYTES:
        raise ComparisonLaunchError(f"TREE_MEMBER_SIZE_LIMIT_EXCEEDED:{label}")
    try:
        with path.open("rb") as stream:
            raw = stream.read(size + 1)
    except OSError as exc:
        raise ComparisonLaunchError(f"TREE_MEMBER_READ_FAILED:{label}") from exc
    if len(raw) != size or _fingerprint(path) != before:
        raise ComparisonLaunchError(f"TREE_MEMBER_CHANGED:{label}")
    return raw


def _assert_snapshot_unchanged(
    root: Path,
    expected: list[dict[str, Any]],
    label: str,
) -> None:
    if _snapshot_tree(root, label) != expected:
        raise ComparisonLaunchError(f"TREE_CHANGED_DURING_PROJECTION:{label}")


def _copy_tree_from_snapshot(
    source: Path,
    destination: Path,
    snapshot: list[dict[str, Any]],
    label: str,
) -> None:
    try:
        destination.mkdir()
    except OSError as exc:
        raise ComparisonLaunchError(f"TEMPORARY_PROJECTION_CREATE_FAILED:{label}") from exc
    directories = sorted(
        (row for row in snapshot if row["kind"] == "DIRECTORY"),
        key=lambda row: (len(PurePosixPath(row["path"]).parts), row["path"]),
    )
    for row in directories:
        target = destination.joinpath(*PurePosixPath(row["path"]).parts)
        try:
            target.mkdir()
        except OSError as exc:
            raise ComparisonLaunchError(
                f"TEMPORARY_PROJECTION_CREATE_FAILED:{label}/{row['path']}"
            ) from exc
    for row in (item for item in snapshot if item["kind"] == "FILE"):
        if row["path"].casefold() == SEALED_RAW_INNER_RELATIVE.casefold():
            raise ComparisonLaunchError("SOURCE_RAW_QUARANTINE_PRESENT")
        source_path = source.joinpath(*PurePosixPath(row["path"]).parts)
        raw = _read_bounded_regular(
            source_path,
            row["fingerprint"],
            f"{label}/{row['path']}",
        )
        target = destination.joinpath(*PurePosixPath(row["path"]).parts)
        try:
            with target.open("xb") as stream:
                stream.write(raw)
        except OSError as exc:
            raise ComparisonLaunchError(
                f"TEMPORARY_PROJECTION_WRITE_FAILED:{label}/{row['path']}"
            ) from exc
    _assert_snapshot_unchanged(source, snapshot, label)


def _checksum_rows(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ComparisonLaunchError("SEALED_CHECKSUMS_INVALID") from exc
    if not text.endswith("\n") or "\r" in text or "\x00" in text:
        raise ComparisonLaunchError("SEALED_CHECKSUMS_INVALID")
    rows: dict[str, str] = {}
    previous = ""
    for line in text.splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise ComparisonLaunchError("SEALED_CHECKSUMS_INVALID")
        digest, relative = line[:64], _safe_relative(line[66:], "sealed checksums")
        if not _hex(digest) or relative <= previous or relative in rows:
            raise ComparisonLaunchError("SEALED_CHECKSUMS_INVALID")
        rows[relative] = digest
        previous = relative
    if not rows:
        raise ComparisonLaunchError("SEALED_CHECKSUMS_INVALID")
    return rows


def _manifest_raw_row(document: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise ComparisonLaunchError(f"SEALED_MANIFEST_INVALID:{label}")
    matches = [row for row in rows if isinstance(row, dict) and row.get("path") == SEALED_RAW_INNER_RELATIVE]
    if len(matches) != 1 or set(matches[0]) != {"path", "sha256", "bytes"}:
        raise ComparisonLaunchError(f"SEALED_MANIFEST_RAW_BINDING_INVALID:{label}")
    return matches[0]


def _validate_archive_binding(
    task_tool: Any,
    root: Path,
    value: Any,
    label: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "excluded_relative_path",
        "declared_sha256",
        "declared_bytes",
        "route_receipt_path",
        "route_receipt_exact_binding",
        "sidecar",
        "archive_bytes_read",
    }:
        raise ComparisonLaunchError(f"RAW_BOUNDARY_ARCHIVE_BINDING_INVALID:{label}")
    archive_relative = _safe_relative(value["excluded_relative_path"], label)
    declared_bytes = value["declared_bytes"]
    if (
        not _hex(value["declared_sha256"])
        or not isinstance(declared_bytes, int)
        or isinstance(declared_bytes, bool)
        or declared_bytes <= 0
        or value["route_receipt_exact_binding"] is not True
        or value["archive_bytes_read"] is not False
    ):
        raise ComparisonLaunchError(f"RAW_BOUNDARY_ARCHIVE_BINDING_INVALID:{label}")
    route_relative = _safe_relative(value["route_receipt_path"], f"{label}/route")
    route, route_raw = _read_object_member(
        task_tool,
        root,
        route_relative,
        f"{label}/route receipt",
    )
    if route_raw != task_tool._canonical(route):
        raise ComparisonLaunchError(f"RAW_BOUNDARY_ROUTE_RECEIPT_NONCANONICAL:{label}")
    export = route.get("export_zip")
    zip_path = export.get("zip_path") if isinstance(export, dict) else None
    route_schema = route.get("schema_id")
    portable_zip_name = _receipt_artifact_name(
        zip_path,
        route_schema=route_schema,
        expected=PurePosixPath(archive_relative).name,
        label=f"{label}/zip",
    )
    if (
        not isinstance(export, dict)
        or export.get("valid") is not True
        or export.get("authority_effect") != "NONE"
        or export.get("zip_sha256") != value["declared_sha256"]
        or export.get("zip_bytes") != declared_bytes
        or portable_zip_name != PurePosixPath(archive_relative).name
        or (
            route_schema == ROUTE_RECEIPT_SCHEMA_V2
            and route.get("receipt_path_contract")
            != "STABLE_ARTIFACT_NAMES_ONLY"
        )
    ):
        raise ComparisonLaunchError(f"RAW_BOUNDARY_ROUTE_ARCHIVE_BINDING_INVALID:{label}")
    sidecar = value["sidecar"]
    if sidecar is not None:
        if not isinstance(sidecar, dict) or set(sidecar) != {"path", "sha256", "bytes"}:
            raise ComparisonLaunchError(f"RAW_BOUNDARY_ARCHIVE_SIDECAR_INVALID:{label}")
        sidecar_relative = _safe_relative(sidecar["path"], f"{label}/sidecar")
        sidecar_raw = _read_bytes_member(
            task_tool,
            root,
            sidecar_relative,
            f"{label}/sidecar",
            task_tool.MAX_JSON_BYTES,
        )
        if (
            not _hex(sidecar["sha256"])
            or not isinstance(sidecar["bytes"], int)
            or isinstance(sidecar["bytes"], bool)
            or sidecar["bytes"] != len(sidecar_raw)
            or task_tool._sha(sidecar_raw) != sidecar["sha256"]
            or sidecar_raw
            != f"{value['declared_sha256']}  {PurePosixPath(archive_relative).name}\n".encode(
                "ascii"
            )
            or export.get("zip_sidecar_sha256") != sidecar["sha256"]
            or _receipt_artifact_name(
                export.get("zip_sidecar_path"),
                route_schema=route_schema,
                expected=PurePosixPath(sidecar_relative).name,
                label=f"{label}/zip-sidecar",
            )
            != PurePosixPath(sidecar_relative).name
        ):
            raise ComparisonLaunchError(f"RAW_BOUNDARY_ARCHIVE_SIDECAR_INVALID:{label}")
    return archive_relative


def _validate_route_export_receipt(task_tool: Any, root: Path) -> dict[str, Any]:
    route, route_raw = _read_object_member(
        task_tool, root, "route_receipt.json", "route_receipt.json"
    )
    if route_raw != task_tool._canonical(route):
        raise ComparisonLaunchError("ROUTE_RECEIPT_CANONICAL_ENCODING_REQUIRED")
    schema = route.get("schema_id")
    export = route.get("export_zip")
    if not isinstance(export, dict):
        raise ComparisonLaunchError("ROUTE_EXPORT_RECEIPT_INVALID")
    archive_name = _receipt_artifact_name(
        export.get("zip_path"),
        route_schema=schema,
        expected="sealed_run.zip",
        label="route_receipt/export_zip/zip_path",
    )
    sidecar_name = _receipt_artifact_name(
        export.get("zip_sidecar_path"),
        route_schema=schema,
        expected="sealed_run.zip.sha256",
        label="route_receipt/export_zip/zip_sidecar_path",
    )
    if (
        archive_name != "sealed_run.zip"
        or sidecar_name != "sealed_run.zip.sha256"
        or not _hex(export.get("zip_sha256"))
        or not _hex(export.get("zip_sidecar_sha256"))
        or isinstance(export.get("zip_bytes"), bool)
        or not isinstance(export.get("zip_bytes"), int)
        or export["zip_bytes"] <= 0
        or export.get("authority_effect") != "NONE"
        or export.get("valid") is not True
        or (
            schema == ROUTE_RECEIPT_SCHEMA_V2
            and route.get("receipt_path_contract")
            != "STABLE_ARTIFACT_NAMES_ONLY"
        )
    ):
        raise ComparisonLaunchError("ROUTE_EXPORT_RECEIPT_INVALID")
    archive_path = root / archive_name
    sidecar_path = root / sidecar_name
    if os.path.lexists(archive_path):
        digest, size = _hash_regular_file(
            archive_path, "sealed_run.zip", MAX_ARCHIVE_BYTES
        )
        if digest != export["zip_sha256"] or size != export["zip_bytes"]:
            raise ComparisonLaunchError("ROUTE_ARCHIVE_EXACT_BINDING_INVALID")
    if os.path.lexists(sidecar_path):
        sidecar_raw = task_tool._read_bytes(sidecar_path, sidecar_name, 4096)
        expected = f"{export['zip_sha256']}  sealed_run.zip\n".encode("ascii")
        if (
            sidecar_raw != expected
            or task_tool._sha(sidecar_raw) != export["zip_sidecar_sha256"]
        ):
            raise ComparisonLaunchError("ROUTE_ARCHIVE_SIDECAR_BINDING_INVALID")
    if os.path.lexists(archive_path) and not os.path.lexists(sidecar_path):
        raise ComparisonLaunchError("ROUTE_ARCHIVE_SIDECAR_MISSING")
    return route


def _validate_raw_free_projection(
    task_tool: Any,
    root: Path,
    capture_raw: bytes,
) -> dict[str, Any] | None:
    posture_candidate = root / RAW_BOUNDARY_FILENAME
    if not os.path.lexists(posture_candidate):
        return None
    posture_path = _safe_member(root, RAW_BOUNDARY_FILENAME, RAW_BOUNDARY_FILENAME)
    posture, posture_raw = task_tool._read_object(posture_path, RAW_BOUNDARY_FILENAME)
    if posture_raw != task_tool._canonical(posture):
        raise ComparisonLaunchError("RAW_BOUNDARY_POSTURE_CANONICAL_ENCODING_REQUIRED")
    if set(posture) != {
        "schema_id",
        "raw_lane_captured_candidate_included",
        "sonya_raw_quarantine_included",
        "excluded_relative_paths",
        "raw_bytes_read_for_projection",
        "raw_hash_recomputed",
        "sealed_raw_bindings",
        "prepared_capture_sha256",
        "posture",
        "authority_effect",
        "effects",
        "mandatory_disclaimer",
    }:
        raise ComparisonLaunchError("RAW_BOUNDARY_POSTURE_KEYSET_INVALID")
    if (
        posture["schema_id"] != RAW_BOUNDARY_POSTURE_SCHEMA
        or posture["posture"] != RAW_BOUNDARY_POSTURE
        or posture["raw_lane_captured_candidate_included"] is not True
        or posture["sonya_raw_quarantine_included"] is not False
        or posture["raw_bytes_read_for_projection"] is not False
        or posture["raw_hash_recomputed"] is not False
        or posture["authority_effect"] != "NONE"
        or posture["effects"] != NO_EFFECTS
        or posture["mandatory_disclaimer"] != FINAL_DISCLAIMER
    ):
        raise ComparisonLaunchError("RAW_BOUNDARY_POSTURE_INVALID")
    excluded = posture["excluded_relative_paths"]
    bindings = posture["sealed_raw_bindings"]
    if (
        not isinstance(excluded, list)
        or not excluded
        or any(not isinstance(item, str) for item in excluded)
        or excluded != sorted(excluded)
        or len(excluded) != len(set(excluded))
        or not isinstance(bindings, list)
        or not bindings
    ):
        raise ComparisonLaunchError("RAW_BOUNDARY_POSTURE_INVENTORY_INVALID")
    expected_excluded: set[str] = set()
    normalized_bindings: list[dict[str, Any]] = []
    prior_raw = ""
    for index, binding in enumerate(bindings):
        label = f"sealed_raw_bindings/{index}"
        if not isinstance(binding, dict) or set(binding) != {
            "excluded_relative_path",
            "declared_sealed_raw_sha256",
            "declared_sealed_raw_bytes",
            "raw_hash_recomputed",
            "core_manifest_sha256",
            "sealed_artifact_manifest_sha256",
            "run_manifest_sha256",
            "raw_bearing_archive",
        }:
            raise ComparisonLaunchError(f"RAW_BOUNDARY_BINDING_INVALID:{index}")
        raw_relative = _safe_relative(binding["excluded_relative_path"], label)
        raw_parts = PurePosixPath(raw_relative).parts
        raw_bytes = binding["declared_sealed_raw_bytes"]
        if (
            raw_relative <= prior_raw
            or len(raw_parts) < 3
            or tuple(part.casefold() for part in raw_parts[-2:])
            != ("sonya", "raw_output.quarantine")
            or not _hex(binding["declared_sealed_raw_sha256"])
            or not isinstance(raw_bytes, int)
            or isinstance(raw_bytes, bool)
            or raw_bytes <= 0
            or binding["raw_hash_recomputed"] is not False
            or any(
                not _hex(binding[key])
                for key in (
                    "core_manifest_sha256",
                    "sealed_artifact_manifest_sha256",
                    "run_manifest_sha256",
                )
            )
        ):
            raise ComparisonLaunchError(f"RAW_BOUNDARY_BINDING_INVALID:{index}")
        prior_raw = raw_relative
        expected_excluded.add(raw_relative)
        archive_relative = _validate_archive_binding(
            task_tool,
            root,
            binding["raw_bearing_archive"],
            f"{label}/archive",
        )
        if archive_relative is not None:
            expected_excluded.add(archive_relative)
        normalized_bindings.append(binding)
    if excluded != sorted(expected_excluded):
        raise ComparisonLaunchError("RAW_BOUNDARY_EXCLUDED_INVENTORY_MISMATCH")
    for relative in excluded:
        candidate = _safe_member(
            root,
            _safe_relative(relative, "excluded raw member"),
            f"excluded raw member/{relative}",
            must_exist=False,
        )
        if os.path.lexists(candidate):
            raise ComparisonLaunchError(f"RAW_BOUNDARY_EXCLUDED_MEMBER_PRESENT:{relative}")
    selected = [
        binding
        for binding in normalized_bindings
        if binding["excluded_relative_path"] == SEALED_RAW_RELATIVE
    ]
    if len(selected) != 1:
        raise ComparisonLaunchError("SEALED_RUN_RAW_BOUNDARY_BINDING_MISSING")
    binding = selected[0]
    archive = binding["raw_bearing_archive"]
    if not isinstance(archive, dict) or archive.get("excluded_relative_path") != SEALED_ARCHIVE_RELATIVE:
        raise ComparisonLaunchError("SEALED_RUN_ARCHIVE_BOUNDARY_BINDING_MISSING")
    capture_sha256 = task_tool._sha(capture_raw)
    if (
        posture["prepared_capture_sha256"] != capture_sha256
        or binding["declared_sealed_raw_sha256"] != capture_sha256
        or binding["declared_sealed_raw_bytes"] != len(capture_raw)
    ):
        raise ComparisonLaunchError("CAPTURE_SEALED_RAW_IDENTITY_MISMATCH")

    manifest_specs = (
        ("sealed_run/core_manifest.json", "artifacts", "core_manifest_sha256"),
        ("sealed_run/sealed_artifact_manifest.json", "files", "sealed_artifact_manifest_sha256"),
        ("sealed_run/run_manifest.json", "artifacts", "run_manifest_sha256"),
    )
    expected_raw_row = {
        "path": SEALED_RAW_INNER_RELATIVE,
        "sha256": capture_sha256,
        "bytes": len(capture_raw),
    }
    for relative, row_key, hash_key in manifest_specs:
        document, raw = _read_object_member(task_tool, root, relative, relative)
        if raw != task_tool._canonical(document) or task_tool._sha(raw) != binding[hash_key]:
            raise ComparisonLaunchError(f"SEALED_MANIFEST_BINDING_INVALID:{relative}")
        if _manifest_raw_row(document, row_key, relative) != expected_raw_row:
            raise ComparisonLaunchError(f"SEALED_MANIFEST_RAW_BINDING_INVALID:{relative}")
    checksums_raw = _read_bytes_member(
        task_tool,
        root,
        "sealed_run/checksums.sha256",
        "sealed checksums",
        task_tool.MAX_JSON_BYTES,
    )
    checksums = _checksum_rows(checksums_raw)
    if checksums.get(SEALED_RAW_INNER_RELATIVE) != capture_sha256:
        raise ComparisonLaunchError("SEALED_CHECKSUM_RAW_BINDING_INVALID")
    sealed_root = _safe_member(root, "sealed_run", "sealed run")
    sealed_snapshot = _snapshot_tree(sealed_root, "sealed run")
    physical_files = {row["path"] for row in sealed_snapshot if row["kind"] == "FILE"}
    if physical_files != (set(checksums) - {SEALED_RAW_INNER_RELATIVE}) | {"checksums.sha256"}:
        raise ComparisonLaunchError("RAW_FREE_SEALED_INVENTORY_MISMATCH")
    return {
        "capture_relative": "raw_lane/captured_semantic.json",
        "capture_sha256": capture_sha256,
        "capture_bytes": len(capture_raw),
        "sealed_root": sealed_root,
    }


@contextlib.contextmanager
def _review_run_projection(paths: dict[str, Any]) -> Iterator[tuple[Path, Path]]:
    projection = paths.get("raw_free_projection")
    if projection is None:
        yield paths["sealed_run"], paths["comparison_root"]
        return
    task_tool = paths["task_tool"]
    task_root = paths["task_root"]
    capture_raw = _read_bytes_member(
        task_tool,
        task_root,
        projection["capture_relative"],
        "raw-lane captured semantic",
        task_tool.MAX_JSON_BYTES,
    )
    if (
        task_tool._sha(capture_raw) != projection["capture_sha256"]
        or len(capture_raw) != projection["capture_bytes"]
    ):
        raise ComparisonLaunchError("CAPTURE_CHANGED_BEFORE_REVIEW")
    source = projection["sealed_root"]
    snapshot = _snapshot_tree(source, "packaged sealed run")
    with tempfile.TemporaryDirectory(prefix="uvlm-raw-free-review-") as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        destination = temporary_root / "sealed_run"
        _copy_tree_from_snapshot(source, destination, snapshot, "packaged sealed run")
        raw_target = destination / "sonya" / "raw_output.quarantine"
        if raw_target.parent.is_symlink() or _link_like(raw_target.parent) or raw_target.exists():
            raise ComparisonLaunchError("TEMPORARY_RAW_TARGET_UNSAFE")
        try:
            with raw_target.open("xb") as stream:
                stream.write(capture_raw)
        except OSError as exc:
            raise ComparisonLaunchError("TEMPORARY_RAW_RECONSTRUCTION_FAILED") from exc
        reconstructed = _read_bounded_regular(
            raw_target,
            _fingerprint(raw_target),
            "temporary reconstructed raw quarantine",
        )
        if (
            reconstructed != capture_raw
            or hashlib.sha256(reconstructed).hexdigest() != projection["capture_sha256"]
        ):
            raise ComparisonLaunchError("TEMPORARY_RAW_RECONSTRUCTION_MISMATCH")
        _assert_snapshot_unchanged(source, snapshot, "packaged sealed run")
        try:
            # The reconstructed raw-bearing run remains temporary, but the UI
            # claims the real task-root output directly.  A completed human
            # submission is therefore durable before the loopback process
            # exits, and there is no deferred rename publication window.
            yield destination, paths["comparison_root"]
        finally:
            _assert_snapshot_unchanged(source, snapshot, "packaged sealed run")


def validate_task_root(task_root: Path) -> dict[str, Any]:
    task_tool = _load_task_tool()
    if _link_like(task_root):
        raise ComparisonLaunchError("TASK_ROOT_UNSAFE")
    root = task_root.resolve(strict=True)
    if _link_like(root) or not root.is_dir():
        raise ComparisonLaunchError("TASK_ROOT_UNSAFE")
    profile, _, _ = task_tool.load_authenticated_inputs()
    status, status_raw = _read_object_member(
        task_tool, root, "task_status.json", "task_status.json"
    )
    if status_raw != task_tool._canonical(status):
        raise ComparisonLaunchError("TASK_STATUS_CANONICAL_ENCODING_REQUIRED")
    required_status = {
        "authority_effect": "NONE",
        "human_comparator_submitted": False,
        "human_decision_submitted": False,
        "nonauthority": profile["nonauthority"],
        "profile_sha256": task_tool.PROFILE_SHA256,
        "replay_exact_tree_equality": True,
        "schema_id": "uvlm.triadic.totality.product_task_status.v1",
        "sealed_run_root": "sealed_run",
        "status": task_tool.TASK_STATUS,
        "task_id": "PRODUCT_TASK_01",
    }
    if any(status.get(key) != value for key, value in required_status.items()):
        raise ComparisonLaunchError("TASK_NOT_AWAITING_UNSUBMITTED_HUMAN_REVIEW")

    answer_key, answer_key_raw = _read_object_member(
        task_tool,
        root,
        "unsupported_claim_answer_key.json",
        "unsupported_claim_answer_key.json",
    )
    expected_answer_key_raw = task_tool._canonical(
        profile["unsupported_claim_answer_key"]
    )
    if (
        answer_key_raw != task_tool._canonical(answer_key)
        or answer_key_raw != expected_answer_key_raw
    ):
        raise ComparisonLaunchError("ANSWER_KEY_PROFILE_IDENTITY_MISMATCH")
    comparator, comparator_raw = _read_object_member(
        task_tool,
        root,
        "usability_comparator.json",
        "usability_comparator.json",
    )
    if comparator_raw != task_tool._canonical(comparator):
        raise ComparisonLaunchError("COMPARATOR_CANONICAL_ENCODING_REQUIRED")
    task_tool._assert_null_human_fields(comparator)
    if task_tool._sha(comparator_raw) != status.get("usability_comparator_sha256"):
        raise ComparisonLaunchError("COMPARATOR_STATUS_IDENTITY_MISMATCH")

    raw_manifest, raw_manifest_raw = _read_object_member(
        task_tool,
        root,
        "raw_lane/raw_candidate_manifest.json",
        "raw_candidate_manifest.json",
    )
    if raw_manifest_raw != task_tool._canonical(raw_manifest):
        raise ComparisonLaunchError("RAW_LANE_MANIFEST_CANONICAL_ENCODING_REQUIRED")
    if (
        raw_manifest.get("capture_origin") != "prepared/captured_semantic.json"
        or raw_manifest.get("quarantine_read_performed") is not False
        or raw_manifest.get("governance_annotations_present") is not False
        or raw_manifest.get("task_id") != profile["task_id"]
        or task_tool._sha(raw_manifest_raw) != status.get("raw_lane_manifest_sha256")
    ):
        raise ComparisonLaunchError("RAW_LANE_ORIGIN_INVALID")
    prepared_request, prepared_request_raw = _read_object_member(
        task_tool,
        root,
        "prepared/request.json",
        "prepared/request.json",
    )
    grounding = prepared_request.get("grounding")
    request_meta = prepared_request.get("meta")
    expected_request_fields = {
        "divergence_mode": "captured_adapter",
        "logical_time": profile["logical_time"],
        "model": "captured-no-provider",
        "request_id": profile["request_id"],
        "retention_requested": False,
        "run_id": profile["run_id"],
        "task_consent": profile["privacy"]["task_consent"],
        "user_input": profile["user_input"],
    }
    if (
        prepared_request_raw != task_tool._canonical(prepared_request)
        or any(
            prepared_request.get(key) != value
            for key, value in expected_request_fields.items()
        )
        or not isinstance(grounding, list)
        or len(grounding) != 1
        or not isinstance(grounding[0], dict)
        or grounding[0].get("source_sha256") != profile["source"]["sha256"]
        or grounding[0].get("label") != profile["source"]["source_label"]
        or grounding[0].get("media_type") != profile["source"]["media_type"]
        or not isinstance(request_meta, dict)
        or request_meta.get("source_label") != profile["source"]["source_label"]
        or request_meta.get("privacy_policy_satisfied")
        != profile["privacy"]["policy_satisfied"]
        or request_meta.get("privacy_basis") != profile["privacy"]["basis"]
    ):
        raise ComparisonLaunchError("PREPARED_REQUEST_PROFILE_MISMATCH")
    prepared_capture = _read_bytes_member(
        task_tool,
        root,
        "prepared/captured_semantic.json",
        "prepared/captured_semantic.json",
        task_tool.MAX_JSON_BYTES,
    )
    capture_object, raw_lane_capture = _read_object_member(
        task_tool,
        root,
        "raw_lane/captured_semantic.json",
        "raw_lane/captured_semantic.json",
    )
    if prepared_capture != raw_lane_capture:
        raise ComparisonLaunchError("PREPARED_RAW_LANE_CAPTURE_MISMATCH")
    expected_answer = "\n".join(profile["captured_adapter"]["claims"])
    expected_claims: list[dict[str, Any]] = []
    cursor = 0
    for index, claim in enumerate(profile["captured_adapter"]["claims"], start=1):
        expected_claims.append(
            {
                "answer_end": cursor + len(claim),
                "answer_start": cursor,
                "candidate_evidence_references": profile["captured_adapter"][
                    "claim_evidence_references"
                ][index - 1],
                "claim_id": f"CLM-{index:04d}",
                "text": claim,
            }
        )
        cursor += len(claim) + 1
    expected_capture = {
        "answer": expected_answer,
        "claims": expected_claims,
        "schema_id": "uvlm.sonya.totality.captured_semantic.v1",
        "uncertainty": float(profile["captured_adapter"]["uncertainty"]),
    }
    if (
        task_tool._canonical(capture_object) != raw_lane_capture
        or raw_manifest.get("capture_sha256") != task_tool._sha(raw_lane_capture)
        or capture_object != expected_capture
    ):
        raise ComparisonLaunchError("RAW_LANE_CAPTURE_PROFILE_MISMATCH")
    bindings = comparator.get("machine_bindings")
    if not isinstance(bindings, dict):
        raise ComparisonLaunchError("COMPARATOR_MACHINE_BINDINGS_INVALID")
    _validate_route_export_receipt(task_tool, root)
    sealed = _safe_member(root, "sealed_run", "sealed run")
    if not sealed.is_dir():
        raise ComparisonLaunchError("SEALED_RUN_UNSAFE")
    exact_bindings = {
        "answer_key_sha256": task_tool._sha(expected_answer_key_raw),
        "comparator_template_sha256": task_tool.COMPARATOR_SHA256,
        "governed_claim_map_sha256": _hash_file(
            task_tool,
            root,
            "sealed_run/claim_evidence_map.json",
            "claim_evidence_map.json",
        ),
        "governed_review_html_sha256": _hash_file(
            task_tool, root, "sealed_run/final_review.html", "final_review.html"
        ),
        "profile_sha256": task_tool.PROFILE_SHA256,
        "raw_candidate_html_sha256": _hash_file(
            task_tool, root, "raw_lane/raw_candidate.html", "raw_candidate.html"
        ),
        "raw_candidate_sha256": task_tool._sha(raw_lane_capture),
        "raw_lane_manifest_sha256": task_tool._sha(raw_manifest_raw),
        "replay_receipt_sha256": _hash_file(
            task_tool, root, "exact_replay_receipt.json", "exact_replay_receipt.json"
        ),
        "route_receipt_sha256": _hash_file(
            task_tool, root, "route_receipt.json", "route_receipt.json"
        ),
        "sealed_run_manifest_sha256": _hash_file(
            task_tool, root, "sealed_run/run_manifest.json", "run_manifest.json"
        ),
        "task_id": "PRODUCT_TASK_01",
    }
    if bindings != exact_bindings:
        raise ComparisonLaunchError("COMPARATOR_EVIDENCE_BINDING_MISMATCH")
    if raw_manifest.get("capture_sha256") != exact_bindings["raw_candidate_sha256"]:
        raise ComparisonLaunchError("RAW_CAPTURE_IDENTITY_MISMATCH")
    comparisons = root / "human_comparisons"
    if os.path.lexists(comparisons) or _link_like(comparisons):
        raise ComparisonLaunchError("HUMAN_COMPARISON_OUTPUT_ALREADY_EXISTS")
    projection = _validate_raw_free_projection(task_tool, root, raw_lane_capture)
    return {
        "task_root": root,
        "task_tool": task_tool,
        "raw_candidate": _safe_member(
            root, "raw_lane/raw_candidate.html", "raw_candidate.html"
        ),
        "sealed_run": sealed,
        "comparison_root": comparisons,
        "comparator": _safe_member(
            root, "usability_comparator.json", "usability_comparator.json"
        ),
        "raw_free_projection": projection,
    }


def launch(
    task_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    no_browser: bool = False,
    smoke_test: bool = False,
    run_process: Any = subprocess.run,
) -> int:
    paths = validate_task_root(task_root)
    sys.stdout.write(
        "The loopback comparator presents Lane A first and locks its human observations "
        "before revealing Lane B. No manual JSON is required.\n"
    )

    repo = Path(__file__).resolve().parents[2]
    atlas_source = repo / "components/uvlm-publications/python/src"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(atlas_source),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "UVLM_NETWORK_POLICY": "DENY",
            "UVLM_PROVIDER_POLICY": "CAPTURED_ONLY",
            "UVLM_MEMORY_POLICY": "NO_WRITE",
        }
    )
    with _review_run_projection(paths) as (
        review_run_root,
        review_comparison_root,
    ):
        command = [
            sys.executable,
            "-P",
            "-m",
            "atlas.triadic.usability_comparator_ui",
            "--task-root",
            str(paths["task_root"]),
            "--review-run-root",
            str(review_run_root),
            "--output-root",
            str(review_comparison_root),
            "--host",
            host,
            "--port",
            str(port),
        ]
        if no_browser:
            command.append("--no-browser")
        if smoke_test:
            command.append("--smoke-test")
        completed = run_process(command, cwd=repo, env=environment, check=False)
        return int(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Render both routes in-process without human submission or output effects.",
    )
    arguments = parser.parse_args()
    try:
        return launch(
            arguments.task_root,
            host=arguments.host,
            port=arguments.port,
            no_browser=arguments.no_browser,
            smoke_test=arguments.smoke_test,
        )
    except (OSError, ComparisonLaunchError) as exc:
        sys.stderr.write(
            json.dumps(
                {"valid": False, "error": type(exc).__name__, "reason": str(exc)},
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
