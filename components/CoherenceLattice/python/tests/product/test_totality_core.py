from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import jsonschema
import pytest

import coherence.totality.cli as totality_cli_module
import coherence.totality.seal as seal_module
from coherence.totality.adapter import (
    CapturedAdapter,
    MAX_RAW_OUTPUT_BYTES,
    build_candidate_packet,
    build_quarantine_verification_receipt,
    captured_adapter_contract,
    quarantine_raw_output,
    read_quarantined_capture,
    validate_adapter_contract,
    validate_candidate_packet,
)
from coherence.totality.aha import evaluate_structural_aha
from coherence.totality.aperture import decide_aperture
from coherence.totality.atlas_contract import (
    ATLAS_DECISIONS,
    ATLAS_EFFECTS,
    ATLAS_NONAUTHORITY,
    ATLAS_NONAUTHORITY_STATEMENT,
    ATLAS_POSTURES,
)
from coherence.totality.canonical import (
    canonical_json_bytes,
    require_identifier,
    sha256_bytes,
    sha256_file,
    sha256_json,
    strict_json_loads,
)
from coherence.totality.claims import build_claim_evidence_map, validate_claim_evidence_map
from coherence.totality.cli import (
    MAX_REQUEST_BYTES,
    build_core_from_inputs,
    finalize_route_tel,
    main as totality_cli,
    replay_core,
    repository_identity,
    verify_failure_output,
)
from coherence.totality.counterexamples import search_counterexamples
from coherence.totality.errors import OperationalError, ValidationError
from coherence.totality.grounding import (
    SEGMENTATION_PROFILE,
    build_grounding_bundle,
    read_grounding_bundle,
    validate_grounding_bundle,
    write_grounding_bundle,
)
from coherence.totality.plugins import (
    EFFECT_KEYS,
    disabled_plugin_receipt,
    validate_disabled_plugin_catalog,
    validate_plugin_receipt,
)
from coherence.totality.pmr import PMRReferenceStore, build_consent_packet, no_write_receipt
from coherence.totality.request import REQUEST_SCHEMA, project_legacy_request, validate_request_envelope
from coherence.totality.seal import (
    build_deterministic_zip,
    build_core_manifest,
    inventory_files,
    seal_run,
    verify_core_manifest_contract,
    verify_sealed_run,
    verify_zip_sidecar,
)
from coherence.totality.tel import (
    AUDIT_PREFIX_ORDER,
    EVENT_ORDER,
    SEALED_ROUTE_ORDER,
    TELLedger,
    build_human_decision_continuation,
    derive_audit_id,
    parse_final_route_tel_jsonl,
    parse_tel_jsonl,
)
from coherence.totality.ucm import AXES, build_ucm_state, project_ucm, validate_ucm_state
from coherence.totality.waveform import encode_reference_waveform


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

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "schema" / "totality"


def source_bytes(*, counterexample: bool = False) -> bytes:
    suffix = "\n\nA limitation is pending review." if counterexample else ""
    return ("The local route uses exact source spans.\n\nReview receipts preserve deterministic evidence." + suffix).encode()


def request_value(source: bytes, **overrides) -> dict:
    bundle = build_grounding_bundle(source)
    value = {
        "schema_id": REQUEST_SCHEMA,
        "request_id": "REQ-001",
        "run_id": "RUN-001",
        "logical_time": "2026-08-22T00:00:00Z",
        "kind": "document_qa",
        "user_input": "What does the local route use?",
        "grounding": [{
            "source_kind": "grounding_bundle",
            "label": "local-source",
            "media_type": "text/markdown",
            "source_id": f"SRC-{bundle['manifest']['source_sha256'][:20]}",
            "bundle_manifest_path": "grounding/manifest.json",
            "bundle_manifest_sha256": sha256_json(bundle["manifest"]),
            "normalized_sha256": bundle["manifest"]["normalized_sha256"],
            "source_sha256": bundle["manifest"]["source_sha256"],
            "metadata": {},
        }],
        "task_consent": True,
        "retention_requested": False,
        "model": None,
        "divergence_mode": None,
        "meta": {"privacy_policy_satisfied": True, "privacy_basis": "Local captured bytes; network policy DENY."},
    }
    value.update(overrides)
    return value


def capture_value() -> dict:
    answer = "The local route uses exact source spans."
    return {
        "schema_id": "uvlm.sonya.totality.captured_semantic.v1",
        "answer": answer,
        "uncertainty": 0.1,
        "claims": [{"claim_id": "CL-001", "text": answer, "answer_start": 0, "answer_end": len(answer)}],
    }


def citation_reference(
    bundle: dict,
    claim_text: str,
    *,
    segment_index: int = 0,
    relation: str = "SUPPORTS",
) -> dict:
    segment = bundle["segments"][segment_index]
    return {
        "source_sha256": bundle["manifest"]["source_sha256"],
        "segment_id": segment["segment_id"],
        "segment_sha256": segment["sha256"],
        "source_span": {
            "byte_start": segment["byte_start"],
            "byte_end": segment["byte_end"],
            "char_start": segment["char_start"],
            "char_end": segment["char_end"],
        },
        "exact_excerpt_sha256": segment["sha256"],
        "claim_text_sha256": sha256_bytes(claim_text.encode("utf-8")),
        "candidate_relation": relation,
    }


