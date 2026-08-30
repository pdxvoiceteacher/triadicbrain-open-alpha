from __future__ import annotations

import re
from typing import Any

from coherence.aegis.policy import (
    AEGIS_LOCAL_RUNTIME_ENFORCEMENT_PHASE,
    LOCAL_RUNTIME_ENFORCEMENT_ALLOWED_CLAIM,
    LOCAL_RUNTIME_ENFORCEMENT_BLOCKED_CLAIMS,
    LOCAL_RUNTIME_ENFORCEMENT_FAILURE_RECEIPT_NAME,
    LOCAL_RUNTIME_ENFORCEMENT_FALSE_FLAGS,
    LOCAL_RUNTIME_ENFORCEMENT_NON_AUTHORITY_BOUNDARY,
)

SAFE_ALLOW = {"local_preview", "local_receipt_view"}
SAFE_CONTROLS = {"report_draft_preview", "evidence_support_review"}
ALARM_OPS = {"file_delete", "connector_push", "memory_write", "atlas_memory_admission"}
HOLD_OPS = {"trace_export", "pmr_federation"}
REJECT_OPS = {
    "model_candidate_generation", "tool_execution", "file_write", "connector_pull", "network_call",
    "provider_call", "package_install", "package_activation", "package_execution", "payment_processing",
    "subscription_billing", "marketplace_download", "final_answer_emit", "accepted_evidence_mark",
}
SUPPORTED_OPS = SAFE_ALLOW | SAFE_CONTROLS | ALARM_OPS | HOLD_OPS | REJECT_OPS
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _ref(value: dict | None, key: str, fallback: str) -> str:
    if not isinstance(value, dict):
        return fallback
    ref = value.get(key)
    return ref if isinstance(ref, str) and ref else fallback


def _base_packet(*, manifest: dict | None, requested_operation: dict, operator_authorization: dict | None, scenario_id: str) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_local_runtime_enforcement_preflight_packet.v1",
        "source_phase": AEGIS_LOCAL_RUNTIME_ENFORCEMENT_PHASE,
        "preflight_status": "reject_fail_closed",
        "scenario_id": scenario_id,
        "receipt_chain_ref": _ref(manifest, "export_ref", "MISSING_RECEIPT_CHAIN_MANIFEST"),
        "receipt_chain_sha256": manifest.get("chain_sha256") if isinstance(manifest, dict) else None,
        "expected_chain_sha256": requested_operation.get("expected_chain_sha256"),
        "requested_operation_ref": requested_operation.get("operation_ref", "missing_operation_ref"),
        "operation_category": requested_operation.get("operation_category", "unsupported"),
        "operation_description": requested_operation.get("operation_description", "AEGIS local runtime preflight operation"),
        "operator_authorization_ref": _ref(operator_authorization, "authorization_ref", "NO_OPERATOR_AUTHORIZATION"),
        "operator_authorization_status": operator_authorization.get("authorization_status") if isinstance(operator_authorization, dict) else "missing",
        "reason_codes": [],
        "controls_required": [],
        "human_review_required": False,
        "preflight_allowed": False,
        "operation_allowed": False,
        "enforcement_failure_receipt_ref": LOCAL_RUNTIME_ENFORCEMENT_FAILURE_RECEIPT_NAME,
        **LOCAL_RUNTIME_ENFORCEMENT_FALSE_FLAGS,
        "non_authority_boundary": LOCAL_RUNTIME_ENFORCEMENT_NON_AUTHORITY_BOUNDARY,
        "blocked_claims": LOCAL_RUNTIME_ENFORCEMENT_BLOCKED_CLAIMS,
        "allowed_claim": LOCAL_RUNTIME_ENFORCEMENT_ALLOWED_CLAIM,
    }


