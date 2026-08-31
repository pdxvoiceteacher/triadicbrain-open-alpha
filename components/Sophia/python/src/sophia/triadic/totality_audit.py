"""Independent, deterministic audit of a Coherence totality run.

Sophia treats every upstream artifact as untrusted input.  The auditor performs
file-only recomputation and writes one bounded governance packet; it never
generates, repairs, or rewrites a candidate or any source artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


AUDIT_SCHEMA = "uvlm.sophia.totality.audit_packet.v1"
AUDIT_VERSION = "1.0"
OUTPUT_NAME = "sophia_audit_packet.json"
COHERENCE_REPOSITORY = "pdxvoiceteacher/CoherenceLattice"
SOPHIA_REPOSITORY = "pdxvoiceteacher/Sophia"

REQUEST_SCHEMA = "uvlm.coherence.totality.request_envelope.v1"
GROUNDING_SCHEMA = "uvlm.coherence.totality.grounding_bundle.v1"
SEGMENT_SCHEMA = "uvlm.coherence.totality.grounding_segment.v1"
CANDIDATE_SCHEMA = "uvlm.sonya.totality.candidate_packet.v1"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
RFC3339_UTC = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,9})?Z$"
)
TOKEN = re.compile(r"[^\W_][\w'-]*", re.UNICODE)
PARAGRAPH = re.compile(r"\n[ \t]*\n+")
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "with",
}

INPUT_PATHS = (
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

OPTIONAL_INPUT_PATHS = frozenset({"pmr_consent.json"})
SEALED_RUN_MARKERS = (
    "run_manifest.json",
    "sealed_artifact_manifest.json",
    "checksums.sha256",
)
MAX_JSON_INPUT_BYTES = 4 * 1024 * 1024
MAX_JSONL_INPUT_BYTES = 16 * 1024 * 1024
MAX_GROUNDING_INPUT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024
MAX_RAW_OUTPUT_BYTES = 2 * 1024 * 1024

PRIVATE_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "internal_deliberation",
    "private_reasoning",
    "scratchpad",
    "thinking",
    "raw_model_output",
    "raw_output",
}
POSITIVE_AUTHORITY_KEYS = {
    "truth_certified",
    "final_answer_authorized",
    "memory_write_authorized",
    "training_authorized",
    "canonization_authorized",
    "publication_authorized",
    "deployment_authorized",
    "release_authorized",
    "self_approved",
    "governance_approved",
}

# Unicode provenance: UCD 17.0.0 DerivedCoreProperties.txt,
# Default_Ignorable_Code_Point; source SHA-256
# 24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08.
# License: Unicode License V3; see the projection root THIRD_PARTY_NOTICES.md.
# Local frozen copy of the cross-owner Unicode DerivedCoreProperties
# Default_Ignorable_Code_Point profile.  Sophia must not import Coherence code
# to validate an upstream artifact.
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


class InputContractError(ValueError):
    """An untrusted input could not be parsed safely."""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    artifact: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "artifact": self.artifact,
            "detail": self.detail,
        }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_unicode(value: str, path: str) -> None:
    if unicodedata.normalize("NFC", value) != value:
        raise InputContractError(f"UNICODE_NFC_REQUIRED:{path}")
    for char in value:
        codepoint = ord(char)
        category = unicodedata.category(char)
        if char == "\x00" or 0xD800 <= codepoint <= 0xDFFF:
            raise InputContractError(f"UNICODE_INVALID:{path}")
        if _is_default_ignorable_code_point(codepoint):
            raise InputContractError(f"UNICODE_DEFAULT_IGNORABLE:{path}")
        if category == "Cc" and char not in {"\n", "\t"}:
            raise InputContractError(f"UNICODE_CONTROL:{path}")


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InputContractError(f"NONFINITE_NUMBER:{path}")
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
                raise InputContractError(f"JSON_KEY_INVALID:{path}")
            _validate_unicode(key, f"{path}.<key>")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise InputContractError(f"JSON_TYPE_INVALID:{path}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputContractError(f"DUPLICATE_JSON_MEMBER:{key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise InputContractError(f"NONFINITE_NUMBER:{value}")


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


def _canonical_sha256(value: Any) -> str:
    return _sha256(_canonical_json_bytes(value))


def _parse_json(raw: bytes, artifact: str, *, require_canonical: bool = True) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise InputContractError(f"JSON_BOM_PROHIBITED:{artifact}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InputContractError(f"JSON_UTF8_INVALID:{artifact}") from exc
    _validate_unicode(text, artifact)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, InputContractError) as exc:
        raise InputContractError(f"JSON_INVALID:{artifact}") from exc
    if not isinstance(value, dict):
        raise InputContractError(f"JSON_OBJECT_REQUIRED:{artifact}")
    _validate_json_value(value)
    if require_canonical and raw != _canonical_json_bytes(value):
        raise InputContractError(f"JSON_NONCANONICAL:{artifact}")
    return value


def _parse_jsonl(raw: bytes, artifact: str) -> list[dict[str, Any]]:
    if not raw:
        raise InputContractError(f"JSONL_EMPTY:{artifact}")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(keepends=True), start=1):
        if not line.endswith(b"\n"):
            raise InputContractError(f"JSONL_FINAL_LF_REQUIRED:{artifact}")
        row = _parse_json(line, f"{artifact}:{index}")
        rows.append(row)
    if raw != b"".join(_canonical_json_bytes(row) for row in rows):
        raise InputContractError(f"JSONL_NONCANONICAL:{artifact}")
    return rows


def _exact_keys(value: Any, required: Iterable[str], path: str) -> bool:
    return isinstance(value, dict) and set(value) == set(required)


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _walk_has_prohibited(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in PRIVATE_KEYS
            or (key in POSITIVE_AUTHORITY_KEYS and item is True)
            or _walk_has_prohibited(item)
            for key, item in value.items()
        )
    return isinstance(value, list) and any(_walk_has_prohibited(item) for item in value)


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _resolved_member(root: Path, relative: str) -> Path | None:
    path = root.joinpath(*relative.split("/"))
    try:
        cursor = root
        for part in Path(relative).parts:
            cursor /= part
            if _link_like(cursor):
                return None
        if not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _write_packet(path: Path, packet: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sophia-totality-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_json_bytes(packet))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _add(
    findings: list[Finding],
    condition: bool,
    code: str,
    severity: str,
    artifact: str,
    detail: str,
) -> None:
    if not condition:
        findings.append(Finding(code, severity, artifact, detail))


def _unique_findings(findings: list[Finding]) -> list[Finding]:
    unique: dict[tuple[str, str, str, str], Finding] = {}
    for finding in findings:
        unique[(finding.code, finding.severity, finding.artifact, finding.detail)] = finding
    return [unique[key] for key in sorted(unique)]


# Contract-specific independent validators follow below.  They intentionally do
# not import CoherenceLattice or Sonya implementation code.


def _validate_request(value: dict[str, Any], findings: list[Finding]) -> dict[str, Any]:
    artifact = "request.json"
    keys = {
        "schema_id",
        "request_id",
        "run_id",
        "logical_time",
        "kind",
        "user_input",
        "grounding",
        "task_consent",
        "retention_requested",
        "model",
        "divergence_mode",
        "meta",
    }
    structural = _exact_keys(value, keys, artifact)
    _add(findings, structural, "REQUEST_CONTRACT_INVALID", "REJECT", artifact, "exact request fields required")
    if not structural:
        return {"privacy_policy_satisfied": False, "privacy_basis_valid": False}
    valid = (
        value["schema_id"] == REQUEST_SCHEMA
        and _identifier(value["request_id"])
        and _identifier(value["run_id"])
        and _text(value["logical_time"])
        and len(value["logical_time"]) <= 128
        and value["kind"] in {"plain_text", "grounded_text", "document_qa", "batch"}
        and _text(value["user_input"])
        and len(value["user_input"]) <= 100_000
        and isinstance(value["grounding"], list)
        and len(value["grounding"]) <= 1000
        and isinstance(value["task_consent"], bool)
        and isinstance(value["retention_requested"], bool)
        and (
            value["model"] is None
            or (_text(value["model"]) and len(value["model"]) <= 256)
        )
        and (
            value["divergence_mode"] is None
            or (
                _text(value["divergence_mode"])
                and len(value["divergence_mode"]) <= 256
            )
        )
        and isinstance(value["meta"], dict)
    )
    _add(findings, valid, "REQUEST_CONTRACT_INVALID", "REJECT", artifact, "request scalar contract failed")
    if not isinstance(value["grounding"], list):
        return {"privacy_policy_satisfied": False, "privacy_basis_valid": False}
    allowed = {
        "source_kind",
        "label",
        "uri",
        "media_type",
        "text",
        "source_id",
        "bundle_manifest_path",
        "bundle_manifest_sha256",
        "normalized_sha256",
        "source_sha256",
        "metadata",
    }
    for index, reference in enumerate(value["grounding"]):
        path = f"request.json#grounding/{index}"
        good = (
            isinstance(reference, dict)
            and "source_kind" in reference
            and set(reference) <= allowed
            and reference.get("source_kind")
            in {"inline_text", "file_text", "atlas_prior", "fixture", "grounding_bundle"}
        )
        if good:
            for name, item in reference.items():
                if name in {"bundle_manifest_sha256", "source_sha256", "normalized_sha256"}:
                    good &= _digest(item)
                elif name == "metadata":
                    good &= isinstance(item, dict)
                elif name != "source_kind":
                    good &= item is None or (_text(item) and len(item) <= 20_000)
            if reference.get("source_kind") == "grounding_bundle":
                good &= all(
                    reference.get(name)
                    for name in (
                        "source_id", "media_type", "bundle_manifest_path",
                        "bundle_manifest_sha256", "source_sha256", "normalized_sha256",
                    )
                )
                good &= (
                    reference.get("media_type") in {"text/plain", "text/markdown"}
                    and isinstance(reference.get("source_id"), str)
                    and re.fullmatch(r"SRC-[0-9a-f]{20}", reference["source_id"])
                    is not None
                    and reference.get("text") is None
                )
        _add(findings, good, "REQUEST_GROUNDING_REFERENCE_INVALID", "REJECT", path, "grounding reference contract failed")
    bundle_references = [
        reference
        for reference in value["grounding"]
        if isinstance(reference, dict) and reference.get("source_kind") == "grounding_bundle"
    ]
    _add(
        findings,
        len(bundle_references) == 1,
        "REQUEST_GROUNDING_BUNDLE_CARDINALITY_INVALID",
        "REJECT",
        artifact,
        "totality audit requires exactly one canonical grounding bundle reference",
    )
    if value["kind"] == "plain_text":
        _add(findings, not value["grounding"], "REQUEST_GROUNDING_REFERENCE_INVALID", "REJECT", artifact, "plain_text cannot carry grounding")
    if value["kind"] in {"grounded_text", "document_qa"}:
        _add(findings, bool(value["grounding"]), "GROUNDING_INADEQUATE", "HOLD", artifact, "grounded task has no grounding reference")
    meta = value["meta"] if isinstance(value["meta"], dict) else {}
    privacy = meta.get("privacy_policy_satisfied")
    privacy_basis = meta.get("privacy_basis")
    privacy_contract_valid = (
        isinstance(privacy, bool)
        and isinstance(privacy_basis, str)
        and bool(privacy_basis.strip())
        and len(privacy_basis) <= 1000
    )
    _add(
        findings,
        privacy_contract_valid,
        "REQUEST_PRIVACY_CONTRACT_INVALID",
        "REJECT",
        artifact,
        "privacy_policy_satisfied must be boolean and privacy_basis must be bounded nonempty text",
    )
    return {
        "privacy_policy_satisfied": privacy is True and privacy_contract_valid,
        "privacy_basis_valid": privacy_contract_valid,
        "task_consent": value["task_consent"] is True,
        "retention_requested": value["retention_requested"] is True,
    }


def _normalize_source(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    _validate_unicode(normalized, "grounding/source.bin")
    if not normalized:
        raise InputContractError("GROUNDING_SOURCE_EMPTY")
    return normalized + "\n"


def _expected_segments(normalized_source: str) -> list[dict[str, Any]]:
    body = normalized_source[:-1]
    raw_parts = [part for part in PARAGRAPH.split(body) if part.strip()]
    parts = raw_parts
    if len(raw_parts) == 1 and "\n" in raw_parts[0]:
        parts = [line for line in raw_parts[0].splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    cursor = 0
    for index, raw_part in enumerate(parts, start=1):
        excerpt = raw_part.strip()
        start = body.find(excerpt, cursor)
        end = start + len(excerpt)
        cursor = end
        rows.append(
            {
                "schema_id": SEGMENT_SCHEMA,
                "segment_id": f"SEG-{index:04d}",
                "index": index,
                "text": excerpt,
                "char_start": start,
                "char_end": end,
                "byte_start": len(body[:start].encode("utf-8")),
                "byte_end": len(body[:end].encode("utf-8")),
                "sha256": _sha256(excerpt.encode("utf-8")),
            }
        )
    return rows


def _validate_grounding(
    request: dict[str, Any],
    manifest: dict[str, Any],
    source_raw: bytes,
    normalized_raw: bytes,
    segments_raw: bytes,
    segments: list[dict[str, Any]],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "grounding/manifest.json"
    keys = {
        "schema_id",
        "bundle_id",
        "source_sha256",
        "normalized_sha256",
        "source_bytes",
        "normalized_bytes",
        "segments_sha256",
        "segment_count",
        "segmentation",
        "authority_effect",
        "network_used",
    }
    structural = _exact_keys(manifest, keys, artifact)
    _add(findings, structural, "GROUNDING_CONTRACT_INVALID", "REJECT", artifact, "exact grounding manifest fields required")
    if structural:
        scalar_ok = (
            manifest["schema_id"] == GROUNDING_SCHEMA
            and _identifier(manifest["bundle_id"])
            and all(_digest(manifest[name]) for name in ("source_sha256", "normalized_sha256", "segments_sha256"))
            and all(_integer(manifest[name]) and manifest[name] >= 0 for name in ("source_bytes", "normalized_bytes", "segment_count"))
            and manifest["segmentation"] == "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1"
            and manifest["authority_effect"] == "NONE"
            and manifest["network_used"] is False
        )
        _add(findings, scalar_ok, "GROUNDING_CONTRACT_INVALID", "REJECT", artifact, "grounding manifest scalar contract failed")
        identity_ok = (
            manifest["source_sha256"] == _sha256(source_raw)
            and manifest["normalized_sha256"] == _sha256(normalized_raw)
            and manifest["segments_sha256"] == _sha256(segments_raw)
            and manifest["source_bytes"] == len(source_raw)
            and manifest["normalized_bytes"] == len(normalized_raw)
            and manifest["segment_count"] == len(segments)
        )
        _add(findings, identity_ok, "GROUNDING_IDENTITY_MISMATCH", "REJECT", artifact, "manifest hashes, sizes, or segment count do not match bytes")
    try:
        source_text = source_raw.decode("utf-8", errors="strict")
        normalized_text = normalized_raw.decode("utf-8", errors="strict")
        _validate_unicode(normalized_text, "grounding/normalized_source.txt")
        normalization_ok = normalized_text == _normalize_source(source_text)
    except (UnicodeDecodeError, InputContractError):
        normalized_text = ""
        normalization_ok = False
    _add(findings, normalization_ok, "GROUNDING_NORMALIZATION_MISMATCH", "REJECT", "grounding/normalized_source.txt", "normalized source is not independently reproducible")
    expected_segments = _expected_segments(normalized_text) if normalization_ok else []

    segment_keys = {
        "schema_id",
        "segment_id",
        "index",
        "text",
        "char_start",
        "char_end",
        "byte_start",
        "byte_end",
        "sha256",
    }
    prior_char_end = 0
    prior_byte_end = 0
    identities: set[str] = set()
    index_by_id: dict[str, dict[str, Any]] = {}
    for ordinal, segment in enumerate(segments, start=1):
        row_path = f"grounding/segments.jsonl#{ordinal}"
        row_ok = _exact_keys(segment, segment_keys, row_path)
        if row_ok:
            row_ok = (
                segment["schema_id"] == SEGMENT_SCHEMA
                and _identifier(segment["segment_id"])
                and segment["segment_id"] not in identities
                and segment["index"] == ordinal
                and _text(segment["text"])
                and all(_integer(segment[name]) and segment[name] >= 0 for name in ("char_start", "char_end", "byte_start", "byte_end"))
                and segment["char_start"] >= prior_char_end
                and segment["char_end"] > segment["char_start"]
                and segment["byte_start"] >= prior_byte_end
                and segment["byte_end"] > segment["byte_start"]
                and _digest(segment["sha256"])
            )
        _add(findings, row_ok, "GROUNDING_SEGMENT_INVALID", "REJECT", row_path, "segment structure, identity, or order failed")
        if not row_ok:
            continue
        char_start, char_end = segment["char_start"], segment["char_end"]
        byte_start, byte_end = segment["byte_start"], segment["byte_end"]
        encoded = normalized_text.encode("utf-8")
        span_ok = (
            char_end <= len(normalized_text)
            and byte_end <= len(encoded)
            and normalized_text[char_start:char_end] == segment["text"]
            and encoded[byte_start:byte_end] == segment["text"].encode("utf-8")
            and len(normalized_text[:char_start].encode("utf-8")) == byte_start
            and segment["sha256"] == _sha256(segment["text"].encode("utf-8"))
        )
        _add(findings, span_ok, "GROUNDING_SEGMENT_SPAN_MISMATCH", "REJECT", row_path, "segment span or digest is not reproducible from normalized source")
        identities.add(segment["segment_id"])
        index_by_id[segment["segment_id"]] = segment
        prior_char_end, prior_byte_end = char_end, byte_end

    _add(
        findings,
        bool(expected_segments) and segments == expected_segments,
        "GROUNDING_SEGMENTATION_MISMATCH",
        "REJECT",
        "grounding/segments.jsonl",
        "complete segment content and order are not independently reproducible",
    )

    references = request.get("grounding") if isinstance(request.get("grounding"), list) else []
    matching_references = [
        reference
        for reference in references
        if (
        isinstance(reference, dict)
        and reference.get("source_kind") == "grounding_bundle"
        and reference.get("bundle_manifest_sha256") == _canonical_sha256(manifest)
        and reference.get("source_sha256") == _sha256(source_raw)
        and reference.get("normalized_sha256") == _sha256(normalized_raw)
        and reference.get("bundle_manifest_path") == "grounding/manifest.json"
        and reference.get("source_id") == f"SRC-{_sha256(source_raw)[:20]}"
        and reference.get("media_type") in {"text/plain", "text/markdown"}
        )
    ]
    bound = len(matching_references) == 1
    _add(findings, bound, "GROUNDING_REQUEST_BINDING_MISMATCH", "REJECT", artifact, "request has no exact grounding bundle binding")
    _add(findings, bool(segments), "GROUNDING_INADEQUATE", "HOLD", artifact, "no usable source segments")
    return {"segments_by_id": index_by_id, "request_binding_valid": bound, "segment_count": len(segments)}


def _validate_candidate(
    request: dict[str, Any],
    candidate: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "candidate_packet.json"
    flags = {
        "candidate_not_final_answer",
        "model_output_not_authority",
        "not_truth_certification",
        "not_memory_authorization",
        "not_training_authorization",
        "not_publication_authorization",
        "not_deployment_authority",
        "not_release_authorization",
        "human_review_required",
    }
    keys = {
        "schema_id",
        "candidate_id",
        "run_id",
        "logical_time",
        "request_sha256",
        "adapter_id",
        "model_identity",
        "raw_output_sha256",
        "answer",
        "uncertainty",
        "claims",
    } | flags
    structural = _exact_keys(candidate, keys, artifact)
    _add(findings, structural, "CANDIDATE_CONTRACT_INVALID", "REJECT", artifact, "exact candidate fields required")
    claims_by_id: dict[str, dict[str, Any]] = {}
    if not structural:
        return {"claims_by_id": claims_by_id}
    seed_valid = _digest(candidate["request_sha256"]) and _digest(candidate["raw_output_sha256"])
    expected_candidate_id = (
        "CAND-" + _sha256((candidate["request_sha256"] + candidate["raw_output_sha256"]).encode("ascii"))[:24]
        if seed_valid
        else None
    )
    scalar_ok = (
        candidate["schema_id"] == CANDIDATE_SCHEMA
        and _identifier(candidate["candidate_id"])
        and candidate["candidate_id"] == expected_candidate_id
        and candidate["run_id"] == request.get("run_id")
        and candidate["logical_time"] == request.get("logical_time")
        and _text(candidate["logical_time"])
        and len(candidate["logical_time"]) <= 128
        and candidate["request_sha256"] == _canonical_sha256(request)
        and _identifier(candidate["adapter_id"])
        and _text(candidate["model_identity"])
        and len(candidate["model_identity"]) <= 256
        and _digest(candidate["raw_output_sha256"])
        and _text(candidate["answer"])
        and len(candidate["answer"]) <= 200_000
        and _number(candidate["uncertainty"])
        and 0 <= float(candidate["uncertainty"]) <= 1
        and isinstance(candidate["claims"], list)
        and bool(candidate["claims"])
        and len(candidate["claims"]) <= 1000
        and all(candidate[name] is True for name in flags)
    )
    _add(findings, scalar_ok, "CANDIDATE_CONTRACT_INVALID", "REJECT", artifact, "candidate scalar, identity, or boundary contract failed")
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
    span_keys = {"byte_start", "byte_end", "char_start", "char_end"}
    for ordinal, claim in enumerate(candidate["claims"] if isinstance(candidate["claims"], list) else [], start=1):
        claim_path = f"candidate_packet.json#claims/{ordinal - 1}"
        good = _exact_keys(claim, claim_keys, claim_path)
        if good:
            start, end = claim["answer_start"], claim["answer_end"]
            good = (
                _identifier(claim["claim_id"])
                and claim["claim_id"] not in claims_by_id
                and _text(claim["text"])
                and _integer(start)
                and _integer(end)
                and 0 <= start < end <= len(candidate["answer"])
                and candidate["answer"][start:end] == claim["text"]
                and isinstance(claim["candidate_evidence_references"], list)
                and len(claim["candidate_evidence_references"]) <= 100
            )
        reference_identities: set[tuple[Any, ...]] = set()
        references_valid = good
        for reference_index, reference in enumerate(
            claim.get("candidate_evidence_references", [])
            if isinstance(claim, dict)
            and isinstance(claim.get("candidate_evidence_references"), list)
            else []
        ):
            reference_path = (
                f"{claim_path}.candidate_evidence_references/{reference_index}"
            )
            reference_ok = _exact_keys(reference, reference_keys, reference_path)
            span = reference.get("source_span") if isinstance(reference, dict) else None
            if reference_ok:
                reference_ok = (
                    _digest(reference["source_sha256"])
                    and _identifier(reference["segment_id"])
                    and _digest(reference["segment_sha256"])
                    and _digest(reference["exact_excerpt_sha256"])
                    and _digest(reference["claim_text_sha256"])
                    and reference["claim_text_sha256"]
                    == _sha256(claim["text"].encode("utf-8"))
                    and reference["candidate_relation"]
                    in {"SUPPORTS", "LIMITS", "CONTRADICTS"}
                    and _exact_keys(span, span_keys, f"{reference_path}.source_span")
                    and all(
                        _integer(span[name]) and span[name] >= 0
                        for name in span_keys
                    )
                    and span["byte_start"] < span["byte_end"]
                    and span["char_start"] < span["char_end"]
                )
            identity: tuple[Any, ...] | None = None
            if reference_ok:
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
                reference_ok = identity not in reference_identities
            _add(
                findings,
                reference_ok,
                "CANDIDATE_EVIDENCE_REFERENCE_INVALID",
                "REJECT",
                reference_path,
                "evidence reference shape, claim binding, relation, span, or uniqueness failed",
            )
            if reference_ok and identity is not None:
                reference_identities.add(identity)
            references_valid &= reference_ok
        good = good and references_valid
        _add(findings, good, "CANDIDATE_CLAIM_SPAN_INVALID", "REJECT", claim_path, "claim is not an exact unique answer span")
        if good:
            claims_by_id[claim["claim_id"]] = claim
    return {"claims_by_id": claims_by_id, "candidate_sha256": _canonical_sha256(candidate)}


def _validate_quarantine_receipt(
    request: dict[str, Any],
    candidate: dict[str, Any],
    receipt: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    """Validate quarantine identity without reading quarantined raw content."""

    artifact = "sonya/quarantine_receipt.json"
    keys = {
        "schema_id",
        "adapter_id",
        "request_sha256",
        "raw_output_sha256",
        "raw_output_bytes",
        "quarantine_member",
        "raw_output_quarantined",
        "network_used",
        "provider_invoked",
        "memory_written",
        "training_used",
        "authority_effect",
    }
    structural = _exact_keys(receipt, keys, artifact)
    _add(
        findings,
        structural,
        "QUARANTINE_RECEIPT_INVALID",
        "REJECT",
        artifact,
        "exact quarantine receipt fields required",
    )
    if not structural:
        return {"receipt_sha256": _canonical_sha256(receipt)}
    valid = (
        receipt["schema_id"] == "uvlm.sonya.totality.raw_quarantine_receipt.v1"
        and _identifier(receipt["adapter_id"])
        and receipt["adapter_id"] == candidate.get("adapter_id")
        and receipt["request_sha256"] == _canonical_sha256(request)
        and receipt["request_sha256"] == candidate.get("request_sha256")
        and _digest(receipt["raw_output_sha256"])
        and receipt["raw_output_sha256"] == candidate.get("raw_output_sha256")
        and _integer(receipt["raw_output_bytes"])
        and 0 < receipt["raw_output_bytes"] <= MAX_RAW_OUTPUT_BYTES
        and receipt["quarantine_member"] == "raw_output.quarantine"
        and receipt["raw_output_quarantined"] is True
        and receipt["network_used"] is False
        and receipt["provider_invoked"] is False
        and receipt["memory_written"] is False
        and receipt["training_used"] is False
        and receipt["authority_effect"] == "NONE"
    )
    _add(
        findings,
        valid,
        "QUARANTINE_RECEIPT_OR_BINDING_INVALID",
        "REJECT",
        artifact,
        "receipt identity, request/candidate binding, or no-effects posture failed",
    )
    return {
        "receipt_sha256": _canonical_sha256(receipt),
        "raw_output_sha256": receipt.get("raw_output_sha256"),
        "raw_output_bytes": receipt.get("raw_output_bytes"),
    }


def _validate_quarantine_verification_receipt(
    request: dict[str, Any],
    candidate: dict[str, Any],
    receipt: dict[str, Any],
    verification_receipt: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    """Validate Coherence's raw-free proof without ingesting quarantine bytes."""

    artifact = "sonya/quarantine_verification_receipt.json"
    keys = {
        "schema_id",
        "run_id",
        "logical_time",
        "request_sha256",
        "adapter_id",
        "quarantine_member",
        "raw_output_sha256",
        "raw_output_bytes",
        "quarantine_receipt_sha256",
        "candidate_id",
        "candidate_sha256",
        "verification",
        "raw_output_disclosed",
        "effects",
        "authority_effect",
    }
    verification_keys = {
        "path_binding_valid",
        "exact_byte_count_valid",
        "exact_sha256_valid",
        "strict_utf8_json_valid",
        "semantic_capture_schema_valid",
        "candidate_binding_valid",
    }
    effects_keys = {
        "network",
        "provider_invocation",
        "memory_write",
        "training",
        "publication",
        "deployment",
        "release",
    }
    structural = _exact_keys(verification_receipt, keys, artifact)
    _add(
        findings,
        structural,
        "QUARANTINE_VERIFICATION_RECEIPT_INVALID",
        "REJECT",
        artifact,
        "exact raw-free quarantine verification receipt fields required",
    )
    if not structural:
        return {"verification_receipt_sha256": _canonical_sha256(verification_receipt)}
    verification = verification_receipt["verification"]
    effects = verification_receipt["effects"]
    nested_valid = (
        _exact_keys(verification, verification_keys, f"{artifact}#verification")
        and all(verification.get(name) is True for name in verification_keys)
        and _exact_keys(effects, effects_keys, f"{artifact}#effects")
        and all(effects.get(name) is False for name in effects_keys)
    )
    valid = (
        verification_receipt["schema_id"]
        == "uvlm.sonya.totality.quarantine_verification_receipt.v1"
        and verification_receipt["run_id"] == request.get("run_id")
        and verification_receipt["run_id"] == candidate.get("run_id")
        and verification_receipt["logical_time"] == request.get("logical_time")
        and verification_receipt["logical_time"] == candidate.get("logical_time")
        and verification_receipt["request_sha256"] == _canonical_sha256(request)
        and verification_receipt["request_sha256"] == candidate.get("request_sha256")
        and verification_receipt["adapter_id"] == receipt.get("adapter_id")
        and verification_receipt["adapter_id"] == candidate.get("adapter_id")
        and verification_receipt["quarantine_member"] == receipt.get("quarantine_member")
        and verification_receipt["raw_output_sha256"] == receipt.get("raw_output_sha256")
        and verification_receipt["raw_output_sha256"] == candidate.get("raw_output_sha256")
        and verification_receipt["raw_output_bytes"] == receipt.get("raw_output_bytes")
        and verification_receipt["quarantine_receipt_sha256"]
        == _canonical_sha256(receipt)
        and verification_receipt["candidate_id"] == candidate.get("candidate_id")
        and verification_receipt["candidate_sha256"] == _canonical_sha256(candidate)
        and all(
            _digest(verification_receipt[name])
            for name in (
                "request_sha256",
                "raw_output_sha256",
                "quarantine_receipt_sha256",
                "candidate_sha256",
            )
        )
        and _identifier(verification_receipt["run_id"])
        and _identifier(verification_receipt["candidate_id"])
        and _identifier(verification_receipt["adapter_id"])
        and _text(verification_receipt["logical_time"])
        and _text(verification_receipt["quarantine_member"])
        and _integer(verification_receipt["raw_output_bytes"])
        and 0 < verification_receipt["raw_output_bytes"] <= MAX_RAW_OUTPUT_BYTES
        and nested_valid
        and verification_receipt["raw_output_disclosed"] is False
        and verification_receipt["authority_effect"] == "NONE"
    )
    _add(
        findings,
        valid,
        "QUARANTINE_VERIFICATION_OR_BINDING_INVALID",
        "REJECT",
        artifact,
        "Coherence raw-free proof, parent bindings, or no-effects posture failed",
    )
    return {
        "verification_receipt_sha256": _canonical_sha256(verification_receipt),
        "coherence_exact_byte_verification_recorded": (
            valid
            and verification.get("exact_byte_count_valid") is True
            and verification.get("exact_sha256_valid") is True
        ),
    }