def candidate_from_capture(capture: dict, *, request_sha: str = "a" * 64) -> dict:
    raw = canonical_json_bytes(capture)
    receipt = {
        "schema_id": "uvlm.sonya.totality.raw_quarantine_receipt.v1",
        "adapter_id": "sonya.captured_candidate.reference.v1",
        "request_sha256": request_sha,
        "raw_output_sha256": sha256_bytes(raw),
        "raw_output_bytes": len(raw),
        "quarantine_member": "raw.quarantine",
        "raw_output_quarantined": True,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    return build_candidate_packet(
        capture,
        receipt,
        request_sha256=request_sha,
        run_id="RUN-1",
        logical_time="T0",
    )


def aha_case(bundle: dict) -> dict:
    lineage = [bundle["segments"][0]["segment_id"]]

    def graph(graph_id: str, domain: str, family: str) -> dict:
        return {
            "graph_id": graph_id, "domain": domain, "source_family_id": family,
            "nodes": [
                {"node_id": "a", "node_type": "state", "label": "input", "lineage": lineage},
                {"node_id": "b", "node_type": "state", "label": "output", "lineage": lineage},
            ],
            "relations": [{
                "relation_id": "r", "relation_type": "causes", "source_node_id": "a",
                "target_node_id": "b", "orientation": "forward", "lineage": lineage,
            }],
        }

    return {
        "schema_id": "aha-case-v1", "case_id": "AHA-001", "question": "Does the route bind evidence?",
        "grounding_segments": [{"segment_id": row["segment_id"], "sha256": row["sha256"]} for row in bundle["segments"]],
        "target": graph("target", "local-route", "target-family"),
        "donors": [graph("donor-1", "ledger", "family-one"), graph("donor-2", "review", "family-two")],
        "mappings": [{
            "mapping_id": f"mapping-{index}", "donor_graph_id": donor,
            "node_map": {"a": "a", "b": "b"}, "relation_map": {"r": "r"},
            "invariant_map": {"ordering": "input precedes output"},
            "disanalogies": ["domain differs"], "declared_scale_or_unit_transformations": [],
        } for index, donor in enumerate(("donor-1", "donor-2"), start=1)],
        "candidate_hypothesis": {
            "statement": "Binding preserves review context.", "target_observable": "binding match",
            "intervention_or_condition": "exact hash binding", "expected_direction": "increase",
            "comparator_or_null": "unbound candidate", "horizon": "one replay",
            "confidence_lowering_observation": "hash substitution is accepted",
        },
        "falsification_test": {
            "test_statement": "Substitute a source hash and require rejection.",
            "primary_outcome": "rejection", "comparator": "unaltered source",
            "reject_criteria": "substitution is accepted", "feasibility_posture": "LOCAL_FEASIBLE",
            "risk_posture": "LOW",
        },
    }


def build_run(tmp_path: Path, *, with_aha: bool = True, counterexample: bool = False) -> Path:
    source = source_bytes(counterexample=counterexample)
    bundle = build_grounding_bundle(source)
    out = tmp_path / "run"
    build_core_from_inputs(
        request_bytes=canonical_json_bytes(request_value(source)),
        source_bytes=source,
        captured_bytes=canonical_json_bytes(capture_value()),
        output_dir=out,
        aha_case=aha_case(bundle) if with_aha else None,
    )
    return out


def schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def write_external_packets(run: Path, *, disposition: str = "PASS") -> tuple[dict, dict]:
    request = strict_json_loads((run / "request.json").read_bytes())
    candidate = strict_json_loads((run / "candidate_packet.json").read_bytes())
    prefix_sha = sha256_bytes((run / "tel_audit_prefix.jsonl").read_bytes())
    audit_id = derive_audit_id(
        sha256_json(candidate),
        sha256_bytes((run / "aperture_decision.json").read_bytes()),
    )
    sophia = {
        "schema_id": "uvlm.sophia.totality.audit_packet.v1",
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "candidate_id": candidate["candidate_id"],
        "audit_id": audit_id,
        "disposition": disposition,
        "input_digests": {
            "grounding/manifest.json": {
                "file_sha256": sha256_bytes((run / "grounding/manifest.json").read_bytes())
            },
            "tel_audit_prefix.jsonl": {"file_sha256": prefix_sha},
        },
    }
    (run / "sophia_audit_packet.json").write_bytes(canonical_json_bytes(sophia))
    atlas = {
        "schema_id": "uvlm.atlas.totality.posture_packet.v1",
        "schema_version": "1.0",
        "packet_type": "atlas_posture_packet",
        "producer_repository": "pdxvoiceteacher/uvlm-publications",
        "producer": {
            "repository": "pdxvoiceteacher/uvlm-publications",
            "role": "bounded_totality_posture_and_human_review_renderer",
            "version": "1.0",
        },
        "run_id": request["run_id"],
        "logical_time": request["logical_time"],
        "candidate_id": candidate["candidate_id"],
        "audit_id": audit_id,
        "sophia_disposition": disposition,
        "requires_human_review": True,
        "human_action_required": True,
        "human_decision": "PENDING",
        "human_decision_options": list(ATLAS_DECISIONS),
        "retention_posture": ATLAS_POSTURES[disposition][0],
        "publication_posture": ATLAS_POSTURES[disposition][1],
        "expiry_posture": "review_bounded",
        "revocation_posture": "revocable",
        "pmr_posture": "separate_consent_no_action",
        "candidate_is_not_answer": True,
        "full_posterior_presented": True,
        "top_k_is_presentation_only": True,
        "sophia_reason_codes": [f"FIXTURE_{disposition}"],
        "sophia_findings": [],
        "limitations": ["Bounded test fixture; human review remains required."],
        "input_digests": {
            "tel_audit_prefix.jsonl": {"file_sha256": prefix_sha},
            "sophia_audit_packet.json": {
                "file_sha256": sha256_bytes((run / "sophia_audit_packet.json").read_bytes())
            },
        },
        "parent_list": [
            {
                "artifact_type": "bounded_input",
                "path": "tel_audit_prefix.jsonl",
                "file_sha256": prefix_sha,
                "canonical_sha256": None,
            },
            {
                "artifact_type": "bounded_input",
                "path": "sophia_audit_packet.json",
                "file_sha256": sha256_bytes(
                    (run / "sophia_audit_packet.json").read_bytes()
                ),
                "canonical_sha256": sha256_json(sophia),
            },
        ],
        "nonauthority": dict.fromkeys(ATLAS_NONAUTHORITY, False),
        "side_effects": dict.fromkeys(ATLAS_EFFECTS, False),
        "nonauthority_statement": ATLAS_NONAUTHORITY_STATEMENT,
    }
    (run / "atlas_posture_packet.json").write_bytes(canonical_json_bytes(atlas))
    return sophia, atlas


def test_request_python_schema_parity_and_explicit_legacy_projection() -> None:
    request = request_value(source_bytes())
    jsonschema.Draft202012Validator(schema("request_envelope.v1.schema.json")).validate(request)
    assert validate_request_envelope(request).to_dict() == request
    mutable = copy.deepcopy(request)
    mutable["meta"] = {"nested": {"values": [1]}}
    mutable["grounding"][0]["metadata"] = {"nested": {"values": [2]}}
    frozen = validate_request_envelope(mutable)
    mutable["meta"]["nested"]["values"].append(3)
    mutable["grounding"][0]["metadata"]["nested"]["values"].append(4)
    projected_copy = frozen.to_dict()
    assert projected_copy["meta"]["nested"]["values"] == [1]
    assert projected_copy["grounding"][0]["metadata"]["nested"]["values"] == [2]
    projected_copy["meta"]["nested"]["values"].append(5)
    assert frozen.to_dict()["meta"]["nested"]["values"] == [1]
    bad = {**request, "unexpected": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema("request_envelope.v1.schema.json"))
    with pytest.raises(ValidationError, match="EXTRA_KEYS"):
        validate_request_envelope(bad)
    missing_manifest_hash = copy.deepcopy(request)
    del missing_manifest_hash["grounding"][0]["bundle_manifest_sha256"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing_manifest_hash, schema("request_envelope.v1.schema.json"))
    with pytest.raises(ValidationError, match="BUNDLE_FIELDS_REQUIRED"):
        validate_request_envelope(missing_manifest_hash)
    null_bundle_field = copy.deepcopy(request)
    null_bundle_field["grounding"][0]["bundle_manifest_sha256"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(null_bundle_field, schema("request_envelope.v1.schema.json"))
    with pytest.raises(ValidationError, match="INVALID_SHA256"):
        validate_request_envelope(null_bundle_field)
    for required_name in ("source_id", "media_type"):
        missing_source_identity = copy.deepcopy(request)
        del missing_source_identity["grounding"][0][required_name]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                missing_source_identity, schema("request_envelope.v1.schema.json")
            )
        with pytest.raises(ValidationError, match="BUNDLE_FIELDS_REQUIRED"):
            validate_request_envelope(missing_source_identity)
    invalid_source_id = copy.deepcopy(request)
    invalid_source_id["grounding"][0]["source_id"] = "ANY-VALID-IDENTIFIER"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            invalid_source_id, schema("request_envelope.v1.schema.json")
        )
    with pytest.raises(ValidationError, match="SOURCE_ID_INVALID"):
        validate_request_envelope(invalid_source_id)
    inline_null = copy.deepcopy(request)
    inline_null["grounding"] = [{"source_kind": "inline_text", "text": None}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(inline_null, schema("request_envelope.v1.schema.json"))
    with pytest.raises(ValidationError, match="INLINE_GROUNDING_TEXT_REQUIRED"):
        validate_request_envelope(inline_null)
    whitespace = copy.deepcopy(request)
    whitespace["user_input"] = " \t\n "
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(whitespace, schema("request_envelope.v1.schema.json"))
    with pytest.raises(ValidationError, match="TEXT_LENGTH_INVALID"):
        validate_request_envelope(whitespace)
    legacy = {
        "kind": "document_qa", "user_input": request["user_input"], "grounding": request["grounding"],
        "experiment": None, "model": None, "divergence_mode": None, "meta": {},
    }
    projected = project_legacy_request(
        legacy, request_id="REQ-L", run_id="RUN-L", logical_time="T0", task_consent=True,
    )
    assert projected.meta["legacy_projection"] == "explicit_v1"
    assert projected.retention_requested is False
    old_legacy = copy.deepcopy(legacy)
    del old_legacy["grounding"][0]["bundle_manifest_sha256"]
    with pytest.raises(ValidationError, match="MANIFEST_HASH_REQUIRED"):
        project_legacy_request(
            old_legacy, request_id="REQ-L", run_id="RUN-L", logical_time="T0", task_consent=True,
        )
    projected_old = project_legacy_request(
        old_legacy, request_id="REQ-L", run_id="RUN-L", logical_time="T0", task_consent=True,
        bundle_manifest_sha256_by_path={
            "grounding/manifest.json": request["grounding"][0]["bundle_manifest_sha256"]
        },
    )
    assert projected_old.grounding[0]["bundle_manifest_sha256"] == request["grounding"][0]["bundle_manifest_sha256"]


@pytest.mark.parametrize("nested", [
    {"x": [{"render_prompt": "draw it"}]},
    {"x": {"training": True}},
    {"x": {"publication_authorization": "YES"}},
])
def test_nested_prompt_and_positive_authority_metadata_are_rejected(nested: dict) -> None:
    request = request_value(source_bytes())
    request["meta"] = nested
    with pytest.raises(ValidationError, match="PROHIBITED"):
        validate_request_envelope(request)


def test_unicode_default_ignorable_non_nfc_and_confusable_keys_fail_closed() -> None:
    request_schema = schema("request_envelope.v1.schema.json")
    layering = request_schema["x-uvlm-contract-layering"]
    assert layering["json_schema_role"] == "structural_validation"
    assert layering["required_semantic_validator"].endswith(
        "validate_request_envelope"
    )
    request = request_value(source_bytes())
    request["user_input"] = "hidden\u200btext"
    jsonschema.Draft202012Validator(request_schema).validate(request)
    with pytest.raises(ValidationError, match="DEFAULT_IGNORABLE"):
        validate_request_envelope(request)
    request = request_value(source_bytes())
    request["user_input"] = "Cafe\u0301"
    jsonschema.Draft202012Validator(request_schema).validate(request)
    with pytest.raises(ValidationError, match="NFC"):
        validate_request_envelope(request)
    request = request_value(source_bytes())
    request["meta"] = {"nested": {"training": True}}
    jsonschema.Draft202012Validator(request_schema).validate(request)
    with pytest.raises(ValidationError, match="PROHIBITED"):
        validate_request_envelope(request)
    with pytest.raises(ValidationError, match="OBJECT_KEY_INVALID_ASCII"):
        strict_json_loads('{"metα":1}')


def test_strict_json_duplicate_nonfinite_and_bom_rejected() -> None:
    with pytest.raises(ValidationError, match="DUPLICATE"):
        strict_json_loads('{"x":1,"x":2}')
    with pytest.raises(ValidationError, match="NONFINITE"):
        strict_json_loads('{"x":NaN}')
    with pytest.raises(ValidationError, match="BOM"):
        strict_json_loads(b"\xef\xbb\xbf{}")


def test_canonical_bridge_path_map_keys_round_trip_but_identifiers_stay_strict() -> None:
    value = {
        "input_digests": {
            "grounding/manifest.json": {"file_sha256": "a" * 64},
            "tel_audit_prefix.jsonl": {"file_sha256": "b" * 64},
        }
    }
    encoded = canonical_json_bytes(value)
    assert strict_json_loads(encoded) == value
    with pytest.raises(ValidationError, match="INVALID_ASCII_IDENTIFIER"):
        require_identifier("grounding/manifest.json", "$.identifier")
    for unsafe in ("/absolute", "a//b", "a/./b", "a/../b", "a\\b", "grounding/manifest.jsoн"):
        with pytest.raises(ValidationError, match="JSON_OBJECT_KEY"):
            canonical_json_bytes({"input_digests": {unsafe: {}}})


def test_grounding_manifest_counts_spans_and_tamper_detection(tmp_path: Path) -> None:
    bundle = build_grounding_bundle(source_bytes())
    assert bundle["manifest"]["segmentation"] == SEGMENTATION_PROFILE
    assert bundle["manifest"]["segment_count"] == 2
    validate_grounding_bundle(bundle)
    write_grounding_bundle(bundle, tmp_path / "grounding")
    assert read_grounding_bundle(tmp_path / "grounding")["manifest"] == bundle["manifest"]
    for mutate, code in (
        (lambda value: value["manifest"].update({"segment_count": 99}), "SEGMENT_COUNT"),
        (lambda value: value["manifest"].update({"source_bytes": 1}), "BYTE_COUNT"),
        (lambda value: value["manifest"].update({"segmentation": "ALPHA_DRIFT"}), "SEGMENTATION"),
        (lambda value: value["segments"][0].update({"text": "substitution"}), "EXACT_SPAN"),
    ):
        changed = copy.deepcopy(bundle)
        mutate(changed)
        with pytest.raises(ValidationError, match=code):
            validate_grounding_bundle(changed)


def test_adapter_schema_capability_authorization_quarantine_and_candidate(tmp_path: Path) -> None:
    contract = captured_adapter_contract()
    jsonschema.validate(contract, schema("adapter_contract.v1.schema.json"))
    validate_adapter_contract(contract)
    assert contract["capabilities"]["cancellation"] is False
    unsafe = copy.deepcopy(contract)
    unsafe["capabilities"]["provider_invocation"] = True
    with pytest.raises(ValidationError, match="CAPABILITY_NOT_AUTHORIZED"):
        validate_adapter_contract(unsafe)
    request_sha = "a" * 64
    raw = canonical_json_bytes(capture_value())
    path = tmp_path / "raw.quarantine"
    receipt = quarantine_raw_output(raw, path, request_sha256=request_sha, task_consent=True)
    capture = read_quarantined_capture(path, receipt, expected_request_sha256=request_sha)
    candidate = build_candidate_packet(
        capture, receipt, request_sha256=request_sha, run_id="RUN-1", logical_time="T0",
    )
    jsonschema.validate(candidate, schema("candidate_packet.v1.schema.json"))
    assert validate_candidate_packet(candidate) == candidate
    packaged_schema = json.loads(
        (
            ROOT
            / "python/src/coherence/totality/schemas/candidate_packet.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert packaged_schema == schema("candidate_packet.v1.schema.json")
    assert candidate["claims"][0]["candidate_evidence_references"] == []
    invalid_candidate = {**candidate, "extra": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_candidate, schema("candidate_packet.v1.schema.json"))
    with pytest.raises(ValidationError, match="EXTRA_KEYS"):
        validate_candidate_packet(invalid_candidate)
    for invalid_identity in ("", "x" * 257):
        invalid_model = {**candidate, "model_identity": invalid_identity}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_model, schema("candidate_packet.v1.schema.json"))
        with pytest.raises(ValidationError, match="MODEL_IDENTITY_INVALID"):
            validate_candidate_packet(invalid_model)
    assert candidate["not_release_authorization"] is True
    assert candidate["logical_time"] == "T0"
    path.write_bytes(raw + b" ")
    with pytest.raises(ValidationError, match="RAW_IDENTITY"):
        read_quarantined_capture(path, receipt, expected_request_sha256=request_sha)
    with pytest.raises(OperationalError, match="EXISTS"):
        quarantine_raw_output(raw, path, request_sha256=request_sha, task_consent=True)


def test_raw_quarantine_byte_cap_precedes_any_file_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "raw.quarantine"
    with pytest.raises(ValidationError, match="LIMIT_EXCEEDED"):
        quarantine_raw_output(
            b"x" * (MAX_RAW_OUTPUT_BYTES + 1), target,
            request_sha256="a" * 64, task_consent=True,
        )
    assert not target.exists()

    forged_receipt = {
        "schema_id": "uvlm.sonya.totality.raw_quarantine_receipt.v1",
        "adapter_id": "sonya.captured_candidate.reference.v1",
        "request_sha256": "a" * 64,
        "raw_output_sha256": "b" * 64,
        "raw_output_bytes": MAX_RAW_OUTPUT_BYTES + 1,
        "quarantine_member": target.name,
        "raw_output_quarantined": True,
        "network_used": False,
        "provider_invoked": False,
        "memory_written": False,
        "training_used": False,
        "authority_effect": "NONE",
    }
    with pytest.raises(ValidationError, match="BYTE_COUNT_INVALID"):
        read_quarantined_capture(
            target, forged_receipt, expected_request_sha256="a" * 64,
        )

    target.write_bytes(b"x" * (MAX_RAW_OUTPUT_BYTES + 1))
    bounded_receipt = {**forged_receipt, "raw_output_bytes": MAX_RAW_OUTPUT_BYTES}
    original_read_bytes = Path.read_bytes

    def reject_unbounded_read(path: Path) -> bytes:
        if path == target:
            raise AssertionError("quarantine must use a bounded stream read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_unbounded_read)
    with pytest.raises(ValidationError, match="LIMIT_EXCEEDED"):
        read_quarantined_capture(
            target, bounded_receipt, expected_request_sha256="a" * 64,
        )


def test_quarantine_verification_receipt_is_raw_free_bound_and_tamper_sensitive(tmp_path: Path) -> None:
    raw = canonical_json_bytes(capture_value())
    request_sha = "a" * 64
    path = tmp_path / "raw.quarantine"
    receipt = quarantine_raw_output(raw, path, request_sha256=request_sha, task_consent=True)
    capture = read_quarantined_capture(path, receipt, expected_request_sha256=request_sha)
    candidate = build_candidate_packet(
        capture, receipt, request_sha256=request_sha, run_id="RUN-1", logical_time="T0",
    )
    verification = build_quarantine_verification_receipt(
        path, receipt, candidate, request_sha256=request_sha, run_id="RUN-1", logical_time="T0",
    )
    jsonschema.validate(verification, schema("quarantine_verification_receipt.v1.schema.json"))
    assert verification["raw_output_disclosed"] is False
    assert set(verification["verification"].values()) == {True}
    assert set(verification["effects"].values()) == {False}
    path.write_bytes(raw + b" ")
    with pytest.raises(ValidationError, match="RAW_IDENTITY"):
        build_quarantine_verification_receipt(
            path, receipt, candidate, request_sha256=request_sha, run_id="RUN-1", logical_time="T0",
        )


def test_claim_evidence_exact_spans_and_recomputation_tamper() -> None:
    source = source_bytes()
    bundle = build_grounding_bundle(source)
    capture = capture_value()
    capture["claims"][0]["candidate_evidence_references"] = [
        citation_reference(bundle, capture["claims"][0]["text"])
    ]
    candidate = candidate_from_capture(capture)
    claim_map = build_claim_evidence_map(candidate, bundle)
    evidence = claim_map["claims"][0]["evidence"][0]
    span = evidence["source_span"]
    assert bundle["normalized_source"][span["char_start"]:span["char_end"]] == evidence["exact_excerpt"]
    assert evidence["citation_integrity"] == "VERIFIED"
    assert evidence["integrity_reason_codes"] == []
    assert claim_map["claims"][0]["support_status"] == "CITATION_VERIFIED_REVIEW_REQUIRED"
    assert claim_map["unsupported_claim_ids"] == []
    changed = copy.deepcopy(claim_map)
    changed["claims"][0]["evidence"][0]["exact_excerpt"] = "tampered"
    with pytest.raises(ValidationError, match="RECOMPUTATION"):
        validate_claim_evidence_map(changed, candidate, bundle)


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda ref: ref.update(source_sha256="0" * 64), "CITATION_SOURCE_SHA256_MISMATCH"),
        (lambda ref: ref.update(segment_id="SEG-9999"), "CITATION_SEGMENT_ID_NOT_FOUND"),
        (lambda ref: ref.update(segment_sha256="0" * 64), "CITATION_SEGMENT_SHA256_MISMATCH"),
        (
            lambda ref: ref.update(
                source_span={
                    **ref["source_span"],
                    "char_start": ref["source_span"]["char_start"] + 1,
                    "byte_start": ref["source_span"]["byte_start"] + 1,
                }
            ),
            "CITATION_EXACT_EXCERPT_SHA256_MISMATCH",
        ),
    ],
)
def test_bad_candidate_citations_fail_closed_without_semantic_inference(
    mutation, reason_code: str,
) -> None:
    bundle = build_grounding_bundle(source_bytes())
    capture = capture_value()
    reference = citation_reference(bundle, capture["claims"][0]["text"])
    mutation(reference)
    capture["claims"][0]["candidate_evidence_references"] = [reference]
    claim_map = build_claim_evidence_map(candidate_from_capture(capture), bundle)
    finding = claim_map["claims"][0]["evidence"][0]
    assert finding["citation_integrity"] == "INVALID"
    assert reason_code in finding["integrity_reason_codes"]
    assert claim_map["claims"][0]["support_status"] == "INSUFFICIENT_EVIDENCE"
    assert claim_map["unsupported_claim_ids"] == ["CL-001"]


