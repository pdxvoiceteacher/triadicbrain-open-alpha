from __future__ import annotations

from dataclasses import dataclass
import hashlib
import unicodedata

NORMALIZATION_VERSION = "v2"


@dataclass(frozen=True)
class DecodedText:
    text: str
    source_sha256: str
    source_encoding: str
    decode_strategy: str
    had_replacement: bool
    replacement_count: int


def build_source_integrity_packet(
    *,
    source_label: str | None,
    source_filename: str | None,
    source_extension: str | None,
    source_sha256: str | None,
    normalized_sha256: str | None,
    source_encoding: str | None,
    decode_strategy: str | None,
    had_replacement: bool,
    replacement_count: int,
    text: str,
) -> dict:
    markers = {m: text.count(m) for m in ("Â", "Î", "Ã", "â")}
    literal_placeholder_count = text.count("?")
    suspected_symbol_loss = literal_placeholder_count >= 20
    warnings: list[str] = []
    if (source_encoding or "").lower() not in {"utf-8", "utf-8-sig"}:
        warnings.append("source_not_utf8")
    if literal_placeholder_count > 0:
        warnings.append("literal_question_mark_placeholders_detected")
    if suspected_symbol_loss:
        warnings.append("possible_symbol_loss")
    if replacement_count > 0:
        warnings.append("replacement_characters_detected")

    status = "clean"
    if any(markers.values()) and replacement_count > 0:
        status = "corrupted_source"
    elif replacement_count > 0:
        status = "lossy_decode"
    elif warnings:
        status = "decoded_with_warnings"

    return {
        "source_label": source_label,
        "source_filename": source_filename,
        "source_extension": source_extension,
        "source_sha256": source_sha256,
        "normalized_sha256": normalized_sha256,
        "source_encoding": source_encoding,
        "decode_strategy": decode_strategy,
        "normalization_version": NORMALIZATION_VERSION,
        "had_replacement": bool(had_replacement),
        "replacement_count": int(replacement_count),
        "unicode_mojibake_markers": markers,
        "literal_placeholder_count": literal_placeholder_count,
        "suspected_symbol_loss": suspected_symbol_loss,
        "source_integrity_status": status,
        "warnings": warnings,
    }


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    return text


def _has_utf16_bom(raw: bytes) -> bool:
    return raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff")


def _null_ratio(raw: bytes) -> float:
    if not raw:
        return 0.0
    sample = raw[:256]
    return sample.count(0) / len(sample)


def _looks_suspicious_utf16_text(text: str) -> bool:
    if not text:
        return False

    sample = text[:4000]
    total = max(len(sample), 1)

    cjk_like = sum(0x3400 <= ord(ch) <= 0x9FFF for ch in sample) / total
    spaces_and_newlines = sum(ch in {" ", "\n", "\t"} for ch in sample) / total
    ascii_letters = sum(("a" <= ch.lower() <= "z") for ch in sample) / total

    return (
        cjk_like > 0.15
        and spaces_and_newlines < 0.03
        and ascii_letters < 0.10
    )


def decode_text_bytes(
    raw: bytes,
    *,
    preferred_encoding: str | None = None,
    fail_on_lossy_decode: bool = False,
) -> DecodedText:
    source_sha256 = hashlib.sha256(raw).hexdigest()

    candidates: list[str] = []

    if preferred_encoding and preferred_encoding.lower() != "auto":
        candidates.append(preferred_encoding)
    else:
        if raw.startswith(b"\xef\xbb\xbf"):
            candidates.append("utf-8-sig")
        candidates.extend(["utf-8-sig", "utf-8"])
        if _has_utf16_bom(raw) or _null_ratio(raw) >= 0.20:
            candidates.extend(["utf-16", "utf-16-le", "utf-16-be"])
        candidates.extend(["cp1252", "latin-1"])

    tried: set[str] = set()
    for enc in candidates:
        if enc in tried:
            continue
        tried.add(enc)

        try:
            text = raw.decode(enc, errors="strict")
            text = _normalize_text(text)

            if enc.startswith("utf-16") and not _has_utf16_bom(raw):
                if _looks_suspicious_utf16_text(text):
                    continue

            return DecodedText(
                text=text,
                source_sha256=source_sha256,
                source_encoding=enc,
                decode_strategy="strict",
                had_replacement=False,
                replacement_count=0,
            )
        except UnicodeDecodeError:
            continue

    text = raw.decode("utf-8", errors="replace")
    replacement_count = text.count("\ufffd")
    if fail_on_lossy_decode and replacement_count > 0:
        raise UnicodeDecodeError(
            "utf-8",
            raw,
            0,
            len(raw),
            "lossy decode would introduce replacement characters",
        )

    text = _normalize_text(text)
    return DecodedText(
        text=text,
        source_sha256=source_sha256,
        source_encoding="utf-8",
        decode_strategy="replace",
        had_replacement=replacement_count > 0,
        replacement_count=replacement_count,
    )
