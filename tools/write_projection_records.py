"""Write deterministic OA-01 lineage and source-selection records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path


SOURCE_COMMIT = "a3b306f6df40fc9862f2494f5048bd604ceafce0"
SOURCE_TREE = "49844480c4e826a28b51362d4f5abe714e6b9a5a"
SOURCE_PARENT = "715292b6c18755b0e6de35f90b2648fdeab7332b"
MERGE_BASE = "308c5af03f9cf0cc4cbb3f2eb4d269ecca310ddd"


def zip_member(packet: Path, suffix: str) -> bytes:
    with zipfile.ZipFile(packet) as archive:
        matches = [name for name in archive.namelist() if name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"expected one {suffix!r} member")
        return archive.read(matches[0])


def list_file(packet: Path, suffix: str) -> list[str]:
    return [
        line for line in zip_member(packet, suffix).decode("utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def git_bytes(repo: Path, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{SOURCE_COMMIT}:{path}"])


def git_rows(repo: Path) -> dict[str, tuple[str, str]]:
    raw = subprocess.check_output(["git", "-C", str(repo), "ls-tree", "-r", SOURCE_COMMIT], text=True)
    rows: dict[str, tuple[str, str]] = {}
    for line in raw.splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, oid = meta.split()
        if kind != "blob":
            raise ValueError(f"unexpected Git object kind: {line}")
        rows[path] = (mode, oid)
    return rows


def csv_bytes(fieldnames: list[str], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--projection-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.projection_root.resolve()
    if subprocess.check_output(["git", "-C", str(args.source_repo), "rev-parse", "HEAD"], text=True).strip() != SOURCE_COMMIT:
        raise SystemExit("source commit mismatch")
    if subprocess.check_output(["git", "-C", str(args.source_repo), "rev-parse", "HEAD^{tree}"], text=True).strip() != SOURCE_TREE:
        raise SystemExit("source tree mismatch")
    hold = set(list_file(args.packet, "PUBLIC_FILE_HOLDLIST.txt"))
    projection_exclusions = {
        "components/CoherenceLattice/python/pyproject.toml",
        "components/Sophia/python/pyproject.toml",
        "components/Sophia/tests/test_distribution_boundary.py",
    }
    selected = set(hold) - projection_exclusions
    selected.update({
        "components/CoherenceLattice/python/src/coherence/context/__init__.py",
        "components/CoherenceLattice/python/src/coherence/context/symbol_normalize.py",
        "components/CoherenceLattice/python/src/coherence/grounding/__init__.py",
        "components/CoherenceLattice/python/src/coherence/grounding/bundle_builder.py",
        "components/CoherenceLattice/python/src/coherence/grounding/bundle_manifest.py",
        "components/CoherenceLattice/python/src/coherence/grounding/text_decode.py",
        "components/CoherenceLattice/python/src/coherence/totality/claims.py",
        "components/CoherenceLattice/python/src/coherence/totality/counterexamples.py",
        "components/Sophia/python/src/sophia/triadic/totality_audit.py",
        "components/uvlm-publications/python/src/atlas/triadic/governed_posture.py",
        "components/uvlm-publications/python/src/atlas/triadic/governed_posture_explain.py",
        "components/uvlm-publications/python/src/atlas/triadic/human_review_ui.py",
        "components/uvlm-publications/python/src/atlas/triadic/usability_comparator_ui.py",
        "components/uvlm-publications/tests/test_atlas_governed_posture.py",
    })
    if len(hold) != 97 or len(selected) != 108:
        raise SystemExit(f"unexpected projection cardinality: {len(hold)}/{len(selected)}")
    bindings = git_rows(args.source_repo)
    missing = selected - bindings.keys()
    if missing:
        raise SystemExit(f"selected paths absent from source tree: {sorted(missing)!r}")
    deny = list_file(args.packet, "PUBLIC_FILE_DENYLIST.txt")
    def denied(path: str) -> bool:
        return any(path == rule or (rule.endswith("/") and path.startswith(rule)) for rule in deny)
    blocked = [path for path in selected if denied(path)]
    if blocked:
        raise SystemExit(f"selected denylist paths: {blocked!r}")
    lineage = []
    for path in sorted(selected):
        data = git_bytes(args.source_repo, path)
        projected = root.joinpath(*path.split("/"))
        if not projected.is_file():
            raise SystemExit(f"projected path missing: {path}")
        projected_bytes = projected.read_bytes()
        replaced = path == "README.md" and projected_bytes != data
        if projected_bytes != data and not replaced:
            raise SystemExit(f"unexpected inherited-byte divergence: {path}")
        mode, oid = bindings[path]
        lineage.append({
            "source_path": path,
            "git_mode": mode,
            "git_blob_oid": oid,
            "source_size_bytes": len(data),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "projected_path": path,
            "projected_size_bytes": len(projected_bytes),
            "projected_sha256": hashlib.sha256(projected_bytes).hexdigest(),
            "classification": "REPLACED_BY_OA01" if replaced else ("INHERITED_HOLD_NUCLEUS" if path in hold else "ADDITIONAL_INHERITED_ROUTE_DEPENDENCY"),
            "byte_identity": "FALSE_REPLACED" if replaced else "TRUE",
            "public_status": "HOLD",
            "public_release_eligible": "false",
        })
    (root / "PROJECTION_LINEAGE.csv").write_bytes(csv_bytes(list(lineage[0]), lineage))
    excluded = []
    for path in sorted(set(bindings) - selected):
        mode, oid = bindings[path]
        if path in projection_exclusions:
            reason = "EXCLUDED_INCOMPLETE_OPTIONAL_DISTRIBUTION_FRAGMENT"
        else:
            reason = "EXCLUDED_DENYLIST" if denied(path) else "EXCLUDED_NOT_NEEDED_FOR_BOUNDED_ROUTE"
        excluded.append({"source_path": path, "git_mode": mode, "git_blob_oid": oid, "reason": reason, "copied": "false"})
    (root / "EXCLUDED_PATHS.csv").write_bytes(csv_bytes(list(excluded[0]), excluded))
    replacements = [{
        "source_path": "README.md",
        "projected_path": "README.md",
        "reason": "OA01_APPROACHABLE_ROOT_DOCUMENTATION_BASELINE",
        "source_git_blob_oid": bindings["README.md"][1],
        "replacement_origin": "OA01_GENERATED_D",
        "public_status": "HOLD",
    }]
    (root / "REPLACED_PATHS.csv").write_bytes(csv_bytes(list(replacements[0]), replacements))
    manifest = {
        "schema": "uvlm.oa01.public_projection_manifest.v1",
        "authority_effect": "NONE",
        "candidate_label": "v0.1.0-alpha.0-private.1",
        "python_distribution_version": "0.1.0a0.dev1",
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "source_parent": SOURCE_PARENT,
        "merge_base": MERGE_BASE,
        "inherited_selected_count": len(selected),
        "oa00_nucleus_reference_count": len(hold),
        "oa00_nucleus_selected_count": len(selected & hold),
        "oa00_nucleus_excluded_count": len(hold - selected),
        "additional_inherited_count": len(selected - hold),
        "replaced_inherited_count": 1,
        "unchanged_inherited_count": len(selected) - 1,
        "source_tree_blob_count": len(bindings),
        "excluded_source_count": len(bindings) - len(selected),
        "public_release": False,
        "public_release_eligible": False,
        "rights_status": "HOLD",
        "outbound_license": "NOT_SELECTED",
        "live_provider": "NOT_TESTED_REQUIRES_SEPARATE_HUMAN_PROVIDER_AUTHORIZATION",
    }
    (root / "PUBLIC_PROJECTION_MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "selected": len(selected), "excluded": len(excluded), "source_tree": SOURCE_TREE}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