def test_claim_citation_copy_is_rejected_before_source_posture() -> None:
    bundle = build_grounding_bundle(source_bytes())
    capture = capture_value()
    reference = citation_reference(bundle, "A different claim.")
    capture["claims"][0]["candidate_evidence_references"] = [reference]
    with pytest.raises(ValidationError, match="CLAIM_TEXT_BINDING_MISMATCH"):
        candidate_from_capture(capture)


def test_paraphrase_limitation_and_contradiction_controls_are_differentiated() -> None:
    source = b"The process preserves exact receipts.\n\nHowever, semantic review remains required."
    bundle = build_grounding_bundle(source)
    claims = [
        "Receipts are preserved by the process.",
        "The source itself resolves semantic meaning.",
    ]
    answer = "\n".join(claims)
    capture = {
        "schema_id": "uvlm.sonya.totality.captured_semantic.v1",
        "answer": answer,
        "uncertainty": 0.2,
        "claims": [
            {
                "claim_id": "CL-PARAPHRASE",
                "text": claims[0],
                "answer_start": 0,
                "answer_end": len(claims[0]),
                "candidate_evidence_references": [
                    citation_reference(bundle, claims[0], relation="SUPPORTS"),
                    citation_reference(
                        bundle,
                        claims[0],
                        segment_index=1,
                        relation="LIMITS",
                    ),
                ],
            },
            {
                "claim_id": "CL-CONTRADICTED",
                "text": claims[1],
                "answer_start": len(claims[0]) + 1,
                "answer_end": len(answer),
                "candidate_evidence_references": [
                    citation_reference(
                        bundle,
                        claims[1],
                        segment_index=1,
                        relation="CONTRADICTS",
                    )
                ],
            },
        ],
    }
    claim_map = build_claim_evidence_map(candidate_from_capture(capture), bundle)
    statuses = {row["claim_id"]: row["support_status"] for row in claim_map["claims"]}
    assert statuses == {
        "CL-PARAPHRASE": "CITATION_VERIFIED_WITH_LIMITATION_REVIEW_REQUIRED",
        "CL-CONTRADICTED": "POSSIBLE_SOURCE_CONTRADICTION_REVIEW_REQUIRED",
    }
    assert claim_map["unsupported_claim_ids"] == ["CL-CONTRADICTED"]


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        ("Alice won the race.", "Alice lost the race."),
        ("Alice won the race. That claim is false.", "Alice won the race."),
    ],
)
def test_lexical_overlap_and_quoted_refutation_never_establish_semantic_support(
    tmp_path: Path, source: str, claim: str
) -> None:
    source_raw = source.encode("utf-8")
    capture = {
        "schema_id": "uvlm.sonya.totality.captured_semantic.v1",
        "answer": claim,
        "uncertainty": 0.1,
        "claims": [
            {
                "claim_id": "CL-SEMANTIC-001",
                "text": claim,
                "answer_start": 0,
                "answer_end": len(claim),
            }
        ],
    }
    run = tmp_path / "semantic-negative"
    build_core_from_inputs(
        request_bytes=canonical_json_bytes(request_value(source_raw)),
        source_bytes=source_raw,
        captured_bytes=canonical_json_bytes(capture),
        output_dir=run,
        aha_case=aha_case(build_grounding_bundle(source_raw)),
    )
    claim_map = strict_json_loads((run / "claim_evidence_map.json").read_bytes())
    assert claim_map["claims"][0]["support_status"] == "NO_VALID_SOURCE_CITATION"
    assert claim_map["unsupported_claim_ids"] == ["CL-SEMANTIC-001"]
    assert strict_json_loads((run / "counterexamples.json").read_bytes())[
        "unresolved_count"
    ] >= 1
    assert strict_json_loads((run / "aperture_decision.json").read_bytes())[
        "decision"
    ] == "REFUSE"


