from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python" / "src"))

from atlas.triadic.totality_posture import (  # noqa: E402
    ATLAS_INPUTS,
    AUDITED_INPUTS,
    AUDITED_TYPES,
    DEFAULT_IGNORABLE_CODE_POINT_PROFILE,
    DEFAULT_IGNORABLE_CODE_POINT_RANGES,
    TotalityPostureError,
    _is_default_ignorable_code_point,
    _validate_pmr_receipt,
    _validate_unicode,
    assign_totality_posture,
)
from atlas.triadic.human_review_ui import (  # noqa: E402
    HumanReviewError,
    create_app,
    load_sealed_run,
)


# Unicode provenance: UCD 17.0.0 DerivedCoreProperties.txt,
# Default_Ignorable_Code_Point; source SHA-256
# 24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08.
# License: Unicode License V3; see the projection root THIRD_PARTY_NOTICES.md.
EXPECTED_DEFAULT_IGNORABLE_CODE_POINT_RANGES = (
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


def canonical(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)


def put(root: Path, relative: str, data: bytes | dict) -> bytes:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(data) if isinstance(data, dict) else data
    path.write_bytes(payload)
    return payload


def seal_totality_fixture_for_ui(root: Path) -> None:
    request = json.loads((root / "request.json").read_bytes())
    candidate = json.loads((root / "candidate_packet.json").read_bytes())
    post_core = (
        "atlas_posture_packet.json",
        "checksums.sha256",
        "final_review.html",
        "run_manifest.json",
        "sealed_artifact_manifest.json",
        "sophia_audit_packet.json",
        "tel_events.jsonl",
        "tel_finalization_receipt.json",
    )

    def rows(exclude=()):
        return [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": digest(path.read_bytes()),
                "bytes": len(path.read_bytes()),
            }
            for path in sorted(
                (item for item in root.rglob("*") if item.is_file()),
                key=lambda item: item.relative_to(root).as_posix(),
            )
            if path.relative_to(root).as_posix() not in set(exclude)
        ]

    core_rows = rows(("core_manifest.json", *post_core))
    put(
        root,
        "core_manifest.json",
        {
            "schema_id": "uvlm.coherence.totality.core_manifest.v1",
            "run_id": request["run_id"],
            "logical_time": request["logical_time"],
            "manifest_scope": "IMMUTABLE_CORE_BUILD_BEFORE_EXTERNAL_AUDIT",
            "post_core_artifacts_excluded": list(post_core),
            "artifact_count": len(core_rows),
            "artifact_bytes": sum(row["bytes"] for row in core_rows),
            "artifacts": core_rows,
            "authority_effect": "NONE",
        },
    )
    repository_identity = {
        "repository": "TriadicGate-fixture",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True,
        "status_sha256": digest(b""),
    }
    effect_ceiling = dict.fromkeys(
        (
            "network",
            "provider_invocation",
            "memory_write",
            "training",
            "canonization",
            "publication",
            "deployment",
            "release",
            "truth_certification",
        ),
        False,
    )
    payload = rows(
        ("sealed_artifact_manifest.json", "run_manifest.json", "checksums.sha256")
    )
    put(
        root,
        "sealed_artifact_manifest.json",
        {
            "schema_id": "uvlm.coherence.totality.sealed_artifact_manifest.v1",
            "run_id": request["run_id"],
            "logical_time": request["logical_time"],
            "repository_identity": repository_identity,
            "effect_ceiling": effect_ceiling,
            "payload_count": len(payload),
            "payload_bytes": sum(row["bytes"] for row in payload),
            "files": payload,
            "authority_effect": "NONE",
        },
    )
    manifest_rows = rows(("run_manifest.json", "checksums.sha256"))
    put(
        root,
        "run_manifest.json",
        {
            "schema_id": "uvlm.coherence.totality.run_manifest.v1",
            "run_id": request["run_id"],
            "logical_time": request["logical_time"],
            "request_sha256": digest((root / "request.json").read_bytes()),
            "candidate_sha256": digest((root / "candidate_packet.json").read_bytes()),
            "core_manifest_sha256": digest((root / "core_manifest.json").read_bytes()),
            "sealed_artifact_manifest_sha256": digest(
                (root / "sealed_artifact_manifest.json").read_bytes()
            ),
            "repository_identity": repository_identity,
            "effect_ceiling": effect_ceiling,
            "artifact_count": len(manifest_rows),
            "artifact_bytes": sum(row["bytes"] for row in manifest_rows),
            "artifacts": manifest_rows,
            "authority_effect": "NONE",
            "human_review_required": True,
        },
    )
    checksum_rows = rows(("checksums.sha256",))
    (root / "checksums.sha256").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in checksum_rows),
        encoding="utf-8",
        newline="\n",
    )


