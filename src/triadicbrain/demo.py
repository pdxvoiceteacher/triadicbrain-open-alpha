"""Deterministic, provider-free private-alpha fixture route."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .contracts import (
    AUTHORITY_DENIALS,
    SIDE_EFFECT_DENIALS,
    ContractError,
    canonical_json,
    load_fixture,
    require_new_output,
    sha256_bytes,
)


def _artifact_set() -> tuple[dict[str, bytes], str]:
    fixture, fixture_raw = load_fixture()
    source = (fixture["source_text"] + "\n").encode("utf-8")
    source_sha = sha256_bytes(source)
    segment_sha = sha256_bytes(fixture["source_text"].encode("utf-8"))
    request = {
        "authority_effect": "NONE",
        "grounding_bundle_path": "grounding_bundle.json",
        "logical_time": fixture["logical_time"],
        "request_id": fixture["request_id"],
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.request_envelope.v1",
        "source_sha256": source_sha,
        "task": fixture["task"],
    }
    request_raw = canonical_json(request)
    grounding = {
        "authority_effect": "NONE",
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.grounding_bundle.v1",
        "segments": [
            {
                "exact_excerpt": fixture["source_text"],
                "segment_id": "SEG-0001",
                "segment_sha256": segment_sha,
            }
        ],
        "source_label": fixture["source_label"],
        "source_path": "source.txt",
        "source_sha256": source_sha,
    }
    grounding_raw = canonical_json(grounding)
    candidate = {
        "answer": fixture["candidate_text"],
        "authority_boundary": dict(AUTHORITY_DENIALS),
        "candidate_is_not_final_answer": True,
        "claims": [
            {
                "claim_id": "CLM-0001",
                "evidence_status": "SOURCE_SUPPORTED_FIXTURE_ONLY",
                "segment_id": "SEG-0001",
                "segment_sha256": segment_sha,
                "text": fixture["claim_text"],
            }
        ],
        "grounding_bundle_sha256": sha256_bytes(grounding_raw),
        "logical_time": fixture["logical_time"],
        "request_sha256": sha256_bytes(request_raw),
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.candidate_packet.v1",
        "side_effects": dict(SIDE_EFFECT_DENIALS),
        "uncertainty": fixture["uncertainty"],
    }
    candidate_raw = canonical_json(candidate)
    sophia = {
        "authority_boundary": dict(AUTHORITY_DENIALS),
        "candidate_rewritten": False,
        "candidate_sha256": sha256_bytes(candidate_raw),
        "disposition": "PASS_BOUNDED_FIXTURE_REQUIRES_HUMAN_REVIEW",
        "reason_codes": ["FIXTURE_GROUNDED", "HUMAN_DECISION_REQUIRED"],
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.sophia_audit.v1",
        "side_effects": dict(SIDE_EFFECT_DENIALS),
    }
    sophia_raw = canonical_json(sophia)
    atlas = {
        "authority_boundary": dict(AUTHORITY_DENIALS),
        "canonization_performed": False,
        "human_decision": "PENDING",
        "orientation": "READY_FOR_BOUNDED_HUMAN_REVIEW",
        "publication_posture": "BLOCKED",
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.atlas_posture.v1",
        "side_effects": dict(SIDE_EFFECT_DENIALS),
        "sophia_audit_sha256": sha256_bytes(sophia_raw),
    }
    atlas_raw = canonical_json(atlas)
    human = {
        "allowed_decisions": ["APPROVE", "HOLD", "REJECT", "REPAIR"],
        "authority_effect": "NONE",
        "atlas_posture_sha256": sha256_bytes(atlas_raw),
        "decision": "PENDING",
        "decision_overwritten_by_automation": False,
        "requires_human_review": True,
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.human_review.v1",
    }
    files = {
        "atlas_posture.json": atlas_raw,
        "candidate_packet.json": candidate_raw,
        "grounding_bundle.json": grounding_raw,
        "human_review.json": canonical_json(human),
        "request_envelope.json": request_raw,
        "source.txt": source,
        "sophia_audit.json": sophia_raw,
    }
    rows = [
        {"bytes": len(files[name]), "path": name, "sha256": sha256_bytes(files[name])}
        for name in sorted(files)
    ]
    manifest = {
        "artifact_count": len(rows),
        "artifacts": rows,
        "authority_effect": "NONE",
        "fixture_sha256": sha256_bytes(fixture_raw),
        "logical_time": fixture["logical_time"],
        "run_id": fixture["run_id"],
        "schema_id": "uvlm.triadicbrain.offline_demo_manifest.v1",
        "side_effects": dict(SIDE_EFFECT_DENIALS),
    }
    files["run_manifest.json"] = canonical_json(manifest)
    checksums = "".join(
        f"{sha256_bytes(files[name])}  {name}\n" for name in sorted(files)
    ).encode("ascii")
    files["SHA256SUMS.txt"] = checksums
    closure = sha256_bytes(
        canonical_json(
            [
                {"bytes": len(files[name]), "path": name, "sha256": sha256_bytes(files[name])}
                for name in sorted(files)
            ]
        )
    )
    return files, closure


def run_demo(output_dir: Path) -> dict[str, Any]:
    output, parent = require_new_output(output_dir)
    files, closure = _artifact_set()
    stage = Path(tempfile.mkdtemp(prefix=".triadicbrain-demo-", dir=parent))
    try:
        for name in sorted(files):
            target = stage / name
            target.write_bytes(files[name])
        if sorted(path.name for path in stage.iterdir()) != sorted(files):
            raise ContractError("demo stage topology mismatch")
        os.replace(stage, output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "artifact_count": len(files),
        "artifact_set_sha256": closure,
        "authority_effect": "NONE",
        "provider_invoked": False,
        "schema_id": "uvlm.triadicbrain.demo_result.v1",
    }
