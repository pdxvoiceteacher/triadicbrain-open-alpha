# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Deterministic grounding bundles with exact normalized-source spans."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .canonical import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    require_exact_keys,
    require_identifier,
    require_sha256,
    sha256_bytes,
    strict_json_loads,
    strict_json_syntax_loads,
    validate_unicode_text,
    write_canonical_json,
)
from .errors import OperationalError, ValidationError
from .schema_runtime import validate_schema_instance

GROUNDING_SCHEMA = "uvlm.coherence.totality.grounding_bundle.v1"
SEGMENT_SCHEMA = "uvlm.coherence.totality.grounding_segment.v1"
SEGMENTATION_PROFILE = "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_GROUNDING_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_GROUNDING_SEGMENTS_BYTES = 32 * 1024 * 1024
MAX_NORMALIZED_SOURCE_BYTES = 16 * 1024 * 1024


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _read_bounded(path: Path, maximum: int, code: str) -> bytes:
    try:
        if _link_like(path) or not path.is_file() or path.stat().st_size > maximum:
            raise ValidationError(code)
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
    except ValidationError:
        raise
    except OSError as exc:
        raise OperationalError(f"{code}_UNREADABLE") from exc
    if len(data) > maximum:
        raise ValidationError(code)
    return data
_PARAGRAPH = re.compile(r"\n[ \t]*\n+")

