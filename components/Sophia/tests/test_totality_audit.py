from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from sophia.triadic.totality_audit import (
    DEFAULT_IGNORABLE_CODE_POINT_PROFILE,
    DEFAULT_IGNORABLE_CODE_POINT_RANGES,
    INPUT_PATHS,
    InputContractError,
    MAX_RAW_OUTPUT_BYTES,
    _canonical_json_bytes,
    _canonical_sha256,
    _citation_evidence,
    _citation_support_status,
    _expected_aperture,
    _expected_counterexamples,
    _expected_projection_disposition,
    _project,
    _sha256,
    _is_default_ignorable_code_point,
    _mark_citation_overlaps,
    _tokens,
    _validate_aha_case_shape,
    _validate_claim_map,
    _validate_unicode,
    audit_totality_run,
)


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = COMPONENT_ROOT / "schema" / "bridge" / "totality_audit_packet.v1.schema.json"
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


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(value))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(_canonical_json_bytes(row) for row in rows))


def _segment_rows(source: str) -> list[dict]:
    paragraphs = [item.strip() for item in source.rstrip("\n").split("\n\n") if item.strip()]
    rows = []
    cursor = 0
    body = source.rstrip("\n")
    for index, text in enumerate(paragraphs, start=1):
        start = body.find(text, cursor)
        end = start + len(text)
        cursor = end
        rows.append(
            {
                "schema_id": "uvlm.coherence.totality.grounding_segment.v1",
                "segment_id": f"SEG-{index:04d}",
                "index": index,
                "text": text,
                "char_start": start,
                "char_end": end,
                "byte_start": len(body[:start].encode()),
                "byte_end": len(body[:end].encode()),
                "sha256": _sha256(text.encode()),
            }
        )
    return rows


def _aha_case(segments: list[dict]) -> dict:
    refs = [{"segment_id": row["segment_id"], "sha256": row["sha256"]} for row in segments]

    def graph(graph_id: str, family: str, prefix: str) -> dict:
        return {
            "graph_id": graph_id,
            "domain": f"domain-{graph_id}",
            "source_family_id": family,
            "nodes": [
                {"node_id": f"{prefix}1", "node_type": "state", "label": "input", "lineage": [segments[0]["segment_id"]]},
                {"node_id": f"{prefix}2", "node_type": "state", "label": "output", "lineage": [segments[0]["segment_id"]]},
            ],
            "relations": [
                {
                    "relation_id": f"{prefix}r",
                    "relation_type": "causes",
                    "source_node_id": f"{prefix}1",
                    "target_node_id": f"{prefix}2",
                    "orientation": "forward",
                    "lineage": [segments[0]["segment_id"]],
                }
            ],
        }

    return {
        "schema_id": "uvlm.coherence.aha.case.v1",
        "case_id": "aha-case-001",
        "question": "Does the structural relation transfer?",
        "grounding_segments": refs,
        "target": graph("target", "target-family", "t"),
        "donors": [graph("donor-a", "family-a", "a"), graph("donor-b", "family-b", "b")],
        "mappings": [
            {
                "mapping_id": "map-a",
                "donor_graph_id": "donor-a",
                "node_map": {"a1": "t1", "a2": "t2"},
                "relation_map": {"ar": "tr"},
                "invariant_map": {"direction": "preserved"},
                "disanalogies": ["different domain"],
                "declared_scale_or_unit_transformations": {"posture": "none"},
            },
            {
                "mapping_id": "map-b",
                "donor_graph_id": "donor-b",
                "node_map": {"b1": "t1", "b2": "t2"},
                "relation_map": {"br": "tr"},
                "invariant_map": {"direction": "preserved"},
                "disanalogies": ["different scale"],
                "declared_scale_or_unit_transformations": {"posture": "declared"},
            },
        ],
        "candidate_hypothesis": {
            "statement": "The relation may transfer under the stated comparator.",
            "target_observable": "relation direction",
            "intervention_or_condition": "bounded source review",
            "expected_direction": "forward",
            "comparator_or_null": "no structural transfer",
            "horizon": "single review",
            "confidence_lowering_observation": "relation reversal",
        },
        "falsification_test": {
            "test_statement": "Compare relation orientation.",
            "primary_outcome": "orientation match",
            "comparator": "no match",
            "reject_criteria": "orientation differs",
            "feasibility_posture": "LOCAL_REVIEWABLE",
            "risk_posture": "LOW",
        },
    }


