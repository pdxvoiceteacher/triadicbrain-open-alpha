from __future__ import annotations

import hashlib
import re
from typing import Any

from coherence.aegis.policy import (
    AEGIS_INSTRUCTION_QUARANTINE_PHASE,
    INSTRUCTION_QUARANTINE_FALSE_FLAGS,
    INSTRUCTION_QUARANTINE_NON_AUTHORITY_BOUNDARY,
    INSTRUCTION_QUARANTINE_RECEIPT_NAME,
)

QUARANTINE_STATUSES = {
    "clear",
    "clear_with_notice",
    "quarantine_for_human_review",
    "reject_fail_closed",
    "alarm_requires_elevated_review",
}

INSTRUCTION_PATTERN_CLASSES = {
    "ignore_prior_instructions": re.compile(r"ignore\s+(all\s+)?(prior|previous|above)\s+instructions", re.I),
    "system_override_attempt": re.compile(r"(system|developer)\s+(override|prompt|instruction)|you\s+are\s+now", re.I),
    "hidden_file_access_request": re.compile(r"(read|open|cat|show).*(\.env|hidden file|dotfile|secret file)", re.I),
    "directory_scan_request": re.compile(r"(scan|list|walk|enumerate).*(directory|folder|repo|filesystem)", re.I),
    "connector_pull_request": re.compile(r"(pull|fetch|sync).*(connector|drive|gmail|slack|sharepoint)", re.I),
    "data_exfiltration_request": re.compile(r"(exfiltrate|send.*secret|upload.*token|leak)", re.I),
    "memory_write_request": re.compile(r"(write|store|save|commit).*(memory|atlas)", re.I),
    "compliance_certification_request": re.compile(r"certif(y|ies|ication).*(compliance|eu ai act|soc ?2|iso)", re.I),
    "legal_advice_request": re.compile(r"provide legal advice|legal opinion", re.I),
    "audit_pass_request": re.compile(r"(pass|guarantee).*(audit|attestation)", re.I),
    "final_answer_authority_request": re.compile(r"(final answer|authoritative answer|answer authority)", re.I),
    "accepted_evidence_authority_request": re.compile(r"accepted[- ]evidence|accept as evidence", re.I),
    "obfuscated_instruction_pattern": re.compile(r"i\s+g\s+n\s+o\s+r\s+e|base64|rot13|obfuscated instruction", re.I),
}

ALARM_PATTERNS = {"data_exfiltration_request", "memory_write_request"}
REJECT_PATTERNS = {
    "ignore_prior_instructions",
    "system_override_attempt",
    "hidden_file_access_request",
    "directory_scan_request",
    "connector_pull_request",
    "compliance_certification_request",
    "legal_advice_request",
    "audit_pass_request",
    "final_answer_authority_request",
    "accepted_evidence_authority_request",
}
HOLD_PATTERNS = {"obfuscated_instruction_pattern"}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_instruction_patterns(source_excerpt: str) -> list[str]:
    return [name for name, pattern in INSTRUCTION_PATTERN_CLASSES.items() if pattern.search(source_excerpt)]


def _grounding_allows(grounding_packet: dict[str, Any] | None) -> bool:
    if grounding_packet is None:
        return False
    return all(
        grounding_packet.get(field) is True
        for field in [
            "downstream_model_use_allowed",
            "report_generation_allowed",
            "evidence_map_use_allowed",
            "control_package_use_allowed",
        ]
    )


def _base_packet(
    *,
    source_ref: str,
    source_excerpt: str,
    source_scope_packet: dict[str, Any],
    grounding_packet: dict[str, Any] | None,
    scenario_id: str,
) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_instruction_quarantine_packet.v1",
        "source_phase": AEGIS_INSTRUCTION_QUARANTINE_PHASE,
        "scenario_id": scenario_id,
        "source_ref": source_ref,
        "source_excerpt_sha256": _sha256(source_excerpt),
        "source_scope_ref": source_scope_packet.get("source_scope_packet_ref", "aegis_source_scope_packet.json"),
        "grounding_ref": None if grounding_packet is None else "aegis_grounding_binding_packet.json",
        "detected_instruction_patterns": [],
        "safe_excerpt_preserved": True,
        "quarantined_instruction_count": 0,
        **INSTRUCTION_QUARANTINE_FALSE_FLAGS,
        "non_authority_boundary": INSTRUCTION_QUARANTINE_NON_AUTHORITY_BOUNDARY,
    }


