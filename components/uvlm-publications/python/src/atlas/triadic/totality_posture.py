"""Fail-closed Atlas orientation for a governed totality run.

Atlas consumes only canonical, file-backed Coherence artifacts and a separately
produced Sophia audit.  It verifies identity and digest bindings, then writes a
deterministic posture packet and a static human-review surface.  It verifies the
raw-free Sonya quarantine receipts but never reads the quarantined provider
bytes and has no memory, publication, deployment, release, or model-invocation
operation.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import tempfile
import unicodedata
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable, Mapping


ATLAS_SCHEMA = "uvlm.atlas.totality.posture_packet.v1"
SOPHIA_SCHEMA = "uvlm.sophia.totality.audit_packet.v1"
REQUEST_SCHEMA = "uvlm.coherence.totality.request_envelope.v1"
CANDIDATE_SCHEMA = "uvlm.sonya.totality.candidate_packet.v1"
OUTPUT_PACKET = "atlas_posture_packet.json"
OUTPUT_REVIEW = "final_review.html"
SEALED_RUN_MARKERS = (
    "run_manifest.json",
    "sealed_artifact_manifest.json",
    "checksums.sha256",
)
MAX_JSON_INPUT_BYTES = 4 * 1024 * 1024
MAX_JSONL_INPUT_BYTES = 16 * 1024 * 1024
MAX_GROUNDING_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024

# This is the exact set independently audited by Sophia.  Atlas accepts no
# substitute path and validates every supplied digest before presentation.
AUDITED_INPUTS = (
    "request.json",
    "grounding/manifest.json",
    "grounding/source.bin",
    "grounding/normalized_source.txt",
    "grounding/segments.jsonl",
    "sonya/quarantine_receipt.json",
    "sonya/quarantine_verification_receipt.json",
    "candidate_packet.json",
    "claim_evidence_map.json",
    "ucm_state.json",
    "projector_receipt.json",
    "residual_refusal.json",
    "aha_result.json",
    "counterexamples.json",
    "reference_waveform.json",
    "pmr_consent.json",
    "pmr_receipt.json",
    "aperture_decision.json",
    "tel_audit_prefix.jsonl",
)
AUDITED_TYPES = {
    "request.json": "request_envelope",
    "grounding/manifest.json": "grounding_manifest",
    "grounding/source.bin": "grounding_source",
    "grounding/normalized_source.txt": "grounding_normalized_source",
    "grounding/segments.jsonl": "grounding_segments",
    "sonya/quarantine_receipt.json": "sonya_quarantine_receipt",
    "sonya/quarantine_verification_receipt.json": "sonya_quarantine_verification_receipt",
    "candidate_packet.json": "candidate_packet",
    "claim_evidence_map.json": "claim_evidence_map",
    "ucm_state.json": "ucm_state",
    "projector_receipt.json": "projector_receipt",
    "residual_refusal.json": "residual_refusal",
    "aha_result.json": "aha_result",
    "counterexamples.json": "counterexamples",
    "reference_waveform.json": "reference_waveform",
    "pmr_consent.json": "pmr_consent",
    "pmr_receipt.json": "pmr_receipt",
    "aperture_decision.json": "aperture_decision",
    "tel_audit_prefix.jsonl": "tel_audit_prefix",
}
OPTIONAL_AUDITED_INPUTS = ("pmr_consent.json",)
JSON_INPUTS = tuple(path for path in AUDITED_INPUTS if path.endswith(".json"))
ATLAS_INPUTS = tuple(path for path in AUDITED_INPUTS if path not in OPTIONAL_AUDITED_INPUTS) + (
    "sophia_audit_packet.json",
)

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
DECISION_MEANINGS = {
    "APPROVE": "Accept this bounded candidate for the stated task only; this does not certify truth or authorize any downstream effect.",
    "HOLD": "Pause this lineage until the identified evidence or contract concern is resolved.",
    "REJECT": "Do not accept this candidate for the stated task; its evidence lineage remains unchanged.",
    "REPAIR": "Request a new Sonya-routed candidate lineage without changing this candidate or Sophia audit.",
}
LIMITATIONS = (
    "Candidate content is model-derived or captured input under review, not a final answer or truth certification.",
    "Evidence identity, exact spans, and deterministic recomputation do not establish that every source assertion is true or sufficient.",
    "Full posterior values are bounded projector outputs, not calibrated real-world probabilities unless separately demonstrated.",
    "Top-k is a display-only view; changing top-k must not change the full posterior, equivalence sets, or disposition.",
    "AHA mappings are hypotheses with disanalogies and falsification criteria, not proof of transfer validity.",
    "Sophia is an independent bounded audit, not final authority; a human decision is still required.",
    "PMR retention requires separate, revocable consent. This route performs no memory write or training.",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_ID = re.compile(r"^AUDIT-[0-9a-f]{24}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRIVATE_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "internal_deliberation",
    "private_reasoning",
    "scratchpad",
    "thinking",
    "raw_model_output",
    "raw_output",
}
_POSITIVE_AUTHORITY_KEYS = {
    "truth_certified",
    "final_answer_authorized",
    "memory_write_authorized",
    "pmr_write_authorized",
    "training_authorized",
    "canonization_authorized",
    "publication_authorized",
    "deployment_authorized",
    "release_authorized",
    "self_approved",
    "governance_approved",
}

# Local frozen copy of the cross-owner Unicode DerivedCoreProperties
# Default_Ignorable_Code_Point profile.  Atlas validates Sophia/upstream bytes
# independently and therefore does not import either owner implementation.
DEFAULT_IGNORABLE_CODE_POINT_PROFILE = (
    "UCD_DERIVED_CORE_PROPERTIES_DEFAULT_IGNORABLE_CODE_POINT_V1"
)
DEFAULT_IGNORABLE_CODE_POINT_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_DEFAULT_IGNORABLE_CODE_POINT_STARTS = tuple(
    start for start, _ in DEFAULT_IGNORABLE_CODE_POINT_RANGES
)


def _is_default_ignorable_code_point(codepoint: int) -> bool:
    index = bisect_right(_DEFAULT_IGNORABLE_CODE_POINT_STARTS, codepoint) - 1
    return (
        index >= 0
        and codepoint <= DEFAULT_IGNORABLE_CODE_POINT_RANGES[index][1]
    )


class TotalityPostureError(ValueError):
    """Stable fail-closed Atlas validation error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise TotalityPostureError(code)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_unicode(value: str, path: str) -> None:
    if unicodedata.normalize("NFC", value) != value:
        _fail(f"UNICODE_NFC_REQUIRED:{path}")
    for character in value:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if character == "\x00" or 0xD800 <= codepoint <= 0xDFFF:
            _fail(f"UNICODE_INVALID:{path}")
        if _is_default_ignorable_code_point(codepoint):
            _fail(f"UNICODE_DEFAULT_IGNORABLE:{path}")
        if category == "Cc" and character not in {"\n", "\t"}:
            _fail(f"UNICODE_CONTROL:{path}")


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"JSON_NONFINITE:{path}")
        return
    if isinstance(value, str):
        _validate_unicode(value, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"JSON_KEY_INVALID:{path}")
            _validate_unicode(key, f"{path}.<key>")
            _validate_json_value(item, f"{path}.{key}")
        return
    _fail(f"JSON_TYPE_INVALID:{path}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            _fail(f"JSON_DUPLICATE_MEMBER:{key}")
        output[key] = value
    return output


def _constant(value: str) -> None:
    _fail(f"JSON_NONFINITE:{value}")


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_json_value(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _parse_json(raw: bytes, artifact: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"JSON_BOM_PROHIBITED:{artifact}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(f"JSON_UTF8_INVALID:{artifact}")
    _validate_unicode(text, artifact)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, TotalityPostureError):
        _fail(f"JSON_INVALID:{artifact}")
    if not isinstance(value, dict):
        _fail(f"JSON_OBJECT_REQUIRED:{artifact}")
    _validate_json_value(value)
    if raw != _canonical_json_bytes(value):
        _fail(f"JSON_NONCANONICAL:{artifact}")
    return value


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _safe_root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or _link_like(path) or path == Path(path.anchor):
        _fail("RUN_ROOT_INVALID")
    try:
        root = path.resolve(strict=True)
    except OSError:
        _fail("RUN_ROOT_INVALID")
    if not root.is_dir():
        _fail("RUN_ROOT_INVALID")
    return root


def _member(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    try:
        cursor = root
        for part in Path(relative).parts:
            cursor /= part
            if _link_like(cursor):
                _fail(f"INPUT_LINK_OR_JUNCTION_PROHIBITED:{relative}")
        if not path.is_file():
            _fail(f"INPUT_UNAVAILABLE:{relative}")
        resolved = path.resolve(strict=True)
    except OSError:
        _fail(f"INPUT_UNAVAILABLE:{relative}")
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"INPUT_OUTSIDE_RUN_ROOT:{relative}")
    return resolved


def _bounded_member_bytes(root: Path, relative: str) -> bytes:
    path = _member(root, relative)
    maximum_bytes = (
        MAX_GROUNDING_INPUT_BYTES
        if relative in {
            "grounding/source.bin",
            "grounding/normalized_source.txt",
        }
        else MAX_JSONL_INPUT_BYTES
        if relative.endswith(".jsonl")
        else MAX_JSON_INPUT_BYTES
    )
    try:
        if path.stat().st_size > maximum_bytes:
            _fail(f"INPUT_SIZE_LIMIT_EXCEEDED:{relative}")
        with path.open("rb") as stream:
            data = stream.read(maximum_bytes + 1)
    except OSError:
        _fail(f"INPUT_UNAVAILABLE:{relative}")
    if len(data) > maximum_bytes:
        _fail(f"INPUT_SIZE_LIMIT_EXCEEDED:{relative}")
    return data


def _load_inputs(root: Path) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    raw = {
        relative: _bounded_member_bytes(root, relative)
        for relative in ATLAS_INPUTS
    }
    for relative in OPTIONAL_AUDITED_INPUTS:
        path = root.joinpath(*relative.split("/"))
        if path.exists() or _link_like(path):
            raw[relative] = _bounded_member_bytes(root, relative)
    if sum(len(payload) for payload in raw.values()) > MAX_TOTAL_INPUT_BYTES:
        _fail("TOTAL_INPUT_SIZE_LIMIT_EXCEEDED")
    objects = {
        relative: _parse_json(raw[relative], relative)
        for relative in JSON_INPUTS
        if relative in raw
    }
    objects["sophia_audit_packet.json"] = _parse_json(
        raw["sophia_audit_packet.json"], "sophia_audit_packet.json"
    )
    for relative in ("grounding/segments.jsonl", "tel_audit_prefix.jsonl"):
        payload = raw[relative]
        if not payload or not payload.endswith(b"\n"):
            _fail(f"JSONL_FINAL_LF_REQUIRED:{relative}")
        for number, line in enumerate(payload.splitlines(keepends=True), start=1):
            _parse_json(line, f"{relative}:{number}")
    try:
        normalized = raw["grounding/normalized_source.txt"].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("GROUNDING_NORMALIZED_UTF8_INVALID")
    _validate_unicode(normalized, "grounding/normalized_source.txt")
    return raw, objects


def _scan_boundaries(value: Any, key: str = "") -> None:
    lowered = key.lower()
    if lowered in _PRIVATE_KEYS:
        _fail("PRIVATE_OR_RAW_CONTENT_PROHIBITED")
    if lowered in _POSITIVE_AUTHORITY_KEYS and value is True:
        _fail("POSITIVE_AUTHORITY_PROHIBITED")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _scan_boundaries(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _scan_boundaries(child, key)


def _need(value: Mapping[str, Any], keys: Iterable[str], artifact: str) -> None:
    missing = sorted(set(keys) - value.keys())
    if missing:
        _fail(f"CONTRACT_FIELDS_MISSING:{artifact}:{','.join(missing)}")


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _false_map(value: Any, artifact: str) -> None:
    if not isinstance(value, dict) or not value or any(item is not False for item in value.values()):
        _fail(f"AUTHORITY_OR_EFFECT_CEILING_INVALID:{artifact}")


def _canonical_hash(value: Any) -> str:
    return _sha256(_canonical_json_bytes(value))


def _expected_digest(
    raw: bytes,
    value: dict[str, Any] | None,
    *,
    canonical_jsonl: bool = False,
) -> dict[str, str | None]:
    canonical = _canonical_hash(value) if value is not None else (_sha256(raw) if canonical_jsonl else None)
    return {"file_sha256": _sha256(raw), "canonical_sha256": canonical}


def _validate_sophia_bindings(
    raw: Mapping[str, bytes], objects: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, str | None]]:
    sophia = objects["sophia_audit_packet.json"]
    _need(
        sophia,
        (
            "schema_id",
            "schema_version",
            "packet_type",
            "producer_repository",
            "audit_id",
            "run_id",
            "logical_time",
            "candidate_id",
            "input_digests",
            "parent_list",
            "disposition",
            "reason_codes",
            "findings",
            "claim_findings",
            "recomputed_checks",
            "requires_human_review",
            "permitted_next_route",
            "return_route",
            "authority_boundary_status",
            "nonauthority",
            "side_effects",
        ),
        "sophia_audit_packet.json",
    )
    if (
        sophia["schema_id"] != SOPHIA_SCHEMA
        or sophia["schema_version"] != "1.0"
        or sophia["packet_type"] != "sophia_totality_audit_packet"
        or sophia["producer_repository"] != "pdxvoiceteacher/Sophia"
    ):
        _fail("SOPHIA_IDENTITY_INVALID")
    if not isinstance(sophia["audit_id"], str) or not _AUDIT_ID.fullmatch(sophia["audit_id"]):
        _fail("SOPHIA_AUDIT_ID_INVALID")
    disposition = sophia["disposition"]
    if disposition not in {"PASS", "HOLD", "REJECT"}:
        _fail("SOPHIA_DISPOSITION_INVALID")
    expected_route = "atlas_rejection_explanation_only" if disposition == "REJECT" else "atlas_posture_only"
    if sophia["requires_human_review"] is not True or sophia["permitted_next_route"] != expected_route:
        _fail("SOPHIA_ROUTE_INVALID")
    reason_codes = sophia["reason_codes"]
    if (
        not isinstance(reason_codes, list)
        or not all(isinstance(item, str) and item for item in reason_codes)
        or reason_codes != sorted(set(reason_codes))
    ):
        _fail("SOPHIA_REASON_CODES_INVALID")
    if not isinstance(sophia["findings"], list) or not isinstance(sophia["claim_findings"], list):
        _fail("SOPHIA_FINDINGS_INVALID")
    finding_codes: list[str] = []
    severities: list[str] = []
    for finding in sophia["findings"]:
        if (
            not isinstance(finding, dict)
            or set(finding) != {"code", "severity", "artifact", "detail"}
            or not all(isinstance(finding[name], str) and finding[name] for name in finding)
            or finding["severity"] not in {"HOLD", "REJECT"}
        ):
            _fail("SOPHIA_FINDINGS_INVALID")
        finding_codes.append(finding["code"])
        severities.append(finding["severity"])
    derived_disposition = (
        "REJECT" if "REJECT" in severities else ("HOLD" if severities else "PASS")
    )
    expected_codes = sorted(set(finding_codes)) or ["BOUNDED_AUDIT_CRITERIA_MET"]
    if disposition != derived_disposition or reason_codes != expected_codes:
        _fail("SOPHIA_FINDING_DISPOSITION_MISMATCH")
    expected_return_route = {
        "PASS": {
            "route": "NONE",
            "destination": "NONE",
            "status": "NOT_REQUIRED",
            "reason_codes": [],
        },
        "HOLD": {
            "route": "CLARIFY",
            "destination": "COHERENCELATTICE",
            "status": "REQUESTED_NOT_EXECUTED",
            "reason_codes": reason_codes,
        },
        "REJECT": {
            "route": "REPAIR",
            "destination": "SONYA_OR_COHERENCELATTICE",
            "status": "REQUESTED_NOT_EXECUTED",
            "reason_codes": reason_codes,
        },
    }[disposition]
    return_route = sophia["return_route"]
    if (
        not isinstance(return_route, dict)
        or set(return_route)
        != {
            "route",
            "destination",
            "status",
            "reason_codes",
            "candidate_mutation_performed",
            "source_mutation_performed",
            "automatic_rerun_performed",
            "authority_effect",
        }
        or any(return_route.get(key) != value for key, value in expected_return_route.items())
        or return_route.get("candidate_mutation_performed") is not False
        or return_route.get("source_mutation_performed") is not False
        or return_route.get("automatic_rerun_performed") is not False
        or return_route.get("authority_effect") != "NONE"
    ):
        _fail("SOPHIA_RETURN_ROUTE_INVALID")
    if not isinstance(sophia["recomputed_checks"], dict):
        _fail("SOPHIA_RECOMPUTED_CHECKS_INVALID")
    if sophia["authority_boundary_status"] not in {"BOUNDED", "REJECTED"}:
        _fail("SOPHIA_AUTHORITY_STATUS_INVALID")
    expected_authority_status = (
        "REJECTED"
        if "AUTHORITY_OR_PRIVATE_REASONING_BOUNDARY_VIOLATION" in reason_codes
        else "BOUNDED"
    )
    if sophia["authority_boundary_status"] != expected_authority_status:
        _fail("SOPHIA_AUTHORITY_STATUS_INVALID")
    _false_map(sophia["nonauthority"], "Sophia nonauthority")
    _false_map(sophia["side_effects"], "Sophia side_effects")

    expected = {
        relative: (
            _expected_digest(
                raw[relative],
                objects.get(relative),
                canonical_jsonl=relative.endswith(".jsonl"),
            )
            if relative in raw
            else {"file_sha256": None, "canonical_sha256": None}
        )
        for relative in AUDITED_INPUTS
    }
    if sophia["input_digests"] != expected:
        _fail("SOPHIA_INPUT_DIGEST_MISMATCH")
    parents = sophia["parent_list"]
    if (
        not isinstance(parents, list)
        or len(parents) != len(AUDITED_INPUTS)
        or [item.get("path") if isinstance(item, dict) else None for item in parents]
        != list(AUDITED_INPUTS)
    ):
        _fail("SOPHIA_PARENT_LIST_INVALID")
    by_path: dict[str, dict[str, Any]] = {}
    for parent in parents:
        if not isinstance(parent, dict) or parent.get("path") in by_path:
            _fail("SOPHIA_PARENT_LIST_INVALID")
        by_path[parent.get("path")] = parent
    for relative, digests in expected.items():
        parent = by_path.get(relative)
        if parent is None or parent.get("file_sha256") != digests["file_sha256"]:
            _fail("SOPHIA_PARENT_LIST_INVALID")
        canonical = digests.get("canonical_sha256")
        if set(parent) != {"artifact_type", "path", "file_sha256", "canonical_sha256"}:
            _fail("SOPHIA_PARENT_LIST_INVALID")
        if parent["artifact_type"] != AUDITED_TYPES[relative]:
            _fail("SOPHIA_PARENT_LIST_INVALID")
        if parent.get("canonical_sha256") != canonical:
            _fail("SOPHIA_PARENT_LIST_INVALID")
    return expected


def _validate_pmr_receipt(
    pmr: Mapping[str, Any],
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    run_id: str,
    logical_time: str,
) -> None:
    """Validate the complete no-write PMR reference lifecycle.

    A separately consented reference lifecycle is valid input to Atlas even
    though Atlas itself performs no retention.  The receipt may describe only
    append-only reference metadata; content persistence, network, federation,
    and training remain prohibited.
    """

    receipt_keys = {
        "schema_id",
        "run_id",
        "candidate_id",
        "logical_time",
        "mode",
        "consent_id",
        "consent_status",
        "reason_codes",
        "events",
        "retained",
        "persistent_bytes_written",
        "network_used",
        "federation_used",
        "training_used",
        "authority_effect",
    }
    if set(pmr) != receipt_keys:
        _fail("PMR_RECEIPT_CONTRACT_INVALID")
    if (
        pmr["schema_id"] != "uvlm.pmr.totality.receipt.v1"
        or pmr["run_id"] != run_id
        or pmr["candidate_id"] != candidate["candidate_id"]
        or pmr["logical_time"] != logical_time
    ):
        _fail("PMR_RUN_BINDING_MISMATCH")
    reason_codes = pmr["reason_codes"]
    if (
        pmr["mode"] != "NO_WRITE_REFERENCE_IMPLEMENTATION"
        or not isinstance(reason_codes, list)
        or not reason_codes
        or not all(isinstance(code, str) and _IDENTIFIER.fullmatch(code) for code in reason_codes)
        or reason_codes != sorted(set(reason_codes))
        or not isinstance(pmr["events"], list)
        or not isinstance(pmr["retained"], bool)
        or pmr["persistent_bytes_written"] != 0
        or pmr["network_used"] is not False
        or pmr["federation_used"] is not False
        or pmr["training_used"] is not False
        or pmr["authority_effect"] != "NONE"
    ):
        _fail("PMR_NO_WRITE_POSTURE_INVALID")

    consent_id = pmr["consent_id"]
    events = pmr["events"]
    if consent_id is None:
        if pmr["consent_status"] != "NOT_GRANTED" or events != [] or pmr["retained"] is not False:
            _fail("PMR_NO_WRITE_POSTURE_INVALID")
        return
    if (
        not isinstance(consent_id, str)
        or not _IDENTIFIER.fullmatch(consent_id)
        or pmr["consent_status"] not in {"ACTIVE", "INACTIVE"}
        or request.get("retention_requested") is not True
        or not events
    ):
        _fail("PMR_CONSENT_LIFECYCLE_INVALID")

    event_keys = {
        "schema_id",
        "sequence",
        "logical_time",
        "event_type",
        "consent_id",
        "run_id",
        "candidate_id",
        "lineage_id",
        "detail",
        "persistent_write_performed",
        "training_used",
        "federation_used",
        "authority_effect",
    }
    allowed_events = {
        "CONSENT_GRANTED",
        "CONSENT_DENIED",
        "REFERENCE_RETAINED",
        "CONSENT_REVOKED",
        "REFERENCE_CORRECTED",
        "REFERENCE_DELETED",
    }
    active_lineages: set[str] = set()
    retained_seen = False
    revoked = False
    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or set(event) != event_keys:
            _fail("PMR_EVENT_CONTRACT_INVALID")
        event_type = event["event_type"]
        lineage_id = event["lineage_id"]
        if (
            event["schema_id"] != "uvlm.pmr.totality.reference_event.v1"
            or event["sequence"] != sequence
            or event["logical_time"] != f"PMR+{sequence:06d}"
            or event_type not in allowed_events
            or event["consent_id"] != consent_id
            or event["run_id"] != run_id
            or event["candidate_id"] != candidate["candidate_id"]
            or not isinstance(event["detail"], dict)
            or event["persistent_write_performed"] is not False
            or event["training_used"] is not False
            or event["federation_used"] is not False
            or event["authority_effect"] != "NONE"
        ):
            _fail("PMR_EVENT_CONTRACT_INVALID")
        if sequence == 1:
            if event_type not in {"CONSENT_GRANTED", "CONSENT_DENIED"} or lineage_id is not None:
                _fail("PMR_CONSENT_LIFECYCLE_INVALID")
            if event_type == "CONSENT_DENIED" and (len(events) != 1 or pmr["consent_status"] != "INACTIVE"):
                _fail("PMR_CONSENT_LIFECYCLE_INVALID")
            continue
        if revoked:
            _fail("PMR_EVENT_AFTER_REVOCATION")
        if event_type == "CONSENT_REVOKED":
            if lineage_id is not None:
                _fail("PMR_CONSENT_LIFECYCLE_INVALID")
            revoked = True
            active_lineages.clear()
            continue
        if not isinstance(lineage_id, str) or not _IDENTIFIER.fullmatch(lineage_id):
            _fail("PMR_LINEAGE_ID_INVALID")
        if event_type == "REFERENCE_RETAINED":
            if lineage_id in active_lineages:
                _fail("PMR_LINEAGE_DUPLICATE")
            active_lineages.add(lineage_id)
            retained_seen = True
        elif event_type in {"REFERENCE_CORRECTED", "REFERENCE_DELETED"}:
            if lineage_id not in active_lineages:
                _fail("PMR_LINEAGE_EVENT_WITHOUT_ACTIVE_REFERENCE")
            if event_type == "REFERENCE_DELETED":
                active_lineages.remove(lineage_id)
        else:
            _fail("PMR_CONSENT_LIFECYCLE_INVALID")
    expected_status = "INACTIVE" if events[0]["event_type"] == "CONSENT_DENIED" or revoked else "ACTIVE"
    if pmr["consent_status"] != expected_status or pmr["retained"] is not retained_seen:
        _fail("PMR_CONSENT_LIFECYCLE_INVALID")


def _validate_contracts(
    raw: Mapping[str, bytes], objects: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    for value in objects.values():
        _scan_boundaries(value)
    request = objects["request.json"]
    candidate = objects["candidate_packet.json"]
    sophia = objects["sophia_audit_packet.json"]
    claim_map = objects["claim_evidence_map.json"]
    pmr = objects["pmr_receipt.json"]
    _need(request, ("schema_id", "run_id", "logical_time", "user_input"), "request.json")
    _need(
        candidate,
        (
            "schema_id",
            "candidate_id",
            "run_id",
            "logical_time",
            "request_sha256",
            "answer",
            "uncertainty",
            "claims",
            "candidate_not_final_answer",
            "model_output_not_authority",
            "not_truth_certification",
            "not_memory_authorization",
            "not_training_authorization",
            "not_publication_authorization",
            "not_deployment_authority",
            "not_release_authorization",
            "human_review_required",
        ),
        "candidate_packet.json",
    )
    if request["schema_id"] != REQUEST_SCHEMA or candidate["schema_id"] != CANDIDATE_SCHEMA:
        _fail("TOTALITY_SCHEMA_PAIR_INVALID")
    run_id = request["run_id"]
    logical_time = request["logical_time"]
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(logical_time, str)
        or not logical_time
        or candidate["run_id"] != run_id
        or candidate["logical_time"] != logical_time
        or sophia["run_id"] != run_id
        or sophia["logical_time"] != logical_time
        or sophia["candidate_id"] != candidate["candidate_id"]
    ):
        _fail("RUN_IDENTITY_MISMATCH")
    if candidate["request_sha256"] != _canonical_hash(request):
        _fail("CANDIDATE_REQUEST_BINDING_MISMATCH")
    nonauthority_flags = (
        "candidate_not_final_answer",
        "model_output_not_authority",
        "not_truth_certification",
        "not_memory_authorization",
        "not_training_authorization",
        "not_publication_authorization",
        "not_deployment_authority",
        "not_release_authorization",
        "human_review_required",
    )
    if any(candidate[name] is not True for name in nonauthority_flags):
        _fail("CANDIDATE_NONAUTHORITY_INVALID")
    if not isinstance(candidate["claims"], list) or not candidate["claims"]:
        _fail("CANDIDATE_CLAIMS_INVALID")
    claim_keys = {
        "claim_id",
        "text",
        "answer_start",
        "answer_end",
        "candidate_evidence_references",
    }
    reference_keys = {
        "source_sha256",
        "segment_id",
        "segment_sha256",
        "source_span",
        "exact_excerpt_sha256",
        "claim_text_sha256",
        "candidate_relation",
    }
    span_keys = {"char_start", "char_end", "byte_start", "byte_end"}
    candidate_ids: list[str] = []
    for claim_index, claim in enumerate(candidate["claims"]):
        if not isinstance(claim, dict) or set(claim) != claim_keys:
            _fail("CANDIDATE_CLAIMS_INVALID")
        claim_id = claim["claim_id"]
        start, end = claim["answer_start"], claim["answer_end"]
        references = claim["candidate_evidence_references"]
        if (
            not isinstance(claim_id, str)
            or not _IDENTIFIER.fullmatch(claim_id)
            or claim_id in candidate_ids
            or not isinstance(claim["text"], str)
            or not claim["text"]
            or isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(candidate["answer"])
            or candidate["answer"][start:end] != claim["text"]
            or not isinstance(references, list)
            or len(references) > 100
        ):
            _fail("CANDIDATE_CLAIMS_INVALID")
        reference_identities: set[tuple[Any, ...]] = set()
        for reference in references:
            span = reference.get("source_span") if isinstance(reference, dict) else None
            if (
                not isinstance(reference, dict)
                or set(reference) != reference_keys
                or not _digest(reference["source_sha256"])
                or not isinstance(reference["segment_id"], str)
                or not _IDENTIFIER.fullmatch(reference["segment_id"])
                or not _digest(reference["segment_sha256"])
                or not _digest(reference["exact_excerpt_sha256"])
                or not _digest(reference["claim_text_sha256"])
                or reference["claim_text_sha256"]
                != _sha256(claim["text"].encode("utf-8"))
                or reference["candidate_relation"]
                not in {"SUPPORTS", "LIMITS", "CONTRADICTS"}
                or not isinstance(span, dict)
                or set(span) != span_keys
                or any(
                    isinstance(span[name], bool)
                    or not isinstance(span[name], int)
                    or span[name] < 0
                    for name in span_keys
                )
                or span["char_start"] >= span["char_end"]
                or span["byte_start"] >= span["byte_end"]
            ):
                _fail("CANDIDATE_EVIDENCE_REFERENCE_INVALID")
            identity = (
                reference["source_sha256"],
                reference["segment_id"],
                reference["segment_sha256"],
                span["byte_start"],
                span["byte_end"],
                span["char_start"],
                span["char_end"],
                reference["exact_excerpt_sha256"],
                reference["claim_text_sha256"],
                reference["candidate_relation"],
            )
            if identity in reference_identities:
                _fail("CANDIDATE_EVIDENCE_REFERENCE_INVALID")
            reference_identities.add(identity)
        candidate_ids.append(claim_id)

    _need(
        claim_map,
        ("schema_id", "run_id", "candidate_id", "candidate_sha256", "claims"),
        "claim_evidence_map.json",
    )
    if (
        claim_map["schema_id"] != "uvlm.coherence.totality.claim_evidence_map.v1"
        or claim_map["run_id"] != run_id
        or claim_map["candidate_id"] != candidate["candidate_id"]
        or claim_map["candidate_sha256"] != _canonical_hash(candidate)
        or not isinstance(claim_map["claims"], list)
        or claim_map.get("mapping_method")
        != "CANDIDATE_DECLARED_EXACT_CITATION_INTEGRITY_V1"
        or not isinstance(claim_map.get("unsupported_claim_ids"), list)
    ):
        _fail("CLAIM_MAP_CANDIDATE_BINDING_MISMATCH")
    mapped_ids = [item.get("claim_id") for item in claim_map["claims"] if isinstance(item, dict)]
    if mapped_ids != candidate_ids or len(mapped_ids) != len(claim_map["claims"]):
        _fail("CLAIM_MAP_COVERAGE_INVALID")
    normalized_source = raw["grounding/normalized_source.txt"].decode(
        "utf-8", errors="strict"
    )
    encoded_source = normalized_source.encode("utf-8")
    segment_rows = [
        _parse_json(line, f"grounding/segments.jsonl:{number}")
        for number, line in enumerate(
            raw["grounding/segments.jsonl"].splitlines(keepends=True), start=1
        )
    ]
    segments_by_id = {
        row.get("segment_id"): row
        for row in segment_rows
        if isinstance(row.get("segment_id"), str)
    }
    evidence_keys = reference_keys | {
        "exact_excerpt",
        "overlap_tokens",
        "token_coverage",
        "citation_integrity",
        "integrity_reason_codes",
    }
    claim_row_keys = {
        "claim_id",
        "text",
        "answer_span",
        "evidence",
        "support_status",
        "residual_tokens",
    }
    permitted_statuses = {
        "CITATION_VERIFIED_REVIEW_REQUIRED",
        "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED",
        "NO_VALID_SOURCE_CITATION",
        "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED",
        "INSUFFICIENT_EVIDENCE",
    }
    expected_unsupported: list[str] = []
    for claim, record in zip(candidate["claims"], claim_map["claims"], strict=True):
        answer_span = record.get("answer_span") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record) != claim_row_keys
            or record["claim_id"] != claim["claim_id"]
            or record["text"] != claim["text"]
            or answer_span
            != {"char_start": claim["answer_start"], "char_end": claim["answer_end"]}
            or record["support_status"] not in permitted_statuses
            or not isinstance(record["residual_tokens"], list)
            or record["residual_tokens"]
            != sorted(set(record["residual_tokens"]))
            or not all(isinstance(token, str) and token for token in record["residual_tokens"])
        ):
            _fail("CLAIM_MAP_EVIDENCE_INVALID")
        evidence = record.get("evidence")
        references = claim["candidate_evidence_references"]
        if not isinstance(evidence, list) or len(evidence) != len(references):
            _fail("CLAIM_MAP_EVIDENCE_INVALID")
        for reference, item in zip(references, evidence, strict=True):
            source_span = item.get("source_span") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or set(item) != evidence_keys
                or {key: item[key] for key in reference_keys} != reference
                or not isinstance(source_span, dict)
                or set(source_span) != span_keys
                or not all(
                    isinstance(source_span.get(name), int)
                    and not isinstance(source_span.get(name), bool)
                    and source_span[name] >= 0
                    for name in ("char_start", "char_end", "byte_start", "byte_end")
                )
                or item["citation_integrity"] not in {"VERIFIED", "INVALID"}
                or not isinstance(item["integrity_reason_codes"], list)
                or item["integrity_reason_codes"]
                != sorted(set(item["integrity_reason_codes"]))
                or not all(
                    isinstance(code, str) and _IDENTIFIER.fullmatch(code)
                    for code in item["integrity_reason_codes"]
                )
                or not isinstance(item["overlap_tokens"], list)
                or item["overlap_tokens"] != sorted(set(item["overlap_tokens"]))
                or not isinstance(item["token_coverage"], (int, float))
                or isinstance(item["token_coverage"], bool)
                or not 0 <= float(item["token_coverage"]) <= 1
            ):
                _fail("CLAIM_MAP_EVIDENCE_INVALID")
            excerpt = item["exact_excerpt"]
            if item["citation_integrity"] == "VERIFIED":
                segment = segments_by_id.get(item["segment_id"])
                char_start, char_end = source_span["char_start"], source_span["char_end"]
                byte_start, byte_end = source_span["byte_start"], source_span["byte_end"]
                if (
                    item["integrity_reason_codes"]
                    or not isinstance(excerpt, str)
                    or not excerpt
                    or item["source_sha256"]
                    != objects["grounding/manifest.json"].get("source_sha256")
                    or segment is None
                    or item["segment_sha256"] != segment.get("sha256")
                    or not 0 <= char_start < char_end <= len(normalized_source)
                    or not 0 <= byte_start < byte_end <= len(encoded_source)
                    or normalized_source[char_start:char_end] != excerpt
                    or encoded_source[byte_start:byte_end] != excerpt.encode("utf-8")
                    or len(normalized_source[:char_start].encode("utf-8")) != byte_start
                    or len(normalized_source[:char_end].encode("utf-8")) != byte_end
                    or item["exact_excerpt_sha256"] != _sha256(excerpt.encode("utf-8"))
                    or not segment["char_start"] <= char_start < char_end <= segment["char_end"]
                    or not segment["byte_start"] <= byte_start < byte_end <= segment["byte_end"]
                ):
                    _fail("CLAIM_MAP_EVIDENCE_INVALID")
            elif not item["integrity_reason_codes"] or excerpt is not None and not isinstance(excerpt, str):
                _fail("CLAIM_MAP_EVIDENCE_INVALID")
        if not evidence:
            expected_status = "NO_VALID_SOURCE_CITATION"
        elif any(item["citation_integrity"] != "VERIFIED" for item in evidence):
            expected_status = "INSUFFICIENT_EVIDENCE"
        else:
            relations = {item["candidate_relation"] for item in evidence}
            if "CONTRADICTS" in relations:
                expected_status = "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED"
            elif "SUPPORTS" in relations and "LIMITS" in relations:
                expected_status = "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED"
            elif "SUPPORTS" in relations:
                expected_status = "CITATION_VERIFIED_REVIEW_REQUIRED"
            else:
                expected_status = "NO_VALID_SOURCE_CITATION"
        if record["support_status"] != expected_status:
            _fail("CLAIM_MAP_SUPPORT_STATUS_INVALID")
        if expected_status not in {
            "CITATION_VERIFIED_REVIEW_REQUIRED",
            "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED",
        }:
            expected_unsupported.append(record["claim_id"])
    if claim_map["unsupported_claim_ids"] != sorted(expected_unsupported):
        _fail("CLAIM_MAP_SUPPORT_STATUS_INVALID")

    display_contracts = {
        "ucm_state.json": "uvlm.coherence.totality.ucm_state.v1",
        "projector_receipt.json": "uvlm.coherence.totality.projector_receipt.v1",
        "residual_refusal.json": "uvlm.coherence.totality.residual_refusal.v1",
        "aha_result.json": "uvlm.coherence.totality.aha_result.v1",
        "counterexamples.json": "uvlm.coherence.totality.counterexamples.v1",
        "aperture_decision.json": "uvlm.coherence.totality.aperture_decision.v1",
    }
    for relative, schema_id in display_contracts.items():
        artifact = objects[relative]
        _need(artifact, ("schema_id", "run_id", "candidate_id", "authority_effect"), relative)
        if (
            artifact["schema_id"] != schema_id
            or artifact["run_id"] != run_id
            or artifact["candidate_id"] != candidate["candidate_id"]
            or artifact["authority_effect"] != "NONE"
        ):
            _fail(f"DISPLAY_ARTIFACT_IDENTITY_INVALID:{relative}")
    projector = objects["projector_receipt.json"]
    _need(
        projector,
        ("full_candidate_posterior", "full_equivalence_posterior", "presentation", "disposition"),
        "projector_receipt.json",
    )
    presentation = projector["presentation"]
    if (
        not isinstance(projector["full_candidate_posterior"], list)
        or not projector["full_candidate_posterior"]
        or not isinstance(projector["full_equivalence_posterior"], list)
        or not projector["full_equivalence_posterior"]
        or not isinstance(presentation, dict)
        or presentation.get("disposition_invariant_to_top_k") is not True
    ):
        _fail("PROJECTOR_PRESENTATION_INCOMPLETE")
    aha = objects["aha_result.json"]
    if aha.get("status") not in {"AVAILABLE", "UNAVAILABLE"}:
        _fail("AHA_POSTURE_INVALID")
    aperture = objects["aperture_decision.json"]
    if (
        not isinstance(aperture.get("hard_gates"), dict)
        or not aperture["hard_gates"]
        or aperture.get("candidate_is_final_answer") is not False
        or aperture.get("human_review_required") is not True
    ):
        _fail("APERTURE_HARD_GATE_POSTURE_INVALID")

    audited = _validate_sophia_bindings(raw, objects)
    _validate_pmr_receipt(
        pmr,
        request,
        candidate,
        run_id=run_id,
        logical_time=logical_time,
    )
    return {"run_id": run_id, "logical_time": logical_time, "audited_digests": audited}