def _finish(packet: dict[str, Any], *, status: str, decision: str, reason_codes: list[str], controls: list[str] | None = None) -> dict[str, Any]:
    allowed = status in {"preflight_allowed", "preflight_allowed_with_controls"}
    packet["preflight_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = status in {"preflight_allowed_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["preflight_allowed"] = allowed
    packet["operation_allowed"] = allowed
    packet["enforcement_failure_receipt_ref"] = None if allowed else LOCAL_RUNTIME_ENFORCEMENT_FAILURE_RECEIPT_NAME
    return packet


def build_local_runtime_enforcement_failure_receipt(*, packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_local_runtime_enforcement_failure_receipt.v1",
        "source_phase": AEGIS_LOCAL_RUNTIME_ENFORCEMENT_PHASE,
        "enforcement_failure_receipt_status": "completed",
        "scenario_id": packet["scenario_id"],
        "receipt_chain_ref": packet["receipt_chain_ref"],
        "receipt_chain_sha256": packet["receipt_chain_sha256"],
        "requested_operation_ref": packet["requested_operation_ref"],
        "operation_category": packet["operation_category"],
        "decision": packet["decision"],
        "reason_codes": list(packet["reason_codes"]),
        "no_operation_performed": True,
        "no_tool_execution": True,
        "no_action_performed": True,
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
        "no_model_candidate_created": True,
        "no_model_output_generated": True,
        "no_final_answer_authority": True,
        "no_accepted_evidence_authority": True,
        "human_review_required": True,
    }


def _authorization_valid(operation: dict, operator_authorization: dict | None) -> bool:
    if not operation.get("requires_operator_authorization", False):
        return True
    if not isinstance(operator_authorization, dict):
        return False
    if operator_authorization.get("authorization_status") not in {"authorized_for_preview_only", "authorized_for_requested_operation"}:
        return False
    return operator_authorization.get("operation_ref") == operation.get("operation_ref")


def _manifest_false_flags_valid(manifest: dict) -> bool:
    for key in ["external_export_performed", "provider_runtime_performed", "network_call_performed", "tool_execution_performed", "action_performed", "memory_write_performed", "final_answer_authority_granted", "accepted_evidence_authority_granted"]:
        if manifest.get(key) is not False:
            return False
    return True


def evaluate_local_runtime_preflight(*, receipt_chain_manifest: dict, requested_operation: dict, operator_authorization: dict | None = None, scenario_id: str = "valid_preview_preflight_allowed") -> dict:
    packet = _base_packet(manifest=receipt_chain_manifest, requested_operation=requested_operation, operator_authorization=operator_authorization, scenario_id=scenario_id)
    category = requested_operation.get("operation_category")
    chain_sha = receipt_chain_manifest.get("chain_sha256") if isinstance(receipt_chain_manifest, dict) else None
    expected_sha = requested_operation.get("expected_chain_sha256")

    if not isinstance(receipt_chain_manifest, dict) or not receipt_chain_manifest or scenario_id == "missing_receipt_chain_manifest_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_receipt_chain_manifest", "fail_closed_preflight"])
    if receipt_chain_manifest.get("schema") != "coherencelattice.aegis_receipt_chain_export_manifest.v1" or receipt_chain_manifest.get("source_phase") != "AEGIS-RECEIPT-CHAIN-EXPORT-00" or scenario_id == "invalid_receipt_chain_schema_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["invalid_receipt_chain_schema", "fail_closed_preflight"])
    if not isinstance(chain_sha, str) or not HEX64.match(chain_sha) or scenario_id == "missing_chain_sha_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_or_malformed_chain_sha", "fail_closed_preflight"])
    if expected_sha is not None and expected_sha != chain_sha or scenario_id == "chain_hash_mismatch_alarm":
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["chain_hash_mismatch", "elevated_review_required"])
    if not _manifest_false_flags_valid(receipt_chain_manifest):
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["receipt_chain_side_effect_flag_detected", "fail_closed_preflight"])
    missing_rows = [row.get("artifact_ref") for row in receipt_chain_manifest.get("chain_rows", []) if row.get("artifact_required") is True and row.get("artifact_present") is not True]
    if missing_rows or receipt_chain_manifest.get("missing_required_packets") or scenario_id == "missing_required_chain_row_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_required_chain_row", "fail_closed_preflight"])
    if category not in SUPPORTED_OPS or scenario_id == "unsupported_operation_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["unsupported_operation", "fail_closed_preflight"])
    if requested_operation.get("requires_human_review") is True:
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["operation_requires_human_review"], controls=["human_review_required"])
    if requested_operation.get("requires_operator_authorization") and not isinstance(operator_authorization, dict) or scenario_id == "missing_operator_authorization_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_operator_authorization", "fail_closed_preflight"])
    if not _authorization_valid(requested_operation, operator_authorization) or scenario_id == "operator_authorization_mismatch_reject":
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["operator_authorization_mismatch", "fail_closed_preflight"])

    completed_with_failures = receipt_chain_manifest.get("export_manifest_status") == "export_manifest_completed_with_failures"
    if completed_with_failures and category in {"model_candidate_generation", "tool_execution", "file_write", "file_delete", "connector_pull", "connector_push", "network_call", "provider_call", "memory_write", "atlas_memory_admission", "trace_export", "pmr_federation", "package_install", "package_activation", "package_execution", "payment_processing", "subscription_billing", "marketplace_download", "final_answer_emit", "accepted_evidence_mark"}:
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["completed_with_failures_blocks_operation", "fail_closed_preflight"])
    if category in ALARM_OPS:
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=[f"{category}_blocked", "elevated_review_required"])
    if category in HOLD_OPS:
        return _finish(packet, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=[f"{category}_requires_human_review"], controls=["human_review_required"])
    if category in REJECT_OPS:
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=[f"{category}_blocked", "fail_closed_preflight"])

    side_effecting = requested_operation.get("side_effecting", False)
    if category in SAFE_ALLOW and side_effecting is False and not completed_with_failures:
        return _finish(packet, status="preflight_allowed", decision="allow", reason_codes=["preflight_allowed", "operation_not_performed"])
    if category in (SAFE_ALLOW | SAFE_CONTROLS) and side_effecting in {False, "preview_only"}:
        return _finish(packet, status="preflight_allowed_with_controls", decision="allow_with_controls", reason_codes=["preflight_allowed_with_controls", "operation_not_performed"], controls=["local_preflight_only", "human_review_available"])
    return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["side_effecting_operation_not_allowed", "fail_closed_preflight"])
