"""Exact candidate-claim and normalized-source evidence binding."""

from __future__ import annotations

import re
from typing import Any

from .adapter import validate_candidate_packet
from .canonical import (
    require_identifier,
    require_sha256,
    sha256_bytes,
    sha256_json,
)
from .errors import ValidationError
from .grounding import validate_grounding_bundle

CLAIM_MAP_SCHEMA = "uvlm.coherence.totality.claim_evidence_map.v1"
MAPPING_METHOD = "CANDIDATE_DECLARED_EXACT_CITATION_INTEGRITY_V1"
CITATION_VERIFIED = "CITATION_VERIFIED_REVIEW_REQUIRED"
CITATION_LIMITED = "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED"
NO_VALID_CITATION = "NO_VALID_SOURCE_CITATION"
POSSIBLE_CONTRADICTION = "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
_TOKEN = re.compile(r"[^\W_][\w'-]*", re.UNICODE)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
}


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(text) if token.casefold() not in _STOP}


def _evaluate_reference(
    reference: dict[str, Any],
    *,
    claim_text: str,
    bundle: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    manifest = bundle["manifest"]
    normalized_source = bundle["normalized_source"]
    encoded_source = normalized_source.encode("utf-8")
    segment = segments_by_id.get(reference["segment_id"])
    span = reference["source_span"]
    char_start, char_end = span["char_start"], span["char_end"]
    byte_start, byte_end = span["byte_start"], span["byte_end"]

    if reference["source_sha256"] != manifest["source_sha256"]:
        reasons.append("CITATION_SOURCE_SHA256_MISMATCH")
    if segment is None:
        reasons.append("CITATION_SEGMENT_ID_NOT_FOUND")
    elif reference["segment_sha256"] != segment["sha256"]:
        reasons.append("CITATION_SEGMENT_SHA256_MISMATCH")
    if reference["claim_text_sha256"] != sha256_bytes(claim_text.encode("utf-8")):
        reasons.append("CITATION_CLAIM_TEXT_SHA256_MISMATCH")

    excerpt: str | None = None
    char_bytes_consistent = False
    if (
        0 <= char_start < char_end <= len(normalized_source)
        and 0 <= byte_start < byte_end <= len(encoded_source)
    ):
        candidate_excerpt = normalized_source[char_start:char_end]
        excerpt_bytes = encoded_source[byte_start:byte_end]
        char_bytes_consistent = (
            len(normalized_source[:char_start].encode("utf-8")) == byte_start
            and len(normalized_source[:char_end].encode("utf-8")) == byte_end
            and excerpt_bytes == candidate_excerpt.encode("utf-8")
        )
        if char_bytes_consistent:
            excerpt = candidate_excerpt
    if not char_bytes_consistent:
        reasons.append("CITATION_CHAR_BYTE_SPAN_MISMATCH")
    if segment is not None and not (
        segment["char_start"] <= char_start < char_end <= segment["char_end"]
        and segment["byte_start"] <= byte_start < byte_end <= segment["byte_end"]
    ):
        reasons.append("CITATION_SPAN_OUTSIDE_SEGMENT")
    if excerpt is None or reference["exact_excerpt_sha256"] != sha256_bytes(
        excerpt.encode("utf-8") if excerpt is not None else b""
    ):
        reasons.append("CITATION_EXACT_EXCERPT_SHA256_MISMATCH")

    claim_tokens = _tokens(claim_text)
    overlap = sorted(claim_tokens & _tokens(excerpt or ""))
    return {
        "source_sha256": reference["source_sha256"],
        "segment_id": reference["segment_id"],
        "segment_sha256": reference["segment_sha256"],
        "source_span": dict(span),
        "exact_excerpt_sha256": reference["exact_excerpt_sha256"],
        "claim_text_sha256": reference["claim_text_sha256"],
        "candidate_relation": reference["candidate_relation"],
        "exact_excerpt": excerpt,
        "overlap_tokens": overlap,
        "token_coverage": round(len(overlap) / max(1, len(claim_tokens)), 12),
        "citation_integrity": "VERIFIED" if not reasons else "INVALID",
        "integrity_reason_codes": sorted(set(reasons)),
    }


def _mark_overlapping_references(rows: list[dict[str, Any]]) -> None:
    for left_index, left in enumerate(rows):
        left_span = left["source_span"]
        for right in rows[left_index + 1 :]:
            if left["source_sha256"] != right["source_sha256"]:
                continue
            right_span = right["source_span"]
            char_overlap = max(left_span["char_start"], right_span["char_start"]) < min(
                left_span["char_end"], right_span["char_end"]
            )
            byte_overlap = max(left_span["byte_start"], right_span["byte_start"]) < min(
                left_span["byte_end"], right_span["byte_end"]
            )
            if not char_overlap and not byte_overlap:
                continue
            for row in (left, right):
                row["citation_integrity"] = "INVALID"
                row["integrity_reason_codes"] = sorted(
                    set(row["integrity_reason_codes"]) | {"CITATION_SPAN_OVERLAP"}
                )


def _support_status(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return NO_VALID_CITATION
    if any(row["citation_integrity"] != "VERIFIED" for row in evidence):
        return INSUFFICIENT
    relations = {row["candidate_relation"] for row in evidence}
    if "CONTRADICTS" in relations:
        return POSSIBLE_CONTRADICTION
    if "SUPPORTS" in relations and "LIMITS" in relations:
        return CITATION_LIMITED
    if "SUPPORTS" in relations:
        return CITATION_VERIFIED
    return NO_VALID_CITATION


def build_claim_evidence_map(
    candidate: Any,
    grounding_bundle: Any,
    *,
    candidate_sha256: str | None = None,
) -> dict[str, Any]:
    candidate = validate_candidate_packet(candidate)
    bundle = validate_grounding_bundle(grounding_bundle)
    segments_by_id = {segment["segment_id"]: segment for segment in bundle["segments"]}
    output_claims: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for index, claim in enumerate(candidate["claims"]):
        claim_id = require_identifier(
            claim["claim_id"], f"$.candidate.claims[{index}].claim_id"
        )
        text = claim["text"]
        start, end = claim["answer_start"], claim["answer_end"]
        claim_tokens = _tokens(text)
        evidence = [
            _evaluate_reference(
                reference,
                claim_text=text,
                bundle=bundle,
                segments_by_id=segments_by_id,
            )
            for reference in claim["candidate_evidence_references"]
        ]
        _mark_overlapping_references(evidence)
        covered: set[str] = set()
        for row in evidence:
            if row["citation_integrity"] == "VERIFIED":
                covered.update(row["overlap_tokens"])
        status = _support_status(evidence)
        if status not in {CITATION_VERIFIED, CITATION_LIMITED}:
            unsupported.append(claim_id)
        output_claims.append(
            {
                "claim_id": claim_id,
                "text": text,
                "answer_span": {"char_start": start, "char_end": end},
                "evidence": evidence,
                "support_status": status,
                "residual_tokens": sorted(claim_tokens - covered),
            }
        )
    resolved_candidate_hash = candidate_sha256 or sha256_json(candidate)
    require_sha256(resolved_candidate_hash, "$.candidate_sha256")
    return {
        "schema_id": CLAIM_MAP_SCHEMA,
        "run_id": require_identifier(candidate["run_id"], "$.candidate.run_id"),
        "candidate_id": require_identifier(candidate["candidate_id"], "$.candidate.candidate_id"),
        "candidate_sha256": resolved_candidate_hash,
        "grounding_manifest_sha256": sha256_json(bundle["manifest"]),
        "source_sha256": bundle["manifest"]["source_sha256"],
        "mapping_method": MAPPING_METHOD,
        "claims": output_claims,
        "unsupported_claim_ids": sorted(unsupported),
        "authority_effect": "NONE",
    }


def validate_claim_evidence_map(value: Any, candidate: Any, grounding_bundle: Any) -> dict[str, Any]:
    expected = build_claim_evidence_map(candidate, grounding_bundle)
    if value != expected:
        raise ValidationError("CLAIM_EVIDENCE_MAP_RECOMPUTATION_MISMATCH")
    return expected