def _escape(value: Any) -> str:
    if value is None:
        return "not supplied"
    if isinstance(value, bool):
        value = "true" if value else "false"
    return html.escape(str(value), quote=True)


def _pretty(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), quote=True)


def _list(items: Iterable[Any], empty: str = "None recorded.") -> str:
    materialized = list(items)
    if not materialized:
        return f'<p class="muted">{_escape(empty)}</p>'
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in materialized) + "</ul>"


def _artifact_details(title: str, relative: str, value: Any) -> str:
    return (
        '<details><summary>'
        + _escape(title)
        + " — exact canonical artifact</summary><p>Path: <code>"
        + _escape(relative)
        + "</code></p><pre>"
        + _pretty(value)
        + "</pre></details>"
    )


def _claim_evidence_html(candidate: dict[str, Any], claim_map: dict[str, Any]) -> str:
    mapped = {item["claim_id"]: item for item in claim_map["claims"]}
    sections: list[str] = []
    for claim in candidate["claims"]:
        record = mapped[claim["claim_id"]]
        evidence_rows: list[str] = []
        for item in record["evidence"]:
            source_span = item.get("source_span")
            if not isinstance(source_span, dict):
                source_span = {}
            evidence_rows.append(
                "<tr>"
                f'<td><code>{_escape(item.get("segment_id"))}</code></td>'
                f'<td>{_escape(item.get("candidate_relation"))}</td>'
                f'<td>{_escape(item.get("citation_integrity"))}</td>'
                f'<td><q>{_escape(item.get("exact_excerpt"))}</q></td>'
                f'<td>{_escape(source_span.get("char_start"))}–{_escape(source_span.get("char_end"))}</td>'
                f'<td>{_escape(source_span.get("byte_start"))}–{_escape(source_span.get("byte_end"))}</td>'
                f'<td>{_escape(", ".join(item.get("integrity_reason_codes", [])) or "none")}</td>'
                "</tr>"
            )
        if not evidence_rows:
            evidence_rows.append(
                '<tr><td colspan="7">No candidate-declared source citation was supplied.</td></tr>'
            )
        sections.append(
            '<article class="claim">'
            f'<h3>{_escape(claim["claim_id"])}</h3>'
            f'<p class="candidate-text">{_escape(claim.get("text"))}</p>'
            f'<p><strong>Candidate answer span:</strong> {_escape(claim.get("answer_start"))}–{_escape(claim.get("answer_end"))}; '
            f'<strong>support:</strong> {_escape(record.get("support_status"))}; '
            f'<strong>uncertainty:</strong> {_escape(record.get("uncertainty", candidate.get("uncertainty")))}</p>'
            '<table><caption>Candidate-declared citations and exact integrity checks</caption><thead><tr>'
            '<th scope="col">Segment</th><th scope="col">Candidate relation</th>'
            '<th scope="col">Citation integrity</th><th scope="col">Exact excerpt</th>'
            '<th scope="col">Character span</th><th scope="col">Byte span</th>'
            '<th scope="col">Integrity reasons</th></tr></thead><tbody>'
            + "".join(evidence_rows)
            + "</tbody></table></article>"
        )
    return "".join(sections)


