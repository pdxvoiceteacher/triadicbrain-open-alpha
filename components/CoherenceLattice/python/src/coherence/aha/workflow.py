"""External-state workflow helpers for the Sonya AHA review pages."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from coherence.grounding.bundle_builder import build_grounding_bundle

from .engine import canonical_json, write_review_package
from .models import AhaCase, CaseValidationError, validate_case


def _write(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(value), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def session_root(state_root: Path, session_id: str) -> Path:
    if not session_id.isalnum() or len(session_id) != 32:
        raise CaseValidationError("AHA_SESSION_INVALID")
    root = state_root / "aha_runs" / session_id
    if root.is_symlink():
        raise CaseValidationError("AHA_SESSION_PATH_UNSAFE")
    return root


def intake(state_root: Path, session_id: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = session_root(state_root, session_id)
    root.mkdir(parents=True, exist_ok=False)
    inventory: list[dict[str, Any]] = []
    for index, source in enumerate(sources, 1):
        source_id = f"{source['role']}-{index:02d}"
        temp = root / f".{source_id}.upload"
        temp.write_bytes(source["content"])
        try:
            built = build_grounding_bundle(temp, source["label"], root / ".bundles", media_type=source["media_type"], preferred_encoding="utf-8", fail_on_lossy_decode=True)
            bundle = Path(built["bundle_dir"])
            destination = root / "grounding" / source_id
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(bundle), destination)
        finally:
            temp.unlink(missing_ok=True)
        segments = []
        for line in (destination / "segments.jsonl").read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            ref = f"{source_id}:{item['segment_id']}"
            segments.append({"segment_id": ref, "bundle_segment_id": item["segment_id"], "locator": item["locator"], "text": item["body_md"], "sha256": hashlib.sha256(item["body_md"].encode("utf-8")).hexdigest()})
        manifest = built["manifest"]
        inventory.append({"source_id": source_id, "role": source["role"], "label": source["label"], "domain": source["domain"], "source_family_id": source["family"], "media_type": source["media_type"], "source_sha256": manifest["source_sha256"], "normalized_sha256": manifest["normalized_sha256"], "source_encoding": manifest["source_encoding"], "decode_strategy": manifest["decode_strategy"], "segments": segments})
    shutil.rmtree(root / ".bundles", ignore_errors=True)
    _write(root / "intake.json", {"session_id": session_id, "sources": [{k: v for k, v in item.items() if k != "segments"} for item in inventory]})
    _write(root / "source_inventory.json", {"session_id": session_id, "sources": inventory})
    return inventory


def read_inventory(root: Path) -> list[dict[str, Any]]:
    return json.loads((root / "source_inventory.json").read_text(encoding="utf-8"))["sources"]


def _lines(value: str, fields: int, name: str) -> list[list[str]]:
    output = []
    for number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != fields or not all(parts):
            raise CaseValidationError(f"AHA_FORM_{name}_LINE_{number}")
        output.append(parts)
    return output


def build_case(inventory: list[dict[str, Any]], form: dict[str, str]) -> AhaCase:
    refs = {segment["segment_id"]: segment for source in inventory for segment in source["segments"]}
    nodes_by_source: dict[str, list[dict[str, Any]]] = {source["source_id"]: [] for source in inventory}
    rels_by_source: dict[str, list[dict[str, Any]]] = {source["source_id"]: [] for source in inventory}
    for source_id, node_id, node_type, label, ref in _lines(form.get("nodes", ""), 5, "NODES"):
        if source_id not in nodes_by_source or ref not in refs:
            raise CaseValidationError("AHA_FORM_NODE_SOURCE_OR_LINEAGE")
        nodes_by_source[source_id].append({"node_id": node_id, "node_type": node_type, "label": label, "lineage": [ref]})
    for source_id, rel_id, rel_type, left, right, orientation, ref in _lines(form.get("relations", ""), 7, "RELATIONS"):
        if source_id not in rels_by_source or ref not in refs:
            raise CaseValidationError("AHA_FORM_RELATION_SOURCE_OR_LINEAGE")
        rels_by_source[source_id].append({"relation_id": rel_id, "relation_type": rel_type, "source_node_id": left, "target_node_id": right, "orientation": orientation, "lineage": [ref]})
    graphs = {source["source_id"]: {"graph_id": source["source_id"], "domain": source["domain"], "source_family_id": source["source_family_id"], "nodes": nodes_by_source[source["source_id"]], "relations": rels_by_source[source["source_id"]]} for source in inventory}
    target = next(source for source in inventory if source["role"] == "target")
    mappings = []
    for donor in (source for source in inventory if source["role"] == "donor"):
        donor_id = donor["source_id"]
        node_map = {left: right for graph, left, right in _lines(form.get("node_maps", ""), 3, "NODE_MAPS") if graph == donor_id}
        relation_map = {left: right for graph, left, right in _lines(form.get("relation_maps", ""), 3, "RELATION_MAPS") if graph == donor_id}
        invariants = {key: value for graph, key, value in _lines(form.get("invariants", ""), 3, "INVARIANTS") if graph == donor_id}
        disanalogies = [text for graph, text in _lines(form.get("disanalogies", ""), 2, "DISANALOGIES") if graph == donor_id]
        scale = [text for graph, text in _lines(form.get("scale_transforms", ""), 2, "SCALE_TRANSFORMS") if graph == donor_id]
        mappings.append({"mapping_id": f"map-{donor_id}", "donor_graph_id": donor_id, "node_map": node_map, "relation_map": relation_map, "invariant_map": invariants, "disanalogies": disanalogies, "declared_scale_or_unit_transformations": scale})
    raw = {"schema_id": "aha-case-v1", "case_id": form.get("case_id", "aha-review"), "question": form.get("question", ""), "grounding_segments": [{"segment_id": ref, "sha256": item["sha256"]} for ref, item in sorted(refs.items())], "target": graphs[target["source_id"]], "donors": [graphs[source["source_id"]] for source in inventory if source["role"] == "donor"], "mappings": mappings, "candidate_hypothesis": {key: form.get(key, "") for key in ("statement", "target_observable", "intervention_or_condition", "expected_direction", "comparator_or_null", "horizon", "confidence_lowering_observation")}, "falsification_test": {key: form.get(key, "") for key in ("test_statement", "primary_outcome", "comparator", "reject_criteria", "feasibility_posture", "risk_posture")}}
    return validate_case(raw)


def run_review(root: Path, case: AhaCase) -> dict[str, Any]:
    _write(root / "aha_case.json", case.raw)
    result = write_review_package(case, root / "review")
    files = [path for path in root.rglob("*") if path.is_file() and path.name not in {"run_manifest.json", "SHA256SUMS.txt"}]
    manifest = {"session_id": root.name, "files": [{"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(files)]}
    _write(root / "run_manifest.json", manifest)
    sums = "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["files"] + [{"path": "run_manifest.json", "sha256": hashlib.sha256((root / "run_manifest.json").read_bytes()).hexdigest()}])
    (root / "SHA256SUMS.txt").write_text(sums, encoding="utf-8", newline="\n")
    return result
