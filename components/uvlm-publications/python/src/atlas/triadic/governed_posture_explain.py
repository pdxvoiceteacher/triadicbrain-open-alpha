"""Deterministic, file-only Atlas posture explanation renderer."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import governed_posture as posture
from .human_review_ui import HumanReviewError, load_sealed_run


class GovernedPostureExplanationError(ValueError):
    """A stable, non-sensitive explanation validation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


EXPLANATION_NAME = "atlas_explanation_packet.json"
SOPHIA_EXPLANATION_SCHEMA = "uvlm.sophia.explanation_packet.v1"
ATLAS_EXPLANATION_SCHEMA = "uvlm.atlas.explanation_packet.v1"
POSTURE_TEXT = {
    "retention_posture": {
        "retain_for_human_review": "This candidate is retained only for bounded human review; it is not a memory write or PMR action.",
        "quarantine": "This candidate is quarantined while the identified concern remains unresolved; no retention authority is created.",
        "rejected": "This candidate is rejected for this review path; it is not accepted as truth or retained as canon.",
    },
    "publication_posture": {
        "publication_blocked_pending_human_review": "Publication is blocked pending a bounded human decision; review does not authorize publication, DOI, Crossref, catalog, or graph changes.",
        "do_not_publish": "Publication is blocked; this posture does not authorize any publication or registry action.",
    },
    "expiry_posture": {
        "review_bounded": "This posture is limited to the current review context and does not create durable authority.",
    },
    "revocation_posture": {
        "revocable": "This context can be revoked; revocation records downstream review effects without rewriting prior evidence.",
    },
}
DECISION_MEANINGS = {
    "APPROVE": "accept this bounded output for the stated use; it does not certify universal truth or authorize memory, publication, deployment, or release",
    "HOLD": "correction or more evidence is required; it does not rewrite the candidate or audit",
    "REJECT": "do not accept this candidate for the stated use; it does not delete or rewrite its lineage",
    "REPAIR": "request a new Sonya-routed candidate lineage; it does not execute repair, generate or revise candidate content, or grant authority",
}


def _error(code: str) -> None:
    raise GovernedPostureExplanationError(code)


