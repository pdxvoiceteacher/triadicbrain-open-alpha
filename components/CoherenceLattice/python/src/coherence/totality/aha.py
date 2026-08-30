"""Binding wrapper for the existing full structural AHA engine."""

from __future__ import annotations

from typing import Any

from coherence.aha.engine import evaluate_case
from coherence.aha.models import CaseValidationError, validate_case

from .canonical import require_exact_keys, require_identifier, require_sha256, sha256_json
from .errors import ValidationError
from .grounding import validate_grounding_bundle

AHA_RESULT_SCHEMA = "uvlm.coherence.totality.aha_result.v1"


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"ARRAY_REQUIRED:{path}")
    return value


def _require_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"NONEMPTY_TEXT_REQUIRED:{path}")
    return value


def _require_text_list(
    value: Any, path: str, *, allow_empty: bool = False
) -> list[str]:
    rows = _require_list(value, path)
    if not allow_empty and not rows:
        raise ValidationError(f"NONEMPTY_ARRAY_REQUIRED:{path}")
    for index, item in enumerate(rows):
        _require_text(item, f"{path}[{index}]")
    return rows


def _require_text_map(value: Any, path: str, *, allow_empty: bool = False) -> dict[str, str]:
    if not isinstance(value, dict) or (not allow_empty and not value):
        raise ValidationError(f"TEXT_MAP_REQUIRED:{path}")
    for key, item in value.items():
        _require_text(key, f"{path}.<key>")
        _require_text(item, f"{path}.{key}")
    return value


def _exact_case_shape(raw: Any) -> None:
    require_exact_keys(
        raw,
        required={
            "schema_id", "case_id", "question", "grounding_segments", "target", "donors",
            "mappings", "candidate_hypothesis", "falsification_test",
        },
        path="$.aha_case",
    )
    segments = _require_list(raw["grounding_segments"], "$.aha_case.grounding_segments")
    donors = _require_list(raw["donors"], "$.aha_case.donors")
    mappings = _require_list(raw["mappings"], "$.aha_case.mappings")
    _require_text(raw["schema_id"], "$.aha_case.schema_id")
    _require_text(raw["case_id"], "$.aha_case.case_id")
    _require_text(raw["question"], "$.aha_case.question")
    for index, segment in enumerate(segments):
        require_exact_keys(segment, required={"segment_id", "sha256"}, path=f"$.aha_case.grounding_segments[{index}]")
        require_identifier(segment["segment_id"], f"$.aha_case.grounding_segments[{index}].segment_id")
        require_sha256(segment["sha256"], f"$.aha_case.grounding_segments[{index}].sha256")
    graphs = [raw["target"], *donors]
    for graph_index, graph in enumerate(graphs):
        base = f"$.aha_case.graphs[{graph_index}]"
        require_exact_keys(
            graph,
            required={"graph_id", "domain", "source_family_id", "nodes", "relations"},
            path=base,
        )
        nodes = _require_list(graph["nodes"], f"{base}.nodes")
        relations = _require_list(graph["relations"], f"{base}.relations")
        for field in ("graph_id", "domain", "source_family_id"):
            _require_text(graph[field], f"{base}.{field}")
        for index, node in enumerate(nodes):
            require_exact_keys(node, required={"node_id", "node_type", "label", "lineage"}, path=f"{base}.nodes[{index}]")
            for field in ("node_id", "node_type", "label"):
                _require_text(node[field], f"{base}.nodes[{index}].{field}")
            _require_text_list(node["lineage"], f"{base}.nodes[{index}].lineage")
        for index, relation in enumerate(relations):
            require_exact_keys(
                relation,
                required={"relation_id", "relation_type", "source_node_id", "target_node_id", "orientation", "lineage"},
                path=f"{base}.relations[{index}]",
            )
            for field in (
                "relation_id", "relation_type", "source_node_id",
                "target_node_id", "orientation",
            ):
                _require_text(relation[field], f"{base}.relations[{index}].{field}")
            _require_text_list(
                relation["lineage"], f"{base}.relations[{index}].lineage"
            )
    for index, mapping in enumerate(mappings):
        require_exact_keys(
            mapping,
            required={
                "mapping_id", "donor_graph_id", "node_map", "relation_map", "invariant_map",
                "disanalogies", "declared_scale_or_unit_transformations",
            },
            path=f"$.aha_case.mappings[{index}]",
        )
        base = f"$.aha_case.mappings[{index}]"
        _require_text(mapping["mapping_id"], f"{base}.mapping_id")
        _require_text(mapping["donor_graph_id"], f"{base}.donor_graph_id")
        _require_text_map(mapping["node_map"], f"{base}.node_map")
        _require_text_map(mapping["relation_map"], f"{base}.relation_map")
        _require_text_map(
            mapping["invariant_map"], f"{base}.invariant_map", allow_empty=True
        )
        _require_text_list(mapping["disanalogies"], f"{base}.disanalogies")
        _require_text_list(
            mapping["declared_scale_or_unit_transformations"],
            f"{base}.declared_scale_or_unit_transformations",
            allow_empty=True,
        )
    require_exact_keys(
        raw["candidate_hypothesis"],
        required={
            "statement", "target_observable", "intervention_or_condition", "expected_direction",
            "comparator_or_null", "horizon", "confidence_lowering_observation",
        },
        path="$.aha_case.candidate_hypothesis",
    )
    for field, item in raw["candidate_hypothesis"].items():
        _require_text(item, f"$.aha_case.candidate_hypothesis.{field}")
    require_exact_keys(
        raw["falsification_test"],
        required={"test_statement", "primary_outcome", "comparator", "reject_criteria", "feasibility_posture", "risk_posture"},
        path="$.aha_case.falsification_test",
    )
    for field, item in raw["falsification_test"].items():
        _require_text(item, f"$.aha_case.falsification_test.{field}")


