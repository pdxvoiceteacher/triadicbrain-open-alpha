"""Packaged Draft 2020-12 schemas for totality runtime boundaries."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import OperationalError, ValidationError

REQUEST_SCHEMA_ID = "uvlm.coherence.totality.request_envelope.v1"
GROUNDING_SCHEMA_ID = "uvlm.coherence.totality.grounding_bundle.v1"
CANDIDATE_SCHEMA_ID = "uvlm.sonya.totality.candidate_packet.v1"

SCHEMA_FILES = {
    REQUEST_SCHEMA_ID: "request_envelope.v1.schema.json",
    GROUNDING_SCHEMA_ID: "grounding_bundle.v1.schema.json",
    CANDIDATE_SCHEMA_ID: "candidate_packet.v1.schema.json",
}
_FAILURE_CODES = {
    REQUEST_SCHEMA_ID: "REQUEST_JSON_SCHEMA_INVALID",
    GROUNDING_SCHEMA_ID: "GROUNDING_JSON_SCHEMA_INVALID",
    CANDIDATE_SCHEMA_ID: "CANDIDATE_JSON_SCHEMA_INVALID",
}


def _source_schema_root() -> Path:
    return Path(__file__).resolve().parents[4] / "schema" / "totality"


def packaged_schema_bytes(schema_id: str) -> bytes:
    filename = SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise ValidationError("RUNTIME_SCHEMA_ID_UNKNOWN")
    try:
        return (
            resources.files("coherence.totality")
            .joinpath("schemas", filename)
            .read_bytes()
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise OperationalError(f"PACKAGED_SCHEMA_UNAVAILABLE:{filename}") from exc


def verify_source_package_schema_parity() -> dict[str, str]:
    """Require byte identity whenever the source schema tree is available."""

    source_root = _source_schema_root()
    receipts: dict[str, str] = {}
    for schema_id, filename in SCHEMA_FILES.items():
        packaged = packaged_schema_bytes(schema_id)
        source_path = source_root / filename
        if source_path.exists():
            try:
                source = source_path.read_bytes()
            except OSError as exc:
                raise OperationalError(f"SOURCE_SCHEMA_UNAVAILABLE:{filename}") from exc
            if source != packaged:
                raise ValidationError(f"PACKAGED_SCHEMA_PARITY_MISMATCH:{filename}")
        receipts[schema_id] = filename
    return receipts


@lru_cache(maxsize=None)
def load_runtime_schema(schema_id: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise ValidationError("RUNTIME_SCHEMA_ID_UNKNOWN")
    verify_source_package_schema_parity()
    try:
        value = json.loads(packaged_schema_bytes(schema_id).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"PACKAGED_SCHEMA_JSON_INVALID:{filename}") from exc
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValidationError(f"PACKAGED_SCHEMA_DRAFT202012_INVALID:{filename}") from exc
    if value.get("$id") != schema_id:
        raise ValidationError(f"PACKAGED_SCHEMA_ID_MISMATCH:{filename}")
    return value


def validate_schema_instance(schema_id: str, value: Any) -> Any:
    validator = Draft202012Validator(load_runtime_schema(schema_id))
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        raise ValidationError(
            f"{_FAILURE_CODES[schema_id]}:{path}:{error.validator}"
        )
    return value
