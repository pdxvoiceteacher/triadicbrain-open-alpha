from __future__ import annotations

from typing import Any

from coherence.aegis.policy import (
    AEGIS_ACTION_FIREWALL_PHASE,
    ACTION_FIREWALL_FAILURE_RECEIPT_NAME,
    ACTION_FIREWALL_FALSE_FLAGS,
    ACTION_FIREWALL_NON_AUTHORITY_BOUNDARY,
)

SAFE_ACTIONS = {"noop", "local_preview", "report_draft_preview"}
SUPPORTED_ACTIONS = SAFE_ACTIONS | {
    "file_write", "file_delete", "connector_pull", "connector_push", "network_call", "provider_call",
    "memory_write", "atlas_memory_admission", "trace_export", "pmr_federation", "package_install",
    "package_activation", "package_execution", "payment_processing", "subscription_billing",
    "marketplace_download", "final_answer_emit", "accepted_evidence_mark",
}
ALARM_ACTIONS = {"file_delete", "connector_push", "memory_write", "atlas_memory_admission"}
HOLD_ACTIONS = {"trace_export", "pmr_federation"}
REJECT_ACTIONS = SUPPORTED_ACTIONS - SAFE_ACTIONS - ALARM_ACTIONS - HOLD_ACTIONS


def _ref(value: dict | None, key: str, fallback: str) -> str:
    if not isinstance(value, dict):
        return "MISSING_PACKET"
    ref = value.get(key)
    return ref if isinstance(ref, str) and ref else fallback


def _base_packet(*, model_candidate_gate_packet: dict | None, proposed_action: dict, operator_authorization: dict | None, scenario_id: str) -> dict[str, Any]:
    action_ref = proposed_action.get("action_ref", "missing_action_ref")
    action_kind = proposed_action.get("action_kind", "unsupported")
    return {
        "schema": "coherencelattice.aegis_action_firewall_packet.v1",
        "source_phase": AEGIS_ACTION_FIREWALL_PHASE,
        "action_firewall_status": "reject_fail_closed",
        "scenario_id": scenario_id,
        "action_ref": action_ref,
        "action_kind": action_kind,
        "action_description": proposed_action.get("action_description", "AEGIS action firewall fixture action"),
        "model_candidate_gate_ref": _ref(model_candidate_gate_packet, "candidate_request_ref", "aegis_model_candidate_gate_packet.json"),
        "operator_authorization_ref": _ref(operator_authorization, "authorization_ref", "NO_OPERATOR_AUTHORIZATION"),
        "operator_authorization_status": operator_authorization.get("authorization_status") if isinstance(operator_authorization, dict) else "missing",
        "side_effecting_action": proposed_action.get("side_effecting", False),
        "reason_codes": [],
        "controls_required": [],
        "human_review_required": False,
        "action_allowed": False,
        "action_firewall_failure_receipt_ref": ACTION_FIREWALL_FAILURE_RECEIPT_NAME,
        **ACTION_FIREWALL_FALSE_FLAGS,
        "non_authority_boundary": ACTION_FIREWALL_NON_AUTHORITY_BOUNDARY,
    }


