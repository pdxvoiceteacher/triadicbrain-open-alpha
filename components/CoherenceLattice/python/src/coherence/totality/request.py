"""Canonical totality request envelope and the sole explicit legacy projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .canonical import (
    canonical_json_bytes,
    require_exact_keys,
    require_identifier,
    require_sha256,
    reject_prohibited_surfaces,
    strict_json_syntax_loads,
    validate_unicode_text,
)
from .errors import ValidationError
from .schema_runtime import validate_schema_instance

REQUEST_SCHEMA = "uvlm.coherence.totality.request_envelope.v1"
REQUEST_KINDS = {"plain_text", "grounded_text", "document_qa", "batch"}
SOURCE_KINDS = {"inline_text", "file_text", "atlas_prior", "fixture", "grounding_bundle"}
GROUNDING_SOURCE_ID = re.compile(r"^SRC-[0-9a-f]{20}$")

_REF_KEYS = {
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


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _nonempty_text(value: Any, path: str, *, maximum: int = 100_000) -> str:
    validate_unicode_text(value, path)
    if not value.strip() or len(value) > maximum:
        raise ValidationError(f"TEXT_LENGTH_INVALID:{path}")
    return value


def _grounding_ref(value: Any, index: int) -> dict[str, Any]:
    path = f"$.grounding[{index}]"
    require_exact_keys(value, required={"source_kind"}, optional=_REF_KEYS - {"source_kind"}, path=path)
    kind = value["source_kind"]
    if kind not in SOURCE_KINDS:
        raise ValidationError(f"GROUNDING_SOURCE_KIND_INVALID:{index}")
    output: dict[str, Any] = {"source_kind": kind}
    for name in sorted(_REF_KEYS - {"source_kind"}):
        if name not in value:
            continue
        item = value[name]
        if name == "metadata":
            if not isinstance(item, dict):
                raise ValidationError(f"OBJECT_REQUIRED:{path}.metadata")
            output[name] = _freeze_json(item)
        elif name in {"bundle_manifest_sha256", "normalized_sha256", "source_sha256"}:
            output[name] = require_sha256(item, f"{path}.{name}")
        elif item is None:
            output[name] = None
        else:
            output[name] = _nonempty_text(item, f"{path}.{name}", maximum=20_000)
    if kind == "grounding_bundle":
        required = {
            "source_id", "media_type", "bundle_manifest_path", "bundle_manifest_sha256",
            "source_sha256", "normalized_sha256",
        }
        missing = sorted(name for name in required if not output.get(name))
        if missing:
            raise ValidationError(f"GROUNDING_BUNDLE_FIELDS_REQUIRED:{index}:{','.join(missing)}")
        require_identifier(output["source_id"], f"{path}.source_id")
        if GROUNDING_SOURCE_ID.fullmatch(output["source_id"]) is None:
            raise ValidationError(f"GROUNDING_BUNDLE_SOURCE_ID_INVALID:{index}")
        if output["media_type"] not in {"text/plain", "text/markdown"}:
            raise ValidationError(f"GROUNDING_BUNDLE_MEDIA_TYPE_INVALID:{index}")
        if any(output.get(name) is not None for name in ("text",)):
            raise ValidationError(f"GROUNDING_BUNDLE_INLINE_TEXT_PROHIBITED:{index}")
    elif kind == "inline_text" and not output.get("text"):
        raise ValidationError(f"INLINE_GROUNDING_TEXT_REQUIRED:{index}")
    return output


@dataclass(frozen=True)
class RequestEnvelope:
    """Frozen validated envelope; ``to_dict`` is the canonical bridge value."""

    request_id: str
    run_id: str
    logical_time: str
    kind: Literal["plain_text", "grounded_text", "document_qa", "batch"]
    user_input: str
    grounding: tuple[Mapping[str, Any], ...]
    task_consent: bool
    retention_requested: bool
    model: str | None
    divergence_mode: str | None
    meta: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": REQUEST_SCHEMA,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "logical_time": self.logical_time,
            "kind": self.kind,
            "user_input": self.user_input,
            "grounding": [_thaw_json(item) for item in self.grounding],
            "task_consent": self.task_consent,
            "retention_requested": self.retention_requested,
            "model": self.model,
            "divergence_mode": self.divergence_mode,
            "meta": _thaw_json(self.meta),
        }


def validate_request_envelope(value: Any) -> RequestEnvelope:
    # Apply the canonical recursive Unicode/key profile to extension objects
    # too; Draft 2020-12 validation has already run on the external parse path.
    canonical_json_bytes(value)
    reject_prohibited_surfaces(value)
    required = {
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
    require_exact_keys(value, required=required)
    if value["schema_id"] != REQUEST_SCHEMA:
        raise ValidationError("REQUEST_SCHEMA_MISMATCH")
    request_id = require_identifier(value["request_id"], "$.request_id")
    run_id = require_identifier(value["run_id"], "$.run_id")
    logical_time = _nonempty_text(value["logical_time"], "$.logical_time", maximum=128)
    kind = value["kind"]
    if kind not in REQUEST_KINDS:
        raise ValidationError("REQUEST_KIND_INVALID")
    user_input = _nonempty_text(value["user_input"], "$.user_input", maximum=100_000)
    grounding = value["grounding"]
    if not isinstance(grounding, list) or len(grounding) > 1000:
        raise ValidationError("REQUEST_GROUNDING_ARRAY_INVALID")
    normalized = tuple(MappingProxyType(_grounding_ref(item, index)) for index, item in enumerate(grounding))
    if kind == "plain_text" and normalized:
        raise ValidationError("PLAIN_TEXT_GROUNDING_PROHIBITED")
    if kind in {"grounded_text", "document_qa"} and not normalized:
        raise ValidationError("GROUNDED_REQUEST_REQUIRES_GROUNDING")
    if not isinstance(value["task_consent"], bool) or not isinstance(value["retention_requested"], bool):
        raise ValidationError("REQUEST_CONSENT_BOOLEAN_REQUIRED")
    for optional_text in ("model", "divergence_mode"):
        item = value[optional_text]
        if item is not None:
            _nonempty_text(item, f"$.{optional_text}", maximum=256)
    if not isinstance(value["meta"], dict):
        raise ValidationError("REQUEST_META_OBJECT_REQUIRED")
    return RequestEnvelope(
        request_id=request_id,
        run_id=run_id,
        logical_time=logical_time,
        kind=kind,
        user_input=user_input,
        grounding=normalized,
        task_consent=value["task_consent"],
        retention_requested=value["retention_requested"],
        model=value["model"],
        divergence_mode=value["divergence_mode"],
        meta=_freeze_json(value["meta"]),
    )


def parse_request_envelope(data: bytes | str) -> RequestEnvelope:
    value = strict_json_syntax_loads(data)
    validate_schema_instance(REQUEST_SCHEMA, value)
    return validate_request_envelope(value)


def project_legacy_request(
    legacy: Any,
    *,
    request_id: str,
    run_id: str,
    logical_time: str,
    task_consent: bool,
    bundle_manifest_sha256_by_path: Mapping[str, str] | None = None,
) -> RequestEnvelope:
    """Explicitly project the pre-totality Pydantic shape; no implicit fallback."""

    required = {"kind", "user_input", "grounding", "experiment", "model", "divergence_mode", "meta"}
    require_exact_keys(legacy, required=required, path="$.legacy")
    if legacy["experiment"] is not None:
        if not isinstance(legacy["experiment"], dict):
            raise ValidationError("LEGACY_EXPERIMENT_OBJECT_REQUIRED")
        meta = {**legacy["meta"], "legacy_experiment": dict(legacy["experiment"]), "legacy_projection": "explicit_v1"}
    else:
        meta = {**legacy["meta"], "legacy_projection": "explicit_v1"}
    grounding = [dict(item) for item in legacy["grounding"]]
    supplied_hashes = dict(bundle_manifest_sha256_by_path or {})
    for index, ref in enumerate(grounding):
        if ref.get("source_kind") != "grounding_bundle" or ref.get("bundle_manifest_sha256"):
            continue
        manifest_path = ref.get("bundle_manifest_path")
        digest = supplied_hashes.get(manifest_path)
        if digest is None:
            raise ValidationError(f"LEGACY_GROUNDING_BUNDLE_MANIFEST_HASH_REQUIRED:{index}")
        ref["bundle_manifest_sha256"] = require_sha256(
            digest, f"$.legacy.grounding[{index}].bundle_manifest_sha256"
        )
    projected = {
        "schema_id": REQUEST_SCHEMA,
        "request_id": request_id,
        "run_id": run_id,
        "logical_time": logical_time,
        "kind": legacy["kind"],
        "user_input": legacy["user_input"],
        "grounding": grounding,
        "task_consent": task_consent,
        "retention_requested": False,
        "model": legacy["model"],
        "divergence_mode": legacy["divergence_mode"],
        "meta": meta,
    }
    return validate_request_envelope(projected)
