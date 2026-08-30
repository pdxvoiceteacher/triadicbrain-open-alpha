"""Strict input validation for the offline AHA review tool."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


class CaseValidationError(ValueError):
    """A deterministic, fail-closed case validation failure."""


MAX_TEXT = 10_000
FORBIDDEN_FIELDS = {
    "truth", "certified_truth", "approval", "approved", "memory", "pmr",
    "publication", "publish", "deployment", "deploy", "release",
    "authority", "authority_effect",
}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise CaseValidationError("AHA_JSON_DUPLICATE_MEMBER")
        output[key] = value
    return output


def _constant(value: str) -> None:
    raise CaseValidationError("AHA_JSON_NONFINITE_NUMBER")


def parse_json(text: str) -> dict[str, Any]:
    if "\x00" in text:
        raise CaseValidationError("AHA_TEXT_NUL")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CaseValidationError("AHA_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise CaseValidationError("AHA_CASE_NOT_OBJECT")
    return value


def _check_value(value: Any, path: str = "$") -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise CaseValidationError("AHA_TEXT_NUL")
        if len(value) > MAX_TEXT:
            raise CaseValidationError("AHA_TEXT_UNBOUNDED")
    elif isinstance(value, float) and not math.isfinite(value):
        raise CaseValidationError("AHA_JSON_NONFINITE_NUMBER")
    elif isinstance(value, list):
        for item in value:
            _check_value(item, path)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_FIELDS:
                raise CaseValidationError("AHA_AUTHORITY_FIELD_FORBIDDEN")
            _check_value(item, f"{path}.{key}")


def _required(obj: dict[str, Any], keys: set[str], code: str) -> None:
    missing = sorted(keys - obj.keys())
    if missing:
        raise CaseValidationError(f"{code}:{','.join(missing)}")


def _ids(items: list[dict[str, Any]], field: str, code: str) -> set[str]:
    values = [item.get(field) for item in items]
    if any(not isinstance(value, str) or not value for value in values) or len(set(values)) != len(values):
        raise CaseValidationError(code)
    return set(values)


def _lineage(lineage: Any, segment_ids: set[str]) -> None:
    if not isinstance(lineage, list) or not lineage:
        raise CaseValidationError("AHA_LINEAGE_MISSING")
    for ref in lineage:
        segment_id = ref if isinstance(ref, str) else ref.get("segment_id") if isinstance(ref, dict) else None
        if segment_id not in segment_ids:
            raise CaseValidationError("AHA_LINEAGE_UNRESOLVED")


def _graph(graph: Any, segment_ids: set[str]) -> None:
    if not isinstance(graph, dict):
        raise CaseValidationError("AHA_GRAPH_INVALID")
    _required(graph, {"graph_id", "domain", "source_family_id", "nodes", "relations"}, "AHA_GRAPH_REQUIRED")
    nodes, relations = graph["nodes"], graph["relations"]
    if not isinstance(nodes, list) or not isinstance(relations, list):
        raise CaseValidationError("AHA_GRAPH_COLLECTION_INVALID")
    node_ids = _ids(nodes, "node_id", "AHA_NODE_ID_DUPLICATE")
    _ids(relations, "relation_id", "AHA_RELATION_ID_DUPLICATE")
    for node in nodes:
        _required(node, {"node_id", "node_type", "label", "lineage"}, "AHA_NODE_REQUIRED")
        _lineage(node["lineage"], segment_ids)
    for relation in relations:
        _required(relation, {"relation_id", "relation_type", "source_node_id", "target_node_id", "orientation", "lineage"}, "AHA_RELATION_REQUIRED")
        if relation["source_node_id"] not in node_ids or relation["target_node_id"] not in node_ids:
            raise CaseValidationError("AHA_RELATION_DANGLING_NODE")
        _lineage(relation["lineage"], segment_ids)


@dataclass(frozen=True)
class AhaCase:
    raw: dict[str, Any]


def validate_case(raw: dict[str, Any]) -> AhaCase:
    _check_value(raw)
    _required(raw, {"schema_id", "case_id", "question", "grounding_segments", "target", "donors", "mappings", "candidate_hypothesis", "falsification_test"}, "AHA_CASE_REQUIRED")
    segments = raw["grounding_segments"]
    if not isinstance(segments, list):
        raise CaseValidationError("AHA_SEGMENTS_INVALID")
    segment_ids = _ids(segments, "segment_id", "AHA_SEGMENT_ID_DUPLICATE")
    for segment in segments:
        _required(segment, {"segment_id", "sha256"}, "AHA_SEGMENT_REQUIRED")
        if len(segment["sha256"]) != 64:
            raise CaseValidationError("AHA_SEGMENT_HASH_INVALID")
    _graph(raw["target"], segment_ids)
    donors = raw["donors"]
    if not isinstance(donors, list) or not 2 <= len(donors) <= 5:
        raise CaseValidationError("AHA_DONOR_CARDINALITY")
    _ids(donors, "graph_id", "AHA_GRAPH_ID_DUPLICATE")
    for donor in donors:
        _graph(donor, segment_ids)
    mappings = raw["mappings"]
    if not isinstance(mappings, list) or not mappings:
        raise CaseValidationError("AHA_MAPPING_MISSING")
    _ids(mappings, "mapping_id", "AHA_MAPPING_ID_DUPLICATE")
    donor_ids = {donor["graph_id"] for donor in donors}
    required_mapping = {"mapping_id", "donor_graph_id", "node_map", "relation_map", "invariant_map", "disanalogies", "declared_scale_or_unit_transformations"}
    for mapping in mappings:
        _required(mapping, required_mapping, "AHA_MAPPING_REQUIRED")
        if mapping["donor_graph_id"] not in donor_ids:
            raise CaseValidationError("AHA_MAPPING_DANGLING_GRAPH")
        if not isinstance(mapping["disanalogies"], list) or not mapping["disanalogies"]:
            raise CaseValidationError("AHA_DISANALOGY_MISSING")
    hypothesis = raw["candidate_hypothesis"]
    _required(hypothesis, {"statement", "target_observable", "intervention_or_condition", "expected_direction", "comparator_or_null", "horizon", "confidence_lowering_observation"}, "AHA_HYPOTHESIS_REQUIRED")
    if not hypothesis["target_observable"]:
        raise CaseValidationError("AHA_TARGET_OBSERVABLE_MISSING")
    if hypothesis["comparator_or_null"] is None or hypothesis["comparator_or_null"] == "":
        raise CaseValidationError("AHA_HYPOTHESIS_COMPARATOR_MISSING")
    if not hypothesis["confidence_lowering_observation"]:
        raise CaseValidationError("AHA_CONFIDENCE_LOWERING_MISSING")
    test = raw["falsification_test"]
    _required(test, {"test_statement", "primary_outcome", "comparator", "reject_criteria", "feasibility_posture", "risk_posture"}, "AHA_TEST_REQUIRED")
    if not test["comparator"]:
        raise CaseValidationError("AHA_TEST_COMPARATOR_MISSING")
    return AhaCase(raw)
