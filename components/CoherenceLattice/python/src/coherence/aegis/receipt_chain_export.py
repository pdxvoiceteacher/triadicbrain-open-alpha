from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from coherence.aegis.policy import (
    AEGIS_RECEIPT_CHAIN_EXPORT_PHASE,
    RECEIPT_CHAIN_EXPORT_ALLOWED_CLAIM,
    RECEIPT_CHAIN_EXPORT_BLOCKED_CLAIMS,
    RECEIPT_CHAIN_EXPORT_FAILURE_RECEIPT_NAME,
    RECEIPT_CHAIN_EXPORT_FALSE_FLAGS,
    RECEIPT_CHAIN_EXPORT_NON_AUTHORITY_BOUNDARY,
)

PACKET_REFS = [
    "aegis_admission_packet.json",
    "aegis_source_scope_packet.json",
    "aegis_consent_packet.json",
    "aegis_grounding_binding_packet.json",
    "aegis_instruction_quarantine_packet.json",
    "aegis_model_candidate_gate_packet.json",
    "aegis_action_firewall_packet.json",
]
RECEIPT_REFS = [
    "aegis_failure_receipt.json",
    "aegis_grounding_failure_receipt.json",
    "aegis_instruction_quarantine_receipt.json",
    "aegis_model_candidate_gate_failure_receipt.json",
    "aegis_action_firewall_failure_receipt.json",
]
BOUNDARY_REFS = [
    "aegis_admission_non_authority_boundary.json",
    "aegis_source_scope_consent_non_authority_boundary.json",
    "aegis_grounding_binding_non_authority_boundary.json",
    "aegis_instruction_quarantine_non_authority_boundary.json",
    "aegis_model_candidate_gate_non_authority_boundary.json",
    "aegis_action_firewall_non_authority_boundary.json",
]
CHAIN_ORDER = PACKET_REFS + RECEIPT_REFS + BOUNDARY_REFS


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _role(ref: str) -> str:
    if ref in PACKET_REFS:
        return "packet"
    if ref in RECEIPT_REFS:
        return "receipt"
    return "boundary"


def _safe_export_ref(export_ref: str) -> bool:
    path = Path(export_ref)
    return "://" not in export_ref and not path.is_absolute() and ".." not in path.parts


def _base_manifest(*, bridge_root: Path, scenario_id: str, export_ref: str) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_receipt_chain_export_manifest.v1",
        "source_phase": AEGIS_RECEIPT_CHAIN_EXPORT_PHASE,
        "export_manifest_status": "reject_fail_closed",
        "scenario_id": scenario_id,
        "export_ref": export_ref,
        "bridge_root_ref": str(bridge_root),
        "chain_row_count": 0,
        "packet_row_count": 0,
        "receipt_row_count": 0,
        "boundary_row_count": 0,
        "required_packet_count": len(PACKET_REFS),
        "missing_required_packets": [],
        "chain_rows": [],
        "chain_sha256": None,
        "chain_order": CHAIN_ORDER,
        "reason_codes": [],
        "controls_required": [],
        "human_review_required": False,
        "local_manifest_written": False,
        **RECEIPT_CHAIN_EXPORT_FALSE_FLAGS,
        "non_authority_boundary": RECEIPT_CHAIN_EXPORT_NON_AUTHORITY_BOUNDARY,
        "blocked_claims": RECEIPT_CHAIN_EXPORT_BLOCKED_CLAIMS,
        "allowed_claim": RECEIPT_CHAIN_EXPORT_ALLOWED_CLAIM,
    }


def _finish(manifest: dict[str, Any], *, status: str, decision: str, reason_codes: list[str], controls: list[str] | None = None) -> dict[str, Any]:
    manifest["export_manifest_status"] = status
    manifest["decision"] = decision
    manifest["reason_codes"] = reason_codes
    manifest["controls_required"] = controls or []
    manifest["human_review_required"] = status in {"export_manifest_completed_with_failures", "hold_for_human_review", "alarm_requires_elevated_review"}
    return manifest


def _row(*, row_index: int, ref: str, bridge_root: Path) -> tuple[dict[str, Any], bool]:
    path = bridge_root / ref
    present = path.exists()
    schema = None
    source_phase = None
    non_authority_preserved = ref in BOUNDARY_REFS
    malformed = False
    if present:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            schema = data.get("schema") if isinstance(data, dict) else None
            source_phase = data.get("source_phase") if isinstance(data, dict) else None
            if isinstance(data, dict) and ("non_authority" in ref or "non_authority_boundary" in data or "non_authority_boundaries" in data):
                non_authority_preserved = True
        except json.JSONDecodeError:
            malformed = True
    return {
        "row_index": row_index,
        "artifact_ref": ref,
        "artifact_role": _role(ref),
        "artifact_required": ref in PACKET_REFS or ref in BOUNDARY_REFS,
        "artifact_present": present,
        "artifact_sha256": sha256_file(path) if present else None,
        "artifact_schema": schema,
        "source_phase": source_phase,
        "upstream_ref": CHAIN_ORDER[row_index - 2] if row_index > 1 else None,
        "downstream_ref": CHAIN_ORDER[row_index] if row_index < len(CHAIN_ORDER) else None,
        "non_authority_boundary_preserved": non_authority_preserved,
        "accepted_evidence_authority_granted": False,
        "final_answer_authority_granted": False,
        "truth_certification_emitted": False,
    }, malformed


