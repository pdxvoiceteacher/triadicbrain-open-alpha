from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from coherence.aegis.policy import (
    AEGIS_SOURCE_SCOPE_CONSENT_PHASE,
    SOURCE_SCOPE_FALSE_FLAGS,
    SOURCE_SCOPE_NON_AUTHORITY_BOUNDARY,
)

SOURCE_SCOPE_STATUSES = {
    "scoped",
    "scoped_with_controls",
    "missing_scope",
    "hidden_file_rejected",
    "directory_scan_rejected",
    "connector_scope_missing",
    "unsupported_source_kind",
    "source_instruction_quarantine",
}

SOURCE_SCOPE_DECISIONS = {
    "allow",
    "allow_with_controls",
    "hold_for_human_review",
    "reject_fail_closed",
    "alarm_requires_elevated_review",
}


def _base_packet(*, source_kind: str, source_ref: str, declared_scope: dict[str, Any], requested_access: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_source_scope_packet.v1",
        "source_phase": AEGIS_SOURCE_SCOPE_CONSENT_PHASE,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "declared_scope": dict(declared_scope),
        "requested_access": dict(requested_access),
        "controls_required": [],
        "human_review_required": False,
        "failure_receipt_required": False,
        "request_envelope_allowed": False,
        **SOURCE_SCOPE_FALSE_FLAGS,
        "non_authority_boundary": SOURCE_SCOPE_NON_AUTHORITY_BOUNDARY,
    }


def _finish(packet: dict[str, Any], *, status: str, decision: str, reason_codes: list[str], controls: list[str] | None = None) -> dict[str, Any]:
    packet["source_scope_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = decision in {"allow_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["failure_receipt_required"] = decision in {"hold_for_human_review", "reject_fail_closed", "alarm_requires_elevated_review"}
    packet["request_envelope_allowed"] = decision in {"allow", "allow_with_controls"}
    return packet


def _is_hidden_path(source_ref: str) -> bool:
    return any(part.startswith(".") for part in PurePosixPath(source_ref).parts if part not in {".", ".."})


def evaluate_source_scope(
    *,
    source_kind: str,
    source_ref: str,
    declared_scope: dict[str, Any],
    requested_access: dict[str, Any],
    scenario_id: str = "valid_explicit_local_file_admit",
) -> dict[str, Any]:
    """Evaluate deterministic AEGIS source scope without reading sources or scanning directories."""

    packet = _base_packet(
        source_kind=source_kind,
        source_ref=source_ref,
        declared_scope=declared_scope,
        requested_access=requested_access,
    )

    if scenario_id == "source_instruction_quarantine_hold" or requested_access.get("contains_source_instruction") is True:
        return _finish(
            packet,
            status="source_instruction_quarantine",
            decision="hold_for_human_review",
            reason_codes=["source_instruction_quarantine", "human_security_review_required"],
            controls=["quarantine_source_instruction", "human_security_review"],
        )

    if source_kind == "pasted_excerpt":
        if declared_scope.get("excerpt_allowed") is True or declared_scope.get("explicit_selection") is True:
            return _finish(
                packet,
                status="scoped_with_controls",
                decision="allow_with_controls",
                reason_codes=["pasted_excerpt_scope_valid", "controls_required_for_excerpt"],
                controls=["excerpt_boundary_notice", "human_review_available"],
            )
        return _finish(
            packet,
            status="missing_scope",
            decision="hold_for_human_review",
            reason_codes=["missing_configured_scope", "human_scope_review_required"],
        )

    if source_kind == "local_file":
        if _is_hidden_path(source_ref) or requested_access.get("hidden_file") is True:
            return _finish(
                packet,
                status="hidden_file_rejected",
                decision="reject_fail_closed",
                reason_codes=["hidden_file_rejected", "fail_closed_no_request_envelope"],
            )
        if requested_access.get("directory_scan") is True or declared_scope.get("directory_scan_allowed") is True:
            return _finish(
                packet,
                status="directory_scan_rejected",
                decision="reject_fail_closed",
                reason_codes=["directory_scan_rejected", "fail_closed_no_request_envelope"],
            )
        if declared_scope.get("explicit_selection") is True and source_ref in set(declared_scope.get("allowed_refs", [source_ref])):
            return _finish(
                packet,
                status="scoped",
                decision="allow",
                reason_codes=["explicit_local_file_scope_valid"],
            )
        return _finish(
            packet,
            status="missing_scope",
            decision="hold_for_human_review",
            reason_codes=["missing_configured_scope", "human_scope_review_required"],
        )

    if source_kind == "directory":
        return _finish(
            packet,
            status="directory_scan_rejected",
            decision="reject_fail_closed",
            reason_codes=["directory_scan_rejected", "fail_closed_no_request_envelope"],
        )

    if source_kind == "connector":
        if declared_scope.get("connector_scope") is True and declared_scope.get("connector_id") == requested_access.get("connector_id"):
            return _finish(packet, status="scoped", decision="allow", reason_codes=["explicit_connector_scope_valid"])
        return _finish(
            packet,
            status="connector_scope_missing",
            decision="reject_fail_closed",
            reason_codes=["connector_without_scope", "fail_closed_no_request_envelope"],
        )

    return _finish(
        packet,
        status="unsupported_source_kind",
        decision="reject_fail_closed",
        reason_codes=["unsupported_source_kind", "fail_closed_no_request_envelope"],
    )