def _finish(
    packet: dict[str, Any],
    *,
    status: str,
    decision: str,
    reason_codes: list[str],
    patterns: list[str],
    controls: list[str] | None = None,
    grounding_allows: bool = False,
) -> dict[str, Any]:
    clear = status in {"clear", "clear_with_notice"} and decision in {"allow", "allow_with_controls"}
    downstream_allowed = clear and grounding_allows
    packet["quarantine_status"] = status
    packet["decision"] = decision
    packet["reason_codes"] = reason_codes
    packet["controls_required"] = controls or []
    packet["detected_instruction_patterns"] = patterns
    packet["quarantined_instruction_count"] = 0 if clear else len(patterns)
    packet["human_review_required"] = status in {"clear_with_notice", "quarantine_for_human_review", "alarm_requires_elevated_review"}
    packet["quarantine_receipt_ref"] = None if clear else INSTRUCTION_QUARANTINE_RECEIPT_NAME
    packet["downstream_model_use_allowed"] = downstream_allowed
    packet["report_generation_allowed"] = downstream_allowed
    packet["evidence_map_use_allowed"] = downstream_allowed
    packet["control_package_use_allowed"] = downstream_allowed
    return packet


def build_instruction_quarantine_receipt(*, packet: dict[str, Any]) -> dict[str, Any]:
    decision = packet["decision"]
    no_downstream = decision in {"hold_for_human_review", "reject_fail_closed", "alarm_requires_elevated_review"}
    return {
        "schema": "coherencelattice.aegis_instruction_quarantine_receipt.v1",
        "source_phase": AEGIS_INSTRUCTION_QUARANTINE_PHASE,
        "quarantine_receipt_status": "completed",
        "scenario_id": packet["scenario_id"],
        "source_ref": packet["source_ref"],
        "decision": decision,
        "reason_codes": list(packet["reason_codes"]),
        "detected_instruction_patterns": list(packet["detected_instruction_patterns"]),
        "no_instruction_executed": True,
        "no_downstream_model_use": no_downstream,
        "no_report_generation": no_downstream,
        "no_evidence_map_use": no_downstream,
        "no_control_package_use": no_downstream,
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


def evaluate_instruction_quarantine(
    *,
    source_ref: str,
    source_excerpt: str,
    source_scope_packet: dict,
    grounding_packet: dict | None = None,
    scenario_id: str = "safe_source_excerpt",
) -> dict:
    """Separate source content from source-borne instructions without executing them."""

    patterns = detect_instruction_patterns(source_excerpt)
    packet = _base_packet(
        source_ref=source_ref,
        source_excerpt=source_excerpt,
        source_scope_packet=source_scope_packet,
        grounding_packet=grounding_packet,
        scenario_id=scenario_id,
    )
    grounding_allows = _grounding_allows(grounding_packet)

    if scenario_id == "safe_source_excerpt" and not patterns:
        return _finish(packet, status="clear", decision="allow", reason_codes=["source_excerpt_clear"], patterns=[], grounding_allows=grounding_allows)
    if scenario_id == "benign_instruction_quoted_as_content":
        return _finish(packet, status="clear_with_notice", decision="allow_with_controls", reason_codes=["instruction_quoted_as_content", "preserve_as_evidence_only"], patterns=patterns, controls=["quote_boundary_notice"], grounding_allows=grounding_allows)
    if scenario_id in {"source_instruction_quarantine_hold", "prompt_injection_quarantine_hold"} or source_scope_packet.get("source_scope_status") == "source_instruction_quarantine":
        return _finish(packet, status="quarantine_for_human_review", decision="hold_for_human_review", reason_codes=["source_instruction_quarantine", "human_review_required"], patterns=patterns or ["system_override_attempt"], controls=["quarantine_source_instruction"])
    if scenario_id == "malformed_or_obfuscated_instruction_hold" or any(pattern in HOLD_PATTERNS for pattern in patterns):
        return _finish(packet, status="quarantine_for_human_review", decision="hold_for_human_review", reason_codes=["obfuscated_instruction_pattern", "human_review_required"], patterns=patterns or ["obfuscated_instruction_pattern"], controls=["quarantine_source_instruction"])
    if scenario_id == "instruction_to_exfiltrate_alarm" or scenario_id == "instruction_to_write_memory_alarm" or any(pattern in ALARM_PATTERNS for pattern in patterns):
        alarm_patterns = patterns or (["memory_write_request"] if "memory" in source_excerpt.casefold() else ["data_exfiltration_request"])
        return _finish(packet, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["instruction_alarm", "elevated_review_required"], patterns=alarm_patterns, controls=["elevated_security_review"])
    if scenario_id.startswith("instruction_to_") or any(pattern in REJECT_PATTERNS for pattern in patterns):
        reject_patterns = patterns or ["system_override_attempt"]
        return _finish(packet, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["source_instruction_rejected", "fail_closed_no_downstream_use"], patterns=reject_patterns)
    if patterns:
        return _finish(packet, status="quarantine_for_human_review", decision="hold_for_human_review", reason_codes=["source_instruction_pattern_detected", "human_review_required"], patterns=patterns, controls=["quarantine_source_instruction"])
    return _finish(packet, status="clear", decision="allow", reason_codes=["source_excerpt_clear"], patterns=[], grounding_allows=grounding_allows)
