"""One deterministic, non-authorizing TEL event chronology."""

from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping

from pathlib import PurePosixPath

from .canonical import canonical_jsonl_bytes, require_exact_keys, require_identifier, require_sha256, sha256_bytes, strict_json_loads
from .errors import ValidationError

TEL_EVENT_SCHEMA = "uvlm.coherence.totality.tel_event.v1"
AUDIT_PREFIX_ORDER = (
    "REQUEST_CANONICALIZED",
    "GROUNDING_VERIFIED",
    "RAW_OUTPUT_QUARANTINED",
    "CANDIDATE_CANONICALIZED",
    "CLAIM_EVIDENCE_MAPPED",
    "UCM_PROJECTED",
    "AHA_EVALUATED",
    "COUNTEREXAMPLES_SCANNED",
    "REFERENCE_WAVEFORM_ENCODED",
    "APERTURE_DECIDED",
    "PMR_BOUNDARY_RECORDED",
    "SOPHIA_AUDIT_REQUESTED",
    "ATLAS_ORIENTATION_PENDING",
    "HUMAN_DECISION_PENDING",
    "CORE_BUILD_COMPLETED",
)
FINALIZATION_ORDER = (
    "SOPHIA_AUDIT_COMPLETED",
    "ATLAS_ORIENTATION_COMPLETED",
    "ROUTE_COMPLETED_HUMAN_PENDING",
)
SEALED_ROUTE_ORDER = AUDIT_PREFIX_ORDER + FINALIZATION_ORDER
EXTERNAL_CONTINUATION_ORDER = ("HUMAN_DECISION_RECORDED",)
EVENT_ORDER = SEALED_ROUTE_ORDER + EXTERNAL_CONTINUATION_ORDER
_RANK = {name: index for index, name in enumerate(EVENT_ORDER)}
_IDENTITY_START = {
    "candidate_id": _RANK["CANDIDATE_CANONICALIZED"],
    "audit_id": _RANK["SOPHIA_AUDIT_REQUESTED"],
    "decision_id": _RANK["HUMAN_DECISION_PENDING"],
}
_EVENT_KEYS = {
    "schema_id", "sequence", "logical_time", "event_type", "run_id", "candidate_id",
    "audit_id", "decision_id", "outcome", "payload", "authority_effect",
}


def derive_audit_id(candidate_sha256: str, aperture_sha256: str) -> str:
    """Derive the single audit lineage shared by core and Sophia."""

    candidate = require_sha256(candidate_sha256, "$.candidate_sha256")
    aperture = require_sha256(aperture_sha256, "$.aperture_sha256")
    return "AUDIT-" + sha256_bytes((candidate + aperture).encode("ascii"))[:24]


def derive_decision_id(audit_id: str, run_id: str) -> str:
    audit = require_identifier(audit_id, "$.audit_id")
    run = require_identifier(run_id, "$.run_id")
    return "DECISION-" + sha256_bytes((audit + run).encode("ascii"))[:24]


