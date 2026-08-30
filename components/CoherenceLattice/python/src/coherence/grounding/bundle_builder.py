from __future__ import annotations

import json
import re
from pathlib import Path

from coherence.context.symbol_normalize import normalize_text
from coherence.grounding.bundle_manifest import build_manifest, bundle_dir
from coherence.grounding.text_decode import decode_text_bytes


def _repair_common_source_artifacts(text: str) -> str:
    replacements = {
        "Â¹": "¹",
        "Â²": "²",
        "Â³": "³",
        "\\Lambda_T": "ΛT",
        "\\Psi": "Ψ",
        "\\Delta S": "ΔS",
        "\\DeltaS": "ΔS",
        "E_s": "Eₛ",
        "?T": "ΔT",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _iter_paragraph_segments(text: str) -> list[dict]:
    lines = text.splitlines()
    current_section = "source"
    paragraph: list[str] = []
    segments: list[dict] = []
    line_start = 1
    para_index = 0

    def flush(end_line: int):
        nonlocal paragraph, para_index, line_start
        if not paragraph:
            return
        body = "\n".join(paragraph).strip()
        if body:
            para_index += 1
            segments.append(
                {
                    "segment_id": f"seg-{para_index:04d}",
                    "kind": "text",
                    "locator": {
                        "section": current_section,
                        "line_start": line_start,
                        "line_end": end_line,
                    },
                    "paragraph_index": para_index,
                    "body_md": body,
                    "quality_score": 0.95,
                }
            )
        paragraph = []

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        is_heading = bool(re.match(r"^(\d+(\.\d+)*|[A-Z][A-Za-z0-9 /&\-\(\)]+):?$", line)) and len(line) < 120
        if is_heading:
            flush(idx - 1)
            current_section = line
            line_start = idx
            continue

        if not line:
            flush(idx - 1)
            line_start = idx + 1
            continue

        if not paragraph:
            line_start = idx
        paragraph.append(raw_line.rstrip())

    flush(len(lines))
    return segments


def build_grounding_bundle(
    source_file: Path,
    source_label: str,
    out_root: Path,
    media_type: str = "text/plain",
    *,
    preferred_encoding: str | None = None,
    fail_on_lossy_decode: bool = False,
) -> dict:
    raw = source_file.read_bytes()
    decoded = decode_text_bytes(
        raw,
        preferred_encoding=preferred_encoding,
        fail_on_lossy_decode=fail_on_lossy_decode,
    )
    text = normalize_text(_repair_common_source_artifacts(decoded.text))

    manifest = build_manifest(text, source_label=source_label, media_type=media_type)
    manifest["source_sha256"] = decoded.source_sha256
    manifest["source_encoding"] = decoded.source_encoding
    manifest["decode_strategy"] = decoded.decode_strategy
    manifest["had_replacement"] = decoded.had_replacement
    manifest["replacement_count"] = decoded.replacement_count

    bdir = bundle_dir(out_root, manifest["normalized_sha256"])
    bdir.mkdir(parents=True, exist_ok=True)

    (bdir / "source.md").write_text(text, encoding="utf-8")

    segments = _iter_paragraph_segments(text)
    segments_path = bdir / "segments.jsonl"
    with segments_path.open("w", encoding="utf-8") as f:
        for seg in segments[:400]:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")

    conversion_report = {
        "line_count": len(text.splitlines()),
        "segment_count": min(len(segments), 400),
        "source_encoding": decoded.source_encoding,
        "decode_strategy": decoded.decode_strategy,
        "had_replacement": decoded.had_replacement,
        "replacement_count": decoded.replacement_count,
        "segmentation_mode": "paragraph_heading_v2",
    }
    (bdir / "conversion_report.json").write_text(
        json.dumps(conversion_report, indent=2),
        encoding="utf-8",
    )
    (bdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return {
        "manifest": manifest,
        "bundle_dir": str(bdir),
        "manifest_path": str(bdir / "manifest.json"),
    }