def totality_run(
    root: Path, disposition: str = "PASS", *, with_retention_consent: bool = False
) -> Path:
    root.mkdir(parents=True)
    run_id, logical_time = "atlas-totality-test", "fixture-logical-time"
    source = b"Grounded <source> excerpt.\n"
    segment = {
        "schema_id": "uvlm.coherence.totality.grounding_segment.v1",
        "segment_id": "SEG-0001",
        "index": 1,
        "text": "Grounded <source> excerpt.",
        "char_start": 0,
        "char_end": 26,
        "byte_start": 0,
        "byte_end": 26,
        "sha256": digest(b"Grounded <source> excerpt."),
    }
    segment_bytes = canonical(segment)
    manifest = {
        "schema_id": "uvlm.coherence.totality.grounding_bundle.v1",
        "bundle_id": "GB-test",
        "source_sha256": digest(source),
        "normalized_sha256": digest(source),
        "source_bytes": len(source),
        "normalized_bytes": len(source),
        "segments_sha256": digest(segment_bytes),
        "segment_count": 1,
        "segmentation": "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1",
        "authority_effect": "NONE",
        "network_used": False,
    }
    request = {
        "schema_id": "uvlm.coherence.totality.request_envelope.v1",
        "request_id": "REQ-test",
        "run_id": run_id,
        "logical_time": logical_time,
        "kind": "grounded_text",
        "user_input": "Assess <img src=x onerror=alert(1)> evidence.",
        "grounding": [
            {
                "source_kind": "grounding_bundle",
                "bundle_manifest_path": "grounding/manifest.json",
                "bundle_manifest_sha256": digest(canonical(manifest)),
                "source_sha256": manifest["source_sha256"],
                "normalized_sha256": manifest["normalized_sha256"],
            }
        ],
        "task_consent": True,
        "retention_requested": with_retention_consent,
        "model": None,
        "divergence_mode": None,
        "meta": {},
    }
    candidate_text = "Candidate <script>alert(1)</script> statement."
    claim_text = "Candidate <script>alert(1)</script> statement."
    raw_capture = canonical(
        {
            "answer": candidate_text,
            "claims": [{"claim_id": "CLAIM-1", "text": claim_text}],
            "uncertainty": 0.3,
        }
    )
    candidate_reference = {
        "source_sha256": manifest["source_sha256"],
        "segment_id": segment["segment_id"],
        "segment_sha256": segment["sha256"],
        "source_span": {
            "char_start": segment["char_start"],
            "char_end": segment["char_end"],
            "byte_start": segment["byte_start"],
            "byte_end": segment["byte_end"],
        },
        "exact_excerpt_sha256": segment["sha256"],
        "claim_text_sha256": digest(claim_text.encode("utf-8")),
        "candidate_relation": "SUPPORTS",
    }
    candidate = {
        "schema_id": "uvlm.sonya.totality.candidate_packet.v1",
        "candidate_id": "CAND-test",
        "run_id": run_id,
        "logical_time": logical_time,
        "request_sha256": digest(canonical(request)),
        "adapter_id": "sonya.captured.test",
        "model_identity": "captured-no-provider",
        "raw_output_sha256": digest(raw_capture),
        "answer": candidate_text,
        "uncertainty": 0.3,
        "claims": [
            {
                "claim_id": "CLAIM-1",
                "text": claim_text,
                "answer_start": 0,
                "answer_end": len(claim_text),
                "candidate_evidence_references": [candidate_reference],
            }
        ],
        "candidate_not_final_answer": True,
        "model_output_not_authority": True,
        "not_truth_certification": True,
        "not_memory_authorization": True,
        "not_training_authorization": True,
        "not_publication_authorization": True,
        "not_deployment_authority": True,
        "not_release_authorization": True,
        "human_review_required": True,
    }
    quarantine_receipt = {
        "schema_id": "uvlm.sonya.totality.quarantine_receipt.v1",
        "adapter_id": candidate["adapter_id"],
        "request_sha256": candidate["request_sha256"],
        "raw_output_sha256": candidate["raw_output_sha256"],
        "raw_output_bytes": len(raw_capture),
        "quarantine_member": "raw_output.quarantine",
        "raw_output_quarantined": True,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    quarantine_verification = {
        "schema_id": "uvlm.sonya.totality.quarantine_verification_receipt.v1",
        "run_id": run_id,
        "logical_time": logical_time,
        "request_sha256": candidate["request_sha256"],
        "adapter_id": candidate["adapter_id"],
        "quarantine_member": quarantine_receipt["quarantine_member"],
        "raw_output_sha256": candidate["raw_output_sha256"],
        "raw_output_bytes": quarantine_receipt["raw_output_bytes"],
        "quarantine_receipt_sha256": digest(canonical(quarantine_receipt)),
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": digest(canonical(candidate)),
        "verification": {
            "path_binding_valid": True,
            "exact_byte_count_valid": True,
            "exact_sha256_valid": True,
            "strict_utf8_json_valid": True,
            "semantic_capture_schema_valid": True,
            "candidate_binding_valid": True,
        },
        "raw_output_disclosed": False,
        "effects": {
            "network": False,
            "provider_invocation": False,
            "memory_write": False,
            "training": False,
            "publication": False,
            "deployment": False,
            "release": False,
        },
        "authority_effect": "NONE",
    }
    claim_map = {
        "schema_id": "uvlm.coherence.totality.claim_evidence_map.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": digest(canonical(candidate)),
        "grounding_manifest_sha256": digest(canonical(manifest)),
        "source_sha256": manifest["source_sha256"],
        "mapping_method": "CANDIDATE_DECLARED_EXACT_CITATION_INTEGRITY_V1",
        "claims": [
            {
                "claim_id": "CLAIM-1",
                "text": claim_text,
                "answer_span": {"char_start": 0, "char_end": len(claim_text)},
                "support_status": "CITATION_VERIFIED_REVIEW_REQUIRED",
                "residual_tokens": ["alert", "candidate", "script", "statement"],
                "evidence": [
                    {
                        **candidate_reference,
                        "exact_excerpt": segment["text"],
                        "overlap_tokens": [],
                        "token_coverage": 0.0,
                        "citation_integrity": "VERIFIED",
                        "integrity_reason_codes": [],
                    }
                ],
            }
        ],
        "unsupported_claim_ids": [],
        "authority_effect": "NONE",
    }
    ucm = {
        "schema_id": "uvlm.coherence.totality.ucm_state.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "expected_context": {"task_kind": "grounded_text"},
        "axes": {"E_cpl": 0.8, "T_tr": 0.75},
        "hypotheses": [
            {
                "hypothesis_id": "H-1",
                "equivalence_group": "EQ-1",
                "score": 1.0,
                "pattern_posture": "KNOWN",
            },
            {
                "hypothesis_id": "H-2",
                "equivalence_group": "EQ-2",
                "score": 0.0,
                "pattern_posture": "KNOWN",
            },
        ],
        "unsupported_claim_ids": [],
        "authority_effect": "NONE",
    }
    projector = {
        "schema_id": "uvlm.coherence.totality.projector_receipt.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "ucm_state_sha256": digest(canonical(ucm)),
        "expected_context": ucm["expected_context"],
        "psi_cl": 0.6,
        "full_candidate_posterior": [
            {"hypothesis_id": "H-1", "equivalence_group": "EQ-1", "score": 1.0, "probability": 0.7310585786},
            {"hypothesis_id": "H-2", "equivalence_group": "EQ-2", "score": 0.0, "probability": 0.2689414214},
        ],
        "full_equivalence_posterior": [
            {"equivalence_group": "EQ-1", "probability": 0.7310585786},
            {"equivalence_group": "EQ-2", "probability": 0.2689414214},
        ],
        "full_posterior_margin": 0.4621171572,
        "disposition": "PASS_SCREEN",
        "reasons": [],
        "presentation": {
            "top_k": 1,
            "candidates": [
                {"hypothesis_id": "H-1", "equivalence_group": "EQ-1", "score": 1.0, "probability": 0.7310585786}
            ],
            "retained_mass": 0.7310585786,
            "omitted_mass": 0.2689414214,
            "disposition_invariant_to_top_k": True,
        },
        "authority_effect": "NONE",
        "human_review_required": True,
    }
    residual = {
        "schema_id": "uvlm.coherence.totality.residual_refusal.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "projector_receipt_sha256": digest(canonical(projector)),
        "residual": {
            "omitted_probability_mass": 0.2689414214,
            "unsupported_claim_ids": [],
            "ambiguity": False,
            "ood_hypothesis_ids": [],
            "new_pattern_hypothesis_ids": [],
        },
        "refusal": {"triggered": False, "reason_codes": []},
        "disposition": "PASS_SCREEN",
        "reasons": [],
        "authority_effect": "NONE",
    }
    aha = {
        "schema_id": "uvlm.coherence.totality.aha_result.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "status": "AVAILABLE",
        "target_graph": {"nodes": ["target"], "relations": ["target-rel"]},
        "donor_graph": {"nodes": ["donor"], "relations": ["donor-rel"]},
        "mappings": [{"target": "target", "donor": "donor"}],
        "disanalogies": ["scope differs"],
        "comparator": "compare measured outcomes",
        "observable": "outcome delta",
        "falsification": "mapping fails when delta reverses",
        "reject_criteria": ["causal mismatch"],
        "authority_effect": "NONE",
    }
    counterexamples = {
        "schema_id": "uvlm.coherence.totality.counterexamples.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "counterexamples": [{"counterexample_id": "CE-1", "detail": "conflicting boundary case"}],
        "conflicts": ["minority evidence retained"],
        "search_complete": True,
        "authority_effect": "NONE",
    }
    waveform = {
        "schema_id": "uvlm.coherence.totality.reference_waveform.v1",
        "codec": "AXIOMATIC_SYNTHETIC_FIVE_AXIS_SINE_CODEC_V1",
        "sample_count": 16,
        "axis_order": [
            "E_cpl",
            "T_tr",
            "E_s",
            "phase_stability_lambda",
            "mutual_containment_mu",
        ],
        "samples": [0.0] * 16,
        "mean_square_energy": 0.0,
        "synthetic_reference_only": True,
        "physical_frequency_claim": False,
        "cross_domain_utility_established": False,
        "claim_ceiling": "REFERENCE CODEC ONLY; NOT A PHYSICAL FREQUENCY OF A PERSON, ARCHETYPE, OR SYSTEM",
        "authority_effect": "NONE",
    }
    aperture = {
        "schema_id": "uvlm.coherence.totality.aperture_decision.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "hard_gates": {"task_consent": True, "privacy": True, "retention_separate": True},
        "noncompensatory": True,
        "decision": "PASS_SCREEN",
        "reasons": [],
        "human_review_required": True,
        "candidate_is_final_answer": False,
        "authority_effect": "NONE",
    }
    tel_event = {
        "schema_id": "uvlm.coherence.totality.tel_event.v1",
        "sequence": 1,
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "event": "CANDIDATE_CANONICALIZED",
        "authority_effect": "NONE",
    }
    pmr = {
        "schema_id": "uvlm.pmr.totality.receipt.v1",
        "run_id": run_id,
        "candidate_id": candidate["candidate_id"],
        "logical_time": logical_time,
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": None,
        "consent_status": "NOT_GRANTED",
        "reason_codes": ["RETENTION_NOT_REQUESTED"],
        "events": [],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    consent = None
    if with_retention_consent:
        consent_id = "CONSENT-test"
        consent = {
            "schema_id": "uvlm.pmr.totality.consent.v1",
            "consent_id": consent_id,
            "run_id": run_id,
            "candidate_id": candidate["candidate_id"],
            "logical_time": logical_time,
            "decision": "GRANT",
            "scope": "PROVENANCE_REFERENCE_ONLY",
            "quota_bytes": 1024,
            "expires_logical_time": None,
            "training_allowed": False,
            "federation_allowed": False,
            "authority_effect": "NONE",
        }
        pmr.update(
            consent_id=consent_id,
            consent_status="ACTIVE",
            reason_codes=["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"],
            events=[
                {
                    "schema_id": "uvlm.pmr.totality.reference_event.v1",
                    "sequence": 1,
                    "logical_time": "PMR+000001",
                    "event_type": "CONSENT_GRANTED",
                    "consent_id": consent_id,
                    "run_id": run_id,
                    "candidate_id": candidate["candidate_id"],
                    "lineage_id": None,
                    "detail": {"scope": "PROVENANCE_REFERENCE_ONLY", "quota_bytes": 1024},
                    "persistent_write_performed": False,
                    "training_used": False,
                    "federation_used": False,
                    "authority_effect": "NONE",
                }
            ],
        )

    values: dict[str, bytes | dict] = {
        "request.json": request,
        "grounding/manifest.json": manifest,
        "grounding/source.bin": source,
        "grounding/normalized_source.txt": source,
        "grounding/segments.jsonl": segment_bytes,
        "sonya/quarantine_receipt.json": quarantine_receipt,
        "sonya/quarantine_verification_receipt.json": quarantine_verification,
        "candidate_packet.json": candidate,
        "claim_evidence_map.json": claim_map,
        "ucm_state.json": ucm,
        "projector_receipt.json": projector,
        "residual_refusal.json": residual,
        "aha_result.json": aha,
        "counterexamples.json": counterexamples,
        "reference_waveform.json": waveform,
        "pmr_receipt.json": pmr,
        "aperture_decision.json": aperture,
        "tel_audit_prefix.jsonl": canonical(tel_event),
    }
    if consent is not None:
        values["pmr_consent.json"] = consent
    raw = {relative: put(root, relative, value) for relative, value in values.items()}
    put(root, "sonya/raw_output.quarantine", raw_capture)
    objects = {relative: value for relative, value in values.items() if isinstance(value, dict)}
    input_digests = {
        relative: (
            {
                "file_sha256": digest(raw[relative]),
                "canonical_sha256": (
                    digest(canonical(objects[relative]))
                    if relative in objects
                    else digest(raw[relative]) if relative.endswith(".jsonl") else None
                ),
            }
            if relative in raw
            else {"file_sha256": None, "canonical_sha256": None}
        )
        for relative in AUDITED_INPUTS
    }
    sophia = {
        "schema_id": "uvlm.sophia.totality.audit_packet.v1",
        "schema_version": "1.0",
        "packet_type": "sophia_totality_audit_packet",
        "audit_id": "AUDIT-" + "1" * 24,
        "producer_repository": "pdxvoiceteacher/Sophia",
        "producer": {"repository": "pdxvoiceteacher/Sophia", "role": "independent_totality_auditor", "version": "1.0"},
        "run_id": run_id,
        "logical_time": logical_time,
        "candidate_id": candidate["candidate_id"],
        "input_digests": input_digests,
        "parent_list": [
            {"artifact_type": AUDITED_TYPES[relative], "path": relative, **input_digests[relative]}
            for relative in AUDITED_INPUTS
        ],
        "disposition": disposition,
        "reason_codes": ["BOUNDED_AUDIT_CRITERIA_MET"] if disposition == "PASS" else [f"FIXTURE_{disposition}"],
        "findings": [] if disposition == "PASS" else [{"code": f"FIXTURE_{disposition}", "severity": disposition, "artifact": "candidate_packet.json", "detail": "fixture finding"}],
        "claim_findings": [{"claim_id": "CLAIM-1", "support_status": "SUPPORTED", "reason_codes": []}],
        "recomputed_checks": {"claim_evidence_exact_spans": True, "projector_full_posterior": True},
        "authority_boundary_status": "BOUNDED",
        "requires_human_review": True,
        "permitted_next_route": "atlas_rejection_explanation_only" if disposition == "REJECT" else "atlas_posture_only",
        "return_route": {
            "route": {"PASS": "NONE", "HOLD": "CLARIFY", "REJECT": "REPAIR"}[disposition],
            "destination": {
                "PASS": "NONE",
                "HOLD": "COHERENCELATTICE",
                "REJECT": "SONYA_OR_COHERENCELATTICE",
            }[disposition],
            "status": "NOT_REQUIRED" if disposition == "PASS" else "REQUESTED_NOT_EXECUTED",
            "reason_codes": [] if disposition == "PASS" else [f"FIXTURE_{disposition}"],
            "candidate_mutation_performed": False,
            "source_mutation_performed": False,
            "automatic_rerun_performed": False,
            "authority_effect": "NONE",
        },
        "nonauthority": dict.fromkeys(
            (
                "truth_certification",
                "final_answer_authority",
                "memory_write_authority",
                "training_authority",
                "canonization",
                "publication",
                "deployment",
                "release",
                "human_decision",
            ),
            False,
        ),
        "side_effects": dict.fromkeys(
            (
                "network_access_performed",
                "model_invocation_performed",
                "candidate_mutation_performed",
                "source_mutation_performed",
                "memory_write_performed",
                "training_performed",
                "canonization_performed",
                "publication_performed",
                "deployment_performed",
                "release_performed",
                "pmr_write_performed",
            ),
            False,
        ),
    }
    put(root, "sophia_audit_packet.json", sophia)
    return root


def test_atlas_frozen_default_ignorable_profile_is_exact() -> None:
    assert DEFAULT_IGNORABLE_CODE_POINT_PROFILE == (
        "UCD_DERIVED_CORE_PROPERTIES_DEFAULT_IGNORABLE_CODE_POINT_V1"
    )
    assert (
        DEFAULT_IGNORABLE_CODE_POINT_RANGES
        == EXPECTED_DEFAULT_IGNORABLE_CODE_POINT_RANGES
    )
    for start, end in EXPECTED_DEFAULT_IGNORABLE_CODE_POINT_RANGES:
        for codepoint in {start, end}:
            assert _is_default_ignorable_code_point(codepoint) is True
            with pytest.raises(TotalityPostureError, match="DEFAULT_IGNORABLE"):
                _validate_unicode(f"left{chr(codepoint)}right", "$.probe")
        assert _is_default_ignorable_code_point(start - 1) is False
        assert _is_default_ignorable_code_point(end + 1) is False
    _validate_unicode("left\u0600right", "$.non_dicp_format")


def test_atlas_actual_candidate_boundary_rejects_nonformat_default_ignorable(
    tmp_path: Path,
) -> None:
    root = totality_run(tmp_path / "dicp", "HOLD")
    candidate_path = root / "candidate_packet.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["answer"] = "hidden\ufe00answer"
    candidate_path.write_bytes(canonical(candidate))

    with pytest.raises(TotalityPostureError, match="UNICODE_DEFAULT_IGNORABLE"):
        assign_totality_posture(root)
    assert not (root / "atlas_posture_packet.json").exists()
    assert not (root / "final_review.html").exists()


@pytest.mark.parametrize(
    ("disposition", "retention", "publication"),
    [
        ("PASS", "retain_for_human_review", "publication_blocked_pending_human_review"),
        ("HOLD", "quarantine", "do_not_publish"),
        ("REJECT", "rejected", "do_not_publish"),
    ],
)
def test_all_sophia_dispositions_are_oriented_deterministically_without_rewrite(
    tmp_path: Path, disposition: str, retention: str, publication: str
) -> None:
    root = totality_run(tmp_path / disposition.lower(), disposition)
    before = {relative: root.joinpath(*relative.split("/")).read_bytes() for relative in ATLAS_INPUTS}
    first = assign_totality_posture(root)
    first_files = (root / "atlas_posture_packet.json").read_bytes(), (root / "final_review.html").read_bytes()
    second = assign_totality_posture(root)
    assert first == second
    assert first_files == ((root / "atlas_posture_packet.json").read_bytes(), (root / "final_review.html").read_bytes())
    assert (first["retention_posture"], first["publication_posture"]) == (retention, publication)
    assert first["human_action_required"] is True and first["human_decision"] == "PENDING"
    assert first["human_decision_options"] == ["APPROVE", "HOLD", "REJECT", "REPAIR"]
    assert all(value is False for value in first["nonauthority"].values())
    assert all(value is False for value in first["side_effects"].values())
    assert before == {relative: root.joinpath(*relative.split("/")).read_bytes() for relative in ATLAS_INPUTS}


def test_sophia_return_route_mismatch_rejects_without_candidate_mutation(
    tmp_path: Path,
) -> None:
    root = totality_run(tmp_path / "return-route", "HOLD")
    candidate_before = (root / "candidate_packet.json").read_bytes()
    sophia_path = root / "sophia_audit_packet.json"
    sophia = json.loads(sophia_path.read_text(encoding="utf-8"))
    sophia["return_route"]["route"] = "REPAIR"
    sophia_path.write_bytes(canonical(sophia))

    with pytest.raises(TotalityPostureError, match="SOPHIA_RETURN_ROUTE_INVALID"):
        assign_totality_posture(root)
    assert (root / "candidate_packet.json").read_bytes() == candidate_before


def test_consent_present_is_an_explicit_atlas_parent(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "consented", with_retention_consent=True)
    packet = assign_totality_posture(root)
    paths = [parent["path"] for parent in packet["parent_list"]]
    assert "pmr_consent.json" in paths
    assert paths.index("pmr_consent.json") < paths.index("pmr_receipt.json")
    assert packet["input_digests"]["pmr_consent.json"]["file_sha256"] == digest(
        (root / "pmr_consent.json").read_bytes()
    )


def test_review_is_accessible_escaped_and_displays_complete_bounded_context(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    assign_totality_posture(root)
    review = (root / "final_review.html").read_text(encoding="utf-8")
    assert '<main id="main" tabindex="-1">' in review and '<a class="skip" href="#main">' in review
    assert (
        "<caption>Candidate-declared citations and exact integrity checks</caption>"
        in review
        and 'scope="col"' in review
    )
    assert "SUPPORTS" in review and "VERIFIED" in review
    assert "<script>alert(1)</script>" not in review and "&lt;script&gt;alert(1)&lt;/script&gt;" in review
    assert '<img src=x onerror=alert(1)>' not in review and "&lt;img src=x onerror=alert(1)&gt;" in review
    for text in (
        "Candidate, not answer",
        "Grounded &lt;source&gt; excerpt.",
        "full_candidate_posterior",
        "full_equivalence_posterior",
        "disposition_invariant_to_top_k",
        "ood_hypothesis_ids",
        "new_pattern_hypothesis_ids",
        "disanalogies",
        "falsification",
        "reject_criteria",
        "conflicting boundary case",
        "noncompensatory",
        "BOUNDED_AUDIT_CRITERIA_MET",
        "separate, revocable lane",
        "APPROVE",
        "HOLD",
        "REJECT",
        "REPAIR",
    ):
        assert text in review


def test_sophia_digest_tamper_fails_closed_and_writes_nothing(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    sophia_path = root / "sophia_audit_packet.json"
    sophia = json.loads(sophia_path.read_text(encoding="utf-8"))
    sophia["input_digests"]["counterexamples.json"]["file_sha256"] = "0" * 64
    sophia_path.write_bytes(canonical(sophia))
    with pytest.raises(TotalityPostureError, match="SOPHIA_INPUT_DIGEST_MISMATCH"):
        assign_totality_posture(root)
    assert not (root / "atlas_posture_packet.json").exists()
    assert not (root / "final_review.html").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda evidence: evidence.update(
            citation_integrity="INVALID", integrity_reason_codes=[]
        ),
        lambda evidence: evidence.update(candidate_relation="LIMITS"),
    ],
)
def test_atlas_revalidates_citation_display_contract_after_bound_input_change(
    tmp_path: Path, mutation,
) -> None:
    root = totality_run(tmp_path / "citation-display")
    claim_map_path = root / "claim_evidence_map.json"
    claim_map = json.loads(claim_map_path.read_text(encoding="utf-8"))
    mutation(claim_map["claims"][0]["evidence"][0])
    claim_map_path.write_bytes(canonical(claim_map))

    sophia_path = root / "sophia_audit_packet.json"
    sophia = json.loads(sophia_path.read_text(encoding="utf-8"))
    rebound = {
        "file_sha256": digest(claim_map_path.read_bytes()),
        "canonical_sha256": digest(canonical(claim_map)),
    }
    sophia["input_digests"]["claim_evidence_map.json"] = rebound
    next(
        parent
        for parent in sophia["parent_list"]
        if parent["path"] == "claim_evidence_map.json"
    ).update(rebound)
    sophia_path.write_bytes(canonical(sophia))

    with pytest.raises(TotalityPostureError, match="CLAIM_MAP_EVIDENCE_INVALID"):
        assign_totality_posture(root)
    assert not (root / "atlas_posture_packet.json").exists()
    assert not (root / "final_review.html").exists()


def test_upstream_file_tamper_fails_closed(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    counter_path = root / "counterexamples.json"
    counter = json.loads(counter_path.read_text(encoding="utf-8"))
    counter["conflicts"].append("tampered")
    counter_path.write_bytes(canonical(counter))
    with pytest.raises(TotalityPostureError, match="SOPHIA_INPUT_DIGEST_MISMATCH"):
        assign_totality_posture(root)


def test_atlas_rejects_parent_junction_without_opening_external_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = totality_run(tmp_path / "junction-run")
    external = tmp_path / "external-grounding"
    (root / "grounding").rename(external)
    make_directory_link(root / "grounding", external)
    secret = external / "manifest.json"
    original_open = Path.open

    def reject_external_open(path: Path, *args, **kwargs):
        if path.resolve(strict=False) == secret.resolve(strict=True):
            raise AssertionError("external junction member was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_external_open)
    with pytest.raises(TotalityPostureError, match="LINK_OR_JUNCTION"):
        assign_totality_posture(root)
    assert not (root / "atlas_posture_packet.json").exists()


def test_positive_authority_and_pmr_write_fail_closed(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "authority")
    aperture_path = root / "aperture_decision.json"
    aperture = json.loads(aperture_path.read_text(encoding="utf-8"))
    aperture["truth_certified"] = True
    aperture_path.write_bytes(canonical(aperture))
    with pytest.raises(TotalityPostureError, match="POSITIVE_AUTHORITY_PROHIBITED"):
        assign_totality_posture(root)

    root = totality_run(tmp_path / "pmr")
    pmr_path = root / "pmr_receipt.json"
    pmr = json.loads(pmr_path.read_text(encoding="utf-8"))
    pmr["persistent_bytes_written"] = 1
    pmr_path.write_bytes(canonical(pmr))
    with pytest.raises(TotalityPostureError, match="SOPHIA_INPUT_DIGEST_MISMATCH"):
        assign_totality_posture(root)


@pytest.mark.parametrize(
    ("first_event", "status"),
    [("CONSENT_GRANTED", "ACTIVE"), ("CONSENT_DENIED", "INACTIVE")],
)
def test_separately_consented_no_write_pmr_lifecycle_is_accepted(
    first_event: str, status: str
) -> None:
    request = {"retention_requested": True}
    candidate = {"candidate_id": "CAND-test"}
    consent_id = "CONSENT-test"
    event = {
        "schema_id": "uvlm.pmr.totality.reference_event.v1",
        "sequence": 1,
        "logical_time": "PMR+000001",
        "event_type": first_event,
        "consent_id": consent_id,
        "run_id": "RUN-test",
        "candidate_id": candidate["candidate_id"],
        "lineage_id": None,
        "detail": {"scope": "PROVENANCE_REFERENCE_ONLY", "quota_bytes": 1024},
        "persistent_write_performed": False,
        "training_used": False,
        "federation_used": False,
        "authority_effect": "NONE",
    }
    receipt = {
        "schema_id": "uvlm.pmr.totality.receipt.v1",
        "run_id": "RUN-test",
        "candidate_id": candidate["candidate_id"],
        "logical_time": "T0",
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": consent_id,
        "consent_status": status,
        "reason_codes": ["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"],
        "events": [event],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    _validate_pmr_receipt(
        receipt,
        request,
        candidate,
        run_id="RUN-test",
        logical_time="T0",
    )


def test_pmr_event_effect_or_bad_lifecycle_fails_closed() -> None:
    candidate = {"candidate_id": "CAND-test"}
    event = {
        "schema_id": "uvlm.pmr.totality.reference_event.v1",
        "sequence": 1,
        "logical_time": "PMR+000001",
        "event_type": "CONSENT_GRANTED",
        "consent_id": "CONSENT-test",
        "run_id": "RUN-test",
        "candidate_id": candidate["candidate_id"],
        "lineage_id": None,
        "detail": {},
        "persistent_write_performed": True,
        "training_used": False,
        "federation_used": False,
        "authority_effect": "NONE",
    }
    receipt = {
        "schema_id": "uvlm.pmr.totality.receipt.v1",
        "run_id": "RUN-test",
        "candidate_id": candidate["candidate_id"],
        "logical_time": "T0",
        "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
        "consent_id": "CONSENT-test",
        "consent_status": "ACTIVE",
        "reason_codes": ["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"],
        "events": [event],
        "retained": False,
        "persistent_bytes_written": 0,
        "network_used": False,
        "federation_used": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    with pytest.raises(TotalityPostureError, match="PMR_EVENT_CONTRACT_INVALID"):
        _validate_pmr_receipt(
            receipt,
            {"retention_requested": True},
            candidate,
            run_id="RUN-test",
            logical_time="T0",
        )


def test_explicit_aha_unavailable_posture_is_presented(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    aha_path = root / "aha_result.json"
    aha = json.loads(aha_path.read_text(encoding="utf-8"))
    aha.update(status="UNAVAILABLE", disposition="UNAVAILABLE", reason_codes=["AHA_CASE_NOT_SUPPLIED"])
    aha_path.write_bytes(canonical(aha))

    sophia_path = root / "sophia_audit_packet.json"
    sophia = json.loads(sophia_path.read_text(encoding="utf-8"))
    rebound = {
        "file_sha256": digest(aha_path.read_bytes()),
        "canonical_sha256": digest(canonical(aha)),
    }
    sophia["input_digests"]["aha_result.json"] = rebound
    next(parent for parent in sophia["parent_list"] if parent["path"] == "aha_result.json").update(rebound)
    sophia["disposition"] = "HOLD"
    sophia["reason_codes"] = ["AHA_UNAVAILABLE"]
    sophia["findings"] = [
        {
            "code": "AHA_UNAVAILABLE",
            "severity": "HOLD",
            "artifact": "aha_result.json",
            "detail": "structural AHA case was not supplied",
        }
    ]
    sophia["return_route"] = {
        "route": "CLARIFY",
        "destination": "COHERENCELATTICE",
        "status": "REQUESTED_NOT_EXECUTED",
        "reason_codes": ["AHA_UNAVAILABLE"],
        "candidate_mutation_performed": False,
        "source_mutation_performed": False,
        "automatic_rerun_performed": False,
        "authority_effect": "NONE",
    }
    sophia_path.write_bytes(canonical(sophia))

    packet = assign_totality_posture(root)
    review = (root / "final_review.html").read_text(encoding="utf-8")
    assert packet["sophia_disposition"] == "HOLD" and packet["retention_posture"] == "quarantine"
    assert "AHA mapping or explicit unavailable posture" in review
    assert "UNAVAILABLE" in review and "AHA_CASE_NOT_SUPPLIED" in review


def test_cli_writes_only_atlas_outputs(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    before = set(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    component = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(component / "python" / "src")}
    command = [sys.executable, "-m", "atlas.triadic.totality_posture", "--run-root", str(root)]
    completed = subprocess.run(command, cwd=component, env=environment, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    after = set(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    assert after - before == {"atlas_posture_packet.json", "final_review.html"}


def test_atlas_refuses_to_mutate_sealed_run(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "sealed-run")
    assign_totality_posture(root)
    before = (root / "atlas_posture_packet.json").read_bytes()
    for marker in (
        "run_manifest.json",
        "sealed_artifact_manifest.json",
        "checksums.sha256",
    ):
        (root / marker).write_bytes(b"sealed\n")
    with pytest.raises(TotalityPostureError, match="SEALED_RUN_IMMUTABLE"):
        assign_totality_posture(root)
    assert (root / "atlas_posture_packet.json").read_bytes() == before


def test_atlas_rejects_oversized_public_input_before_full_read(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "oversized-input")
    request_path = root / "request.json"
    with request_path.open("wb") as stream:
        stream.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(TotalityPostureError, match="INPUT_SIZE_LIMIT_EXCEEDED"):
        assign_totality_posture(root)
    assert not (root / "atlas_posture_packet.json").exists()


def _finalize_totality_fixture_for_ui(root: Path, atlas_mutator=None) -> str:
    def load(relative: str) -> dict:
        return json.loads(root.joinpath(*relative.split("/")).read_bytes())

    request = load("request.json")
    manifest = load("grounding/manifest.json")
    quarantine = load("sonya/quarantine_receipt.json")
    candidate = load("candidate_packet.json")
    claim_map = load("claim_evidence_map.json")
    ucm = load("ucm_state.json")
    projector = load("projector_receipt.json")
    aha = load("aha_result.json")
    counterexamples = load("counterexamples.json")
    waveform = load("reference_waveform.json")
    aperture = load("aperture_decision.json")
    pmr = load("pmr_receipt.json")
    sophia = load("sophia_audit_packet.json")
    audit_id = sophia["audit_id"]
    decision_id = "DECISION-" + digest((audit_id + request["run_id"]).encode())[:24]
    event_order = (
        "REQUEST_CANONICALIZED",
        "GROUNDING_VERIFIED",
        "RAW_OUTPUT_QUARANTINED",
        "CANDIDATE_CANONICALIZED",
        "CLAIM_EVIDENCE_MAPPED",
        "UCM_PROJECTED",
        "AHA_EVALUATED",
        "COUNTEREXAMPLES_SCANNED",
        "REFERENCE_WAVEFORM_ENCODED",
        "APERTURE_DECIDED",
        "PMR_BOUNDARY_RECORDED",
        "SOPHIA_AUDIT_REQUESTED",
        "ATLAS_ORIENTATION_PENDING",
        "HUMAN_DECISION_PENDING",
        "CORE_BUILD_COMPLETED",
    )
    payloads = {
        "REQUEST_CANONICALIZED": {"request_sha256": digest(canonical(request))},
        "GROUNDING_VERIFIED": {"grounding_manifest_sha256": digest(canonical(manifest))},
        "RAW_OUTPUT_QUARANTINED": {"raw_output_sha256": quarantine["raw_output_sha256"]},
        "CANDIDATE_CANONICALIZED": {"candidate_sha256": digest(canonical(candidate))},
        "CLAIM_EVIDENCE_MAPPED": {"claim_map_sha256": digest(canonical(claim_map))},
        "UCM_PROJECTED": {
            "ucm_state_sha256": digest(canonical(ucm)),
            "projector_receipt_sha256": digest(canonical(projector)),
        },
        "AHA_EVALUATED": {"aha_result_sha256": digest(canonical(aha))},
        "COUNTEREXAMPLES_SCANNED": {
            "counterexamples_sha256": digest(canonical(counterexamples)),
            "unresolved_count": counterexamples.get("unresolved_count"),
        },
        "REFERENCE_WAVEFORM_ENCODED": {
            "reference_waveform_sha256": digest(canonical(waveform)),
            "physical_frequency_claim": False,
        },
        "APERTURE_DECIDED": {
            "aperture_decision_sha256": digest(canonical(aperture)),
            "decision": aperture["decision"],
        },
        "PMR_BOUNDARY_RECORDED": {
            "pmr_receipt_sha256": digest(canonical(pmr)),
            "persistent_bytes_written": 0,
        },
        "SOPHIA_AUDIT_REQUESTED": {"status": "REQUESTED_NOT_EXECUTED"},
        "ATLAS_ORIENTATION_PENDING": {"status": "PENDING_SOPHIA"},
        "HUMAN_DECISION_PENDING": {"status": "PENDING", "external_receipt_required": True},
        "CORE_BUILD_COMPLETED": {"stop_boundary": "BEFORE_SOPHIA_AND_ATLAS"},
    }
    outcomes = dict.fromkeys(event_order, "SUCCESS")
    outcomes["UCM_PROJECTED"] = {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}[projector["disposition"]]
    outcomes["AHA_EVALUATED"] = "REFUSE" if aha.get("disposition") == "REJECTED" else ("HOLD" if aha["status"] == "UNAVAILABLE" else "SUCCESS")
    outcomes["APERTURE_DECIDED"] = {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}[aperture["decision"]]
    for name in event_order[10:]:
        outcomes[name] = "RECORDED"
    prefix_rows = [
        {
            "schema_id": "uvlm.coherence.totality.tel_event.v1",
            "sequence": index,
            "logical_time": f"T+{index:06d}",
            "event_type": event_type,
            "run_id": request["run_id"],
            "candidate_id": candidate["candidate_id"] if index >= 4 else None,
            "audit_id": audit_id if index >= 12 else None,
            "decision_id": decision_id if index >= 14 else None,
            "outcome": outcomes[event_type],
            "payload": payloads[event_type],
            "authority_effect": "NONE",
        }
        for index, event_type in enumerate(event_order, start=1)
    ]
    prefix_bytes = b"".join(canonical(row) for row in prefix_rows)
    put(root, "tel_audit_prefix.jsonl", prefix_bytes)
    prefix_binding = {
        "file_sha256": digest(prefix_bytes),
        "canonical_sha256": digest(prefix_bytes),
    }
    sophia["input_digests"]["tel_audit_prefix.jsonl"] = prefix_binding
    next(
        parent for parent in sophia["parent_list"]
        if parent["path"] == "tel_audit_prefix.jsonl"
    ).update(prefix_binding)
    put(root, "sophia_audit_packet.json", sophia)
    assign_totality_posture(root)
    atlas = load("atlas_posture_packet.json")
    if atlas_mutator is not None:
        atlas_mutator(atlas)
        put(root, "atlas_posture_packet.json", atlas)
    extension = (
        (
            "SOPHIA_AUDIT_COMPLETED",
            {"sophia_audit_packet_sha256": digest(canonical(sophia)), "disposition": sophia["disposition"]},
            {"PASS": "SUCCESS", "HOLD": "HOLD", "REJECT": "REFUSE"}[sophia["disposition"]],
        ),
        (
            "ATLAS_ORIENTATION_COMPLETED",
            {"atlas_posture_packet_sha256": digest(canonical(atlas)), "human_decision": "PENDING"},
            "RECORDED",
        ),
        (
            "ROUTE_COMPLETED_HUMAN_PENDING",
            {"tel_audit_prefix_sha256": digest(prefix_bytes), "external_human_decision_receipt_required": True, "human_decision": "PENDING"},
            "RECORDED",
        ),
    )
    full_rows = list(prefix_rows)
    for index, (event_type, payload, outcome) in enumerate(extension, start=16):
        full_rows.append(
            {
                "schema_id": "uvlm.coherence.totality.tel_event.v1",
                "sequence": index,
                "logical_time": f"T+{index:06d}",
                "event_type": event_type,
                "run_id": request["run_id"],
                "candidate_id": candidate["candidate_id"],
                "audit_id": audit_id,
                "decision_id": decision_id,
                "outcome": outcome,
                "payload": payload,
                "authority_effect": "NONE",
            }
        )
    tel_bytes = b"".join(canonical(row) for row in full_rows)
    put(root, "tel_events.jsonl", tel_bytes)
    put(
        root,
        "tel_finalization_receipt.json",
        {
            "schema_id": "uvlm.coherence.totality.tel_finalization_receipt.v1",
            "run_id": request["run_id"],
            "logical_time": request["logical_time"],
            "candidate_id": candidate["candidate_id"],
            "audit_id": audit_id,
            "decision_id": decision_id,
            "tel_audit_prefix_sha256": digest(prefix_bytes),
            "sophia_audit_packet_sha256": digest(canonical(sophia)),
            "atlas_posture_packet_sha256": digest(canonical(atlas)),
            "tel_events_sha256": digest(tel_bytes),
            "event_count": 18,
            "human_decision": "PENDING",
            "external_continuation_required": True,
            "effects": dict.fromkeys(
                ("network", "provider_invocation", "memory_write", "training", "publication", "deployment", "release"),
                False,
            ),
            "authority_effect": "NONE",
        },
    )
    seal_totality_fixture_for_ui(root)
    return decision_id


def test_totality_run_is_compatible_with_sealed_human_review_ui(tmp_path: Path) -> None:
    root = totality_run(tmp_path / "run")
    decision_id = _finalize_totality_fixture_for_ui(root)
    tel_bytes = (root / "tel_events.jsonl").read_bytes()

    app = create_app(root)

    async def loopback(scope, receive, send):
        scope = dict(scope)
        scope["client"] = ("127.0.0.1", 1)
        await app(scope, receive, send)

    client = TestClient(loopback, base_url="http://127.0.0.1")
    response = client.get("/review")
    assert response.status_code == 200
    assert "Assess &lt;img src=x onerror=alert(1)&gt; evidence." in response.text
    assert "Grounded &lt;source&gt; excerpt." in response.text
    assert "character span 0–26" in response.text and "byte span 0–26" in response.text
    assert response.text.count('type="radio"') == 4 and 'value="REPAIR"' in response.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    preview = client.post(
        "/review/preview",
        data={"csrf": csrf, "decision": "APPROVE", "reviewer": "Fixture reviewer", "note": ""},
    )
    assert preview.status_code == 200
    assert "AUDIT-111111111111111111111111" in preview.text and "CAND-test" in preview.text
    token = re.search(r'name="confirmation_token" value="([^"]+)"', preview.text).group(1)
    committed = client.post(
        "/review/commit",
        data={"csrf": csrf, "confirmation_token": token},
    )
    assert committed.status_code == 200
    decision_root = root.parent / "human_decisions" / decision_id
    decision = json.loads((decision_root / "human_review_decision.json").read_bytes())
    continuation = (decision_root / "tel_human_continuation.jsonl").read_bytes()
    for member_name in ("human_review_decision.json", "tel_human_continuation.jsonl"):
        member = decision_root / member_name
        sidecar = (decision_root / f"{member_name}.sha256").read_bytes()
        assert sidecar == f"{digest(member.read_bytes())}  {member_name}\n".encode("ascii")
        assert b"\r" not in sidecar
    assert decision["decision_id"] == decision_id
    assert continuation.startswith(tel_bytes)
    final_event = json.loads(continuation.splitlines()[-1])
    assert final_event["event_type"] == "HUMAN_DECISION_RECORDED"
    assert final_event["payload"]["decision_receipt_sha256"] == digest(
        (decision_root / "human_review_decision.json").read_bytes()
    )
    fresh_app = create_app(root)

    async def fresh_loopback(scope, receive, send):
        scope = dict(scope)
        scope["client"] = ("127.0.0.1", 1)
        await fresh_app(scope, receive, send)

    fresh = TestClient(fresh_loopback, base_url="http://127.0.0.1").get("/review")
    assert fresh.status_code == 409 and "Decision already recorded" in fresh.text
    sophia_path = root / "sophia_audit_packet.json"
    sophia = json.loads(sophia_path.read_bytes())
    sophia["reason_codes"] = ["TAMPERED_BUT_RELEDGERED"]
    sophia_path.write_bytes(canonical(sophia))
    checksum_path = root / "checksums.sha256"
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    checksum_path.write_text(
        "\n".join(
            f"{digest(sophia_path.read_bytes())}  sophia_audit_packet.json"
            if line.endswith("  sophia_audit_packet.json")
            else line
            for line in lines
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(HumanReviewError, match="manifest verification failed"):
        load_sealed_run(root)


def test_human_review_rejects_coherently_sealed_positive_atlas_authority(
    tmp_path: Path,
) -> None:
    root = totality_run(tmp_path / "positive-publication")

    def add_publication_authority(packet: dict) -> None:
        packet["nonauthority"]["publication"] = True

    _finalize_totality_fixture_for_ui(root, add_publication_authority)
    with pytest.raises(HumanReviewError, match="authority or posture"):
        load_sealed_run(root)


@pytest.mark.parametrize(
    ("surface", "field"),
    [("nonauthority", "canonization"), ("side_effects", "canonization_performed")],
)
def test_publisher_cannot_canonize(
    tmp_path: Path, surface: str, field: str
) -> None:
    root = totality_run(tmp_path / f"canonization-{surface}")
    candidate_before = (root / "candidate_packet.json").read_bytes()

    def add_canonization(packet: dict) -> None:
        packet[surface][field] = True

    _finalize_totality_fixture_for_ui(root, add_canonization)
    with pytest.raises(HumanReviewError, match="authority or posture"):
        load_sealed_run(root)
    assert (root / "candidate_packet.json").read_bytes() == candidate_before


def test_human_review_never_opens_raw_quarantine_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = totality_run(tmp_path / "opaque-raw")
    _finalize_totality_fixture_for_ui(root)
    protected = (root / "sonya" / "raw_output.quarantine").resolve()
    original_read_bytes = Path.read_bytes
    original_open = Path.open
    expected_digest = digest(original_read_bytes(protected))

    def guarded_read_bytes(path: Path) -> bytes:
        if path.resolve() == protected:
            raise AssertionError("Atlas UI attempted to read raw quarantine bytes")
        return original_read_bytes(path)

    def guarded_open(path: Path, *args, **kwargs):
        if path.resolve() == protected:
            raise AssertionError("Atlas UI attempted to open raw quarantine bytes")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "open", guarded_open)
    sealed = load_sealed_run(root)
    assert sealed["raw_quarantine_bytes_loaded"] is False
    assert sealed["hashes"]["sonya/raw_output.quarantine"] == expected_digest
