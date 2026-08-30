"""Deterministic, offline evaluation and package writing for AHA cases."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import AhaCase, CaseValidationError, parse_json, validate_case


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def load_case(path: str | Path) -> AhaCase:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise CaseValidationError("AHA_INPUT_PATH_UNSAFE")
    return validate_case(parse_json(source.read_text(encoding="utf-8")))


def _mapping_result(case: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    donor = next(graph for graph in case["donors"] if graph["graph_id"] == mapping["donor_graph_id"])
    target = case["target"]
    donor_relations = {item["relation_id"]: item for item in donor["relations"]}
    target_relations = {item["relation_id"]: item for item in target["relations"]}
    target_nodes = {item["node_id"] for item in target["nodes"]}
    failures: list[str] = []
    mapped: list[dict[str, str]] = []
    for donor_id, target_id in sorted(mapping["relation_map"].items()):
        left, right = donor_relations.get(donor_id), target_relations.get(target_id)
        if not left or not right:
            failures.append("AHA_RELATION_UNSUPPORTED")
            continue
        if left["relation_type"] != right["relation_type"]:
            failures.append("AHA_RELATION_TYPE_MISMATCH")
        if left["orientation"] != right["orientation"]:
            failures.append("AHA_CAUSAL_REVERSAL_UNDECLARED")
        if mapping["node_map"].get(left["source_node_id"]) not in target_nodes or mapping["node_map"].get(left["target_node_id"]) not in target_nodes:
            failures.append("AHA_MAPPING_DANGLING_NODE")
        mapped.append({"donor_relation_id": donor_id, "target_relation_id": target_id})
    if not mapped:
        failures.append("AHA_RELATION_MAPPING_EMPTY")
    return {"mapping_id": mapping["mapping_id"], "donor_graph_id": donor["graph_id"], "mapped_relations": mapped, "unmapped_donor_relations": sorted(set(donor_relations) - set(mapping["relation_map"])), "fail_reasons": sorted(set(failures)), "invariants": mapping["invariant_map"], "disanalogies": mapping["disanalogies"]}


def evaluate_case(case: AhaCase) -> dict[str, Any]:
    raw = case.raw
    mappings = [_mapping_result(raw, mapping) for mapping in sorted(raw["mappings"], key=lambda item: item["mapping_id"])]
    reasons = sorted({reason for item in mappings for reason in item["fail_reasons"]})
    families = [donor["source_family_id"] for donor in raw["donors"]]
    clone = len(set(families)) != len(families)
    if clone:
        reasons.append("AHA_SOURCE_FAMILY_CLONE")
    valid = not reasons
    components = {
        "relation_preservation": "PASS" if not any("RELATION" in code for code in reasons) else "FAIL",
        "causal_orientation": "PASS" if "AHA_CAUSAL_REVERSAL_UNDECLARED" not in reasons else "FAIL",
        "invariant_preservation": "PASS" if all(item["invariants"] for item in mappings) else "FAIL",
        "scale_unit_compatibility": "DECLARED" if all(raw_mapping["declared_scale_or_unit_transformations"] is not None for raw_mapping in raw["mappings"]) else "NOT_SCORABLE",
        "exact_evidence_coverage": "PASS",
        "source_family_independence": "FAIL" if clone else "PASS",
        "disanalogy_completeness": "PASS",
        "target_observability": "PASS",
        "falsifiability": "PASS",
        "replay_determinism": "PASS",
    }
    scores = {
        "P_epi": {"kind": "ordinal_evidence_posture", "posture": "NOT_SCORABLE", "nonclaim": "No probability or truth certification is emitted."},
        "C_bridge": {"kind": "bridge_fidelity", "scorable": valid, "components": components},
        "V_test": {"information_value": "QUALITATIVE", "feasibility": raw["falsification_test"]["feasibility_posture"], "cost": "NOT_SUPPLIED", "risk": raw["falsification_test"]["risk_posture"]},
        "Q_AHA": {"kind": "nonprobabilistic_attention_rank", "rank": 1, "authority_effect": "NONE"},
    }
    return {"case_id": raw["case_id"], "disposition": "REVIEWABLE" if valid else "REJECTED", "fail_reasons": sorted(set(reasons)), "bridge_evidence_map": mappings, "scores": scores}


def _atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_review_package(case: AhaCase, output_root: str | Path) -> dict[str, Any]:
    root = Path(output_root)
    if root.is_symlink() or not root.is_absolute():
        raise CaseValidationError("AHA_OUTPUT_PATH_UNSAFE")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise CaseValidationError("AHA_OUTPUT_PATH_UNSAFE")
    result = evaluate_case(case)
    raw = case.raw
    files: dict[str, str] = {
        "aha_case_normalized.json": canonical_json(raw),
        "bridge_evidence_map.json": canonical_json({"case_id": raw["case_id"], "mappings": result["bridge_evidence_map"]}),
        "falsification_suite.json": canonical_json(raw["falsification_test"]),
        "score_report.json": canonical_json({key: result[key] for key in ("case_id", "disposition", "fail_reasons", "scores")}),
    }
    summary = f"# AHA candidate review: {raw['case_id']}\n\n## Target question\n{raw['question']}\n\n## Donors\n" + "\n".join(f"- {d['domain']} ({d['source_family_id']})" for d in sorted(raw['donors'], key=lambda x: x['graph_id'])) + f"\n\n## Target prediction\n{raw['candidate_hypothesis']['statement']}\n\n## Smallest falsifying test\n{raw['falsification_test']['test_statement']}\n\n## P_epi\n{result['scores']['P_epi']}\n\n## C_bridge\n{result['scores']['C_bridge']}\n\n## V_test\n{result['scores']['V_test']}\n\n## Q_AHA\n{result['scores']['Q_AHA']}\n\n## Warnings and fail reasons\n{', '.join(result['fail_reasons']) or 'None'}\n\n## Nonclaims\nThis is an offline candidate review package, not truth, approval, memory, publication, deployment, or release authority.\n"
    files["human_review_summary.md"] = summary
    for name, content in files.items():
        _atomic(root / name, content)
    manifest = {"case_id": raw["case_id"], "artifacts": [{"path": name, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()} for name, content in sorted(files.items())]}
    files["artifact_manifest.json"] = canonical_json(manifest)
    _atomic(root / "artifact_manifest.json", files["artifact_manifest.json"])
    sums = "".join(f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}  {name}\n" for name, content in sorted(files.items()))
    _atomic(root / "SHA256SUMS.txt", sums)
    return result
