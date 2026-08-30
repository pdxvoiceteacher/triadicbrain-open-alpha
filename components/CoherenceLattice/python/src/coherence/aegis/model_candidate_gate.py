from __future__ import annotations

from typing import Any

from coherence.aegis.policy import (
    AEGIS_MODEL_CANDIDATE_GATE_PHASE,
    MODEL_CANDIDATE_GATE_FAILURE_RECEIPT_NAME,
    MODEL_CANDIDATE_GATE_FALSE_FLAGS,
    MODEL_CANDIDATE_GATE_NON_AUTHORITY_BOUNDARY,
)

ALLOWED_PURPOSES = {"configured_ai_work", "evidence_support_report_generation"}
COMPATIBLE_ADMISSION = {"admit", "admit_with_controls"}
COMPATIBLE_DECISIONS = {"allow", "allow_with_controls"}
COMPATIBLE_GROUNDING = {"bound", "bound_with_controls"}
COMPATIBLE_QUARANTINE = {"clear", "clear_with_notice"}
GATE_STATUSES = {
    "candidate_allowed",
    "candidate_allowed_with_controls",
    "hold_for_human_review",
    "reject_fail_closed",
    "alarm_requires_elevated_review",
}


def _missing(packet: dict | None) -> bool:
    return not isinstance(packet, dict) or not packet


def _ref(packet: dict | None, *keys: str, fallback: str) -> str:
    if not isinstance(packet, dict):
        return "MISSING_PACKET"
    for key in keys:
        value = packet.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _base_packet(
    *,
    admission_packet: dict | None,
    source_scope_packet: dict | None,
    consent_packet: dict | None,
    grounding_packet: dict | None,
    instruction_quarantine_packet: dict | None,
    candidate_request_ref: str,
    candidate_purpose: str,
    scenario_id: str,
) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_model_candidate_gate_packet.v1",
        "source_phase": AEGIS_MODEL_CANDIDATE_GATE_PHASE,
        "model_candidate_gate_status": "reject_fail_closed",
        "scenario_id": scenario_id,
        "candidate_request_ref": candidate_request_ref,
        "candidate_purpose": candidate_purpose,
        "admission_ref": _ref(admission_packet, "admission_id", fallback="aegis_admission_packet.json"),
        "source_scope_ref": _ref(source_scope_packet, "source_scope_ref", fallback="aegis_source_scope_packet.json"),
        "consent_ref": _ref(consent_packet, "consent_profile_id", fallback="aegis_consent_packet.json"),
        "grounding_ref": _ref(grounding_packet, "grounding_ref", fallback="aegis_grounding_binding_packet.json"),
        "instruction_quarantine_ref": _ref(instruction_quarantine_packet, "quarantine_ref", fallback="aegis_instruction_quarantine_packet.json"),
        "upstream_compatibility_status": "not_evaluated",
        "reason_codes": [],
        "controls_required": [],
        "human_review_required": False,
        "model_candidate_allowed": False,
        "model_candidate_failure_receipt_ref": MODEL_CANDIDATE_GATE_FAILURE_RECEIPT_NAME,
        "downstream_report_generation_allowed": False,
        "downstream_evidence_map_use_allowed": False,
        "downstream_control_package_use_allowed": False,
        **MODEL_CANDIDATE_GATE_FALSE_FLAGS,
        "non_authority_boundary": MODEL_CANDIDATE_GATE_NON_AUTHORITY_BOUNDARY,
    }


