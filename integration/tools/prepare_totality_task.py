"""Prepare deterministic, host-path-free inputs for a totality product run.

This integration helper only prepares bridge inputs.  CoherenceLattice remains
the authority for validating and rebuilding grounding, candidate, and AHA
artifacts during the governed route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "uvlm.coherence.totality.request_envelope.v1"
CAPTURE_SCHEMA = "uvlm.sonya.totality.captured_semantic.v1"
INPUT_MANIFEST_SCHEMA = "uvlm.triadicgate.totality_task_input_manifest.v1"
SEGMENTATION_PROFILE = "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1"
_PARAGRAPH = re.compile(r"\n[ \t]*\n+")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_REFERENCE_KEYS = {
    "source_sha256",
    "segment_id",
    "segment_sha256",
    "source_span",
    "exact_excerpt_sha256",
    "claim_text_sha256",
    "candidate_relation",
}
_SOURCE_SPAN_KEYS = {"byte_start", "byte_end", "char_start", "char_end"}
_CANDIDATE_RELATIONS = {"SUPPORTS", "LIMITS", "CONTRADICTS"}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_LOGICAL_TIME_CHARS = 128
MAX_USER_INPUT_CHARS = 100_000
MAX_SOURCE_LABEL_CHARS = 20_000
MAX_PRIVACY_BASIS_CHARS = 1_000
MAX_CAPTURE_CLAIMS = 1_000
MAX_ANSWER_CHARS = 200_000
MAX_CAPTURE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_REFERENCES_PER_CLAIM = 100


class PreparationError(ValueError):
    """A deterministic input-preparation contract failed."""


def _canonical(value: Any) -> bytes:
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PreparationError(f"INVALID_IDENTIFIER:{field}")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PreparationError(f"INVALID_SHA256:{field}")
    return value


def _text(value: str, field: str, *, maximum: int | None = None) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or (maximum is not None and len(value) > maximum)
        or unicodedata.normalize("NFC", value) != value
    ):
        raise PreparationError(f"INVALID_NFC_TEXT:{field}")
    for character in value:
        category = unicodedata.category(character)
        if character == "\x00" or 0xD800 <= ord(character) <= 0xDFFF or category == "Cf":
            raise PreparationError(f"INVALID_UNICODE_TEXT:{field}")
        if category == "Cc" and character not in {"\n", "\t"}:
            raise PreparationError(f"INVALID_CONTROL_TEXT:{field}")
    return value


def _normalize(source: bytes) -> tuple[str, bytes]:
    if not source or source.startswith(b"\xef\xbb\xbf"):
        raise PreparationError("SOURCE_EMPTY_OR_BOM")
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PreparationError("SOURCE_UTF8_INVALID") from exc
    normalized = _text(text.replace("\r\n", "\n").replace("\r", "\n").strip(), "source") + "\n"
    return normalized, normalized.encode("utf-8")


def _evidence_references(
    value: Any,
    *,
    claim_text: str,
    field: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_EVIDENCE_REFERENCES_PER_CLAIM:
        raise PreparationError(f"EVIDENCE_REFERENCE_COUNT_INVALID:{field}")
    expected_claim_sha = _sha(claim_text.encode("utf-8"))
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, reference in enumerate(value):
        path = f"{field}[{index}]"
        if not isinstance(reference, dict) or set(reference) != _EVIDENCE_REFERENCE_KEYS:
            raise PreparationError(f"EVIDENCE_REFERENCE_CONTRACT_INVALID:{path}")
        source_sha = _sha256(reference["source_sha256"], f"{path}.source_sha256")
        segment_id = _identifier(reference["segment_id"], f"{path}.segment_id")
        segment_sha = _sha256(reference["segment_sha256"], f"{path}.segment_sha256")
        excerpt_sha = _sha256(
            reference["exact_excerpt_sha256"], f"{path}.exact_excerpt_sha256"
        )
        claim_sha = _sha256(
            reference["claim_text_sha256"], f"{path}.claim_text_sha256"
        )
        if claim_sha != expected_claim_sha:
            raise PreparationError(f"EVIDENCE_CLAIM_TEXT_BINDING_MISMATCH:{path}")
        relation = reference["candidate_relation"]
        if relation not in _CANDIDATE_RELATIONS:
            raise PreparationError(f"EVIDENCE_RELATION_INVALID:{path}")
        span = reference["source_span"]
        if not isinstance(span, dict) or set(span) != _SOURCE_SPAN_KEYS:
            raise PreparationError(f"EVIDENCE_SPAN_CONTRACT_INVALID:{path}")
        if any(
            isinstance(span[name], bool)
            or not isinstance(span[name], int)
            or span[name] < 0
            for name in _SOURCE_SPAN_KEYS
        ) or not (
            span["byte_start"] < span["byte_end"]
            and span["char_start"] < span["char_end"]
        ):
            raise PreparationError(f"EVIDENCE_SPAN_INVALID:{path}")
        identity = (
            source_sha,
            segment_id,
            segment_sha,
            span["byte_start"],
            span["byte_end"],
            span["char_start"],
            span["char_end"],
            excerpt_sha,
            claim_sha,
            relation,
        )
        if identity in seen:
            raise PreparationError(f"EVIDENCE_REFERENCE_DUPLICATE:{path}")
        seen.add(identity)
        normalized.append(
            {
                "source_sha256": source_sha,
                "segment_id": segment_id,
                "segment_sha256": segment_sha,
                "source_span": {
                    "byte_start": span["byte_start"],
                    "byte_end": span["byte_end"],
                    "char_start": span["char_start"],
                    "char_end": span["char_end"],
                },
                "exact_excerpt_sha256": excerpt_sha,
                "claim_text_sha256": claim_sha,
                "candidate_relation": relation,
            }
        )
    return normalized


def _segments(normalized: str) -> list[dict[str, str]]:
    body = normalized[:-1]
    raw_parts = [part for part in _PARAGRAPH.split(body) if part.strip()]
    parts = raw_parts
    if len(raw_parts) == 1 and "\n" in raw_parts[0]:
        parts = [line for line in raw_parts[0].splitlines() if line.strip()]
    return [
        {
            "segment_id": f"SEG-{index:04d}",
            "sha256": _sha(part.strip().encode("utf-8")),
        }
        for index, part in enumerate(parts, start=1)
    ]


def _grounding_manifest(source: bytes, normalized: str, normalized_bytes: bytes) -> dict[str, Any]:
    """Reproduce the versioned grounding bridge manifest before handoff.

    This intentionally duplicates only the public bridge algorithm so the
    request can bind the exact manifest that Coherence must independently
    rebuild.  Producer/consumer parity is exercised by the integration tests.
    """

    body = normalized[:-1]
    raw_parts = [part for part in _PARAGRAPH.split(body) if part.strip()]
    parts = raw_parts
    if len(raw_parts) == 1 and "\n" in raw_parts[0]:
        parts = [line for line in raw_parts[0].splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    cursor = 0
    for index, raw_part in enumerate(parts, start=1):
        excerpt = raw_part.strip()
        start = body.find(excerpt, cursor)
        if start < 0:
            raise PreparationError("GROUNDING_SEGMENT_SPAN_INTERNAL_ERROR")
        end = start + len(excerpt)
        cursor = end
        rows.append(
            {
                "schema_id": "uvlm.coherence.totality.grounding_segment.v1",
                "segment_id": f"SEG-{index:04d}",
                "index": index,
                "text": excerpt,
                "char_start": start,
                "char_end": end,
                "byte_start": len(body[:start].encode("utf-8")),
                "byte_end": len(body[:end].encode("utf-8")),
                "sha256": _sha(excerpt.encode("utf-8")),
            }
        )
    if not rows:
        raise PreparationError("GROUNDING_NO_SEGMENTS")
    segments_bytes = b"".join(_canonical(row) for row in rows)
    source_sha = _sha(source)
    return {
        "schema_id": "uvlm.coherence.totality.grounding_bundle.v1",
        "bundle_id": f"GB-{source_sha[:20]}",
        "source_sha256": source_sha,
        "normalized_sha256": _sha(normalized_bytes),
        "source_bytes": len(source),
        "normalized_bytes": len(normalized_bytes),
        "segments_sha256": _sha(segments_bytes),
        "segment_count": len(rows),
        "segmentation": SEGMENTATION_PROFILE,
        "authority_effect": "NONE",
        "network_used": False,
    }


def _graph(
    graph_id: str,
    domain: str,
    family: str,
    first_segment: str,
    last_segment: str,
) -> dict[str, Any]:
    return {
        "graph_id": graph_id,
        "domain": domain,
        "source_family_id": family,
        "nodes": [
            {
                "node_id": "candidate",
                "node_type": "governed_stage",
                "label": "bounded candidate",
                "lineage": [first_segment],
            },
            {
                "node_id": "review",
                "node_type": "governed_stage",
                "label": "independent review",
                "lineage": [last_segment],
            },
        ],
        "relations": [
            {
                "relation_id": "precedes",
                "relation_type": "precedes",
                "source_node_id": "candidate",
                "target_node_id": "review",
                "orientation": "forward",
                "lineage": [last_segment],
            }
        ],
    }


def _aha_case(rows: list[dict[str, str]], run_id: str) -> dict[str, Any]:
    if not rows:
        raise PreparationError("AHA_REQUIRES_GROUNDING_SEGMENTS")
    first, last = rows[0]["segment_id"], rows[-1]["segment_id"]
    target = _graph("target-review-sequence", "private-integration-review", "target-private-lineage", first, last)
    donors = [
        _graph("donor-software-gate", "software-release-gate", "software-assurance", first, last),
        _graph("donor-research-gate", "research-protocol-gate", "research-governance", first, last),
    ]
    mappings = [
        {
            "mapping_id": f"map-{index}",
            "donor_graph_id": donor["graph_id"],
            "node_map": {"candidate": "candidate", "review": "review"},
            "relation_map": {"precedes": "precedes"},
            "invariant_map": {"ordering": "candidate precedes independent review"},
            "disanalogies": ["Domain-specific evidence and authority rules differ."],
            "declared_scale_or_unit_transformations": [],
        }
        for index, donor in enumerate(donors, start=1)
    ]
    return {
        "schema_id": "aha-case-v1",
        "case_id": f"AHA-{run_id}",
        "question": "Does independent review remain downstream of candidate construction?",
        "grounding_segments": rows,
        "target": target,
        "donors": donors,
        "mappings": mappings,
        "candidate_hypothesis": {
            "statement": "Independent exact-candidate review follows construction of the private completion candidate.",
            "target_observable": "review_sequence_order",
            "intervention_or_condition": "a private completion candidate exists",
            "expected_direction": "review follows candidate construction",
            "comparator_or_null": "review precedes candidate construction",
            "horizon": "the bounded local review sequence",
            "confidence_lowering_observation": "authenticated instructions place independent review before candidate construction",
        },
        "falsification_test": {
            "test_statement": "Compare the authenticated ordinal positions of private candidate construction and independent review.",
            "primary_outcome": "candidate construction precedes independent review",
            "comparator": "independent review precedes candidate construction",
            "reject_criteria": "the authenticated sequence orders independent review first",
            "feasibility_posture": "LOCAL_FEASIBLE",
            "risk_posture": "LOW",
        },
    }


def prepare(
    *,
    source_path: Path,
    output_dir: Path,
    request_id: str,
    run_id: str,
    logical_time: str,
    user_input: str,
    claims: list[str],
    uncertainty: float,
    source_label: str,
    aha_mode: str,
    task_consent: bool,
    privacy_policy_satisfied: bool,
    privacy_basis: str,
    claim_evidence_references: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        raise PreparationError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    if source_path.is_symlink() or not source_path.is_file():
        raise PreparationError("SOURCE_PATH_UNSAFE")
    if source_path.stat().st_size > MAX_SOURCE_BYTES:
        raise PreparationError("SOURCE_SIZE_LIMIT_EXCEEDED")
    _identifier(request_id, "request_id")
    _identifier(run_id, "run_id")
    _text(logical_time, "logical_time", maximum=MAX_LOGICAL_TIME_CHARS)
    _text(user_input, "user_input", maximum=MAX_USER_INPUT_CHARS)
    _text(source_label, "source_label", maximum=MAX_SOURCE_LABEL_CHARS)
    _text(privacy_basis, "privacy_basis", maximum=MAX_PRIVACY_BASIS_CHARS)
    if not isinstance(task_consent, bool) or not isinstance(privacy_policy_satisfied, bool):
        raise PreparationError("CONSENT_AND_PRIVACY_ASSERTIONS_MUST_BE_EXPLICIT_BOOLEANS")
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CAPTURE_CLAIMS:
        raise PreparationError("CLAIMS_REQUIRED")
    if isinstance(uncertainty, bool) or not math.isfinite(uncertainty) or not 0 <= uncertainty <= 1:
        raise PreparationError("UNCERTAINTY_INVALID")

    try:
        with source_path.open("rb") as stream:
            source = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise PreparationError("SOURCE_READ_FAILED") from exc
    if len(source) > MAX_SOURCE_BYTES:
        raise PreparationError("SOURCE_SIZE_LIMIT_EXCEEDED")
    normalized, normalized_bytes = _normalize(source)
    source_sha, normalized_sha = _sha(source), _sha(normalized_bytes)
    grounding_manifest = _grounding_manifest(source, normalized, normalized_bytes)
    grounding_manifest_sha = _sha(_canonical(grounding_manifest))
    validated_claims = [
        _text(claim, f"claims[{index}]", maximum=MAX_ANSWER_CHARS)
        for index, claim in enumerate(claims)
    ]
    supplied_references: list[Any]
    if claim_evidence_references is None:
        supplied_references = [[] for _ in validated_claims]
    elif (
        not isinstance(claim_evidence_references, list)
        or len(claim_evidence_references) != len(validated_claims)
    ):
        raise PreparationError("CLAIM_EVIDENCE_REFERENCE_ALIGNMENT_INVALID")
    else:
        supplied_references = claim_evidence_references
    validated_references = [
        _evidence_references(
            references,
            claim_text=validated_claims[index],
            field=f"claim_evidence_references[{index}]",
        )
        for index, references in enumerate(supplied_references)
    ]
    answer = "\n".join(validated_claims)
    if len(answer) > MAX_ANSWER_CHARS:
        raise PreparationError("ANSWER_SIZE_LIMIT_EXCEEDED")
    cursor = 0
    captured_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(validated_claims, start=1):
        start = answer.find(claim, cursor)
        if start < 0:
            raise PreparationError("CLAIM_SPAN_INTERNAL_ERROR")
        end = start + len(claim)
        captured_claims.append(
            {
                "claim_id": f"CLM-{index:04d}",
                "text": claim,
                "answer_start": start,
                "answer_end": end,
                "candidate_evidence_references": validated_references[index - 1],
            }
        )
        cursor = end

    request = {
        "schema_id": REQUEST_SCHEMA,
        "request_id": request_id,
        "run_id": run_id,
        "logical_time": logical_time,
        "kind": "document_qa",
        "user_input": user_input,
        "grounding": [
            {
                "source_kind": "grounding_bundle",
                "label": source_label,
                "media_type": "text/markdown",
                "source_id": f"SRC-{source_sha[:20]}",
                "bundle_manifest_path": "grounding/manifest.json",
                "bundle_manifest_sha256": grounding_manifest_sha,
                "normalized_sha256": normalized_sha,
                "source_sha256": source_sha,
                "metadata": {
                    "authority_effect": "NONE",
                    "network_used": False,
                    "provenance": "authenticated_local_input",
                },
            }
        ],
        "task_consent": task_consent,
        "retention_requested": False,
        "model": "captured-no-provider",
        "divergence_mode": "captured_adapter",
        "meta": {
            "preparation_profile": "integration.totality-task-input.v1",
            "source_label": source_label,
            "privacy_policy_satisfied": privacy_policy_satisfied,
            "privacy_basis": privacy_basis,
        },
    }
    capture = {
        "schema_id": CAPTURE_SCHEMA,
        "answer": answer,
        "uncertainty": float(uncertainty),
        "claims": captured_claims,
    }
    capture_bytes = _canonical(capture)
    if len(capture_bytes) > MAX_CAPTURE_BYTES:
        raise PreparationError("CAPTURE_SIZE_LIMIT_EXCEEDED")

    output_dir.mkdir(parents=True)
    files: dict[str, bytes] = {
        "source.bin": source,
        "request.json": _canonical(request),
        "captured_semantic.json": capture_bytes,
    }
    if aha_mode == "structural":
        files["aha_case.json"] = _canonical(_aha_case(_segments(normalized), run_id))
    elif aha_mode != "unavailable":
        raise PreparationError("AHA_MODE_INVALID")
    for name, payload in files.items():
        (output_dir / name).write_bytes(payload)
    manifest = {
        "schema_id": INPUT_MANIFEST_SCHEMA,
        "run_id": run_id,
        "logical_time": logical_time,
        "source_label": source_label,
        "segmentation_profile": SEGMENTATION_PROFILE,
        "aha_mode": aha_mode.upper(),
        "request_sha256": _sha(files["request.json"]),
        "grounding_manifest_sha256": grounding_manifest_sha,
        "task_consent_asserted": task_consent,
        "privacy_policy_satisfied_asserted": privacy_policy_satisfied,
        "privacy_basis": privacy_basis,
        "artifacts": [
            {"path": name, "sha256": _sha(payload), "bytes": len(payload)}
            for name, payload in sorted(files.items())
        ],
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "publication_performed": False,
        "deployment_performed": False,
        "release_performed": False,
        "authority_effect": "NONE",
    }
    (output_dir / "input_manifest.json").write_bytes(_canonical(manifest))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--logical-time", required=True)
    parser.add_argument("--user-input", required=True)
    parser.add_argument("--claim", action="append", required=True)
    parser.add_argument("--uncertainty", required=True, type=float)
    parser.add_argument("--source-label", required=True)
    parser.add_argument("--aha-mode", choices=("unavailable", "structural"), default="unavailable")
    parser.add_argument("--task-consent", choices=("true", "false"), required=True)
    parser.add_argument("--privacy-policy-satisfied", choices=("true", "false"), required=True)
    parser.add_argument("--privacy-basis", required=True)
    arguments = parser.parse_args()
    manifest = prepare(
        source_path=arguments.source.resolve(),
        output_dir=arguments.out_dir.resolve(),
        request_id=arguments.request_id,
        run_id=arguments.run_id,
        logical_time=arguments.logical_time,
        user_input=arguments.user_input,
        claims=arguments.claim,
        uncertainty=arguments.uncertainty,
        source_label=arguments.source_label,
        aha_mode=arguments.aha_mode,
        task_consent=arguments.task_consent == "true",
        privacy_policy_satisfied=arguments.privacy_policy_satisfied == "true",
        privacy_basis=arguments.privacy_basis,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
