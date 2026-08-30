"""Deterministic source limitation and unsupported-claim search."""

from __future__ import annotations

import re
from typing import Any

from .canonical import require_identifier, require_sha256, sha256_json
from .errors import ValidationError
from .grounding import validate_grounding_bundle

COUNTEREXAMPLE_SCHEMA = "uvlm.coherence.totality.counterexamples.v1"
METHOD = "EXACT_SPAN_LIMITATION_MARKERS_AND_UNSUPPORTED_CLAIMS_V1"
_TOKEN = re.compile(r"[^\W_][\w'-]*", re.UNICODE)
_MARKERS = {
    "but", "conflict", "contradicts", "failed", "failure", "however", "limitation", "limitations",
    "never", "no", "not", "pending", "reject", "risk", "uncertain", "uncertainty", "unknown",
    "unsupported", "unestablished",
}


def search_counterexamples(
    claim_map: Any,
    grounding_bundle: Any,
    *,
    run_id: str,
    candidate_id: str,
    candidate_sha256: str,
) -> dict[str, Any]:
    bundle = validate_grounding_bundle(grounding_bundle)
    if claim_map.get("candidate_sha256") != candidate_sha256:
        raise ValidationError("COUNTEREXAMPLE_CANDIDATE_BINDING_MISMATCH")
    if claim_map.get("source_sha256") != bundle["manifest"]["source_sha256"]:
        raise ValidationError("COUNTEREXAMPLE_SOURCE_BINDING_MISMATCH")
    findings: list[dict[str, Any]] = []
    for claim_id in sorted(claim_map.get("unsupported_claim_ids", [])):
        findings.append(
            {
                "finding_id": f"CE-UNSUPPORTED-{claim_id}",
                "kind": "UNSUPPORTED_CLAIM",
                "claim_id": claim_id,
                "segment_id": None,
                "segment_sha256": None,
                "exact_excerpt": None,
                "source_span": None,
                "markers": [],
                "reason_code": "CLAIM_HAS_INSUFFICIENT_EXACT_SOURCE_SUPPORT",
            }
        )
    for segment in bundle["segments"]:
        tokens = {token.casefold() for token in _TOKEN.findall(segment["text"])}
        markers = sorted(tokens & _MARKERS)
        if not markers:
            continue
        findings.append(
            {
                "finding_id": f"CE-MARKER-{segment['segment_id']}",
                "kind": "SOURCE_LIMITATION_OR_COUNTEREVIDENCE_MARKER",
                "claim_id": None,
                "segment_id": segment["segment_id"],
                "segment_sha256": segment["sha256"],
                "exact_excerpt": segment["text"],
                "source_span": {
                    "char_start": segment["char_start"], "char_end": segment["char_end"],
                    "byte_start": segment["byte_start"], "byte_end": segment["byte_end"],
                },
                "markers": markers,
                "reason_code": "SOURCE_COUNTEREVIDENCE_REQUIRES_HUMAN_REVIEW",
            }
        )
    findings.sort(key=lambda row: row["finding_id"])
    return {
        "schema_id": COUNTEREXAMPLE_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "candidate_sha256": require_sha256(candidate_sha256, "$.candidate_sha256"),
        "claim_map_sha256": sha256_json(claim_map),
        "source_sha256": bundle["manifest"]["source_sha256"],
        "method": METHOD,
        "count": len(findings),
        "findings": findings,
        "unresolved_count": len(findings),
        "authority_effect": "NONE",
    }