def evaluate_structural_aha(
    case: Any | None,
    *,
    grounding_bundle: Any,
    run_id: str,
    candidate_id: str,
    candidate_sha256: str,
) -> dict[str, Any]:
    bundle = validate_grounding_bundle(grounding_bundle)
    base = {
        "schema_id": AHA_RESULT_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "candidate_sha256": require_sha256(candidate_sha256, "$.candidate_sha256"),
        "source_sha256": bundle["manifest"]["source_sha256"],
    }
    if case is None:
        return {
            **base,
            "status": "UNAVAILABLE",
            "disposition": "UNAVAILABLE",
            "reason_codes": ["AHA_CASE_NOT_SUPPLIED"],
            "case_sha256": None,
            "case": None,
            "evaluation": None,
            "authority_effect": "NONE",
        }
    try:
        _exact_case_shape(case)
    except ValidationError as exc:
        raise ValidationError(f"AHA_CASE_INVALID:{exc}") from exc
    bundle_refs = {(row["segment_id"], row["sha256"]) for row in bundle["segments"]}
    case_refs = {(row.get("segment_id"), row.get("sha256")) for row in case["grounding_segments"]}
    if case_refs != bundle_refs:
        raise ValidationError("AHA_GROUNDING_SEGMENT_SET_OR_HASH_MISMATCH")
    try:
        validated = validate_case(case)
        evaluation = evaluate_case(validated)
    except (CaseValidationError, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"AHA_CASE_INVALID:{exc}") from exc
    components = evaluation["scores"]["C_bridge"]["components"]
    lineage_coverage = components.pop("exact_evidence_coverage")
    components["lineage_reference_coverage"] = lineage_coverage
    evaluation["semantic_non_vacuity_assessed"] = False
    evaluation["semantic_utility_demonstrated"] = False
    evaluation["limitation"] = "STRUCTURAL_LINEAGE_COVERAGE_ONLY_NOT_SEMANTIC_EVIDENCE_OR_EXTERNAL_UTILITY"
    disposition = evaluation["disposition"]
    return {
        **base,
        "status": "AVAILABLE",
        "disposition": disposition,
        "reason_codes": evaluation["fail_reasons"] or ["AHA_STRUCTURAL_CASE_REVIEWABLE"],
        "case_sha256": sha256_json(case),
        "case": case,
        "evaluation": evaluation,
        "authority_effect": "NONE",
    }


def validate_aha_result(value: Any, *, grounding_bundle: Any) -> dict[str, Any]:
    require_exact_keys(
        value,
        required={
            "schema_id", "run_id", "candidate_id", "candidate_sha256", "source_sha256", "status",
            "disposition", "reason_codes", "case_sha256", "case", "evaluation", "authority_effect",
        },
    )
    if value["schema_id"] != AHA_RESULT_SCHEMA or value["authority_effect"] != "NONE":
        raise ValidationError("AHA_RESULT_SCHEMA_OR_AUTHORITY_INVALID")
    expected = evaluate_structural_aha(
        value["case"],
        grounding_bundle=grounding_bundle,
        run_id=value["run_id"],
        candidate_id=value["candidate_id"],
        candidate_sha256=value["candidate_sha256"],
    )
    if value != expected:
        raise ValidationError("AHA_RESULT_RECOMPUTATION_MISMATCH")
    return expected