def _rfc3339_utc(value: Any) -> tuple[datetime, int] | None:
    if not isinstance(value, str) or not RFC3339_UTC.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value[:19] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != timezone.utc:
        return None
    fraction = value[20:-1] if len(value) > 20 else ""
    nanoseconds = int(fraction.ljust(9, "0")) if fraction else 0
    return parsed, nanoseconds


def _expected_pmr_no_write_receipt(
    request: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_id": "uvlm.pmr.totality.receipt.v1",
        "run_id": request.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "logical_time": request.get("logical_time"),
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": None,
        "consent_status": "NOT_GRANTED",
        "reason_codes": ["PMR_SEPARATE_CONSENT_NOT_GRANTED"],
        "events": [],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }


def _expected_pmr_consent_receipt(consent: dict[str, Any]) -> dict[str, Any]:
    granted = consent.get("decision") == "GRANT"
    event = {
        "schema_id": "uvlm.pmr.totality.reference_event.v1",
        "sequence": 1,
        "logical_time": "PMR+000001",
        "event_type": "CONSENT_GRANTED" if granted else "CONSENT_DENIED",
        "consent_id": consent.get("consent_id"),
        "run_id": consent.get("run_id"),
        "candidate_id": consent.get("candidate_id"),
        "lineage_id": None,
        "detail": {
            "scope": consent.get("scope"),
            "quota_bytes": consent.get("quota_bytes"),
        },
        "persistent_write_performed": False,
        "training_used": False,
        "federation_used": False,
        "authority_effect": "NONE",
    }
    return {
        "schema_id": "uvlm.pmr.totality.receipt.v1",
        "run_id": consent.get("run_id"),
        "candidate_id": consent.get("candidate_id"),
        "logical_time": consent.get("logical_time"),
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": consent.get("consent_id"),
        "consent_status": "ACTIVE" if granted else "INACTIVE",
        "reason_codes": ["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"],
        "events": [event],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }


