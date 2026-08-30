from __future__ import annotations

from typing import Any

from coherence.aegis.policy import (
    AEGIS_GROUNDING_BINDING_PHASE,
    GROUNDING_BINDING_FALSE_FLAGS,
    GROUNDING_BINDING_NON_AUTHORITY_BOUNDARY,
    GROUNDING_FAILURE_RECEIPT_NAME,
)

COMPATIBLE_ADMISSION_DECISIONS = {"admit", "admit_with_controls"}
COMPATIBLE_SCOPE_DECISIONS = {"allow", "allow_with_controls"}
COMPATIBLE_CONSENT_DECISIONS = {"allow", "allow_with_controls"}
GROUNDING_STATUSES = {
    "bound",
    "bound_with_controls",
    "hold_for_human_review",
    "reject_fail_closed",
    "alarm_requires_elevated_review",
}


def _compatible(admission_packet: dict[str, Any], source_scope_packet: dict[str, Any], consent_packet: dict[str, Any]) -> bool:
    return (
        admission_packet.get("decision") in COMPATIBLE_ADMISSION_DECISIONS
        and source_scope_packet.get("decision") in COMPATIBLE_SCOPE_DECISIONS
        and consent_packet.get("decision") in COMPATIBLE_CONSENT_DECISIONS
    )


def _failure_receipt(*, scenario_id: str, decision: str, reason_codes: list[str]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_grounding_failure_receipt.v1",
        "source_phase": AEGIS_GROUNDING_BINDING_PHASE,
        "grounding_failure_receipt_status": "completed",
        "scenario_id": scenario_id,
        "decision": decision,
        "reason_codes": reason_codes,
        "no_request_envelope_created": True,
        "downstream_model_use_allowed": False,
        "report_generation_allowed": False,
        "evidence_map_use_allowed": False,
        "control_package_use_allowed": False,
        "no_provider_call": True,
        "no_network_call": True,
        "no_memory_write": True,
        "no_atlas_admission": True,
        "no_trace_export": True,
        "no_pmr_federation": True,
        "no_final_answer_authority": True,
        "no_accepted_evidence_authority": True,
        "human_review_required": True,
    }


def build_grounding_failure_receipt(*, scenario_id: str, decision: str, reason_codes: list[str]) -> dict[str, Any]:
    """Build a no-downstream-processing grounding failure receipt."""

    return _failure_receipt(scenario_id=scenario_id, decision=decision, reason_codes=reason_codes)


def _finish(
    packet: dict[str, Any],
    *,
    status: str,
    decision: str,
    reason_codes: list[str],
    controls: list[str] | None = None,
) -> dict[str, Any]:
    compatible_bound = status in {"bound", "bound_with_controls"} and decision in {"allow", "allow_with_controls"}
    packet["grounding_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = status in {"bound_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["request_envelope_allowed"] = compatible_bound
    packet["downstream_model_use_allowed"] = compatible_bound
    packet["report_generation_allowed"] = compatible_bound
    packet["evidence_map_use_allowed"] = compatible_bound
    packet["control_package_use_allowed"] = compatible_bound
    packet["grounding_failure_receipt_ref"] = None if compatible_bound else GROUNDING_FAILURE_RECEIPT_NAME
    return packet


def _base_packet(
    *,
    admission_packet: dict[str, Any],
    source_scope_packet: dict[str, Any],
    consent_packet: dict[str, Any],
    source_ref: str,
    source_hash: str,
    evidence_ref: str,
    receipt_ref: str,
    scenario_id: str,
) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_grounding_binding_packet.v1",
        "source_phase": AEGIS_GROUNDING_BINDING_PHASE,
        "scenario_id": scenario_id,
        "admission_ref": admission_packet.get("admission_id", "UNKNOWN_ADMISSION_PACKET"),
        "source_scope_ref": admission_packet.get("source_scope_packet_ref", "aegis_source_scope_packet.json"),
        "consent_ref": admission_packet.get("consent_packet_ref", "aegis_consent_packet.json"),
        "source_ref": source_ref,
        "source_hash": source_hash,
        "evidence_ref": evidence_ref,
        "receipt_ref": receipt_ref,
        **GROUNDING_BINDING_FALSE_FLAGS,
        "non_authority_boundary": GROUNDING_BINDING_NON_AUTHORITY_BOUNDARY,
    }


def build_grounding_binding_packet(
    *,
    admission_packet: dict,
    source_scope_packet: dict,
    consent_packet: dict,
    source_ref: str,
    source_hash: str,
    evidence_ref: str,
    receipt_ref: str,
    scenario_id: str = "valid_grounding_binding",
) -> dict:
    """Bind admitted source and consent packets to evidence references without reading source content."""

    packet = _base_packet(
        admission_packet=admission_packet,
        source_scope_packet=source_scope_packet,
        consent_packet=consent_packet,
        source_ref=source_ref,
        source_hash=source_hash,
        evidence_ref=evidence_ref,
        receipt_ref=receipt_ref,
        scenario_id=scenario_id,
    )

    if scenario_id == "hash_mismatch_alarm" or source_hash == "HASH_MISMATCH":
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["hash_mismatch", "elevated_review_required"])
    if not source_hash or scenario_id == "missing_source_hash_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_source_hash", "fail_closed_no_request_envelope"])
    if not evidence_ref or scenario_id == "missing_evidence_ref_hold":
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["missing_evidence_ref", "human_grounding_review_required"])
    if scenario_id == "source_instruction_quarantine_hold" or source_scope_packet.get("source_scope_status") == "source_instruction_quarantine":
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["source_instruction_quarantine", "human_security_review_required"])
    if not evidence_ref.startswith(("evidence://", "docs/", "receipt://")) or scenario_id == "unsupported_evidence_ref_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["unsupported_evidence_ref", "fail_closed_no_request_envelope"])
    if admission_packet.get("decision") not in COMPATIBLE_ADMISSION_DECISIONS or scenario_id == "admission_not_admitted_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["admission_not_admitted", "fail_closed_no_request_envelope"])
    if source_scope_packet.get("decision") not in COMPATIBLE_SCOPE_DECISIONS or scenario_id == "source_scope_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["source_scope_not_allowed", "fail_closed_no_request_envelope"])
    if consent_packet.get("decision") not in COMPATIBLE_CONSENT_DECISIONS or scenario_id == "consent_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["consent_not_allowed", "fail_closed_no_request_envelope"])

    if source_scope_packet.get("decision") == "allow_with_controls" or consent_packet.get("decision") == "allow_with_controls" or admission_packet.get("decision") == "admit_with_controls" or scenario_id == "pasted_excerpt_grounding_with_controls":
        return _finish(packet, status="bound_with_controls", decision="allow_with_controls", reason_codes=["grounding_bound_with_controls", "admission_scope_consent_compatible"], controls=["preserve_excerpt_boundaries", "human_review_available"])

    if _compatible(admission_packet, source_scope_packet, consent_packet):
        return _finish(packet, status="bound", decision="allow", reason_codes=["grounding_bound", "admission_scope_consent_compatible"])

    return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["grounding_incompatible", "fail_closed_no_request_envelope"])
