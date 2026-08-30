"""Separately consented, append-only PMR reference lifecycle with no writes."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import re
from typing import Any, Mapping

from .canonical import require_exact_keys, require_identifier, require_sha256, validate_unicode_text
from .errors import ValidationError

PMR_CONSENT_SCHEMA = "uvlm.pmr.totality.consent.v1"
PMR_EVENT_SCHEMA = "uvlm.pmr.totality.reference_event.v1"
PMR_RECEIPT_SCHEMA = "uvlm.pmr.totality.receipt.v1"
_CONSENT_KEYS = {
    "schema_id", "consent_id", "run_id", "candidate_id", "logical_time", "decision", "scope",
    "quota_bytes", "expires_logical_time", "training_allowed", "federation_allowed", "authority_effect",
}
_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,9})?Z$"
)


def _logical_time(value: Any, path: str) -> str:
    validate_unicode_text(value, path, allow_newlines=False)
    if not value or len(value) > 128:
        raise ValidationError(f"PMR_LOGICAL_TIME_INVALID:{path}")
    return value


def _utc_instant(value: Any, path: str) -> tuple[datetime, int]:
    logical_time = _logical_time(value, path)
    if _RFC3339_UTC.fullmatch(logical_time) is None:
        raise ValidationError(f"PMR_EXPIRY_TIME_RFC3339_UTC_REQUIRED:{path}")
    try:
        parsed = datetime.fromisoformat(logical_time[:19] + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"PMR_EXPIRY_TIME_INVALID:{path}") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValidationError(f"PMR_EXPIRY_TIME_UTC_REQUIRED:{path}")
    fraction = logical_time[20:-1] if len(logical_time) > 20 else ""
    nanoseconds = int(fraction.ljust(9, "0")) if fraction else 0
    return parsed, nanoseconds


def build_consent_packet(
    *,
    consent_id: str,
    run_id: str,
    candidate_id: str,
    logical_time: str,
    decision: str,
    quota_bytes: int = 1_048_576,
    expires_logical_time: str | None = None,
) -> dict[str, Any]:
    if decision not in {"GRANT", "DENY"}:
        raise ValidationError("PMR_CONSENT_DECISION_INVALID")
    if isinstance(quota_bytes, bool) or not isinstance(quota_bytes, int) or not 1 <= quota_bytes <= 100_000_000:
        raise ValidationError("PMR_CONSENT_QUOTA_INVALID")
    logical_time = _logical_time(logical_time, "$.logical_time")
    if expires_logical_time is not None:
        issued = _utc_instant(logical_time, "$.logical_time")
        expires = _utc_instant(expires_logical_time, "$.expires_logical_time")
        if expires <= issued:
            raise ValidationError("PMR_EXPIRY_NOT_AFTER_CONSENT")
    return {
        "schema_id": PMR_CONSENT_SCHEMA,
        "consent_id": require_identifier(consent_id, "$.consent_id"),
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "logical_time": logical_time,
        "decision": decision,
        "scope": "PROVENANCE_REFERENCE_ONLY",
        "quota_bytes": quota_bytes,
        "expires_logical_time": expires_logical_time,
        "training_allowed": False,
        "federation_allowed": False,
        "authority_effect": "NONE",
    }


def validate_consent_packet(value: Any) -> dict[str, Any]:
    require_exact_keys(value, required=_CONSENT_KEYS)
    rebuilt = build_consent_packet(
        consent_id=value["consent_id"], run_id=value["run_id"], candidate_id=value["candidate_id"],
        logical_time=value["logical_time"], decision=value["decision"], quota_bytes=value["quota_bytes"],
        expires_logical_time=value["expires_logical_time"],
    )
    if rebuilt != value:
        raise ValidationError("PMR_CONSENT_PACKET_INVALID")
    return rebuilt


def no_write_receipt(*, run_id: str, candidate_id: str, logical_time: str, reason: str) -> dict[str, Any]:
    require_identifier(reason, "$.reason")
    return {
        "schema_id": PMR_RECEIPT_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "logical_time": logical_time,
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": None,
        "consent_status": "NOT_GRANTED",
        "reason_codes": [reason],
        "events": [],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }


class PMRReferenceStore:
    """In-memory reference state; no content copy, reinjection, or training.

    The lifecycle is a contracted/dormant reference implementation. Sophia- or
    human-authorized retention transitions and prior reinjection are not active.
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._consents: dict[str, dict[str, Any]] = {}
        self._lineages: dict[str, dict[str, Any]] = {}

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(row) for row in self._events)

    def _append(self, event_type: str, consent: Mapping[str, Any], lineage_id: str | None, detail: Mapping[str, Any]) -> dict[str, Any]:
        sequence = len(self._events) + 1
        row = {
            "schema_id": PMR_EVENT_SCHEMA,
            "sequence": sequence,
            "logical_time": f"PMR+{sequence:06d}",
            "event_type": event_type,
            "consent_id": consent["consent_id"],
            "run_id": consent["run_id"],
            "candidate_id": consent["candidate_id"],
            "lineage_id": lineage_id,
            "detail": copy.deepcopy(dict(detail)),
            "persistent_write_performed": False,
            "training_used": False,
            "federation_used": False,
            "authority_effect": "NONE",
        }
        self._events.append(row)
        return copy.deepcopy(row)

    def apply_consent(self, packet: Any) -> dict[str, Any]:
        consent = validate_consent_packet(packet)
        if consent["consent_id"] in self._consents:
            raise ValidationError("PMR_CONSENT_ALREADY_RECORDED")
        self._consents[consent["consent_id"]] = {**consent, "active": consent["decision"] == "GRANT"}
        return self._append(
            "CONSENT_GRANTED" if consent["decision"] == "GRANT" else "CONSENT_DENIED",
            consent, None, {"scope": consent["scope"], "quota_bytes": consent["quota_bytes"]},
        )

    def retain_reference(
        self,
        *,
        consent_id: str,
        lineage_id: str,
        artifact_sha256: str,
        referenced_bytes: int,
    ) -> dict[str, Any]:
        consent = self._active(consent_id)
        lineage_id = require_identifier(lineage_id, "$.lineage_id")
        artifact_sha256 = require_sha256(artifact_sha256, "$.artifact_sha256")
        if lineage_id in self._lineages:
            raise ValidationError("PMR_LINEAGE_ALREADY_EXISTS")
        if isinstance(referenced_bytes, bool) or not isinstance(referenced_bytes, int) or referenced_bytes < 0:
            raise ValidationError("PMR_REFERENCED_BYTES_INVALID")
        used = sum(row["referenced_bytes"] for row in self._lineages.values() if row["consent_id"] == consent_id)
        if used + referenced_bytes > consent["quota_bytes"]:
            raise ValidationError("PMR_REFERENCE_QUOTA_EXCEEDED")
        self._lineages[lineage_id] = {
            "lineage_id": lineage_id, "consent_id": consent_id, "artifact_sha256": artifact_sha256,
            "referenced_bytes": referenced_bytes, "status": "ACTIVE", "corrections": [],
        }
        return self._append("REFERENCE_RETAINED", consent, lineage_id, self._lineages[lineage_id])

    def revoke(self, consent_id: str, *, reason: str) -> dict[str, Any]:
        consent = self._active(consent_id)
        require_identifier(reason, "$.reason")
        consent["active"] = False
        for row in self._lineages.values():
            if row["consent_id"] == consent_id and row["status"] == "ACTIVE":
                row["status"] = "REVOKED"
        return self._append("CONSENT_REVOKED", consent, None, {"reason": reason})

    def correct(self, consent_id: str, lineage_id: str, *, replacement_sha256: str) -> dict[str, Any]:
        consent = self._active(consent_id)
        lineage = self._lineage(consent_id, lineage_id)
        replacement = require_sha256(replacement_sha256, "$.replacement_sha256")
        lineage["corrections"].append(replacement)
        lineage["artifact_sha256"] = replacement
        return self._append("REFERENCE_CORRECTED", consent, lineage_id, {"replacement_sha256": replacement})

    def delete(self, consent_id: str, lineage_id: str, *, reason: str) -> dict[str, Any]:
        consent = self._active(consent_id)
        lineage = self._lineage(consent_id, lineage_id)
        require_identifier(reason, "$.reason")
        lineage["status"] = "DELETED_TOMBSTONE"
        return self._append("REFERENCE_DELETED", consent, lineage_id, {"reason": reason})

    def retrieve(self, lineage_id: str, *, logical_time: str) -> dict[str, Any]:
        lineage_id = require_identifier(lineage_id, "$.lineage_id")
        logical_time = _logical_time(logical_time, "$.retrieval_logical_time")
        lineage = self._lineages.get(lineage_id)
        if lineage is None:
            raise ValidationError("PMR_LINEAGE_NOT_FOUND")
        consent = self._consents.get(lineage["consent_id"])
        if consent is None or consent.get("active") is not True or consent.get("decision") != "GRANT":
            raise ValidationError("PMR_ACTIVE_CONSENT_REQUIRED")
        if lineage.get("status") != "ACTIVE":
            raise ValidationError("PMR_ACTIVE_LINEAGE_REQUIRED")
        expiry = consent.get("expires_logical_time")
        if expiry is not None:
            retrieved = _utc_instant(logical_time, "$.retrieval_logical_time")
            if retrieved >= _utc_instant(expiry, "$.expires_logical_time"):
                raise ValidationError("PMR_CONSENT_EXPIRED")
        return {
            **copy.deepcopy(lineage),
            "retrieval_logical_time": logical_time,
            "active_consent_verified": True,
            "content_stored": False,
            "training_eligible": False,
        }

    def receipt(self, consent_id: str) -> dict[str, Any]:
        consent = self._consents.get(consent_id)
        if consent is None:
            raise ValidationError("PMR_CONSENT_NOT_FOUND")
        events = [copy.deepcopy(row) for row in self._events if row["consent_id"] == consent_id]
        retained = any(row["event_type"] == "REFERENCE_RETAINED" for row in events)
        return {
            "schema_id": PMR_RECEIPT_SCHEMA,
            "run_id": consent["run_id"], "candidate_id": consent["candidate_id"],
            "logical_time": consent["logical_time"], "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
            "consent_id": consent_id, "consent_status": "ACTIVE" if consent["active"] else "INACTIVE",
            "reason_codes": ["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"], "events": events,
            "retained": retained, "persistent_bytes_written": 0, "network_used": False,
            "federation_used": False, "training_used": False, "authority_effect": "NONE",
        }

    def _active(self, consent_id: str) -> dict[str, Any]:
        consent = self._consents.get(consent_id)
        if consent is None or consent.get("active") is not True:
            raise ValidationError("PMR_ACTIVE_CONSENT_REQUIRED")
        return consent

    def _lineage(self, consent_id: str, lineage_id: str) -> dict[str, Any]:
        lineage = self._lineages.get(lineage_id)
        if lineage is None or lineage["consent_id"] != consent_id or lineage["status"] != "ACTIVE":
            raise ValidationError("PMR_ACTIVE_LINEAGE_REQUIRED")
        return lineage
