# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Security-critical consumer contract for the Atlas totality posture packet."""

from __future__ import annotations

from typing import Any, Mapping

from .canonical import require_exact_keys, require_identifier
from .errors import ValidationError


ATLAS_PACKET_KEYS = {
    "schema_id",
    "schema_version",
    "packet_type",
    "producer_repository",
    "producer",
    "run_id",
    "logical_time",
    "candidate_id",
    "audit_id",
    "input_digests",
    "parent_list",
    "sophia_disposition",
    "sophia_reason_codes",
    "sophia_findings",
    "retention_posture",
    "publication_posture",
    "expiry_posture",
    "revocation_posture",
    "pmr_posture",
    "candidate_is_not_answer",
    "full_posterior_presented",
    "top_k_is_presentation_only",
    "human_action_required",
    "requires_human_review",
    "human_decision",
    "human_decision_options",
    "limitations",
    "nonauthority",
    "side_effects",
    "nonauthority_statement",
}
ATLAS_NONAUTHORITY = (
    "truth_certification",
    "final_answer_authority",
    "memory_write_authority",
    "pmr_write_authority",
    "training_authority",
    "canonization",
    "publication",
    "doi_mutation",
    "crossref_deposit",
    "catalog_mutation",
    "knowledge_graph_mutation",
    "deployment",
    "release",
    "model_invocation",
    "candidate_alteration",
    "sophia_alteration",
    "external_action_authority",
    "automatic_phase_advance",
)
ATLAS_EFFECTS = (
    "network_access_performed",
    "model_invocation_performed",
    "candidate_mutation_performed",
    "sophia_mutation_performed",
    "source_mutation_performed",
    "memory_write_performed",
    "pmr_write_performed",
    "training_performed",
    "canonization_performed",
    "publication_performed",
    "doi_mutated",
    "crossref_deposit_performed",
    "catalog_mutated",
    "knowledge_graph_mutated",
    "deployment_performed",
    "release_performed",
)
ATLAS_DECISIONS = ("APPROVE", "HOLD", "REJECT", "REPAIR")
ATLAS_POSTURES = {
    "PASS": ("retain_for_human_review", "publication_blocked_pending_human_review"),
    "HOLD": ("quarantine", "do_not_publish"),
    "REJECT": ("rejected", "do_not_publish"),
}
ATLAS_NONAUTHORITY_STATEMENT = (
    "Atlas presents bounded evidence and posture only. It does not certify truth "
    "or authorize memory, PMR, training, canonization, publication, deployment, "
    "release, or any external action."
)


def _false_exact_map(value: Any, keys: tuple[str, ...], path: str) -> None:
    require_exact_keys(value, required=set(keys), path=path)
    if any(item is not False for item in value.values()):
        raise ValidationError(f"ATLAS_POSITIVE_AUTHORITY_OR_EFFECT:{path}")


def validate_atlas_posture_packet(
    packet: Mapping[str, Any], *, sophia_disposition: str
) -> None:
    """Reject any Atlas packet outside the bounded human-review-only contract."""

    require_exact_keys(packet, required=ATLAS_PACKET_KEYS, path="$.atlas")
    if sophia_disposition not in ATLAS_POSTURES:
        raise ValidationError("ATLAS_SOPHIA_DISPOSITION_INVALID")
    producer = packet["producer"]
    require_exact_keys(
        producer,
        required={"repository", "role", "version"},
        path="$.atlas.producer",
    )
    if (
        packet["schema_id"] != "uvlm.atlas.totality.posture_packet.v1"
        or packet["schema_version"] != "1.0"
        or packet["packet_type"] != "atlas_posture_packet"
        or packet["producer_repository"] != "pdxvoiceteacher/uvlm-publications"
        or producer
        != {
            "repository": "pdxvoiceteacher/uvlm-publications",
            "role": "bounded_totality_posture_and_human_review_renderer",
            "version": "1.0",
        }
        or packet["sophia_disposition"] != sophia_disposition
        or (packet["retention_posture"], packet["publication_posture"])
        != ATLAS_POSTURES[sophia_disposition]
        or packet["expiry_posture"] != "review_bounded"
        or packet["revocation_posture"] != "revocable"
        or packet["pmr_posture"] != "separate_consent_no_action"
        or any(
            packet[name] is not True
            for name in (
                "candidate_is_not_answer",
                "full_posterior_presented",
                "top_k_is_presentation_only",
                "human_action_required",
                "requires_human_review",
            )
        )
        or packet["human_decision"] != "PENDING"
        or packet["human_decision_options"] != list(ATLAS_DECISIONS)
        or not isinstance(packet["limitations"], list)
        or not packet["limitations"]
        or any(not isinstance(item, str) or not item for item in packet["limitations"])
        or not isinstance(packet["sophia_reason_codes"], list)
        or not packet["sophia_reason_codes"]
        or any(not isinstance(item, str) or not item for item in packet["sophia_reason_codes"])
        or not isinstance(packet["sophia_findings"], list)
        or not isinstance(packet["input_digests"], dict)
        or not isinstance(packet["parent_list"], list)
        or packet["nonauthority_statement"] != ATLAS_NONAUTHORITY_STATEMENT
    ):
        raise ValidationError("ATLAS_BOUNDED_POSTURE_CONTRACT_INVALID")
    for name in ("run_id", "candidate_id", "audit_id"):
        require_identifier(packet[name], f"$.atlas.{name}")
    if not isinstance(packet["logical_time"], str) or not packet["logical_time"]:
        raise ValidationError("ATLAS_LOGICAL_TIME_INVALID")
    _false_exact_map(packet["nonauthority"], ATLAS_NONAUTHORITY, "$.atlas.nonauthority")
    _false_exact_map(packet["side_effects"], ATLAS_EFFECTS, "$.atlas.side_effects")
