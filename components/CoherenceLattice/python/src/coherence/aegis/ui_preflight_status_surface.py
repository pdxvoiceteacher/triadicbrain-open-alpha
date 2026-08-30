from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from coherence.aegis.policy import (
    AEGIS_UI_PREFLIGHT_STATUS_SURFACE_PHASE,
    UI_PREFLIGHT_STATUS_SURFACE_ALLOWED_CLAIM,
    UI_PREFLIGHT_STATUS_SURFACE_BLOCKED_CLAIMS,
    UI_PREFLIGHT_STATUS_SURFACE_BOUNDARY_NAME,
    UI_PREFLIGHT_STATUS_SURFACE_FAILURE_RECEIPT_NAME,
    UI_PREFLIGHT_STATUS_SURFACE_FALSE_FLAGS,
    UI_PREFLIGHT_STATUS_SURFACE_HTML_NAME,
    UI_PREFLIGHT_STATUS_SURFACE_MARKDOWN_NAME,
    UI_PREFLIGHT_STATUS_SURFACE_NON_AUTHORITY_BOUNDARY,
    UI_PREFLIGHT_STATUS_SURFACE_PACKET_NAME,
)

STATUS_DECISION = {
    "preflight_allowed": ("allow", "ready_for_preview", "Ready for preview", "informational", "rendered"),
    "preflight_allowed_with_controls": ("allow_with_controls", "ready_with_controls", "Ready with controls", "caution", "rendered_with_controls"),
    "hold_for_human_review": ("hold_for_human_review", "review_required", "Human review required", "caution", "rendered_with_controls"),
    "reject_fail_closed": ("reject_fail_closed", "blocked_fail_closed", "Blocked", "blocked", "rendered_fail_closed"),
    "alarm_requires_elevated_review": ("alarm_requires_elevated_review", "elevated_review_required", "Elevated review required", "critical", "rendered_elevated_review"),
}
GENERIC_REASON = "Additional governed review information is available in the receipt."
RUNTIME_CLAIMS = [
    "operation_performed", "tool_execution_performed", "action_performed", "file_write_performed", "file_delete_performed",
    "connector_pull_performed", "connector_push_performed", "provider_runtime_performed", "network_call_performed",
    "memory_write_performed", "atlas_memory_admission_performed", "trace_export_performed", "pmr_federation_performed",
    "package_install_performed", "package_activation_performed", "package_execution_performed", "payment_processing_performed",
    "subscription_billing_performed", "marketplace_download_performed", "model_candidate_created", "model_output_generated",
    "final_answer_authority_granted", "accepted_evidence_authority_granted", "compliance_certification_emitted",
    "audit_pass_claimed", "truth_certification_emitted", "product_release_performed",
]
REASON_MESSAGES = {
    "preflight_allowed": "The local preflight adapter allowed preview eligibility.",
    "preflight_allowed_with_controls": "The local preflight adapter allowed the request with controls.",
    "operation_not_performed": "No operation was performed.",
    "status_decision_mismatch": "The source status and decision do not match the governed mapping.",
    "source_runtime_claim_detected": "The source packet claims a runtime or authority action occurred.",
    "missing_source_failure_receipt": "The source packet is blocked or held but lacks its failure receipt reference.",
    "missing_non_authority_boundary": "The source packet is missing its non-authority boundary.",
    "invalid_preflight_schema": "The source packet schema is invalid for this surface.",
    "invalid_preflight_source_phase": "The source packet phase is invalid for this surface.",
}
CONTROL_MESSAGES = {
    "local_preflight_only": "Treat this status as local preflight presentation only.",
    "human_review_available": "Human review remains available and may be required.",
}
NEXT_STEPS = {
    "ready_for_preview": "Proceed only with local preview display; do not execute operations.",
    "ready_with_controls": "Apply listed controls before local preview or evidence-support review.",
    "review_required": "Send the request to human review.",
    "blocked_fail_closed": "Do not proceed unless a new valid AEGIS preflight packet is produced.",
    "elevated_review_required": "Escalate to elevated review.",
    "surface_error_fail_closed": "Repair the source preflight packet before display.",
}


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _messages(codes: list[str], registry: dict[str, str]) -> list[str]:
    return [registry.get(code, GENERIC_REASON) for code in codes]