def _build_fixture(
    root: Path,
    *,
    mode: str = "supported",
    aha_available: bool = True,
    hypotheses: list[dict] | None = None,
    top_k: int = 8,
    privacy_policy_satisfied: bool = True,
    retention_requested: bool = False,
    pmr_consent_decision: str | None = None,
    pmr_expires_logical_time: str | None = None,
    logical_time: str = "2026-08-22T00:00:00Z",
) -> Path:
    root.mkdir(parents=True)
    source = "Ada Lovelace published notes in 1843.\n"
    answer = "Ada Lovelace published notes in 1843."
    if mode == "unsupported":
        answer = "Grace Hopper created COBOL."
    elif mode == "conflicting":
        source = "Ada Lovelace published notes in 1843.\n\nHowever, other notes were not published in 1843.\n"
    elif mode == "refuted":
        source = "Ada Lovelace published notes in 1843. That claim is false.\n"
    source_raw = source.encode()
    normalized_raw = source.encode()
    segments = _segment_rows(source)
    segments_raw = b"".join(_canonical_json_bytes(row) for row in segments)
    manifest = {
        "schema_id": "uvlm.coherence.totality.grounding_bundle.v1",
        "bundle_id": "GB-fixture-001",
        "source_sha256": _sha256(source_raw),
        "normalized_sha256": _sha256(normalized_raw),
        "source_bytes": len(source_raw),
        "normalized_bytes": len(normalized_raw),
        "segments_sha256": _sha256(segments_raw),
        "segment_count": len(segments),
        "segmentation": "PARAGRAPH_THEN_NONEMPTY_LINE_EXACT_SPAN_UTF8_NFC_V1",
        "authority_effect": "NONE",
        "network_used": False,
    }
    request = {
        "schema_id": "uvlm.coherence.totality.request_envelope.v1",
        "request_id": "REQ-fixture-001",
        "run_id": "RUN-fixture-001",
        "logical_time": logical_time,
        "kind": "grounded_text",
        "user_input": "Summarize the authenticated source.",
        "grounding": [
            {
                "source_kind": "grounding_bundle",
                "source_id": f"SRC-{manifest['source_sha256'][:20]}",
                "media_type": "text/markdown",
                "bundle_manifest_path": "grounding/manifest.json",
                "bundle_manifest_sha256": _canonical_sha256(manifest),
                "source_sha256": manifest["source_sha256"],
                "normalized_sha256": manifest["normalized_sha256"],
            }
        ],
        "task_consent": True,
        "retention_requested": retention_requested,
        "model": None,
        "divergence_mode": None,
        "meta": {
            "privacy_policy_satisfied": privacy_policy_satisfied,
            "privacy_basis": "Fixture privacy review is recorded for the bounded local run.",
        },
    }
    request_sha = _canonical_sha256(request)
    raw_output_sha = _sha256(_canonical_json_bytes({"captured": answer}))
    candidate_id = "CAND-" + _sha256((request_sha + raw_output_sha).encode("ascii"))[:24]
    relation_by_mode = {
        "supported": "SUPPORTS",
        "conflicting": "SUPPORTS",
        "refuted": "CONTRADICTS",
    }
    references = []
    if mode in relation_by_mode:
        selected_segments = [segments[0]]
        relations = [relation_by_mode[mode]]
        if mode == "conflicting":
            selected_segments.append(segments[1])
            relations.append("LIMITS")
        for segment, relation in zip(selected_segments, relations, strict=True):
            references.append(
                {
                    "source_sha256": manifest["source_sha256"],
                    "segment_id": segment["segment_id"],
                    "segment_sha256": segment["sha256"],
                    "source_span": {
                        name: segment[name]
                        for name in ("char_start", "char_end", "byte_start", "byte_end")
                    },
                    "exact_excerpt_sha256": segment["sha256"],
                    "claim_text_sha256": _sha256(answer.encode("utf-8")),
                    "candidate_relation": relation,
                }
            )
    candidate = {
        "schema_id": "uvlm.sonya.totality.candidate_packet.v1",
        "candidate_id": candidate_id,
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "request_sha256": request_sha,
        "adapter_id": "sonya.captured.fixture.v1",
        "model_identity": "captured-no-provider",
        "raw_output_sha256": raw_output_sha,
        "answer": answer,
        "uncertainty": 0.10,
        "claims": [
            {
                "claim_id": "claim-001",
                "text": answer,
                "answer_start": 0,
                "answer_end": len(answer),
                "candidate_evidence_references": references,
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
        "schema_id": "uvlm.sonya.totality.raw_quarantine_receipt.v1",
        "adapter_id": candidate["adapter_id"],
        "request_sha256": request_sha,
        "raw_output_sha256": raw_output_sha,
        "raw_output_bytes": len(_canonical_json_bytes({"captured": answer})),
        "quarantine_member": "raw_output.quarantine",
        "raw_output_quarantined": True,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    quarantine_verification_receipt = {
        "schema_id": "uvlm.sonya.totality.quarantine_verification_receipt.v1",
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "request_sha256": request_sha,
        "adapter_id": candidate["adapter_id"],
        "quarantine_member": quarantine_receipt["quarantine_member"],
        "raw_output_sha256": raw_output_sha,
        "raw_output_bytes": quarantine_receipt["raw_output_bytes"],
        "quarantine_receipt_sha256": _canonical_sha256(quarantine_receipt),
        "candidate_id": candidate_id,
        "candidate_sha256": _canonical_sha256(candidate),
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
    pmr_consent = None
    if pmr_consent_decision is not None:
        pmr_consent = {
            "schema_id": "uvlm.pmr.totality.consent.v1",
            "consent_id": "CONSENT-fixture-001",
            "run_id": request["run_id"],
            "candidate_id": candidate_id,
            "logical_time": request["logical_time"],
            "decision": pmr_consent_decision,
            "scope": "PROVENANCE_REFERENCE_ONLY",
            "quota_bytes": 1_048_576,
            "expires_logical_time": pmr_expires_logical_time,
            "training_allowed": False,
            "federation_allowed": False,
            "authority_effect": "NONE",
        }
        granted = pmr_consent_decision == "GRANT"
        pmr_receipt = {
            "schema_id": "uvlm.pmr.totality.receipt.v1",
            "run_id": request["run_id"],
            "candidate_id": candidate_id,
            "logical_time": request["logical_time"],
            "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
            "consent_id": pmr_consent["consent_id"],
            "consent_status": "ACTIVE" if granted else "INACTIVE",
            "reason_codes": ["REFERENCE_EVENTS_ONLY_NO_CONTENT_WRITE"],
            "events": [
                {
                    "schema_id": "uvlm.pmr.totality.reference_event.v1",
                    "sequence": 1,
                    "logical_time": "PMR+000001",
                    "event_type": "CONSENT_GRANTED" if granted else "CONSENT_DENIED",
                    "consent_id": pmr_consent["consent_id"],
                    "run_id": request["run_id"],
                    "candidate_id": candidate_id,
                    "lineage_id": None,
                    "detail": {
                        "scope": "PROVENANCE_REFERENCE_ONLY",
                        "quota_bytes": pmr_consent["quota_bytes"],
                    },
                    "persistent_write_performed": False,
                    "training_used": False,
                    "federation_used": False,
                    "authority_effect": "NONE",
                }
            ],
            "retained": False,
            "persistent_bytes_written": 0,
            "network_used": False,
            "federation_used": False,
            "training_used": False,
            "authority_effect": "NONE",
        }
    else:
        pmr_receipt = {
            "schema_id": "uvlm.pmr.totality.receipt.v1",
            "run_id": request["run_id"],
            "candidate_id": candidate_id,
            "logical_time": request["logical_time"],
            "mode": "NO_WRITE_REFERENCE_IMPLEMENTATION",
            "consent_id": None,
            "consent_status": "NOT_GRANTED",
            "reason_codes": ["PMR_SEPARATE_CONSENT_NOT_GRANTED"],
            "events": [],
            "retained": False,
            "persistent_bytes_written": 0,
            "network_used": False,
            "federation_used": False,
            "training_used": False,
            "authority_effect": "NONE",
        }
    claim_tokens = set(_tokens(answer))
    segments_by_id = {row["segment_id"]: row for row in segments}
    evidence = [
        _citation_evidence(
            reference,
            claim_text=answer,
            manifest=manifest,
            normalized_source=source,
            segments_by_id=segments_by_id,
        )
        for reference in references
    ]
    _mark_citation_overlaps(evidence)
    covered: set[str] = set()
    for row in evidence:
        if row["citation_integrity"] == "VERIFIED":
            covered.update(row["overlap_tokens"])
    support = _citation_support_status(evidence)
    unsupported = (
        []
        if support
        in {
            "CITATION_VERIFIED_REVIEW_REQUIRED",
            "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED",
        }
        else ["claim-001"]
    )
    claim_map = {
        "schema_id": "uvlm.coherence.totality.claim_evidence_map.v1",
        "run_id": request["run_id"],
        "candidate_id": candidate_id,
        "candidate_sha256": _canonical_sha256(candidate),
        "grounding_manifest_sha256": _canonical_sha256(manifest),
        "source_sha256": manifest["source_sha256"],
        "mapping_method": "CANDIDATE_DECLARED_EXACT_CITATION_INTEGRITY_V1",
        "claims": [
            {
                "claim_id": "claim-001",
                "text": answer,
                "answer_span": {"char_start": 0, "char_end": len(answer)},
                "evidence": evidence,
                "support_status": support,
                "residual_tokens": sorted(claim_tokens - covered),
            }
        ],
        "unsupported_claim_ids": unsupported,
        "authority_effect": "NONE",
    }
    rows = hypotheses or [
        {"hypothesis_id": candidate_id, "score": 0.9, "equivalence_group": candidate_id, "pattern_posture": "IN_DISTRIBUTION"}
    ]
    rows = sorted(rows, key=lambda row: row["hypothesis_id"])
    ucm = {
        "schema_id": "uvlm.coherence.totality.ucm_state.v1",
        "run_id": request["run_id"],
        "candidate_id": candidate_id,
        "expected_context": {
            "request_sha256": request_sha,
            "candidate_sha256": _canonical_sha256(candidate),
            "grounding_manifest_sha256": _canonical_sha256(manifest),
            "source_sha256": manifest["source_sha256"],
            "claim_map_sha256": _canonical_sha256(claim_map),
        },
        "axes": {"E_cpl": 0.9, "T_tr": 0.9, "E_s": 0.9, "phase_stability_lambda": 0.8, "mutual_containment_mu": 0.8},
        "uncertainty": candidate["uncertainty"],
        "source_ref_count": 1,
        "unsupported_claim_ids": unsupported,
        "hypotheses": rows,
        "authority_effect": "NONE",
    }
    candidate_posterior, groups, margin = _project(rows)
    disposition, reasons = _expected_projection_disposition(ucm, margin)
    safe_top_k = max(1, min(top_k, len(rows)))
    presentation_rows = sorted(candidate_posterior, key=lambda row: (-row["probability"], row["hypothesis_id"]))[:safe_top_k]
    retained = sum(row["probability"] for row in presentation_rows)
    projector = {
        "schema_id": "uvlm.coherence.totality.projector_receipt.v1",
        "run_id": request["run_id"],
        "candidate_id": candidate_id,
        "ucm_state_sha256": _canonical_sha256(ucm),
        "expected_context": ucm["expected_context"],
        "psi_cl": 0.81,
        "full_candidate_posterior": candidate_posterior,
        "full_equivalence_posterior": groups,
        "full_posterior_margin": margin,
        "disposition": disposition,
        "reasons": reasons,
        "presentation": {
            "top_k": safe_top_k,
            "candidates": presentation_rows,
            "retained_mass": retained,
            "omitted_mass": max(0.0, 1.0 - retained),
            "disposition_invariant_to_top_k": True,
        },
        "authority_effect": "NONE",
        "human_review_required": True,
    }
    ambiguity = margin < 0.10 or any(row["pattern_posture"] == "AMBIGUOUS" for row in rows)
    projector_invariant = {
        name: projector[name]
        for name in (
            "ucm_state_sha256", "expected_context", "psi_cl", "full_candidate_posterior",
            "full_equivalence_posterior", "full_posterior_margin", "disposition", "reasons",
        )
    }
    residual = {
        "schema_id": "uvlm.coherence.totality.residual_refusal.v1",
        "run_id": request["run_id"],
        "candidate_id": candidate_id,
        "projector_invariant_sha256": _canonical_sha256(projector_invariant),
        "residual": {
            "omitted_probability_mass": 0.0,
            "unsupported_claim_ids": unsupported,
            "ambiguity": ambiguity,
            "ood_hypothesis_ids": sorted(row["hypothesis_id"] for row in rows if row["pattern_posture"] == "OOD"),
            "new_pattern_hypothesis_ids": sorted(row["hypothesis_id"] for row in rows if row["pattern_posture"] == "NEW_PATTERN"),
        },
        "refusal": {"triggered": disposition == "REFUSE", "reason_codes": reasons if disposition == "REFUSE" else []},
        "disposition": disposition,
        "reasons": reasons,
        "authority_effect": "NONE",
    }
    if aha_available:
        case = _aha_case(segments)
        evaluation = _validate_aha_case_shape(case, segments_by_id)
        aha = {
            "schema_id": "uvlm.coherence.totality.aha_result.v1",
            "run_id": request["run_id"],
            "candidate_id": candidate_id,
            "candidate_sha256": _canonical_sha256(candidate),
            "source_sha256": manifest["source_sha256"],
            "status": "AVAILABLE",
            "disposition": evaluation["disposition"],
            "reason_codes": evaluation["fail_reasons"] or ["AHA_STRUCTURAL_CASE_REVIEWABLE"],
            "case_sha256": _canonical_sha256(case),
            "case": case,
            "evaluation": evaluation,
            "authority_effect": "NONE",
        }
    else:
        aha = {
            "schema_id": "uvlm.coherence.totality.aha_result.v1",
            "run_id": request["run_id"],
            "candidate_id": candidate_id,
            "candidate_sha256": _canonical_sha256(candidate),
            "source_sha256": manifest["source_sha256"],
            "status": "UNAVAILABLE",
            "disposition": "UNAVAILABLE",
            "reason_codes": ["AHA_CASE_NOT_SUPPLIED"],
            "case_sha256": None,
            "case": None,
            "evaluation": None,
            "authority_effect": "NONE",
        }
    counterexamples = _expected_counterexamples(candidate, manifest, segments_by_id, claim_map)
    axis_order = (
        "E_cpl",
        "T_tr",
        "E_s",
        "phase_stability_lambda",
        "mutual_containment_mu",
    )
    sample_count = 64
    axis_values = [float(ucm["axes"][name]) for name in axis_order]
    waveform_samples = [
        round(
            math.fsum(
                amplitude
                * math.sin(2.0 * math.pi * harmonic * (index / sample_count))
                for harmonic, amplitude in enumerate(axis_values, start=1)
            )
            / len(axis_values),
            12,
        )
        for index in range(sample_count)
    ]
    waveform = {
        "schema_id": "uvlm.coherence.totality.reference_waveform.v1",
        "codec": "AXIOMATIC_SYNTHETIC_FIVE_AXIS_SINE_CODEC_V1",
        "sample_count": sample_count,
        "axis_order": list(axis_order),
        "samples": waveform_samples,
        "mean_square_energy": round(
            math.fsum(value * value for value in waveform_samples)
            / len(waveform_samples),
            12,
        ),
        "synthetic_reference_only": True,
        "physical_frequency_claim": False,
        "cross_domain_utility_established": False,
        "claim_ceiling": "REFERENCE CODEC ONLY; NOT A PHYSICAL FREQUENCY OF A PERSON, ARCHETYPE, OR SYSTEM",
        "authority_effect": "NONE",
    }
    aperture = _expected_aperture(
        request,
        candidate,
        projector,
        residual,
        aha,
        counterexamples,
        task_consent=True,
        privacy_policy_satisfied=privacy_policy_satisfied,
        retention_gate_satisfied=(
            not retention_requested or pmr_consent_decision == "GRANT"
        ),
        grounding_valid=True,
        context_binding_valid=True,
        quarantine_valid=True,
        claim_evidence_valid=not unsupported,
        ucm_not_refuse=(
            projector["disposition"] != "REFUSE"
            and residual["refusal"]["triggered"] is False
        ),
        aha_not_rejected=aha["disposition"] != "REJECTED",
    )
    event_types = [
        "REQUEST_CANONICALIZED", "GROUNDING_VERIFIED", "RAW_OUTPUT_QUARANTINED",
        "CANDIDATE_CANONICALIZED", "CLAIM_EVIDENCE_MAPPED", "UCM_PROJECTED", "AHA_EVALUATED",
        "COUNTEREXAMPLES_SCANNED", "REFERENCE_WAVEFORM_ENCODED", "APERTURE_DECIDED",
        "PMR_BOUNDARY_RECORDED", "SOPHIA_AUDIT_REQUESTED", "ATLAS_ORIENTATION_PENDING",
        "HUMAN_DECISION_PENDING",
        "CORE_BUILD_COMPLETED",
    ]
    tel = []
    audit_id = "AUDIT-" + _sha256((_canonical_sha256(candidate) + _canonical_sha256(aperture)).encode("ascii"))[:24]
    decision_id = "DECISION-" + _sha256((audit_id + request["run_id"]).encode("ascii"))[:24]
    event_payloads = {
        "REQUEST_CANONICALIZED": {"request_sha256": _canonical_sha256(request)},
        "GROUNDING_VERIFIED": {"grounding_manifest_sha256": _canonical_sha256(manifest)},
        "RAW_OUTPUT_QUARANTINED": {"raw_output_sha256": quarantine_receipt["raw_output_sha256"]},
        "CANDIDATE_CANONICALIZED": {"candidate_sha256": _canonical_sha256(candidate)},
        "CLAIM_EVIDENCE_MAPPED": {"claim_map_sha256": _canonical_sha256(claim_map)},
        "UCM_PROJECTED": {
            "ucm_state_sha256": _canonical_sha256(ucm),
            "projector_receipt_sha256": _canonical_sha256(projector),
        },
        "AHA_EVALUATED": {"aha_result_sha256": _canonical_sha256(aha)},
        "COUNTEREXAMPLES_SCANNED": {
            "counterexamples_sha256": _canonical_sha256(counterexamples),
            "unresolved_count": counterexamples["unresolved_count"],
        },
        "REFERENCE_WAVEFORM_ENCODED": {
            "reference_waveform_sha256": _canonical_sha256(waveform),
            "physical_frequency_claim": False,
        },
        "APERTURE_DECIDED": {
            "aperture_decision_sha256": _canonical_sha256(aperture),
            "decision": aperture["decision"],
        },
        "PMR_BOUNDARY_RECORDED": {
            "pmr_receipt_sha256": _canonical_sha256(pmr_receipt),
            "persistent_bytes_written": 0,
        },
        "SOPHIA_AUDIT_REQUESTED": {"status": "REQUESTED_NOT_EXECUTED"},
        "ATLAS_ORIENTATION_PENDING": {"status": "PENDING_SOPHIA"},
        "HUMAN_DECISION_PENDING": {
            "status": "PENDING",
            "external_receipt_required": True,
        },
        "CORE_BUILD_COMPLETED": {"stop_boundary": "BEFORE_SOPHIA_AND_ATLAS"},
    }
    for index, event_type in enumerate(event_types, start=1):
        outcome = "SUCCESS"
        if event_type == "UCM_PROJECTED":
            outcome = {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}[projector["disposition"]]
        elif event_type == "AHA_EVALUATED":
            outcome = "HOLD" if aha["status"] == "UNAVAILABLE" else "SUCCESS"
        elif event_type == "APERTURE_DECIDED":
            outcome = {"PASS_SCREEN": "SUCCESS", "HOLD": "HOLD", "REFUSE": "REFUSE"}[aperture["decision"]]
        elif event_type in {
            "PMR_BOUNDARY_RECORDED",
            "SOPHIA_AUDIT_REQUESTED",
            "ATLAS_ORIENTATION_PENDING",
            "HUMAN_DECISION_PENDING",
            "CORE_BUILD_COMPLETED",
        }:
            outcome = "RECORDED"
        tel.append(
            {
                "schema_id": "uvlm.coherence.totality.tel_event.v1",
                "sequence": index,
                "logical_time": f"T+{index:06d}",
                "event_type": event_type,
                "run_id": request["run_id"],
                "candidate_id": candidate_id if index >= 4 else None,
                "audit_id": audit_id if index >= 12 else None,
                "decision_id": decision_id if index >= 14 else None,
                "outcome": outcome,
                "payload": event_payloads[event_type],
                "authority_effect": "NONE",
            }
        )
    _write_json(root / "request.json", request)
    (root / "grounding").mkdir()
    _write_json(root / "grounding" / "manifest.json", manifest)
    (root / "grounding" / "source.bin").write_bytes(source_raw)
    (root / "grounding" / "normalized_source.txt").write_bytes(normalized_raw)
    _write_jsonl(root / "grounding" / "segments.jsonl", segments)
    _write_json(root / "sonya" / "quarantine_receipt.json", quarantine_receipt)
    _write_json(
        root / "sonya" / "quarantine_verification_receipt.json",
        quarantine_verification_receipt,
    )
    if pmr_consent is not None:
        _write_json(root / "pmr_consent.json", pmr_consent)
    _write_json(root / "pmr_receipt.json", pmr_receipt)
    for name, value in (
        ("candidate_packet.json", candidate),
        ("claim_evidence_map.json", claim_map),
        ("ucm_state.json", ucm),
        ("projector_receipt.json", projector),
        ("residual_refusal.json", residual),
        ("aha_result.json", aha),
        ("counterexamples.json", counterexamples),
        ("reference_waveform.json", waveform),
        ("aperture_decision.json", aperture),
    ):
        _write_json(root / name, value)
    _write_jsonl(root / "tel_audit_prefix.jsonl", tel)
    return root


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, value: dict) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _upstream_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        relative: (root / relative).read_bytes() if (root / relative).is_file() else None
        for relative in INPUT_PATHS
    }


def test_sophia_frozen_default_ignorable_profile_is_exact() -> None:
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
            with pytest.raises(InputContractError, match="DEFAULT_IGNORABLE"):
                _validate_unicode(f"left{chr(codepoint)}right", "$.probe")
        assert _is_default_ignorable_code_point(start - 1) is False
        assert _is_default_ignorable_code_point(end + 1) is False
    _validate_unicode("left\u0600right", "$.non_dicp_format")


def test_sophia_actual_request_boundary_rejects_nonformat_default_ignorable(
    tmp_path: Path,
) -> None:
    root = _build_fixture(tmp_path / "dicp-run")
    request_path = root / "request.json"
    request = _load(request_path)
    request["meta"]["dicp_probe"] = "hidden\ufe00metadata"
    request_path.write_bytes(
        (
            json.dumps(
                request,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    )
    before = _upstream_snapshot(root)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert any(
        row["code"] == "JSON_CONTRACT_OR_CANONICALIZATION_INVALID"
        and row["artifact"] == "request.json"
        for row in packet["findings"]
    )
    assert before == _upstream_snapshot(root)


def _validate_output(packet: dict) -> None:
    jsonschema.Draft202012Validator(_load(SCHEMA)).validate(packet)


def test_bounded_citation_hold_schema_determinism_cli_and_no_rewrite(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "run")
    before = _upstream_snapshot(root)
    first = audit_totality_run(root)
    first_bytes = (root / "sophia_audit_packet.json").read_bytes()
    second = audit_totality_run(root)
    assert first == second
    assert first_bytes == (root / "sophia_audit_packet.json").read_bytes()
    assert first["disposition"] == "HOLD"
    assert first["return_route"] == {
        "route": "CLARIFY",
        "destination": "COHERENCELATTICE",
        "status": "REQUESTED_NOT_EXECUTED",
        "reason_codes": first["reason_codes"],
        "candidate_mutation_performed": False,
        "source_mutation_performed": False,
        "automatic_rerun_performed": False,
        "authority_effect": "NONE",
    }
    assert "NO_VALID_SOURCE_CITATION" not in first["reason_codes"]
    assert first["claim_findings"] == [
        {
            "claim_id": "claim-001",
            "stored_support_status": "INSUFFICIENT_EVIDENCE",
            "evidence_count": 1,
            "recomputed_supported": False,
            "residual_tokens": [],
        }
    ]
    claim_map = _load(root / "claim_evidence_map.json")
    assert claim_map["claims"][0]["support_status"] == (
        "CITATION_VERIFIED_REVIEW_REQUIRED"
    )
    assert "RAW_QUARANTINE_BYTES_NOT_INDEPENDENTLY_VERIFIED" in first["reason_codes"]
    assert (
        first["recomputed_checks"][
            "coherence_reperformed_exact_byte_proof_recorded"
        ]
        is True
    )
    assert first["recomputed_checks"]["raw_quarantine_bytes_independently_verified"] is False
    assert before == _upstream_snapshot(root)
    _validate_output(first)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "python/src"
    result = subprocess.run(
        [sys.executable, "-m", "sophia.triadic.totality_audit", "--run-root", str(root)],
        cwd=COMPONENT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert before == _upstream_snapshot(root)


@pytest.mark.parametrize(
    ("name", "mutate", "reason"),
    [
        (
            "source-substitution",
            lambda root: (root / "grounding" / "source.bin").write_bytes(b"substituted\n"),
            "GROUNDING_IDENTITY_MISMATCH",
        ),
        (
            "evidence-span",
            lambda root: _mutate_nested(root, "claim_evidence_map.json", ["claims", 0, "evidence", 0, "exact_excerpt"], "substituted"),
            "CLAIM_MAP_RECOMPUTATION_MISMATCH",
        ),
        (
            "citation-copy",
            lambda root: _mutate_nested(
                root,
                "candidate_packet.json",
                ["claims", 0, "candidate_evidence_references", 0, "claim_text_sha256"],
                "0" * 64,
            ),
            "CANDIDATE_EVIDENCE_REFERENCE_INVALID",
        ),
        (
            "ucm-context",
            lambda root: _mutate_nested(root, "ucm_state.json", ["expected_context", "source_sha256"], "0" * 64),
            "UCM_CONTEXT_OR_STATE_MISMATCH",
        ),
        (
            "equivalence-posterior",
            lambda root: _mutate_nested(root, "projector_receipt.json", ["full_equivalence_posterior", 0, "probability"], 0.5),
            "PROJECTOR_RELATIONSHIP_MISMATCH",
        ),
        (
            "aha-evaluation",
            lambda root: _mutate_nested(root, "aha_result.json", ["evaluation", "disposition"], "REJECTED"),
            "AHA_RESULT_RECOMPUTATION_MISMATCH",
        ),
        (
            "aperture-bypass",
            lambda root: _mutate_nested(root, "aperture_decision.json", ["hard_gates", "privacy_policy_satisfied"], False),
            "APERTURE_BYPASS_OR_BINDING_MISMATCH",
        ),
    ],
)
def test_tamper_and_substitution_reject(tmp_path: Path, name: str, mutate, reason: str) -> None:
    root = _build_fixture(tmp_path / name)
    mutate(root)
    before = _upstream_snapshot(root)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert packet["return_route"]["route"] == "REPAIR"
    assert packet["return_route"]["destination"] == "SONYA_OR_COHERENCELATTICE"
    assert packet["return_route"]["status"] == "REQUESTED_NOT_EXECUTED"
    assert reason in packet["reason_codes"]
    assert before == _upstream_snapshot(root)
    _validate_output(packet)


def _mutate_nested(root: Path, filename: str, keys: list, replacement) -> None:
    path = root / filename
    value = _load(path)
    cursor = value
    for key in keys[:-1]:
        cursor = cursor[key]
    cursor[keys[-1]] = replacement
    _save(path, value)


def test_sophia_independently_recomputes_invalid_source_citation_posture(
    tmp_path: Path,
) -> None:
    root = _build_fixture(tmp_path / "citation-recompute")
    candidate = _load(root / "candidate_packet.json")
    candidate["claims"][0]["candidate_evidence_references"][0][
        "source_sha256"
    ] = "0" * 64
    manifest = _load(root / "grounding" / "manifest.json")
    normalized_source = (root / "grounding" / "normalized_source.txt").read_text(
        encoding="utf-8"
    )
    segments = [
        json.loads(line)
        for line in (root / "grounding" / "segments.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    findings = []
    result = _validate_claim_map(
        candidate,
        manifest,
        normalized_source,
        {row["segment_id"]: row for row in segments},
        _load(root / "claim_evidence_map.json"),
        findings,
    )
    assert result["unsupported_claim_ids"] == ["claim-001"]
    codes = {finding.code for finding in findings}
    assert "CITATION_INTEGRITY_INSUFFICIENT" in codes
    assert "CLAIM_MAP_RECOMPUTATION_MISMATCH" in codes


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("unsupported", "NO_VALID_SOURCE_CITATION"),
        ("conflicting", "SOURCE_LIMITATION_REVIEW_REQUIRED"),
        ("refuted", "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED"),
    ],
)
def test_unsupported_limitation_and_contradiction_evidence_hold(
    tmp_path: Path, mode: str, reason: str,
) -> None:
    packet = audit_totality_run(_build_fixture(tmp_path / mode, mode=mode))
    assert packet["disposition"] == "HOLD"
    assert reason in packet["reason_codes"]
    assert "BOUNDED_AUDIT_CRITERIA_MET" not in packet["reason_codes"]
    _validate_output(packet)


def test_equivalence_and_top_k_are_presentation_only(tmp_path: Path) -> None:
    hypotheses = [
        {"hypothesis_id": "hyp-a", "score": 5.0, "equivalence_group": "group-a", "pattern_posture": "IN_DISTRIBUTION"},
        {"hypothesis_id": "hyp-b", "score": 0.0, "equivalence_group": "group-b", "pattern_posture": "IN_DISTRIBUTION"},
    ]
    one_root = _build_fixture(tmp_path / "top-one", hypotheses=hypotheses, top_k=1)
    two_root = _build_fixture(tmp_path / "top-two", hypotheses=hypotheses, top_k=2)
    one = audit_totality_run(one_root)
    two = audit_totality_run(two_root)
    assert one["disposition"] == two["disposition"] == "HOLD"
    assert (one_root / "residual_refusal.json").read_bytes() == (two_root / "residual_refusal.json").read_bytes()
    assert one["recomputed_checks"]["top_k_disposition_invariant"] is True
    assert two["recomputed_checks"]["top_k_disposition_invariant"] is True


def test_aha_unavailable_holds_and_invalid_rejects(tmp_path: Path) -> None:
    unavailable = audit_totality_run(_build_fixture(tmp_path / "unavailable", aha_available=False))
    assert unavailable["disposition"] == "HOLD"
    assert "AHA_UNAVAILABLE" in unavailable["reason_codes"]
    invalid_root = _build_fixture(tmp_path / "invalid")
    _mutate_nested(invalid_root, "aha_result.json", ["case", "mappings", 0, "disanalogies"], [])
    invalid = audit_totality_run(invalid_root)
    assert invalid["disposition"] == "REJECT"
    assert "AHA_RESULT_RECOMPUTATION_MISMATCH" in invalid["reason_codes"]


def test_malformed_input_still_emits_schema_valid_reject(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "malformed")
    (root / "ucm_state.json").write_bytes(b'{"x":1,"x":2}\n')
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "JSON_CONTRACT_OR_CANONICALIZATION_INVALID" in packet["reason_codes"]
    assert packet["recomputed_checks"]["ucm_expected_context_binding"] is False
    assert packet["recomputed_checks"]["full_posterior_and_equivalence_recomputation"] is False
    _validate_output(packet)


def test_privacy_gate_is_recomputed_and_forged_stored_true_rejects(tmp_path: Path) -> None:
    root = _build_fixture(
        tmp_path / "privacy-forge",
        privacy_policy_satisfied=False,
    )
    _mutate_nested(
        root,
        "aperture_decision.json",
        ["hard_gates", "privacy_policy_satisfied"],
        True,
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "APERTURE_BYPASS_OR_BINDING_MISMATCH" in packet["reason_codes"]
    assert "APERTURE_REFUSE" in packet["reason_codes"]
    assert packet["recomputed_checks"]["aperture_decision"] is None
    _validate_output(packet)


def test_quarantine_receipt_tamper_rejects_without_raw_output_read(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "quarantine-tamper")
    _mutate_nested(
        root,
        "sonya/quarantine_receipt.json",
        ["raw_output_sha256"],
        "f" * 64,
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "QUARANTINE_RECEIPT_OR_BINDING_INVALID" in packet["reason_codes"]
    assert packet["recomputed_checks"]["quarantine_receipt_binding"] is False
    assert packet["recomputed_checks"]["quarantine_verification_binding"] is False
    assert "sonya/raw_output.quarantine" not in packet["input_digests"]
    _validate_output(packet)


def test_audit_rejects_parent_junction_without_opening_external_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _build_fixture(tmp_path / "junction-run")
    external = tmp_path / "external-sonya"
    (root / "sonya").rename(external)
    make_directory_link(root / "sonya", external)
    secret = external / "quarantine_receipt.json"
    original_open = Path.open

    def reject_external_open(path: Path, *args, **kwargs):
        if path.resolve(strict=False) == secret.resolve(strict=True):
            raise AssertionError("external junction member was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_external_open)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "REQUIRED_ARTIFACT_MISSING_OR_UNSAFE" in packet["reason_codes"]
    _validate_output(packet)


def test_raw_free_quarantine_verification_tamper_rejects(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "quarantine-verification-tamper")
    _mutate_nested(
        root,
        "sonya/quarantine_verification_receipt.json",
        ["verification", "exact_sha256_valid"],
        False,
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "QUARANTINE_VERIFICATION_OR_BINDING_INVALID" in packet["reason_codes"]
    assert packet["recomputed_checks"]["quarantine_receipt_binding"] is True
    assert packet["recomputed_checks"]["quarantine_verification_binding"] is False
    assert (
        packet["recomputed_checks"][
            "coherence_reperformed_exact_byte_proof_recorded"
        ]
        is False
    )
    assert "sonya/raw_output.quarantine" not in packet["input_digests"]
    _validate_output(packet)


def test_oversized_quarantine_byte_declaration_rejects_even_when_receipts_agree(
    tmp_path: Path,
) -> None:
    root = _build_fixture(tmp_path / "quarantine-oversized-declaration")
    receipt_path = root / "sonya" / "quarantine_receipt.json"
    verification_path = root / "sonya" / "quarantine_verification_receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    verification = json.loads(verification_path.read_bytes())
    receipt["raw_output_bytes"] = MAX_RAW_OUTPUT_BYTES + 1
    verification["raw_output_bytes"] = MAX_RAW_OUTPUT_BYTES + 1
    verification["quarantine_receipt_sha256"] = _canonical_sha256(receipt)
    _write_json(receipt_path, receipt)
    _write_json(verification_path, verification)

    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "QUARANTINE_RECEIPT_OR_BINDING_INVALID" in packet["reason_codes"]
    assert "QUARANTINE_VERIFICATION_OR_BINDING_INVALID" in packet["reason_codes"]
    assert packet["recomputed_checks"]["quarantine_receipt_binding"] is False
    assert packet["recomputed_checks"]["quarantine_verification_binding"] is False
    _validate_output(packet)


def test_request_manifest_hash_mismatch_rejects_and_fails_grounding_check(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "manifest-mismatch")
    _mutate_nested(
        root,
        "request.json",
        ["grounding", 0, "bundle_manifest_sha256"],
        "0" * 64,
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "GROUNDING_REQUEST_BINDING_MISMATCH" in packet["reason_codes"]
    assert packet["recomputed_checks"]["grounding_identity_and_adequacy"] is False
    _validate_output(packet)


def test_retention_grant_validates_no_write_pmr_boundary(tmp_path: Path) -> None:
    root = _build_fixture(
        tmp_path / "retention-grant",
        retention_requested=True,
        pmr_consent_decision="GRANT",
        pmr_expires_logical_time="2026-08-23T00:00:00Z",
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "HOLD"
    assert packet["recomputed_checks"]["pmr_retention_gate_satisfied"] is True
    assert _load(root / "pmr_receipt.json")["persistent_bytes_written"] == 0
    assert packet["side_effects"]["pmr_write_performed"] is False
    _validate_output(packet)


def test_retention_grant_preserves_nanosecond_expiry_order(tmp_path: Path) -> None:
    root = _build_fixture(
        tmp_path / "retention-grant-nanoseconds",
        retention_requested=True,
        pmr_consent_decision="GRANT",
        logical_time="2026-08-22T00:00:00.000000001Z",
        pmr_expires_logical_time="2026-08-22T00:00:00.000000002Z",
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "HOLD"
    assert "PMR_CONSENT_OR_CONTEXT_INVALID" not in packet["reason_codes"]
    assert packet["recomputed_checks"]["pmr_retention_gate_satisfied"] is True
    _validate_output(packet)


def test_retention_without_separate_consent_is_bounded_refusal(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "retention-no-consent", retention_requested=True)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "HOLD"
    assert "PMR_RETENTION_CONSENT_NOT_GRANTED" in packet["reason_codes"]
    assert packet["recomputed_checks"]["pmr_retention_gate_satisfied"] is False
    assert packet["input_digests"]["pmr_consent.json"] == {
        "file_sha256": None,
        "canonical_sha256": None,
    }
    _validate_output(packet)


def test_expired_pmr_grant_rejects_and_cannot_open_retention_gate(tmp_path: Path) -> None:
    root = _build_fixture(
        tmp_path / "retention-expired",
        retention_requested=True,
        pmr_consent_decision="GRANT",
        pmr_expires_logical_time="2026-08-21T23:59:59Z",
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "PMR_CONSENT_OR_CONTEXT_INVALID" in packet["reason_codes"]
    assert "APERTURE_BYPASS_OR_BINDING_MISMATCH" in packet["reason_codes"]
    assert packet["recomputed_checks"]["pmr_retention_gate_satisfied"] is False
    _validate_output(packet)


def test_aha_structural_review_never_claims_semantic_utility(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "aha-semantic-limit")
    aha = _load(root / "aha_result.json")
    assert aha["evaluation"]["semantic_non_vacuity_assessed"] is False
    assert aha["evaluation"]["semantic_utility_demonstrated"] is False
    assert (
        aha["evaluation"]["limitation"]
        == "STRUCTURAL_LINEAGE_COVERAGE_ONLY_NOT_SEMANTIC_EVIDENCE_OR_EXTERNAL_UTILITY"
    )
    components = aha["evaluation"]["scores"]["C_bridge"]["components"]
    assert components["lineage_reference_coverage"] == "PASS"
    assert "exact_evidence_coverage" not in components
    _mutate_nested(
        root,
        "aha_result.json",
        ["evaluation", "semantic_utility_demonstrated"],
        True,
    )
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "AHA_RESULT_RECOMPUTATION_MISMATCH" in packet["reason_codes"]
    _validate_output(packet)


def test_tel_audit_prefix_is_the_only_tel_parent(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "immutable-tel-prefix")
    (root / "tel_events.jsonl").write_bytes(b"later mutable route ledger\n")
    before = (root / "tel_events.jsonl").read_bytes()
    packet = audit_totality_run(root)
    assert packet["disposition"] == "HOLD"
    assert "tel_audit_prefix.jsonl" in packet["input_digests"]
    assert "tel_events.jsonl" not in packet["input_digests"]
    assert (root / "tel_events.jsonl").read_bytes() == before
    _validate_output(packet)


def test_tel_payload_digest_mutation_is_rejected(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "tel-payload-mutation")
    rows = [
        json.loads(line)
        for line in (root / "tel_audit_prefix.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["payload"]["request_sha256"] = "0" * 64
    _write_jsonl(root / "tel_audit_prefix.jsonl", rows)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "TEL_EVENT_INVALID" in packet["reason_codes"]
    assert packet["recomputed_checks"]["tel_chronology_valid"] is False
    _validate_output(packet)


def test_default_output_refuses_to_mutate_sealed_run(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "sealed-run")
    audit_totality_run(root)
    before = (root / "sophia_audit_packet.json").read_bytes()
    for marker in (
        "run_manifest.json",
        "sealed_artifact_manifest.json",
        "checksums.sha256",
    ):
        (root / marker).write_bytes(b"sealed\n")
    with pytest.raises(ValueError, match="sealed run is immutable"):
        audit_totality_run(root)
    assert (root / "sophia_audit_packet.json").read_bytes() == before


def test_oversized_public_input_is_rejected_before_full_read(tmp_path: Path) -> None:
    root = _build_fixture(tmp_path / "oversized-input")
    request_path = root / "request.json"
    with request_path.open("wb") as stream:
        stream.truncate(4 * 1024 * 1024 + 1)
    packet = audit_totality_run(root)
    assert packet["disposition"] == "REJECT"
    assert "ARTIFACT_SIZE_LIMIT_EXCEEDED_OR_UNREADABLE" in packet["reason_codes"]
    assert packet["input_digests"]["request.json"] == {
        "file_sha256": None,
        "canonical_sha256": None,
    }
    _validate_output(packet)
