from __future__ import annotations

import re


UNICODE_REPLACEMENTS: list[tuple[str, str]] = [
    ("Î", "Δ"),
    ("Î", "Λ"),
    ("Î¨", "Ψ"),
    ("ÎΨ", "Ψ"),
    ("ÎS", "ΔS"),
    ("DeltaS", "ΔS"),
    ("Delta S", "ΔS"),
    ("ÎT", "ΛT"),
    ("Lambda_T", "ΛT"),
    ("Psi", "Ψ"),
    ("Eâ", "Eₛ"),
    ("â", "ₛ"),
    ("E_s", "Eₛ"),
    ("Â¹", "¹"),
    ("Â²", "²"),
    ("Â³", "³"),
]

ASCII_REPLACEMENTS: list[tuple[str, str]] = [
    ("Ψ", "Psi"),
    ("ΔS", "DeltaS"),
    ("ΛT", "Lambda_T"),
    ("Eₛ", "E_s"),
]


def normalize_symbol_text(text: str, *, ascii_safe: bool = False) -> str:
    if not isinstance(text, str) or not text:
        return ""

    out = text.replace("\u00a0", " ")

    for src, dst in UNICODE_REPLACEMENTS:
        out = out.replace(src, dst)

    out = re.sub(r"(ΛT|Ψ|ΔS|Eₛ)([A-Za-z])", r"\1 \2", out)

    if ascii_safe:
        for src, dst in ASCII_REPLACEMENTS:
            out = out.replace(src, dst)

    return out


def sanitize_presentation_text(text: str, *, normalization_profile_id: str | None = None) -> str:
    out = normalize_symbol_text(text or "")
    if not out:
        return ""
    out = (
        out.replace("ÎT", "ΛT")
        .replace("Î", "Λ")
        .replace("Î", "Δ")
        .replace("ÎS", "ΔS")
        .replace("Î¨", "Ψ")
        .replace("Eâ", "Eₛ")
        .replace("Eâ", "Eₛ")
        .replace("Â¹", "¹")
        .replace("Â²", "²")
        .replace("Â³", "³")
        .replace("Ã", "")
    )
    out = re.sub(r"\bΛ\s+T\b", "ΛT", out)
    out = re.sub(r"\bΔ\s+S\b", "ΔS", out)
    out = re.sub(r"Eₛabove", "Eₛ above", out)
    out = re.sub(r"ΛTwithin", "ΛT within", out)
    out = re.sub(r"Ψthat", "Ψ that", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


# BACKWARD-COMPAT SHIM
# Older callers still import normalize_text directly.
def normalize_text(text: str, *, ascii_safe: bool = False) -> str:
    return normalize_symbol_text(text, ascii_safe=ascii_safe)


def canonical_symbol_token(term: str) -> str:
    return normalize_symbol_text(term, ascii_safe=True).strip()


# BACKWARD-COMPAT SHIM
# Older governance code paths import normalize_symbol directly.
def normalize_symbol(term: str) -> str:
    return canonical_symbol_token(term)


def normalize_text_list(values, *, ascii_safe: bool = False, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        if value is None:
            continue
        text = normalize_symbol_text(str(value), ascii_safe=ascii_safe).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break

    return out


def canonical_bundle_uri(bundle_manifest_path: str | None, normalized_sha256: str | None) -> str:
    if isinstance(normalized_sha256, str) and normalized_sha256.strip():
        return f"local://grounding/{normalized_sha256.strip()}/manifest.json"

    if isinstance(bundle_manifest_path, str) and bundle_manifest_path.strip():
        return f"local://{bundle_manifest_path.strip().replace(chr(92), '/')}"

    return "local://unknown"


__all__ = [
    "normalize_symbol_text",
    "normalize_text",
    "normalize_symbol",
    "canonical_symbol_token",
    "normalize_text_list",
    "canonical_bundle_uri",
    "sanitize_presentation_text",
]
