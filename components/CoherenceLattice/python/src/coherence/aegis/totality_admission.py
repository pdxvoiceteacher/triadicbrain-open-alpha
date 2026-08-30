"""Actual-input AEGIS admission gate for the private totality route."""

from __future__ import annotations

import re
from typing import Any, Mapping

from coherence.totality.canonical import (
    require_exact_keys,
    require_identifier,
    require_sha256,
    sha256_json,
    validate_unicode_text,
)
from coherence.totality.errors import ValidationError
from coherence.totality.grounding import validate_grounding_runtime_boundary
from coherence.totality.request import validate_request_envelope

TOTALITY_ADMISSION_SCHEMA = "uvlm.aegis.totality.actual_input_admission.v1"
TOTALITY_INSTRUCTION_QUARANTINE_SCHEMA = (
    "uvlm.aegis.totality.bounded_instruction_quarantine.v1"
)
TOTALITY_INSTRUCTION_QUARANTINE_PROFILE = (
    "AEGIS-BOUNDED-LEXICAL-HIGH-CONFIDENCE-01"
)
_INSTRUCTION_PATTERNS = {
    "disregard_prior_instructions": re.compile(
        r"(?im)^\s*(?:please\s+)?disregard\s+(?:all\s+)?"
        r"(?:prior|previous|above)\s+instructions\b"
    ),
    "follow_instructions_instead": re.compile(
        r"(?im)^\s*(?:please\s+)?follow\s+(?:these|the\s+following)\s+"
        r"instructions\s+instead\b"
    ),
    "ignore_prior_instructions": re.compile(
        r"(?im)^\s*(?:please\s+)?ignore\s+(?:all\s+)?"
        r"(?:prior|previous|above)\s+instructions\b"
    ),
    "system_override_attempt": re.compile(
        r"(?im)^\s*(?:(?:system|developer)\s+"
        r"(?:override|prompt|instruction)\b|you\s+are\s+now\b)"
    ),
}
_BINDING_KEYS = {
    "request_sha256",
    "grounding_manifest_sha256",
    "grounding_bundle_id",
    "bundle_manifest_path",
    "source_id",
    "source_sha256",
    "normalized_sha256",
}
_INSTRUCTION_QUARANTINE_KEYS = {
    "schema_id",
    "profile_id",
    "detector_scope",
    "source_sha256",
    "normalized_sha256",
    "scanned_utf8_bytes",
    "pattern_ids_checked",
    "detected_pattern_ids",
    "status",
    "decision",
    "candidate_route_allowed",
    "instruction_executed",
    "comprehensive_semantic_detection_claimed",
    "authority_effect",
}
_EFFECT_KEYS = {
    "network",
    "provider_invocation",
    "memory_write",
    "pmr_write",
    "atlas_read",
    "atlas_write",
    "prior_influence",
    "training",
    "source_mutation",
    "candidate_authority",
    "truth_certification",
    "canonization",
    "publication",
    "deployment",
    "release",
    "external_action",
}
_PACKET_KEYS = {
    "schema_id",
    "admission_id",
    "status",
    "decision",
    "request_id",
    "run_id",
    "logical_time",
    "binding",
    "binding_sha256",
    "instruction_quarantine",
    "task_consent_verified",
    "active_grounding_reference_count",
    "active_grounding_source_kind",
    "candidate_route_allowed",
    "human_review_required",
    "effects",
    "authority_effect",
}


def _instruction_quarantine(
    grounding_bundle: Mapping[str, Any], binding: Mapping[str, str]
) -> dict[str, Any]:
    normalized_source = grounding_bundle.get("normalized_source")
    if not isinstance(normalized_source, str):
        raise ValidationError("AEGIS_NORMALIZED_SOURCE_REQUIRED")
    detected = sorted(
        pattern_id
        for pattern_id, pattern in _INSTRUCTION_PATTERNS.items()
        if pattern.search(normalized_source)
    )
    if detected:
        raise ValidationError(
            "AEGIS_INSTRUCTION_QUARANTINE_REJECTED:" + ",".join(detected)
        )
    return {
        "schema_id": TOTALITY_INSTRUCTION_QUARANTINE_SCHEMA,
        "profile_id": TOTALITY_INSTRUCTION_QUARANTINE_PROFILE,
        "detector_scope": "NORMALIZED_SOURCE_BOUNDED_LEXICAL_HIGH_CONFIDENCE_V1",
        "source_sha256": binding["source_sha256"],
        "normalized_sha256": binding["normalized_sha256"],
        "scanned_utf8_bytes": len(normalized_source.encode("utf-8")),
        "pattern_ids_checked": sorted(_INSTRUCTION_PATTERNS),
        "detected_pattern_ids": [],
        "status": "CLEAR",
        "decision": "ALLOW",
        "candidate_route_allowed": True,
        "instruction_executed": False,
        "comprehensive_semantic_detection_claimed": False,
        "authority_effect": "NONE",
    }


