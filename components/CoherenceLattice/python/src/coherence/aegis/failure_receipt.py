from __future__ import annotations

from coherence.aegis.policy import SOURCE_PHASE
from coherence.aegis.types import AegisDecision

FAILURE_RECEIPT_TRUE_FLAGS = {
    "no_request_envelope_created": True,
    "no_downstream_processing_performed": True,
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


def build_aegis_failure_receipt(
    *,
    source_event_ref: str,
    decision: AegisDecision,
    reason_codes: list[str],
) -> dict:
    return {
        "schema": "coherencelattice.aegis_failure_receipt.v1",
        "source_phase": SOURCE_PHASE,
        "failure_receipt_status": "completed",
        "source_event_ref": source_event_ref,
        "decision": decision,
        "reason_codes": reason_codes,
        **FAILURE_RECEIPT_TRUE_FLAGS,
    }