_MANIFEST_KEYS = {
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
_SEGMENT_KEYS = {
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


def normalize_source(source_bytes: bytes) -> tuple[str, bytes]:
    if not isinstance(source_bytes, bytes):
        raise ValidationError("GROUNDING_SOURCE_BYTES_REQUIRED")
    if not source_bytes or len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValidationError("GROUNDING_SOURCE_SIZE_INVALID")
    if source_bytes.startswith(b"\xef\xbb\xbf"):
        raise ValidationError("GROUNDING_UTF8_BOM_PROHIBITED")
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("GROUNDING_UTF8_INVALID") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    validate_unicode_text(text, "$.grounding_source")
    if not text:
        raise ValidationError("GROUNDING_SOURCE_EMPTY")
    normalized = text + "\n"
    return normalized, normalized.encode("utf-8")


def _span_bytes(text: str, char_offset: int) -> int:
    return len(text[:char_offset].encode("utf-8"))


def segment_source(normalized_source: str) -> list[dict[str, Any]]:
    if not normalized_source.endswith("\n"):
        raise ValidationError("GROUNDING_NORMALIZED_TRAILING_NEWLINE_REQUIRED")
    validate_unicode_text(normalized_source, "$.normalized_source")
    body = normalized_source[:-1]
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
            raise ValidationError("GROUNDING_SEGMENT_SPAN_INTERNAL_ERROR")
        end = start + len(excerpt)
        cursor = end
        excerpt_bytes = excerpt.encode("utf-8")
        rows.append(
            {
                "schema_id": SEGMENT_SCHEMA,
                "segment_id": f"SEG-{index:04d}",
                "index": index,
                "text": excerpt,
                "char_start": start,
                "char_end": end,
                "byte_start": _span_bytes(body, start),
                "byte_end": _span_bytes(body, end),
                "sha256": sha256_bytes(excerpt_bytes),
            }
        )
    if not rows:
        raise ValidationError("GROUNDING_NO_SEGMENTS")
    return rows


def build_grounding_bundle(source_bytes: bytes, *, bundle_id: str | None = None) -> dict[str, Any]:
    normalized_text, normalized_bytes = normalize_source(source_bytes)
    segments = segment_source(normalized_text)
    source_sha = sha256_bytes(source_bytes)
    resolved_id = bundle_id or f"GB-{source_sha[:20]}"
    require_identifier(resolved_id, "$.bundle_id")
    segments_bytes = canonical_jsonl_bytes(segments)
    manifest = {
        "schema_id": GROUNDING_SCHEMA,
        "bundle_id": resolved_id,
        "source_sha256": source_sha,
        "normalized_sha256": sha256_bytes(normalized_bytes),
        "source_bytes": len(source_bytes),
        "normalized_bytes": len(normalized_bytes),
        "segments_sha256": sha256_bytes(segments_bytes),
        "segment_count": len(segments),
        "segmentation": SEGMENTATION_PROFILE,
        "authority_effect": "NONE",
        "network_used": False,
    }
    return validate_grounding_runtime_boundary({
        "manifest": manifest,
        "source_bytes": source_bytes,
        "normalized_source": normalized_text,
        "segments": segments,
    })


def _validate_segment(row: Any, index: int, normalized: str) -> dict[str, Any]:
    path = f"$.segments[{index}]"
    require_exact_keys(row, required=_SEGMENT_KEYS, path=path)
    if row["schema_id"] != SEGMENT_SCHEMA or row["index"] != index + 1:
        raise ValidationError(f"GROUNDING_SEGMENT_IDENTITY_INVALID:{index}")
    if row["segment_id"] != f"SEG-{index + 1:04d}":
        raise ValidationError(f"GROUNDING_SEGMENT_ORDER_INVALID:{index}")
    text = row["text"]
    validate_unicode_text(text, f"{path}.text")
    for name in ("char_start", "char_end", "byte_start", "byte_end"):
        if not isinstance(row[name], int) or isinstance(row[name], bool) or row[name] < 0:
            raise ValidationError(f"GROUNDING_SEGMENT_OFFSET_INVALID:{index}:{name}")
    start, end = row["char_start"], row["char_end"]
    if start >= end or normalized[start:end] != text:
        raise ValidationError(f"GROUNDING_SEGMENT_EXACT_SPAN_MISMATCH:{index}")
    if _span_bytes(normalized, start) != row["byte_start"] or _span_bytes(normalized, end) != row["byte_end"]:
        raise ValidationError(f"GROUNDING_SEGMENT_BYTE_SPAN_MISMATCH:{index}")
    if sha256_bytes(text.encode("utf-8")) != require_sha256(row["sha256"], f"{path}.sha256"):
        raise ValidationError(f"GROUNDING_SEGMENT_SHA256_MISMATCH:{index}")
    return dict(row)


def validate_grounding_bundle(bundle: Any) -> dict[str, Any]:
    require_exact_keys(
        bundle,
        required={"manifest", "source_bytes", "normalized_source", "segments"},
    )
    source_bytes = bundle["source_bytes"]
    normalized, normalized_bytes = normalize_source(source_bytes)
    if bundle["normalized_source"] != normalized:
        raise ValidationError("GROUNDING_NORMALIZED_SOURCE_MISMATCH")
    manifest = bundle["manifest"]
    require_exact_keys(manifest, required=_MANIFEST_KEYS, path="$.manifest")
    if manifest["schema_id"] != GROUNDING_SCHEMA:
        raise ValidationError("GROUNDING_SCHEMA_MISMATCH")
    require_identifier(manifest["bundle_id"], "$.manifest.bundle_id")
    if manifest["segmentation"] != SEGMENTATION_PROFILE:
        raise ValidationError("GROUNDING_SEGMENTATION_PROFILE_MISMATCH")
    if manifest["authority_effect"] != "NONE" or manifest["network_used"] is not False:
        raise ValidationError("GROUNDING_NONAUTHORITY_POSTURE_INVALID")
    checks = {
        "source_sha256": sha256_bytes(source_bytes),
        "normalized_sha256": sha256_bytes(normalized_bytes),
    }
    for name, expected in checks.items():
        if require_sha256(manifest[name], f"$.manifest.{name}") != expected:
            raise ValidationError(f"GROUNDING_{name.upper()}_MISMATCH")
    if manifest["source_bytes"] != len(source_bytes) or manifest["normalized_bytes"] != len(normalized_bytes):
        raise ValidationError("GROUNDING_MANIFEST_BYTE_COUNT_MISMATCH")
    if not isinstance(bundle["segments"], list):
        raise ValidationError("GROUNDING_SEGMENTS_ARRAY_REQUIRED")
    validated = [_validate_segment(row, index, normalized) for index, row in enumerate(bundle["segments"])]
    expected = segment_source(normalized)
    if canonical_json_bytes(validated) != canonical_json_bytes(expected):
        raise ValidationError("GROUNDING_SEGMENT_CONTENT_OR_ORDER_MISMATCH")
    segment_bytes = canonical_jsonl_bytes(validated)
    if require_sha256(manifest["segments_sha256"], "$.manifest.segments_sha256") != sha256_bytes(segment_bytes):
        raise ValidationError("GROUNDING_SEGMENTS_SHA256_MISMATCH")
    if manifest["segment_count"] != len(validated) or not isinstance(manifest["segment_count"], int):
        raise ValidationError("GROUNDING_MANIFEST_SEGMENT_COUNT_MISMATCH")
    return {
        "manifest": dict(manifest),
        "source_bytes": source_bytes,
        "normalized_source": normalized,
        "segments": validated,
    }


def validate_grounding_runtime_boundary(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict) or "manifest" not in bundle:
        raise ValidationError("GROUNDING_BUNDLE_OBJECT_REQUIRED")
    validate_schema_instance(GROUNDING_SCHEMA, bundle["manifest"])
    return validate_grounding_bundle(bundle)


def write_grounding_bundle(bundle: Any, output_dir: Path) -> dict[str, Any]:
    validated = validate_grounding_runtime_boundary(bundle)
    if output_dir.exists() or _link_like(output_dir):
        raise OperationalError(f"GROUNDING_OUTPUT_EXISTS:{output_dir}")
    output_dir.mkdir(parents=True)
    (output_dir / "source.bin").write_bytes(validated["source_bytes"])
    (output_dir / "normalized_source.txt").write_text(
        validated["normalized_source"], encoding="utf-8", newline="\n"
    )
    (output_dir / "segments.jsonl").write_bytes(canonical_jsonl_bytes(validated["segments"]))
    write_canonical_json(output_dir / "manifest.json", validated["manifest"])
    return validated["manifest"]


def read_grounding_bundle(bundle_dir: Path) -> dict[str, Any]:
    if not bundle_dir.is_dir() or _link_like(bundle_dir):
        raise OperationalError("GROUNDING_BUNDLE_PATH_UNSAFE")
    expected = {"source.bin", "normalized_source.txt", "segments.jsonl", "manifest.json"}
    members = list(bundle_dir.iterdir())
    if any(_link_like(path) or not path.is_file() for path in members):
        raise ValidationError("GROUNDING_BUNDLE_LINK_OR_MEMBER_TYPE_PROHIBITED")
    actual = {path.name for path in members}
    if actual != expected:
        raise ValidationError("GROUNDING_BUNDLE_MEMBER_SET_MISMATCH")
    manifest = strict_json_syntax_loads(
        _read_bounded(
            bundle_dir / "manifest.json",
            MAX_GROUNDING_MANIFEST_BYTES,
            "GROUNDING_MANIFEST_SIZE_LIMIT_EXCEEDED",
        )
    )
    rows: list[dict[str, Any]] = []
    segments_raw = _read_bounded(
        bundle_dir / "segments.jsonl",
        MAX_GROUNDING_SEGMENTS_BYTES,
        "GROUNDING_SEGMENTS_SIZE_LIMIT_EXCEEDED",
    )
    for number, line in enumerate(segments_raw.splitlines(), start=1):
        value = strict_json_loads(line)
        if not isinstance(value, dict):
            raise ValidationError(f"GROUNDING_JSONL_OBJECT_REQUIRED:{number}")
        rows.append(value)
    bundle = {
        "manifest": manifest,
        "source_bytes": _read_bounded(
            bundle_dir / "source.bin",
            MAX_SOURCE_BYTES,
            "GROUNDING_SOURCE_SIZE_LIMIT_EXCEEDED",
        ),
        "normalized_source": _read_bounded(
            bundle_dir / "normalized_source.txt",
            MAX_NORMALIZED_SOURCE_BYTES,
            "GROUNDING_NORMALIZED_SIZE_LIMIT_EXCEEDED",
        ).decode("utf-8", errors="strict"),
        "segments": rows,
    }
    return validate_grounding_runtime_boundary(bundle)