def build_aegis_receipt_chain_export_failure_receipt(*, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "coherencelattice.aegis_receipt_chain_export_failure_receipt.v1",
        "source_phase": AEGIS_RECEIPT_CHAIN_EXPORT_PHASE,
        "export_failure_receipt_status": "completed",
        "scenario_id": manifest["scenario_id"],
        "export_ref": manifest["export_ref"],
        "decision": manifest["decision"],
        "reason_codes": list(manifest["reason_codes"]),
        "missing_required_packets": list(manifest["missing_required_packets"]),
        "no_external_export": True,
        "no_provider_call": True,
        "no_network_call": True,
        "no_tool_execution": True,
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
        "no_model_output_generated": True,
        "no_action_performed": True,
        "no_final_answer_authority": True,
        "no_accepted_evidence_authority": True,
        "human_review_required": True,
    }


def build_aegis_receipt_chain_export(*, bridge_root: str | Path, scenario_id: str, export_ref: str = "aegis_receipt_chain_export_manifest.json", expected_chain_sha256: str | None = None) -> dict:
    bridge = Path(bridge_root)
    manifest = _base_manifest(bridge_root=bridge, scenario_id=scenario_id, export_ref=export_ref)
    if not _safe_export_ref(export_ref):
        return _finish(manifest, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["non_local_export_rejected", "fail_closed_no_external_export"])

    rows = []
    malformed_refs = []
    for idx, ref in enumerate(CHAIN_ORDER, start=1):
        row, malformed = _row(row_index=idx, ref=ref, bridge_root=bridge)
        if malformed:
            malformed_refs.append(ref)
        if row["artifact_present"] or row["artifact_required"]:
            rows.append(row)

    missing_packets = [row["artifact_ref"] for row in rows if row["artifact_role"] == "packet" and row["artifact_required"] and not row["artifact_present"]]
    missing_boundaries = [row["artifact_ref"] for row in rows if row["artifact_role"] == "boundary" and row["artifact_required"] and not row["artifact_present"]]
    manifest["chain_rows"] = rows
    manifest["chain_row_count"] = len(rows)
    manifest["packet_row_count"] = sum(row["artifact_role"] == "packet" for row in rows)
    manifest["receipt_row_count"] = sum(row["artifact_role"] == "receipt" and row["artifact_present"] for row in rows)
    manifest["boundary_row_count"] = sum(row["artifact_role"] == "boundary" for row in rows)
    manifest["missing_required_packets"] = missing_packets
    manifest["chain_sha256"] = _canonical_sha(rows)

    if missing_packets:
        manifest = _finish(manifest, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_required_packet", "fail_closed_no_export_manifest"])
    elif missing_boundaries:
        manifest["missing_required_packets"] = missing_boundaries
        manifest = _finish(manifest, status="reject_fail_closed", decision="reject_fail_closed", reason_codes=["missing_boundary", "fail_closed_no_export_manifest"])
    elif malformed_refs:
        manifest["missing_required_packets"] = malformed_refs
        manifest = _finish(manifest, status="hold_for_human_review", decision="hold_for_human_review", reason_codes=["malformed_packet", "human_review_required"], controls=["repair_malformed_artifact"])
    elif expected_chain_sha256 is not None and expected_chain_sha256 != manifest["chain_sha256"]:
        manifest = _finish(manifest, status="alarm_requires_elevated_review", decision="alarm_requires_elevated_review", reason_codes=["hash_mismatch", "elevated_review_required"])
    elif manifest["receipt_row_count"] > 0:
        manifest = _finish(manifest, status="export_manifest_completed_with_failures", decision="allow_with_controls", reason_codes=["receipt_chain_export_completed_with_failure_receipts"], controls=["preserve_failure_receipts", "human_review_available"])
    else:
        manifest = _finish(manifest, status="export_manifest_completed", decision="allow", reason_codes=["receipt_chain_export_completed"])

    out = bridge / export_ref
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["local_manifest_written"] = True
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if manifest["decision"] in {"hold_for_human_review", "reject_fail_closed", "alarm_requires_elevated_review"}:
        receipt = build_aegis_receipt_chain_export_failure_receipt(manifest=manifest)
        (bridge / RECEIPT_CHAIN_EXPORT_FAILURE_RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return manifest