def _finish(packet: dict[str, Any], *, status: str, decision: str, reason_codes: list[str], controls: list[str] | None = None) -> dict[str, Any]:
    allowed = status in {"action_allowed", "action_allowed_with_controls"}
    packet["action_firewall_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = status in {"action_allowed_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["action_allowed"] = allowed
    packet["action_firewall_failure_receipt_ref"] = None if allowed else ACTION_FIREWALL_FAILURE_RECEIPT_NAME
    return packet


def build_action_firewall_failure_receipt(*, packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_action_firewall_failure_receipt.v1",
        "source_phase": AEGIS_ACTION_FIREWALL_PHASE,
        "action_firewall_failure_receipt_status": "completed",
        "scenario_id": packet["scenario_id"],
        "action_ref": packet["action_ref"],
        "action_kind": packet["action_kind"],
        "decision": packet["decision"],
        "reason_codes": list(packet["reason_codes"]),
        "no_action_performed": True,
        "no_tool_execution": True,
        "no_file_write": True,
        "no_file_delete": True,
        "no_connector_pull": True,
        "no_connector_push": True,
        "no_provider_call": True,
        "no_network_call": True,
        "no_memory_write": True,
        "no_atlas_admission": True,
        "no_trace_export": True,
        "no_pmr_federation": True,
        "no_package_install": True,
        "no_package_activation": True,
        "no_package_execution": True,
        "no_payment_processing": True,
        "no_subscription_billing": True,
        "no_marketplace_download": True,
        "no_final_answer_authority": True,
        "no_accepted_evidence_authority": True,
        "human_review_required": True,
    }


def _authorization_valid(proposed_action: dict, operator_authorization: dict | None) -> bool:
    if not proposed_action.get("requires_operator_authorization", False):
        return True
    if not isinstance(operator_authorization, dict):
        return False
    if operator_authorization.get("authorization_status") not in {"authorized_for_preview_only", "authorized_for_requested_action"}:
        return False
    return operator_authorization.get("action_ref") == proposed_action.get("action_ref")


def evaluate_action_firewall(*, model_candidate_gate_packet: dict, proposed_action: dict, operator_authorization: dict | None = None, scenario_id: str = "safe_noop_action_allowed") -> dict:
    packet = _base_packet(model_candidate_gate_packet=model_candidate_gate_packet, proposed_action=proposed_action, operator_authorization=operator_authorization, scenario_id=scenario_id)
    kind = proposed_action.get("action_kind")

    if not isinstance(model_candidate_gate_packet, dict) or not model_candidate_gate_packet or scenario_id == "missing_model_candidate_gate_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_model_candidate_gate", "fail_closed_no_action"])
    if model_candidate_gate_packet.get("model_candidate_allowed") is not True or scenario_id == "model_candidate_not_allowed_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["model_candidate_not_allowed", "fail_closed_no_action"])
    if model_candidate_gate_packet.get("model_candidate_created") is not False or model_candidate_gate_packet.get("provider_runtime_performed") is not False or model_candidate_gate_packet.get("model_output_generated") is not False:
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["model_candidate_runtime_side_effect_detected", "fail_closed_no_action"])
    if kind not in SUPPORTED_ACTIONS or scenario_id == "unsupported_action_kind_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["unsupported_action_kind", "fail_closed_no_action"])
    if proposed_action.get("requires_human_review") is True or scenario_id == "destructive_action_hold":
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["destructive_or_human_review_action", "no_action_performed"], controls=["elevated_operator_review"])
    if proposed_action.get("requires_operator_authorization") and not isinstance(operator_authorization, dict) or scenario_id == "missing_operator_authorization_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_operator_authorization", "fail_closed_no_action"])
    if not _authorization_valid(proposed_action, operator_authorization) or scenario_id == "operator_authorization_mismatch_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["operator_authorization_mismatch", "fail_closed_no_action"])
    if kind in ALARM_ACTIONS:
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=[f"{kind}_blocked", "no_action_performed"])
    if kind in HOLD_ACTIONS:
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=[f"{kind}_requires_human_review", "no_action_performed"], controls=["elevated_operator_review"])
    if kind in REJECT_ACTIONS:
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=[f"{kind}_blocked", "fail_closed_no_action"])

    if kind == "noop" and proposed_action.get("side_effecting") is False:
        return _finish(packet, status="action_allowed", decision="allow", reason_codes=["noop_action_allowed", "action_not_performed"])
    if kind in {"local_preview", "report_draft_preview"} and proposed_action.get("side_effecting") in {False, "preview_only"}:
        return _finish(packet, status="action_allowed_with_controls", decision="allow_with_controls", reason_codes=["preview_action_allowed_with_controls", "action_not_performed"], controls=["preview_only", "operator_authorization_preserved"])
    return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["side_effect_outside_preview_scope", "fail_closed_no_action"])