def ucm_state(*, unsupported=(), pattern="IN_DISTRIBUTION") -> dict:
    context = {
        "request_sha256": "1" * 64, "candidate_sha256": "2" * 64,
        "grounding_manifest_sha256": "3" * 64, "source_sha256": "4" * 64,
        "claim_map_sha256": "5" * 64,
    }
    hypotheses = [
        {"hypothesis_id": "h1", "score": 3.0, "equivalence_group": "g1", "pattern_posture": pattern},
        {"hypothesis_id": "h2", "score": 2.0, "equivalence_group": "g1", "pattern_posture": "IN_DISTRIBUTION"},
        {"hypothesis_id": "h3", "score": 0.0, "equivalence_group": "g2", "pattern_posture": "IN_DISTRIBUTION"},
    ]
    return build_ucm_state(
        run_id="RUN-1", candidate_id="CAND-1", expected_context=context,
        axes=dict.fromkeys(AXES, 0.9), uncertainty=0.1, source_ref_count=1,
        unsupported_claim_ids=list(unsupported), hypotheses=hypotheses,
    )


def test_full_posterior_equivalence_and_top_k_is_presentation_only() -> None:
    state = ucm_state()
    one, three = project_ucm(state, top_k=1), project_ucm(state, top_k=3)
    assert one["projector"]["full_equivalence_posterior"] == three["projector"]["full_equivalence_posterior"]
    assert one["projector"]["disposition"] == three["projector"]["disposition"] == "PASS_SCREEN"
    assert one["residual_refusal"] == three["residual_refusal"]
    assert one["projector"]["presentation"] != three["projector"]["presentation"]
    assert sum(row["probability"] for row in one["projector"]["full_candidate_posterior"]) == pytest.approx(1.0)
    assert one["projector"]["full_equivalence_posterior"][0]["equivalence_group"] == "g1"