def _summary(label: str, category: str) -> str:
    return f"{label} for operation category {category}. No operation was performed by this status surface."


def _base(preflight_packet: dict | None, scenario_id: str) -> dict[str, Any]:
    packet_hash = _canonical_sha(preflight_packet) if isinstance(preflight_packet, dict) else None
    return {
        "schema": "coherencelattice.aegis_ui_preflight_status_surface_packet.v1",
        "source_phase": AEGIS_UI_PREFLIGHT_STATUS_SURFACE_PHASE,
        "surface_status": "surface_error_fail_closed",
        "rendering_outcome": "rendered_fail_closed",
        "scenario_id": scenario_id,
        "source_preflight_schema": preflight_packet.get("schema") if isinstance(preflight_packet, dict) else None,
        "source_preflight_phase": preflight_packet.get("source_phase") if isinstance(preflight_packet, dict) else None,
        "source_preflight_status": preflight_packet.get("preflight_status") if isinstance(preflight_packet, dict) else None,
        "source_preflight_decision": preflight_packet.get("decision") if isinstance(preflight_packet, dict) else None,
        "source_preflight_packet_sha256": packet_hash,
        "requested_operation_ref": preflight_packet.get("requested_operation_ref") if isinstance(preflight_packet, dict) else None,
        "operation_category": preflight_packet.get("operation_category") if isinstance(preflight_packet, dict) else None,
        "display_label": "Surface error: blocked fail-closed",
        "display_summary": "Surface error: blocked fail-closed. No operation was performed by this status surface.",
        "display_severity": "blocked",
        "aria_status_label": "Surface error: blocked fail-closed",
        "reason_codes": [],
        "reason_messages": [],
        "controls_required": [],
        "control_messages": [],
        "next_step_messages": [NEXT_STEPS["surface_error_fail_closed"]],
        "human_review_required": True,
        "failure_receipt_ref": UI_PREFLIGHT_STATUS_SURFACE_FAILURE_RECEIPT_NAME,
        "source_enforcement_failure_receipt_ref": preflight_packet.get("enforcement_failure_receipt_ref") if isinstance(preflight_packet, dict) else None,
        "source_receipt_chain_ref": preflight_packet.get("receipt_chain_ref") if isinstance(preflight_packet, dict) else None,
        "source_receipt_chain_sha256": preflight_packet.get("receipt_chain_sha256") if isinstance(preflight_packet, dict) else None,
        "status_mapping_preserved": False,
        "operation_allowed_displayed": False,
        **UI_PREFLIGHT_STATUS_SURFACE_FALSE_FLAGS,
        "surface_sha256": None,
        "non_authority_boundary": UI_PREFLIGHT_STATUS_SURFACE_NON_AUTHORITY_BOUNDARY,
        "blocked_claims": UI_PREFLIGHT_STATUS_SURFACE_BLOCKED_CLAIMS,
        "allowed_claim": UI_PREFLIGHT_STATUS_SURFACE_ALLOWED_CLAIM,
    }


def _finalize(packet: dict[str, Any]) -> dict[str, Any]:
    clone = dict(packet)
    clone.pop("surface_sha256", None)
    packet["surface_sha256"] = _canonical_sha(clone)
    return packet


def _apply_status(packet: dict[str, Any], *, surface_status: str, label: str, severity: str, outcome: str, reason_codes: list[str], controls: list[str] | None = None, preserved: bool = True) -> dict[str, Any]:
    packet["surface_status"] = surface_status
    packet["rendering_outcome"] = outcome
    packet["display_label"] = label
    packet["display_severity"] = severity
    packet["aria_status_label"] = label
    packet["reason_codes"] = reason_codes
    packet["reason_messages"] = _messages(reason_codes, REASON_MESSAGES)
    packet["controls_required"] = controls or []
    packet["control_messages"] = _messages(packet["controls_required"], CONTROL_MESSAGES)
    packet["next_step_messages"] = [NEXT_STEPS.get(surface_status, NEXT_STEPS["surface_error_fail_closed"])]
    packet["human_review_required"] = surface_status in {"ready_with_controls", "review_required", "blocked_fail_closed", "elevated_review_required", "surface_error_fail_closed"}
    packet["failure_receipt_ref"] = None if surface_status in {"ready_for_preview", "ready_with_controls"} else UI_PREFLIGHT_STATUS_SURFACE_FAILURE_RECEIPT_NAME
    packet["status_mapping_preserved"] = preserved
    packet["operation_allowed_displayed"] = surface_status in {"ready_for_preview", "ready_with_controls"}
    packet["display_summary"] = _summary(label, str(packet.get("operation_category") or "unknown"))
    return _finalize(packet)