def _sophia_html(sophia: dict[str, Any]) -> str:
    findings = []
    for finding in sophia["findings"]:
        if isinstance(finding, dict):
            findings.append(
                f'{finding.get("severity", "finding")}: {finding.get("code", "UNSPECIFIED")} — '
                f'{finding.get("artifact", "unspecified artifact")}: {finding.get("detail", "")}'
            )
        else:
            findings.append(str(finding))
    checks = [f"{key}: {value}" for key, value in sorted(sophia["recomputed_checks"].items())]
    return_route = sophia["return_route"]
    return (
        f'<p class="disposition {sophia["disposition"].lower()}"><strong>{_escape(sophia["disposition"])}</strong></p>'
        f'<p><strong>Bounded return route:</strong> {_escape(return_route["route"])} to {_escape(return_route["destination"])}; {_escape(return_route["status"])}. This request did not mutate the candidate or automatically rerun any component.</p>'
        '<h3>Reason codes</h3>'
        + _list(sophia["reason_codes"])
        + '<h3>Independent findings</h3>'
        + _list(findings)
        + '<h3>Critical relationships recomputed</h3>'
        + _list(checks)
    )


def _html_review(objects: Mapping[str, dict[str, Any]], packet: dict[str, Any]) -> bytes:
    request = objects["request.json"]
    candidate = objects["candidate_packet.json"]
    claim_map = objects["claim_evidence_map.json"]
    ucm = objects["ucm_state.json"]
    projector = objects["projector_receipt.json"]
    refusal = objects["residual_refusal.json"]
    aha = objects["aha_result.json"]
    counters = objects["counterexamples.json"]
    aperture = objects["aperture_decision.json"]
    sophia = objects["sophia_audit_packet.json"]
    pmr = objects["pmr_receipt.json"]
    decision_rows = "".join(
        f'<dt>{_escape(choice)}</dt><dd>{_escape(meaning)}</dd>'
        for choice, meaning in DECISION_MEANINGS.items()
    )
    limitations = _list(LIMITATIONS)
    exact_artifacts = "".join(
        (
            _artifact_details("Canonical request envelope", "request.json", request),
            _artifact_details(
                "Grounding manifest", "grounding/manifest.json", objects["grounding/manifest.json"]
            ),
            _artifact_details("Candidate packet", "candidate_packet.json", candidate),
            _artifact_details("Complete claim/evidence map", "claim_evidence_map.json", claim_map),
            _artifact_details("UCM state", "ucm_state.json", ucm),
            _artifact_details("Full-posterior projector receipt", "projector_receipt.json", projector),
            _artifact_details("Residual and refusal result", "residual_refusal.json", refusal),
            _artifact_details("AHA structural result or unavailable posture", "aha_result.json", aha),
            _artifact_details("Counterexamples and conflicts", "counterexamples.json", counters),
            _artifact_details("Noncompensatory aperture decision", "aperture_decision.json", aperture),
            _artifact_details("Sophia audit packet", "sophia_audit_packet.json", sophia),
            _artifact_details("PMR separate-consent receipt", "pmr_receipt.json", pmr),
        )
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas totality human review — {_escape(packet['run_id'])}</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; line-height: 1.55; }}
body {{ margin: 0; background: Canvas; color: CanvasText; }}
.skip {{ position: absolute; left: -9999px; }} .skip:focus {{ left: 1rem; top: 1rem; background: Canvas; padding: .75rem; z-index: 2; }}
header, main, footer {{ max-width: 76rem; margin: auto; padding: 1rem 1.5rem; }}
nav ul {{ display: flex; flex-wrap: wrap; gap: .8rem; padding: 0; list-style: none; }}
section {{ border-top: 2px solid GrayText; margin-top: 2rem; padding-top: 1rem; }}
.boundary, .warning {{ border-left: .4rem solid #9b5b00; padding: .8rem 1rem; background: color-mix(in srgb, Canvas 88%, #f0a000 12%); }}
.candidate-text {{ white-space: pre-wrap; font-size: 1.05rem; }}
table {{ border-collapse: collapse; width: 100%; }} caption {{ font-weight: 700; text-align: left; margin: .5rem 0; }}
th, td {{ border: 1px solid GrayText; padding: .55rem; text-align: left; vertical-align: top; }}
q {{ white-space: pre-wrap; }} pre {{ white-space: pre-wrap; overflow-wrap: anywhere; padding: .8rem; border: 1px solid GrayText; }}
dt {{ font-weight: 700; margin-top: .7rem; }} .muted {{ color: GrayText; }}
.pass {{ color: #146b28; }} .hold {{ color: #8a5600; }} .reject {{ color: #a32020; }}
</style>
</head>
<body>
<a class="skip" href="#main">Skip to review</a>
<header>
<h1>Atlas totality review</h1>
<p>Run <code>{_escape(packet['run_id'])}</code> · logical time <code>{_escape(packet['logical_time'])}</code></p>
<p>Candidate <code>{_escape(packet['candidate_id'])}</code> · Sophia audit <code>{_escape(packet['audit_id'])}</code></p>
<p class="boundary"><strong>Candidate, not answer.</strong> This is bounded decision context. It is not truth certification and grants no memory, training, canonization, publication, deployment, release, or external-action authority.</p>
<nav aria-label="Review sections"><ul>
<li><a href="#task">Task</a></li><li><a href="#candidate">Candidate and evidence</a></li>
<li><a href="#uncertainty">Uncertainty and refusals</a></li><li><a href="#audit">Sophia audit</a></li>
<li><a href="#decision">Human decision</a></li><li><a href="#exact">Exact artifacts</a></li>
</ul></nav>
</header>
<main id="main" tabindex="-1">
<section id="task"><h2>Task and grounding</h2>
<p><strong>User task:</strong> {_escape(request['user_input'])}</p>
<p><strong>Grounding bundle:</strong> <code>{_escape(objects['grounding/manifest.json'].get('bundle_id'))}</code>; source SHA-256 <code>{_escape(objects['grounding/manifest.json'].get('source_sha256'))}</code>; normalized SHA-256 <code>{_escape(objects['grounding/manifest.json'].get('normalized_sha256'))}</code>.</p>
</section>
<section id="candidate"><h2>Candidate and exact claim evidence</h2>
<p class="warning">The following text is a candidate under review. Do not present it as Atlas's answer.</p>
<p class="candidate-text">{_escape(candidate['answer'])}</p>
<p><strong>Candidate uncertainty:</strong> {_escape(candidate['uncertainty'])}</p>
{_claim_evidence_html(candidate, claim_map)}
</section>
<section id="uncertainty"><h2>Uncertainty, posterior, equivalence, and refusal</h2>
<p>The full posterior and every equivalence set are shown in the exact projector artifact below. Any top-k list is presentation-only and cannot change those values, the residual, or the disposition.</p>
{_artifact_details('Typed UCM state', 'ucm_state.json', ucm)}
{_artifact_details('Full posterior, equivalence sets, and top-k display receipt', 'projector_receipt.json', projector)}
{_artifact_details('Residual, ambiguity, OOD, insufficient-evidence, and new-pattern refusal', 'residual_refusal.json', refusal)}
</section>
<section id="analogy"><h2>AHA structural analogy</h2>
<p>The result must either show structural donor/target mapping, disanalogies, comparator, observable, falsification, and reject criteria, or state an explicit unavailable posture. A mapping is a testable hypothesis, not proof.</p>
{_artifact_details('AHA mapping or explicit unavailable posture', 'aha_result.json', aha)}
</section>
<section id="counterevidence"><h2>Counterexamples and conflicts</h2>
{_artifact_details('Counterexample search result', 'counterexamples.json', counters)}
</section>
<section id="aperture"><h2>Noncompensatory aperture</h2>
<p>Consent, privacy, and retention gates are hard gates: a favorable score elsewhere cannot compensate for a failed gate.</p>
{_artifact_details('Aperture decision', 'aperture_decision.json', aperture)}
</section>
<section id="audit"><h2>Sophia independent audit</h2>
{_sophia_html(sophia)}
</section>
<section id="pmr"><h2>PMR separate consent and no-action posture</h2>
<p>Task consent is not retention consent. PMR remains a separate, revocable lane; this Atlas operation wrote no memory and performed no training.</p>
{_artifact_details('PMR receipt', 'pmr_receipt.json', pmr)}
</section>
<section id="limitations"><h2>Limitations and authority boundaries</h2>{limitations}
<p><strong>Atlas posture:</strong> {_escape(packet['retention_posture'])}; {_escape(packet['publication_posture'])}; {_escape(packet['expiry_posture'])}; {_escape(packet['revocation_posture'])}.</p>
</section>
<section id="decision"><h2>Human decision required</h2>
<p>No choice has been made by this artifact. Use the loopback human-review interface for two-step confirmation and an immutable receipt outside the sealed run root.</p>
<dl>{decision_rows}</dl>
</section>
<section id="exact"><h2>Exact bounded artifacts</h2>{exact_artifacts}</section>
</main>
<footer><p>Atlas oriented this evidence without changing upstream artifacts or performing memory, PMR, training, canonization, publication, DOI, Crossref, catalog, knowledge-graph, deployment, release, or model actions.</p></footer>
</body></html>
"""
    return document.encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and _link_like(path):
        _fail(f"OUTPUT_SYMLINK_PROHIBITED:{path.name}")
    descriptor, temporary = tempfile.mkstemp(prefix=".atlas-totality-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def assign_totality_posture(run_root: str | Path) -> dict[str, Any]:
    """Validate a totality run and deterministically write Atlas outputs."""

    root = _safe_root(run_root)
    if any((root / name).exists() for name in SEALED_RUN_MARKERS):
        _fail("SEALED_RUN_IMMUTABLE")
    raw, objects = _load_inputs(root)
    validated = _validate_contracts(raw, objects)
    sophia = objects["sophia_audit_packet.json"]
    pmr = objects["pmr_receipt.json"]
    disposition = sophia["disposition"]
    retention, publication = {
        "PASS": ("retain_for_human_review", "publication_blocked_pending_human_review"),
        "HOLD": ("quarantine", "do_not_publish"),
        "REJECT": ("rejected", "do_not_publish"),
    }[disposition]
    input_digests = {
        **validated["audited_digests"],
        "sophia_audit_packet.json": _expected_digest(
            raw["sophia_audit_packet.json"], sophia
        ),
        "pmr_receipt.json": _expected_digest(raw["pmr_receipt.json"], pmr),
    }
    parent_paths = tuple(path for path in AUDITED_INPUTS if path in raw) + (
        "sophia_audit_packet.json",
    )
    packet = {
        "schema_id": ATLAS_SCHEMA,
        "schema_version": "1.0",
        "packet_type": "atlas_posture_packet",
        "producer_repository": "pdxvoiceteacher/uvlm-publications",
        "producer": {
            "repository": "pdxvoiceteacher/uvlm-publications",
            "role": "bounded_totality_posture_and_human_review_renderer",
            "version": "1.0",
        },
        "run_id": validated["run_id"],
        "logical_time": validated["logical_time"],
        "candidate_id": objects["candidate_packet.json"]["candidate_id"],
        "audit_id": sophia["audit_id"],
        "input_digests": input_digests,
        "parent_list": [
            {"artifact_type": "bounded_input", "path": path, **input_digests[path]}
            for path in parent_paths
        ],
        "sophia_disposition": disposition,
        "sophia_reason_codes": sophia["reason_codes"],
        "sophia_findings": sophia["findings"],
        "retention_posture": retention,
        "publication_posture": publication,
        "expiry_posture": "review_bounded",
        "revocation_posture": "revocable",
        "pmr_posture": "separate_consent_no_action",
        "candidate_is_not_answer": True,
        "full_posterior_presented": True,
        "top_k_is_presentation_only": True,
        "human_action_required": True,
        "requires_human_review": True,
        "human_decision": "PENDING",
        "human_decision_options": list(DECISION_MEANINGS),
        "limitations": list(LIMITATIONS),
        "nonauthority": dict.fromkeys(ATLAS_NONAUTHORITY, False),
        "side_effects": dict.fromkeys(ATLAS_EFFECTS, False),
        "nonauthority_statement": "Atlas presents bounded evidence and posture only. It does not certify truth or authorize memory, PMR, training, canonization, publication, deployment, release, or any external action.",
    }
    packet_bytes = _canonical_json_bytes(packet)
    review_bytes = _html_review(objects, packet)
    _atomic_write(root / OUTPUT_PACKET, packet_bytes)
    _atomic_write(root / OUTPUT_REVIEW, review_bytes)
    if any(
        _bounded_member_bytes(root, relative) != payload
        for relative, payload in raw.items()
    ):
        _fail("UPSTREAM_ARTIFACT_MUTATION_DETECTED")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write deterministic Atlas posture and static totality review artifacts."
    )
    parser.add_argument("--run-root", required=True)
    arguments = parser.parse_args()
    assign_totality_posture(arguments.run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