def _absolute_file(value: str | Path, code: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _error(code)
    return path.resolve()


def _external_root(value: str | Path, sealed_root: Path) -> Path:
    root = Path(value)
    if not root.is_absolute() or root.is_symlink() or root == Path(root.anchor):
        _error("OUTPUT_ROOT_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    if root.is_symlink() or not root.is_dir():
        _error("OUTPUT_ROOT_INVALID")
    try:
        root.relative_to(sealed_root)
    except ValueError:
        return root
    _error("OUTPUT_INSIDE_SEALED_RUN")


def _all_false(value: Any, keys: tuple[str, ...], code: str) -> None:
    if not isinstance(value, dict) or set(value) != set(keys) or any(value.get(key) is not False for key in keys):
        _error(code)


def _expected_parent(kind: str, path: str, file_hash: str, canonical_hash: str) -> dict[str, str]:
    return {"artifact_type": kind, "path": path, "file_sha256": file_hash, "canonical_sha256": canonical_hash}


def _validated_sophia_explanation(path: str | Path, sealed: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    packet_path = _absolute_file(path, "SOPHIA_EXPLANATION_UNSAFE")
    try:
        packet_path.relative_to(sealed["root"])
    except ValueError:
        pass
    else:
        _error("SOPHIA_EXPLANATION_INSIDE_SEALED_RUN")
    try:
        data, file_hash, canonical_hash = posture._load(packet_path)
        posture._scan(data)
    except posture.GovernedPostureError as exc:
        raise GovernedPostureExplanationError("SOPHIA_EXPLANATION_INVALID") from exc
    required = ("schema_id", "schema_version", "packet_type", "run_id", "logical_time", "producer_repository", "parents", "disposition", "overall_reason", "claim_explanations", "repairable", "authority_boundary", "side_effects", "nonauthority")
    if any(key not in data for key in required):
        _error("SOPHIA_EXPLANATION_INVALID")
    if (data["schema_id"], data["schema_version"], data["packet_type"], data["producer_repository"]) != (SOPHIA_EXPLANATION_SCHEMA, "1.0", "sophia_explanation", "pdxvoiceteacher/Sophia"):
        _error("SOPHIA_EXPLANATION_IDENTITY_MISMATCH")
    if data["run_id"] != sealed["request"]["run_id"] or data["logical_time"] != sealed["request"]["logical_time"]:
        _error("SOPHIA_EXPLANATION_RUN_MISMATCH")
    hashes = sealed["hashes"]
    candidate = _expected_parent("candidate_packet", "candidate_packet.json", hashes["candidate_packet.json"], posture._hash(posture._canon(sealed["candidate"])))
    audit = _expected_parent("sophia_audit_packet", "sophia_audit_packet.json", hashes["sophia_audit_packet.json"], posture._hash(posture._canon(sealed["sophia"])))
    if data["parents"] != [candidate, audit]:
        _error("SOPHIA_EXPLANATION_PARENT_MISMATCH")
    if data["disposition"] != sealed["sophia"]["disposition"] or not isinstance(data["overall_reason"], str) or not data["overall_reason"]:
        _error("SOPHIA_EXPLANATION_INVALID")
    if not isinstance(data["repairable"], bool) or not isinstance(data["claim_explanations"], list):
        _error("SOPHIA_EXPLANATION_INVALID")
    for claim in data["claim_explanations"]:
        if not isinstance(claim, dict) or any(key not in claim for key in ("claim_id", "evidence_status", "maturity_status", "uncertainty_status", "reason_codes", "plain_language_reason", "evidence_refs", "repair_constraints")):
            _error("SOPHIA_EXPLANATION_INVALID")
        if not all(isinstance(claim[key], str) and claim[key] for key in ("claim_id", "evidence_status", "maturity_status", "uncertainty_status", "plain_language_reason")) or not all(isinstance(x, str) for x in claim["reason_codes"] + claim["evidence_refs"]):
            _error("SOPHIA_EXPLANATION_INVALID")
        if not all(isinstance(item, dict) and isinstance(item.get("code"), str) and isinstance(item.get("instruction"), str) for item in claim["repair_constraints"]):
            _error("SOPHIA_EXPLANATION_INVALID")
    _all_false(data["authority_boundary"], posture.SOPHIA_NONAUTH, "SOPHIA_EXPLANATION_AUTHORITY")
    _all_false(data["side_effects"], posture.SOPHIA_EFFECTS, "SOPHIA_EXPLANATION_EFFECTS")
    if not isinstance(data["nonauthority"], str) or not data["nonauthority"]:
        _error("SOPHIA_EXPLANATION_INVALID")
    return data, file_hash, canonical_hash


def build_atlas_explanation(run_root: str | Path, sophia_explanation: str | Path, output_root: str | Path) -> dict[str, Any]:
    """Validate sealed artifacts and write one deterministic external explanation."""
    try:
        sealed = load_sealed_run(run_root)
    except HumanReviewError as exc:
        raise GovernedPostureExplanationError("SEALED_RUN_INVALID") from exc
    output = _external_root(output_root, sealed["root"])
    sophia, sophia_file, sophia_canonical = _validated_sophia_explanation(sophia_explanation, sealed)
    atlas = sealed["atlas"]
    explanations: dict[str, str] = {}
    for field, mapping in POSTURE_TEXT.items():
        value = atlas.get(field)
        if value not in mapping:
            _error("UNKNOWN_ATLAS_POSTURE")
        explanations[field.removesuffix("_posture")] = mapping[value]
    explanations["human_review"] = (
        "Human review is required because Sophia evaluated the candidate without certifying truth; Atlas presents that bounded disposition and records, but does not rank, the human decision."
    )
    hashes = sealed["hashes"]
    atlas_parent = _expected_parent("atlas_posture_packet", "atlas_posture_packet.json", hashes["atlas_posture_packet.json"], posture._hash(posture._canon(atlas)))
    sophia_parent = _expected_parent("sophia_explanation_packet", Path(sophia_explanation).name, sophia_file, sophia_canonical)
    packet = {
        "schema_id": ATLAS_EXPLANATION_SCHEMA,
        "schema_version": "1.0",
        "packet_type": "atlas_explanation",
        "run_id": sealed["request"]["run_id"],
        "logical_time": sealed["request"]["logical_time"],
        "producer_repository": "pdxvoiceteacher/uvlm-publications",
        "parents": [atlas_parent, sophia_parent],
        "current_posture": {key: atlas[key] for key in ("retention_posture", "publication_posture", "expiry_posture", "revocation_posture", "requires_human_review", "human_decision")},
        "posture_explanations": explanations,
        "sophia_disposition_explanation": f"Sophia disposition {sophia['disposition']} informs this presentation: {sophia['overall_reason']}",
        "repair_available": sophia["repairable"],
        "provider_explanation": None if atlas.get("provider_context") is None else f"Provider trust class {atlas['provider_context']['trust_class']} and data-egress class {atlas['provider_context']['data_egress']} describe execution routing only. Identity assurance {atlas['provider_context']['assurance']} does not create correctness or Atlas posture authority.",
        "decision_meanings": DECISION_MEANINGS,
        "permitted_next_actions": ["REQUEST_REPAIR", "RECORD_DECISION", "EXPORT_EVIDENCE"],
        "authority_boundary": dict.fromkeys(posture.ATLAS_NONAUTH, False),
        "side_effects": dict.fromkeys(posture.ATLAS_EFFECTS, False),
        "nonauthority": "This explanation presents bounded posture and decision context only. It does not authorize memory, PMR, canonization, publication, DOI, Crossref, catalog, graph, deployment, or release.",
    }
    data = posture._canon(packet) + b"\n"
    target = output / EXPLANATION_NAME
    if target.exists() and target.is_symlink():
        _error("OUTPUT_PATH_UNSAFE")
    with NamedTemporaryFile(dir=output, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    os.replace(temporary, target)
    return packet


def load_atlas_explanation(run_root: str | Path, explanation_path: str | Path) -> tuple[dict[str, Any], str, str]:
    """Validate a presented Atlas explanation against a currently sealed run."""
    try:
        sealed = load_sealed_run(run_root)
    except HumanReviewError as exc:
        raise GovernedPostureExplanationError("SEALED_RUN_INVALID") from exc
    path = _absolute_file(explanation_path, "ATLAS_EXPLANATION_UNSAFE")
    try:
        path.relative_to(sealed["root"])
    except ValueError:
        pass
    else:
        _error("ATLAS_EXPLANATION_INSIDE_SEALED_RUN")
    try:
        packet, file_hash, canonical_hash = posture._load(path)
        posture._scan(packet)
    except posture.GovernedPostureError as exc:
        raise GovernedPostureExplanationError("ATLAS_EXPLANATION_INVALID") from exc
    required = ("schema_id", "schema_version", "packet_type", "run_id", "logical_time", "producer_repository", "parents", "current_posture", "posture_explanations", "decision_meanings", "permitted_next_actions", "authority_boundary", "side_effects", "nonauthority")
    if any(key not in packet for key in required) or (packet["schema_id"], packet["schema_version"], packet["packet_type"], packet["producer_repository"]) != (ATLAS_EXPLANATION_SCHEMA, "1.0", "atlas_explanation", "pdxvoiceteacher/uvlm-publications"):
        _error("ATLAS_EXPLANATION_INVALID")
    if (packet["run_id"], packet["logical_time"]) != (sealed["request"]["run_id"], sealed["request"]["logical_time"]):
        _error("ATLAS_EXPLANATION_RUN_MISMATCH")
    atlas_parent = _expected_parent("atlas_posture_packet", "atlas_posture_packet.json", sealed["hashes"]["atlas_posture_packet.json"], posture._hash(posture._canon(sealed["atlas"])))
    if not isinstance(packet["parents"], list) or not packet["parents"] or packet["parents"][0] != atlas_parent:
        _error("ATLAS_EXPLANATION_PARENT_MISMATCH")
    expected_current = {key: sealed["atlas"][key] for key in ("retention_posture", "publication_posture", "expiry_posture", "revocation_posture", "requires_human_review", "human_decision")}
    if packet["current_posture"] != expected_current or packet["decision_meanings"] != DECISION_MEANINGS or packet["permitted_next_actions"] != ["REQUEST_REPAIR", "RECORD_DECISION", "EXPORT_EVIDENCE"]:
        _error("ATLAS_EXPLANATION_INVALID")
    _all_false(packet["authority_boundary"], posture.ATLAS_NONAUTH, "ATLAS_EXPLANATION_AUTHORITY")
    _all_false(packet["side_effects"], posture.ATLAS_EFFECTS, "ATLAS_EXPLANATION_EFFECTS")
    return packet, file_hash, canonical_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--sophia-explanation", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    build_atlas_explanation(args.run_root, args.sophia_explanation, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