class TELLedger:
    """Append-only in-memory ledger; callers explicitly persist canonical JSONL."""

    def __init__(self, run_id: str, rows: Iterable[Mapping[str, Any]] = ()) -> None:
        self.run_id = require_identifier(run_id, "$.run_id")
        self._rows: list[dict[str, Any]] = []
        self._failed = False
        for row in rows:
            self._append_validated(copy.deepcopy(dict(row)))

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(row) for row in self._rows)

    def _append_validated(self, row: dict[str, Any]) -> None:
        require_exact_keys(row, required=_EVENT_KEYS)
        if row["schema_id"] != TEL_EVENT_SCHEMA or row["run_id"] != self.run_id or row["authority_effect"] != "NONE":
            raise ValidationError("TEL_EVENT_IDENTITY_OR_AUTHORITY_INVALID")
        if row["sequence"] != len(self._rows) + 1 or row["logical_time"] != f"T+{row['sequence']:06d}":
            raise ValidationError("TEL_SEQUENCE_OR_LOGICAL_TIME_INVALID")
        event_type = row["event_type"]
        if event_type != "STAGE_FAILED" and event_type not in _RANK:
            raise ValidationError("TEL_EVENT_TYPE_INVALID")
        if row["outcome"] not in {"SUCCESS", "HOLD", "REFUSE", "FAILURE", "RECORDED"}:
            raise ValidationError("TEL_OUTCOME_INVALID")
        if not isinstance(row["payload"], dict):
            raise ValidationError("TEL_PAYLOAD_OBJECT_REQUIRED")
        for field in ("candidate_id", "audit_id", "decision_id"):
            if row[field] is not None:
                require_identifier(row[field], f"$.{field}")
        if event_type != "STAGE_FAILED":
            current_rank = _RANK[event_type]
            for field, first_rank in _IDENTITY_START.items():
                expected_present = current_rank >= first_rank
                if (row[field] is not None) is not expected_present:
                    raise ValidationError(f"TEL_{field.upper()}_STAGE_BINDING_INVALID")
        for previous_row in self._rows:
            for field in ("candidate_id", "audit_id", "decision_id"):
                if (
                    previous_row[field] is not None
                    and row[field] is not None
                    and previous_row[field] != row[field]
                ):
                    raise ValidationError(f"TEL_{field.upper()}_LINEAGE_MISMATCH")
        if self._rows:
            previous = self._rows[-1]["event_type"]
            previous_rank = _RANK.get(previous, len(_RANK))
            current_rank = _RANK.get(event_type, len(_RANK))
            if current_rank <= previous_rank:
                raise ValidationError("TEL_EVENT_ORDER_INVALID")
        if self._failed and event_type != "RUN_COMPLETED":
            raise ValidationError("TEL_EVENT_AFTER_FAILURE_PROHIBITED")
        if event_type == "STAGE_FAILED":
            if row["outcome"] != "FAILURE" or set(row["payload"]) != {"stage", "reason_code"}:
                raise ValidationError("TEL_FAILURE_EVENT_INVALID")
            self._failed = True
        if event_type == "HUMAN_DECISION_RECORDED":
            require_exact_keys(
                row["payload"],
                required={
                    "decision_receipt_sha256", "disposition", "external_receipt_path",
                    "parent_sealed_tel_sha256",
                },
                path="$.payload",
            )
            require_sha256(row["payload"]["decision_receipt_sha256"], "$.payload.decision_receipt_sha256")
            require_sha256(row["payload"]["parent_sealed_tel_sha256"], "$.payload.parent_sealed_tel_sha256")
            if row["payload"]["disposition"] not in {"APPROVE", "HOLD", "REJECT", "REPAIR"}:
                raise ValidationError("TEL_HUMAN_DISPOSITION_INVALID")
            external = row["payload"]["external_receipt_path"]
            if (
                not isinstance(external, str) or not external or "\\" in external
                or PurePosixPath(external).is_absolute() or ".." in PurePosixPath(external).parts
            ):
                raise ValidationError("TEL_HUMAN_RECEIPT_PATH_INVALID")
            if (
                row["outcome"] != "RECORDED" or row["candidate_id"] is None
                or row["audit_id"] is None or row["decision_id"] is None
            ):
                raise ValidationError("TEL_HUMAN_EVENT_BINDING_INVALID")
        self._rows.append(row)

    def emit(
        self,
        event_type: str,
        *,
        outcome: str = "SUCCESS",
        payload: Mapping[str, Any] | None = None,
        candidate_id: str | None = None,
        audit_id: str | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        sequence = len(self._rows) + 1
        row = {
            "schema_id": TEL_EVENT_SCHEMA,
            "sequence": sequence,
            "logical_time": f"T+{sequence:06d}",
            "event_type": event_type,
            "run_id": self.run_id,
            "candidate_id": candidate_id,
            "audit_id": audit_id,
            "decision_id": decision_id,
            "outcome": outcome,
            "payload": copy.deepcopy(dict(payload or {})),
            "authority_effect": "NONE",
        }
        self._append_validated(row)
        return copy.deepcopy(row)

    def failure(self, stage: str, reason_code: str, *, candidate_id: str | None = None) -> dict[str, Any]:
        require_identifier(stage, "$.failure.stage")
        require_identifier(reason_code, "$.failure.reason_code")
        return self.emit(
            "STAGE_FAILED",
            outcome="FAILURE",
            payload={"stage": stage, "reason_code": reason_code},
            candidate_id=candidate_id,
        )

    def to_jsonl_bytes(self) -> bytes:
        return canonical_jsonl_bytes(self._rows)


def parse_tel_jsonl(data: bytes) -> TELLedger:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(data.splitlines(), start=1):
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise ValidationError(f"TEL_JSONL_OBJECT_REQUIRED:{number}")
        rows.append(value)
    if not rows:
        raise ValidationError("TEL_LEDGER_EMPTY")
    if data != canonical_jsonl_bytes(rows):
        raise ValidationError("TEL_JSONL_NOT_CANONICAL")
    ledger = TELLedger(rows[0].get("run_id", ""))
    for row in rows:
        ledger._append_validated(row)
    return ledger


def parse_final_route_tel_jsonl(data: bytes) -> TELLedger:
    """Validate either the immutable sealed route or its external human continuation."""

    ledger = parse_tel_jsonl(data)
    order = tuple(row["event_type"] for row in ledger.rows)
    if order not in {SEALED_ROUTE_ORDER, EVENT_ORDER}:
        raise ValidationError("TEL_FINAL_ROUTE_ORDER_INVALID")
    if order == EVENT_ORDER:
        parent_raw = canonical_jsonl_bytes(ledger.rows[:-1])
        final, parent = ledger.rows[-1], ledger.rows[-2]
        if any(final[field] != parent[field] for field in ("candidate_id", "audit_id", "decision_id")):
            raise ValidationError("TEL_HUMAN_LINEAGE_IDENTITY_MISMATCH")
        if final["payload"]["parent_sealed_tel_sha256"] != sha256_bytes(parent_raw):
            raise ValidationError("TEL_HUMAN_PARENT_SEALED_HASH_MISMATCH")
    return ledger


def build_human_decision_continuation(
    sealed_tel_data: bytes,
    *,
    decision_receipt_sha256: str,
    disposition: str,
    external_receipt_path: str,
) -> bytes:
    """Return a 19-row external continuation without mutating sealed bytes."""

    sealed = parse_final_route_tel_jsonl(sealed_tel_data)
    if tuple(row["event_type"] for row in sealed.rows) != SEALED_ROUTE_ORDER:
        raise ValidationError("TEL_HUMAN_CONTINUATION_REQUIRES_SEALED_ROUTE")
    parent = sealed.rows[-1]
    if any(parent[field] is None for field in ("candidate_id", "audit_id", "decision_id")):
        raise ValidationError("TEL_HUMAN_CONTINUATION_PARENT_IDENTITY_MISSING")
    ledger = TELLedger(sealed.run_id, sealed.rows)
    ledger.emit(
        "HUMAN_DECISION_RECORDED",
        outcome="RECORDED",
        candidate_id=parent["candidate_id"],
        audit_id=parent["audit_id"],
        decision_id=parent["decision_id"],
        payload={
            "decision_receipt_sha256": decision_receipt_sha256,
            "disposition": disposition,
            "external_receipt_path": external_receipt_path,
            "parent_sealed_tel_sha256": sha256_bytes(sealed_tel_data),
        },
    )
    result = ledger.to_jsonl_bytes()
    parse_final_route_tel_jsonl(result)
    return result
