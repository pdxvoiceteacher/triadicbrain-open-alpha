"""Provider-neutral Sonya captured-output adapter and quarantine boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical import (
    require_exact_keys,
    require_identifier,
    require_sha256,
    reject_prohibited_surfaces,
    sha256_bytes,
    sha256_json,
    strict_json_loads,
    validate_unicode_text,
)
from .errors import OperationalError, ValidationError
from .schema_runtime import validate_schema_instance

ADAPTER_SCHEMA = "uvlm.sonya.totality.adapter_contract.v1"
CAPTURE_SCHEMA = "uvlm.sonya.totality.captured_semantic.v1"
QUARANTINE_SCHEMA = "uvlm.sonya.totality.raw_quarantine_receipt.v1"
CANDIDATE_SCHEMA = "uvlm.sonya.totality.candidate_packet.v1"
QUARANTINE_VERIFICATION_SCHEMA = "uvlm.sonya.totality.quarantine_verification_receipt.v1"
MAX_RAW_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_ANSWER_CHARS = 200_000
MAX_CAPTURE_CLAIMS = 1000
MAX_EVIDENCE_REFERENCES_PER_CLAIM = 100
_CLAIM_KEYS = {"claim_id", "text", "answer_start", "answer_end"}
_EVIDENCE_REFERENCE_KEYS = {
    "source_sha256",
    "segment_id",
    "segment_sha256",
    "source_span",
    "exact_excerpt_sha256",
    "claim_text_sha256",
    "candidate_relation",
}
_SOURCE_SPAN_KEYS = {"byte_start", "byte_end", "char_start", "char_end"}
_CANDIDATE_RELATIONS = {"SUPPORTS", "LIMITS", "CONTRADICTS"}
_CANDIDATE_KEYS = {
    "schema_id", "candidate_id", "run_id", "logical_time", "request_sha256", "adapter_id",
    "model_identity", "raw_output_sha256", "answer", "uncertainty", "claims",
    "candidate_not_final_answer", "model_output_not_authority", "not_truth_certification",
    "not_memory_authorization", "not_training_authorization", "not_publication_authorization",
    "not_deployment_authority", "not_release_authorization", "human_review_required",
}

_CONTRACT_KEYS = {
    "schema_id",
    "adapter_id",
    "adapter_kind",
    "local_or_remote",
    "capabilities",
    "input_schema",
    "output_schema",
    "network_policy",
    "raw_output_policy",
    "candidate_packet_policy",
    "failure_receipt_policy",
    "telemetry_policy",
    "provenance_policy",
    "consent_policy",
    "claim_ceiling",
}
_CAPABILITIES = {
    "capture_exact_bytes",
    "cancellation",
    "provider_invocation",
    "memory_write",
    "training",
}
_QUARANTINE_KEYS = {
    "schema_id", "adapter_id", "request_sha256", "raw_output_sha256", "raw_output_bytes",
    "quarantine_member", "raw_output_quarantined", "network_used", "provider_invoked",
    "memory_written", "training_used", "authority_effect",
}


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def captured_adapter_contract(adapter_id: str = "sonya.captured_candidate.reference.v1") -> dict[str, Any]:
    require_identifier(adapter_id, "$.adapter_id")
    return {
        "schema_id": ADAPTER_SCHEMA,
        "adapter_id": adapter_id,
        "adapter_kind": "captured_candidate",
        "local_or_remote": "local",
        "capabilities": {
            "capture_exact_bytes": True,
            "cancellation": False,
            "provider_invocation": False,
            "memory_write": False,
            "training": False,
        },
        "input_schema": "opaque_bytes_or_uvlm.sonya.totality.captured_semantic.v1",
        "output_schema": CANDIDATE_SCHEMA,
        "network_policy": "DENY",
        "raw_output_policy": "QUARANTINE_EXACT_BYTES",
        "candidate_packet_policy": "NONAUTHORITATIVE_ONLY",
        "failure_receipt_policy": "DETERMINISTIC_REQUIRED",
        "telemetry_policy": "LOCAL_DETERMINISTIC_NO_HIDDEN_TELEMETRY",
        "provenance_policy": "EXACT_HASH_AND_BYTE_COUNT_REQUIRED",
        "consent_policy": "EXPLICIT_TASK_CONSENT_REQUIRED",
        "claim_ceiling": "NONAUTHORITATIVE_CANDIDATE_ONLY",
    }


def validate_adapter_contract(value: Any, *, default_route: bool = True) -> dict[str, Any]:
    require_exact_keys(value, required=_CONTRACT_KEYS)
    if value["schema_id"] != ADAPTER_SCHEMA:
        raise ValidationError("ADAPTER_SCHEMA_MISMATCH")
    require_identifier(value["adapter_id"], "$.adapter_id")
    if value["adapter_kind"] != "captured_candidate":
        raise ValidationError("ADAPTER_KIND_NOT_CAPTURED_REFERENCE")
    capabilities = value["capabilities"]
    require_exact_keys(capabilities, required=_CAPABILITIES, path="$.capabilities")
    if any(not isinstance(item, bool) for item in capabilities.values()):
        raise ValidationError("ADAPTER_CAPABILITY_BOOLEAN_REQUIRED")
    if default_route:
        constraints = {
            "local_or_remote": "local",
            "network_policy": "DENY",
            "raw_output_policy": "QUARANTINE_EXACT_BYTES",
            "candidate_packet_policy": "NONAUTHORITATIVE_ONLY",
            "failure_receipt_policy": "DETERMINISTIC_REQUIRED",
            "telemetry_policy": "LOCAL_DETERMINISTIC_NO_HIDDEN_TELEMETRY",
            "provenance_policy": "EXACT_HASH_AND_BYTE_COUNT_REQUIRED",
            "consent_policy": "EXPLICIT_TASK_CONSENT_REQUIRED",
            "claim_ceiling": "NONAUTHORITATIVE_CANDIDATE_ONLY",
            "input_schema": "opaque_bytes_or_uvlm.sonya.totality.captured_semantic.v1",
            "output_schema": CANDIDATE_SCHEMA,
        }
        for field, expected in constraints.items():
            if value[field] != expected:
                raise ValidationError(f"ADAPTER_DEFAULT_POLICY_VIOLATION:{field}")
        if capabilities["provider_invocation"] or capabilities["memory_write"] or capabilities["training"]:
            raise ValidationError("ADAPTER_CAPABILITY_NOT_AUTHORIZED")
        if capabilities["cancellation"]:
            raise ValidationError("ADAPTER_CAPTURED_CANCELLATION_UNSUPPORTED")
        if not capabilities["capture_exact_bytes"]:
            raise ValidationError("ADAPTER_EXACT_CAPTURE_REQUIRED")
    return {**value, "capabilities": dict(capabilities)}


def validate_quarantine_receipt(value: Any) -> dict[str, Any]:
    require_exact_keys(value, required=_QUARANTINE_KEYS)
    if value["schema_id"] != QUARANTINE_SCHEMA:
        raise ValidationError("QUARANTINE_RECEIPT_SCHEMA_MISMATCH")
    require_identifier(value["adapter_id"], "$.adapter_id")
    require_sha256(value["request_sha256"], "$.request_sha256")
    require_sha256(value["raw_output_sha256"], "$.raw_output_sha256")
    if (
        isinstance(value["raw_output_bytes"], bool)
        or not isinstance(value["raw_output_bytes"], int)
        or not 1 <= value["raw_output_bytes"] <= MAX_RAW_OUTPUT_BYTES
    ):
        raise ValidationError("QUARANTINE_BYTE_COUNT_INVALID")
    member = value["quarantine_member"]
    validate_unicode_text(member, "$.quarantine_member", allow_newlines=False)
    if not member or "/" in member or "\\" in member or member in {".", ".."}:
        raise ValidationError("QUARANTINE_MEMBER_INVALID")
    posture = (
        value["raw_output_quarantined"], value["network_used"], value["provider_invoked"],
        value["memory_written"], value["training_used"], value["authority_effect"],
    )
    if posture != (True, False, False, False, False, "NONE"):
        raise ValidationError("QUARANTINE_POSTURE_INVALID")
    return dict(value)


def quarantine_raw_output(
    raw_output: bytes,
    quarantine_path: Path,
    *,
    request_sha256: str,
    contract: Mapping[str, Any] | None = None,
    task_consent: bool,
) -> dict[str, Any]:
    selected = validate_adapter_contract(dict(contract or captured_adapter_contract()))
    require_sha256(request_sha256, "$.request_sha256")
    if task_consent is not True:
        raise ValidationError("ADAPTER_TASK_CONSENT_REQUIRED")
    if not isinstance(raw_output, bytes) or not raw_output:
        raise ValidationError("ADAPTER_RAW_BYTES_REQUIRED")
    if len(raw_output) > MAX_RAW_OUTPUT_BYTES:
        raise ValidationError("ADAPTER_RAW_BYTES_LIMIT_EXCEEDED")
    if quarantine_path.exists() or _link_like(quarantine_path) or _link_like(quarantine_path.parent):
        raise OperationalError("QUARANTINE_OUTPUT_EXISTS_OR_UNSAFE")
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with quarantine_path.open("xb") as stream:
            stream.write(raw_output)
    except OSError as exc:
        raise OperationalError("QUARANTINE_WRITE_FAILED") from exc
    return {
        "schema_id": QUARANTINE_SCHEMA,
        "adapter_id": selected["adapter_id"],
        "request_sha256": request_sha256,
        "raw_output_sha256": sha256_bytes(raw_output),
        "raw_output_bytes": len(raw_output),
        "quarantine_member": quarantine_path.name,
        "raw_output_quarantined": True,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "authority_effect": "NONE",
    }


def _validate_evidence_references(
    value: Any,
    *,
    claim_text: str,
    path: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_EVIDENCE_REFERENCES_PER_CLAIM:
        raise ValidationError(f"CAPTURE_EVIDENCE_REFERENCE_COUNT_INVALID:{path}")
    expected_claim_sha = sha256_bytes(claim_text.encode("utf-8"))
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, reference in enumerate(value):
        reference_path = f"{path}[{index}]"
        require_exact_keys(
            reference,
            required=_EVIDENCE_REFERENCE_KEYS,
            path=reference_path,
        )
        source_sha = require_sha256(
            reference["source_sha256"], f"{reference_path}.source_sha256"
        )
        segment_id = require_identifier(
            reference["segment_id"], f"{reference_path}.segment_id"
        )
        segment_sha = require_sha256(
            reference["segment_sha256"], f"{reference_path}.segment_sha256"
        )
        excerpt_sha = require_sha256(
            reference["exact_excerpt_sha256"],
            f"{reference_path}.exact_excerpt_sha256",
        )
        claim_sha = require_sha256(
            reference["claim_text_sha256"], f"{reference_path}.claim_text_sha256"
        )
        if claim_sha != expected_claim_sha:
            raise ValidationError(
                f"CAPTURE_EVIDENCE_CLAIM_TEXT_BINDING_MISMATCH:{reference_path}"
            )
        relation = reference["candidate_relation"]
        if relation not in _CANDIDATE_RELATIONS:
            raise ValidationError(
                f"CAPTURE_EVIDENCE_RELATION_INVALID:{reference_path}"
            )
        span = require_exact_keys(
            reference["source_span"],
            required=_SOURCE_SPAN_KEYS,
            path=f"{reference_path}.source_span",
        )
        if any(
            isinstance(span[name], bool)
            or not isinstance(span[name], int)
            or span[name] < 0
            for name in _SOURCE_SPAN_KEYS
        ):
            raise ValidationError(f"CAPTURE_EVIDENCE_SPAN_INVALID:{reference_path}")
        if not (
            span["char_start"] < span["char_end"]
            and span["byte_start"] < span["byte_end"]
        ):
            raise ValidationError(f"CAPTURE_EVIDENCE_SPAN_INVALID:{reference_path}")
        identity = (
            source_sha,
            segment_id,
            segment_sha,
            span["byte_start"],
            span["byte_end"],
            span["char_start"],
            span["char_end"],
            excerpt_sha,
            claim_sha,
            relation,
        )
        if identity in seen:
            raise ValidationError(f"CAPTURE_EVIDENCE_REFERENCE_DUPLICATE:{reference_path}")
        seen.add(identity)
        normalized.append(
            {
                "source_sha256": source_sha,
                "segment_id": segment_id,
                "segment_sha256": segment_sha,
                "source_span": {
                    "byte_start": span["byte_start"],
                    "byte_end": span["byte_end"],
                    "char_start": span["char_start"],
                    "char_end": span["char_end"],
                },
                "exact_excerpt_sha256": excerpt_sha,
                "claim_text_sha256": claim_sha,
                "candidate_relation": relation,
            }
        )
    return normalized


def _validate_capture(
    value: Any,
    *,
    require_evidence_field: bool = False,
) -> dict[str, Any]:
    reject_prohibited_surfaces(value)
    require_exact_keys(
        value,
        required={"schema_id", "answer", "uncertainty", "claims"},
    )
    if value["schema_id"] != CAPTURE_SCHEMA:
        raise ValidationError("CAPTURE_SCHEMA_MISMATCH")
    answer = value["answer"]
    validate_unicode_text(answer, "$.answer")
    if not answer.strip() or len(answer) > MAX_ANSWER_CHARS:
        raise ValidationError("CAPTURE_ANSWER_LENGTH_INVALID")
    uncertainty = value["uncertainty"]
    if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)) or not 0 <= float(uncertainty) <= 1:
        raise ValidationError("CAPTURE_UNCERTAINTY_INVALID")
    claims = value["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CAPTURE_CLAIMS:
        raise ValidationError("CAPTURE_CLAIMS_COUNT_INVALID")
    normalized_claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        required_claim_keys = set(_CLAIM_KEYS)
        optional_claim_keys = {"candidate_evidence_references"}
        if require_evidence_field:
            required_claim_keys.add("candidate_evidence_references")
            optional_claim_keys.clear()
        require_exact_keys(
            claim,
            required=required_claim_keys,
            optional=optional_claim_keys,
            path=f"$.claims[{index}]",
        )
        claim_id = require_identifier(claim["claim_id"], f"$.claims[{index}].claim_id")
        if claim_id in seen:
            raise ValidationError(f"CAPTURE_CLAIM_ID_DUPLICATE:{claim_id}")
        seen.add(claim_id)
        start, end = claim["answer_start"], claim["answer_end"]
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (start, end)):
            raise ValidationError(f"CAPTURE_CLAIM_SPAN_INVALID:{claim_id}")
        text = claim["text"]
        validate_unicode_text(text, f"$.claims[{index}].text")
        if start < 0 or start >= end or answer[start:end] != text:
            raise ValidationError(f"CAPTURE_CLAIM_EXACT_SPAN_MISMATCH:{claim_id}")
        references = _validate_evidence_references(
            claim.get("candidate_evidence_references", []),
            claim_text=text,
            path=f"$.claims[{index}].candidate_evidence_references",
        )
        normalized_claims.append(
            {
                "claim_id": claim_id,
                "text": text,
                "answer_start": start,
                "answer_end": end,
                "candidate_evidence_references": references,
            }
        )
    return {
        "schema_id": CAPTURE_SCHEMA,
        "answer": answer,
        "uncertainty": float(uncertainty),
        "claims": normalized_claims,
    }


def read_quarantined_capture(
    quarantine_path: Path,
    receipt: Any,
    *,
    expected_request_sha256: str,
) -> dict[str, Any]:
    receipt = validate_quarantine_receipt(receipt)
    require_sha256(expected_request_sha256, "$.expected_request_sha256")
    if receipt["request_sha256"] != expected_request_sha256:
        raise ValidationError("QUARANTINE_REQUEST_BINDING_MISMATCH")
    if (
        receipt["quarantine_member"] != quarantine_path.name
        or _link_like(quarantine_path)
        or _link_like(quarantine_path.parent)
        or not quarantine_path.is_file()
    ):
        raise ValidationError("QUARANTINE_PATH_BINDING_INVALID")
    try:
        with quarantine_path.open("rb") as stream:
            raw = stream.read(MAX_RAW_OUTPUT_BYTES + 1)
    except OSError as exc:
        raise OperationalError("QUARANTINE_READ_FAILED") from exc
    if len(raw) > MAX_RAW_OUTPUT_BYTES:
        raise ValidationError("QUARANTINE_RAW_BYTES_LIMIT_EXCEEDED")
    if len(raw) != receipt["raw_output_bytes"] or sha256_bytes(raw) != receipt["raw_output_sha256"]:
        raise ValidationError("QUARANTINE_RAW_IDENTITY_MISMATCH")
    return _validate_capture(strict_json_loads(raw))


def build_candidate_packet(
    capture: Any,
    receipt: Mapping[str, Any],
    *,
    request_sha256: str,
    run_id: str,
    logical_time: str,
    model_identity: str = "captured-no-provider",
) -> dict[str, Any]:
    normalized = _validate_capture(capture)
    receipt = validate_quarantine_receipt(receipt)
    require_sha256(request_sha256, "$.request_sha256")
    if receipt.get("request_sha256") != request_sha256:
        raise ValidationError("CANDIDATE_REQUEST_BINDING_MISMATCH")
    run_id = require_identifier(run_id, "$.run_id")
    validate_unicode_text(logical_time, "$.logical_time", allow_newlines=False)
    if not logical_time.strip() or len(logical_time) > 128:
        raise ValidationError("CANDIDATE_LOGICAL_TIME_INVALID")
    validate_unicode_text(model_identity, "$.model_identity", allow_newlines=False)
    if not model_identity.strip() or len(model_identity) > 256:
        raise ValidationError("MODEL_IDENTITY_INVALID")
    candidate_seed = (request_sha256 + receipt["raw_output_sha256"]).encode("ascii")
    return validate_candidate_runtime_boundary({
        "schema_id": CANDIDATE_SCHEMA,
        "candidate_id": "CAND-" + sha256_bytes(candidate_seed)[:24],
        "run_id": run_id,
        "logical_time": logical_time,
        "request_sha256": request_sha256,
        "adapter_id": receipt["adapter_id"],
        "model_identity": model_identity,
        "raw_output_sha256": receipt["raw_output_sha256"],
        "answer": normalized["answer"],
        "uncertainty": normalized["uncertainty"],
        "claims": normalized["claims"],
        "candidate_not_final_answer": True,
        "model_output_not_authority": True,
        "not_truth_certification": True,
        "not_memory_authorization": True,
        "not_training_authorization": True,
        "not_publication_authorization": True,
        "not_deployment_authority": True,
        "not_release_authorization": True,
        "human_review_required": True,
    })


def validate_candidate_packet(value: Any) -> dict[str, Any]:
    require_exact_keys(value, required=_CANDIDATE_KEYS)
    reject_prohibited_surfaces(value)
    if value["schema_id"] != CANDIDATE_SCHEMA:
        raise ValidationError("CANDIDATE_SCHEMA_MISMATCH")
    candidate_id = require_identifier(value["candidate_id"], "$.candidate_id")
    require_identifier(value["run_id"], "$.run_id")
    validate_unicode_text(value["logical_time"], "$.logical_time", allow_newlines=False)
    if not value["logical_time"].strip() or len(value["logical_time"]) > 128:
        raise ValidationError("CANDIDATE_LOGICAL_TIME_INVALID")
    request_sha = require_sha256(value["request_sha256"], "$.request_sha256")
    raw_sha = require_sha256(value["raw_output_sha256"], "$.raw_output_sha256")
    require_identifier(value["adapter_id"], "$.adapter_id")
    validate_unicode_text(value["model_identity"], "$.model_identity", allow_newlines=False)
    if not value["model_identity"].strip() or len(value["model_identity"]) > 256:
        raise ValidationError("MODEL_IDENTITY_INVALID")
    capture = _validate_capture({
        "schema_id": CAPTURE_SCHEMA,
        "answer": value["answer"],
        "uncertainty": value["uncertainty"],
        "claims": value["claims"],
    }, require_evidence_field=True)
    expected_id = "CAND-" + sha256_bytes((request_sha + raw_sha).encode("ascii"))[:24]
    if candidate_id != expected_id:
        raise ValidationError("CANDIDATE_ID_DERIVATION_MISMATCH")
    posture_fields = _CANDIDATE_KEYS - {
        "schema_id", "candidate_id", "run_id", "logical_time", "request_sha256", "adapter_id",
        "model_identity", "raw_output_sha256", "answer", "uncertainty", "claims",
    }
    if any(value[name] is not True for name in posture_fields):
        raise ValidationError("CANDIDATE_NONAUTHORITY_POSTURE_INVALID")
    return {**value, "uncertainty": capture["uncertainty"], "claims": capture["claims"]}


def validate_candidate_runtime_boundary(value: Any) -> dict[str, Any]:
    validate_schema_instance(CANDIDATE_SCHEMA, value)
    return validate_candidate_packet(value)


def build_quarantine_verification_receipt(
    quarantine_path: Path,
    quarantine_receipt: Any,
    candidate: Any,
    *,
    request_sha256: str,
    run_id: str,
    logical_time: str,
) -> dict[str, Any]:
    """Re-read quarantine and emit a raw-free proof for downstream auditors."""

    receipt = validate_quarantine_receipt(quarantine_receipt)
    capture = read_quarantined_capture(
        quarantine_path,
        receipt,
        expected_request_sha256=request_sha256,
    )
    normalized_candidate = validate_candidate_packet(candidate)
    if (
        normalized_candidate["request_sha256"] != request_sha256
        or normalized_candidate["run_id"] != run_id
        or normalized_candidate["logical_time"] != logical_time
        or normalized_candidate["adapter_id"] != receipt["adapter_id"]
        or normalized_candidate["raw_output_sha256"] != receipt["raw_output_sha256"]
        or normalized_candidate["answer"] != capture["answer"]
        or normalized_candidate["uncertainty"] != capture["uncertainty"]
        or normalized_candidate["claims"] != capture["claims"]
    ):
        raise ValidationError("QUARANTINE_CANDIDATE_BINDING_MISMATCH")
    return {
        "schema_id": QUARANTINE_VERIFICATION_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "logical_time": logical_time,
        "request_sha256": require_sha256(request_sha256, "$.request_sha256"),
        "adapter_id": receipt["adapter_id"],
        "quarantine_member": receipt["quarantine_member"],
        "raw_output_sha256": receipt["raw_output_sha256"],
        "raw_output_bytes": receipt["raw_output_bytes"],
        "quarantine_receipt_sha256": sha256_json(receipt),
        "candidate_id": normalized_candidate["candidate_id"],
        "candidate_sha256": sha256_json(normalized_candidate),
        "verification": {
            "path_binding_valid": True,
            "exact_byte_count_valid": True,
            "exact_sha256_valid": True,
            "strict_utf8_json_valid": True,
            "semantic_capture_schema_valid": True,
            "candidate_binding_valid": True,
        },
        "raw_output_disclosed": False,
        "effects": {
            "network": False,
            "provider_invocation": False,
            "memory_write": False,
            "training": False,
            "publication": False,
            "deployment": False,
            "release": False,
        },
        "authority_effect": "NONE",
    }


@dataclass(frozen=True)
class CapturedAdapter:
    """Synchronous captured-byte facade, distinct from live ProviderAdapter.

    It truthfully declares ``cancellation=False`` because it performs no model
    invocation or streaming operation to cancel.  The existing live-provider
    protocol remains the compatibility owner for cancellable generation.
    """

    contract: Mapping[str, Any]

    @classmethod
    def reference(cls) -> "CapturedAdapter":
        return cls(captured_adapter_contract())

    def quarantine(
        self,
        raw_output: bytes,
        path: Path,
        *,
        request_sha256: str,
        task_consent: bool,
    ) -> dict[str, Any]:
        return quarantine_raw_output(
            raw_output,
            path,
            request_sha256=request_sha256,
            contract=self.contract,
            task_consent=task_consent,
        )
