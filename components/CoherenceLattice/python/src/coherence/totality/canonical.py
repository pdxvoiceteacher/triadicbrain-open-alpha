# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Strict canonical JSON and external-text validation.

This is the private convergence layer over the Community Edition canonical
profile.  It keeps CE's sorted, compact, newline-terminated UTF-8 encoding and
adds duplicate-member, NFC, default-ignorable, surrogate, and key checks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import OperationalError, ValidationError

HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
JSON_OBJECT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,999}$")
PROHIBITED_PROMPT_KEYS = {
    "render_prompt", "image_prompt", "scene_prompt", "scene_plan",
    "generation_prompt", "illustration_prompt",
}
PROHIBITED_AUTHORITY_KEYS = {
    "truth", "certified_truth", "truth_certification", "final_answer", "final_answer_authority",
    "memory_write", "memory_write_authority", "training", "training_authorization",
    "publication", "publication_authorization", "deployment", "deployment_authority",
    "release", "release_authorization", "authority_effect",
}

# Unicode provenance: UCD 17.0.0 DerivedCoreProperties.txt,
# Default_Ignorable_Code_Point; source SHA-256
# 24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08.
# License: Unicode License V3; see the root THIRD_PARTY_NOTICES.md.
# Frozen Unicode DerivedCoreProperties Default_Ignorable_Code_Point profile.
# This explicit range set keeps the boundary independent of the host Python
# Unicode database version.  Changing it is a versioned contract change.
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


def is_default_ignorable_code_point(codepoint: int) -> bool:
    """Return membership in the frozen Default_Ignorable_Code_Point profile."""

    index = bisect_right(_DEFAULT_IGNORABLE_CODE_POINT_STARTS, codepoint) - 1
    return (
        index >= 0
        and codepoint <= DEFAULT_IGNORABLE_CODE_POINT_RANGES[index][1]
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValidationError(f"JSON_DUPLICATE_MEMBER:{key}")
        output[key] = value
    return output


def _nonfinite_constant(value: str) -> None:
    raise ValidationError(f"JSON_NONFINITE_NUMBER:{value}")


def validate_unicode_text(value: str, path: str = "$", *, allow_newlines: bool = True) -> str:
    """Reject identity-obscuring Unicode without rewriting submitted text.

    Human prose may use any script.  Identifiers are separately ASCII-only.
    Default-ignorable format characters, bidi controls, non-NFC spellings,
    surrogates, NUL, and disallowed control characters fail closed.
    """

    if not isinstance(value, str):
        raise ValidationError(f"TYPE_STRING_REQUIRED:{path}")
    if unicodedata.normalize("NFC", value) != value:
        raise ValidationError(f"UNICODE_NFC_REQUIRED:{path}")
    for char in value:
        code = ord(char)
        category = unicodedata.category(char)
        if 0xD800 <= code <= 0xDFFF:
            raise ValidationError(f"UNICODE_SURROGATE_PROHIBITED:{path}")
        if char == "\x00":
            raise ValidationError(f"TEXT_NUL_PROHIBITED:{path}")
        if is_default_ignorable_code_point(code):
            raise ValidationError(f"UNICODE_DEFAULT_IGNORABLE_PROHIBITED:{path}:U+{code:04X}")
        if category == "Cc" and char not in ({"\n", "\t"} if allow_newlines else set()):
            raise ValidationError(f"UNICODE_CONTROL_PROHIBITED:{path}:U+{code:04X}")
    return value


def require_identifier(value: Any, path: str) -> str:
    """Return an ASCII identifier, rejecting homoglyph/confusable spellings."""

    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError(f"INVALID_ASCII_IDENTIFIER:{path}")
    return value


def require_json_object_key(value: Any, path: str) -> str:
    """Validate a bounded ASCII key, including safe POSIX artifact-map paths.

    This is intentionally distinct from :func:`require_identifier`: only JSON
    map keys may contain ``/``, and path-like keys remain relative and free of
    empty, current-directory, or parent-directory segments.
    """

    validate_unicode_text(value, path, allow_newlines=False)
    if JSON_OBJECT_KEY.fullmatch(value) is None:
        raise ValidationError(f"JSON_OBJECT_KEY_INVALID_ASCII:{path}")
    if "/" in value:
        segments = value.split("/")
        if any(not segment or segment in {".", ".."} for segment in segments):
            raise ValidationError(f"JSON_OBJECT_KEY_PATH_SEGMENT_INVALID:{path}")
    return value


def require_sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValidationError(f"INVALID_SHA256:{path}")
    return value


def require_exact_keys(
    value: Any,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    path: str = "$",
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"OBJECT_REQUIRED:{path}")
    required_set, optional_set = set(required), set(optional)
    missing = sorted(required_set - value.keys())
    extra = sorted(value.keys() - required_set - optional_set)
    if missing:
        raise ValidationError(f"MISSING_KEYS:{path}:{','.join(missing)}")
    if extra:
        raise ValidationError(f"EXTRA_KEYS:{path}:{','.join(extra)}")
    return value


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"JSON_NONFINITE_NUMBER:{path}")
        return
    if isinstance(value, str):
        validate_unicode_text(value, path)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            require_json_object_key(key, f"{path}.<key>")
            _validate_json_value(child, f"{path}.{key}")
        return
    raise ValidationError(f"JSON_TYPE_UNSUPPORTED:{path}:{type(value).__name__}")


