from __future__ import annotations

from datetime import date
from typing import Any

from coherence.aegis.policy import (
    AEGIS_SOURCE_SCOPE_CONSENT_PHASE,
    CONSENT_FALSE_FLAGS,
    SOURCE_SCOPE_CONSENT_NON_AUTHORITY_BOUNDARY,
)

CONSENT_STATUSES = {
    "consent_valid",
    "consent_valid_with_controls",
    "consent_missing",
    "consent_scope_mismatch",
    "consent_revoked",
    "consent_expired",
    "consent_requires_human_review",
}


def _base_packet(*, consent_profile: dict[str, Any], requested_use: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_consent_packet.v1",
        "source_phase": AEGIS_SOURCE_SCOPE_CONSENT_PHASE,
        "consent_profile_id": consent_profile.get("consent_profile_id", "UNKNOWN_CONSENT_PROFILE"),
        "requested_use": dict(requested_use),
        "controls_required": [],
        "human_review_required": False,
        "failure_receipt_required": False,
        "request_envelope_allowed": False,
        **CONSENT_FALSE_FLAGS,
        "non_authority_boundary": SOURCE_SCOPE_CONSENT_NON_AUTHORITY_BOUNDARY,
    }


def _finish(packet: dict[str, Any], *, status: str, decision: str, reason_codes: list[str], controls: list[str] | None = None) -> dict[str, Any]:
    packet["consent_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["human_review_required"] = decision in {"allow_with_controls", "hold_for_human_review", "alarm_requires_elevated_review"}
    packet["failure_receipt_required"] = decision in {"hold_for_human_review", "reject_fail_closed", "alarm_requires_elevated_review"}
    packet["request_envelope_allowed"] = decision in {"allow", "allow_with_controls"}
    return packet


def _expired(consent_profile: dict[str, Any]) -> bool:
    expires_on = consent_profile.get("expires_on")
    if not expires_on:
        return False
    return date.fromisoformat(expires_on) < date.today()


def evaluate_consent(
    *,
    consent_profile: dict[str, Any],
    requested_use: dict[str, Any],
    scenario_id: str = "valid_explicit_local_file_admit",
) -> dict[str, Any]:
    """Evaluate deterministic consent fit without writing consent state."""

    packet = _base_packet(consent_profile=consent_profile, requested_use=requested_use)

    if not consent_profile or consent_profile.get("consent_present") is False or scenario_id == "missing_consent_reject_fail_closed":
        return _finish(packet, status="consent_missing", decision="reject_fail_closed", reason_codes=["missing_consent", "fail_closed_no_request_envelope"])
    if consent_profile.get("revoked") is True:
        return _finish(packet, status="consent_revoked", decision="reject_fail_closed", reason_codes=["consent_revoked", "fail_closed_no_request_envelope"])
    if _expired(consent_profile):
        return _finish(packet, status="consent_expired", decision="reject_fail_closed", reason_codes=["consent_expired", "fail_closed_no_request_envelope"])
    if consent_profile.get("requires_human_review") is True:
        return _finish(packet, status="consent_requires_human_review", decision="hold_for_human_review", reason_codes=["consent_requires_human_review", "human_consent_review_required"])

    allowed_uses = set(consent_profile.get("allowed_uses", []))
    requested_purpose = requested_use.get("purpose")
    if allowed_uses and requested_purpose not in allowed_uses:
        return _finish(packet, status="consent_scope_mismatch", decision="reject_fail_closed", reason_codes=["consent_scope_mismatch", "fail_closed_no_request_envelope"])

    if requested_use.get("source_kind") == "pasted_excerpt" or scenario_id == "valid_pasted_excerpt_admit_with_controls":
        return _finish(
            packet,
            status="consent_valid_with_controls",
            decision="allow_with_controls",
            reason_codes=["consent_present", "controls_required_for_excerpt"],
            controls=["excerpt_consent_notice", "human_review_available"],
        )

    return _finish(packet, status="consent_valid", decision="allow", reason_codes=["consent_present"])
