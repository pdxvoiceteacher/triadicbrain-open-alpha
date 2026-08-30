"""Noncompensatory totality aperture: no score can offset a failed hard gate."""

from __future__ import annotations

from typing import Any

from .canonical import require_identifier, require_sha256, sha256_json
from .errors import ValidationError

APERTURE_SCHEMA = "uvlm.coherence.totality.aperture_decision.v1"
HARD_GATES = (
    "task_consent",
    "privacy_policy_satisfied",
    "retention_gate_satisfied",
    "grounding_valid",
    "context_binding_valid",
    "quarantine_valid",
    "claim_evidence_valid",
    "ucm_not_refuse",
    "aha_not_rejected",
)
_GATE_REASONS = {
    "task_consent": "TASK_CONSENT_MISSING",
    "privacy_policy_satisfied": "PRIVACY_POLICY_NOT_SATISFIED",
    "retention_gate_satisfied": "RETENTION_REQUEST_WITHOUT_SEPARATE_CONSENT",
    "grounding_valid": "GROUNDING_INVALID",
    "context_binding_valid": "EXPECTED_CONTEXT_BINDING_INVALID",
    "quarantine_valid": "RAW_OUTPUT_QUARANTINE_INVALID",
    "claim_evidence_valid": "CLAIM_EVIDENCE_BINDING_INVALID",
    "ucm_not_refuse": "UCM_REFUSAL",
    "aha_not_rejected": "AHA_STRUCTURAL_REJECTION",
}


def decide_aperture(
    *,
    run_id: str,
    candidate_id: str,
    projector: Any,
    residual_refusal: Any,
    aha_result: Any,
    counterexamples: Any,
    task_consent: bool,
    privacy_policy_satisfied: bool,
    retention_requested: bool,
    retention_consent: bool,
    grounding_valid: bool = True,
    context_binding_valid: bool = True,
    quarantine_valid: bool = True,
    claim_evidence_valid: bool = True,
) -> dict[str, Any]:
    gates = {
        "task_consent": task_consent is True,
        "privacy_policy_satisfied": privacy_policy_satisfied is True,
        "retention_gate_satisfied": not retention_requested or retention_consent is True,
        "grounding_valid": grounding_valid is True,
        "context_binding_valid": context_binding_valid is True,
        "quarantine_valid": quarantine_valid is True,
        "claim_evidence_valid": claim_evidence_valid is True,
        "ucm_not_refuse": projector.get("disposition") != "REFUSE" and residual_refusal.get("refusal", {}).get("triggered") is False,
        "aha_not_rejected": aha_result.get("disposition") != "REJECTED",
    }
    if set(gates) != set(HARD_GATES):
        raise ValidationError("APERTURE_HARD_GATE_INTERNAL_SET_MISMATCH")
    reasons = sorted(_GATE_REASONS[name] for name, passed in gates.items() if not passed)
    if reasons:
        decision = "REFUSE"
    else:
        if projector.get("disposition") == "HOLD":
            reasons.append("UCM_REQUIRES_REVIEW")
        if aha_result.get("status") == "UNAVAILABLE":
            reasons.append("AHA_UNAVAILABLE")
        if counterexamples.get("unresolved_count", 0):
            reasons.append("UNRESOLVED_COUNTEREXAMPLES_PRESENT")
        if reasons:
            decision = "HOLD"
        else:
            decision = "PASS_SCREEN"
            reasons.append("BOUNDED_NONCOMPENSATORY_SCREEN_PASSED")
    return {
        "schema_id": APERTURE_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "projector_receipt_sha256": require_sha256(sha256_json(projector), "$.projector_receipt_sha256"),
        "residual_refusal_sha256": require_sha256(sha256_json(residual_refusal), "$.residual_refusal_sha256"),
        "aha_result_sha256": require_sha256(sha256_json(aha_result), "$.aha_result_sha256"),
        "counterexamples_sha256": require_sha256(sha256_json(counterexamples), "$.counterexamples_sha256"),
        "hard_gates": gates,
        "decision": decision,
        "reasons": sorted(reasons),
        "human_review_required": True,
        "candidate_is_final_answer": False,
        "authority_effect": "NONE",
    }