def _actual_binding(
    request: Mapping[str, Any],
    grounding_bundle: Mapping[str, Any],
    request_sha256: str,
) -> dict[str, str]:
    request = validate_request_envelope(dict(request)).to_dict()
    grounding_bundle = validate_grounding_runtime_boundary(dict(grounding_bundle))
    require_sha256(request_sha256, "$.request_sha256")
    if request_sha256 != sha256_json(dict(request)):
        raise ValidationError("AEGIS_REQUEST_HASH_MISMATCH")
    references = request.get("grounding")
    if (
        not isinstance(references, list)
        or len(references) != 1
        or not isinstance(references[0], dict)
        or references[0].get("source_kind") != "grounding_bundle"
    ):
        raise ValidationError("PRIOR_REINJECTION_DORMANT")
    ref = references[0]
    manifest = grounding_bundle.get("manifest")
    if not isinstance(manifest, dict):
        raise ValidationError("AEGIS_GROUNDING_MANIFEST_REQUIRED")
    source_sha256 = require_sha256(
        manifest.get("source_sha256"), "$.grounding_bundle.manifest.source_sha256"
    )
    normalized_sha256 = require_sha256(
        manifest.get("normalized_sha256"),
        "$.grounding_bundle.manifest.normalized_sha256",
    )
    grounding_bundle_id = require_identifier(
        manifest.get("bundle_id"), "$.grounding_bundle.manifest.bundle_id"
    )
    manifest_sha256 = sha256_json(manifest)
    if ref.get("bundle_manifest_path") != "grounding/manifest.json":
        raise ValidationError("BUILD_GROUNDING_MANIFEST_PATH_MISMATCH")
    expected_source_id = f"SRC-{source_sha256[:20]}"
    if ref.get("source_id") != expected_source_id:
        raise ValidationError("BUILD_GROUNDING_SOURCE_ID_MISMATCH")
    if ref.get("media_type") not in {"text/plain", "text/markdown"}:
        raise ValidationError("BUILD_GROUNDING_MEDIA_TYPE_INVALID")
    if ref.get("bundle_manifest_sha256") != manifest_sha256:
        raise ValidationError("BUILD_REQUEST_GROUNDING_MANIFEST_SHA256_MISMATCH")
    if (
        ref.get("source_sha256") != source_sha256
        or ref.get("normalized_sha256") != normalized_sha256
    ):
        raise ValidationError("BUILD_REQUEST_GROUNDING_IDENTITY_MISMATCH")
    return {
        "request_sha256": request_sha256,
        "grounding_manifest_sha256": manifest_sha256,
        "grounding_bundle_id": grounding_bundle_id,
        "bundle_manifest_path": "grounding/manifest.json",
        "source_id": expected_source_id,
        "source_sha256": source_sha256,
        "normalized_sha256": normalized_sha256,
    }


