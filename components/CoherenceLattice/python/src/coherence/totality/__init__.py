"""Private, additive Triadic Brain totality convergence primitives."""

from .adapter import CapturedAdapter, build_candidate_packet, build_quarantine_verification_receipt, captured_adapter_contract, validate_candidate_packet
from .aha import evaluate_structural_aha
from .aperture import decide_aperture
from .canonical import canonical_json_bytes, sha256_json, strict_json_loads
from .claims import build_claim_evidence_map
from .counterexamples import search_counterexamples
from .grounding import build_grounding_bundle, validate_grounding_bundle
from .pmr import PMRReferenceStore, build_consent_packet, no_write_receipt
from .request import RequestEnvelope, parse_request_envelope, project_legacy_request, validate_request_envelope
from .seal import build_deterministic_zip, seal_run, verify_sealed_run
from .tel import TELLedger, build_human_decision_continuation, parse_final_route_tel_jsonl
from .ucm import build_ucm_state, project_ucm, validate_ucm_state

__all__ = [
    "CapturedAdapter", "PMRReferenceStore", "RequestEnvelope", "TELLedger",
    "build_candidate_packet", "build_claim_evidence_map", "build_consent_packet",
    "build_quarantine_verification_receipt",
    "build_human_decision_continuation",
    "build_deterministic_zip", "build_grounding_bundle", "build_ucm_state",
    "canonical_json_bytes", "captured_adapter_contract", "decide_aperture",
    "evaluate_structural_aha", "no_write_receipt", "parse_request_envelope",
    "parse_final_route_tel_jsonl",
    "project_legacy_request", "project_ucm", "seal_run", "sha256_json",
    "strict_json_loads", "search_counterexamples", "validate_grounding_bundle",
    "validate_request_envelope", "validate_ucm_state", "verify_sealed_run",
    "validate_candidate_packet",
]