def build_preflight_status_surface(*, preflight_packet: dict | None, surface_profile: dict | None = None, scenario_id: str = "allowed_preview_status_surface") -> dict:
    packet = _base(preflight_packet, scenario_id)
    if not isinstance(preflight_packet, dict):
        return _apply_status(packet, surface_status="surface_error_fail_closed", label="Surface error: blocked fail-closed", severity="blocked", outcome="rendered_fail_closed", reason_codes=["missing_preflight_packet"], preserved=False)
    if preflight_packet.get("schema") != "coherencelattice.aegis_local_runtime_enforcement_preflight_packet.v1":
        return _apply_status(packet, surface_status="surface_error_fail_closed", label="Surface error: blocked fail-closed", severity="blocked", outcome="rendered_fail_closed", reason_codes=["invalid_preflight_schema"], preserved=False)
    if preflight_packet.get("source_phase") != "AEGIS-LOCAL-RUNTIME-ENFORCEMENT-ADAPTER-00":
        return _apply_status(packet, surface_status="surface_error_fail_closed", label="Surface error: blocked fail-closed", severity="blocked", outcome="rendered_fail_closed", reason_codes=["invalid_preflight_source_phase"], preserved=False)
    if not isinstance(preflight_packet.get("non_authority_boundary"), dict):
        return _apply_status(packet, surface_status="surface_error_fail_closed", label="Surface error: blocked fail-closed", severity="blocked", outcome="rendered_fail_closed", reason_codes=["missing_non_authority_boundary"], preserved=False)

    status = preflight_packet.get("preflight_status")
    decision = preflight_packet.get("decision")
    if status not in STATUS_DECISION:
        return _apply_status(packet, surface_status="surface_error_fail_closed", label="Surface error: blocked fail-closed", severity="blocked", outcome="rendered_fail_closed", reason_codes=["unknown_preflight_status"], preserved=False)
    expected_decision, surface_status, label, severity, outcome = STATUS_DECISION[status]
    if decision != expected_decision:
        return _apply_status(packet, surface_status="elevated_review_required", label="Elevated review required", severity="critical", outcome="rendered_elevated_review", reason_codes=["status_decision_mismatch"], preserved=False)
    if any(preflight_packet.get(flag) is True for flag in RUNTIME_CLAIMS):
        return _apply_status(packet, surface_status="elevated_review_required", label="Elevated review required", severity="critical", outcome="rendered_elevated_review", reason_codes=["source_runtime_claim_detected"], preserved=False)
    if status in {"hold_for_human_review", "reject_fail_closed", "alarm_requires_elevated_review"} and not preflight_packet.get("enforcement_failure_receipt_ref"):
        return _apply_status(packet, surface_status="elevated_review_required", label="Elevated review required", severity="critical", outcome="rendered_elevated_review", reason_codes=list(preflight_packet.get("reason_codes", [])) + ["missing_source_failure_receipt"], preserved=False)
    return _apply_status(packet, surface_status=surface_status, label=label, severity=severity, outcome=outcome, reason_codes=list(preflight_packet.get("reason_codes", [])), controls=list(preflight_packet.get("controls_required", [])), preserved=True)