def _validate_pmr_boundary(
    request: dict[str, Any],
    candidate: dict[str, Any],
    consent: dict[str, Any] | None,
    *,
    consent_file_present: bool,
    receipt: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    """Validate a no-write PMR boundary; never retrieve or retain a reference."""

    consent_artifact = "pmr_consent.json"
    receipt_artifact = "pmr_receipt.json"
    consent_keys = {
        "schema_id",
        "consent_id",
        "run_id",
        "candidate_id",
        "logical_time",
        "decision",
        "scope",
        "quota_bytes",
        "expires_logical_time",
        "training_allowed",
        "federation_allowed",
        "authority_effect",
    }
    retention_requested = request.get("retention_requested") is True
    consent_valid = False
    consent_granted = False
    if consent is not None:
        structural = _exact_keys(consent, consent_keys, consent_artifact)
        expiry = consent.get("expires_logical_time") if structural else None
        expiry_valid = expiry is None
        if isinstance(expiry, str):
            issued_at = _rfc3339_utc(consent.get("logical_time"))
            expires_at = _rfc3339_utc(expiry)
            expiry_valid = (
                issued_at is not None
                and expires_at is not None
                and expires_at > issued_at
            )
        consent_valid = (
            structural
            and consent["schema_id"] == "uvlm.pmr.totality.consent.v1"
            and _identifier(consent["consent_id"])
            and consent["run_id"] == request.get("run_id")
            and consent["run_id"] == candidate.get("run_id")
            and consent["candidate_id"] == candidate.get("candidate_id")
            and consent["logical_time"] == request.get("logical_time")
            and consent["logical_time"] == candidate.get("logical_time")
            and _text(consent["logical_time"])
            and len(consent["logical_time"]) <= 128
            and "\n" not in consent["logical_time"]
            and "\r" not in consent["logical_time"]
            and consent["decision"] in {"GRANT", "DENY"}
            and consent["scope"] == "PROVENANCE_REFERENCE_ONLY"
            and _integer(consent["quota_bytes"])
            and 1 <= consent["quota_bytes"] <= 100_000_000
            and expiry_valid
            and consent["training_allowed"] is False
            and consent["federation_allowed"] is False
            and consent["authority_effect"] == "NONE"
            and retention_requested
        )
        _add(
            findings,
            consent_valid,
            "PMR_CONSENT_OR_CONTEXT_INVALID",
            "REJECT",
            consent_artifact,
            "consent contract, context, expiry, or no-authority posture failed",
        )
        consent_granted = consent_valid and consent.get("decision") == "GRANT"
        expected_receipt = _expected_pmr_consent_receipt(consent)
    else:
        _add(
            findings,
            not consent_file_present,
            "PMR_CONSENT_PARSE_FAILED",
            "REJECT",
            consent_artifact,
            "present consent could not be strictly parsed",
        )
        expected_receipt = _expected_pmr_no_write_receipt(request, candidate)

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
    receipt_valid = (
        _exact_keys(receipt, receipt_keys, receipt_artifact)
        and receipt == expected_receipt
    )
    _add(
        findings,
        receipt_valid,
        "PMR_RECEIPT_OR_LIFECYCLE_INVALID",
        "REJECT",
        receipt_artifact,
        "PMR receipt is not the exact no-write lifecycle expected from consent posture",
    )
    if retention_requested and not consent_granted:
        findings.append(
            Finding(
                "PMR_RETENTION_CONSENT_NOT_GRANTED",
                "HOLD",
                consent_artifact,
                "retention was requested but separate active GRANT consent is absent",
            )
        )
    return {
        "consent_present": consent is not None,
        "consent_valid": consent_valid,
        "consent_granted": consent_granted,
        "receipt_valid": receipt_valid,
        "retention_gate_satisfied": (
            receipt_valid
            and (
                (not retention_requested and consent is None and not consent_file_present)
                or (retention_requested and consent_granted)
            )
        ),
    }


def _tokens(value: str) -> list[str]:
    return sorted({token.casefold() for token in TOKEN.findall(value) if token.casefold() not in STOP_WORDS})


def _close(left: Any, right: float, *, tolerance: float = 1e-12) -> bool:
    return _number(left) and math.isclose(float(left), right, rel_tol=tolerance, abs_tol=tolerance)


def _citation_evidence(
    reference: dict[str, Any],
    *,
    claim_text: str,
    manifest: dict[str, Any],
    normalized_source: str,
    segments_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    segment = segments_by_id.get(reference["segment_id"])
    span = reference["source_span"]
    char_start, char_end = span["char_start"], span["char_end"]
    byte_start, byte_end = span["byte_start"], span["byte_end"]
    encoded_source = normalized_source.encode("utf-8")

    if reference["source_sha256"] != manifest.get("source_sha256"):
        reasons.append("CITATION_SOURCE_SHA256_MISMATCH")
    if segment is None:
        reasons.append("CITATION_SEGMENT_ID_NOT_FOUND")
    elif reference["segment_sha256"] != segment["sha256"]:
        reasons.append("CITATION_SEGMENT_SHA256_MISMATCH")
    if reference["claim_text_sha256"] != _sha256(claim_text.encode("utf-8")):
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
    if excerpt is None or reference["exact_excerpt_sha256"] != _sha256(
        excerpt.encode("utf-8") if excerpt is not None else b""
    ):
        reasons.append("CITATION_EXACT_EXCERPT_SHA256_MISMATCH")

    claim_tokens = set(_tokens(claim_text))
    overlap = sorted(claim_tokens & set(_tokens(excerpt or "")))
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


def _mark_citation_overlaps(rows: list[dict[str, Any]]) -> None:
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


def _citation_support_status(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "NO_VALID_SOURCE_CITATION"
    if any(row["citation_integrity"] != "VERIFIED" for row in evidence):
        return "INSUFFICIENT_EVIDENCE"
    relations = {row["candidate_relation"] for row in evidence}
    if "CONTRADICTS" in relations:
        return "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED"
    if "SUPPORTS" in relations and "LIMITS" in relations:
        return "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED"
    if "SUPPORTS" in relations:
        return "CITATION_VERIFIED_REVIEW_REQUIRED"
    return "NO_VALID_SOURCE_CITATION"


def _validate_claim_map(
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    normalized_source: str,
    segments_by_id: dict[str, dict[str, Any]],
    claim_map: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "claim_evidence_map.json"
    keys = {
        "schema_id",
        "run_id",
        "candidate_id",
        "candidate_sha256",
        "grounding_manifest_sha256",
        "source_sha256",
        "mapping_method",
        "claims",
        "unsupported_claim_ids",
        "authority_effect",
    }
    structural = _exact_keys(claim_map, keys, artifact)
    _add(findings, structural, "CLAIM_MAP_CONTRACT_INVALID", "REJECT", artifact, "exact claim map fields required")
    claim_findings: list[dict[str, Any]] = []
    if not structural:
        return {"claim_findings": claim_findings, "claim_map_sha256": _canonical_sha256(claim_map)}
    identity_ok = (
        claim_map["schema_id"] == "uvlm.coherence.totality.claim_evidence_map.v1"
        and claim_map["run_id"] == candidate.get("run_id")
        and claim_map["candidate_id"] == candidate.get("candidate_id")
        and claim_map["candidate_sha256"] == _canonical_sha256(candidate)
        and claim_map["grounding_manifest_sha256"] == _canonical_sha256(manifest)
        and claim_map["source_sha256"] == manifest.get("source_sha256")
        and _text(claim_map["mapping_method"])
        and isinstance(claim_map["claims"], list)
        and isinstance(claim_map["unsupported_claim_ids"], list)
        and claim_map["authority_effect"] == "NONE"
    )
    _add(findings, identity_ok, "CLAIM_MAP_BINDING_MISMATCH", "REJECT", artifact, "claim map parent or nonauthority binding failed")
    expected_claims: list[dict[str, Any]] = []
    exact_unsupported: list[str] = []
    for claim in candidate.get("claims", []):
        if not isinstance(claim, dict):
            continue
        claim_tokens = set(_tokens(claim.get("text", "")))
        covered: set[str] = set()
        expected_evidence = [
            _citation_evidence(
                reference,
                claim_text=claim["text"],
                manifest=manifest,
                normalized_source=normalized_source,
                segments_by_id=segments_by_id,
            )
            for reference in claim.get("candidate_evidence_references", [])
        ]
        _mark_citation_overlaps(expected_evidence)
        for evidence in expected_evidence:
            if evidence["citation_integrity"] == "VERIFIED":
                covered.update(evidence["overlap_tokens"])
        status = _citation_support_status(expected_evidence)
        if status not in {
            "CITATION_VERIFIED_REVIEW_REQUIRED",
            "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED",
        }:
            exact_unsupported.append(claim["claim_id"])
        expected_claims.append(
            {
                "claim_id": claim["claim_id"],
                "text": claim["text"],
                "answer_span": {"char_start": claim["answer_start"], "char_end": claim["answer_end"]},
                "evidence": expected_evidence,
                "support_status": status,
                "residual_tokens": sorted(claim_tokens - covered),
            }
        )
        claim_findings.append(
            {
                "claim_id": claim["claim_id"],
                # Exact citation integrity is not semantic support
                # certification.  Preserve the conservative bridge field and
                # expose the bounded posture in the claim map itself.
                "stored_support_status": "INSUFFICIENT_EVIDENCE",
                "evidence_count": len(expected_evidence),
                "recomputed_supported": False,
                "residual_tokens": sorted(claim_tokens - covered),
            }
        )
        status_finding = {
            "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED": (
                "SOURCE_LIMITATION_REVIEW_REQUIRED",
                "exact candidate-declared support and limitation citations were verified; semantic review remains required",
            ),
            "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED": (
                "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED",
                "an exact candidate-declared contradiction citation was verified; semantic contradiction is not certified",
            ),
            "NO_VALID_SOURCE_CITATION": (
                "NO_VALID_SOURCE_CITATION",
                "claim has no verified candidate-declared supporting citation",
            ),
            "INSUFFICIENT_EVIDENCE": (
                "CITATION_INTEGRITY_INSUFFICIENT",
                "one or more candidate-declared citations failed exact integrity checks",
            ),
        }.get(status)
        if status_finding is not None:
            findings.append(
                Finding(
                    status_finding[0],
                    "HOLD",
                    f"claim_evidence_map.json#claims/{claim['claim_id']}",
                    status_finding[1],
                )
            )
    expected_map = {
        "schema_id": "uvlm.coherence.totality.claim_evidence_map.v1",
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": _canonical_sha256(candidate),
        "grounding_manifest_sha256": _canonical_sha256(manifest),
        "source_sha256": manifest.get("source_sha256"),
        "mapping_method": "CANDIDATE_DECLARED_EXACT_CITATION_INTEGRITY_V1",
        "claims": expected_claims,
        "unsupported_claim_ids": sorted(exact_unsupported),
        "authority_effect": "NONE",
    }
    _add(findings, claim_map == expected_map, "CLAIM_MAP_RECOMPUTATION_MISMATCH", "REJECT", artifact, "full claim/evidence map differs from independent recomputation")
    return {
        "claim_findings": sorted(claim_findings, key=lambda item: item["claim_id"]),
        "claim_map_sha256": _canonical_sha256(claim_map),
        "unsupported_claim_ids": sorted(exact_unsupported),
    }


def _validate_ucm(
    request: dict[str, Any],
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    claim_map: dict[str, Any],
    ucm: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "ucm_state.json"
    keys = {
        "schema_id",
        "run_id",
        "candidate_id",
        "expected_context",
        "axes",
        "uncertainty",
        "source_ref_count",
        "unsupported_claim_ids",
        "hypotheses",
        "authority_effect",
    }
    context_keys = {"request_sha256", "candidate_sha256", "grounding_manifest_sha256", "source_sha256", "claim_map_sha256"}
    axes_keys = {"E_cpl", "T_tr", "E_s", "phase_stability_lambda", "mutual_containment_mu"}
    hypothesis_keys = {"hypothesis_id", "score", "equivalence_group", "pattern_posture"}
    structural = _exact_keys(ucm, keys, artifact)
    _add(findings, structural, "UCM_CONTRACT_INVALID", "REJECT", artifact, "exact UCM fields required")
    hypotheses: list[dict[str, Any]] = []
    if not structural:
        return {"hypotheses": hypotheses, "ucm_state_sha256": _canonical_sha256(ucm)}
    expected_context = {
        "request_sha256": _canonical_sha256(request),
        "candidate_sha256": _canonical_sha256(candidate),
        "grounding_manifest_sha256": _canonical_sha256(manifest),
        "source_sha256": manifest.get("source_sha256"),
        "claim_map_sha256": _canonical_sha256(claim_map),
    }
    scalar_ok = (
        ucm["schema_id"] == "uvlm.coherence.totality.ucm_state.v1"
        and ucm["run_id"] == candidate.get("run_id")
        and ucm["candidate_id"] == candidate.get("candidate_id")
        and _exact_keys(ucm["expected_context"], context_keys, "ucm_state.json#expected_context")
        and ucm["expected_context"] == expected_context
        and _exact_keys(ucm["axes"], axes_keys, "ucm_state.json#axes")
        and all(_number(ucm["axes"].get(name)) and 0 <= float(ucm["axes"][name]) <= 1 for name in axes_keys)
        and _number(ucm["uncertainty"])
        and 0 <= float(ucm["uncertainty"]) <= 1
        and _close(ucm["uncertainty"], float(candidate.get("uncertainty", -1)))
        and _integer(ucm["source_ref_count"])
        and ucm["source_ref_count"] >= 0
        and isinstance(ucm["unsupported_claim_ids"], list)
        and ucm["unsupported_claim_ids"] == claim_map.get("unsupported_claim_ids")
        and isinstance(ucm["hypotheses"], list)
        and bool(ucm["hypotheses"])
        and ucm["authority_effect"] == "NONE"
    )
    _add(findings, scalar_ok, "UCM_CONTEXT_OR_STATE_MISMATCH", "REJECT", artifact, "UCM context, axes, or claim state is not bound exactly")
    source_refs = request.get("grounding", []) if isinstance(request.get("grounding"), list) else []
    _add(findings, ucm["source_ref_count"] == len(source_refs), "UCM_SOURCE_COUNT_MISMATCH", "REJECT", artifact, "source reference count differs from canonical request")
    seen: set[str] = set()
    for index, hypothesis in enumerate(ucm["hypotheses"] if isinstance(ucm["hypotheses"], list) else []):
        path = f"ucm_state.json#hypotheses/{index}"
        good = _exact_keys(hypothesis, hypothesis_keys, path)
        if good:
            good = (
                _identifier(hypothesis["hypothesis_id"])
                and hypothesis["hypothesis_id"] not in seen
                and _number(hypothesis["score"])
                and _identifier(hypothesis["equivalence_group"])
                and hypothesis["pattern_posture"] in {"IN_DISTRIBUTION", "AMBIGUOUS", "NEW_PATTERN", "OOD"}
            )
        _add(findings, good, "UCM_HYPOTHESIS_INVALID", "REJECT", path, "hypothesis contract failed")
        if good:
            seen.add(hypothesis["hypothesis_id"])
            hypotheses.append(dict(hypothesis))
    _add(findings, hypotheses == sorted(hypotheses, key=lambda item: item["hypothesis_id"]), "UCM_HYPOTHESIS_ORDER_INVALID", "REJECT", artifact, "hypotheses must be ordered by stable identity")
    return {
        "expected_context": expected_context,
        "axes": ucm.get("axes", {}),
        "uncertainty": ucm.get("uncertainty"),
        "source_ref_count": ucm.get("source_ref_count"),
        "unsupported_claim_ids": ucm.get("unsupported_claim_ids", []),
        "hypotheses": hypotheses,
        "ucm_state_sha256": _canonical_sha256(ucm),
    }


def _softmax(scores: list[float]) -> list[float]:
    maximum = max(scores)
    exponents = [math.exp(score - maximum) for score in scores]
    denominator = sum(exponents)
    return [value / denominator for value in exponents]


def _project(hypotheses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    probabilities = _softmax([float(item["score"]) for item in hypotheses])
    candidates = [
        {**hypothesis, "probability": probability}
        for hypothesis, probability in zip(hypotheses, probabilities, strict=True)
    ]
    grouped: dict[str, float] = {}
    for row in candidates:
        group = row["equivalence_group"]
        grouped[group] = grouped.get(group, 0.0) + row["probability"]
    groups = sorted(
        ({"equivalence_group": name, "probability": probability} for name, probability in grouped.items()),
        key=lambda item: (-item["probability"], item["equivalence_group"]),
    )
    second = groups[1]["probability"] if len(groups) > 1 else 0.0
    return sorted(candidates, key=lambda item: item["hypothesis_id"]), groups, groups[0]["probability"] - second


def _expected_projection_disposition(ucm: dict[str, Any], margin: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    axes = ucm["axes"]
    hypotheses = ucm["hypotheses"]
    if ucm["source_ref_count"] == 0:
        reasons.append("NO_AUTHENTICATED_SOURCE_REFERENCE")
    if axes["T_tr"] < 0.20:
        reasons.append("TRANSPARENCY_BELOW_REFUSAL_FLOOR")
    if ucm["uncertainty"] >= 0.85:
        reasons.append("UNCERTAINTY_ABOVE_REFUSAL_CEILING")
    if ucm["unsupported_claim_ids"]:
        reasons.append("INSUFFICIENT_EVIDENCE_FOR_CLAIMS")
    if any(row["pattern_posture"] == "OOD" for row in hypotheses):
        reasons.append("OOD_PATTERN_DETECTED")
    if reasons:
        return "REFUSE", sorted(reasons)
    if axes["E_cpl"] * axes["T_tr"] < 0.45:
        reasons.append("COHERENCE_BELOW_SCREEN_THRESHOLD")
    if axes["E_s"] < 0.50:
        reasons.append("ETHICAL_SYMMETRY_REQUIRES_REVIEW")
    if ucm["uncertainty"] > 0.40:
        reasons.append("UNCERTAINTY_REQUIRES_REVIEW")
    if margin < 0.10:
        reasons.append("FULL_POSTERIOR_MARGIN_AMBIGUOUS")
    if any(row["pattern_posture"] == "NEW_PATTERN" for row in hypotheses):
        reasons.append("NEW_PATTERN_REQUIRES_REVIEW")
    if any(row["pattern_posture"] == "AMBIGUOUS" for row in hypotheses):
        reasons.append("PATTERN_AMBIGUITY_REQUIRES_REVIEW")
    return ("HOLD", sorted(reasons)) if reasons else ("PASS_SCREEN", ["BOUNDED_SCREEN_CRITERIA_MET"])


def _validate_projector(
    candidate: dict[str, Any],
    ucm: dict[str, Any],
    projector: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "projector_receipt.json"
    keys = {
        "schema_id",
        "run_id",
        "candidate_id",
        "ucm_state_sha256",
        "expected_context",
        "psi_cl",
        "full_candidate_posterior",
        "full_equivalence_posterior",
        "full_posterior_margin",
        "disposition",
        "reasons",
        "presentation",
        "authority_effect",
        "human_review_required",
    }
    presentation_keys = {"top_k", "candidates", "retained_mass", "omitted_mass", "disposition_invariant_to_top_k"}
    structural = _exact_keys(projector, keys, artifact)
    _add(findings, structural, "PROJECTOR_CONTRACT_INVALID", "REJECT", artifact, "exact projector fields required")
    if not structural:
        return {"projector_receipt_sha256": _canonical_sha256(projector)}
    hypotheses = ucm.get("hypotheses") if isinstance(ucm.get("hypotheses"), list) else []
    hypotheses_valid = bool(hypotheses) and all(
        isinstance(item, dict) and _number(item.get("score")) and _identifier(item.get("equivalence_group"))
        for item in hypotheses
    )
    expected_candidates: list[dict[str, Any]] = []
    expected_groups: list[dict[str, Any]] = []
    expected_margin = 0.0
    if hypotheses_valid:
        expected_candidates, expected_groups, expected_margin = _project(hypotheses)
    expected_disposition, expected_reasons = (
        _expected_projection_disposition(ucm, expected_margin)
        if hypotheses_valid and isinstance(ucm.get("axes"), dict)
        else (None, None)
    )
    axes = ucm.get("axes") if isinstance(ucm.get("axes"), dict) else {}
    expected_psi = float(axes.get("E_cpl", -1)) * float(axes.get("T_tr", -1)) if _number(axes.get("E_cpl")) and _number(axes.get("T_tr")) else -1
    presentation = projector["presentation"]
    top_k = presentation.get("top_k") if isinstance(presentation, dict) else None
    ranked = sorted(expected_candidates, key=lambda item: (-item["probability"], item["hypothesis_id"]))
    expected_presentation = ranked[:top_k] if _integer(top_k) and 1 <= top_k <= len(ranked) else []
    retained = sum(item["probability"] for item in expected_presentation)
    relationship_ok = (
        projector["schema_id"] == "uvlm.coherence.totality.projector_receipt.v1"
        and projector["run_id"] == candidate.get("run_id")
        and projector["candidate_id"] == candidate.get("candidate_id")
        and projector["ucm_state_sha256"] == _canonical_sha256(ucm)
        and projector["expected_context"] == ucm.get("expected_context")
        and _close(projector["psi_cl"], expected_psi)
        and isinstance(projector["full_candidate_posterior"], list)
        and len(projector["full_candidate_posterior"]) == len(expected_candidates)
        and all(
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_close(actual[key], expected[key]) if key in {"score", "probability"} else actual[key] == expected[key] for key in expected)
            for actual, expected in zip(projector["full_candidate_posterior"], expected_candidates, strict=True)
        )
        and isinstance(projector["full_equivalence_posterior"], list)
        and len(projector["full_equivalence_posterior"]) == len(expected_groups)
        and all(
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and actual["equivalence_group"] == expected["equivalence_group"]
            and _close(actual["probability"], expected["probability"])
            for actual, expected in zip(projector["full_equivalence_posterior"], expected_groups, strict=True)
        )
        and _close(projector["full_posterior_margin"], expected_margin)
        and projector["disposition"] == expected_disposition
        and projector["reasons"] == expected_reasons
        and _exact_keys(presentation, presentation_keys, "projector_receipt.json#presentation")
        and presentation.get("candidates") == expected_presentation
        and _close(presentation.get("retained_mass"), retained)
        and _close(presentation.get("omitted_mass"), max(0.0, 1.0 - retained))
        and presentation.get("disposition_invariant_to_top_k") is True
        and projector["authority_effect"] == "NONE"
        and projector["human_review_required"] is True
    )
    _add(findings, relationship_ok, "PROJECTOR_RELATIONSHIP_MISMATCH", "REJECT", artifact, "full posterior, equivalence aggregation, top-k presentation, or binding is not reproducible")
    if projector["disposition"] != "PASS_SCREEN":
        findings.append(Finding("PROJECTOR_" + projector["disposition"], "HOLD", artifact, "upstream projector did not pass its bounded screen"))
    return {
        "projector_receipt_sha256": _canonical_sha256(projector),
        "full_posterior_margin": expected_margin,
        "omitted_mass": max(0.0, 1.0 - retained),
        "disposition": projector.get("disposition"),
        "top_k_invariant": presentation.get("disposition_invariant_to_top_k") is True,
    }


def _validate_residual(
    candidate: dict[str, Any],
    ucm: dict[str, Any],
    projector: dict[str, Any],
    residual: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "residual_refusal.json"
    keys = {"schema_id", "run_id", "candidate_id", "projector_invariant_sha256", "residual", "refusal", "disposition", "reasons", "authority_effect"}
    residual_keys = {"omitted_probability_mass", "unsupported_claim_ids", "ambiguity", "ood_hypothesis_ids", "new_pattern_hypothesis_ids"}
    refusal_keys = {"triggered", "reason_codes"}
    structural = _exact_keys(residual, keys, artifact)
    _add(findings, structural, "RESIDUAL_CONTRACT_INVALID", "REJECT", artifact, "exact residual/refusal fields required")
    if not structural:
        return {}
    body, refusal = residual["residual"], residual["refusal"]
    hypotheses = ucm.get("hypotheses") if isinstance(ucm.get("hypotheses"), list) else []
    expected_ood = sorted(item["hypothesis_id"] for item in hypotheses if isinstance(item, dict) and item.get("pattern_posture") == "OOD")
    expected_new = sorted(item["hypothesis_id"] for item in hypotheses if isinstance(item, dict) and item.get("pattern_posture") == "NEW_PATTERN")
    invariant_fields = (
        "ucm_state_sha256", "expected_context", "psi_cl", "full_candidate_posterior",
        "full_equivalence_posterior", "full_posterior_margin", "disposition", "reasons",
    )
    invariant = {name: projector.get(name) for name in invariant_fields}
    relationship_ok = (
        residual["schema_id"] == "uvlm.coherence.totality.residual_refusal.v1"
        and residual["run_id"] == candidate.get("run_id")
        and residual["candidate_id"] == candidate.get("candidate_id")
        and residual["projector_invariant_sha256"] == _canonical_sha256(invariant)
        and _exact_keys(body, residual_keys, "residual_refusal.json#residual")
        and _close(body.get("omitted_probability_mass"), 0.0)
        and body.get("unsupported_claim_ids") == ucm.get("unsupported_claim_ids")
        and body.get("ambiguity") is (
            float(projector.get("full_posterior_margin", 1)) < 0.10
            or any(isinstance(item, dict) and item.get("pattern_posture") == "AMBIGUOUS" for item in hypotheses)
        )
        and body.get("ood_hypothesis_ids") == expected_ood
        and body.get("new_pattern_hypothesis_ids") == expected_new
        and _exact_keys(refusal, refusal_keys, "residual_refusal.json#refusal")
        and refusal.get("triggered") is (projector.get("disposition") == "REFUSE")
        and refusal.get("reason_codes") == (projector.get("reasons") if projector.get("disposition") == "REFUSE" else [])
        and residual["disposition"] == projector.get("disposition")
        and residual["reasons"] == projector.get("reasons")
        and residual["authority_effect"] == "NONE"
    )
    _add(findings, relationship_ok, "RESIDUAL_OR_REFUSAL_MISMATCH", "REJECT", artifact, "residual, ambiguity, OOD, new-pattern, or refusal relationship is not reproducible")
    if refusal.get("triggered") is True or body.get("unsupported_claim_ids") or body.get("ambiguity") or expected_ood or expected_new:
        findings.append(Finding("RESIDUAL_OR_REFUSAL_ACTIVE", "HOLD", artifact, "unresolved residual or refusal posture is preserved"))
    return {"refusal_triggered": refusal.get("triggered"), "ood_count": len(expected_ood), "new_pattern_count": len(expected_new)}


def _aha_mapping_result(case: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    donor = next((graph for graph in case["donors"] if graph["graph_id"] == mapping["donor_graph_id"]), None)
    if donor is None:
        raise InputContractError("AHA_MAPPING_DANGLING_GRAPH")
    target = case["target"]
    donor_relations = {item["relation_id"]: item for item in donor["relations"]}
    target_relations = {item["relation_id"]: item for item in target["relations"]}
    target_nodes = {item["node_id"] for item in target["nodes"]}
    failures: list[str] = []
    mapped: list[dict[str, str]] = []
    for donor_id, target_id in sorted(mapping["relation_map"].items()):
        left, right = donor_relations.get(donor_id), target_relations.get(target_id)
        if not left or not right:
            failures.append("AHA_RELATION_UNSUPPORTED")
            continue
        if left["relation_type"] != right["relation_type"]:
            failures.append("AHA_RELATION_TYPE_MISMATCH")
        if left["orientation"] != right["orientation"]:
            failures.append("AHA_CAUSAL_REVERSAL_UNDECLARED")
        if mapping["node_map"].get(left["source_node_id"]) not in target_nodes or mapping["node_map"].get(left["target_node_id"]) not in target_nodes:
            failures.append("AHA_MAPPING_DANGLING_NODE")
        mapped.append({"donor_relation_id": donor_id, "target_relation_id": target_id})
    if not mapped:
        failures.append("AHA_RELATION_MAPPING_EMPTY")
    return {
        "mapping_id": mapping["mapping_id"],
        "donor_graph_id": donor["graph_id"],
        "mapped_relations": mapped,
        "unmapped_donor_relations": sorted(set(donor_relations) - set(mapping["relation_map"])),
        "fail_reasons": sorted(set(failures)),
        "invariants": mapping["invariant_map"],
        "disanalogies": mapping["disanalogies"],
    }


def _aha_case_values_bounded(value: Any) -> bool:
    forbidden = {
        "truth", "certified_truth", "approval", "approved", "memory", "pmr",
        "publication", "publish", "deployment", "deploy", "release", "authority",
        "authority_effect",
    }
    if isinstance(value, str):
        return len(value) <= 10_000 and "\x00" not in value
    if isinstance(value, list):
        return all(_aha_case_values_bounded(item) for item in value)
    if isinstance(value, dict):
        return all(key.casefold() not in forbidden and _aha_case_values_bounded(item) for key, item in value.items())
    return not isinstance(value, float) or math.isfinite(value)


def _validate_aha_case_shape(case: Any, segments_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_keys = {"schema_id", "case_id", "question", "grounding_segments", "target", "donors", "mappings", "candidate_hypothesis", "falsification_test"}
    if not _exact_keys(case, case_keys, "aha_result.json#case"):
        raise InputContractError("AHA_CASE_SHAPE_INVALID")
    if not _aha_case_values_bounded(case):
        raise InputContractError("AHA_CASE_AUTHORITY_OR_VALUE_BOUNDARY_INVALID")
    if not all(_text(case[name]) for name in ("schema_id", "case_id", "question")):
        raise InputContractError("AHA_CASE_IDENTITY_INVALID")
    expected_refs = sorted(
        ({"segment_id": segment["segment_id"], "sha256": segment["sha256"]} for segment in segments_by_id.values()),
        key=lambda item: item["segment_id"],
    )
    if not isinstance(case["grounding_segments"], list) or sorted(case["grounding_segments"], key=lambda item: item.get("segment_id", "") if isinstance(item, dict) else "") != expected_refs:
        raise InputContractError("AHA_GROUNDING_SEGMENT_SET_OR_HASH_MISMATCH")
    graph_keys = {"graph_id", "domain", "source_family_id", "nodes", "relations"}
    node_keys = {"node_id", "node_type", "label", "lineage"}
    relation_keys = {"relation_id", "relation_type", "source_node_id", "target_node_id", "orientation", "lineage"}
    graphs = [case["target"], *(case["donors"] if isinstance(case["donors"], list) else [])]
    if not isinstance(case["donors"], list) or not 2 <= len(case["donors"]) <= 5:
        raise InputContractError("AHA_DONOR_CARDINALITY")
    donor_ids: set[str] = set()
    for graph_index, graph in enumerate(graphs):
        if not _exact_keys(graph, graph_keys, f"aha_result.json#case/graphs/{graph_index}"):
            raise InputContractError("AHA_GRAPH_SHAPE_INVALID")
        if not all(_text(graph[name]) for name in ("graph_id", "domain", "source_family_id")) or not isinstance(graph["nodes"], list) or not isinstance(graph["relations"], list):
            raise InputContractError("AHA_GRAPH_INVALID")
        if graph_index:
            if graph["graph_id"] in donor_ids:
                raise InputContractError("AHA_GRAPH_ID_DUPLICATE")
            donor_ids.add(graph["graph_id"])
        node_ids: set[str] = set()
        for node in graph["nodes"]:
            if not _exact_keys(node, node_keys, "aha_result.json#case/node") or not all(_text(node[name]) for name in ("node_id", "node_type", "label")) or node["node_id"] in node_ids:
                raise InputContractError("AHA_NODE_INVALID")
            node_ids.add(node["node_id"])
            if not isinstance(node["lineage"], list) or not node["lineage"] or any((ref if isinstance(ref, str) else ref.get("segment_id") if isinstance(ref, dict) else None) not in segments_by_id for ref in node["lineage"]):
                raise InputContractError("AHA_LINEAGE_UNRESOLVED")
        relation_ids: set[str] = set()
        for relation in graph["relations"]:
            if not _exact_keys(relation, relation_keys, "aha_result.json#case/relation") or not all(_text(relation[name]) for name in ("relation_id", "relation_type", "source_node_id", "target_node_id", "orientation")) or relation["relation_id"] in relation_ids:
                raise InputContractError("AHA_RELATION_INVALID")
            relation_ids.add(relation["relation_id"])
            if relation["source_node_id"] not in node_ids or relation["target_node_id"] not in node_ids:
                raise InputContractError("AHA_RELATION_DANGLING_NODE")
            if not isinstance(relation["lineage"], list) or not relation["lineage"] or any((ref if isinstance(ref, str) else ref.get("segment_id") if isinstance(ref, dict) else None) not in segments_by_id for ref in relation["lineage"]):
                raise InputContractError("AHA_LINEAGE_UNRESOLVED")
    mapping_keys = {"mapping_id", "donor_graph_id", "node_map", "relation_map", "invariant_map", "disanalogies", "declared_scale_or_unit_transformations"}
    if not isinstance(case["mappings"], list) or not case["mappings"]:
        raise InputContractError("AHA_MAPPING_MISSING")
    mapping_ids: set[str] = set()
    for mapping in case["mappings"]:
        if not _exact_keys(mapping, mapping_keys, "aha_result.json#case/mapping") or not _identifier(mapping.get("mapping_id")) or mapping["mapping_id"] in mapping_ids or mapping.get("donor_graph_id") not in donor_ids:
            raise InputContractError("AHA_MAPPING_INVALID")
        mapping_ids.add(mapping["mapping_id"])
        if not all(isinstance(mapping[name], dict) for name in ("node_map", "relation_map", "invariant_map")) or not isinstance(mapping["disanalogies"], list) or not mapping["disanalogies"]:
            raise InputContractError("AHA_MAPPING_STRUCTURE_INVALID")
    hypothesis_keys = {"statement", "target_observable", "intervention_or_condition", "expected_direction", "comparator_or_null", "horizon", "confidence_lowering_observation"}
    test_keys = {"test_statement", "primary_outcome", "comparator", "reject_criteria", "feasibility_posture", "risk_posture"}
    hypothesis, test = case["candidate_hypothesis"], case["falsification_test"]
    if not _exact_keys(hypothesis, hypothesis_keys, "aha_result.json#case/candidate_hypothesis") or not all(hypothesis.get(name) not in (None, "") for name in ("target_observable", "comparator_or_null", "confidence_lowering_observation")):
        raise InputContractError("AHA_HYPOTHESIS_INVALID")
    if not _exact_keys(test, test_keys, "aha_result.json#case/falsification_test") or not test.get("comparator"):
        raise InputContractError("AHA_FALSIFICATION_TEST_INVALID")
    mapping_results = [_aha_mapping_result(case, mapping) for mapping in sorted(case["mappings"], key=lambda item: item["mapping_id"])]
    reasons = sorted({reason for item in mapping_results for reason in item["fail_reasons"]})
    families = [donor["source_family_id"] for donor in case["donors"]]
    clone = len(set(families)) != len(families)
    if clone:
        reasons.append("AHA_SOURCE_FAMILY_CLONE")
    valid = not reasons
    components = {
        "relation_preservation": "PASS" if not any("RELATION" in code for code in reasons) else "FAIL",
        "causal_orientation": "PASS" if "AHA_CAUSAL_REVERSAL_UNDECLARED" not in reasons else "FAIL",
        "invariant_preservation": "PASS" if all(item["invariants"] for item in mapping_results) else "FAIL",
        "scale_unit_compatibility": "DECLARED" if all(mapping["declared_scale_or_unit_transformations"] is not None for mapping in case["mappings"]) else "NOT_SCORABLE",
        "lineage_reference_coverage": "PASS",
        "source_family_independence": "FAIL" if clone else "PASS",
        "disanalogy_completeness": "PASS",
        "target_observability": "PASS",
        "falsifiability": "PASS",
        "replay_determinism": "PASS",
    }
    evaluation = {
        "case_id": case["case_id"],
        "disposition": "REVIEWABLE" if valid else "REJECTED",
        "fail_reasons": sorted(set(reasons)),
        "bridge_evidence_map": mapping_results,
        "scores": {
            "P_epi": {"kind": "ordinal_evidence_posture", "posture": "NOT_SCORABLE", "nonclaim": "No probability or truth certification is emitted."},
            "C_bridge": {"kind": "bridge_fidelity", "scorable": valid, "components": components},
            "V_test": {"information_value": "QUALITATIVE", "feasibility": test["feasibility_posture"], "cost": "NOT_SUPPLIED", "risk": test["risk_posture"]},
            "Q_AHA": {"kind": "nonprobabilistic_attention_rank", "rank": 1, "authority_effect": "NONE"},
        },
        "semantic_non_vacuity_assessed": False,
        "semantic_utility_demonstrated": False,
        "limitation": "STRUCTURAL_LINEAGE_COVERAGE_ONLY_NOT_SEMANTIC_EVIDENCE_OR_EXTERNAL_UTILITY",
    }
    return evaluation


def _validate_aha(
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
    aha: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "aha_result.json"
    keys = {"schema_id", "run_id", "candidate_id", "candidate_sha256", "source_sha256", "status", "disposition", "reason_codes", "case_sha256", "case", "evaluation", "authority_effect"}
    structural = _exact_keys(aha, keys, artifact)
    _add(findings, structural, "AHA_RESULT_CONTRACT_INVALID", "REJECT", artifact, "exact AHA result fields required")
    if not structural:
        return {"status": None, "disposition": None}
    base_ok = (
        aha["schema_id"] == "uvlm.coherence.totality.aha_result.v1"
        and aha["run_id"] == candidate.get("run_id")
        and aha["candidate_id"] == candidate.get("candidate_id")
        and aha["candidate_sha256"] == _canonical_sha256(candidate)
        and aha["source_sha256"] == manifest.get("source_sha256")
        and aha["authority_effect"] == "NONE"
        and isinstance(aha["reason_codes"], list)
        and all(_text(code) for code in aha["reason_codes"])
    )
    _add(findings, base_ok, "AHA_RESULT_BINDING_MISMATCH", "REJECT", artifact, "AHA parent or nonauthority binding failed")
    if aha["status"] == "UNAVAILABLE":
        valid = (
            aha["disposition"] == "UNAVAILABLE"
            and aha["reason_codes"] == ["AHA_CASE_NOT_SUPPLIED"]
            and aha["case_sha256"] is None
            and aha["case"] is None
            and aha["evaluation"] is None
        )
        _add(findings, valid, "AHA_UNAVAILABLE_POSTURE_INVALID", "REJECT", artifact, "unavailable AHA posture is not explicit and bounded")
        findings.append(Finding("AHA_UNAVAILABLE", "HOLD", artifact, "no structural AHA case was supplied"))
    elif aha["status"] == "AVAILABLE":
        try:
            expected_evaluation = _validate_aha_case_shape(aha["case"], segments_by_id)
            valid = (
                aha["case_sha256"] == _canonical_sha256(aha["case"])
                and aha["evaluation"] == expected_evaluation
                and aha["disposition"] == expected_evaluation["disposition"]
                and aha["reason_codes"] == (expected_evaluation["fail_reasons"] or ["AHA_STRUCTURAL_CASE_REVIEWABLE"])
            )
        except (InputContractError, KeyError, TypeError, ValueError):
            expected_evaluation = None
            valid = False
        _add(findings, valid, "AHA_RESULT_RECOMPUTATION_MISMATCH", "REJECT", artifact, "full structural case or evaluation is not independently reproducible")
        if aha["disposition"] == "REJECTED":
            findings.append(Finding("AHA_REJECTED", "REJECT", artifact, "structural AHA evaluation rejected the mapping"))
    else:
        _add(findings, False, "AHA_RESULT_CONTRACT_INVALID", "REJECT", artifact, "AHA status must be AVAILABLE or UNAVAILABLE")
    return {"status": aha.get("status"), "disposition": aha.get("disposition"), "case_sha256": aha.get("case_sha256")}


def _expected_counterexamples(
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
    claim_map: dict[str, Any],
) -> dict[str, Any]:
    marker_set = {
        "but", "conflict", "contradicts", "failed", "failure", "however", "limitation", "limitations",
        "never", "no", "not", "pending", "reject", "risk", "uncertain", "uncertainty", "unknown",
        "unsupported", "unestablished",
    }
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
    for segment in segments_by_id.values():
        markers = sorted(set(_tokens(segment["text"])) & marker_set)
        if markers:
            findings.append(
                {
                    "finding_id": f"CE-MARKER-{segment['segment_id']}",
                    "kind": "SOURCE_LIMITATION_OR_COUNTEREVIDENCE_MARKER",
                    "claim_id": None,
                    "segment_id": segment["segment_id"],
                    "segment_sha256": segment["sha256"],
                    "exact_excerpt": segment["text"],
                    "source_span": {
                        "char_start": segment["char_start"],
                        "char_end": segment["char_end"],
                        "byte_start": segment["byte_start"],
                        "byte_end": segment["byte_end"],
                    },
                    "markers": markers,
                    "reason_code": "SOURCE_COUNTEREVIDENCE_REQUIRES_HUMAN_REVIEW",
                }
            )
    findings.sort(key=lambda row: row["finding_id"])
    return {
        "schema_id": "uvlm.coherence.totality.counterexamples.v1",
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": _canonical_sha256(candidate),
        "claim_map_sha256": _canonical_sha256(claim_map),
        "source_sha256": manifest.get("source_sha256"),
        "method": "EXACT_SPAN_LIMITATION_MARKERS_AND_UNSUPPORTED_CLAIMS_V1",
        "count": len(findings),
        "findings": findings,
        "unresolved_count": len(findings),
        "authority_effect": "NONE",
    }


def _validate_counterexamples(
    candidate: dict[str, Any],
    manifest: dict[str, Any],
    segments_by_id: dict[str, dict[str, Any]],
    claim_map: dict[str, Any],
    counterexamples: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    expected = _expected_counterexamples(candidate, manifest, segments_by_id, claim_map)
    _add(findings, counterexamples == expected, "COUNTEREXAMPLE_PRESERVATION_MISMATCH", "REJECT", "counterexamples.json", "counterexample and limitation findings differ from independent search")
    if expected["unresolved_count"]:
        findings.append(Finding("UNRESOLVED_COUNTEREXAMPLES", "HOLD", "counterexamples.json", "source limitation or unsupported-claim findings require review"))
    return {"unresolved_count": expected["unresolved_count"], "finding_ids": [row["finding_id"] for row in expected["findings"]]}


def _expected_aperture(
    request: dict[str, Any],
    candidate: dict[str, Any],
    projector: dict[str, Any],
    residual: dict[str, Any],
    aha: dict[str, Any],
    counterexamples: dict[str, Any],
    *,
    task_consent: bool,
    privacy_policy_satisfied: bool,
    retention_gate_satisfied: bool,
    grounding_valid: bool,
    context_binding_valid: bool,
    quarantine_valid: bool,
    claim_evidence_valid: bool,
    ucm_not_refuse: bool,
    aha_not_rejected: bool,
) -> dict[str, Any]:
    # Gate values are supplied only from completed Sophia validators.  In
    # particular, this function never consults aperture["hard_gates"]: that
    # object is an untrusted assertion being checked, not an audit input.
    gates = {
        "task_consent": task_consent is True,
        "privacy_policy_satisfied": privacy_policy_satisfied is True,
        "retention_gate_satisfied": retention_gate_satisfied is True,
        "grounding_valid": grounding_valid is True,
        "context_binding_valid": context_binding_valid is True,
        "quarantine_valid": quarantine_valid is True,
        "claim_evidence_valid": claim_evidence_valid is True,
        "ucm_not_refuse": ucm_not_refuse is True,
        "aha_not_rejected": aha_not_rejected is True,
    }
    gate_reasons = {
        "task_consent": "TASK_CONSENT_MISSING",
        "privacy_policy_satisfied": "PRIVACY_POLICY_NOT_SATISFIED",
        "retention_gate_satisfied": "RETENTION_REQUEST_WITHOUT_SEPARATE_CONSENT",
        "grounding_valid": "GROUNDING_INVALID",
        "context_binding_valid": "EXPECTED_CONTEXT_BINDING_INVALID",
        "quarantine_valid": "RAW_OUTPUT_QUARANTINE_INVALID",
        "claim_evidence_valid": "CLAIM_EVIDENCE_BINDING_INVALID",
        "ucm_not_refuse": "UCM_REFUSAL",
        "aha_not_rejected": "AHA_STRUCTURAL_REJECTION",
    }
    reasons = sorted(gate_reasons[name] for name, passed in gates.items() if not passed)
    if reasons:
        decision = "REFUSE"
    else:
        if projector.get("disposition") == "HOLD":
            reasons.append("UCM_REQUIRES_REVIEW")
        if aha.get("status") == "UNAVAILABLE":
            reasons.append("AHA_UNAVAILABLE")
        if counterexamples.get("unresolved_count", 0):
            reasons.append("UNRESOLVED_COUNTEREXAMPLES_PRESENT")
        if reasons:
            decision = "HOLD"
        else:
            decision, reasons = "PASS_SCREEN", ["BOUNDED_NONCOMPENSATORY_SCREEN_PASSED"]
    return {
        "schema_id": "uvlm.coherence.totality.aperture_decision.v1",
        "run_id": candidate.get("run_id"),
        "candidate_id": candidate.get("candidate_id"),
        "projector_receipt_sha256": _canonical_sha256(projector),
        "residual_refusal_sha256": _canonical_sha256(residual),
        "aha_result_sha256": _canonical_sha256(aha),
        "counterexamples_sha256": _canonical_sha256(counterexamples),
        "hard_gates": gates,
        "decision": decision,
        "reasons": sorted(reasons),
        "human_review_required": True,
        "candidate_is_final_answer": False,
        "authority_effect": "NONE",
    }


def _validate_aperture(
    request: dict[str, Any],
    candidate: dict[str, Any],
    projector: dict[str, Any],
    residual: dict[str, Any],
    aha: dict[str, Any],
    counterexamples: dict[str, Any],
    aperture: dict[str, Any],
    findings: list[Finding],
    *,
    task_consent: bool,
    privacy_policy_satisfied: bool,
    retention_gate_satisfied: bool,
    grounding_valid: bool,
    context_binding_valid: bool,
    quarantine_valid: bool,
    claim_evidence_valid: bool,
    ucm_not_refuse: bool,
    aha_not_rejected: bool,
) -> dict[str, Any]:
    expected = _expected_aperture(
        request,
        candidate,
        projector,
        residual,
        aha,
        counterexamples,
        task_consent=task_consent,
        privacy_policy_satisfied=privacy_policy_satisfied,
        retention_gate_satisfied=retention_gate_satisfied,
        grounding_valid=grounding_valid,
        context_binding_valid=context_binding_valid,
        quarantine_valid=quarantine_valid,
        claim_evidence_valid=claim_evidence_valid,
        ucm_not_refuse=ucm_not_refuse,
        aha_not_rejected=aha_not_rejected,
    )
    _add(findings, aperture == expected, "APERTURE_BYPASS_OR_BINDING_MISMATCH", "REJECT", "aperture_decision.json", "hard-gate decision or parent binding differs from independent recomputation")
    if expected["decision"] != "PASS_SCREEN":
        findings.append(Finding("APERTURE_" + expected["decision"], "HOLD", "aperture_decision.json", "noncompensatory aperture did not pass its bounded screen"))
    return {"decision": expected["decision"], "failed_hard_gates": sorted(name for name, passed in expected["hard_gates"].items() if not passed)}


def _validate_reference_waveform(
    ucm: dict[str, Any], waveform: dict[str, Any], findings: list[Finding]
) -> dict[str, Any]:
    artifact = "reference_waveform.json"
    keys = {
        "schema_id", "codec", "sample_count", "axis_order", "samples",
        "mean_square_energy", "synthetic_reference_only", "physical_frequency_claim",
        "cross_domain_utility_established", "claim_ceiling", "authority_effect",
    }
    axis_order = (
        "E_cpl", "T_tr", "E_s", "phase_stability_lambda", "mutual_containment_mu",
    )
    structural = _exact_keys(waveform, keys, artifact)
    axes = ucm.get("axes")
    sample_count = waveform.get("sample_count")
    valid_inputs = (
        structural
        and isinstance(axes, dict)
        and set(axes) == set(axis_order)
        and all(_number(axes.get(name)) and 0 <= axes[name] <= 1 for name in axis_order)
        and _integer(sample_count)
        and 16 <= sample_count <= 4096
    )
    expected: dict[str, Any] | None = None
    if valid_inputs:
        values = [float(axes[name]) for name in axis_order]
        samples = [
            round(
                math.fsum(
                    amplitude * math.sin(2.0 * math.pi * harmonic * (index / sample_count))
                    for harmonic, amplitude in enumerate(values, start=1)
                )
                / len(values),
                12,
            )
            for index in range(sample_count)
        ]
        expected = {
            "schema_id": "uvlm.coherence.totality.reference_waveform.v1",
            "codec": "AXIOMATIC_SYNTHETIC_FIVE_AXIS_SINE_CODEC_V1",
            "sample_count": sample_count,
            "axis_order": list(axis_order),
            "samples": samples,
            "mean_square_energy": round(
                math.fsum(value * value for value in samples) / len(samples), 12
            ),
            "synthetic_reference_only": True,
            "physical_frequency_claim": False,
            "cross_domain_utility_established": False,
            "claim_ceiling": "REFERENCE CODEC ONLY; NOT A PHYSICAL FREQUENCY OF A PERSON, ARCHETYPE, OR SYSTEM",
            "authority_effect": "NONE",
        }
    valid = expected is not None and waveform == expected
    _add(
        findings,
        valid,
        "REFERENCE_WAVEFORM_RECOMPUTATION_MISMATCH",
        "REJECT",
        artifact,
        "synthetic waveform bytes or nonphysical claim boundary differ from independent recomputation",
    )
    return {"valid": valid, "canonical_sha256": _canonical_sha256(waveform)}


TEL_EVENT_ORDER = (
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


def _validate_tel(
    request: dict[str, Any],
    manifest: dict[str, Any],
    quarantine_receipt: dict[str, Any],
    candidate: dict[str, Any],
    claim_map: dict[str, Any],
    ucm: dict[str, Any],
    projector: dict[str, Any],
    aha: dict[str, Any],
    counterexamples: dict[str, Any],
    waveform: dict[str, Any],
    pmr_receipt: dict[str, Any],
    aperture: dict[str, Any],
    rows: list[dict[str, Any]],
    findings: list[Finding],
) -> dict[str, Any]:
    artifact = "tel_audit_prefix.jsonl"
    keys = {"schema_id", "sequence", "logical_time", "event_type", "run_id", "candidate_id", "audit_id", "decision_id", "outcome", "payload", "authority_effect"}
    rank = {name: index for index, name in enumerate(TEL_EVENT_ORDER)}
    previous_rank = -1
    failed = False
    types: list[str] = []
    valid = bool(rows)
    expected_audit_id = "AUDIT-" + _sha256((_canonical_sha256(candidate) + _canonical_sha256(aperture)).encode("ascii"))[:24]
    expected_decision_id = "DECISION-" + _sha256((expected_audit_id + str(request.get("run_id"))).encode("ascii"))[:24]
    expected_payloads = {
        "REQUEST_CANONICALIZED": {"request_sha256": _canonical_sha256(request)},
        "GROUNDING_VERIFIED": {"grounding_manifest_sha256": _canonical_sha256(manifest)},
        "RAW_OUTPUT_QUARANTINED": {"raw_output_sha256": quarantine_receipt.get("raw_output_sha256")},
        "CANDIDATE_CANONICALIZED": {"candidate_sha256": _canonical_sha256(candidate)},
        "CLAIM_EVIDENCE_MAPPED": {"claim_map_sha256": _canonical_sha256(claim_map)},
        "UCM_PROJECTED": {
            "ucm_state_sha256": _canonical_sha256(ucm),
            "projector_receipt_sha256": _canonical_sha256(projector),
        },
        "AHA_EVALUATED": {"aha_result_sha256": _canonical_sha256(aha)},
        "COUNTEREXAMPLES_SCANNED": {
            "counterexamples_sha256": _canonical_sha256(counterexamples),
            "unresolved_count": counterexamples.get("unresolved_count"),
        },
        "REFERENCE_WAVEFORM_ENCODED": {
            "reference_waveform_sha256": _canonical_sha256(waveform),
            "physical_frequency_claim": False,
        },
        "APERTURE_DECIDED": {
            "aperture_decision_sha256": _canonical_sha256(aperture),
            "decision": aperture.get("decision"),
        },
        "PMR_BOUNDARY_RECORDED": {
            "pmr_receipt_sha256": _canonical_sha256(pmr_receipt),
            "persistent_bytes_written": 0,
        },
        "SOPHIA_AUDIT_REQUESTED": {"status": "REQUESTED_NOT_EXECUTED"},
        "ATLAS_ORIENTATION_PENDING": {"status": "PENDING_SOPHIA"},
        "HUMAN_DECISION_PENDING": {"status": "PENDING", "external_receipt_required": True},
        "CORE_BUILD_COMPLETED": {"stop_boundary": "BEFORE_SOPHIA_AND_ATLAS"},
    }
    expected_outcomes = dict.fromkeys(TEL_EVENT_ORDER, "SUCCESS")
    expected_outcomes.update(
        {
            "UCM_PROJECTED": {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}.get(projector.get("disposition")),
            "AHA_EVALUATED": "REFUSE" if aha.get("disposition") == "REJECTED" else ("HOLD" if aha.get("status") == "UNAVAILABLE" else "SUCCESS"),
            "APERTURE_DECIDED": {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}.get(aperture.get("decision")),
            "PMR_BOUNDARY_RECORDED": "RECORDED",
            "SOPHIA_AUDIT_REQUESTED": "RECORDED",
            "ATLAS_ORIENTATION_PENDING": "RECORDED",
            "HUMAN_DECISION_PENDING": "RECORDED",
            "CORE_BUILD_COMPLETED": "RECORDED",
        }
    )
    for index, row in enumerate(rows, start=1):
        path = f"tel_audit_prefix.jsonl#{index}"
        good = _exact_keys(row, keys, path)
        event_type = row.get("event_type") if isinstance(row, dict) else None
        current_rank = rank.get(event_type, len(rank))
        if good:
            candidate_expected = event_type in TEL_EVENT_ORDER[3:]
            audit_expected = event_type in TEL_EVENT_ORDER[11:]
            decision_expected = event_type in TEL_EVENT_ORDER[13:]
            good = (
                row["schema_id"] == "uvlm.coherence.totality.tel_event.v1"
                and row["sequence"] == index
                and row["logical_time"] == f"T+{index:06d}"
                and (event_type == "STAGE_FAILED" or event_type in rank)
                and row["run_id"] == request.get("run_id")
                and row["candidate_id"] == (candidate.get("candidate_id") if candidate_expected else None)
                and row["audit_id"] == (expected_audit_id if audit_expected else None)
                and row["decision_id"] == (expected_decision_id if decision_expected else None)
                and row["outcome"] in {"SUCCESS", "HOLD", "REFUSE", "FAILURE", "RECORDED"}
                and isinstance(row["payload"], dict)
                and row["authority_effect"] == "NONE"
                and current_rank > previous_rank
                and (not failed or event_type == "RUN_COMPLETED")
            )
            if good and event_type != "STAGE_FAILED":
                good = (
                    row["payload"] == expected_payloads.get(event_type)
                    and row["outcome"] == expected_outcomes.get(event_type)
                )
        if good and event_type == "STAGE_FAILED":
            good = row["outcome"] == "FAILURE" and set(row["payload"]) == {"stage", "reason_code"} and all(_identifier(row["payload"][name]) for name in ("stage", "reason_code"))
            failed = True
        _add(findings, good, "TEL_EVENT_INVALID", "REJECT", path, "TEL identity, sequence, order, exact artifact payload, outcome, failure, or nonauthority contract failed")
        valid &= good
        if good:
            previous_rank = current_rank
            types.append(event_type)
    required_prefix = list(TEL_EVENT_ORDER)
    complete_core = types[: len(required_prefix)] == required_prefix
    _add(findings, complete_core or failed, "TEL_CORE_CHRONOLOGY_INCOMPLETE", "REJECT", artifact, "successful preaudit TEL must preserve every core stage in deterministic order")
    if failed:
        findings.append(Finding("TEL_FAILURE_RECORDED", "REJECT", artifact, "a core stage failure remains visible"))
    return {
        "valid": valid and (complete_core or failed),
        "event_count": len(rows),
        "last_event_type": types[-1] if types else None,
        "failure_recorded": failed,
        "audit_id": expected_audit_id,
        "decision_id": expected_decision_id,
    }


def _safe_validate(
    findings: list[Finding],
    code: str,
    artifact: str,
    operation: Any,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    before = len(findings)
    try:
        result = operation()
        result = dict(result) if isinstance(result, dict) else dict(fallback)
        result["_completed"] = True
        result["_valid"] = not any(
            finding.severity == "REJECT" for finding in findings[before:]
        )
        return result
    except (
        InputContractError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
        StopIteration,
    ):
        findings.append(Finding(code, "REJECT", artifact, "independent recomputation could not safely validate the artifact"))
        result = dict(fallback)
        result["_completed"] = True
        result["_valid"] = False
        return result


def _pending_validation(**values: Any) -> dict[str, Any]:
    """Create a fail-closed state for a validator that has not completed."""

    return {**values, "_completed": False, "_valid": False}


def _validation_succeeded(result: dict[str, Any]) -> bool:
    return result.get("_completed") is True and result.get("_valid") is True


def _return_route(disposition: str, reason_codes: list[str]) -> dict[str, Any]:
    """Describe a bounded return request without changing or rerunning inputs."""

    route, destination = {
        "PASS": ("NONE", "NONE"),
        "HOLD": ("CLARIFY", "COHERENCELATTICE"),
        "REJECT": ("REPAIR", "SONYA_OR_COHERENCELATTICE"),
    }[disposition]
    return {
        "route": route,
        "destination": destination,
        "status": "NOT_REQUIRED" if route == "NONE" else "REQUESTED_NOT_EXECUTED",
        "reason_codes": [] if route == "NONE" else list(reason_codes),
        "candidate_mutation_performed": False,
        "source_mutation_performed": False,
        "automatic_rerun_performed": False,
        "authority_effect": "NONE",
    }


def audit_totality_run(
    run_root: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Audit one totality run and emit a deterministic bounded packet.

    HOLD and REJECT are packet dispositions, not operational exceptions.  Only
    an unsafe root or unsafe output target raises before packet production.
    """

    root = Path(run_root)
    if not root.is_absolute() or _link_like(root) or not root.is_dir():
        raise ValueError("run_root must be an absolute existing non-symlink directory")
    root = root.resolve(strict=True)
    if root == root.parent:
        raise ValueError("run_root must be a bounded directory")
    output = Path(output_path) if output_path is not None else root / OUTPUT_NAME
    if not output.is_absolute() or output.name != OUTPUT_NAME or _link_like(output):
        raise ValueError(f"output_path must be an absolute non-symlink path named {OUTPUT_NAME}")
    output_parent = output.parent.resolve(strict=False)
    if output_parent == output_parent.parent:
        raise ValueError("output_path must be bounded")
    try:
        output.resolve(strict=False).relative_to(root)
        output_inside_run = True
    except ValueError:
        output_inside_run = False
    if output_inside_run and any((root / name).exists() for name in SEALED_RUN_MARKERS):
        raise ValueError("sealed run is immutable; Sophia output must remain external")

    findings: list[Finding] = []
    raw: dict[str, bytes] = {}
    input_digests: dict[str, dict[str, str | None]] = {}
    parsed: dict[str, dict[str, Any]] = {}
    jsonl: dict[str, list[dict[str, Any]]] = {}
    total_input_bytes = 0
    for relative in INPUT_PATHS:
        lexical_member = root.joinpath(*relative.split("/"))
        member = _resolved_member(root, relative)
        if member is None:
            optional_absent = (
                relative in OPTIONAL_INPUT_PATHS
                and not lexical_member.exists()
                and not _link_like(lexical_member)
            )
            if not optional_absent:
                findings.append(Finding("REQUIRED_ARTIFACT_MISSING_OR_UNSAFE", "REJECT", relative, "required regular file is absent or escapes run root"))
            input_digests[relative] = {"file_sha256": None, "canonical_sha256": None}
            continue
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
            if member.stat().st_size > maximum_bytes:
                raise InputContractError("artifact size limit exceeded")
            with member.open("rb") as stream:
                data = stream.read(maximum_bytes + 1)
            if len(data) > maximum_bytes:
                raise InputContractError("artifact size limit exceeded")
        except (OSError, InputContractError):
            findings.append(
                Finding(
                    "ARTIFACT_SIZE_LIMIT_EXCEEDED_OR_UNREADABLE",
                    "REJECT",
                    relative,
                    "artifact exceeded its bounded audit input size or could not be read safely",
                )
            )
            input_digests[relative] = {
                "file_sha256": None,
                "canonical_sha256": None,
            }
            continue
        if total_input_bytes + len(data) > MAX_TOTAL_INPUT_BYTES:
            findings.append(
                Finding(
                    "TOTAL_INPUT_SIZE_LIMIT_EXCEEDED",
                    "REJECT",
                    relative,
                    "aggregate audited inputs exceeded the bounded memory budget",
                )
            )
            input_digests[relative] = {
                "file_sha256": None,
                "canonical_sha256": None,
            }
            continue
        total_input_bytes += len(data)
        raw[relative] = data
        input_digests[relative] = {"file_sha256": _sha256(data), "canonical_sha256": None}
        if relative.endswith(".json"):
            try:
                value = _parse_json(data, relative)
                parsed[relative] = value
                input_digests[relative]["canonical_sha256"] = _canonical_sha256(value)
            except (InputContractError, OverflowError, RecursionError):
                findings.append(Finding("JSON_CONTRACT_OR_CANONICALIZATION_INVALID", "REJECT", relative, "strict canonical JSON parse failed"))
        elif relative.endswith(".jsonl"):
            try:
                rows = _parse_jsonl(data, relative)
                jsonl[relative] = rows
                input_digests[relative]["canonical_sha256"] = _sha256(b"".join(_canonical_json_bytes(row) for row in rows))
            except (InputContractError, OverflowError, RecursionError):
                findings.append(Finding("JSONL_CONTRACT_OR_CANONICALIZATION_INVALID", "REJECT", relative, "strict canonical JSONL parse failed"))

    request = parsed.get("request.json", {})
    manifest = parsed.get("grounding/manifest.json", {})
    quarantine_receipt = parsed.get("sonya/quarantine_receipt.json", {})
    quarantine_verification_receipt = parsed.get(
        "sonya/quarantine_verification_receipt.json",
        {},
    )
    candidate = parsed.get("candidate_packet.json", {})
    claim_map = parsed.get("claim_evidence_map.json", {})
    ucm = parsed.get("ucm_state.json", {})
    projector = parsed.get("projector_receipt.json", {})
    residual = parsed.get("residual_refusal.json", {})
    aha = parsed.get("aha_result.json", {})
    counterexamples = parsed.get("counterexamples.json", {})
    waveform = parsed.get("reference_waveform.json", {})
    pmr_consent = parsed.get("pmr_consent.json")
    pmr_receipt = parsed.get("pmr_receipt.json", {})
    aperture = parsed.get("aperture_decision.json", {})
    segments = jsonl.get("grounding/segments.jsonl", [])
    tel_rows = jsonl.get("tel_audit_prefix.jsonl", [])

    request_result = _pending_validation(
        privacy_policy_satisfied=False,
        privacy_basis_valid=False,
        task_consent=False,
        retention_requested=True,
    )
    if "request.json" in parsed:
        request_result = _safe_validate(
            findings,
            "REQUEST_VALIDATION_FAILED",
            "request.json",
            lambda: _validate_request(request, findings),
            request_result,
        )
    grounding_result = _pending_validation(
        segments_by_id={},
        request_binding_valid=False,
        segment_count=0,
    )
    if (
        "request.json" in parsed
        and "grounding/manifest.json" in parsed
        and all(name in raw for name in ("grounding/source.bin", "grounding/normalized_source.txt"))
        and "grounding/segments.jsonl" in jsonl
    ):
        grounding_result = _safe_validate(
            findings,
            "GROUNDING_VALIDATION_FAILED",
            "grounding/manifest.json",
            lambda: _validate_grounding(request, manifest, raw["grounding/source.bin"], raw["grounding/normalized_source.txt"], raw["grounding/segments.jsonl"], segments, findings),
            grounding_result,
        )
    candidate_result = _pending_validation(claims_by_id={})
    if "request.json" in parsed and "candidate_packet.json" in parsed:
        candidate_result = _safe_validate(findings, "CANDIDATE_VALIDATION_FAILED", "candidate_packet.json", lambda: _validate_candidate(request, candidate, findings), candidate_result)
    quarantine_result = _pending_validation()
    if all(
        name in parsed
        for name in (
            "request.json",
            "sonya/quarantine_receipt.json",
            "candidate_packet.json",
        )
    ):
        quarantine_result = _safe_validate(
            findings,
            "QUARANTINE_RECEIPT_VALIDATION_FAILED",
            "sonya/quarantine_receipt.json",
            lambda: _validate_quarantine_receipt(
                request,
                candidate,
                quarantine_receipt,
                findings,
            ),
            quarantine_result,
        )
    quarantine_verification_result = _pending_validation()
    if all(
        name in parsed
        for name in (
            "request.json",
            "sonya/quarantine_receipt.json",
            "sonya/quarantine_verification_receipt.json",
            "candidate_packet.json",
        )
    ):
        quarantine_verification_result = _safe_validate(
            findings,
            "QUARANTINE_VERIFICATION_VALIDATION_FAILED",
            "sonya/quarantine_verification_receipt.json",
            lambda: _validate_quarantine_verification_receipt(
                request,
                candidate,
                quarantine_receipt,
                quarantine_verification_receipt,
                findings,
            ),
            quarantine_verification_result,
        )
    findings.append(
        Finding(
            "RAW_QUARANTINE_BYTES_NOT_INDEPENDENTLY_VERIFIED",
            "HOLD",
            "sonya/quarantine_verification_receipt.json",
            "Sophia policy prohibits consuming raw model output; only Coherence's bound raw-free verification receipt was audited",
        )
    )
    claim_result = _pending_validation(claim_findings=[], unsupported_claim_ids=[])
    normalized_source = ""
    try:
        normalized_source = raw.get("grounding/normalized_source.txt", b"").decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass
    if (
        all(name in parsed for name in ("candidate_packet.json", "grounding/manifest.json", "claim_evidence_map.json"))
        and grounding_result["segments_by_id"]
    ):
        claim_result = _safe_validate(
            findings,
            "CLAIM_MAP_VALIDATION_FAILED",
            "claim_evidence_map.json",
            lambda: _validate_claim_map(candidate, manifest, normalized_source, grounding_result["segments_by_id"], claim_map, findings),
            claim_result,
        )
    ucm_result = _pending_validation(hypotheses=[])
    if all(name in parsed for name in ("request.json", "candidate_packet.json", "grounding/manifest.json", "claim_evidence_map.json", "ucm_state.json")):
        ucm_result = _safe_validate(findings, "UCM_VALIDATION_FAILED", "ucm_state.json", lambda: _validate_ucm(request, candidate, manifest, claim_map, ucm, findings), ucm_result)
    projector_result: dict[str, Any] = _pending_validation()
    if all(name in parsed for name in ("candidate_packet.json", "ucm_state.json", "projector_receipt.json")):
        projector_result = _safe_validate(findings, "PROJECTOR_VALIDATION_FAILED", "projector_receipt.json", lambda: _validate_projector(candidate, ucm, projector, findings), projector_result)
    residual_result: dict[str, Any] = _pending_validation()
    if all(name in parsed for name in ("candidate_packet.json", "ucm_state.json", "projector_receipt.json", "residual_refusal.json")):
        residual_result = _safe_validate(findings, "RESIDUAL_VALIDATION_FAILED", "residual_refusal.json", lambda: _validate_residual(candidate, ucm, projector, residual, findings), residual_result)
    aha_result: dict[str, Any] = _pending_validation(status=None, disposition=None)
    if all(name in parsed for name in ("candidate_packet.json", "grounding/manifest.json", "aha_result.json")) and grounding_result["segments_by_id"]:
        aha_result = _safe_validate(findings, "AHA_VALIDATION_FAILED", "aha_result.json", lambda: _validate_aha(candidate, manifest, grounding_result["segments_by_id"], aha, findings), aha_result)
    counterexample_result: dict[str, Any] = _pending_validation()
    if all(name in parsed for name in ("candidate_packet.json", "grounding/manifest.json", "claim_evidence_map.json", "counterexamples.json")) and grounding_result["segments_by_id"]:
        counterexample_result = _safe_validate(
            findings,
            "COUNTEREXAMPLE_VALIDATION_FAILED",
            "counterexamples.json",
            lambda: _validate_counterexamples(candidate, manifest, grounding_result["segments_by_id"], claim_map, counterexamples, findings),
            counterexample_result,
        )
    waveform_result: dict[str, Any] = _pending_validation(valid=False)
    if all(name in parsed for name in ("ucm_state.json", "reference_waveform.json")):
        waveform_result = _safe_validate(
            findings,
            "REFERENCE_WAVEFORM_VALIDATION_FAILED",
            "reference_waveform.json",
            lambda: _validate_reference_waveform(ucm, waveform, findings),
            waveform_result,
        )
    pmr_result: dict[str, Any] = _pending_validation(
        consent_valid=False,
        consent_granted=False,
        receipt_valid=False,
        retention_gate_satisfied=False,
    )
    if all(
        name in parsed
        for name in ("request.json", "candidate_packet.json", "pmr_receipt.json")
    ):
        pmr_result = _safe_validate(
            findings,
            "PMR_BOUNDARY_VALIDATION_FAILED",
            "pmr_receipt.json",
            lambda: _validate_pmr_boundary(
                request,
                candidate,
                pmr_consent,
                consent_file_present=(
                    "pmr_consent.json" in raw
                    or (root / "pmr_consent.json").exists()
                    or _link_like(root / "pmr_consent.json")
                ),
                receipt=pmr_receipt,
                findings=findings,
            ),
            pmr_result,
        )
    request_valid = _validation_succeeded(request_result)
    candidate_valid = _validation_succeeded(candidate_result)
    grounding_valid = (
        _validation_succeeded(grounding_result)
        and grounding_result.get("request_binding_valid") is True
        and grounding_result.get("segment_count", 0) > 0
    )
    quarantine_valid = (
        request_valid
        and candidate_valid
        and _validation_succeeded(quarantine_result)
        and _validation_succeeded(quarantine_verification_result)
    )
    claim_evidence_valid = (
        _validation_succeeded(claim_result)
        and not claim_result.get("unsupported_claim_ids")
    )
    context_binding_valid = _validation_succeeded(ucm_result)
    projector_valid = _validation_succeeded(projector_result)
    residual_valid = _validation_succeeded(residual_result)
    aha_valid = _validation_succeeded(aha_result)
    ucm_not_refuse = (
        context_binding_valid
        and projector_valid
        and residual_valid
        and projector_result.get("disposition") != "REFUSE"
        and residual_result.get("refusal_triggered") is False
    )
    aha_not_rejected = aha_valid and aha_result.get("disposition") != "REJECTED"
    recomputed_gate_values = {
        "task_consent": request_valid and request_result.get("task_consent") is True,
        "privacy_policy_satisfied": (
            request_valid
            and request_result.get("privacy_basis_valid") is True
            and request_result.get("privacy_policy_satisfied") is True
        ),
        "retention_gate_satisfied": (
            request_valid
            and candidate_valid
            and _validation_succeeded(pmr_result)
            and pmr_result.get("retention_gate_satisfied") is True
        ),
        "grounding_valid": grounding_valid,
        "context_binding_valid": context_binding_valid,
        "quarantine_valid": quarantine_valid,
        "claim_evidence_valid": claim_evidence_valid,
        "ucm_not_refuse": ucm_not_refuse,
        "aha_not_rejected": aha_not_rejected,
    }
    aperture_result: dict[str, Any] = _pending_validation()
    if all(
        name in parsed
        for name in (
            "request.json",
            "candidate_packet.json",
            "projector_receipt.json",
            "residual_refusal.json",
            "aha_result.json",
            "counterexamples.json",
            "aperture_decision.json",
        )
    ):
        aperture_result = _safe_validate(
            findings,
            "APERTURE_VALIDATION_FAILED",
            "aperture_decision.json",
            lambda: _validate_aperture(
                request,
                candidate,
                projector,
                residual,
                aha,
                counterexamples,
                aperture,
                findings,
                **recomputed_gate_values,
            ),
            aperture_result,
        )
    tel_result: dict[str, Any] = _pending_validation(event_count=len(tel_rows), valid=False)
    if (
        all(
            name in parsed
            for name in (
                "request.json",
                "grounding/manifest.json",
                "sonya/quarantine_receipt.json",
                "candidate_packet.json",
                "claim_evidence_map.json",
                "ucm_state.json",
                "projector_receipt.json",
                "aha_result.json",
                "counterexamples.json",
                "reference_waveform.json",
                "pmr_receipt.json",
                "aperture_decision.json",
            )
        )
        and "tel_audit_prefix.jsonl" in jsonl
    ):
        tel_result = _safe_validate(
            findings,
            "TEL_VALIDATION_FAILED",
            "tel_audit_prefix.jsonl",
            lambda: _validate_tel(
                request,
                manifest,
                quarantine_receipt,
                candidate,
                claim_map,
                ucm,
                projector,
                aha,
                counterexamples,
                waveform,
                pmr_receipt,
                aperture,
                tel_rows,
                findings,
            ),
            tel_result,
        )

    upstream_values = [*parsed.values(), *(row for rows in jsonl.values() for row in rows)]
    if _walk_has_prohibited(upstream_values):
        findings.append(Finding("AUTHORITY_OR_PRIVATE_REASONING_BOUNDARY_VIOLATION", "REJECT", "run_root", "prohibited private/raw or positive-authority field detected"))
    findings = _unique_findings(findings)
    disposition = "REJECT" if any(item.severity == "REJECT" for item in findings) else ("HOLD" if findings else "PASS")
    reason_codes = sorted({item.code for item in findings}) or ["BOUNDED_AUDIT_CRITERIA_MET"]
    run_id = request.get("run_id") if _identifier(request.get("run_id")) else None
    logical_time = request.get("logical_time") if _text(request.get("logical_time")) else None
    candidate_id = candidate.get("candidate_id") if _identifier(candidate.get("candidate_id")) else None
    audit_seed = {"schema_version": AUDIT_VERSION, "run_id": run_id, "candidate_id": candidate_id, "input_digests": input_digests}
    audit_id = (
        "AUDIT-" + _sha256((_canonical_sha256(candidate) + _canonical_sha256(aperture)).encode("ascii"))[:24]
        if candidate and aperture
        else "AUDIT-" + _canonical_sha256(audit_seed)[:24]
    )
    artifact_types = {
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
    packet = {
        "schema_id": AUDIT_SCHEMA,
        "schema_version": AUDIT_VERSION,
        "packet_type": "sophia_totality_audit_packet",
        "audit_id": audit_id,
        "run_id": run_id,
        "logical_time": logical_time,
        "candidate_id": candidate_id,
        "producer_repository": SOPHIA_REPOSITORY,
        "producer": {"repository": SOPHIA_REPOSITORY, "role": "independent_totality_auditor", "version": AUDIT_VERSION},
        "input_digests": input_digests,
        "parent_list": [
            {
                "artifact_type": artifact_types[path],
                "path": path,
                "file_sha256": input_digests[path]["file_sha256"],
                "canonical_sha256": input_digests[path]["canonical_sha256"],
            }
            for path in INPUT_PATHS
        ],
        "disposition": disposition,
        "reason_codes": reason_codes,
        "findings": [item.to_dict() for item in findings],
        "claim_findings": claim_result.get("claim_findings", []),
        "recomputed_checks": {
            "grounding_identity_and_adequacy": grounding_valid,
            "candidate_request_and_span_binding": candidate_valid,
            "quarantine_receipt_binding": _validation_succeeded(quarantine_result),
            "quarantine_verification_binding": (
                request_valid
                and candidate_valid
                and _validation_succeeded(quarantine_result)
                and _validation_succeeded(quarantine_verification_result)
            ),
            "coherence_reperformed_exact_byte_proof_recorded": (
                _validation_succeeded(quarantine_result)
                and _validation_succeeded(quarantine_verification_result)
                and quarantine_verification_result.get(
                    "coherence_exact_byte_verification_recorded"
                )
                is True
            ),
            "raw_quarantine_bytes_independently_verified": False,
            "pmr_retention_gate_satisfied": (
                request_valid
                and candidate_valid
                and _validation_succeeded(pmr_result)
                and pmr_result.get("retention_gate_satisfied") is True
            ),
            "claim_evidence_exact_recomputation": claim_evidence_valid,
            "ucm_expected_context_binding": context_binding_valid,
            "full_posterior_and_equivalence_recomputation": projector_valid,
            "top_k_disposition_invariant": projector_valid and projector_result.get("top_k_invariant") is True,
            "residual_refusal_recomputed": residual_valid,
            "aha_status": aha_result.get("status") if aha_valid else None,
            "counterexamples_unresolved": counterexample_result.get("unresolved_count") if _validation_succeeded(counterexample_result) else None,
            "reference_waveform_recomputed": (
                _validation_succeeded(waveform_result)
                and waveform_result.get("valid") is True
            ),
            "aperture_decision": aperture_result.get("decision") if _validation_succeeded(aperture_result) else None,
            "tel_event_count": tel_result.get("event_count", 0),
            "tel_chronology_valid": _validation_succeeded(tel_result) and tel_result.get("valid") is True,
        },
        "authority_boundary_status": "REJECTED" if "AUTHORITY_OR_PRIVATE_REASONING_BOUNDARY_VIOLATION" in reason_codes else "BOUNDED",
        "requires_human_review": True,
        "permitted_next_route": "atlas_rejection_explanation_only" if disposition == "REJECT" else "atlas_posture_only",
        "return_route": _return_route(disposition, reason_codes),
        "nonauthority": dict.fromkeys(
            [
                "truth_certification", "final_answer_authority", "memory_write_authority",
                "training_authority", "canonization", "publication", "deployment", "release",
                "human_decision",
            ],
            False,
        ),
        "side_effects": dict.fromkeys(
            [
                "network_access_performed", "model_invocation_performed", "candidate_mutation_performed",
                "source_mutation_performed", "memory_write_performed", "training_performed",
                "canonization_performed", "publication_performed", "deployment_performed",
                "release_performed", "pmr_write_performed",
            ],
            False,
        ),
    }
    _write_packet(output, packet)
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently audit a local totality run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--output", help=f"Optional absolute output path named {OUTPUT_NAME}")
    args = parser.parse_args(argv)
    audit_totality_run(args.run_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
