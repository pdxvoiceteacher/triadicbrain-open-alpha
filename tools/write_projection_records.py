"""Regenerate the bounded TB-PUBLIC-UX-01 manifest, rights, and lineage records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path, PurePosixPath


REPAIR_BASE_COMMIT = "82f819f4f5491f5daffb510c0c6ab6a7328dd6e6"
REPAIR_BASE_TREE = "a612d2f58a8e8f2a53e06ec3a61ae1675068870c"
REPAIR_BRANCH = "product/public-development-ux01"
REPAIR_ID = "UVLM-TB-PUBLIC-UX-01"
CANDIDATE_LABEL = "v0.1.0-alpha.0-public-dev.1-rc1"
PYTHON_VERSION = "0.1.0a0.dev4"
LICENSE_EXPRESSION = "MPL-2.0 AND Unicode-3.0"
MPL_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
REDISTRIBUTION_AUTHORITY = (
    "HUMAN_PUBLIC_REPOSITORY_VISIBILITY_COMPLETED_FORMAL_RELEASE_REMAINS_HOLD"
)
POST_MERGE_CI_RUN = 33423783473
GROUP_D_NEW_PATHS = {
    "PUBLIC_DEVELOPMENT_STATUS.md",
    "docs/evidence/rl02-repair01-main-closure.md",
    "docs/investor-demo-checklist.md",
    "docs/investor-demo.md",
    "docs/investor-one-page.md",
    "docs/operator-runbook.md",
    "docs/status-matrix.md",
    "docs/website-front-matter.md",
}

CHANGED_PATH_CLASSIFICATIONS = {
    ".github/workflows/private-alpha-ci.yml": "CI_OR_TEST",
    "AGENTS.md": "BINDING_GOVERNANCE",
    "AI_ASSISTANCE_DISCLOSURE.md": "ACTIVE_DOCUMENTATION",
    "CONTRIBUTING.md": "ACTIVE_DOCUMENTATION",
    "DEPENDENCIES.md": "ACTIVE_DOCUMENTATION",
    "HUMAN_RIGHTS_ATTESTATION_REQUIRED.md": "BINDING_GOVERNANCE",
    "LICENSE_DECISION_MEMO.md": "ACTIVE_DOCUMENTATION",
    "LICENSE_SCOPE.md": "ACTIVE_DOCUMENTATION",
    "NOTICE": "ACTIVE_DOCUMENTATION",
    "NOTICE_REPAIR_PLAN.md": "ACTIVE_DOCUMENTATION",
    "PUBLIC_CLAIM_LEDGER.csv": "CLAIM_LEDGER",
    "PUBLIC_DEVELOPMENT_STATUS.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "PUBLIC_PROJECTION_MANIFEST.json": "RIGHTS_OR_LINEAGE_RECORD",
    "PROJECTION_LINEAGE.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "README.md": "ACTIVE_DOCUMENTATION",
    "RIGHTS_EVIDENCE_MATRIX.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "SECURITY.md": "ACTIVE_DOCUMENTATION",
    "_triadicbrain_build_backend.py": "LICENSE_METADATA",
    "docs/evidence/rl02-repair01-main-closure.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/first-review.md": "ACTIVE_DOCUMENTATION",
    "docs/getting-started.md": "ACTIVE_DOCUMENTATION",
    "docs/index.md": "ACTIVE_DOCUMENTATION",
    "docs/investor-demo-checklist.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/investor-demo.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/investor-one-page.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/operator-runbook.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/output-guide.md": "ACTIVE_DOCUMENTATION",
    "docs/research/index.md": "ACTIVE_DOCUMENTATION",
    "docs/roadmap.md": "ACTIVE_DOCUMENTATION",
    "docs/safety-and-boundaries.md": "ACTIVE_DOCUMENTATION",
    "docs/status-matrix.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/technical/index.md": "ACTIVE_DOCUMENTATION",
    "docs/website-front-matter.md": "NEW_PUBLIC_DEVELOPMENT_DOCUMENTATION",
    "docs/whitepaper/index.md": "ACTIVE_DOCUMENTATION",
    "pyproject.toml": "LICENSE_METADATA",
    "src/triadicbrain/__init__.py": "VERSION_IDENTITY",
    "src/triadicbrain/cli.py": "RUNTIME_STATUS_REPORT",
    "src/triadicbrain/doctor.py": "RUNTIME_STATUS_REPORT",
    "src/triadicbrain/serve.py": "RUNTIME_STATUS_REPORT",
    "tests/repository_modes_test.py": "CI_OR_TEST",
    "tests/test_root_package.py": "CI_OR_TEST",
    "tools/build_docs.py": "CI_OR_TEST",
    "tools/oa01_validate.py": "CI_OR_TEST",
    "tools/run_private_alpha_ci.py": "CI_OR_TEST",
    "tools/write_projection_records.py": "RIGHTS_OR_LINEAGE_RECORD",
}
RECORD_OUTPUTS = {
    "PUBLIC_PROJECTION_MANIFEST.json",
    "PROJECTION_LINEAGE.csv",
    "RIGHTS_EVIDENCE_MATRIX.csv",
}
LINEAGE_REFRESH_PATHS = {"AGENTS.md", "README.md"}

if len(CHANGED_PATH_CLASSIFICATIONS) != 45 or len(GROUP_D_NEW_PATHS) != 8:
    raise RuntimeError("TB-PUBLIC-UX-01 changed-path contract is not 45 paths / 8 adds")


def run(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments],
        text=True,
        encoding="utf-8",
        errors="strict",
    ).strip()


def git_bytes(root: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), "show", f"{revision}:{path}"])


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
            name
            for name in directories
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


def diff_paths(root: Path, revision: str) -> set[str]:
    tracked = set(run(root, "diff", "--name-only", revision, "--").splitlines())
    untracked = set(run(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return {path.replace("\\", "/") for path in tracked | untracked if path}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_lineage(root: Path) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, REPAIR_BASE_COMMIT, "PROJECTION_LINEAGE.csv"))
    by_path = {row["projected_path"]: row for row in rows}
    if len(rows) != 109 or len(by_path) != len(rows):
        raise ValueError("repair-base lineage cardinality mismatch")
    for path in sorted(LINEAGE_REFRESH_PATHS):
        row = by_path[path]
        if row["record_status"] != "ACTIVE":
            raise ValueError(f"repair lineage row is not active: {path}")
        payload = root.joinpath(*path.split("/")).read_bytes()
        row["projected_size_bytes"] = str(len(payload))
        row["projected_sha256"] = hashlib.sha256(payload).hexdigest()
        row["public_status"] = "HOLD"
        row["public_release_eligible"] = "false"
    final = sorted(rows, key=lambda row: row["projected_path"])
    if (
        sum(row["record_status"] == "ACTIVE" for row in final) != 107
        or sum(row["record_status"] == "RETIRED" for row in final) != 2
        or any(
            row["public_status"] != "HOLD" or row["public_release_eligible"] != "false"
            for row in final
        )
    ):
        raise ValueError("TB-PUBLIC-UX-01 lineage posture mismatch")
    return final


def append_evidence(existing: str, token: str) -> str:
    values = [value.strip() for value in existing.split(";") if value.strip()]
    if token not in values:
        values.append(token)
    return "; ".join(values)


def build_rights(root: Path, files: list[str]) -> list[dict[str, str]]:
    rows = csv_rows(git_bytes(root, REPAIR_BASE_COMMIT, "RIGHTS_EVIDENCE_MATRIX.csv"))
    by_path = {row["path"]: row for row in rows}
    if len(rows) != 158 or len(by_path) != len(rows):
        raise ValueError("UX-01 base rights cardinality mismatch")

    if GROUP_D_NEW_PATHS & set(by_path):
        raise ValueError("UX-01 new Group-D path already exists in the base rights matrix")
    template = by_path["docs/first-review.md"]
    for path in sorted(GROUP_D_NEW_PATHS):
        target = root.joinpath(*path.split("/"))
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"UX-01 new Group-D source is unavailable: {path}")
        row = dict(template)
        row.update(
            {
                "path": path,
                "rights_group": "D",
                "origin": "TB-PUBLIC-UX-01 supplied repository-ready documentation",
                "origin_commit": "NOT_APPLICABLE",
                "source_identity": "TB_PUBLIC_UX01_SUPPLIED_BYTES",
                "modification_status": "NEW_TB_PUBLIC_UX01_FILE",
                "owner_evidence": (
                    "TB_PUBLIC_UX01_HUMAN_COMMISSION_AND_PACKET_PAYLOAD; "
                    "HUMAN_ATTESTATION_REQUIRED"
                ),
                "ai_assistance": "YES_OPENAI_CODEX",
                "third_party_material": (
                    "NO_KNOWN_COPIED_MATERIAL; FILE_LEVEL_REVIEW_REQUIRED"
                ),
                "inbound_license": "GENERATED_PENDING_HUMAN_RIGHTS_CONFIRMATION",
                "current_notice": "AI_ASSISTANCE_DISCLOSURE_PENDING_APPROVAL",
                "outbound_license": "MPL-2.0",
                "redistribution_authority": REDISTRIBUTION_AUTHORITY,
                "public_status": "HOLD",
                "public_release_eligible": "false",
                "required_action": "INDEPENDENT_REVIEW_BEFORE_FORMAL_RELEASE",
                "evidence_reference": f"{REPAIR_ID}:SUPPLIED_DOCUMENTATION:{path}",
                "authority_effect": "NONE",
                "record_status": "ACTIVE",
            }
        )
        rows.append(row)
        by_path[path] = row

    for path, classification in CHANGED_PATH_CLASSIFICATIONS.items():
        row = by_path.get(path)
        if row is None or row.get("record_status") != "ACTIVE":
            raise ValueError(f"UX-01 changed path lacks an active rights row: {path}")
        if path not in GROUP_D_NEW_PATHS:
            row["modification_status"] = (
                "TB_PUBLIC_UX01_REGENERATED_RECORD"
                if path in RECORD_OUTPUTS
                else "TB_PUBLIC_UX01_PUBLIC_DEVELOPMENT_RECONCILIATION"
            )
        row["owner_evidence"] = append_evidence(
            row["owner_evidence"], "TB_PUBLIC_UX01_HUMAN_COMMISSION"
        )
        row["evidence_reference"] = append_evidence(
            row["evidence_reference"], f"{REPAIR_ID}:{classification}:{path}"
        )
        if path in {"pyproject.toml", "_triadicbrain_build_backend.py", "PUBLIC_PROJECTION_MANIFEST.json"}:
            row["current_notice"] = "TB_PUBLIC_UX01_CONTAINING_DISTRIBUTION_LICENSE_EXPRESSION"
            row["outbound_license"] = "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION"

    for row in rows:
        row["public_status"] = "HOLD"
        row["public_release_eligible"] = "false"
        row["authority_effect"] = "NONE"
        row["redistribution_authority"] = REDISTRIBUTION_AUTHORITY
        row["required_action"] = "INDEPENDENT_REVIEW_BEFORE_FORMAL_RELEASE"

    final = sorted(rows, key=lambda row: row["path"])
    active_paths = {row["path"] for row in final if row["record_status"] == "ACTIVE"}
    retired_paths = {row["path"] for row in final if row["record_status"] == "RETIRED"}
    if active_paths != set(files):
        raise ValueError("UX-01 rights/source topology mismatch")
    if retired_paths != {".github/workflows/triadicgate-ci.yml", "LICENSE_NOT_YET_SELECTED.md"}:
        raise ValueError("UX-01 retired rights path mismatch")
    if (
        len(final) != 166
        or len(active_paths) != 164
        or any(row["public_status"] != "HOLD" for row in final)
        or any(row["public_release_eligible"] != "false" for row in final)
        or any(row["authority_effect"] != "NONE" for row in final)
    ):
        raise ValueError("TB-PUBLIC-UX-01 rights posture mismatch")
    return final


def build_manifest(
    root: Path,
    files: list[str],
    lineage: list[dict[str, str]],
    rights: list[dict[str, str]],
) -> dict[str, object]:
    value = json.loads(git_bytes(root, REPAIR_BASE_COMMIT, "PUBLIC_PROJECTION_MANIFEST.json"))
    if not isinstance(value, dict):
        raise ValueError("repair-base manifest is not an object")
    value.update(
        {
            "active_source_file_count": len(files),
            "candidate_label": CANDIDATE_LABEL,
            "candidate_review_status": "PENDING_INDEPENDENT_REVIEW",
            "distribution_status": "PUBLIC_DEVELOPMENT_NO_FORMAL_RELEASE",
            "formal_release_created": False,
            "human_authority_effect": (
                "PUBLIC_DEVELOPMENT_DOCUMENTATION_AND_UX_CANDIDATE_ONLY"
            ),
            "main_commit_at_phase_start": REPAIR_BASE_COMMIT,
            "main_tree_at_phase_start": REPAIR_BASE_TREE,
            "outbound_license": LICENSE_EXPRESSION,
            "outbound_license_selected": True,
            "package_published": False,
            "pages_enabled": False,
            "post_merge_ci_run": POST_MERGE_CI_RUN,
            "primary_license": "MPL-2.0",
            "public_release": False,
            "public_release_eligible": False,
            "python_distribution_version": PYTHON_VERSION,
            "remote_push": True,
            "repository_visibility": "PUBLIC",
            "reviewed_base": {"commit": REPAIR_BASE_COMMIT, "tree": REPAIR_BASE_TREE},
            "rights_active_count": sum(row["record_status"] == "ACTIVE" for row in rights),
            "rights_clear_count": sum(row["public_status"] == "CLEAR" for row in rights),
            "rights_hold_count": sum(row["public_status"] == "HOLD" for row in rights),
            "rights_retired_count": sum(row["record_status"] == "RETIRED" for row in rights),
            "rights_status": "PUBLIC_SOURCE_AVAILABLE_FORMAL_RELEASE_REMAINS_HOLD",
            "runtime_authority_effect": "NONE",
            "source_publicly_available": True,
            "successor_branch": REPAIR_BRANCH,
            "third_party_licenses": ["Unicode-3.0"],
        }
    )
    expected = {
        "active_source_file_count": len(files),
        "lineage_active_count": sum(row["record_status"] == "ACTIVE" for row in lineage),
        "lineage_retired_count": sum(row["record_status"] == "RETIRED" for row in lineage),
        "rights_active_count": 164,
        "rights_retired_count": 2,
        "rights_hold_count": 166,
        "rights_clear_count": 0,
        "mpl_license_sha256": MPL_SHA256,
        "unicode_license_sha256": UNICODE_LICENSE_SHA256,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"UX-01 manifest {key} mismatch")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.projection_root.resolve()
    if run(root, "rev-parse", "HEAD") != REPAIR_BASE_COMMIT:
        raise SystemExit("TB-PUBLIC-UX-01 base commit mismatch")
    if run(root, "rev-parse", "HEAD^{tree}") != REPAIR_BASE_TREE:
        raise SystemExit("TB-PUBLIC-UX-01 base tree mismatch")
    if run(root, "branch", "--show-current") != REPAIR_BRANCH:
        raise SystemExit("TB-PUBLIC-UX-01 branch mismatch")

    files = active_files(root)
    if len(files) != 164 or "LICENSE_NOT_YET_SELECTED.md" in files:
        raise SystemExit("TB-PUBLIC-UX-01 active-source topology mismatch")
    if sha256(root / "LICENSE") != MPL_SHA256:
        raise SystemExit("TB-PUBLIC-UX-01 MPL license identity mismatch")
    if sha256(root / "licenses" / "Unicode-3.0.txt") != UNICODE_LICENSE_SHA256:
        raise SystemExit("TB-PUBLIC-UX-01 Unicode license identity mismatch")

    prewrite_changed = diff_paths(root, REPAIR_BASE_COMMIT)
    if not prewrite_changed.issubset(CHANGED_PATH_CLASSIFICATIONS):
        raise SystemExit("TB-PUBLIC-UX-01 prewrite changed surface exceeds authorization")

    lineage = build_lineage(root)
    rights = build_rights(root, files)
    manifest = build_manifest(root, files, lineage, rights)
    outputs = {
        "PROJECTION_LINEAGE.csv": csv_bytes(list(lineage[0]), lineage),
        "RIGHTS_EVIDENCE_MATRIX.csv": csv_bytes(list(rights[0]), rights),
        "PUBLIC_PROJECTION_MANIFEST.json": (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8"),
    }
    for name, payload in outputs.items():
        (root / name).write_bytes(payload)

    observed = diff_paths(root, REPAIR_BASE_COMMIT)
    if observed != set(CHANGED_PATH_CLASSIFICATIONS):
        raise SystemExit(
            "TB-PUBLIC-UX-01 changed-path mismatch: "
            f"missing={sorted(set(CHANGED_PATH_CLASSIFICATIONS)-observed)!r} "
            f"extra={sorted(observed-set(CHANGED_PATH_CLASSIFICATIONS))!r}"
        )
    print(
        json.dumps(
            {
                "active_source_files": len(files),
                "candidate_label": CANDIDATE_LABEL,
                "delta_changed_paths": len(observed),
                "license_expression": LICENSE_EXPRESSION,
                "rights_clear": 0,
                "rights_hold": 166,
                "rights_rows": len(rights),
                "status": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
