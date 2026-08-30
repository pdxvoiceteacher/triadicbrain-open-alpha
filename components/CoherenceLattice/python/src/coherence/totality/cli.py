"""CLI composition for the additive private Coherence totality core."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from coherence.aegis.totality_admission import build_totality_admission_packet

from .adapter import (
    CapturedAdapter,
    MAX_RAW_OUTPUT_BYTES,
    build_candidate_packet,
    build_quarantine_verification_receipt,
    read_quarantined_capture,
)
from .aha import evaluate_structural_aha
from .atlas_contract import validate_atlas_posture_packet
from .aperture import decide_aperture
from .canonical import (
    canonical_json_bytes,
    require_exact_keys,
    require_identifier,
    require_sha256,
    sha256_bytes,
    sha256_file,
    sha256_json,
    strict_json_loads,
    write_canonical_json,
)
from .claims import build_claim_evidence_map
from .counterexamples import search_counterexamples
from .errors import OperationalError, TotalityError, ValidationError
from .grounding import MAX_SOURCE_BYTES, build_grounding_bundle, write_grounding_bundle
from .plugins import disabled_plugin_catalog_receipt, validate_disabled_plugin_catalog
from .pmr import PMRReferenceStore, no_write_receipt, validate_consent_packet
from .request import parse_request_envelope
from .seal import (
    _link_like,
    _walk_members,
    build_core_manifest,
    build_deterministic_zip,
    seal_run,
    verify_core_manifest_contract,
    verify_sealed_run,
)
from .tel import AUDIT_PREFIX_ORDER, SEALED_ROUTE_ORDER, TELLedger, derive_audit_id, derive_decision_id, parse_tel_jsonl
from .ucm import AXES, build_ucm_state, project_ucm
from .waveform import encode_reference_waveform

BUILD_RECEIPT_SCHEMA = "uvlm.coherence.totality.build_core_receipt.v1"
DEFAULT_AXES = {
    "E_cpl": 1.0,
    "T_tr": 1.0,
    "E_s": 1.0,
    "phase_stability_lambda": 0.8,
    "mutual_containment_mu": 1.0,
}
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_AHA_CASE_BYTES = 4 * 1024 * 1024
MAX_PMR_CONSENT_BYTES = 1024 * 1024
MAX_ROUTE_PACKET_BYTES = 16 * 1024 * 1024


def _object(data: bytes, name: str) -> dict[str, Any]:
    value = strict_json_loads(data)
    if not isinstance(value, dict):
        raise ValidationError(f"CLI_JSON_OBJECT_REQUIRED:{name}")
    return value


def _read_cli_input(path: Path, name: str, *, maximum_bytes: int | None = None) -> bytes:
    reason = f"BUILD_{name.upper()}_INPUT_UNAVAILABLE"
    try:
        if _link_like(path) or not path.is_file():
            raise OperationalError(reason)
        if maximum_bytes is not None and path.stat().st_size > maximum_bytes:
            raise ValidationError(f"BUILD_{name.upper()}_INPUT_LIMIT_EXCEEDED")
        with path.open("rb") as stream:
            data = stream.read(None if maximum_bytes is None else maximum_bytes + 1)
    except TotalityError:
        raise
    except OSError as exc:
        raise OperationalError(reason) from exc
    if maximum_bytes is not None and len(data) > maximum_bytes:
        raise ValidationError(f"BUILD_{name.upper()}_INPUT_LIMIT_EXCEEDED")
    return data


def _safe_new_output(path: Path) -> Path:
    if not path.is_absolute() or path == Path(path.anchor) or path.exists() or path.is_symlink():
        raise OperationalError("BUILD_OUTPUT_PATH_UNSAFE_OR_EXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _external_receipt_path(path: Path, protected_root: Path) -> Path:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise OperationalError("REPLAY_RECEIPT_OUTPUT_UNSAFE_OR_EXISTS")
    resolved = path.resolve(strict=False)
    root = protected_root.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    raise OperationalError("REPLAY_RECEIPT_INSIDE_RUN_ROOT_PROHIBITED")


def _verify_request_grounding(request: Mapping[str, Any], bundle: Mapping[str, Any]) -> None:
    del bundle  # Binding is evaluated by the actual-input AEGIS gate below.
    refs = request["grounding"]
    if len(refs) != 1 or refs[0]["source_kind"] != "grounding_bundle":
        raise ValidationError("PRIOR_REINJECTION_DORMANT")


def _axes_and_hypotheses(request: Mapping[str, Any], claim_map: Mapping[str, Any], uncertainty: float) -> tuple[dict[str, float], Any]:
    meta = request["meta"]
    supported = len(claim_map["claims"]) - len(claim_map["unsupported_claim_ids"])
    support_ratio = supported / max(1, len(claim_map["claims"]))
    defaults = {
        **DEFAULT_AXES,
        "E_cpl": support_ratio,
        "phase_stability_lambda": 1.0 - uncertainty,
        "mutual_containment_mu": support_ratio,
    }
    axes = meta.get("ucm_axes", defaults)
    hypotheses = meta.get("ucm_hypotheses")
    return dict(axes), hypotheses


def _write_artifact(root: Path, relative: str, value: Any) -> None:
    write_canonical_json(root / relative, value, exclusive=True)


def _build_core_success_from_inputs(
    *,
    request_bytes: bytes,
    source_bytes: bytes,
    captured_bytes: bytes,
    output_dir: Path,
    aha_case: dict[str, Any] | None = None,
    pmr_consent: dict[str, Any] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    output_dir = _safe_new_output(output_dir)
    request_envelope = parse_request_envelope(request_bytes)
    request = request_envelope.to_dict()
    if request_bytes != canonical_json_bytes(request):
        raise ValidationError("BUILD_REQUEST_NOT_CANONICAL_BYTES")
    bundle = build_grounding_bundle(source_bytes)
    _verify_request_grounding(request, bundle)
    request_sha = sha256_json(request)
    aegis_admission = build_totality_admission_packet(
        request,
        bundle,
        request_sha256=request_sha,
    )
    temp = Path(tempfile.mkdtemp(prefix=".totality-build-", dir=output_dir.parent))
    try:
        _write_artifact(temp, "request.json", request)
        write_grounding_bundle(bundle, temp / "grounding")
        _write_artifact(temp, "aegis_admission_packet.json", aegis_admission)
        adapter = CapturedAdapter.reference()
        _write_artifact(temp, "sonya/adapter_contract.json", dict(adapter.contract))
        quarantine_path = temp / "sonya/raw_output.quarantine"
        quarantine_receipt = adapter.quarantine(
            captured_bytes,
            quarantine_path,
            request_sha256=request_sha,
            task_consent=request["task_consent"],
        )
        _write_artifact(temp, "sonya/quarantine_receipt.json", quarantine_receipt)
        capture = read_quarantined_capture(
            quarantine_path,
            quarantine_receipt,
            expected_request_sha256=request_sha,
        )
        candidate = build_candidate_packet(
            capture,
            quarantine_receipt,
            request_sha256=request_sha,
            run_id=request["run_id"],
            logical_time=request["logical_time"],
        )
        _write_artifact(temp, "candidate_packet.json", candidate)
        candidate_sha = sha256_json(candidate)
        quarantine_verification = build_quarantine_verification_receipt(
            quarantine_path,
            quarantine_receipt,
            candidate,
            request_sha256=request_sha,
            run_id=request["run_id"],
            logical_time=request["logical_time"],
        )
        _write_artifact(
            temp,
            "sonya/quarantine_verification_receipt.json",
            quarantine_verification,
        )
        claim_map = build_claim_evidence_map(candidate, bundle, candidate_sha256=candidate_sha)
        _write_artifact(temp, "claim_evidence_map.json", claim_map)
        axes, hypotheses = _axes_and_hypotheses(request, claim_map, candidate["uncertainty"])
        expected_context = {
            "request_sha256": request_sha,
            "candidate_sha256": candidate_sha,
            "grounding_manifest_sha256": sha256_json(bundle["manifest"]),
            "source_sha256": bundle["manifest"]["source_sha256"],
            "claim_map_sha256": sha256_json(claim_map),
        }
        ucm_state = build_ucm_state(
            run_id=request["run_id"], candidate_id=candidate["candidate_id"],
            expected_context=expected_context, axes=axes, uncertainty=candidate["uncertainty"],
            source_ref_count=len(request["grounding"]),
            unsupported_claim_ids=claim_map["unsupported_claim_ids"], hypotheses=hypotheses,
        )
        _write_artifact(temp, "ucm_state.json", ucm_state)
        projected = project_ucm(ucm_state, top_k=top_k)
        projector, residual_refusal = projected["projector"], projected["residual_refusal"]
        _write_artifact(temp, "projector_receipt.json", projector)
        _write_artifact(temp, "residual_refusal.json", residual_refusal)
        aha_result = evaluate_structural_aha(
            aha_case,
            grounding_bundle=bundle,
            run_id=request["run_id"],
            candidate_id=candidate["candidate_id"],
            candidate_sha256=candidate_sha,
        )
        _write_artifact(temp, "aha_result.json", aha_result)
        counterexamples = search_counterexamples(
            claim_map, bundle, run_id=request["run_id"], candidate_id=candidate["candidate_id"],
            candidate_sha256=candidate_sha,
        )
        _write_artifact(temp, "counterexamples.json", counterexamples)
        waveform = encode_reference_waveform(ucm_state["axes"])
        _write_artifact(temp, "reference_waveform.json", waveform)
        consent = validate_consent_packet(pmr_consent) if pmr_consent is not None else None
        if consent is not None:
            if (
                consent["run_id"] != request["run_id"]
                or consent["candidate_id"] != candidate["candidate_id"]
                or consent["logical_time"] != request["logical_time"]
                or request["retention_requested"] is not True
            ):
                raise ValidationError("PMR_CONSENT_CONTEXT_MISMATCH")
            store = PMRReferenceStore()
            store.apply_consent(consent)
            pmr_receipt = store.receipt(consent["consent_id"])
            _write_artifact(temp, "pmr_consent.json", consent)
            retention_consent = consent["decision"] == "GRANT"
        else:
            pmr_receipt = no_write_receipt(
                run_id=request["run_id"], candidate_id=candidate["candidate_id"],
                logical_time=request["logical_time"], reason="PMR_SEPARATE_CONSENT_NOT_GRANTED",
            )
            retention_consent = False
        _write_artifact(temp, "pmr_receipt.json", pmr_receipt)
        privacy = request["meta"].get("privacy_policy_satisfied")
        if not isinstance(privacy, bool):
            raise ValidationError("BUILD_PRIVACY_POLICY_BOOLEAN_REQUIRED")
        privacy_basis = request["meta"].get("privacy_basis")
        if not isinstance(privacy_basis, str) or not privacy_basis.strip() or len(privacy_basis) > 1000:
            raise ValidationError("BUILD_PRIVACY_BASIS_REQUIRED")
        aperture = decide_aperture(
            run_id=request["run_id"], candidate_id=candidate["candidate_id"], projector=projector,
            residual_refusal=residual_refusal, aha_result=aha_result, counterexamples=counterexamples,
            task_consent=request["task_consent"], privacy_policy_satisfied=privacy,
            retention_requested=request["retention_requested"], retention_consent=retention_consent,
            claim_evidence_valid=not claim_map["unsupported_claim_ids"],
        )
        _write_artifact(temp, "aperture_decision.json", aperture)
        plugins = validate_disabled_plugin_catalog(disabled_plugin_catalog_receipt())
        _write_artifact(temp, "optional_plugin_receipts.json", plugins)
        audit_id = derive_audit_id(candidate_sha, sha256_json(aperture))
        decision_id = derive_decision_id(audit_id, request["run_id"])
        tel = TELLedger(request["run_id"])
        tel.emit("REQUEST_CANONICALIZED", payload={"request_sha256": request_sha})
        tel.emit("GROUNDING_VERIFIED", payload={"grounding_manifest_sha256": expected_context["grounding_manifest_sha256"]})
        tel.emit("RAW_OUTPUT_QUARANTINED", payload={"raw_output_sha256": quarantine_receipt["raw_output_sha256"]})
        tel.emit("CANDIDATE_CANONICALIZED", candidate_id=candidate["candidate_id"], payload={"candidate_sha256": candidate_sha})
        tel.emit("CLAIM_EVIDENCE_MAPPED", candidate_id=candidate["candidate_id"], payload={"claim_map_sha256": expected_context["claim_map_sha256"]})
        tel.emit("UCM_PROJECTED", outcome=projector["disposition"].replace("PASS_SCREEN", "SUCCESS"), candidate_id=candidate["candidate_id"], payload={"ucm_state_sha256": sha256_json(ucm_state), "projector_receipt_sha256": sha256_json(projector)})
        tel.emit("AHA_EVALUATED", outcome="SUCCESS" if aha_result["disposition"] == "REVIEWABLE" else "HOLD" if aha_result["disposition"] == "UNAVAILABLE" else "REFUSE", candidate_id=candidate["candidate_id"], payload={"aha_result_sha256": sha256_json(aha_result)})
        tel.emit("COUNTEREXAMPLES_SCANNED", candidate_id=candidate["candidate_id"], payload={"counterexamples_sha256": sha256_json(counterexamples), "unresolved_count": counterexamples["unresolved_count"]})
        tel.emit("REFERENCE_WAVEFORM_ENCODED", candidate_id=candidate["candidate_id"], payload={"reference_waveform_sha256": sha256_json(waveform), "physical_frequency_claim": False})
        tel.emit("APERTURE_DECIDED", outcome=aperture["decision"].replace("PASS_SCREEN", "SUCCESS"), candidate_id=candidate["candidate_id"], payload={"aperture_decision_sha256": sha256_json(aperture), "decision": aperture["decision"]})
        tel.emit("PMR_BOUNDARY_RECORDED", outcome="RECORDED", candidate_id=candidate["candidate_id"], payload={"pmr_receipt_sha256": sha256_json(pmr_receipt), "persistent_bytes_written": 0})
        tel.emit("SOPHIA_AUDIT_REQUESTED", outcome="RECORDED", candidate_id=candidate["candidate_id"], audit_id=audit_id, payload={"status": "REQUESTED_NOT_EXECUTED"})
        tel.emit("ATLAS_ORIENTATION_PENDING", outcome="RECORDED", candidate_id=candidate["candidate_id"], audit_id=audit_id, payload={"status": "PENDING_SOPHIA"})
        tel.emit("HUMAN_DECISION_PENDING", outcome="RECORDED", candidate_id=candidate["candidate_id"], audit_id=audit_id, decision_id=decision_id, payload={"status": "PENDING", "external_receipt_required": True})
        tel.emit("CORE_BUILD_COMPLETED", outcome="RECORDED", candidate_id=candidate["candidate_id"], audit_id=audit_id, decision_id=decision_id, payload={"stop_boundary": "BEFORE_SOPHIA_AND_ATLAS"})
        tel_prefix_bytes = tel.to_jsonl_bytes()
        (temp / "tel_audit_prefix.jsonl").write_bytes(tel_prefix_bytes)
        # Compatibility projection only; finalization replaces this alias after
        # Sophia and Atlas bind the immutable audit prefix.
        (temp / "tel_events.jsonl").write_bytes(tel_prefix_bytes)
        receipt = {
            "schema_id": BUILD_RECEIPT_SCHEMA,
            "run_id": request["run_id"], "logical_time": request["logical_time"],
            "candidate_id": candidate["candidate_id"], "candidate_sha256": candidate_sha,
            "audit_id": audit_id, "decision_id": decision_id,
            "aperture": aperture["decision"], "sophia_status": "REQUESTED_NOT_EXECUTED",
            "atlas_status": "PENDING_SOPHIA", "human_decision": "PENDING",
            "network_used": False, "provider_invoked": False, "memory_written": False,
            "training_used": False, "publication_performed": False, "deployment_performed": False,
            "release_performed": False, "authority_effect": "NONE",
        }
        _write_artifact(temp, "build_core_receipt.json", receipt)
        core_manifest = build_core_manifest(temp, run_id=request["run_id"], logical_time=request["logical_time"])
        _write_artifact(temp, "core_manifest.json", core_manifest)
        os.replace(temp, output_dir)
        return {**receipt, "core_manifest_sha256": sha256_json(core_manifest)}
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def _failure_stage(reason_code: str) -> str:
    groups = (
        ("aegis_admission", ("AEGIS_", "PRIOR_REINJECTION_DORMANT")),
        ("grounding_binding", ("GROUNDING",)),
        ("candidate_canonicalization", ("CANDIDATE",)),
        ("request_validation", ("REQUEST", "JSON", "UNICODE", "TEXT_")),
        ("sonya_quarantine", ("ADAPTER", "QUARANTINE", "CAPTURE")),
        ("claim_evidence_mapping", ("CLAIM",)),
        ("ucm_projection", ("UCM", "PROJECTOR")),
        ("aha_evaluation", ("AHA",)),
        ("counterexample_search", ("COUNTEREXAMPLE",)),
        ("pmr_boundary", ("PMR",)),
        ("aperture_decision", ("PRIVACY", "APERTURE", "RETENTION")),
        ("seal_preflight", ("SEAL", "REPOSITORY", "ZIP")),
    )
    for stage, prefixes in groups:
        if any(token in reason_code for token in prefixes):
            return stage
    return "core_build"


def _failure_identity(request_bytes: bytes, source_bytes: bytes, captured_bytes: bytes) -> tuple[str, str]:
    seed = (
        sha256_bytes(request_bytes) + sha256_bytes(source_bytes) + sha256_bytes(captured_bytes)
    ).encode("ascii")
    fallback = "FAILRUN-" + sha256_bytes(seed)[:20]
    try:
        request = strict_json_loads(request_bytes)
        if not isinstance(request, dict):
            return fallback, "INPUT-DERIVED"
        run_id = require_identifier(request.get("run_id"), "$.run_id")
        logical_time = request.get("logical_time")
        if not isinstance(logical_time, str) or not logical_time or len(logical_time) > 128:
            logical_time = "INPUT-DERIVED"
        return run_id, logical_time
    except TotalityError:
        return fallback, "INPUT-DERIVED"


def _emit_failure_output(
    output_dir: Path,
    *,
    request_bytes: bytes,
    source_bytes: bytes,
    captured_bytes: bytes,
    reason_code: str,
) -> dict[str, Any]:
    output = _safe_new_output(output_dir)
    run_id, logical_time = _failure_identity(request_bytes, source_bytes, captured_bytes)
    stage = _failure_stage(reason_code)
    output.mkdir(parents=True)
    ledger = TELLedger(run_id)
    ledger.failure(stage, reason_code)
    tel_bytes = ledger.to_jsonl_bytes()
    receipt = {
        "schema_id": "uvlm.coherence.totality.build_failure_receipt.v1",
        "run_id": run_id,
        "logical_time": logical_time,
        "stage": stage,
        "reason_code": reason_code,
        "input_bindings": {
            "request_input_sha256": sha256_bytes(request_bytes),
            "source_input_sha256": sha256_bytes(source_bytes),
            "captured_input_sha256": sha256_bytes(captured_bytes),
        },
        "tel_events_sha256": sha256_bytes(tel_bytes),
        "partial_run_promoted": False,
        "success_artifacts_emitted": False,
        "retry_safe": True,
        "effects": {
            "network": False, "provider_invocation": False, "memory_write": False,
            "training": False, "publication": False, "deployment": False, "release": False,
        },
        "authority_effect": "NONE",
    }
    receipt_bytes = canonical_json_bytes(receipt)
    (output / "failure_receipt.json").write_bytes(receipt_bytes)
    (output / "tel_events.jsonl").write_bytes(tel_bytes)
    rows = [
        {"path": "failure_receipt.json", "sha256": sha256_bytes(receipt_bytes), "bytes": len(receipt_bytes)},
        {"path": "tel_events.jsonl", "sha256": sha256_bytes(tel_bytes), "bytes": len(tel_bytes)},
    ]
    manifest = {
        "schema_id": "uvlm.coherence.totality.failure_manifest.v1",
        "run_id": run_id,
        "logical_time": logical_time,
        "artifact_count": len(rows),
        "artifact_bytes": sum(row["bytes"] for row in rows),
        "artifacts": rows,
        "successful_run": False,
        "authority_effect": "NONE",
    }
    manifest_bytes = canonical_json_bytes(manifest)
    (output / "failure_manifest.json").write_bytes(manifest_bytes)
    checks = [*rows, {"path": "failure_manifest.json", "sha256": sha256_bytes(manifest_bytes), "bytes": len(manifest_bytes)}]
    (output / "failure_checksums.sha256").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in sorted(checks, key=lambda row: row["path"])),
        encoding="utf-8", newline="\n",
    )
    return receipt


def build_core_from_inputs(
    *,
    request_bytes: bytes,
    source_bytes: bytes,
    captured_bytes: bytes,
    output_dir: Path,
    aha_case: dict[str, Any] | None = None,
    pmr_consent: dict[str, Any] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    try:
        return _build_core_success_from_inputs(
            request_bytes=request_bytes,
            source_bytes=source_bytes,
            captured_bytes=captured_bytes,
            output_dir=output_dir,
            aha_case=aha_case,
            pmr_consent=pmr_consent,
            top_k=top_k,
        )
    except (TotalityError, OSError) as exc:
        reason = _failure_reason(exc)
        if output_dir.is_absolute() and output_dir != Path(output_dir.anchor) and not output_dir.exists() and not output_dir.is_symlink():
            _emit_failure_output(
                output_dir,
                request_bytes=request_bytes,
                source_bytes=source_bytes,
                captured_bytes=captured_bytes,
                reason_code=reason,
            )
        raise


def _failure_reason(exc: BaseException) -> str:
    reason = str(exc).split(":", 1)[0]
    if not reason or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for char in reason):
        reason = "LOCAL_OPERATION_FAILED" if isinstance(exc, OSError) else "CORE_BUILD_FAILED"
    return reason


def build_core_from_paths(
    *,
    request_path: Path,
    source_path: Path,
    captured_path: Path,
    output_dir: Path,
    aha_case_path: Path | None = None,
    pmr_consent_path: Path | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """Acquire CLI inputs inside the deterministic failure-preservation boundary."""

    request_bytes = b""
    source_bytes = b""
    captured_bytes = b""
    try:
        request_bytes = _read_cli_input(
            request_path, "request", maximum_bytes=MAX_REQUEST_BYTES
        )
        source_bytes = _read_cli_input(
            source_path, "source", maximum_bytes=MAX_SOURCE_BYTES
        )
        captured_bytes = _read_cli_input(
            captured_path, "captured", maximum_bytes=MAX_RAW_OUTPUT_BYTES
        )
        try:
            aha_case = (
                _object(
                    _read_cli_input(
                        aha_case_path,
                        "aha_case",
                        maximum_bytes=MAX_AHA_CASE_BYTES,
                    ),
                    "aha_case",
                )
                if aha_case_path is not None
                else None
            )
        except TotalityError as exc:
            raise ValidationError("BUILD_AHA_CASE_INPUT_INVALID") from exc
        try:
            pmr_consent = (
                _object(
                    _read_cli_input(
                        pmr_consent_path,
                        "pmr_consent",
                        maximum_bytes=MAX_PMR_CONSENT_BYTES,
                    ),
                    "pmr_consent",
                )
                if pmr_consent_path is not None
                else None
            )
        except TotalityError as exc:
            raise ValidationError("BUILD_PMR_CONSENT_INPUT_INVALID") from exc
        return build_core_from_inputs(
            request_bytes=request_bytes,
            source_bytes=source_bytes,
            captured_bytes=captured_bytes,
            output_dir=output_dir,
            aha_case=aha_case,
            pmr_consent=pmr_consent,
            top_k=top_k,
        )
    except (TotalityError, OSError) as exc:
        if (
            output_dir.is_absolute()
            and output_dir != Path(output_dir.anchor)
            and not output_dir.exists()
            and not output_dir.is_symlink()
        ):
            _emit_failure_output(
                output_dir,
                request_bytes=request_bytes,
                source_bytes=source_bytes,
                captured_bytes=captured_bytes,
                reason_code=_failure_reason(exc),
            )
        raise


def verify_failure_output(root: Path) -> dict[str, Any]:
    expected_names = {
        "failure_receipt.json", "tel_events.jsonl", "failure_manifest.json", "failure_checksums.sha256"
    }
    if not root.is_absolute() or not root.is_dir() or _link_like(root):
        raise OperationalError("FAILURE_ROOT_UNSAFE")
    resolved = root.resolve(strict=True)
    actual = {
        path.relative_to(resolved).as_posix()
        for path in _walk_members(resolved)
        if path.is_file()
    }
    if actual != expected_names:
        raise ValidationError("FAILURE_ARTIFACT_SET_INVALID")
    receipt_raw = _read_cli_input(
        root / "failure_receipt.json", "failure_receipt", maximum_bytes=MAX_ROUTE_PACKET_BYTES
    )
    receipt = _object(receipt_raw, "failure_receipt.json")
    if receipt_raw != canonical_json_bytes(receipt):
        raise ValidationError("FAILURE_RECEIPT_NOT_CANONICAL")
    require_exact_keys(
        receipt,
        required={
            "schema_id", "run_id", "logical_time", "stage", "reason_code", "input_bindings",
            "tel_events_sha256", "partial_run_promoted", "success_artifacts_emitted", "retry_safe",
            "effects", "authority_effect",
        },
    )
    require_exact_keys(
        receipt["input_bindings"],
        required={"request_input_sha256", "source_input_sha256", "captured_input_sha256"},
        path="$.input_bindings",
    )
    require_exact_keys(
        receipt["effects"],
        required={"network", "provider_invocation", "memory_write", "training", "publication", "deployment", "release"},
        path="$.effects",
    )
    require_identifier(receipt["run_id"], "$.run_id")
    require_identifier(receipt["stage"], "$.stage")
    require_identifier(receipt["reason_code"], "$.reason_code")
    if not isinstance(receipt["logical_time"], str) or not receipt["logical_time"] or len(receipt["logical_time"]) > 128:
        raise ValidationError("FAILURE_LOGICAL_TIME_INVALID")
    require_sha256(receipt["tel_events_sha256"], "$.tel_events_sha256")
    for name, digest in receipt["input_bindings"].items():
        require_sha256(digest, f"$.input_bindings.{name}")
    if (
        receipt["schema_id"] != "uvlm.coherence.totality.build_failure_receipt.v1"
        or receipt["partial_run_promoted"] is not False
        or receipt["success_artifacts_emitted"] is not False
        or receipt["retry_safe"] is not True
        or receipt["authority_effect"] != "NONE"
        or any(value is not False for value in receipt["effects"].values())
    ):
        raise ValidationError("FAILURE_RECEIPT_POSTURE_INVALID")
    tel_raw = _read_cli_input(
        root / "tel_events.jsonl", "failure_tel", maximum_bytes=MAX_ROUTE_PACKET_BYTES
    )
    ledger = parse_tel_jsonl(tel_raw)
    if (
        len(ledger.rows) != 1 or ledger.rows[0]["event_type"] != "STAGE_FAILED"
        or ledger.rows[0]["run_id"] != receipt["run_id"]
        or ledger.rows[0]["payload"] != {"stage": receipt["stage"], "reason_code": receipt["reason_code"]}
        or receipt["tel_events_sha256"] != sha256_bytes(tel_raw)
    ):
        raise ValidationError("FAILURE_TEL_BINDING_INVALID")
    manifest_raw = _read_cli_input(
        root / "failure_manifest.json", "failure_manifest", maximum_bytes=MAX_ROUTE_PACKET_BYTES
    )
    manifest = _object(manifest_raw, "failure_manifest.json")
    if manifest_raw != canonical_json_bytes(manifest):
        raise ValidationError("FAILURE_MANIFEST_NOT_CANONICAL")
    require_exact_keys(
        manifest,
        required={
            "schema_id", "run_id", "logical_time", "artifact_count", "artifact_bytes",
            "artifacts", "successful_run", "authority_effect",
        },
    )
    expected_rows = [
        {"path": name, "sha256": sha256_file(root / name), "bytes": (root / name).stat().st_size}
        for name in ("failure_receipt.json", "tel_events.jsonl")
    ]
    if (
        manifest["schema_id"] != "uvlm.coherence.totality.failure_manifest.v1"
        or (manifest["run_id"], manifest["logical_time"]) != (receipt["run_id"], receipt["logical_time"])
        or manifest["artifacts"] != expected_rows or manifest["artifact_count"] != 2
        or manifest.get("artifact_bytes") != sum(row["bytes"] for row in expected_rows)
        or manifest.get("successful_run") is not False or manifest.get("authority_effect") != "NONE"
    ):
        raise ValidationError("FAILURE_MANIFEST_INVALID")
    expected_checks = {
        name: sha256_file(root / name)
        for name in ("failure_receipt.json", "failure_manifest.json", "tel_events.jsonl")
    }
    sidecar_raw = _read_cli_input(
        root / "failure_checksums.sha256", "failure_checksums", maximum_bytes=8 * 1024 * 1024
    )
    if not sidecar_raw or not sidecar_raw.endswith(b"\n") or b"\r" in sidecar_raw or b"\x00" in sidecar_raw:
        raise ValidationError("FAILURE_CHECKSUM_FORMAT_INVALID")
    try:
        lines = sidecar_raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValidationError("FAILURE_CHECKSUM_UTF8_INVALID") from exc
    observed: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if (
            len(parts) != 2 or parts[1] in observed or parts[1] not in expected_checks
            or len(parts[0]) != 64 or any(char not in "0123456789abcdef" for char in parts[0])
        ):
            raise ValidationError("FAILURE_CHECKSUM_FORMAT_INVALID")
        observed[parts[1]] = parts[0]
    if observed != expected_checks or list(observed) != sorted(observed):
        raise ValidationError("FAILURE_CHECKSUM_MISMATCH")
    return receipt


def _canonical_packet(path: Path, name: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_cli_input(path, name, maximum_bytes=MAX_ROUTE_PACKET_BYTES)
    value = _object(raw, name)
    if raw != canonical_json_bytes(value):
        raise ValidationError(f"ROUTE_PACKET_NOT_CANONICAL:{name}")
    return value, raw


def _bound_digest(packet: Mapping[str, Any], relative: str) -> str | None:
    digests = packet.get("input_digests")
    if not isinstance(digests, dict):
        return None
    entry = digests.get(relative)
    return entry.get("file_sha256") if isinstance(entry, dict) else None


def finalize_route_tel(run_root: Path) -> dict[str, Any]:
    """Append audited route completion without changing the Sophia-bound prefix."""

    if not run_root.is_absolute() or not run_root.is_dir() or _link_like(run_root):
        raise OperationalError("TEL_FINALIZATION_ROOT_UNSAFE")
    if (run_root / "checksums.sha256").exists() or (run_root / "run_manifest.json").exists():
        raise OperationalError("TEL_FINALIZATION_AFTER_SEAL_PROHIBITED")
    verify_core_manifest(run_root)
    request, _ = _canonical_packet(run_root / "request.json", "request.json")
    candidate, _ = _canonical_packet(run_root / "candidate_packet.json", "candidate_packet.json")
    sophia, sophia_raw = _canonical_packet(run_root / "sophia_audit_packet.json", "sophia_audit_packet.json")
    atlas, atlas_raw = _canonical_packet(run_root / "atlas_posture_packet.json", "atlas_posture_packet.json")
    prefix_path = run_root / "tel_audit_prefix.jsonl"
    prefix_raw = _read_cli_input(
        prefix_path, "tel_audit_prefix", maximum_bytes=MAX_ROUTE_PACKET_BYTES
    )
    prefix = parse_tel_jsonl(prefix_raw)
    if tuple(row["event_type"] for row in prefix.rows) != AUDIT_PREFIX_ORDER:
        raise ValidationError("TEL_AUDIT_PREFIX_ORDER_INVALID")
    run_id, logical_time = request.get("run_id"), request.get("logical_time")
    candidate_id = candidate.get("candidate_id")
    audit_id = derive_audit_id(sha256_json(candidate), sha256_file(run_root / "aperture_decision.json"))
    decision_id = derive_decision_id(audit_id, run_id)
    if (
        candidate.get("run_id") != run_id or candidate.get("logical_time") != logical_time
        or sophia.get("run_id") != run_id or sophia.get("logical_time") != logical_time
        or sophia.get("candidate_id") != candidate_id or sophia.get("audit_id") != audit_id
        or sophia.get("disposition") not in {"PASS", "HOLD", "REJECT"}
    ):
        raise ValidationError("TEL_SOPHIA_IDENTITY_OR_DISPOSITION_INVALID")
    if (
        atlas.get("run_id") != run_id or atlas.get("logical_time") != logical_time
        or atlas.get("candidate_id") != candidate_id or atlas.get("audit_id") != audit_id
        or atlas.get("sophia_disposition") != sophia.get("disposition")
        or atlas.get("requires_human_review") is not True or atlas.get("human_decision") != "PENDING"
    ):
        raise ValidationError("TEL_ATLAS_IDENTITY_OR_POSTURE_INVALID")
    validate_atlas_posture_packet(
        atlas, sophia_disposition=sophia["disposition"]
    )
    prefix_sha = sha256_bytes(prefix_raw)
    sophia_sha, atlas_sha = sha256_bytes(sophia_raw), sha256_bytes(atlas_raw)
    if _bound_digest(sophia, "tel_audit_prefix.jsonl") != prefix_sha:
        raise ValidationError("TEL_SOPHIA_PREFIX_BINDING_INVALID")
    if (
        _bound_digest(atlas, "tel_audit_prefix.jsonl") != prefix_sha
        or _bound_digest(atlas, "sophia_audit_packet.json") != sophia_sha
    ):
        raise ValidationError("TEL_ATLAS_PARENT_BINDING_INVALID")
    ledger = TELLedger(run_id, prefix.rows)
    sophia_outcome = {"PASS": "SUCCESS", "HOLD": "HOLD", "REJECT": "REFUSE"}[sophia["disposition"]]
    ledger.emit(
        "SOPHIA_AUDIT_COMPLETED", outcome=sophia_outcome, candidate_id=candidate_id,
        audit_id=audit_id, decision_id=decision_id,
        payload={"sophia_audit_packet_sha256": sophia_sha, "disposition": sophia["disposition"]},
    )
    ledger.emit(
        "ATLAS_ORIENTATION_COMPLETED", outcome="RECORDED", candidate_id=candidate_id,
        audit_id=audit_id, decision_id=decision_id,
        payload={"atlas_posture_packet_sha256": atlas_sha, "human_decision": "PENDING"},
    )
    ledger.emit(
        "ROUTE_COMPLETED_HUMAN_PENDING", outcome="RECORDED", candidate_id=candidate_id,
        audit_id=audit_id, decision_id=decision_id,
        payload={
            "tel_audit_prefix_sha256": prefix_sha,
            "external_human_decision_receipt_required": True,
            "human_decision": "PENDING",
        },
    )
    if tuple(row["event_type"] for row in ledger.rows) != SEALED_ROUTE_ORDER:
        raise ValidationError("TEL_FINAL_ORDER_INTERNAL_MISMATCH")
    full_raw = ledger.to_jsonl_bytes()
    receipt = {
        "schema_id": "uvlm.coherence.totality.tel_finalization_receipt.v1",
        "run_id": run_id, "logical_time": logical_time, "candidate_id": candidate_id,
        "audit_id": audit_id, "decision_id": decision_id,
        "tel_audit_prefix_sha256": prefix_sha,
        "sophia_audit_packet_sha256": sophia_sha,
        "atlas_posture_packet_sha256": atlas_sha,
        "tel_events_sha256": sha256_bytes(full_raw),
        "event_count": len(ledger.rows),
        "human_decision": "PENDING",
        "external_continuation_required": True,
        "effects": {
            "network": False, "provider_invocation": False, "memory_write": False,
            "training": False, "publication": False, "deployment": False, "release": False,
        },
        "authority_effect": "NONE",
    }
    tel_path = run_root / "tel_events.jsonl"
    current = (
        _read_cli_input(tel_path, "tel_events", maximum_bytes=MAX_ROUTE_PACKET_BYTES)
        if tel_path.is_file()
        else prefix_raw
    )
    if current not in {prefix_raw, full_raw}:
        raise ValidationError("TEL_FINALIZATION_EXISTING_CHRONOLOGY_INVALID")
    receipt_path = run_root / "tel_finalization_receipt.json"
    expected_receipt = canonical_json_bytes(receipt)
    if receipt_path.exists():
        if _read_cli_input(
            receipt_path, "tel_finalization_receipt", maximum_bytes=MAX_ROUTE_PACKET_BYTES
        ) != expected_receipt:
            raise ValidationError("TEL_FINALIZATION_RECEIPT_CONFLICT")
    if current != full_raw or not receipt_path.exists():
        tel_temporary = tel_path.with_name(".tel_events.jsonl.finalize.tmp")
        receipt_temporary = receipt_path.with_name(".tel_finalization_receipt.json.tmp")
        rollback_temporary = tel_path.with_name(".tel_events.jsonl.rollback.tmp")
        if any(path.exists() or path.is_symlink() for path in (tel_temporary, receipt_temporary, rollback_temporary)):
            raise OperationalError("TEL_FINALIZATION_TEMPORARY_PATH_CONFLICT")
        tel_replaced = False
        try:
            if current != full_raw:
                with tel_temporary.open("xb") as stream:
                    stream.write(full_raw)
            if not receipt_path.exists():
                with receipt_temporary.open("xb") as stream:
                    stream.write(expected_receipt)
            if current != full_raw:
                os.replace(tel_temporary, tel_path)
                tel_replaced = True
            if not receipt_path.exists():
                try:
                    os.replace(receipt_temporary, receipt_path)
                except OSError:
                    if tel_replaced:
                        with rollback_temporary.open("xb") as stream:
                            stream.write(prefix_raw)
                        os.replace(rollback_temporary, tel_path)
                    raise
        finally:
            for path in (tel_temporary, receipt_temporary, rollback_temporary):
                if path.exists() and path.is_file() and not path.is_symlink():
                    path.unlink()
    return receipt


def verify_core_manifest(root: Path) -> dict[str, Any]:
    return verify_core_manifest_contract(root)


def replay_core(run_root: Path) -> dict[str, Any]:
    if (
        not run_root.is_absolute()
        or _link_like(run_root)
        or not run_root.is_dir()
        or run_root == Path(run_root.anchor)
    ):
        raise OperationalError("REPLAY_ROOT_UNSAFE")
    run_root = run_root.resolve(strict=True)
    if (run_root / "failure_receipt.json").is_file():
        failure = verify_failure_output(run_root)
        return {
            "schema_id": "uvlm.coherence.totality.failure_replay_receipt.v1",
            "run_id": failure["run_id"],
            "logical_time": failure["logical_time"],
            "valid": True,
            "failure_preserved": True,
            "stage": failure["stage"],
            "reason_code": failure["reason_code"],
            "failure_receipt_sha256": sha256_file(run_root / "failure_receipt.json"),
            "tel_events_sha256": sha256_file(run_root / "tel_events.jsonl"),
            "successful_run_claimed": False,
            "authority_effect": "NONE",
        }
    if (run_root / "checksums.sha256").exists():
        verify_sealed_run(run_root)
    original_manifest = verify_core_manifest(run_root)
    request_bytes = _read_cli_input(
        run_root / "request.json", "request", maximum_bytes=MAX_REQUEST_BYTES
    )
    source_bytes = _read_cli_input(
        run_root / "grounding/source.bin", "source", maximum_bytes=MAX_SOURCE_BYTES
    )
    captured_bytes = _read_cli_input(
        run_root / "sonya/raw_output.quarantine",
        "captured",
        maximum_bytes=MAX_RAW_OUTPUT_BYTES,
    )
    aha_case = _object(
        _read_cli_input(
            run_root / "aha_result.json", "aha_result", maximum_bytes=MAX_AHA_CASE_BYTES
        ),
        "aha_result.json",
    ).get("case")
    consent_path = run_root / "pmr_consent.json"
    consent = (
        _object(
            _read_cli_input(
                consent_path, "pmr_consent", maximum_bytes=MAX_PMR_CONSENT_BYTES
            ),
            "pmr_consent.json",
        )
        if consent_path.is_file()
        else None
    )
    projector = _object(
        _read_cli_input(
            run_root / "projector_receipt.json",
            "projector_receipt",
            maximum_bytes=MAX_ROUTE_PACKET_BYTES,
        ),
        "projector_receipt.json",
    )
    temp_parent = Path(tempfile.mkdtemp(prefix="totality-replay-"))
    replay_dir = temp_parent / "replay"
    try:
        build_core_from_inputs(
            request_bytes=request_bytes, source_bytes=source_bytes, captured_bytes=captured_bytes,
            output_dir=replay_dir, aha_case=aha_case, pmr_consent=consent,
            top_k=projector["presentation"]["top_k"],
        )
        replay_manifest = verify_core_manifest(replay_dir)
        original_bytes = canonical_json_bytes(original_manifest)
        replay_bytes = canonical_json_bytes(replay_manifest)
        equal = original_bytes == replay_bytes
        differences: list[str] = []
        original_rows = {row["path"]: row for row in original_manifest["artifacts"]}
        replay_rows = {row["path"]: row for row in replay_manifest["artifacts"]}
        for name in sorted(set(original_rows) | set(replay_rows)):
            if original_rows.get(name) != replay_rows.get(name):
                differences.append(name)
        return {
            "schema_id": "uvlm.coherence.totality.exact_replay_receipt.v1",
            "run_id": original_manifest["run_id"], "logical_time": original_manifest["logical_time"],
            "valid": equal and not differences, "exact_core_manifest_equality": equal,
            "original_core_manifest_sha256": sha256_bytes(original_bytes),
            "replay_core_manifest_sha256": sha256_bytes(replay_bytes),
            "files_compared": len(original_rows), "differences": differences,
            "network_used": False, "provider_invoked": False, "memory_written": False,
            "training_used": False, "authority_effect": "NONE",
        }
    finally:
        shutil.rmtree(temp_parent)


def repository_identity(repo_root: Path, *, allow_dirty: bool = False) -> dict[str, Any]:
    if not repo_root.is_absolute() or not repo_root.is_dir() or _link_like(repo_root):
        raise OperationalError("REPOSITORY_ROOT_UNSAFE")

    def git_object(spec: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", spec],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        value = completed.stdout.strip()
        if completed.returncode != 0 or len(value) not in {40, 64}:
            raise OperationalError(f"REPOSITORY_IDENTITY_UNAVAILABLE:{spec}")
        return value

    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        check=False, capture_output=True,
    )
    if status.returncode != 0:
        raise OperationalError("REPOSITORY_STATUS_UNAVAILABLE")
    clean = not status.stdout
    if not clean and not allow_dirty:
        raise OperationalError("REPOSITORY_WORKTREE_DIRTY")
    return {
        "repository": "TriadicGate",
        "commit": git_object("HEAD^{commit}"),
        "tree": git_object("HEAD^{tree}"),
        "prefix_trees": {
            "coherence_lattice": git_object("HEAD:components/CoherenceLattice"),
            "sophia": git_object("HEAD:components/Sophia"),
            "uvlm_publications": git_object("HEAD:components/uvlm-publications"),
        },
        "worktree_clean": clean,
        "status_sha256": sha256_bytes(status.stdout),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m coherence.totality.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    grounding = sub.add_parser("grounding-manifest")
    grounding.add_argument("--source", type=Path, required=True)
    build = sub.add_parser("build-core")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--task", type=Path, required=True)
    build.add_argument("--captured", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--aha-case", type=Path)
    build.add_argument("--pmr-consent", type=Path)
    build.add_argument("--top-k", type=int, default=8)
    replay = sub.add_parser("replay")
    replay.add_argument("--run-root", type=Path, required=True)
    replay.add_argument("--receipt", type=Path)
    finalize = sub.add_parser("finalize-route-tel")
    finalize.add_argument("--run-root", type=Path, required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--run-root", type=Path, required=True)
    seal.add_argument("--repo-root", type=Path, required=True)
    seal.add_argument("--zip", type=Path)
    seal.add_argument("--allow-dirty", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--run-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "grounding-manifest":
            result = build_grounding_bundle(
                _read_cli_input(
                    args.source, "source", maximum_bytes=MAX_SOURCE_BYTES
                )
            )["manifest"]
        elif args.command == "build-core":
            result = build_core_from_paths(
                request_path=args.task,
                source_path=args.source,
                captured_path=args.captured,
                output_dir=args.out,
                aha_case_path=args.aha_case,
                pmr_consent_path=args.pmr_consent,
                top_k=args.top_k,
            )
        elif args.command == "replay":
            receipt_path = (
                _external_receipt_path(args.receipt, args.run_root)
                if args.receipt
                else None
            )
            result = replay_core(args.run_root)
            if receipt_path is not None:
                write_canonical_json(receipt_path, result, exclusive=True)
        elif args.command == "finalize-route-tel":
            result = finalize_route_tel(args.run_root)
        elif args.command == "seal":
            result = seal_run(args.run_root, repository_identity=repository_identity(args.repo_root, allow_dirty=args.allow_dirty))
            if args.zip:
                result = {**result, "zip": build_deterministic_zip(args.run_root, args.zip)}
        else:
            result = (
                verify_failure_output(args.run_root)
                if (args.run_root / "failure_receipt.json").is_file()
                else verify_sealed_run(args.run_root)
            )
        sys.stdout.buffer.write(canonical_json_bytes(result))
        sys.stdout.buffer.flush()
        return 0
    except (OSError, TotalityError) as exc:
        error = {"valid": False, "error": type(exc).__name__, "reason": str(exc)}
        sys.stderr.buffer.write(canonical_json_bytes(error))
        sys.stderr.buffer.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
