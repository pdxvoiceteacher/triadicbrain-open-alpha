"""Orchestrate, seal, verify, and exactly replay the private totality route.

Every component is invoked through its public module CLI in a separate Python
process.  No sibling private package is imported into the integration owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


ROUTE_RECEIPT_SCHEMA = "uvlm.triadicgate.totality_product_route_receipt.v2"
REPLAY_RECEIPT_SCHEMA = "uvlm.triadicgate.totality_exact_replay_receipt.v1"
ROUTE_FAILURE_RECEIPT_SCHEMA = "uvlm.triadicgate.totality_route_failure_receipt.v1"
ROUTE_FAILURE_EVENT_SCHEMA = "uvlm.triadicgate.totality_route_failure_event.v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 2 * 1024 * 1024
MAX_AHA_BYTES = 4 * 1024 * 1024
MAX_CONSENT_BYTES = 1024 * 1024
MAX_ROUTE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ROUTE_TREE_BYTES = 128 * 1024 * 1024


class RouteError(RuntimeError):
    """A cross-component route operation failed closed."""


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _portable_artifact_name(name: str) -> bool:
    return bool(name) and (
        PurePosixPath(name).name == name
        and PureWindowsPath(name).name == name
        and not any(character in name for character in "/\\:\r\n\x00")
    )


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


def _walk_members(root: Path, code: str) -> list[Path]:
    members: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise RouteError(code) from exc
        directories: list[Path] = []
        for path in children:
            if not _member_safe(root, path):
                raise RouteError(code)
            members.append(path)
            if path.is_dir():
                directories.append(path)
        pending.extend(reversed(directories))
    return sorted(members, key=lambda item: item.relative_to(root).as_posix())


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _member_limit(relative: str) -> int:
    return {
        "input_manifest.json": MAX_MANIFEST_BYTES,
        "request.json": MAX_REQUEST_BYTES,
        "source.bin": MAX_SOURCE_BYTES,
        "grounding/source.bin": MAX_SOURCE_BYTES,
        "grounding/normalized_source.txt": MAX_SOURCE_BYTES,
        "captured_semantic.json": MAX_CAPTURE_BYTES,
        "sonya/raw_output.quarantine": MAX_CAPTURE_BYTES,
        "aha_case.json": MAX_AHA_BYTES,
        "pmr_consent.json": MAX_CONSENT_BYTES,
    }.get(relative, MAX_ROUTE_MEMBER_BYTES)


def _read_bounded(path: Path, label: str, *, maximum: int | None = None) -> bytes:
    limit = maximum if maximum is not None else _member_limit(label)
    try:
        if _link_like(path) or not path.is_file() or path.stat().st_size > limit:
            raise RouteError(f"INPUT_SIZE_OR_TYPE_INVALID:{label}")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except RouteError:
        raise
    except OSError as exc:
        raise RouteError(f"INPUT_UNREADABLE:{label}") from exc
    if len(data) > limit:
        raise RouteError(f"INPUT_SIZE_OR_TYPE_INVALID:{label}")
    return data


def _hash_bounded(path: Path, label: str) -> tuple[str, int]:
    limit = _member_limit(label)
    try:
        size = path.stat().st_size
        if size > limit:
            raise RouteError(f"INPUT_SIZE_OR_TYPE_INVALID:{label}")
        digest = hashlib.sha256()
        observed = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                observed += len(chunk)
                if observed > limit:
                    raise RouteError(f"INPUT_SIZE_OR_TYPE_INVALID:{label}")
                digest.update(chunk)
    except RouteError:
        raise
    except OSError as exc:
        raise RouteError(f"INPUT_UNREADABLE:{label}") from exc
    if observed != size:
        raise RouteError(f"INPUT_SIZE_CHANGED_DURING_READ:{label}")
    return digest.hexdigest(), observed


def _safe_repo(value: Path) -> Path:
    if not value.is_absolute() or _link_like(value) or not value.is_dir():
        raise RouteError("REPOSITORY_ROOT_UNSAFE")
    root = value.resolve(strict=True)
    if root == Path(root.anchor):
        raise RouteError("REPOSITORY_ROOT_UNBOUNDED")
    required = {
        "components/CoherenceLattice/python/src",
        "components/Sophia/python/src",
        "components/uvlm-publications/python/src",
    }
    if any(not root.joinpath(*PurePosixPath(path).parts).is_dir() for path in required):
        raise RouteError("REPOSITORY_COMPONENT_BOUNDARY_MISSING")
    return root


def _safe_existing_dir(value: Path, code: str) -> Path:
    if not value.is_absolute() or _link_like(value) or not value.is_dir():
        raise RouteError(code)
    path = value.resolve(strict=True)
    if path == Path(path.anchor):
        raise RouteError(code)
    return path


def _safe_new_dir(value: Path) -> Path:
    if not value.is_absolute() or value.exists() or _link_like(value) or value == Path(value.anchor):
        raise RouteError("OUTPUT_ROOT_UNSAFE_OR_EXISTS")
    resolved = value.resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _require_disjoint_directories(*named_paths: tuple[str, Path]) -> None:
    resolved = [(name, path.resolve(strict=False)) for name, path in named_paths]
    for index, (left_name, left) in enumerate(resolved):
        for right_name, right in resolved[index + 1 :]:
            if _contains(left, right) or _contains(right, left):
                raise RouteError(
                    f"PATH_SCOPE_OVERLAP:{left_name}:{right_name}"
                )


def _require_external_new_file(
    path: Path,
    *,
    protected_roots: Iterable[Path],
    other_outputs: Iterable[Path] = (),
) -> Path:
    if not path.is_absolute() or path.exists() or _link_like(path):
        raise RouteError("EXTERNAL_OUTPUT_UNSAFE_OR_EXISTS")
    resolved = path.resolve(strict=False)
    if any(_contains(root, resolved) for root in protected_roots):
        raise RouteError("EXTERNAL_OUTPUT_INSIDE_PROTECTED_ROOT")
    if any(resolved == other.resolve(strict=False) for other in other_outputs):
        raise RouteError("EXTERNAL_OUTPUT_PATH_COLLISION")
    return resolved


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in rows:
        if key in value:
            raise RouteError(f"JSON_DUPLICATE_MEMBER:{key}")
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise RouteError(f"JSON_NONFINITE_NUMBER:{value}")


def _parse_object(raw: bytes, label: str, *, require_canonical: bool = True) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RouteError(f"JSON_BOM_PROHIBITED:{label}")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RouteError(f"JSON_OUTPUT_INVALID:{label}") from exc
    if not isinstance(value, dict):
        raise RouteError(f"JSON_OUTPUT_NOT_OBJECT:{label}")
    if require_canonical and raw != _canonical(value):
        raise RouteError(f"JSON_CANONICAL_ENCODING_REQUIRED:{label}")
    return value


def _component_env(repo: Path, component: str) -> dict[str, str]:
    paths = {
        "coherence": repo / "components/CoherenceLattice/python/src",
        "sophia": repo / "components/Sophia/python/src",
        "atlas": repo / "components/uvlm-publications/python/src",
    }
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(paths[component]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "UVLM_NETWORK_POLICY": "DENY",
            "UVLM_PROVIDER_POLICY": "CAPTURED_ONLY",
            "UVLM_MEMORY_POLICY": "NO_WRITE",
        }
    )
    return env


def _module(
    repo: Path,
    component: str,
    module: str,
    arguments: Iterable[str | Path],
    *,
    expect_json: bool = False,
) -> dict[str, Any]:
    argument_values = tuple(str(item) for item in arguments)
    command = [sys.executable, "-P", "-m", module, *argument_values]
    completed = subprocess.run(
        command,
        cwd=repo,
        env=_component_env(repo, component),
        check=False,
        capture_output=True,
        text=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        operation = argument_values[0] if argument_values else "module"
        raise RouteError(
            f"COMPONENT_FAILED:{component}:{module}:operation={operation}:"
            f"exit={completed.returncode}:{detail}"
        )
    if expect_json:
        return _parse_object(completed.stdout, f"{component}:{module}")
    return {"exit_code": completed.returncode, "stdout_sha256": _sha(completed.stdout)}


def _failure_stage(error: BaseException) -> str:
    reason = str(error)
    if "COMPONENT_FAILED:sophia:" in reason:
        return "SOPHIA_AUDIT"
    if "COMPONENT_FAILED:atlas:" in reason:
        return "ATLAS_ORIENTATION"
    if "finalize-route-tel" in reason:
        return "TEL_FINALIZATION"
    if ":coherence.totality.cli:operation=seal:" in reason:
        return "SEAL"
    if ":coherence.totality.cli:operation=verify:" in reason:
        return "VERIFY"
    if ":coherence.totality.cli:operation=finalize-route-tel:" in reason:
        return "TEL_FINALIZATION"
    if "COMPONENT_FAILED:coherence:" in reason:
        return "COHERENCE_CORE_OR_ROUTE"
    return "INTEGRATION_ROUTE"


def _partial_tel_identity(run_root: Path) -> dict[str, Any]:
    tel = run_root / "tel_events.jsonl"
    result: dict[str, Any] = {
        "parent_tel_sha256": None,
        "parent_tel_event_count": 0,
        "candidate_id": None,
        "audit_id": None,
        "decision_id": None,
    }
    if _link_like(tel) or not tel.is_file():
        return result
    raw = _read_bounded(tel, "tel_events.jsonl")
    result["parent_tel_sha256"] = _sha(raw)
    lines = raw.splitlines(keepends=True)
    result["parent_tel_event_count"] = len(lines)
    if not lines:
        return result
    try:
        final = _parse_object(lines[-1], "partial:tel_events.jsonl")
    except RouteError:
        return result
    for field in ("candidate_id", "audit_id", "decision_id"):
        value = final.get(field)
        result[field] = value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None
    return result


def _preserve_route_failure(
    failure_root: Path,
    *,
    run_root: Path,
    run_id: str,
    logical_time: str,
    error: BaseException,
) -> dict[str, Any]:
    """Write external deterministic evidence without mutating the partial run."""

    if failure_root.exists() or _link_like(failure_root) or not failure_root.is_absolute():
        raise RouteError("ROUTE_FAILURE_EVIDENCE_ROOT_UNSAFE_OR_EXISTS")
    failure_root.parent.mkdir(parents=True, exist_ok=True)
    failure_root.mkdir()
    stage = _failure_stage(error)
    reason_code = f"ROUTE_{stage}_FAILED"
    identity = _partial_tel_identity(run_root)
    error_sha256 = _sha(str(error).encode("utf-8", errors="replace"))
    event = {
        "schema_id": ROUTE_FAILURE_EVENT_SCHEMA,
        "sequence": 1,
        "event_type": "ROUTE_STAGE_FAILED",
        "run_id": run_id,
        "candidate_id": identity["candidate_id"],
        "audit_id": identity["audit_id"],
        "decision_id": identity["decision_id"],
        "stage": stage,
        "reason_code": reason_code,
        "error_sha256": error_sha256,
        "parent_tel_sha256": identity["parent_tel_sha256"],
        "parent_tel_event_count": identity["parent_tel_event_count"],
        "sealed_run_mutated": False,
        "authority_effect": "NONE",
    }
    event_bytes = _canonical(event)
    receipt = {
        "schema_id": ROUTE_FAILURE_RECEIPT_SCHEMA,
        "run_id": run_id,
        "logical_time": logical_time,
        "stage": stage,
        "reason_code": reason_code,
        "error_sha256": error_sha256,
        "failure_event_sha256": _sha(event_bytes),
        "parent_tel_sha256": identity["parent_tel_sha256"],
        "parent_tel_event_count": identity["parent_tel_event_count"],
        "partial_run_preserved": run_root.is_dir() and not _link_like(run_root),
        "sealed_run_mutated": False,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "publication_performed": False,
        "deployment_performed": False,
        "release_performed": False,
        "authority_effect": "NONE",
    }
    (failure_root / "route_failure_tel.jsonl").write_bytes(event_bytes)
    receipt_bytes = _canonical(receipt)
    (failure_root / "route_failure_receipt.json").write_bytes(receipt_bytes)
    (failure_root / "failure_checksums.sha256").write_bytes(
        (
            f"{_sha(receipt_bytes)}  route_failure_receipt.json\n"
            f"{_sha(event_bytes)}  route_failure_tel.jsonl\n"
        ).encode("ascii")
    )
    return receipt


def _verify_prepared(root: Path) -> dict[str, Any]:
    prepared = _safe_existing_dir(root, "PREPARED_INPUT_ROOT_UNSAFE")
    manifest_path = prepared / "input_manifest.json"
    if _link_like(manifest_path) or not manifest_path.is_file():
        raise RouteError("PREPARED_INPUT_MANIFEST_MISSING")
    manifest = _parse_object(
        _read_bounded(manifest_path, "input_manifest.json"),
        "input_manifest.json",
    )
    manifest_keys = {
        "schema_id",
        "run_id",
        "logical_time",
        "source_label",
        "segmentation_profile",
        "aha_mode",
        "request_sha256",
        "grounding_manifest_sha256",
        "task_consent_asserted",
        "privacy_policy_satisfied_asserted",
        "privacy_basis",
        "artifacts",
        "network_used",
        "provider_invoked",
        "memory_written",
        "training_used",
        "publication_performed",
        "deployment_performed",
        "release_performed",
        "authority_effect",
    }
    if set(manifest) != manifest_keys:
        raise RouteError("PREPARED_INPUT_MANIFEST_CONTRACT_INVALID")
    if (
        manifest["schema_id"] != "uvlm.triadicgate.totality_task_input_manifest.v1"
        or not isinstance(manifest["run_id"], str)
        or not _IDENTIFIER.fullmatch(manifest["run_id"])
        or not isinstance(manifest["logical_time"], str)
        or not manifest["logical_time"]
        or not isinstance(manifest["source_label"], str)
        or not manifest["source_label"]
        or manifest["segmentation_profile"]
        != "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1"
        or manifest["aha_mode"] not in {"UNAVAILABLE", "STRUCTURAL"}
        or not isinstance(manifest["request_sha256"], str)
        or not _HEX64.fullmatch(manifest["request_sha256"])
        or not isinstance(manifest["grounding_manifest_sha256"], str)
        or not _HEX64.fullmatch(manifest["grounding_manifest_sha256"])
        or not isinstance(manifest["task_consent_asserted"], bool)
        or not isinstance(manifest["privacy_policy_satisfied_asserted"], bool)
        or not isinstance(manifest["privacy_basis"], str)
        or not manifest["privacy_basis"]
        or manifest["network_used"] is not False
        or manifest["provider_invoked"] is not False
        or manifest["memory_written"] is not False
        or manifest["training_used"] is not False
        or manifest["publication_performed"] is not False
        or manifest["deployment_performed"] is not False
        or manifest["release_performed"] is not False
        or manifest["authority_effect"] != "NONE"
    ):
        raise RouteError("PREPARED_INPUT_MANIFEST_CONTRACT_INVALID")
    rows = manifest.get("artifacts")
    if not isinstance(rows, list) or not rows:
        raise RouteError("PREPARED_INPUT_INVENTORY_INVALID")
    expected: set[str] = {"input_manifest.json"}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "bytes"}:
            raise RouteError("PREPARED_INPUT_INVENTORY_INVALID")
        relative = row["path"]
        posix = PurePosixPath(relative) if isinstance(relative, str) else PurePosixPath("..")
        if posix.is_absolute() or ".." in posix.parts or "\\" in str(relative):
            raise RouteError("PREPARED_INPUT_PATH_UNSAFE")
        canonical_relative = posix.as_posix()
        if canonical_relative in seen:
            raise RouteError("PREPARED_INPUT_INVENTORY_INVALID")
        seen.add(canonical_relative)
        path = prepared.joinpath(*posix.parts)
        if not _member_safe(prepared, path) or not path.is_file():
            raise RouteError("PREPARED_INPUT_MEMBER_MISSING")
        payload = _read_bounded(path, canonical_relative)
        if not isinstance(row["sha256"], str) or not _HEX64.fullmatch(row["sha256"]):
            raise RouteError("PREPARED_INPUT_DIGEST_INVALID")
        if (
            isinstance(row["bytes"], bool)
            or not isinstance(row["bytes"], int)
            or row["bytes"] < 0
            or _sha(payload) != row["sha256"]
            or len(payload) != row["bytes"]
        ):
            raise RouteError("PREPARED_INPUT_IDENTITY_MISMATCH")
        expected.add(canonical_relative)
    allowed = {"source.bin", "request.json", "captured_semantic.json", "aha_case.json", "pmr_consent.json"}
    required = {"source.bin", "request.json", "captured_semantic.json"}
    if not required <= seen or not seen <= allowed:
        raise RouteError("PREPARED_INPUT_MEMBER_SET_MISMATCH")
    if (manifest["aha_mode"] == "STRUCTURAL") is not ("aha_case.json" in seen):
        raise RouteError("PREPARED_INPUT_AHA_MODE_MISMATCH")
    if rows != sorted(rows, key=lambda row: row["path"]):
        raise RouteError("PREPARED_INPUT_INVENTORY_ORDER_INVALID")
    actual = {
        path.relative_to(prepared).as_posix()
        for path in _walk_members(prepared, "PREPARED_INPUT_LINK_OR_ESCAPE_PROHIBITED")
        if path.is_file()
    }
    if actual != expected:
        raise RouteError("PREPARED_INPUT_MEMBER_SET_MISMATCH")
    request_raw = _read_bounded(prepared / "request.json", "request.json")
    request = _parse_object(request_raw, "request.json")
    capture = _parse_object(
        _read_bounded(
            prepared / "captured_semantic.json", "captured_semantic.json"
        ),
        "captured_semantic.json",
    )
    grounding = request.get("grounding")
    reference = grounding[0] if isinstance(grounding, list) and len(grounding) == 1 else None
    source = _read_bounded(prepared / "source.bin", "source.bin")
    if (
        manifest["request_sha256"] != _sha(request_raw)
        or request.get("schema_id") != "uvlm.coherence.totality.request_envelope.v1"
        or request.get("run_id") != manifest["run_id"]
        or request.get("logical_time") != manifest["logical_time"]
        or request.get("task_consent") is not manifest["task_consent_asserted"]
        or not isinstance(request.get("meta"), dict)
        or request["meta"].get("privacy_policy_satisfied")
        is not manifest["privacy_policy_satisfied_asserted"]
        or request["meta"].get("privacy_basis") != manifest["privacy_basis"]
        or not isinstance(reference, dict)
        or reference.get("source_kind") != "grounding_bundle"
        or reference.get("label") != manifest["source_label"]
        or reference.get("bundle_manifest_path") != "grounding/manifest.json"
        or reference.get("bundle_manifest_sha256") != manifest["grounding_manifest_sha256"]
        or reference.get("source_sha256") != _sha(source)
        or capture.get("schema_id") != "uvlm.sonya.totality.captured_semantic.v1"
    ):
        raise RouteError("PREPARED_INPUT_CROSS_BINDING_INVALID")
    return manifest


def _run_pipeline(
    *,
    repo: Path,
    request: Path,
    source: Path,
    captured: Path,
    run_root: Path,
    aha_case: Path | None,
    pmr_consent: Path | None,
    top_k: int,
    export_zip: Path | None,
    allow_dirty: bool,
) -> dict[str, Any]:
    arguments: list[str | Path] = [
        "build-core",
        "--source",
        source,
        "--task",
        request,
        "--captured",
        captured,
        "--out",
        run_root,
        "--top-k",
        str(top_k),
    ]
    if aha_case is not None:
        arguments.extend(("--aha-case", aha_case))
    if pmr_consent is not None:
        arguments.extend(("--pmr-consent", pmr_consent))
    core = _module(repo, "coherence", "coherence.totality.cli", arguments, expect_json=True)
    sophia = _module(
        repo,
        "sophia",
        "sophia.triadic.totality_audit",
        ("--run-root", run_root),
    )
    atlas = _module(
        repo,
        "atlas",
        "atlas.triadic.totality_posture",
        ("--run-root", run_root),
    )
    tel_finalization = _module(
        repo,
        "coherence",
        "coherence.totality.cli",
        ("finalize-route-tel", "--run-root", run_root),
        expect_json=True,
    )
    seal_args: list[str | Path] = ["seal", "--run-root", run_root, "--repo-root", repo]
    if allow_dirty:
        seal_args.append("--allow-dirty")
    if export_zip is not None:
        if not export_zip.is_absolute() or export_zip.exists() or _link_like(export_zip):
            raise RouteError("EXPORT_ZIP_UNSAFE_OR_EXISTS")
        seal_args.extend(("--zip", export_zip))
    sealed = _module(repo, "coherence", "coherence.totality.cli", seal_args, expect_json=True)
    verified = _module(
        repo,
        "coherence",
        "coherence.totality.cli",
        ("verify", "--run-root", run_root),
        expect_json=True,
    )
    audit = _parse_object(
        _read_bounded(
            run_root / "sophia_audit_packet.json", "sophia_audit_packet.json"
        ),
        "sophia_audit_packet.json",
    )
    posture = _parse_object(
        _read_bounded(
            run_root / "atlas_posture_packet.json", "atlas_posture_packet.json"
        ),
        "atlas_posture_packet.json",
    )
    return {
        "core": core,
        "sophia_process": sophia,
        "atlas_process": atlas,
        "sophia_disposition": audit.get("disposition"),
        "sophia_audit_id": audit.get("audit_id"),
        "atlas_retention_posture": posture.get("retention_posture"),
        "atlas_human_decision": posture.get("human_decision"),
        "tel_finalization": tel_finalization,
        "seal": sealed,
        "verification": verified,
    }


def build_product_route(
    repo_root: Path,
    prepared_input: Path,
    run_root: Path,
    *,
    top_k: int = 8,
    export_zip: Path | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    repo = _safe_repo(repo_root)
    prepared = _safe_existing_dir(prepared_input, "PREPARED_INPUT_ROOT_UNSAFE")
    run_candidate = run_root.resolve(strict=False)
    failure_candidate = run_candidate.with_name(run_candidate.name + ".route-failure")
    _require_disjoint_directories(
        ("repository", repo),
        ("prepared_input", prepared),
        ("run_root", run_candidate),
        ("failure_root", failure_candidate),
    )
    if failure_candidate.exists() or _link_like(failure_candidate):
        raise RouteError("ROUTE_FAILURE_EVIDENCE_ROOT_UNSAFE_OR_EXISTS")
    if export_zip is not None:
        if not _portable_artifact_name(export_zip.name):
            raise RouteError("EXPORT_ZIP_NAME_NOT_PORTABLE")
        export_zip = _require_external_new_file(
            export_zip,
            protected_roots=(repo, prepared, run_candidate, failure_candidate),
        )
        _require_external_new_file(
            export_zip.with_name(export_zip.name + ".sha256"),
            protected_roots=(repo, prepared, run_candidate, failure_candidate),
            other_outputs=(export_zip,),
        )
    manifest = _verify_prepared(prepared)
    run = _safe_new_dir(run_candidate)
    try:
        result = _run_pipeline(
            repo=repo,
            request=prepared / "request.json",
            source=prepared / "source.bin",
            captured=prepared / "captured_semantic.json",
            run_root=run,
            aha_case=(prepared / "aha_case.json") if (prepared / "aha_case.json").is_file() else None,
            pmr_consent=(prepared / "pmr_consent.json") if (prepared / "pmr_consent.json").is_file() else None,
            top_k=top_k,
            export_zip=export_zip,
            allow_dirty=allow_dirty,
        )
    except Exception as exc:
        try:
            _preserve_route_failure(
                failure_candidate,
                run_root=run,
                run_id=manifest["run_id"],
                logical_time=manifest["logical_time"],
                error=exc,
            )
        except Exception as preservation_error:
            raise RouteError(
                "ROUTE_FAILURE_PRESERVATION_FAILED:"
                + _sha(str(preservation_error).encode("utf-8", errors="replace"))
            ) from exc
        raise RouteError(f"ROUTE_FAILED_WITH_EXTERNAL_EVIDENCE:{_failure_stage(exc)}") from exc
    request = _parse_object(
        _read_bounded(prepared / "request.json", "request.json"),
        "request.json",
    )
    exported = result["seal"].get("zip")
    if export_zip is None:
        if exported is not None:
            raise RouteError("UNREQUESTED_EXPORT_RECEIPT")
    elif (
        not isinstance(exported, dict)
        or exported.get("zip_path") != export_zip.name
        or exported.get("zip_sidecar_path") != export_zip.name + ".sha256"
        or not _HEX64.fullmatch(str(exported.get("zip_sha256", "")))
        or not _HEX64.fullmatch(str(exported.get("zip_sidecar_sha256", "")))
        or isinstance(exported.get("zip_bytes"), bool)
        or not isinstance(exported.get("zip_bytes"), int)
        or exported["zip_bytes"] <= 0
    ):
        raise RouteError("NONPORTABLE_OR_INVALID_EXPORT_RECEIPT")
    receipt = {
        "schema_id": ROUTE_RECEIPT_SCHEMA,
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "run_root_name": run.name,
        "input_manifest_sha256": _sha(
            _read_bounded(prepared / "input_manifest.json", "input_manifest.json")
        ),
        "sophia_disposition": result["sophia_disposition"],
        "sophia_audit_id": result["sophia_audit_id"],
        "atlas_retention_posture": result["atlas_retention_posture"],
        "human_decision": result["atlas_human_decision"],
        "decision_id": result["tel_finalization"].get("decision_id"),
        "tel_event_count": result["tel_finalization"].get("event_count"),
        "tel_events_sha256": result["tel_finalization"].get("tel_events_sha256"),
        "external_human_continuation_required": result["tel_finalization"].get(
            "external_continuation_required"
        ),
        "export_zip": exported,
        "receipt_path_contract": "STABLE_ARTIFACT_NAMES_ONLY",
        "sealed": result["verification"].get("valid") is True,
        "files_verified": result["verification"].get("files_verified"),
        "repository_worktree_clean": result["seal"].get("repository_identity", {}).get("worktree_clean"),
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "publication_performed": False,
        "deployment_performed": False,
        "release_performed": False,
        "authority_effect": "NONE",
    }
    return receipt


def _tree(root: Path) -> dict[str, dict[str, Any]]:
    bounded = _safe_existing_dir(root, "RUN_ROOT_UNSAFE")
    rows: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for path in _walk_members(bounded, "RUN_TREE_LINK_OR_ESCAPE_PROHIBITED"):
        if not path.is_file():
            continue
        relative = path.relative_to(bounded).as_posix()
        digest, size = _hash_bounded(path, relative)
        total_bytes += size
        if total_bytes > MAX_ROUTE_TREE_BYTES:
            raise RouteError("RUN_TREE_SIZE_LIMIT_EXCEEDED")
        rows[relative] = {"sha256": digest, "bytes": size}
    return rows


def replay_product_route(
    repo_root: Path,
    original_run: Path,
    replay_root: Path,
    *,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    repo = _safe_repo(repo_root)
    original = _safe_existing_dir(original_run, "ORIGINAL_RUN_ROOT_UNSAFE")
    replay_candidate = replay_root.resolve(strict=False)
    failure_candidate = replay_candidate.with_name(
        replay_candidate.name + ".route-failure"
    )
    _require_disjoint_directories(
        ("repository", repo),
        ("original_run", original),
        ("replay_root", replay_candidate),
        ("failure_root", failure_candidate),
    )
    if failure_candidate.exists() or _link_like(failure_candidate):
        raise RouteError("ROUTE_FAILURE_EVIDENCE_ROOT_UNSAFE_OR_EXISTS")
    # Inventory first so no artifact is read or handed to a subprocess before
    # every member has been proven to be a bounded regular file.
    left = _tree(original)
    original_verification = _module(
        repo,
        "coherence",
        "coherence.totality.cli",
        ("verify", "--run-root", original),
        expect_json=True,
    )
    if original_verification.get("valid") is not True:
        raise RouteError("ORIGINAL_RUN_SEAL_INVALID")
    replay = _safe_new_dir(replay_candidate)
    original_projector = _parse_object(
        _read_bounded(
            original / "projector_receipt.json", "projector_receipt.json"
        ),
        "projector_receipt.json",
    )
    aha_result = _parse_object(
        _read_bounded(original / "aha_result.json", "aha_result.json"),
        "aha_result.json",
    )
    request = _parse_object(
        _read_bounded(original / "request.json", "request.json"),
        "request.json",
    )
    try:
        with tempfile.TemporaryDirectory(prefix=".totality-replay-input-", dir=replay.parent) as temporary:
            case = aha_result.get("case")
            case_path: Path | None = None
            if case is not None:
                case_path = Path(temporary) / "aha_case.json"
                case_path.write_bytes(_canonical(case))
            result = _run_pipeline(
                repo=repo,
                request=original / "request.json",
                source=original / "grounding/source.bin",
                captured=original / "sonya/raw_output.quarantine",
                run_root=replay,
                aha_case=case_path,
                pmr_consent=(original / "pmr_consent.json") if (original / "pmr_consent.json").is_file() else None,
                top_k=original_projector["presentation"]["top_k"],
                export_zip=None,
                allow_dirty=allow_dirty,
            )
    except Exception as exc:
        try:
            _preserve_route_failure(
                failure_candidate,
                run_root=replay,
                run_id=request.get("run_id", "UNKNOWN-RUN"),
                logical_time=request.get("logical_time", "UNKNOWN-TIME"),
                error=exc,
            )
        except Exception as preservation_error:
            raise RouteError(
                "ROUTE_FAILURE_PRESERVATION_FAILED:"
                + _sha(str(preservation_error).encode("utf-8", errors="replace"))
            ) from exc
        raise RouteError(f"REPLAY_FAILED_WITH_EXTERNAL_EVIDENCE:{_failure_stage(exc)}") from exc
    right = _tree(replay)
    differences = [path for path in sorted(set(left) | set(right)) if left.get(path) != right.get(path)]
    receipt = {
        "schema_id": REPLAY_RECEIPT_SCHEMA,
        "run_id": request.get("run_id"),
        "logical_time": request.get("logical_time"),
        "valid": not differences,
        "exact_tree_equality": not differences,
        "files_compared": len(left),
        "original_tree_sha256": _sha(_canonical(left)),
        "replay_tree_sha256": _sha(_canonical(right)),
        "differences": differences,
        "sophia_disposition": result["sophia_disposition"],
        "sophia_audit_id": result["sophia_audit_id"],
        "repository_worktree_clean": result["seal"].get("repository_identity", {}).get("worktree_clean"),
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "publication_performed": False,
        "deployment_performed": False,
        "release_performed": False,
        "authority_effect": "NONE",
    }
    return receipt


def _write_receipt(
    path: Path | None,
    value: dict[str, Any],
    *,
    protected_roots: Iterable[Path] = (),
    other_outputs: Iterable[Path] = (),
) -> None:
    if path is None:
        return
    path = _require_external_new_file(
        path, protected_roots=protected_roots, other_outputs=other_outputs
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(value))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", required=True, type=Path)
    build.add_argument("--prepared-input", required=True, type=Path)
    build.add_argument("--run-root", required=True, type=Path)
    build.add_argument("--top-k", type=int, default=8)
    build.add_argument("--export-zip", type=Path)
    build.add_argument("--receipt", type=Path)
    build.add_argument("--allow-dirty", action="store_true")
    replay = subparsers.add_parser("replay")
    replay.add_argument("--repo-root", required=True, type=Path)
    replay.add_argument("--original-run", required=True, type=Path)
    replay.add_argument("--replay-root", required=True, type=Path)
    replay.add_argument("--receipt", type=Path)
    replay.add_argument("--allow-dirty", action="store_true")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        receipt_path = arguments.receipt.resolve() if arguments.receipt else None
        if arguments.command == "build":
            repo_root = arguments.repo_root.resolve()
            prepared_input = arguments.prepared_input.resolve()
            run_root = arguments.run_root.resolve()
            export_zip = arguments.export_zip.resolve() if arguments.export_zip else None
            if receipt_path is not None:
                _require_external_new_file(
                    receipt_path,
                    protected_roots=(repo_root, prepared_input, run_root),
                    other_outputs=(
                        *(() if export_zip is None else (export_zip, export_zip.with_name(export_zip.name + ".sha256"))),
                    ),
                )
            result = build_product_route(
                repo_root,
                prepared_input,
                run_root,
                top_k=arguments.top_k,
                export_zip=export_zip,
                allow_dirty=arguments.allow_dirty,
            )
            protected_roots = (repo_root, prepared_input, run_root)
            other_outputs = () if export_zip is None else (
                export_zip,
                export_zip.with_name(export_zip.name + ".sha256"),
            )
        else:
            repo_root = arguments.repo_root.resolve()
            original_run = arguments.original_run.resolve()
            replay_root = arguments.replay_root.resolve()
            if receipt_path is not None:
                _require_external_new_file(
                    receipt_path,
                    protected_roots=(repo_root, original_run, replay_root),
                )
            result = replay_product_route(
                repo_root,
                original_run,
                replay_root,
                allow_dirty=arguments.allow_dirty,
            )
            protected_roots = (repo_root, original_run, replay_root)
            other_outputs = ()
        _write_receipt(
            receipt_path,
            result,
            protected_roots=protected_roots,
            other_outputs=other_outputs,
        )
        sys.stdout.write(_canonical(result).decode("utf-8"))
        return 0 if result.get("valid", result.get("sealed", False)) else 2
    except (OSError, RouteError) as exc:
        sys.stderr.write(_canonical({"valid": False, "error": type(exc).__name__, "reason": str(exc)}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