def test_ucm_expected_context_cross_field_mutation_and_refusal() -> None:
    state = ucm_state()
    expected = dict(state["expected_context"])
    validate_ucm_state(state, expected_context=expected)
    changed = copy.deepcopy(state)
    changed["expected_context"]["source_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="EXPECTED_CONTEXT"):
        validate_ucm_state(changed, expected_context=expected)
    assert project_ucm(ucm_state(unsupported=("CL-1",)))["projector"]["disposition"] == "REFUSE"
    assert project_ucm(ucm_state(pattern="OOD"))["residual_refusal"]["refusal"]["triggered"] is True


def test_structural_aha_donor_shuffle_and_source_ablation_controls() -> None:
    bundle = build_grounding_bundle(source_bytes())
    case = aha_case(bundle)
    first = evaluate_structural_aha(
        case, grounding_bundle=bundle, run_id="RUN-1", candidate_id="CAND-1", candidate_sha256="a" * 64,
    )
    shuffled = copy.deepcopy(case)
    shuffled["donors"].reverse()
    shuffled["mappings"].reverse()
    second = evaluate_structural_aha(
        shuffled, grounding_bundle=bundle, run_id="RUN-1", candidate_id="CAND-1", candidate_sha256="a" * 64,
    )
    assert first["evaluation"] == second["evaluation"]
    assert first["disposition"] == "REVIEWABLE"
    components = first["evaluation"]["scores"]["C_bridge"]["components"]
    assert "exact_evidence_coverage" not in components
    assert components["lineage_reference_coverage"] == "PASS"
    assert first["evaluation"]["semantic_non_vacuity_assessed"] is False
    assert first["evaluation"]["semantic_utility_demonstrated"] is False
    substituted = copy.deepcopy(case)
    substituted["donors"][0]["relations"][0]["relation_type"] = "precedes"
    substituted_result = evaluate_structural_aha(
        substituted,
        grounding_bundle=bundle,
        run_id="RUN-1",
        candidate_id="CAND-1",
        candidate_sha256="a" * 64,
    )
    assert substituted_result["disposition"] == "REJECTED"
    assert "AHA_RELATION_TYPE_MISMATCH" in substituted_result["reason_codes"]
    ablated = copy.deepcopy(case)
    ablated["grounding_segments"].pop()
    with pytest.raises(ValidationError, match="SEGMENT_SET"):
        evaluate_structural_aha(
            ablated, grounding_bundle=bundle, run_id="RUN-1", candidate_id="CAND-1", candidate_sha256="a" * 64,
        )
    unavailable = evaluate_structural_aha(
        None, grounding_bundle=bundle, run_id="RUN-1", candidate_id="CAND-1", candidate_sha256="a" * 64,
    )
    assert unavailable["status"] == unavailable["disposition"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "mode",
    (
        "segments_null",
        "donors_object",
        "mappings_string",
        "nodes_null",
        "relation_scalar",
        "node_map_list",
        "relation_map_list",
        "invariant_map_list",
        "disanalogy_object",
        "scale_transform_object",
    ),
)
def test_structural_aha_malformed_nested_collections_fail_as_validation_errors(
    mode: str,
) -> None:
    bundle = build_grounding_bundle(source_bytes())
    case = aha_case(bundle)
    if mode == "segments_null":
        case["grounding_segments"] = None
    elif mode == "donors_object":
        case["donors"] = {}
    elif mode == "mappings_string":
        case["mappings"] = "mapping"
    elif mode == "nodes_null":
        case["target"]["nodes"] = None
    elif mode == "relation_scalar":
        case["target"]["relations"] = [None]
    elif mode == "node_map_list":
        case["mappings"][0]["node_map"] = []
    elif mode == "relation_map_list":
        case["mappings"][0]["relation_map"] = []
    elif mode == "invariant_map_list":
        case["mappings"][0]["invariant_map"] = []
    elif mode == "disanalogy_object":
        case["mappings"][0]["disanalogies"] = [{}]
    else:
        case["mappings"][0]["declared_scale_or_unit_transformations"] = {}
    with pytest.raises(
        ValidationError,
        match="ARRAY_REQUIRED|OBJECT_REQUIRED|TEXT_MAP_REQUIRED|NONEMPTY_TEXT_REQUIRED",
    ):
        evaluate_structural_aha(
            case,
            grounding_bundle=bundle,
            run_id="RUN-1",
            candidate_id="CAND-1",
            candidate_sha256="a" * 64,
        )


def test_counterexample_and_aperture_noncompensatory_hard_gates() -> None:
    bundle = build_grounding_bundle(source_bytes(counterexample=True))
    candidate = {
        "candidate_sha256": "a" * 64, "source_sha256": bundle["manifest"]["source_sha256"],
        "unsupported_claim_ids": ["CL-1"],
    }
    findings = search_counterexamples(
        candidate, bundle, run_id="RUN-1", candidate_id="CAND-1", candidate_sha256="a" * 64,
    )
    assert {row["kind"] for row in findings["findings"]} == {
        "UNSUPPORTED_CLAIM", "SOURCE_LIMITATION_OR_COUNTEREVIDENCE_MARKER",
    }
    projector = {"disposition": "PASS_SCREEN"}
    residual = {"refusal": {"triggered": False}}
    aha = {"disposition": "REVIEWABLE", "status": "AVAILABLE"}
    clear = {"unresolved_count": 0}
    passed = decide_aperture(
        run_id="RUN-1", candidate_id="CAND-1", projector=projector, residual_refusal=residual,
        aha_result=aha, counterexamples=clear, task_consent=True, privacy_policy_satisfied=True,
        retention_requested=False, retention_consent=False,
    )
    assert passed["decision"] == "PASS_SCREEN"
    refused = decide_aperture(
        run_id="RUN-1", candidate_id="CAND-1", projector=projector, residual_refusal=residual,
        aha_result=aha, counterexamples=clear, task_consent=True, privacy_policy_satisfied=True,
        retention_requested=True, retention_consent=False,
    )
    assert refused["decision"] == "REFUSE"
    assert refused["hard_gates"]["retention_gate_satisfied"] is False


def test_waveform_is_synthetic_nonphysical_receipt() -> None:
    receipt = encode_reference_waveform(dict.fromkeys(AXES, 0.5), sample_count=32)
    assert receipt["physical_frequency_claim"] is False
    assert receipt["cross_domain_utility_established"] is False
    assert receipt["synthetic_reference_only"] is True
    assert len(receipt["samples"]) == 32


def test_tel_deterministic_order_schema_and_failure_preservation() -> None:
    first, second = TELLedger("RUN-1"), TELLedger("RUN-1")
    for ledger in (first, second):
        for name in SEALED_ROUTE_ORDER:
            rank = SEALED_ROUTE_ORDER.index(name)
            ledger.emit(
                name,
                outcome="RECORDED",
                payload={"stage": name},
                candidate_id="CAND-1" if rank >= SEALED_ROUTE_ORDER.index("CANDIDATE_CANONICALIZED") else None,
                audit_id="AUDIT-1" if rank >= SEALED_ROUTE_ORDER.index("SOPHIA_AUDIT_REQUESTED") else None,
                decision_id="DECISION-1" if rank >= SEALED_ROUTE_ORDER.index("HUMAN_DECISION_PENDING") else None,
            )
    assert first.to_jsonl_bytes() == second.to_jsonl_bytes()
    immutable_bytes = first.to_jsonl_bytes()
    exposed = first.rows[0]
    exposed["payload"]["stage"] = "MUTATED"
    assert first.to_jsonl_bytes() == immutable_bytes
    returned_ledger = TELLedger("RUN-returned")
    returned = returned_ledger.emit("REQUEST_CANONICALIZED", payload={"nested": {"value": 1}})
    returned["payload"]["nested"]["value"] = 2
    assert returned_ledger.rows[0]["payload"]["nested"]["value"] == 1
    assert parse_final_route_tel_jsonl(first.to_jsonl_bytes()).rows == first.rows
    with pytest.raises(ValidationError, match="TEL_JSONL_NOT_CANONICAL"):
        parse_tel_jsonl(first.to_jsonl_bytes().rstrip(b"\n"))
    with pytest.raises(ValidationError, match="TEL_JSONL_NOT_CANONICAL"):
        parse_tel_jsonl(b" " + first.to_jsonl_bytes())
    jsonschema.validate(first.rows[0], schema("tel_event.v1.schema.json"))
    sealed_raw = first.to_jsonl_bytes()
    continued_raw = build_human_decision_continuation(
        sealed_raw,
        decision_receipt_sha256="d" * 64,
        disposition="APPROVE",
        external_receipt_path="human_decisions/DECISION-1/human_review_decision.json",
    )
    continued = parse_final_route_tel_jsonl(continued_raw)
    assert tuple(row["event_type"] for row in continued.rows) == EVENT_ORDER
    jsonschema.validate(continued.rows[-1], schema("tel_event.v1.schema.json"))
    mutated = copy.deepcopy(continued.rows[-1])
    mutated["payload"]["parent_sealed_tel_sha256"] = "e" * 64
    rows = [*continued.rows[:-1], mutated]
    with pytest.raises(ValidationError, match="PARENT_SEALED"):
        parse_final_route_tel_jsonl(b"".join(canonical_json_bytes(row) for row in rows))
    lineage_mutation = copy.deepcopy(first.rows)
    lineage_mutation[4]["candidate_id"] = "CAND-2"
    with pytest.raises(ValidationError, match="CANDIDATE_ID_LINEAGE_MISMATCH"):
        parse_final_route_tel_jsonl(
            b"".join(canonical_json_bytes(row) for row in lineage_mutation)
        )
    premature = TELLedger("RUN-P")
    with pytest.raises(ValidationError, match="CANDIDATE_ID_STAGE_BINDING_INVALID"):
        premature.emit("REQUEST_CANONICALIZED", candidate_id="CAND-early")
    assert derive_audit_id("a" * 64, "b" * 64) == "AUDIT-" + sha256_bytes(("a" * 64 + "b" * 64).encode())[:24]
    failure = TELLedger("RUN-F")
    failure.emit("REQUEST_CANONICALIZED")
    failure.failure("grounding", "GROUNDING_INVALID")
    with pytest.raises(ValidationError):
        failure.emit("GROUNDING_VERIFIED")


def test_pmr_separate_consent_revoke_correct_delete_and_never_train() -> None:
    consent = build_consent_packet(
        consent_id="CONSENT-1", run_id="RUN-1", candidate_id="CAND-1", logical_time="T0", decision="GRANT",
    )
    jsonschema.validate(consent, schema("pmr_consent.v1.schema.json"))
    store = PMRReferenceStore()
    store.apply_consent(consent)
    retained_event = store.retain_reference(
        consent_id="CONSENT-1", lineage_id="LINEAGE-1",
        artifact_sha256="a" * 64, referenced_bytes=20,
    )
    retained_before = copy.deepcopy(retained_event)
    store.correct("CONSENT-1", "LINEAGE-1", replacement_sha256="b" * 64)
    assert retained_event == retained_before
    exposed_events = store.events
    exposed_events[1]["detail"]["corrections"].append("c" * 64)
    assert store.events[1]["detail"]["corrections"] == []
    assert store.retrieve("LINEAGE-1", logical_time="T1")["artifact_sha256"] == "b" * 64
    store.delete("CONSENT-1", "LINEAGE-1", reason="USER_DELETE")
    with pytest.raises(ValidationError, match="ACTIVE_LINEAGE"):
        store.retrieve("LINEAGE-1", logical_time="T2")
    store.revoke("CONSENT-1", reason="USER_REVOKE")
    with pytest.raises(ValidationError, match="ACTIVE_CONSENT"):
        store.retrieve("LINEAGE-1", logical_time="T3")
    receipt = store.receipt("CONSENT-1")
    assert receipt["persistent_bytes_written"] == 0
    assert receipt["training_used"] is False
    assert all(row["training_used"] is False for row in receipt["events"])
    with pytest.raises(ValidationError, match="ACTIVE_CONSENT"):
        store.retain_reference(consent_id="CONSENT-1", lineage_id="LINEAGE-2", artifact_sha256="c" * 64, referenced_bytes=1)
    assert no_write_receipt(run_id="R", candidate_id="C", logical_time="T", reason="NO_CONSENT")["retained"] is False

    expiring = build_consent_packet(
        consent_id="CONSENT-EXP", run_id="RUN-1", candidate_id="CAND-1",
        logical_time="2026-08-22T00:00:00Z", expires_logical_time="2026-08-22T01:00:00Z",
        decision="GRANT",
    )
    expiring_store = PMRReferenceStore()
    expiring_store.apply_consent(expiring)
    expiring_store.retain_reference(
        consent_id="CONSENT-EXP", lineage_id="LINEAGE-EXP", artifact_sha256="d" * 64,
        referenced_bytes=1,
    )
    assert expiring_store.retrieve(
        "LINEAGE-EXP", logical_time="2026-08-22T00:59:59Z"
    )["active_consent_verified"] is True
    with pytest.raises(ValidationError, match="CONSENT_EXPIRED"):
        expiring_store.retrieve("LINEAGE-EXP", logical_time="2026-08-22T01:00:00Z")
    with pytest.raises(ValidationError, match="EXPIRY_NOT_AFTER"):
        build_consent_packet(
            consent_id="CONSENT-BAD", run_id="RUN-1", candidate_id="CAND-1",
            logical_time="2026-08-22T01:00:00Z", expires_logical_time="2026-08-22T01:00:00Z",
            decision="GRANT",
        )
    nanosecond_consent = build_consent_packet(
        consent_id="CONSENT-NS", run_id="RUN-1", candidate_id="CAND-1",
        logical_time="2026-08-22T00:00:00.000000001Z",
        expires_logical_time="2026-08-22T00:00:00.000000002Z",
        decision="GRANT",
    )
    nanosecond_store = PMRReferenceStore()
    nanosecond_store.apply_consent(nanosecond_consent)
    nanosecond_store.retain_reference(
        consent_id="CONSENT-NS", lineage_id="LINEAGE-NS",
        artifact_sha256="e" * 64, referenced_bytes=1,
    )
    assert nanosecond_store.retrieve(
        "LINEAGE-NS", logical_time="2026-08-22T00:00:00.000000001Z"
    )["active_consent_verified"] is True
    with pytest.raises(ValidationError, match="CONSENT_EXPIRED"):
        nanosecond_store.retrieve(
            "LINEAGE-NS", logical_time="2026-08-22T00:00:00.000000002Z"
        )


def test_optional_plugin_output_and_effects_fail_closed() -> None:
    disabled = disabled_plugin_receipt("atlas_432")
    assert tuple(disabled["declared_effects"]) == EFFECT_KEYS
    assert tuple(disabled["observed_effects"]) == EFFECT_KEYS
    validate_plugin_receipt(disabled)
    unsafe = copy.deepcopy(disabled)
    unsafe["observed_effects"]["network"] = True
    with pytest.raises(ValidationError, match="EFFECT"):
        validate_plugin_receipt(unsafe)
    missing = copy.deepcopy(disabled)
    del missing["declared_effects"]["publication"]
    with pytest.raises(ValidationError, match="KEYS"):
        validate_plugin_receipt(missing)
    extra = copy.deepcopy(disabled)
    extra["observed_effects"]["undeclared_effect"] = False
    with pytest.raises(ValidationError, match="KEYS"):
        validate_plugin_receipt(extra)
    payload = {
        **disabled, "status": "EXECUTED", "output_schema": "plugin.output.v1",
        "output": {"schema_id": "plugin.output.v1", "payload": {"x": [{"scene_prompt": "draw"}]}, "authority_effect": "NONE"},
    }
    payload["output_sha256"] = sha256_json(payload["output"])
    with pytest.raises(ValidationError, match="PROMPT"):
        validate_plugin_receipt(payload, execution_authorized=True)


def test_build_core_lexical_only_refusal_is_offline_nonauthoritative_and_exactly_replayable(tmp_path: Path) -> None:
    run = build_run(tmp_path)
    receipt = json.loads((run / "build_core_receipt.json").read_text())
    plugin_catalog = json.loads((run / "optional_plugin_receipts.json").read_text())
    assert validate_disabled_plugin_catalog(plugin_catalog) == plugin_catalog
    assert all(
        plugin_receipt[effect_map] == dict.fromkeys(EFFECT_KEYS, False)
        for plugin_receipt in plugin_catalog["receipts"]
        for effect_map in ("declared_effects", "observed_effects")
    )
    assert receipt["aperture"] == "REFUSE"
    assert receipt["sophia_status"] == "REQUESTED_NOT_EXECUTED"
    assert receipt["human_decision"] == "PENDING"
    assert not any(receipt[name] for name in (
        "network_used", "provider_invoked", "memory_written", "training_used",
        "publication_performed", "deployment_performed", "release_performed",
    ))
    candidate = json.loads((run / "candidate_packet.json").read_text())
    assert candidate["candidate_not_final_answer"] is True
    prefix_raw = (run / "tel_audit_prefix.jsonl").read_bytes()
    assert (run / "tel_events.jsonl").read_bytes() == prefix_raw
    tel = parse_tel_jsonl(prefix_raw)
    assert tuple(row["event_type"] for row in tel.rows) == AUDIT_PREFIX_ORDER
    replay = replay_core(run)
    assert replay["valid"] is True
    assert replay["differences"] == []


def test_build_core_explicit_aha_unavailable_and_counterexample_refuse(tmp_path: Path) -> None:
    run = build_run(tmp_path / "a", with_aha=False)
    assert json.loads((run / "aha_result.json").read_text())["status"] == "UNAVAILABLE"
    assert json.loads((run / "aperture_decision.json").read_text())["decision"] == "REFUSE"
    counter = build_run(tmp_path / "b", with_aha=True, counterexample=True)
    assert json.loads((counter / "counterexamples.json").read_text())["unresolved_count"] > 0
    assert json.loads((counter / "aperture_decision.json").read_text())["decision"] == "REFUSE"


@pytest.mark.parametrize("meta", [{}, {"privacy_policy_satisfied": "yes", "privacy_basis": "local"}, {"privacy_policy_satisfied": True}])
def test_build_core_missing_privacy_evidence_emits_only_bounded_failure_output(tmp_path: Path, meta: dict) -> None:
    source = source_bytes()
    request = request_value(source)
    request["meta"] = meta
    output = tmp_path / "run"
    with pytest.raises(ValidationError, match="PRIVACY"):
        build_core_from_inputs(
            request_bytes=canonical_json_bytes(request), source_bytes=source,
            captured_bytes=canonical_json_bytes(capture_value()), output_dir=output,
        )
    failure = verify_failure_output(output)
    assert failure["stage"] == "aperture_decision"
    assert failure["success_artifacts_emitted"] is False


def test_build_core_rejects_grounding_manifest_hash_substitution(tmp_path: Path) -> None:
    source = source_bytes()
    request = request_value(source)
    request["grounding"][0]["bundle_manifest_sha256"] = "f" * 64
    output = tmp_path / "run"
    with pytest.raises(ValidationError, match="GROUNDING_MANIFEST_SHA256_MISMATCH"):
        build_core_from_inputs(
            request_bytes=canonical_json_bytes(request), source_bytes=source,
            captured_bytes=canonical_json_bytes(capture_value()), output_dir=output,
        )
    failure = verify_failure_output(output)
    assert failure["stage"] == "grounding_binding"
    assert failure["reason_code"] == "BUILD_REQUEST_GROUNDING_MANIFEST_SHA256_MISMATCH"


def test_core_manifest_rejects_unlisted_pre_audit_files_and_casefold_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra_run = build_run(tmp_path / "extra")
    (extra_run / "unlisted-pre-audit.txt").write_text(
        "not part of the immutable core inventory\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(ValidationError, match="SCOPED_INVENTORY_MISMATCH"):
        verify_core_manifest_contract(extra_run)

    collision_run = build_run(tmp_path / "collision")
    manifest_path = collision_run / "core_manifest.json"
    manifest = strict_json_loads(manifest_path.read_bytes())
    duplicate = dict(manifest["artifacts"][0])
    duplicate["path"] = duplicate["path"].upper()
    manifest["artifacts"].append(duplicate)
    manifest["artifacts"].sort(key=lambda row: row["path"])
    manifest["artifact_count"] += 1
    manifest["artifact_bytes"] += duplicate["bytes"]
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    with monkeypatch.context() as collision_context:
        collision_context.setattr(
            seal_module,
            "sha256_file",
            lambda _path: pytest.fail(
                "artifact hashing occurred before namespace collision rejection"
            ),
        )
        with pytest.raises(ValidationError, match="CASEFOLD_PATH_COLLISION"):
            verify_core_manifest_contract(collision_run)

    typed_run = build_run(tmp_path / "aggregate-type")
    typed_manifest_path = typed_run / "core_manifest.json"
    typed_manifest = strict_json_loads(typed_manifest_path.read_bytes())
    typed_manifest["artifact_count"] = float(typed_manifest["artifact_count"])
    typed_manifest_path.write_bytes(canonical_json_bytes(typed_manifest))
    with pytest.raises(ValidationError, match="COUNT_OR_BYTES_MISMATCH"):
        verify_core_manifest_contract(typed_run)

    for label, reserved_path in (
        ("reserved-case", "Checksums.sha256"),
        ("dot-path", "."),
    ):
        reserved_run = build_run(tmp_path / label)
        reserved_manifest_path = reserved_run / "core_manifest.json"
        reserved_manifest = strict_json_loads(reserved_manifest_path.read_bytes())
        row = dict(reserved_manifest["artifacts"][0])
        row["path"] = reserved_path
        reserved_manifest["artifacts"] = [row]
        reserved_manifest["artifact_count"] = 1
        reserved_manifest["artifact_bytes"] = row["bytes"]
        reserved_manifest_path.write_bytes(canonical_json_bytes(reserved_manifest))
        with monkeypatch.context() as reserved_context:
            reserved_context.setattr(
                seal_module,
                "sha256_file",
                lambda _path: pytest.fail(
                    "artifact hashing occurred before reserved path rejection"
                ),
            )
            with pytest.raises(ValidationError, match="CORE_MANIFEST_PATH_INVALID"):
                verify_core_manifest_contract(reserved_run)

    missing_run = build_run(tmp_path / "missing")
    missing_manifest = strict_json_loads(
        (missing_run / "core_manifest.json").read_bytes()
    )
    missing_relative = missing_manifest["artifacts"][0]["path"]
    (missing_run / missing_relative).unlink()
    with pytest.raises(
        ValidationError,
        match=f"CORE_MANIFEST_ARTIFACT_MISMATCH:{re.escape(missing_relative)}",
    ):
        verify_core_manifest_contract(missing_run)


def test_grounding_manifest_cli_supports_pre_request_hash_binding(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    source = tmp_path / "source.md"
    source.write_bytes(source_bytes())
    assert totality_cli(["grounding-manifest", "--source", str(source)]) == 0
    manifest_bytes = capsysbinary.readouterr().out
    manifest = strict_json_loads(manifest_bytes)
    assert manifest_bytes == canonical_json_bytes(manifest)
    request = request_value(source.read_bytes())
    assert request["grounding"][0]["bundle_manifest_sha256"] == sha256_bytes(manifest_bytes)


def test_cli_subprocess_stdout_and_stderr_are_exact_canonical_lf_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_bytes(source_bytes())
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "python" / "src")}
    success = subprocess.run(
        [
            sys.executable, "-m", "coherence.totality.cli", "grounding-manifest",
            "--source", str(source),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert success.returncode == 0 and success.stderr == b""
    assert success.stdout.endswith(b"\n") and b"\r" not in success.stdout
    assert success.stdout == canonical_json_bytes(strict_json_loads(success.stdout))
    failure = subprocess.run(
        [
            sys.executable, "-m", "coherence.totality.cli", "grounding-manifest",
            "--source", str(tmp_path / "missing.md"),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert failure.returncode == 2 and failure.stdout == b""
    assert failure.stderr.endswith(b"\n") and b"\r" not in failure.stderr
    assert failure.stderr == canonical_json_bytes(strict_json_loads(failure.stderr))


def test_build_core_cli_preserves_pre_read_and_optional_parse_failures(tmp_path: Path) -> None:
    source_raw = source_bytes()
    source = tmp_path / "source.md"
    capture = tmp_path / "captured.json"
    request = tmp_path / "request.json"
    source.write_bytes(source_raw)
    capture.write_bytes(canonical_json_bytes(capture_value()))
    request.write_bytes(canonical_json_bytes(request_value(source_raw)))
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "python" / "src")}

    missing_output = tmp_path / "missing-input-failure"
    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "coherence.totality.cli",
            "build-core",
            "--source",
            str(source),
            "--task",
            str(tmp_path / "missing-request.json"),
            "--captured",
            str(capture),
            "--out",
            str(missing_output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 2
    missing_receipt = verify_failure_output(missing_output)
    assert missing_receipt["reason_code"] == "BUILD_REQUEST_INPUT_UNAVAILABLE"
    assert missing_receipt["stage"] == "request_validation"

    oversized_request = tmp_path / "oversized-request.json"
    with oversized_request.open("wb") as stream:
        stream.truncate(MAX_REQUEST_BYTES + 1)
    oversized_output = tmp_path / "oversized-input-failure"
    oversized = subprocess.run(
        [
            sys.executable,
            "-m",
            "coherence.totality.cli",
            "build-core",
            "--source",
            str(source),
            "--task",
            str(oversized_request),
            "--captured",
            str(capture),
            "--out",
            str(oversized_output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert oversized.returncode == 2
    oversized_receipt = verify_failure_output(oversized_output)
    assert oversized_receipt["reason_code"] == "BUILD_REQUEST_INPUT_LIMIT_EXCEEDED"

    malformed_aha = tmp_path / "aha.json"
    malformed_aha.write_bytes(b"[]\n")
    malformed_output = tmp_path / "malformed-optional-failure"
    malformed = subprocess.run(
        [
            sys.executable,
            "-m",
            "coherence.totality.cli",
            "build-core",
            "--source",
            str(source),
            "--task",
            str(request),
            "--captured",
            str(capture),
            "--aha-case",
            str(malformed_aha),
            "--out",
            str(malformed_output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert malformed.returncode == 2
    malformed_receipt = verify_failure_output(malformed_output)
    assert malformed_receipt["reason_code"] == "BUILD_AHA_CASE_INPUT_INVALID"
    assert malformed_receipt["stage"] == "aha_evaluation"

    nested_aha = tmp_path / "nested-aha.json"
    nested_case = aha_case(build_grounding_bundle(source_raw))
    nested_case["grounding_segments"] = None
    nested_aha.write_bytes(canonical_json_bytes(nested_case))
    nested_output = tmp_path / "nested-optional-failure"
    nested = subprocess.run(
        [
            sys.executable,
            "-m",
            "coherence.totality.cli",
            "build-core",
            "--source",
            str(source),
            "--task",
            str(request),
            "--captured",
            str(capture),
            "--aha-case",
            str(nested_aha),
            "--out",
            str(nested_output),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    assert nested.returncode == 2
    nested_receipt = verify_failure_output(nested_output)
    assert nested_receipt["reason_code"] == "AHA_CASE_INVALID"
    assert nested_receipt["stage"] == "aha_evaluation"


def test_genuine_quarantine_stage_failure_is_preserved_and_replayable(tmp_path: Path) -> None:
    source = source_bytes()
    output = tmp_path / "failed-run"
    with pytest.raises(ValidationError, match="LIMIT_EXCEEDED"):
        build_core_from_inputs(
            request_bytes=canonical_json_bytes(request_value(source)), source_bytes=source,
            captured_bytes=b"x" * (MAX_RAW_OUTPUT_BYTES + 1), output_dir=output,
        )
    failure = verify_failure_output(output)
    assert failure["stage"] == "sonya_quarantine"
    assert not (output / "sonya/raw_output.quarantine").exists()
    assert tuple(row["event_type"] for row in parse_tel_jsonl((output / "tel_events.jsonl").read_bytes()).rows) == ("STAGE_FAILED",)
    replay = replay_core(output)
    assert replay["valid"] is True and replay["failure_preserved"] is True
    (output / "tel_events.jsonl").write_bytes(b"{}\n")
    with pytest.raises(ValidationError):
        verify_failure_output(output)


def test_replay_receipt_cannot_be_written_inside_run_root(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    run = build_run(tmp_path)
    receipt = run / "replay_receipt.json"
    assert totality_cli(
        ["replay", "--run-root", str(run), "--receipt", str(receipt)]
    ) == 2
    captured = capsysbinary.readouterr()
    assert captured.out == b""
    assert b"REPLAY_RECEIPT_INSIDE_RUN_ROOT_PROHIBITED" in captured.err
    assert not receipt.exists()


def test_repository_identity_fails_dirty_unless_explicit_and_records_status_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **kwargs):
        if "status" in args:
            return SimpleNamespace(returncode=0, stdout=b" M components/CoherenceLattice/file.py\x00")
        return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")

    monkeypatch.setattr(totality_cli_module.subprocess, "run", fake_run)
    with pytest.raises(OperationalError, match="WORKTREE_DIRTY"):
        repository_identity(tmp_path)
    identity = repository_identity(tmp_path, allow_dirty=True)
    assert identity["worktree_clean"] is False
    assert identity["status_sha256"] == sha256_bytes(b" M components/CoherenceLattice/file.py\x00")


def test_tel_finalization_preserves_prefix_is_idempotent_and_replays_core(tmp_path: Path) -> None:
    run = build_run(tmp_path)
    prefix = (run / "tel_audit_prefix.jsonl").read_bytes()
    core_manifest = (run / "core_manifest.json").read_bytes()
    write_external_packets(run)
    receipt = finalize_route_tel(run)
    jsonschema.validate(receipt, schema("tel_finalization_receipt.v1.schema.json"))
    assert (run / "tel_audit_prefix.jsonl").read_bytes() == prefix
    assert (run / "core_manifest.json").read_bytes() == core_manifest
    manifest = strict_json_loads(core_manifest)
    assert manifest["manifest_scope"] == "IMMUTABLE_CORE_BUILD_BEFORE_EXTERNAL_AUDIT"
    assert "tel_events.jsonl" in manifest["post_core_artifacts_excluded"]
    assert "tel_finalization_receipt.json" in manifest["post_core_artifacts_excluded"]
    assert tuple(
        row["event_type"] for row in parse_final_route_tel_jsonl((run / "tel_events.jsonl").read_bytes()).rows
    ) == SEALED_ROUTE_ORDER
    assert receipt == finalize_route_tel(run)
    assert receipt["tel_audit_prefix_sha256"] == sha256_bytes(prefix)
    assert replay_core(run)["valid"] is True
    sophia = strict_json_loads((run / "sophia_audit_packet.json").read_bytes())
    sophia["disposition"] = "HOLD"
    (run / "sophia_audit_packet.json").write_bytes(canonical_json_bytes(sophia))
    with pytest.raises(ValidationError, match="IDENTITY_OR_(DISPOSITION|POSTURE)|RECEIPT_CONFLICT"):
        finalize_route_tel(run)


def test_tel_finalization_rejects_positive_atlas_authority(tmp_path: Path) -> None:
    run = build_run(tmp_path)
    write_external_packets(run)
    atlas_path = run / "atlas_posture_packet.json"
    atlas = strict_json_loads(atlas_path.read_bytes())
    atlas["nonauthority"]["publication"] = True
    atlas_path.write_bytes(canonical_json_bytes(atlas))
    with pytest.raises(ValidationError, match="ATLAS_POSITIVE_AUTHORITY_OR_EFFECT"):
        finalize_route_tel(run)


def test_ui_compatible_seal_manifest_checksum_tamper_and_deterministic_zip(tmp_path: Path) -> None:
    run = build_run(tmp_path)
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text("<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n")
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {"coherence_lattice": "c" * 40, "sophia": "d" * 40, "uvlm_publications": "e" * 40},
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    manifest = seal_run(run, repository_identity=identity)
    assert manifest["repository_identity"] == identity
    assert (run / "sealed_artifact_manifest.json").is_file()
    assert verify_sealed_run(run)["valid"] is True
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    build_deterministic_zip(run, first)
    build_deterministic_zip(run, second)
    assert first.read_bytes() == second.read_bytes()
    assert (first.with_name(first.name + ".sha256")).read_bytes() == (
        f"{sha256_bytes(first.read_bytes())}  {first.name}\n".encode("utf-8")
    )
    assert verify_zip_sidecar(first)["valid"] is True
    first.with_name(first.name + ".sha256").write_text(
        f"{'0' * 64}  {first.name}\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(ValidationError, match="ZIP_SIDECAR_MISMATCH"):
        verify_zip_sidecar(first)
    (run / "final_review.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValidationError, match="INVENTORY|COVERAGE"):
        verify_sealed_run(run)


def test_seal_rejects_coherently_rebuilt_core_without_aegis_admission(
    tmp_path: Path,
) -> None:
    run = build_run(tmp_path)
    request = strict_json_loads((run / "request.json").read_bytes())
    (run / "aegis_admission_packet.json").unlink()
    (run / "core_manifest.json").write_bytes(
        canonical_json_bytes(
            build_core_manifest(
                run,
                run_id=request["run_id"],
                logical_time=request["logical_time"],
            )
        )
    )
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n"
    )
    identity = {
        "repository": "TriadicGate",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True,
        "status_sha256": sha256_bytes(b""),
    }
    with pytest.raises(
        ValidationError,
        match="SEAL_REQUIRED_ARTIFACTS_MISSING|SEAL_REQUIRED_ARTIFACT_MISSING_OR_UNSAFE",
    ):
        seal_run(run, repository_identity=identity)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("effectful", "PLUGIN_EFFECT_NOT_ALLOWED"),
        ("missing_effect_key", "MISSING_KEYS"),
        ("extra_effect_key", "EXTRA_KEYS"),
        ("missing_receipt", "OPTIONAL_PLUGIN_CATALOG_COVERAGE_INVALID"),
        ("extra_receipt", "OPTIONAL_PLUGIN_CATALOG_COVERAGE_INVALID"),
    ],
)
def test_seal_rejects_coherently_rebuilt_invalid_optional_plugin_catalog(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    run = build_run(tmp_path / mutation)
    write_external_packets(run)
    finalize_route_tel(run)

    catalog_path = run / "optional_plugin_receipts.json"
    catalog = strict_json_loads(catalog_path.read_bytes())
    if mutation == "effectful":
        catalog["receipts"][0]["observed_effects"]["federation"] = True
    elif mutation == "missing_effect_key":
        del catalog["receipts"][0]["declared_effects"]["truth_certification"]
    elif mutation == "extra_effect_key":
        catalog["receipts"][0]["observed_effects"]["undeclared_effect"] = False
    elif mutation == "missing_receipt":
        catalog["receipts"].pop()
    else:
        catalog["receipts"].append(copy.deepcopy(catalog["receipts"][0]))
    catalog_path.write_bytes(canonical_json_bytes(catalog))

    request = strict_json_loads((run / "request.json").read_bytes())
    (run / "core_manifest.json").write_bytes(
        canonical_json_bytes(
            build_core_manifest(
                run,
                run_id=request["run_id"],
                logical_time=request["logical_time"],
            )
        )
    )
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n",
        encoding="utf-8",
        newline="\n",
    )
    repository = {
        "repository": "TriadicGate",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True,
        "status_sha256": sha256_bytes(b""),
    }
    with pytest.raises(ValidationError, match=reason):
        seal_run(run, repository_identity=repository)
    assert not any(
        (run / name).exists()
        for name in (
            "sealed_artifact_manifest.json",
            "run_manifest.json",
            "checksums.sha256",
        )
    )


def test_seal_rejects_coherently_resealed_atlas_cross_component_identity(
    tmp_path: Path,
) -> None:
    run = build_run(tmp_path)
    sophia, atlas = write_external_packets(run)
    receipt = finalize_route_tel(run)
    atlas["run_id"] = "RUN-FORGED-CROSS-COMPONENT"
    atlas_raw = canonical_json_bytes(atlas)
    (run / "atlas_posture_packet.json").write_bytes(atlas_raw)

    prefix_raw = (run / "tel_audit_prefix.jsonl").read_bytes()
    ledger = TELLedger(receipt["run_id"], parse_tel_jsonl(prefix_raw).rows)
    identity = (
        receipt["candidate_id"],
        receipt["audit_id"],
        receipt["decision_id"],
    )
    ledger.emit(
        "SOPHIA_AUDIT_COMPLETED",
        outcome={"PASS": "SUCCESS", "HOLD": "HOLD", "REJECT": "REFUSE"}[
            sophia["disposition"]
        ],
        candidate_id=identity[0],
        audit_id=identity[1],
        decision_id=identity[2],
        payload={
            "sophia_audit_packet_sha256": receipt[
                "sophia_audit_packet_sha256"
            ],
            "disposition": sophia["disposition"],
        },
    )
    ledger.emit(
        "ATLAS_ORIENTATION_COMPLETED",
        outcome="RECORDED",
        candidate_id=identity[0],
        audit_id=identity[1],
        decision_id=identity[2],
        payload={
            "atlas_posture_packet_sha256": sha256_bytes(atlas_raw),
            "human_decision": "PENDING",
        },
    )
    ledger.emit(
        "ROUTE_COMPLETED_HUMAN_PENDING",
        outcome="RECORDED",
        candidate_id=identity[0],
        audit_id=identity[1],
        decision_id=identity[2],
        payload={
            "tel_audit_prefix_sha256": receipt["tel_audit_prefix_sha256"],
            "external_human_decision_receipt_required": True,
            "human_decision": "PENDING",
        },
    )
    tel_raw = ledger.to_jsonl_bytes()
    (run / "tel_events.jsonl").write_bytes(tel_raw)
    receipt["atlas_posture_packet_sha256"] = sha256_bytes(atlas_raw)
    receipt["tel_events_sha256"] = sha256_bytes(tel_raw)
    (run / "tel_finalization_receipt.json").write_bytes(canonical_json_bytes(receipt))
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n"
    )
    repository = {
        "repository": "TriadicGate",
        "commit": "a" * 40,
        "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True,
        "status_sha256": sha256_bytes(b""),
    }
    with pytest.raises(
        ValidationError, match="SEAL_TEL_CROSS_COMPONENT_PARENT_BINDING_INVALID"
    ):
        seal_run(run, repository_identity=repository)


def test_inventory_rejects_directory_junction_before_external_file_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bounded"
    external = tmp_path / "external"
    root.mkdir()
    external.mkdir()
    secret = external / "secret.txt"
    secret.write_text("must not be inventoried", encoding="utf-8")
    make_directory_link(root / "linked", external)
    original_open = Path.open

    def reject_external_open(path: Path, *args, **kwargs):
        if path.resolve(strict=False) == secret.resolve(strict=True):
            raise AssertionError("external junction member was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_external_open)
    with pytest.raises(ValidationError, match="LINK_OR_PATH_ESCAPE"):
        inventory_files(root)


def test_public_grounding_seal_and_replay_reads_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    grounding_dir = tmp_path / "grounding-bounded"
    write_grounding_bundle(build_grounding_bundle(source_bytes()), grounding_dir)
    grounding_manifest = grounding_dir / "manifest.json"
    with grounding_manifest.open("wb") as stream:
        stream.truncate(2 * 1024 * 1024 + 1)

    run = build_run(tmp_path / "seal-bounded")
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n",
    )
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    seal_run(run, repository_identity=identity)
    run_manifest = run / "run_manifest.json"
    with run_manifest.open("wb") as stream:
        stream.truncate(seal_module.MAX_SEAL_JSON_BYTES + 1)

    protected = {grounding_manifest.resolve(), run_manifest.resolve()}
    original_open = Path.open

    def reject_oversized_open(path: Path, *args, **kwargs):
        if path.resolve(strict=False) in protected:
            raise AssertionError("oversized verifier member was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_oversized_open)
    with pytest.raises(ValidationError, match="GROUNDING_MANIFEST_SIZE_LIMIT"):
        read_grounding_bundle(grounding_dir)
    with pytest.raises(ValidationError, match="RUN_MANIFEST_SIZE_LIMIT"):
        verify_sealed_run(run)
    monkeypatch.setattr(Path, "open", original_open)

    replay_run = build_run(tmp_path / "replay-bounded")
    capture_path = replay_run / "sonya" / "raw_output.quarantine"
    with capture_path.open("wb") as stream:
        stream.truncate(MAX_RAW_OUTPUT_BYTES + 1)
    core_path = replay_run / "core_manifest.json"
    core = strict_json_loads(core_path.read_bytes())
    capture_row = next(
        row for row in core["artifacts"]
        if row["path"] == "sonya/raw_output.quarantine"
    )
    capture_row.update(
        sha256=sha256_file(capture_path),
        bytes=capture_path.stat().st_size,
    )
    core["artifact_bytes"] = sum(row["bytes"] for row in core["artifacts"])
    core_path.write_bytes(canonical_json_bytes(core))
    with pytest.raises(ValidationError, match="CAPTURED_INPUT_LIMIT_EXCEEDED"):
        replay_core(replay_run)


@pytest.mark.parametrize(
    "fault",
    ("run_manifest.json", "checksums.sha256", "final_verify"),
)
def test_seal_transaction_leaves_fail_closed_tombstones_after_any_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    run = build_run(tmp_path / fault.replace(".", "-"))
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n",
    )
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    original_link = seal_module.os.link
    with monkeypatch.context() as scoped:
        if fault == "final_verify":
            def injected_verify(_root: Path) -> dict:
                raise ValidationError("INJECTED_FINAL_VERIFY_FAILURE")

            scoped.setattr(
                seal_module,
                "verify_sealed_run",
                injected_verify,
            )
        else:
            def injected_link(source: Path, destination: Path) -> None:
                if Path(destination).name == fault:
                    raise OSError("injected seal publish failure")
                original_link(source, destination)

            scoped.setattr(seal_module.os, "link", injected_link)
        with pytest.raises((OperationalError, ValidationError)):
            seal_run(run, repository_identity=identity)
    ordered = ("sealed_artifact_manifest.json", "run_manifest.json", "checksums.sha256")
    claimed_count = {
        "sealed_artifact_manifest.json": 0,
        "run_manifest.json": 1,
        "checksums.sha256": 2,
        "final_verify": 3,
    }[fault]
    assert [name for name in ordered if (run / name).exists()] == list(
        ordered[:claimed_count]
    )
    assert not list(run.parent.glob(f".{run.name}.seal-*"))
    if claimed_count:
        with pytest.raises(OperationalError, match="SEAL_ALREADY_EXISTS"):
            seal_run(run, repository_identity=identity)
    else:
        seal_run(run, repository_identity=identity)
        assert verify_sealed_run(run)["valid"] is True


def test_zip_export_mid_member_failure_leaves_no_final_paths_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_run(tmp_path / "zip-fault-run")
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n",
    )
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    seal_run(run, repository_identity=identity)
    output = tmp_path / "faulted.zip"
    original_open = seal_module.zipfile.ZipFile.open
    writes = 0

    def injected_open(archive, name, mode="r", *args, **kwargs):
        nonlocal writes
        if mode == "w":
            writes += 1
            if writes == 2:
                raise OSError("injected mid-member failure")
        return original_open(archive, name, mode, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(seal_module.zipfile.ZipFile, "open", injected_open)
        with pytest.raises(OSError, match="mid-member"):
            build_deterministic_zip(run, output)
    assert not output.exists()
    assert not output.with_name(output.name + ".sha256").exists()
    assert not list(tmp_path.glob(f".{output.name}.build-*"))
    build_deterministic_zip(run, output)
    assert verify_zip_sidecar(output)["valid"] is True


def test_zip_export_publish_failure_leaves_fail_closed_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = build_run(tmp_path / "zip-publish-fault-run")
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text(
        "<!doctype html><title>Review</title>\n", encoding="utf-8", newline="\n",
    )
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    seal_run(run, repository_identity=identity)
    output = tmp_path / "publish-faulted.zip"
    original_link = seal_module.os.link

    def fail_sidecar(source: Path, destination: Path) -> None:
        if Path(destination).name.endswith(".sha256"):
            raise OSError("injected sidecar publish failure")
        original_link(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(seal_module.os, "link", fail_sidecar)
        with pytest.raises(OperationalError, match="ZIP_SIDECAR_PUBLISH_FAILED"):
            build_deterministic_zip(run, output)
    assert output.is_file()
    assert not output.with_name(output.name + ".sha256").exists()
    assert not list(tmp_path.glob(f".{output.name}.build-*"))
    with pytest.raises(OperationalError, match="ZIP_OUTPUT_EXISTS_OR_UNSAFE"):
        build_deterministic_zip(run, output)


def test_seal_binds_canonical_manifests_to_request_candidate_and_tel_identity(
    tmp_path: Path,
) -> None:
    identity = {
        "repository": "TriadicGate", "commit": "a" * 40, "tree": "b" * 40,
        "prefix_trees": {
            "coherence_lattice": "c" * 40,
            "sophia": "d" * 40,
            "uvlm_publications": "e" * 40,
        },
        "worktree_clean": True, "status_sha256": sha256_bytes(b""),
    }
    run = build_run(tmp_path / "identity")
    write_external_packets(run)
    finalize_route_tel(run)
    (run / "final_review.html").write_text("<!doctype html>\n", encoding="utf-8", newline="\n")
    seal_run(run, repository_identity=identity)
    sealed_path, manifest_path = (
        run / "sealed_artifact_manifest.json",
        run / "run_manifest.json",
    )
    sealed = strict_json_loads(sealed_path.read_bytes())
    manifest = strict_json_loads(manifest_path.read_bytes())
    sealed["run_id"] = manifest["run_id"] = "FAKE-RUN"
    sealed_path.write_bytes(canonical_json_bytes(sealed))
    sealed_row = next(
        row for row in manifest["artifacts"]
        if row["path"] == "sealed_artifact_manifest.json"
    )
    sealed_row.update(
        sha256=sha256_bytes(sealed_path.read_bytes()),
        bytes=sealed_path.stat().st_size,
    )
    manifest["artifact_bytes"] = sum(row["bytes"] for row in manifest["artifacts"])
    manifest["sealed_artifact_manifest_sha256"] = sha256_bytes(sealed_path.read_bytes())
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    rows = inventory_files(run, exclude={"checksums.sha256"})
    (run / "checksums.sha256").write_bytes(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in rows).encode("utf-8")
    )
    with pytest.raises(ValidationError, match="CROSS_ARTIFACT_RUN_IDENTITY"):
        verify_sealed_run(run)

    noncanonical = build_run(tmp_path / "noncanonical")
    write_external_packets(noncanonical)
    finalize_route_tel(noncanonical)
    (noncanonical / "final_review.html").write_text("<!doctype html>\n", encoding="utf-8", newline="\n")
    seal_run(noncanonical, repository_identity=identity)
    run_manifest = strict_json_loads((noncanonical / "run_manifest.json").read_bytes())
    (noncanonical / "run_manifest.json").write_bytes(
        json.dumps(run_manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    )
    rows = inventory_files(noncanonical, exclude={"checksums.sha256"})
    (noncanonical / "checksums.sha256").write_bytes(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in rows).encode("utf-8")
    )
    with pytest.raises(ValidationError, match="RUN_MANIFEST_NOT_CANONICAL"):
        verify_sealed_run(noncanonical)