def build_preflight_status_surface_failure_receipt(*, surface_packet: dict) -> dict:
    return {
        "schema": "coherencelattice.aegis_ui_preflight_status_surface_failure_receipt.v1",
        "source_phase": AEGIS_UI_PREFLIGHT_STATUS_SURFACE_PHASE,
        "surface_failure_receipt_status": "completed",
        "scenario_id": surface_packet["scenario_id"],
        "surface_status": surface_packet["surface_status"],
        "source_preflight_status": surface_packet.get("source_preflight_status"),
        "source_preflight_decision": surface_packet.get("source_preflight_decision"),
        "reason_codes": list(surface_packet["reason_codes"]),
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


def render_preflight_status_markdown(surface_packet: dict) -> str:
    controls = ", ".join(html.escape(c) for c in surface_packet.get("control_messages", [])) or "None"
    receipts = html.escape(str(surface_packet.get("failure_receipt_ref") or surface_packet.get("source_enforcement_failure_receipt_ref") or "None"))
    return "\n".join([
        "# AEGIS Preflight Status",
        f"**Status:** {html.escape(str(surface_packet['display_label']))}",
        f"**Summary:** {html.escape(str(surface_packet['display_summary']))}",
        f"**Operation category:** {html.escape(str(surface_packet.get('operation_category')))}",
        f"**Controls required:** {controls}",
        f"**Human review required:** {surface_packet.get('human_review_required')}",
        f"**Receipt references:** {receipts}",
        "No operation was performed by this status surface.",
        "This status is an admissibility presentation, not truth, compliance, audit, product, final-answer, or accepted-evidence authority.",
        "",
    ])


def render_preflight_status_html(surface_packet: dict) -> str:
    label = html.escape(str(surface_packet["display_label"]))
    summary = html.escape(str(surface_packet["display_summary"]))
    category = html.escape(str(surface_packet.get("operation_category")))
    controls = html.escape(", ".join(surface_packet.get("control_messages", [])) or "None")
    notice = "This status is an admissibility presentation, not truth, compliance, audit, product, final-answer, or accepted-evidence authority."
    return f"""<!doctype html>
<html lang=\"en\">
<head><meta charset=\"utf-8\"><title>AEGIS Preflight Status</title><style>body{{font-family:system-ui,sans-serif;line-height:1.5}}.status{{border:2px solid currentColor;padding:1rem}}.status strong{{display:block}}</style></head>
<body>
<main>
<h1>AEGIS Preflight Status</h1>
<section class=\"status\" aria-live=\"polite\" aria-label=\"{label}\">
<strong>{label}</strong>
<p>{summary}</p>
<p>Operation category: {category}</p>
<p>Controls required: {controls}</p>
<p>No operation was performed by this status surface.</p>
<p>{html.escape(notice)}</p>
</section>
</main>
</body>
</html>
"""


def write_preflight_status_surface_artifacts(*, bridge_root: str | Path, surface_packet: dict) -> dict:
    root = Path(bridge_root)
    root.mkdir(parents=True, exist_ok=True)
    packet_path = root / UI_PREFLIGHT_STATUS_SURFACE_PACKET_NAME
    md_path = root / UI_PREFLIGHT_STATUS_SURFACE_MARKDOWN_NAME
    html_path = root / UI_PREFLIGHT_STATUS_SURFACE_HTML_NAME
    boundary_path = root / UI_PREFLIGHT_STATUS_SURFACE_BOUNDARY_NAME
    packet_path.write_text(json.dumps(surface_packet, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_preflight_status_markdown(surface_packet), encoding="utf-8")
    html_path.write_text(render_preflight_status_html(surface_packet), encoding="utf-8")
    boundary_path.write_text(json.dumps(UI_PREFLIGHT_STATUS_SURFACE_NON_AUTHORITY_BOUNDARY, indent=2) + "\n", encoding="utf-8")
    receipt_ref = None
    if surface_packet.get("failure_receipt_ref"):
        receipt_ref = UI_PREFLIGHT_STATUS_SURFACE_FAILURE_RECEIPT_NAME
        (root / receipt_ref).write_text(json.dumps(build_preflight_status_surface_failure_receipt(surface_packet=surface_packet), indent=2) + "\n", encoding="utf-8")
    return {
        "local_surface_artifacts_written": True,
        "external_file_write_performed": False,
        "user_file_write_performed": False,
        "packet_ref": str(packet_path),
        "markdown_ref": str(md_path),
        "html_ref": str(html_path),
        "boundary_ref": str(boundary_path),
        "failure_receipt_ref": receipt_ref,
    }
