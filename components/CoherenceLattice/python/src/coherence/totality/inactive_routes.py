"""Typed fail-closed postures for deliberately inactive totality routes."""

from __future__ import annotations

from typing import Any

from .errors import ValidationError


INACTIVE_ROUTE_RECEIPT_SCHEMA = "uvlm.coherence.totality.inactive_route_receipt.v1"
INACTIVE_ROUTE_EFFECTS = (
    "candidate_mutation_performed",
    "source_mutation_performed",
    "sophia_audit_manufactured",
    "memory_write_performed",
    "canonization_performed",
    "network_access_performed",
    "external_action_performed",
)
_ROUTES = {
    "OMEGA": {
        "status": "NOT_APPLICABLE_NORMAL_ROUTE_NO_REFERENCE",
        "reason_codes": ["OMEGA_NOT_REFERENCED_BY_NORMAL_TOTALITY_ROUTE"],
        "stop_reason_packet_required": False,
    },
    "RETROSYNTHESIS": {
        "status": "CONTRACTED_AND_DORMANT",
        "reason_codes": ["RETROSYNTHESIS_ACTIVE_ROUTE_UNREACHABLE"],
        "stop_reason_packet_required": False,
    },
}


def inactive_route_receipt(route_id: str) -> dict[str, Any]:
    """Return explicit nonauthority evidence without activating the route."""

    try:
        contract = _ROUTES[route_id]
    except KeyError as exc:
        raise ValidationError("INACTIVE_ROUTE_ID_INVALID") from exc
    return {
        "schema_id": INACTIVE_ROUTE_RECEIPT_SCHEMA,
        "route_id": route_id,
        "status": contract["status"],
        "reason_codes": list(contract["reason_codes"]),
        "normal_route_reference_observed": False,
        "active_route_reachable": False,
        "output_reentry_performed": False,
        "stop_reason_packet_required": contract["stop_reason_packet_required"],
        "effects": dict.fromkeys(INACTIVE_ROUTE_EFFECTS, False),
        "authority_effect": "NONE",
    }


def validate_inactive_route_receipt(value: Any) -> dict[str, Any]:
    """Reject any mutation away from the exact registered dormant posture."""

    if not isinstance(value, dict) or not isinstance(value.get("route_id"), str):
        raise ValidationError("INACTIVE_ROUTE_RECEIPT_INVALID")
    expected = inactive_route_receipt(value["route_id"])
    if value != expected:
        raise ValidationError("INACTIVE_ROUTE_RECEIPT_INVALID")
    return dict(value)
