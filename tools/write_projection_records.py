"""Regenerate deterministic RL-02 projection, rights, and notice records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path, PurePosixPath


BASE_COMMIT = "b278378f5add312aa8fb81a6cc1e0dc5fccc49aa"
BASE_TREE = "aefe9503e8f0ede0d7d5ab3de9f93a8e25a3668e"
SOURCE_COMMIT = "a3b306f6df40fc9862f2494f5048bd604ceafce0"
SOURCE_TREE = "49844480c4e826a28b51362d4f5abe714e6b9a5a"
SOURCE_PARENT = "715292b6c18755b0e6de35f90b2648fdeab7332b"
MERGE_BASE = "308c5af03f9cf0cc4cbb3f2eb4d269ecca310ddd"
HUMAN_RECEIPT_SHA256 = "da4f57bddcd15e9b74029d3797bbb60704e45ffb4f44dbca02d5e763c2b2211f"
MPL_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
UNICODE_SOURCE_SHA256 = "24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08"
REDISTRIBUTION_AUTHORITY = "HUMAN_APPROVED_RL02_CANDIDATE_PENDING_INDEPENDENT_REVIEW"
RETIRED_LICENSE_REASON = "RETIRED_RL02_OBSOLETE_LICENSE_PLACEHOLDER"
RETIRED_WORKFLOW_REASON = "RETIRED_INAPPLICABLE_UPSTREAM_INTEGRATION_WORKFLOW"

RECORD_FILES = {
    "EXCLUDED_PATHS.csv",
    "PROJECTION_LINEAGE.csv",
    "PUBLIC_PROJECTION_MANIFEST.json",
    "REPLACED_PATHS.csv",
    "RIGHTS_EVIDENCE_MATRIX.csv",
    "THIRD_PARTY_SNIPPET_AND_LICENSE_FINDINGS.csv",
}
NEW_FILES = {
    "AI_ASSISTANCE_DISCLOSURE.md",
    "CONTRIBUTORS.md",
    "DEPENDENCIES.md",
    "LICENSE",
    "LICENSE_SCOPE.md",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "licenses/Unicode-3.0.txt",
}
UNICODE_PATHS = {
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/tests/product/test_r3_actual_runtime_boundaries.py",
    "components/Sophia/python/src/sophia/triadic/totality_audit.py",
    "components/Sophia/tests/test_totality_audit.py",
    "components/uvlm-publications/python/src/atlas/triadic/totality_posture.py",
    "components/uvlm-publications/tests/test_atlas_totality_posture.py",
}
MPL_MARKED_PATHS = {
    "components/CoherenceLattice/python/src/coherence/totality/atlas_contract.py",
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/src/coherence/totality/grounding.py",
    "components/CoherenceLattice/python/src/coherence/totality/seal.py",
    "components/CoherenceLattice/python/src/coherence/totality/ucm.py",
    "components/CoherenceLattice/python/src/coherence/totality/waveform.py",
}
RL02_MODIFIED_PATHS = {
    ".github/workflows/private-alpha-ci.yml",
    "CONTRIBUTING.md",
    "HUMAN_RIGHTS_ATTESTATION_REQUIRED.md",
    "LICENSE_DECISION_MEMO.md",
    "NOTICE_REPAIR_PLAN.md",
    "README.md",
    "_triadicbrain_build_backend.py",
    "components/CoherenceLattice/README.md",
    "docs/getting-started.md",
    "pyproject.toml",
    "src/triadicbrain/__init__.py",
    "tests/test_root_package.py",
    "tools/oa01_validate.py",
    "tools/run_private_alpha_ci.py",
    "tools/write_projection_records.py",
} | UNICODE_PATHS | RECORD_FILES
AUTHORIZED_CHANGED_PATHS = NEW_FILES | RL02_MODIFIED_PATHS | {"LICENSE_NOT_YET_SELECTED.md"}
if len(AUTHORIZED_CHANGED_PATHS) != 36:
    raise RuntimeError("RL-02 changed-path contract is not 36 paths")


def run(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, encoding="utf-8", errors="strict"
    ).strip()


def git_bytes(root: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), "show", f"{revision}:{path}"])


def git_binding(root: Path, revision: str, path: str) -> tuple[str, str]:
    raw = run(root, "ls-tree", revision, "--", path)
    if not raw:
        raise ValueError(f"Git binding unavailable for {path}")
    meta, observed = raw.split("\t", 1)
    mode, kind, oid = meta.split()
    if observed != path or kind != "blob":
        raise ValueError(f"unexpected Git binding for {path}")
    return mode, oid


def csv_rows(payload: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8"), newline="")))


def csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def active_files(root: Path) -> list[str]:
    rows: list[str] = []
    for base, directories, files in os.walk(root):
        directories[:] = sorted(
            name for name in directories
            if name not in {".git", ".pytest_cache", "__pycache__", "build", "dist", ".venv"}
            and not name.endswith((".egg-info", ".dist-info"))
        )
        for name in sorted(files):
            path = Path(base) / name
            relative = path.relative_to(root).as_posix()
            parsed = PurePosixPath(relative)
            if relative != "/".join(parsed.parts) or path.is_symlink() or not path.is_file():
                raise ValueError(f"unsafe active source member: {relative}")
            rows.append(relative)
    rows.sort()
    if len(rows) != len({row.casefold() for row in rows}):
        raise ValueError("active source topology is ambiguous")
    return rows


def changed_paths(root: Path) -> set[str]:
    tracked = set(run(root, "diff", "--name-only", BASE_COMMIT, "--").splitlines())
    untracked = set(run(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return {path.replace("\\", "/") for path in tracked | untracked if path}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_lineage(root: Path) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, BASE_COMMIT, "PROJECTION_LINEAGE.csv"))
    by_path = {row["projected_path"]: row for row in rows}
    for path in sorted(UNICODE_PATHS | {"README.md", "components/CoherenceLattice/README.md"}):
        row = by_path[path]
        payload = root.joinpath(*path.split("/")).read_bytes()
        row["projected_size_bytes"] = str(len(payload))
        row["projected_sha256"] = hashlib.sha256(payload).hexdigest()
        row["public_status"] = "HOLD"
        row["public_release_eligible"] = "false"
        if path in UNICODE_PATHS:
            row["classification"] = "RL02_UNICODE_PROVENANCE_COMMENT_ONLY"
            row["byte_identity"] = "FALSE_RL02_PROVENANCE_COMMENT_ONLY"
        else:
            row["classification"] = "REPLACED_BY_RL02_BOUNDED_NOTICE_DOCUMENTATION"
            row["byte_identity"] = "FALSE_RL02_REPLACED"

    mode, oid = git_binding(root, BASE_COMMIT, "LICENSE_NOT_YET_SELECTED.md")
    payload = git_bytes(root, BASE_COMMIT, "LICENSE_NOT_YET_SELECTED.md")
    rows.append({
        "source_path": "LICENSE_NOT_YET_SELECTED.md",
        "git_mode": mode,
        "git_blob_oid": oid,
        "source_size_bytes": str(len(payload)),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "projected_path": "LICENSE_NOT_YET_SELECTED.md",
        "projected_size_bytes": str(len(payload)),
        "projected_sha256": hashlib.sha256(payload).hexdigest(),
        "classification": RETIRED_LICENSE_REASON,
        "byte_identity": "TRUE_RETIRED_RL02_BASE",
        "public_status": "HOLD",
        "public_release_eligible": "false",
        "record_status": "RETIRED",
    })
    rows.sort(key=lambda row: row["projected_path"])
    if len(rows) != 109:
        raise ValueError("RL-02 lineage row count mismatch")
    return rows


def build_excluded(root: Path) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, BASE_COMMIT, "EXCLUDED_PATHS.csv"))
    mode, oid = git_binding(root, BASE_COMMIT, "LICENSE_NOT_YET_SELECTED.md")
    rows.append({
        "source_path": "LICENSE_NOT_YET_SELECTED.md",
        "git_mode": mode,
        "git_blob_oid": oid,
        "reason": RETIRED_LICENSE_REASON,
        "copied": "false",
        "record_status": "RETIRED",
    })
    rows.sort(key=lambda row: row["source_path"])
    if len(rows) != 8420:
        raise ValueError("RL-02 exclusion row count mismatch")
    return rows


def build_replacements(root: Path, lineage: list[dict[str, str]]) -> list[dict[str, str]]:
    by_path = {row["projected_path"]: row for row in lineage}
    return [
        {
            "source_path": path,
            "projected_path": path,
            "reason": reason,
            "source_git_blob_oid": by_path[path]["git_blob_oid"],
            "replacement_origin": "RL02_HUMAN_APPROVED_AI_ASSISTED_CANDIDATE",
            "public_status": "HOLD",
        }
        for path, reason in (
            ("README.md", "RL02_ROOT_LICENSE_NOTICE_AND_PRIVATE_HOLD_DOCUMENTATION"),
            ("components/CoherenceLattice/README.md", "RL02_BOUNDED_COMPONENT_README_REPLACEMENT"),
        )
    ]


def build_findings(root: Path) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, BASE_COMMIT, "THIRD_PARTY_SNIPPET_AND_LICENSE_FINDINGS.csv"))
    by_id = {row["finding_id"]: row for row in rows}
    by_id["TP-001"].update({
        "current_disposition": "HUMAN_APPROVED_RL02_CANDIDATE_PENDING_INDEPENDENT_REVIEW",
        "required_action": "Preserve six SPDX headers and independently verify MPL scope notice and package inclusion",
    })
    by_id["TP-003"].update({
        "observed_evidence": "Ambiguous inherited collaborator wording replaced by bounded RL02 component README",
        "current_disposition": "REPLACED_IN_RL02_CANDIDATE_PENDING_INDEPENDENT_REVIEW",
        "required_action": "Verify replacement identity notice and retained component boundary",
    })
    rows.append({
        "finding_id": "TP-013",
        "scope": "six Unicode range-bearing source and test files; three runtime copies ship in wheel and sdist",
        "finding_type": "embedded Unicode UCD-derived data and notice",
        "material_or_dependency": "Unicode UCD 17.0.0 DerivedCoreProperties Default_Ignorable_Code_Point / Unicode License V3",
        "observed_evidence": f"Exact ranges bind official UCD SHA256 {UNICODE_SOURCE_SHA256}; exact license SHA256 {UNICODE_LICENSE_SHA256}",
        "current_disposition": "NOTICE_AND_LICENSE_IMPLEMENTED_RL02_PENDING_INDEPENDENT_REVIEW",
        "required_action": "Verify six comments range identity THIRD_PARTY_NOTICES and wheel/sdist Unicode license bytes",
        "public_status": "HOLD",
        "authority_effect": "NONE",
    })
    rows.sort(key=lambda row: row["finding_id"])
    if len(rows) != 13:
        raise ValueError("RL-02 third-party finding count mismatch")
    return rows


def new_rights_row(path: str) -> dict[str, str]:
    official_mpl = path == "LICENSE"
    official_unicode = path == "licenses/Unicode-3.0.txt"
    return {
        "path": path,
        "rights_group": "D",
        "origin": "RL-02 human-approved implementation candidate",
        "origin_commit": "NOT_APPLICABLE_PENDING_SUCCESSOR_COMMIT",
        "source_identity": (
            f"OFFICIAL_MPL_TEXT_SHA256:{MPL_SHA256}" if official_mpl else
            f"OFFICIAL_UNICODE_LICENSE_SHA256:{UNICODE_LICENSE_SHA256}" if official_unicode else
            "RL02_GENERATED_BYTES"
        ),
        "modification_status": "NEW_RL02_FILE",
        "owner_evidence": f"RL01_OPERATIVE_DECISION_RECEIPT:{HUMAN_RECEIPT_SHA256}; INDEPENDENT_REVIEW_REQUIRED",
        "ai_assistance": "NO_AI_ASSISTANCE_EXACT_OFFICIAL_LICENSE_BYTES" if (official_mpl or official_unicode) else "YES_OPENAI_CODEX_DISCLOSED",
        "third_party_material": (
            "OFFICIAL_MPL-2.0_LICENSE_TEXT" if official_mpl else
            "OFFICIAL_UNICODE_LICENSE_V3_TEXT" if official_unicode else
            "NO_KNOWN_COPIED_MATERIAL_EXCEPT_AS_EXPLICITLY_NOTICED"
        ),
        "inbound_license": (
            "MPL-2.0_OFFICIAL_TEXT" if official_mpl else
            "UNICODE-3.0_OFFICIAL_TEXT" if official_unicode else
            "HUMAN_APPROVED_RL02_CANDIDATE"
        ),
        "current_notice": "RL02_LICENSE_NOTICE_AND_AI_DISCLOSURE_SET",
        "outbound_license": "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION" if official_unicode else "MPL-2.0",
        "redistribution_authority": REDISTRIBUTION_AUTHORITY,
        "public_status": "HOLD",
        "public_release_eligible": "false",
        "required_action": "INDEPENDENT_REVIEW_OF_RL02_CANDIDATE_BEFORE_PUBLIC_RELEASE",
        "evidence_reference": f"RL02_OPERATIVE_DECISION:{HUMAN_RECEIPT_SHA256};RL02_CANDIDATE:{path}",
        "authority_effect": "NONE",
        "record_status": "ACTIVE",
    }


def build_rights(root: Path, files: list[str]) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, BASE_COMMIT, "RIGHTS_EVIDENCE_MATRIX.csv"))
    by_path = {row["path"]: row for row in rows}
    for path in NEW_FILES:
        if path in by_path:
            raise ValueError(f"new RL-02 path already has a base rights row: {path}")
        by_path[path] = new_rights_row(path)

    placeholder = by_path["LICENSE_NOT_YET_SELECTED.md"]
    placeholder.update({
        "modification_status": "RETIRED_IN_RL02_SUCCESSOR",
        "current_notice": "SUPERSEDED_BY_OPERATIVE_MPL_AND_UNICODE_NOTICE_SET",
        "outbound_license": "NOT_APPLICABLE_RETIRED",
        "redistribution_authority": REDISTRIBUTION_AUTHORITY,
        "required_action": "PRESERVE_RETIRED_IDENTITY_IN_RIGHTS_AND_LINEAGE_EVIDENCE",
        "evidence_reference": f"RL02_OPERATIVE_DECISION:{HUMAN_RECEIPT_SHA256};RL02_RETIRED:LICENSE_NOT_YET_SELECTED.md",
        "record_status": "RETIRED",
    })

    for path, row in by_path.items():
        row["public_status"] = "HOLD"
        row["public_release_eligible"] = "false"
        row["authority_effect"] = "NONE"
        if row["record_status"] == "ACTIVE":
            row["redistribution_authority"] = REDISTRIBUTION_AUTHORITY
            row["required_action"] = "INDEPENDENT_REVIEW_OF_RL02_CANDIDATE_BEFORE_PUBLIC_RELEASE"
            row["outbound_license"] = "MPL-2.0"
            if path in RL02_MODIFIED_PATHS:
                row["modification_status"] = "RL02_REGENERATED_RECORD" if path in RECORD_FILES else (
                    "RL02_REPLACED_INHERITED_PATH" if path == "components/CoherenceLattice/README.md" else
                    "RL02_UNICODE_PROVENANCE_COMMENT_ONLY" if path in UNICODE_PATHS else
                    "RL02_SUCCESSOR_MODIFIED"
                )
                row["owner_evidence"] = f"{row['owner_evidence']}; RL01_OPERATIVE_DECISION_RECEIPT:{HUMAN_RECEIPT_SHA256}"
                row["evidence_reference"] = f"RL02_OPERATIVE_DECISION:{HUMAN_RECEIPT_SHA256};RL02_CANDIDATE:{path}"
            if path in MPL_MARKED_PATHS:
                row["current_notice"] = "EXISTING_SPDX_MPL-2.0_HEADER_PRESERVED"
                row["inbound_license"] = "MPL-2.0_FILE_HEADER_PRESERVED"
            if path in UNICODE_PATHS:
                row["third_party_material"] = "UNICODE_UCD_17.0.0_DEFAULT_IGNORABLE_CODE_POINT_DATA"
                row["inbound_license"] = "MPL-2.0_WITH_UNICODE-3.0_DATA_EXCEPTION"
                row["current_notice"] = "UNICODE_UCD_PROVENANCE_COMMENT_AND_THIRD_PARTY_NOTICE"
                row["outbound_license"] = "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION"
            if path == "licenses/Unicode-3.0.txt":
                row["third_party_material"] = "UNICODE_LICENSE_V3_EXACT_OFFICIAL_TEXT"
                row["inbound_license"] = "UNICODE-3.0_OFFICIAL_TEXT"
                row["current_notice"] = "UNICODE_LICENSE_V3_EXACT_OFFICIAL_TEXT"
                row["outbound_license"] = "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION"
        elif path == ".github/workflows/triadicgate-ci.yml":
            row["outbound_license"] = "NOT_APPLICABLE_RETIRED"
            row["redistribution_authority"] = REDISTRIBUTION_AUTHORITY

    final = sorted(by_path.values(), key=lambda row: row["path"])
    active = {row["path"] for row in final if row["record_status"] == "ACTIVE"}
    if active != set(files):
        raise ValueError(f"rights/source mismatch: missing={sorted(set(files)-active)!r} extra={sorted(active-set(files))!r}")
    if len(final) != 158 or sum(row["record_status"] == "ACTIVE" for row in final) != 156:
        raise ValueError("RL-02 rights cardinality mismatch")
    if any(row["public_status"] != "HOLD" or row["public_release_eligible"] != "false" for row in final):
        raise ValueError("RL-02 rights HOLD posture mismatch")
    return final


def build_manifest(
    files: list[str], lineage: list[dict[str, str]], excluded: list[dict[str, str]], rights: list[dict[str, str]]
) -> dict[str, object]:
    return {
        "schema": "uvlm.rl02.public_projection_manifest.v1",
        "authority_effect": "NONE",
        "runtime_authority_effect": "NONE",
        "human_authority_effect": "RIGHTS_AND_LICENSE_IMPLEMENTATION_CANDIDATE_ONLY",
        "candidate_label": "v0.1.0-alpha.0-private.3-rc1",
        "python_distribution_version": "0.1.0a0.dev2",
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "source_parent": SOURCE_PARENT,
        "merge_base": MERGE_BASE,
        "reviewed_base": {"commit": BASE_COMMIT, "tree": BASE_TREE},
        "successor_branch": "rights-license/mpl-unicode-notices-01",
        "reviewed_baseline_tag": "v0.1.0-alpha.0-private.1",
        "active_source_file_count": len(files),
        "retired_source_file_count": 2,
        "inherited_selected_count": 107,
        "unchanged_inherited_count": 98,
        "modified_inherited_count": 7,
        "replaced_inherited_count": 2,
        "lineage_active_count": sum(row["record_status"] == "ACTIVE" for row in lineage),
        "lineage_retired_count": sum(row["record_status"] == "RETIRED" for row in lineage),
        "excluded_active_count": sum(row["record_status"] == "ACTIVE" for row in excluded),
        "excluded_retired_count": sum(row["record_status"] == "RETIRED" for row in excluded),
        "excluded_source_count": len(excluded),
        "rights_active_count": sum(row["record_status"] == "ACTIVE" for row in rights),
        "rights_retired_count": sum(row["record_status"] == "RETIRED" for row in rights),
        "rights_hold_count": sum(row["public_status"] == "HOLD" for row in rights),
        "rights_clear_count": sum(row["public_status"] == "CLEAR" for row in rights),
        "rights_status": "HUMAN_APPROVED_IMPLEMENTATION_CANDIDATE_PENDING_INDEPENDENT_REVIEW",
        "outbound_license": "MPL-2.0 with Unicode License V3 exception",
        "mpl_license_sha256": MPL_SHA256,
        "unicode_license_sha256": UNICODE_LICENSE_SHA256,
        "unicode_ucd_source_sha256": UNICODE_SOURCE_SHA256,
        "unicode_affected_paths": sorted(UNICODE_PATHS),
        "active_workflows": [".github/workflows/private-alpha-ci.yml"],
        "retired_workflows": [".github/workflows/triadicgate-ci.yml"],
        "superseded_workflows": [
            ".github/workflows/oa01-linux-python312.yml",
            ".github/workflows/oa01-windows-python312.yml",
        ],
        "action_pins": {
            "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
            "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
        },
        "repository_visibility": "PRIVATE",
        "github_actions": "RESTRICTED_GITHUB_OWNED_ACTIONS_FULL_SHA_PINS_SOURCE_DEFINED",
        "remote_push": False,
        "public_release": False,
        "public_release_eligible": False,
        "live_provider": "NOT_INVOKED_REQUIRES_SEPARATE_HUMAN_PROVIDER_AUTHORIZATION",
        "record_status_values": ["ACTIVE", "RETIRED"],
        "triadicgate_workflow_retirement_reason": RETIRED_WORKFLOW_REASON,
        "retired_license_placeholder_reason": RETIRED_LICENSE_REASON,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.projection_root.resolve()
    if run(root, "rev-parse", "HEAD") != BASE_COMMIT or run(root, "rev-parse", "HEAD^{tree}") != BASE_TREE:
        raise SystemExit("RL-02 base identity mismatch")
    if run(root, "branch", "--show-current") != "rights-license/mpl-unicode-notices-01":
        raise SystemExit("RL-02 branch mismatch")

    files = active_files(root)
    if len(files) != 156 or "LICENSE_NOT_YET_SELECTED.md" in files:
        raise SystemExit("RL-02 active-source topology mismatch")
    if sha256(root / "LICENSE") != MPL_SHA256 or sha256(root / "licenses" / "Unicode-3.0.txt") != UNICODE_LICENSE_SHA256:
        raise SystemExit("RL-02 license identity mismatch")

    lineage = build_lineage(root)
    excluded = build_excluded(root)
    replacements = build_replacements(root, lineage)
    findings = build_findings(root)
    rights = build_rights(root, files)
    manifest = build_manifest(files, lineage, excluded, rights)

    outputs = {
        "PROJECTION_LINEAGE.csv": csv_bytes(list(lineage[0]), lineage),
        "EXCLUDED_PATHS.csv": csv_bytes(list(excluded[0]), excluded),
        "REPLACED_PATHS.csv": csv_bytes(list(replacements[0]), replacements),
        "THIRD_PARTY_SNIPPET_AND_LICENSE_FINDINGS.csv": csv_bytes(list(findings[0]), findings),
        "RIGHTS_EVIDENCE_MATRIX.csv": csv_bytes(list(rights[0]), rights),
        "PUBLIC_PROJECTION_MANIFEST.json": (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8"),
    }
    for name, payload in outputs.items():
        (root / name).write_bytes(payload)

    observed = changed_paths(root)
    if observed != AUTHORIZED_CHANGED_PATHS:
        raise SystemExit(
            f"RL-02 changed-path ceiling mismatch: missing={sorted(AUTHORIZED_CHANGED_PATHS-observed)!r} "
            f"extra={sorted(observed-AUTHORIZED_CHANGED_PATHS)!r}"
        )
    print(json.dumps({
        "status": "PASS",
        "active_source_files": len(files),
        "rights_rows": len(rights),
        "rights_hold": 158,
        "rights_clear": 0,
        "changed_paths": len(observed),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