def reject_prohibited_surfaces(value: Any, path: str = "$") -> None:
    """Block nested prompt-generation tunnels and positive authority claims."""

    if isinstance(value, dict):
        for key, child in value.items():
            folded = key.casefold()
            if folded in PROHIBITED_PROMPT_KEYS:
                raise ValidationError(f"PROHIBITED_PROMPT_SURFACE:{path}.{key}")
            if folded in PROHIBITED_AUTHORITY_KEYS:
                denied = child is False or child is None or (
                    isinstance(child, str)
                    and child in {"NONE", "DENY", "PROHIBITED", "NOT_AUTHORIZED"}
                )
                if not denied:
                    raise ValidationError(f"PROHIBITED_AUTHORITY_CLAIM:{path}.{key}")
            reject_prohibited_surfaces(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_prohibited_surfaces(child, f"{path}[{index}]")


def strict_json_syntax_loads(data: bytes | str) -> Any:
    """Parse external JSON without applying the semantic Unicode profile.

    Duplicate members, non-finite numbers, a UTF-8 BOM, invalid UTF-8, and
    malformed JSON remain syntax failures.  Parsed strings and object keys are
    intentionally left for the boundary's Draft 2020-12 schema and semantic
    validator, in that order.
    """

    if isinstance(data, bytes):
        if data.startswith(b"\xef\xbb\xbf"):
            raise ValidationError("JSON_UTF8_BOM_PROHIBITED")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError("JSON_UTF8_INVALID") from exc
    elif isinstance(data, str):
        text = data
    else:
        raise ValidationError("JSON_BYTES_OR_TEXT_REQUIRED")
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_nonfinite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValidationError(f"JSON_INVALID:{exc.lineno}:{exc.colno}") from exc


def strict_json_loads(data: bytes | str) -> Any:
    value = strict_json_syntax_loads(data)
    _validate_json_value(value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
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


def canonical_json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OperationalError(f"FILE_HASH_FAILED:{path.name}") from exc
    return digest.hexdigest()


def canonical_jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) for row in rows)


def write_canonical_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    try:
        with path.open(mode) as stream:
            stream.write(canonical_json_bytes(value))
    except FileExistsError as exc:
        raise OperationalError(f"OUTPUT_EXISTS:{path.name}") from exc
    except OSError as exc:
        raise OperationalError(f"OUTPUT_WRITE_FAILED:{path.name}") from exc