def _finish(
    packet: dict[str, Any],
    *,
    status: str,
    decision: str,
    reason_codes: list[str],
    controls: list[str] | None = None,
) -> dict[str, Any]:
    allowed = status in {"candidate_allowed", "candidate_allowed_with_controls"}
    packet["model_candidate_gate_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = status in {"candidate_allowed_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["model_candidate_allowed"] = allowed
    packet["model_candidate_failure_receipt_ref"] = None if allowed else MODEL_CANDIDATE_GATE_FAILURE_RECEIPT_NAME
    packet["downstream_report_generation_allowed"] = allowed
    packet["downstream_evidence_map_use_allowed"] = allowed
    packet["downstream_control_package_use_allowed"] = allowed
    packet["upstream_compatibility_status"] = "compatible" if allowed else "blocked"
    return packet


def build_model_candidate_gate_failure_receipt(*, packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_model_candidate_gate_failure_receipt.v1",
        "source_phase": AEGIS_MODEL_CANDIDATE_GATE_PHASE,
        "model_candidate_failure_receipt_status": "completed",
        "scenario_id": packet["scenario_id"],
        "candidate_request_ref": packet["candidate_request_ref"],
        "candidate_purpose": packet["candidate_purpose"],
        "decision": packet["decision"],
        "reason_codes": list(packet["reason_codes"]),
        "no_model_candidate_created": True,
        "no_provider_call": True,
        "no_network_call": True,
        "no_model_output_generated": True,
        "no_downstream_report_generation": True,
        "no_downstream_evidence_map_use": True,
        "no_downstream_control_package_use": True,
        "no_memory_write": True,
        "no_atlas_admission": True,
        "no_trace_export": True,
        "no_pmr_federation": True,
        "no_final_answer_authority": True,
        "no_accepted_evidence_authority": True,
        "human_review_required": True,
    }


def evaluate_model_candidate_gate(
    *,
    admission_packet: dict,
    source_scope_packet: dict,
    consent_packet: dict,
    grounding_packet: dict,
    instruction_quarantine_packet: dict,
    candidate_request_ref: str,
    candidate_purpose: str = "configured_ai_work",
    scenario_id: str = "valid_model_candidate_gate",
) -> dict:
    packet = _base_packet(
        admission_packet=admission_packet,
        source_scope_packet=source_scope_packet,
        consent_packet=consent_packet,
        grounding_packet=grounding_packet,
        instruction_quarantine_packet=instruction_quarantine_packet,
        candidate_request_ref=candidate_request_ref,
        candidate_purpose=candidate_purpose,
        scenario_id=scenario_id,
    )

    missing_checks = [
        ("missing_admission_packet", admission_packet),
        ("missing_source_scope_packet", source_scope_packet),
        ("missing_consent_packet", consent_packet),
        ("missing_grounding_packet", grounding_packet),
        ("missing_instruction_quarantine_packet", instruction_quarantine_packet),
    ]
    for reason, upstream in missing_checks:
        if _missing(upstream) or scenario_id == f"{reason}_reject":
            return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=[reason, "fail_closed_no_model_candidate"])

    if candidate_purpose not in ALLOWED_PURPOSES or scenario_id == "unsupported_candidate_purpose_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["unsupported_candidate_purpose", "fail_closed_no_model_candidate"])
    if scenario_id == "candidate_requires_human_review_hold" or any(
        upstream.get("human_review_required") is True
        for upstream in [admission_packet, source_scope_packet, consent_packet, grounding_packet, instruction_quarantine_packet]
        if upstream.get("decision") not in {"allow", "allow_with_controls", "admit", "admit_with_controls"}
    ):
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["candidate_requires_human_review", "no_model_candidate_created"], controls=["human_candidate_review"])
    if admission_packet.get("decision") not in COMPATIBLE_ADMISSION or scenario_id == "admission_not_admitted_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["admission_not_admitted", "fail_closed_no_model_candidate"])
    if source_scope_packet.get("decision") not in COMPATIBLE_DECISIONS or scenario_id == "source_scope_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["source_scope_not_allowed", "fail_closed_no_model_candidate"])
    if consent_packet.get("decision") not in COMPATIBLE_DECISIONS or scenario_id == "consent_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["consent_not_allowed", "fail_closed_no_model_candidate"])
    if grounding_packet.get("grounding_status") == "alarm_requires_elevated_review" or scenario_id == "grounding_alarm_blocks_candidate":
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["grounding_alarm_blocks_candidate", "no_model_candidate_created"])
    if grounding_packet.get("grounding_status") not in COMPATIBLE_GROUNDING or scenario_id == "grounding_not_bound_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["grounding_not_bound", "fail_closed_no_model_candidate"])
    if instruction_quarantine_packet.get("quarantine_status") == "alarm_requires_elevated_review" or scenario_id == "instruction_quarantine_alarm_blocks_candidate":
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["instruction_quarantine_alarm_blocks_candidate", "no_model_candidate_created"])
    if instruction_quarantine_packet.get("quarantine_status") not in COMPATIBLE_QUARANTINE or scenario_id == "instruction_quarantine_blocks_candidate":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["instruction_quarantine_blocks_candidate", "fail_closed_no_model_candidate"])
    if grounding_packet.get("downstream_model_use_allowed") is not True or instruction_quarantine_packet.get("downstream_model_use_allowed") is not True or scenario_id == "downstream_use_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["downstream_use_not_allowed", "fail_closed_no_model_candidate"])

    controls_required = (
        admission_packet.get("decision") == "admit_with_controls"
        or source_scope_packet.get("decision") == "allow_with_controls"
        or consent_packet.get("decision") == "allow_with_controls"
        or grounding_packet.get("grounding_status") == "bound_with_controls"
        or instruction_quarantine_packet.get("quarantine_status") == "clear_with_notice"
        or scenario_id == "valid_model_candidate_with_controls"
    )
    if controls_required:
        return _finish(packet, status="candidate_allowed_with_controls", decision="allow_with_controls", reason_codes=["compatible_upstream_with_controls", "model_candidate_gate_allowed"], controls=["preserve_controls", "human_review_available"])
    return _finish(packet, status="candidate_allowed", decision="allow", reason_codes=["compatible_upstream", "model_candidate_gate_allowed"])
