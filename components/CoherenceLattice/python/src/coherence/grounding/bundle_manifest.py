from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(source_text: str, source_label: str, media_type: str = "text/plain") -> dict:
    source_sha = sha256_text(source_text)
    normalized = sha256_text("\n".join(line.strip() for line in source_text.splitlines() if line.strip()))
    return {
        "schema": "coherencelattice.grounding_bundle.v1",
        "source_id": f"grounding:sha256:{normalized}",
        "source_label": source_label,
        "source_sha256": source_sha,
        "normalized_sha256": normalized,
        "media_type": media_type,
        "artifacts": {
            "source_md": "source.md",
            "segments_jsonl": "segments.jsonl",
            "conversion_report_json": "conversion_report.json",
        },
    }


def bundle_dir(out_root: Path, normalized_sha256: str) -> Path:
    return out_root / normalized_sha256
