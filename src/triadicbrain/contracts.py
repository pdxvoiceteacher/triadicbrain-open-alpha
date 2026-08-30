"""Small, dependency-free helpers shared by the private-alpha commands."""

from __future__ import annotations

import hashlib
import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

AUTHORITY_DENIALS = {
    "truth_certification": False,
    "final_answer_authority": False,
    "memory_write_authority": False,
    "canonization_authority": False,
    "publication_authority": False,
    "deployment_authority": False,
    "release_authority": False,
    "model_invocation_authority": False,
    "automatic_phase_advance": False,
}

SIDE_EFFECT_DENIALS = {
    "network_used": False,
    "provider_invoked": False,
    "memory_written": False,
    "training_used": False,
    "publication_performed": False,
    "deployment_performed": False,
    "release_performed": False,
}

MAX_JSON_BYTES = 2 * 1024 * 1024
FIXTURE_NAME = "offline_demo_fixture.v1.json"


class ContractError(ValueError):
    """Raised when a bounded local artifact violates its closed contract."""


def canonical_json(value: Any) -> bytes:
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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_JSON_BYTES or payload.startswith(b"\xef\xbb\xbf"):
        raise ContractError(f"{label}: unsafe JSON encoding or size")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise ContractError(f"{label}: duplicate JSON member {key!r}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ContractError(f"{label}: non-finite JSON number {value}")

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label}: invalid JSON") from exc
    if not isinstance(value, dict) or canonical_json(value) != payload:
        raise ContractError(f"{label}: canonical JSON object required")
    return value


def fixture_bytes() -> bytes:
    return resources.files("triadicbrain.resources").joinpath(FIXTURE_NAME).read_bytes()


def load_fixture() -> tuple[dict[str, Any], bytes]:
    payload = fixture_bytes()
    value = parse_canonical_object(payload, FIXTURE_NAME)
    required = {
        "candidate_text",
        "claim_text",
        "fixture_id",
        "logical_time",
        "request_id",
        "run_id",
        "schema_id",
        "source_label",
        "source_text",
        "task",
        "uncertainty",
    }
    if set(value) != required or value.get("schema_id") != "uvlm.triadicbrain.offline_demo_fixture.v1":
        raise ContractError("offline fixture contract invalid")
    for key in required - {"schema_id"}:
        if not isinstance(value[key], str) or not value[key] or "\x00" in value[key]:
            raise ContractError(f"offline fixture field invalid: {key}")
    return value, payload


def is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


def require_new_output(path: Path) -> tuple[Path, Path]:
    if not path.is_absolute() or path == Path(path.anchor):
        raise ContractError("output must be an absolute bounded path")
    if os.path.lexists(path) or is_link_like(path):
        raise ContractError("output must not already exist")
    parent = path.parent
    if not parent.is_dir() or is_link_like(parent):
        raise ContractError("output parent must be an existing ordinary directory")
    resolved_parent = parent.resolve(strict=True)
    resolved = resolved_parent / path.name
    if resolved.parent != resolved_parent:
        raise ContractError("output path escapes its parent")
    return resolved, resolved_parent