def validate_totality_admission_packet(
    packet: Any,
    *,
    request: Mapping[str, Any],
    grounding_bundle: Mapping[str, Any],
    request_sha256: str,
) -> dict[str, Any]:
    require_exact_keys(packet, required=_PACKET_KEYS)
    if packet["schema_id"] != TOTALITY_ADMISSION_SCHEMA:
        raise ValidationError("AEGIS_ADMISSION_SCHEMA_MISMATCH")
    for name in ("admission_id", "request_id", "run_id"):
        require_identifier(packet[name], f"$.{name}")
    validate_unicode_text(packet["logical_time"], "$.logical_time", allow_newlines=False)
    if not packet["logical_time"].strip() or len(packet["logical_time"]) > 128:
        raise ValidationError("AEGIS_LOGICAL_TIME_INVALID")
    binding = require_exact_keys(packet["binding"], required=_BINDING_KEYS, path="$.binding")
    for name in (
        "request_sha256",
        "grounding_manifest_sha256",
        "source_sha256",
        "normalized_sha256",
    ):
        require_sha256(binding[name], f"$.binding.{name}")
    require_identifier(binding["grounding_bundle_id"], "$.binding.grounding_bundle_id")
    require_identifier(binding["source_id"], "$.binding.source_id")
    expected_binding = _actual_binding(request, grounding_bundle, request_sha256)
    if dict(binding) != expected_binding:
        raise ValidationError("AEGIS_ACTUAL_INPUT_BINDING_MISMATCH")
    binding_sha256 = require_sha256(packet["binding_sha256"], "$.binding_sha256")
    if binding_sha256 != sha256_json(expected_binding):
        raise ValidationError("AEGIS_BINDING_DIGEST_MISMATCH")
    quarantine = require_exact_keys(
        packet["instruction_quarantine"],
        required=_INSTRUCTION_QUARANTINE_KEYS,
        path="$.instruction_quarantine",
    )
    expected_quarantine = _instruction_quarantine(grounding_bundle, expected_binding)
    if dict(quarantine) != expected_quarantine:
        raise ValidationError("AEGIS_INSTRUCTION_QUARANTINE_BINDING_MISMATCH")
    expected_admission_id = f"AEGIS-{binding_sha256[:24]}"
    if packet["admission_id"] != expected_admission_id:
        raise ValidationError("AEGIS_ADMISSION_ID_DERIVATION_MISMATCH")
    if (
        packet["request_id"] != request["request_id"]
        or packet["run_id"] != request["run_id"]
        or packet["logical_time"] != request["logical_time"]
    ):
        raise ValidationError("AEGIS_REQUEST_CONTEXT_MISMATCH")
    effects = require_exact_keys(packet["effects"], required=_EFFECT_KEYS, path="$.effects")
    if any(value is not False for value in effects.values()):
        raise ValidationError("AEGIS_EFFECT_CEILING_VIOLATION")
    if (
        packet["status"] != "ADMITTED"
        or packet["decision"] != "ADMIT"
        or packet["task_consent_verified"] is not True
        or isinstance(packet["active_grounding_reference_count"], bool)
        or packet["active_grounding_reference_count"] != 1
        or packet["active_grounding_source_kind"] != "grounding_bundle"
        or packet["candidate_route_allowed"] is not True
        or packet["human_review_required"] is not True
        or packet["authority_effect"] != "NONE"
    ):
        raise ValidationError("AEGIS_ADMISSION_POSTURE_INVALID")
    if request.get("task_consent") is not True:
        raise ValidationError("AEGIS_TASK_CONSENT_REQUIRED")
    return {**packet, "binding": dict(binding), "effects": dict(effects)}


def build_totality_admission_packet(
    request: Mapping[str, Any],
    grounding_bundle: Mapping[str, Any],
    *,
    request_sha256: str,
) -> dict[str, Any]:
    if request.get("task_consent") is not True:
        raise ValidationError("AEGIS_TASK_CONSENT_REQUIRED")
    binding = _actual_binding(request, grounding_bundle, request_sha256)
    binding_sha256 = sha256_json(binding)
    instruction_quarantine = _instruction_quarantine(grounding_bundle, binding)
    packet = {
        "schema_id": TOTALITY_ADMISSION_SCHEMA,
        "admission_id": f"AEGIS-{binding_sha256[:24]}",
        "status": "ADMITTED",
        "decision": "ADMIT",
        "request_id": request["request_id"],
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "binding": binding,
        "binding_sha256": binding_sha256,
        "instruction_quarantine": instruction_quarantine,
        "task_consent_verified": True,
        "active_grounding_reference_count": 1,
        "active_grounding_source_kind": "grounding_bundle",
        "candidate_route_allowed": True,
        "human_review_required": True,
        "effects": dict.fromkeys(sorted(_EFFECT_KEYS), False),
        "authority_effect": "NONE",
    }
    return validate_totality_admission_packet(
        packet,
        request=request,
        grounding_bundle=grounding_bundle,
        request_sha256=request_sha256,
    )
