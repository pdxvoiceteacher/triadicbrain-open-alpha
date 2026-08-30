# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Deterministic run inventory, UI-compatible checksum seal, and ZIP export."""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from .atlas_contract import validate_atlas_posture_packet
from .canonical import (
    canonical_json_bytes,
    require_exact_keys,
    require_identifier,
    require_sha256,
    sha256_bytes,
    sha256_file,
    strict_json_loads,
)
from .errors import OperationalError, ValidationError
from .grounding import read_grounding_bundle
from .tel import (
    AUDIT_PREFIX_ORDER,
    SEALED_ROUTE_ORDER,
    derive_audit_id,
    derive_decision_id,
    parse_final_route_tel_jsonl,
    parse_tel_jsonl,
)

CORE_MANIFEST_SCHEMA = "uvlm.coherence.totality.core_manifest.v1"
RUN_MANIFEST_SCHEMA = "uvlm.coherence.totality.run_manifest.v1"
CORE_MANIFEST_SCOPE = "IMMUTABLE_CORE_BUILD_BEFORE_EXTERNAL_AUDIT"
POST_CORE_ARTIFACTS = (
    "atlas_posture_packet.json",
    "checksums.sha256",
    "final_review.html",
    "run_manifest.json",
    "sealed_artifact_manifest.json",
    "sophia_audit_packet.json",
    "tel_events.jsonl",
    "tel_finalization_receipt.json",
)
CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)$")
UI_REQUIRED = {
    "request.json", "grounding/manifest.json", "aegis_admission_packet.json",
    "candidate_packet.json",
    "sophia_audit_packet.json", "atlas_posture_packet.json", "final_review.html",
    "tel_audit_prefix.jsonl", "tel_events.jsonl", "tel_finalization_receipt.json",
}
EFFECT_CEILING_KEYS = (
    "network", "provider_invocation", "memory_write", "training", "canonization",
    "publication", "deployment", "release", "truth_certification",
)
MAX_SEAL_JSON_BYTES = 16 * 1024 * 1024
MAX_SEAL_TEL_BYTES = 16 * 1024 * 1024
MAX_SEAL_CHECKSUM_BYTES = 8 * 1024 * 1024


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _member_safe(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor /= part
            if _link_like(cursor):
                return False
        path.resolve(strict=True).relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _walk_members(root: Path) -> list[Path]:
    members: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ValidationError("SEAL_MEMBER_ENUMERATION_FAILED") from exc
        directories: list[Path] = []
        for path in children:
            if not _member_safe(root, path):
                raise ValidationError("SEAL_LINK_OR_PATH_ESCAPE_PROHIBITED")
            members.append(path)
            if path.is_dir():
                directories.append(path)
        pending.extend(reversed(directories))
    return sorted(members, key=lambda item: item.relative_to(root).as_posix())


def _bounded_read(path: Path, maximum: int, code: str) -> bytes:
    try:
        if _link_like(path) or not path.is_file() or path.stat().st_size > maximum:
            raise ValidationError(code)
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(code) from exc
    if len(data) > maximum:
        raise ValidationError(code)
    return data


def _safe_root(root: Path) -> Path:
    if not root.is_absolute() or _link_like(root) or root == Path(root.anchor):
        raise OperationalError("SEAL_ROOT_UNSAFE")
    resolved = root.resolve()
    if not resolved.is_dir():
        raise OperationalError("SEAL_ROOT_NOT_DIRECTORY")
    return resolved


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or str(path) in {".", ".."}:
        raise ValidationError(f"SEAL_PATH_UNSAFE:{value}")
    return path.as_posix()


def inventory_files(root: Path, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    resolved = _safe_root(root)
    excluded = set(exclude)
    rows: list[dict[str, Any]] = []
    seen_casefold: set[str] = set()
    for path in _walk_members(resolved):
        if not path.is_file():
            continue
        relative = _safe_relative(path.relative_to(resolved).as_posix())
        if relative in excluded:
            continue
        folded = relative.casefold()
        if folded in seen_casefold:
            raise ValidationError("SEAL_CASEFOLD_PATH_COLLISION")
        seen_casefold.add(folded)
        rows.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return rows


def build_core_manifest(root: Path, *, run_id: str, logical_time: str) -> dict[str, Any]:
    rows = inventory_files(
        root,
        exclude={"core_manifest.json", *POST_CORE_ARTIFACTS},
    )
    return {
        "schema_id": CORE_MANIFEST_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "logical_time": logical_time,
        "manifest_scope": CORE_MANIFEST_SCOPE,
        "post_core_artifacts_excluded": list(POST_CORE_ARTIFACTS),
        "artifact_count": len(rows),
        "artifact_bytes": sum(row["bytes"] for row in rows),
        "artifacts": rows,
        "authority_effect": "NONE",
    }


def verify_core_manifest_contract(root: Path) -> dict[str, Any]:
    """Verify the immutable pre-audit core inventory and its explicit scope."""

    resolved = _safe_root(root)
    manifest_path = resolved / "core_manifest.json"
    manifest_raw = _bounded_read(
        manifest_path, MAX_SEAL_JSON_BYTES, "CORE_MANIFEST_SIZE_LIMIT_EXCEEDED"
    )
    manifest = _object_from_bytes(manifest_raw, manifest_path.name)
    if manifest_raw != canonical_json_bytes(manifest):
        raise ValidationError("CORE_MANIFEST_NOT_CANONICAL")
    require_exact_keys(
        manifest,
        required={
            "schema_id", "run_id", "logical_time", "manifest_scope",
            "post_core_artifacts_excluded", "artifact_count", "artifact_bytes",
            "artifacts", "authority_effect",
        },
    )
    if (
        manifest["schema_id"] != CORE_MANIFEST_SCHEMA
        or manifest["manifest_scope"] != CORE_MANIFEST_SCOPE
        or manifest["post_core_artifacts_excluded"] != list(POST_CORE_ARTIFACTS)
        or manifest["authority_effect"] != "NONE"
    ):
        raise ValidationError("CORE_MANIFEST_SCOPE_OR_AUTHORITY_INVALID")
    require_identifier(manifest["run_id"], "$.run_id")
    if not isinstance(manifest["logical_time"], str) or not manifest["logical_time"] or len(manifest["logical_time"]) > 128:
        raise ValidationError("CORE_MANIFEST_LOGICAL_TIME_INVALID")
    if not isinstance(manifest["artifacts"], list):
        raise ValidationError("CORE_MANIFEST_ARTIFACTS_ARRAY_REQUIRED")
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    previous = ""
    validated_rows: list[tuple[dict[str, Any], str]] = []
    reserved_casefold = {
        name.casefold() for name in {"core_manifest.json", *POST_CORE_ARTIFACTS}
    }
    # Validate the complete logical namespace before touching any artifact.
    # Otherwise a case-sensitive host can report a missing case-variant path
    # before the later row proves that the manifest itself is ambiguous.
    for index, row in enumerate(manifest["artifacts"]):
        require_exact_keys(row, required={"path", "sha256", "bytes"})
        relative = row["path"]
        relative_path = PurePosixPath(relative) if isinstance(relative, str) else None
        if (
            not isinstance(relative, str) or not relative or "\\" in relative
            or relative_path is None or relative_path.is_absolute()
            or relative_path.as_posix() != relative or ".." in relative_path.parts
            or relative == "." or relative in seen or relative <= previous
            or relative.casefold() in reserved_casefold
        ):
            raise ValidationError("CORE_MANIFEST_PATH_INVALID")
        if relative.casefold() in seen_casefold:
            raise ValidationError("CORE_MANIFEST_CASEFOLD_PATH_COLLISION")
        require_sha256(row["sha256"], f"$.artifacts[{index}].sha256")
        if (
            isinstance(row["bytes"], bool)
            or not isinstance(row["bytes"], int)
            or row["bytes"] < 0
        ):
            raise ValidationError("CORE_MANIFEST_ARTIFACT_BYTES_INVALID")
        seen.add(relative)
        seen_casefold.add(relative.casefold())
        previous = relative
        validated_rows.append((row, relative))
    if (
        isinstance(manifest["artifact_count"], bool)
        or not isinstance(manifest["artifact_count"], int)
        or manifest["artifact_count"] != len(validated_rows)
        or isinstance(manifest["artifact_bytes"], bool)
        or not isinstance(manifest["artifact_bytes"], int)
        or manifest["artifact_bytes"] != sum(row["bytes"] for row, _ in validated_rows)
    ):
        raise ValidationError("CORE_MANIFEST_COUNT_OR_BYTES_MISMATCH")

    # Only an unambiguous, type-valid manifest may resolve, stat, or hash
    # filesystem members.
    for row, relative in validated_rows:
        path = resolved / Path(relative)
        if (
            not _member_safe(resolved, path) or not path.is_file()
            or sha256_file(path) != row["sha256"]
            or path.stat().st_size != row["bytes"]
        ):
            raise ValidationError(f"CORE_MANIFEST_ARTIFACT_MISMATCH:{relative}")
    actual_scope = inventory_files(
        resolved,
        exclude={"core_manifest.json", *POST_CORE_ARTIFACTS},
    )
    if manifest["artifacts"] != actual_scope:
        raise ValidationError("CORE_MANIFEST_SCOPED_INVENTORY_MISMATCH")
    _validate_required_disabled_plugin_catalog(resolved)
    return manifest


def _object_from_bytes(data: bytes, label: str) -> dict[str, Any]:
    value = strict_json_loads(data)
    if not isinstance(value, dict):
        raise ValidationError(f"SEAL_JSON_OBJECT_REQUIRED:{label}")
    return value


def _read_object(path: Path, *, maximum: int = MAX_SEAL_JSON_BYTES) -> dict[str, Any]:
    return _object_from_bytes(
        _bounded_read(path, maximum, f"SEAL_INPUT_SIZE_LIMIT_EXCEEDED:{path.name}"),
        path.name,
    )


def _validate_required_disabled_plugin_catalog(root: Path) -> dict[str, Any]:
    # Keep the core verifier import-order neutral: plugin validation depends
    # only on canonical boundary helpers, but the public totality package also
    # re-exports this seal module.
    from .plugins import validate_disabled_plugin_catalog

    catalog_path = root / "optional_plugin_receipts.json"
    catalog_raw = _bounded_read(
        catalog_path,
        MAX_SEAL_JSON_BYTES,
        "SEAL_OPTIONAL_PLUGIN_CATALOG_SIZE_OR_SAFETY_INVALID",
    )
    catalog = _object_from_bytes(catalog_raw, catalog_path.name)
    if catalog_raw != canonical_json_bytes(catalog):
        raise ValidationError("SEAL_OPTIONAL_PLUGIN_CATALOG_NOT_CANONICAL")
    return validate_disabled_plugin_catalog(catalog)


def _validate_required_aegis_admission(root: Path) -> dict[str, Any]:
    # Lazy import preserves both public package import orders:
    # coherence.aegis imports totality boundary types, while coherence.totality
    # re-exports this seal module.
    from coherence.aegis.totality_admission import validate_totality_admission_packet

    for relative in sorted(UI_REQUIRED):
        target = root.joinpath(*PurePosixPath(relative).parts)
        if not target.is_file() or _link_like(target):
            raise ValidationError(f"SEAL_REQUIRED_ARTIFACT_MISSING_OR_UNSAFE:{relative}")
    request_path = root / "request.json"
    packet_path = root / "aegis_admission_packet.json"
    request_raw = _bounded_read(
        request_path, MAX_SEAL_JSON_BYTES, "SEAL_REQUEST_SIZE_LIMIT_EXCEEDED"
    )
    packet_raw = _bounded_read(
        packet_path, MAX_SEAL_JSON_BYTES, "SEAL_AEGIS_SIZE_LIMIT_EXCEEDED"
    )
    request = _object_from_bytes(request_raw, request_path.name)
    packet = _object_from_bytes(packet_raw, packet_path.name)
    if request_raw != canonical_json_bytes(request) or packet_raw != canonical_json_bytes(packet):
        raise ValidationError("SEAL_AEGIS_OR_REQUEST_NOT_CANONICAL")
    return validate_totality_admission_packet(
        packet,
        request=request,
        grounding_bundle=read_grounding_bundle(root / "grounding"),
        request_sha256=sha256_bytes(request_raw),
    )


def _validate_repository_identity(value: Any) -> dict[str, Any]:
    require_exact_keys(value, required={"repository", "commit", "tree", "prefix_trees", "worktree_clean", "status_sha256"}, path="$.repository_identity")
    require_exact_keys(
        value["prefix_trees"],
        required={"coherence_lattice", "sophia", "uvlm_publications"},
        path="$.repository_identity.prefix_trees",
    )
    for path, object_id in {
        "commit": value["commit"], "tree": value["tree"], **value["prefix_trees"],
    }.items():
        if not isinstance(object_id, str) or len(object_id) not in {40, 64} or any(char not in "0123456789abcdef" for char in object_id):
            raise ValidationError(f"SEAL_REPOSITORY_OBJECT_ID_INVALID:{path}")
    if not isinstance(value["repository"], str) or not value["repository"]:
        raise ValidationError("SEAL_REPOSITORY_NAME_INVALID")
    if not isinstance(value["worktree_clean"], bool):
        raise ValidationError("SEAL_WORKTREE_CLEAN_BOOLEAN_REQUIRED")
    require_sha256(value["status_sha256"], "$.repository_identity.status_sha256")
    return {**value, "prefix_trees": dict(value["prefix_trees"])}


def _validate_finalized_tel(root: Path) -> dict[str, Any]:
    prefix_raw = _bounded_read(
        root / "tel_audit_prefix.jsonl",
        MAX_SEAL_TEL_BYTES,
        "SEAL_TEL_PREFIX_SIZE_LIMIT_EXCEEDED",
    )
    full_raw = _bounded_read(
        root / "tel_events.jsonl",
        MAX_SEAL_TEL_BYTES,
        "SEAL_TEL_EVENTS_SIZE_LIMIT_EXCEEDED",
    )
    prefix = parse_tel_jsonl(prefix_raw)
    full = parse_final_route_tel_jsonl(full_raw)
    if tuple(row["event_type"] for row in prefix.rows) != AUDIT_PREFIX_ORDER:
        raise ValidationError("SEAL_TEL_AUDIT_PREFIX_ORDER_INVALID")
    if tuple(row["event_type"] for row in full.rows) != SEALED_ROUTE_ORDER:
        raise ValidationError("SEAL_TEL_ROUTE_NOT_FINALIZED_OR_EXTERNAL_CONTINUATION_PRESENT")
    if full.rows[:len(prefix.rows)] != prefix.rows:
        raise ValidationError("SEAL_TEL_PREFIX_MUTATION_DETECTED")
    receipt_path = root / "tel_finalization_receipt.json"
    receipt_raw = _bounded_read(
        receipt_path,
        MAX_SEAL_JSON_BYTES,
        "SEAL_TEL_RECEIPT_SIZE_LIMIT_EXCEEDED",
    )
    receipt = _object_from_bytes(receipt_raw, receipt_path.name)
    if receipt_raw != canonical_json_bytes(receipt):
        raise ValidationError("SEAL_TEL_FINALIZATION_RECEIPT_NOT_CANONICAL")
    require_exact_keys(
        receipt,
        required={
            "schema_id", "run_id", "logical_time", "candidate_id", "audit_id", "decision_id",
            "tel_audit_prefix_sha256", "sophia_audit_packet_sha256",
            "atlas_posture_packet_sha256", "tel_events_sha256", "event_count",
            "human_decision", "external_continuation_required", "effects", "authority_effect",
        },
    )
    effects = receipt["effects"]
    require_exact_keys(
        effects,
        required={"network", "provider_invocation", "memory_write", "training", "publication", "deployment", "release"},
        path="$.effects",
    )
    if (
        receipt["schema_id"] != "uvlm.coherence.totality.tel_finalization_receipt.v1"
        or receipt["authority_effect"] != "NONE" or any(value is not False for value in effects.values())
        or receipt["human_decision"] != "PENDING"
        or receipt["external_continuation_required"] is not True
        or receipt["event_count"] != len(SEALED_ROUTE_ORDER)
    ):
        raise ValidationError("SEAL_TEL_FINALIZATION_POSTURE_INVALID")
    for field in ("run_id", "candidate_id", "audit_id", "decision_id"):
        require_identifier(receipt[field], f"$.{field}")
    for field in (
        "tel_audit_prefix_sha256", "sophia_audit_packet_sha256",
        "atlas_posture_packet_sha256", "tel_events_sha256",
    ):
        require_sha256(receipt[field], f"$.{field}")
    if (
        receipt["tel_audit_prefix_sha256"] != sha256_bytes(prefix_raw)
        or receipt["sophia_audit_packet_sha256"] != sha256_file(root / "sophia_audit_packet.json")
        or receipt["atlas_posture_packet_sha256"] != sha256_file(root / "atlas_posture_packet.json")
        or receipt["tel_events_sha256"] != sha256_bytes(full_raw)
    ):
        raise ValidationError("SEAL_TEL_FINALIZATION_HASH_BINDING_INVALID")
    request_path, candidate_path = root / "request.json", root / "candidate_packet.json"
    request_raw = _bounded_read(
        request_path, MAX_SEAL_JSON_BYTES, "SEAL_REQUEST_SIZE_LIMIT_EXCEEDED"
    )
    candidate_raw = _bounded_read(
        candidate_path, MAX_SEAL_JSON_BYTES, "SEAL_CANDIDATE_SIZE_LIMIT_EXCEEDED"
    )
    request = _object_from_bytes(request_raw, request_path.name)
    candidate = _object_from_bytes(candidate_raw, candidate_path.name)
    if request_raw != canonical_json_bytes(request) or candidate_raw != canonical_json_bytes(candidate):
        raise ValidationError("SEAL_TEL_PRIMARY_ARTIFACT_NOT_CANONICAL")
    if (
        (receipt["run_id"], receipt["logical_time"], receipt["candidate_id"])
        != (request.get("run_id"), request.get("logical_time"), candidate.get("candidate_id"))
    ):
        raise ValidationError("SEAL_TEL_FINALIZATION_IDENTITY_MISMATCH")
    sophia_path, atlas_path = root / "sophia_audit_packet.json", root / "atlas_posture_packet.json"
    sophia_raw = _bounded_read(
        sophia_path, MAX_SEAL_JSON_BYTES, "SEAL_SOPHIA_SIZE_LIMIT_EXCEEDED"
    )
    atlas_raw = _bounded_read(
        atlas_path, MAX_SEAL_JSON_BYTES, "SEAL_ATLAS_SIZE_LIMIT_EXCEEDED"
    )
    sophia = _object_from_bytes(sophia_raw, sophia_path.name)
    atlas = _object_from_bytes(atlas_raw, atlas_path.name)
    if sophia_raw != canonical_json_bytes(sophia) or atlas_raw != canonical_json_bytes(atlas):
        raise ValidationError("SEAL_TEL_AUDIT_ARTIFACT_NOT_CANONICAL")
    validate_atlas_posture_packet(
        atlas, sophia_disposition=sophia.get("disposition")
    )
    expected_audit_id = derive_audit_id(
        sha256_bytes(candidate_raw), sha256_file(root / "aperture_decision.json")
    )
    expected_decision_id = derive_decision_id(expected_audit_id, receipt["run_id"])
    sophia_inputs = sophia.get("input_digests")
    atlas_inputs = atlas.get("input_digests")
    sophia_prefix = (
        sophia_inputs.get("tel_audit_prefix.jsonl")
        if isinstance(sophia_inputs, dict)
        else None
    )
    atlas_prefix = (
        atlas_inputs.get("tel_audit_prefix.jsonl")
        if isinstance(atlas_inputs, dict)
        else None
    )
    atlas_sophia = (
        atlas_inputs.get("sophia_audit_packet.json")
        if isinstance(atlas_inputs, dict)
        else None
    )
    if (
        receipt["audit_id"] != expected_audit_id
        or receipt["decision_id"] != expected_decision_id
        or (sophia.get("run_id"), sophia.get("logical_time"), sophia.get("candidate_id"))
        != (receipt["run_id"], receipt["logical_time"], receipt["candidate_id"])
        or sophia.get("audit_id") != expected_audit_id
        or sophia.get("disposition") not in {"PASS", "HOLD", "REJECT"}
        or (atlas.get("run_id"), atlas.get("logical_time"), atlas.get("candidate_id"))
        != (receipt["run_id"], receipt["logical_time"], receipt["candidate_id"])
        or atlas.get("audit_id") != expected_audit_id
        or atlas.get("sophia_disposition") != sophia.get("disposition")
        or not isinstance(sophia_prefix, dict)
        or sophia_prefix.get("file_sha256") != receipt["tel_audit_prefix_sha256"]
        or not isinstance(atlas_prefix, dict)
        or atlas_prefix.get("file_sha256") != receipt["tel_audit_prefix_sha256"]
        or not isinstance(atlas_sophia, dict)
        or atlas_sophia.get("file_sha256") != receipt["sophia_audit_packet_sha256"]
    ):
        raise ValidationError("SEAL_TEL_CROSS_COMPONENT_PARENT_BINDING_INVALID")
    sophia_row, atlas_row, route_row = full.rows[-3:]
    identity = (receipt["candidate_id"], receipt["audit_id"], receipt["decision_id"])
    if any((row["candidate_id"], row["audit_id"], row["decision_id"]) != identity for row in (sophia_row, atlas_row, route_row)):
        raise ValidationError("SEAL_TEL_FINAL_EVENT_IDENTITY_MISMATCH")
    if (
        sophia_row["payload"] != {
            "sophia_audit_packet_sha256": receipt["sophia_audit_packet_sha256"],
            "disposition": sophia.get("disposition"),
        }
        or atlas_row["payload"] != {
            "atlas_posture_packet_sha256": receipt["atlas_posture_packet_sha256"],
            "human_decision": "PENDING",
        }
        or route_row["payload"] != {
            "tel_audit_prefix_sha256": receipt["tel_audit_prefix_sha256"],
            "external_human_decision_receipt_required": True,
            "human_decision": "PENDING",
        }
        or sophia.get("audit_id") != receipt["audit_id"]
        or atlas.get("audit_id") != receipt["audit_id"]
        or atlas.get("human_decision") != "PENDING"
    ):
        raise ValidationError("SEAL_TEL_FINAL_EVENT_BINDING_INVALID")
    return receipt


def seal_run(root: Path, *, repository_identity: dict[str, Any]) -> dict[str, Any]:
    resolved = _safe_root(root)
    if any((resolved / name).exists() for name in ("sealed_artifact_manifest.json", "run_manifest.json", "checksums.sha256")):
        raise OperationalError("SEAL_ALREADY_EXISTS")
    actual = {row["path"] for row in inventory_files(resolved)}
    missing = sorted(UI_REQUIRED - actual)
    if missing:
        raise ValidationError("SEAL_REQUIRED_ARTIFACTS_MISSING:" + ",".join(missing))
    verify_core_manifest_contract(resolved)
    _validate_required_aegis_admission(resolved)
    _validate_finalized_tel(resolved)
    request = _read_object(resolved / "request.json")
    candidate = _read_object(resolved / "candidate_packet.json")
    if (request.get("run_id"), request.get("logical_time")) != (candidate.get("run_id"), candidate.get("logical_time")):
        raise ValidationError("SEAL_REQUEST_CANDIDATE_IDENTITY_MISMATCH")
    run_id = require_identifier(request.get("run_id"), "$.request.run_id")
    logical_time = request.get("logical_time")
    repo = _validate_repository_identity(repository_identity)
    seal_payload = inventory_files(
        resolved,
        exclude={"sealed_artifact_manifest.json", "run_manifest.json", "checksums.sha256"},
    )
    sealed_artifact_manifest = {
        "schema_id": "uvlm.coherence.totality.sealed_artifact_manifest.v1",
        "run_id": run_id,
        "logical_time": logical_time,
        "repository_identity": dict(repo),
        "effect_ceiling": dict.fromkeys(EFFECT_CEILING_KEYS, False),
        "payload_count": len(seal_payload),
        "payload_bytes": sum(row["bytes"] for row in seal_payload),
        "files": seal_payload,
        "authority_effect": "NONE",
    }
    sealed_bytes = canonical_json_bytes(sealed_artifact_manifest)
    rows = sorted(
        [
            *seal_payload,
            {
                "path": "sealed_artifact_manifest.json",
                "sha256": sha256_bytes(sealed_bytes),
                "bytes": len(sealed_bytes),
            },
        ],
        key=lambda row: row["path"],
    )
    manifest = {
        "schema_id": RUN_MANIFEST_SCHEMA,
        "run_id": run_id,
        "logical_time": logical_time,
        "request_sha256": sha256_file(resolved / "request.json"),
        "candidate_sha256": sha256_file(resolved / "candidate_packet.json"),
        "core_manifest_sha256": sha256_file(resolved / "core_manifest.json") if (resolved / "core_manifest.json").is_file() else None,
        "sealed_artifact_manifest_sha256": sha256_bytes(sealed_bytes),
        "repository_identity": dict(repo),
        "effect_ceiling": dict.fromkeys(EFFECT_CEILING_KEYS, False),
        "artifact_count": len(rows),
        "artifact_bytes": sum(row["bytes"] for row in rows),
        "artifacts": rows,
        "authority_effect": "NONE",
        "human_review_required": True,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    checksum_rows = sorted(
        [
            *rows,
            {
                "path": "run_manifest.json",
                "sha256": sha256_bytes(manifest_bytes),
                "bytes": len(manifest_bytes),
            },
        ],
        key=lambda row: row["path"],
    )
    sidecar = "".join(f"{row['sha256']}  {row['path']}\n" for row in checksum_rows).encode("utf-8")
    staged = {
        "sealed_artifact_manifest.json": sealed_bytes,
        "run_manifest.json": manifest_bytes,
        "checksums.sha256": sidecar,
    }
    failure_codes = {
        "sealed_artifact_manifest.json": "SEAL_ARTIFACT_MANIFEST_PUBLISH_FAILED",
        "run_manifest.json": "SEAL_RUN_MANIFEST_PUBLISH_FAILED",
        "checksums.sha256": "SEAL_CHECKSUM_PUBLISH_FAILED",
    }
    with TemporaryDirectory(dir=resolved.parent, prefix=f".{resolved.name}.seal-") as temporary:
        staging = Path(temporary)
        for name, data in staged.items():
            (staging / name).write_bytes(data)
        for name in staged:
            destination = resolved / name
            try:
                os.link(staging / name, destination)
            except OSError as exc:
                raise OperationalError(failure_codes[name]) from exc
        # Never unlink a public path after any exclusive hard-link claim.  A
        # same-user racer could replace the pathname between an identity check
        # and cleanup.  Partial claims intentionally remain as fail-closed
        # tombstones, causing every later sealing attempt to reject.
        verify_sealed_run(resolved)
    return manifest


def _validate_manifest_inventory(root: Path, manifest: Any) -> None:
    require_exact_keys(
        manifest,
        required={
            "schema_id", "run_id", "logical_time", "request_sha256", "candidate_sha256",
            "core_manifest_sha256", "artifact_count", "artifact_bytes", "artifacts",
            "sealed_artifact_manifest_sha256", "repository_identity", "effect_ceiling",
            "authority_effect", "human_review_required",
        },
    )
    if manifest["schema_id"] != RUN_MANIFEST_SCHEMA or manifest["authority_effect"] != "NONE" or manifest["human_review_required"] is not True:
        raise ValidationError("SEAL_MANIFEST_POSTURE_INVALID")
    require_identifier(manifest["run_id"], "$.run_manifest.run_id")
    if (
        not isinstance(manifest["logical_time"], str)
        or not manifest["logical_time"]
        or len(manifest["logical_time"]) > 128
    ):
        raise ValidationError("SEAL_MANIFEST_LOGICAL_TIME_INVALID")
    _validate_repository_identity(manifest["repository_identity"])
    if manifest["effect_ceiling"] != dict.fromkeys(EFFECT_CEILING_KEYS, False):
        raise ValidationError("SEAL_MANIFEST_EFFECT_CEILING_INVALID")
    rows = inventory_files(root, exclude={"run_manifest.json", "checksums.sha256"})
    if manifest["artifacts"] != rows:
        raise ValidationError("SEAL_MANIFEST_INVENTORY_MISMATCH")
    if manifest["artifact_count"] != len(rows) or manifest["artifact_bytes"] != sum(row["bytes"] for row in rows):
        raise ValidationError("SEAL_MANIFEST_COUNT_OR_BYTES_MISMATCH")
    if manifest["request_sha256"] != sha256_file(root / "request.json") or manifest["candidate_sha256"] != sha256_file(root / "candidate_packet.json"):
        raise ValidationError("SEAL_MANIFEST_PRIMARY_HASH_MISMATCH")
    core = root / "core_manifest.json"
    expected_core = sha256_file(core) if core.is_file() else None
    if manifest["core_manifest_sha256"] != expected_core:
        raise ValidationError("SEAL_MANIFEST_CORE_HASH_MISMATCH")
    sealed_path = root / "sealed_artifact_manifest.json"
    if manifest["sealed_artifact_manifest_sha256"] != sha256_file(sealed_path):
        raise ValidationError("SEAL_ARTIFACT_MANIFEST_HASH_MISMATCH")
    sealed_raw = _bounded_read(
        sealed_path, MAX_SEAL_JSON_BYTES, "SEALED_ARTIFACT_MANIFEST_SIZE_LIMIT_EXCEEDED"
    )
    sealed = _object_from_bytes(sealed_raw, sealed_path.name)
    if sealed_raw != canonical_json_bytes(sealed):
        raise ValidationError("SEALED_ARTIFACT_MANIFEST_NOT_CANONICAL")
    require_exact_keys(
        sealed,
        required={"schema_id", "run_id", "logical_time", "repository_identity", "effect_ceiling", "payload_count", "payload_bytes", "files", "authority_effect"},
    )
    payload = inventory_files(root, exclude={"sealed_artifact_manifest.json", "run_manifest.json", "checksums.sha256"})
    if (
        sealed["schema_id"] != "uvlm.coherence.totality.sealed_artifact_manifest.v1"
        or sealed["files"] != payload or sealed["payload_count"] != len(payload)
        or sealed["payload_bytes"] != sum(row["bytes"] for row in payload)
        or sealed["effect_ceiling"] != dict.fromkeys(EFFECT_CEILING_KEYS, False)
        or sealed["authority_effect"] != "NONE"
        or sealed["repository_identity"] != manifest["repository_identity"]
        or (sealed["run_id"], sealed["logical_time"]) != (manifest["run_id"], manifest["logical_time"])
    ):
        raise ValidationError("SEAL_ARTIFACT_MANIFEST_INVALID")
    request_path, candidate_path = root / "request.json", root / "candidate_packet.json"
    request_raw = _bounded_read(
        request_path, MAX_SEAL_JSON_BYTES, "SEAL_REQUEST_SIZE_LIMIT_EXCEEDED"
    )
    candidate_raw = _bounded_read(
        candidate_path, MAX_SEAL_JSON_BYTES, "SEAL_CANDIDATE_SIZE_LIMIT_EXCEEDED"
    )
    request = _object_from_bytes(request_raw, request_path.name)
    candidate = _object_from_bytes(candidate_raw, candidate_path.name)
    if request_raw != canonical_json_bytes(request) or candidate_raw != canonical_json_bytes(candidate):
        raise ValidationError("SEAL_PRIMARY_ARTIFACT_NOT_CANONICAL")
    core = _read_object(root / "core_manifest.json")
    tel_receipt = _read_object(root / "tel_finalization_receipt.json")
    identity = (request.get("run_id"), request.get("logical_time"))
    if (
        not isinstance(identity[0], str)
        or not isinstance(identity[1], str)
        or (candidate.get("run_id"), candidate.get("logical_time")) != identity
        or (core.get("run_id"), core.get("logical_time")) != identity
        or (tel_receipt.get("run_id"), tel_receipt.get("logical_time")) != identity
        or (manifest["run_id"], manifest["logical_time"]) != identity
        or (sealed["run_id"], sealed["logical_time"]) != identity
    ):
        raise ValidationError("SEAL_CROSS_ARTIFACT_RUN_IDENTITY_MISMATCH")


def verify_sealed_run(root: Path) -> dict[str, Any]:
    resolved = _safe_root(root)
    manifest_path, sidecar_path = resolved / "run_manifest.json", resolved / "checksums.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file() or manifest_path.is_symlink() or sidecar_path.is_symlink():
        raise ValidationError("SEAL_FILES_MISSING_OR_UNSAFE")
    manifest_raw = _bounded_read(
        manifest_path, MAX_SEAL_JSON_BYTES, "RUN_MANIFEST_SIZE_LIMIT_EXCEEDED"
    )
    manifest = _object_from_bytes(manifest_raw, manifest_path.name)
    if manifest_raw != canonical_json_bytes(manifest):
        raise ValidationError("RUN_MANIFEST_NOT_CANONICAL")
    verify_core_manifest_contract(resolved)
    _validate_required_aegis_admission(resolved)
    _validate_finalized_tel(resolved)
    _validate_manifest_inventory(resolved, manifest)
    raw = _bounded_read(
        sidecar_path, MAX_SEAL_CHECKSUM_BYTES, "SEAL_CHECKSUM_SIZE_LIMIT_EXCEEDED"
    )
    if not raw or not raw.endswith(b"\n") or b"\r" in raw or b"\x00" in raw:
        raise ValidationError("SEAL_CHECKSUM_FORMAT_INVALID")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValidationError("SEAL_CHECKSUM_UTF8_INVALID") from exc
    observed: dict[str, str] = {}
    for line in lines:
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValidationError("SEAL_CHECKSUM_LINE_INVALID")
        digest, relative = match.groups()
        relative = _safe_relative(relative)
        if relative in observed:
            raise ValidationError("SEAL_CHECKSUM_DUPLICATE_PATH")
        observed[relative] = digest
    rows = inventory_files(resolved, exclude={"checksums.sha256"})
    expected = {row["path"]: row["sha256"] for row in rows}
    if observed != expected or list(observed) != sorted(observed):
        raise ValidationError("SEAL_CHECKSUM_COVERAGE_OR_ORDER_MISMATCH")
    return {
        "schema_id": "uvlm.coherence.totality.seal_verification.v1",
        "valid": True,
        "run_id": manifest["run_id"],
        "logical_time": manifest["logical_time"],
        "files_verified": len(expected),
        "checksums_sha256": sha256_bytes(raw),
        "authority_effect": "NONE",
    }


def build_deterministic_zip(root: Path, output_zip: Path) -> dict[str, Any]:
    verification = verify_sealed_run(root)
    resolved = root.resolve()
    sidecar_path = output_zip.with_name(output_zip.name + ".sha256")
    try:
        output_zip.resolve().relative_to(resolved)
    except ValueError:
        pass
    else:
        raise OperationalError("ZIP_OUTPUT_INSIDE_SEALED_ROOT_PROHIBITED")
    if (
        output_zip.exists()
        or output_zip.is_symlink()
        or sidecar_path.exists()
        or sidecar_path.is_symlink()
        or PurePosixPath(output_zip.name).name != output_zip.name
        or PureWindowsPath(output_zip.name).name != output_zip.name
        or any(character in output_zip.name for character in "/\\:\r\n\x00")
    ):
        raise OperationalError("ZIP_OUTPUT_EXISTS_OR_UNSAFE")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_zip.parent, prefix=f".{output_zip.name}.build-") as temporary:
        staging = Path(temporary)
        staged_zip = staging / output_zip.name
        staged_sidecar = staging / sidecar_path.name
        with zipfile.ZipFile(staged_zip, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for row in inventory_files(resolved):
                info = zipfile.ZipInfo(row["path"], date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                with (
                    (resolved / Path(row["path"])).open("rb") as source,
                    archive.open(info, "w", force_zip64=True) as destination,
                ):
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        zip_sha256 = sha256_file(staged_zip)
        sidecar_bytes = f"{zip_sha256}  {output_zip.name}\n".encode("utf-8")
        staged_sidecar.write_bytes(sidecar_bytes)
        for staged_path, destination, code in (
            (staged_zip, output_zip, "ZIP_PUBLISH_FAILED"),
            (staged_sidecar, sidecar_path, "ZIP_SIDECAR_PUBLISH_FAILED"),
        ):
            try:
                os.link(staged_path, destination)
            except OSError as exc:
                raise OperationalError(code) from exc
        # As above, a post-claim failure leaves tombstones.  Never perform
        # pathname-based rollback of published ZIP or sidecar names.
        verify_zip_sidecar(output_zip)
    return {
        **verification,
        # Receipt paths are package-stable artifact names.  The caller already
        # controls the bounded publication directory; leaking its host path
        # would make an otherwise exact receipt non-portable.
        "zip_path": output_zip.name,
        "zip_sha256": zip_sha256,
        "zip_bytes": output_zip.stat().st_size,
        "zip_sidecar_path": sidecar_path.name,
        "zip_sidecar_sha256": sha256_bytes(sidecar_bytes),
    }


def verify_zip_sidecar(output_zip: Path) -> dict[str, Any]:
    sidecar_path = output_zip.with_name(output_zip.name + ".sha256")
    if (
        not output_zip.is_file()
        or output_zip.is_symlink()
        or not sidecar_path.is_file()
        or sidecar_path.is_symlink()
        or PurePosixPath(output_zip.name).name != output_zip.name
        or PureWindowsPath(output_zip.name).name != output_zip.name
        or any(character in output_zip.name for character in "/\\:\r\n\x00")
    ):
        raise ValidationError("ZIP_OR_SIDECAR_MISSING_OR_UNSAFE")
    digest = sha256_file(output_zip)
    expected = f"{digest}  {output_zip.name}\n".encode("utf-8")
    actual = _bounded_read(
        sidecar_path, 4096, "ZIP_SIDECAR_SIZE_LIMIT_EXCEEDED"
    )
    if actual != expected:
        raise ValidationError("ZIP_SIDECAR_MISMATCH")
    return {
        "valid": True,
        "zip_path": output_zip.name,
        "zip_sha256": digest,
        "zip_bytes": output_zip.stat().st_size,
        "zip_sidecar_path": sidecar_path.name,
        "zip_sidecar_sha256": sha256_bytes(actual),
        "authority_effect": "NONE",
    }
