"""Regenerate the bounded RL-02 Repair01 manifest, rights, and lineage records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path, PurePosixPath


REPAIR_BASE_COMMIT = "0a269a739834944985e20273d6ee2e716d876ae2"
REPAIR_BASE_TREE = "a5c1e097a41a5adee415785a3c010318ab2d8e9a"
ORIGINAL_RL02_BASE_COMMIT = "b278378f5add312aa8fb81a6cc1e0dc5fccc49aa"
REPAIR_BRANCH = "rights-license/mpl-unicode-notices-01-repair01"
REPAIR_ID = "UVLM-TB-RL02-REPAIR-01"
CANDIDATE_LABEL = "v0.1.0-alpha.0-private.3-rc2"
PYTHON_VERSION = "0.1.0a0.dev3"
LICENSE_EXPRESSION = "MPL-2.0 AND Unicode-3.0"
MPL_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
REDISTRIBUTION_AUTHORITY = "HUMAN_APPROVED_RL02_CANDIDATE_PENDING_INDEPENDENT_REVIEW"

CHANGED_PATH_CLASSIFICATIONS = {
    "AGENTS.md": "BINDING_GOVERNANCE",
    "PUBLIC_CLAIM_LEDGER.csv": "CLAIM_LEDGER",
    "PUBLIC_PROJECTION_MANIFEST.json": "RIGHTS_OR_LINEAGE_RECORD",
    "PROJECTION_LINEAGE.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "README.md": "ACTIVE_DOCUMENTATION",
    "RIGHTS_EVIDENCE_MATRIX.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "_triadicbrain_build_backend.py": "LICENSE_METADATA",
    "docs/getting-started.md": "ACTIVE_DOCUMENTATION",
    "docs/roadmap.md": "ACTIVE_DOCUMENTATION",
    "docs/safety-and-boundaries.md": "ACTIVE_DOCUMENTATION",
    "docs/whitepaper/index.md": "ACTIVE_DOCUMENTATION",
    "pyproject.toml": "LICENSE_METADATA",
    "src/triadicbrain/__init__.py": "VERSION_IDENTITY",
    "src/triadicbrain/doctor.py": "RUNTIME_STATUS_REPORT",
    "tests/test_root_package.py": "CI_OR_TEST",
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

if len(CHANGED_PATH_CLASSIFICATIONS) != 18:
    raise RuntimeError("RL-02 Repair01 changed-path contract is not 18 paths")


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
        raise ValueError("RL-02 Repair01 lineage posture mismatch")
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
        raise ValueError("repair-base rights cardinality mismatch")

    for path, classification in CHANGED_PATH_CLASSIFICATIONS.items():
        row = by_path.get(path)
        if row is None or row.get("record_status") != "ACTIVE":
            raise ValueError(f"Repair01 changed path lacks an active rights row: {path}")
        row["modification_status"] = (
            "RL02_REPAIR01_REGENERATED_RECORD"
            if path in RECORD_OUTPUTS
            else "RL02_REPAIR01_LICENSE_POSTURE_RECONCILIATION"
        )
        row["owner_evidence"] = append_evidence(
            row["owner_evidence"], "RL02_REPAIR01_HUMAN_COMMISSION"
        )
        row["evidence_reference"] = append_evidence(
            row["evidence_reference"], f"{REPAIR_ID}:{classification}:{path}"
        )
        if path in {"pyproject.toml", "_triadicbrain_build_backend.py", "PUBLIC_PROJECTION_MANIFEST.json"}:
            row["current_notice"] = "RL02_REPAIR01_CONTAINING_DISTRIBUTION_LICENSE_EXPRESSION"
            row["outbound_license"] = "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION"

    for row in rows:
        row["public_status"] = "HOLD"
        row["public_release_eligible"] = "false"
        row["authority_effect"] = "NONE"
        if row["record_status"] == "ACTIVE" and row["redistribution_authority"] != REDISTRIBUTION_AUTHORITY:
            raise ValueError(f"active redistribution authority drift: {row['path']}")

    final = sorted(rows, key=lambda row: row["path"])
    active_paths = {row["path"] for row in final if row["record_status"] == "ACTIVE"}
    retired_paths = {row["path"] for row in final if row["record_status"] == "RETIRED"}
    if active_paths != set(files):
        raise ValueError("Repair01 rights/source topology mismatch")
    if retired_paths != {".github/workflows/triadicgate-ci.yml", "LICENSE_NOT_YET_SELECTED.md"}:
        raise ValueError("Repair01 retired rights path mismatch")
    if (
        len(final) != 158
        or len(active_paths) != 156
        or any(row["public_status"] != "HOLD" for row in final)
        or any(row["public_release_eligible"] != "false" for row in final)
        or any(row["authority_effect"] != "NONE" for row in final)
    ):
        raise ValueError("RL-02 Repair01 rights posture mismatch")
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
            "candidate_label": CANDIDATE_LABEL,
            "candidate_review_status": "PENDING_INDEPENDENT_REVIEW",
            "outbound_license": LICENSE_EXPRESSION,
            "outbound_license_selected": True,
            "primary_license": "MPL-2.0",
            "public_release": False,
            "public_release_eligible": False,
            "python_distribution_version": PYTHON_VERSION,
            "reviewed_base": {"commit": REPAIR_BASE_COMMIT, "tree": REPAIR_BASE_TREE},
            "rights_active_count": sum(row["record_status"] == "ACTIVE" for row in rights),
            "rights_clear_count": sum(row["public_status"] == "CLEAR" for row in rights),
            "rights_hold_count": sum(row["public_status"] == "HOLD" for row in rights),
            "rights_retired_count": sum(row["record_status"] == "RETIRED" for row in rights),
            "successor_branch": REPAIR_BRANCH,
            "third_party_licenses": ["Unicode-3.0"],
        }
    )
    expected = {
        "active_source_file_count": len(files),
        "lineage_active_count": sum(row["record_status"] == "ACTIVE" for row in lineage),
        "lineage_retired_count": sum(row["record_status"] == "RETIRED" for row in lineage),
        "rights_active_count": 156,
        "rights_retired_count": 2,
        "rights_hold_count": 158,
        "rights_clear_count": 0,
        "mpl_license_sha256": MPL_SHA256,
        "unicode_license_sha256": UNICODE_LICENSE_SHA256,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"Repair01 manifest {key} mismatch")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.projection_root.resolve()
    if run(root, "rev-parse", "HEAD") != REPAIR_BASE_COMMIT:
        raise SystemExit("RL-02 Repair01 base commit mismatch")
    if run(root, "rev-parse", "HEAD^{tree}") != REPAIR_BASE_TREE:
        raise SystemExit("RL-02 Repair01 base tree mismatch")
    if run(root, "branch", "--show-current") != REPAIR_BRANCH:
        raise SystemExit("RL-02 Repair01 branch mismatch")

    files = active_files(root)
    if len(files) != 156 or "LICENSE_NOT_YET_SELECTED.md" in files:
        raise SystemExit("RL-02 Repair01 active-source topology mismatch")
    if sha256(root / "LICENSE") != MPL_SHA256:
        raise SystemExit("RL-02 Repair01 MPL license identity mismatch")
    if sha256(root / "licenses" / "Unicode-3.0.txt") != UNICODE_LICENSE_SHA256:
        raise SystemExit("RL-02 Repair01 Unicode license identity mismatch")

    prewrite_changed = diff_paths(root, REPAIR_BASE_COMMIT)
    if not prewrite_changed.issubset(CHANGED_PATH_CLASSIFICATIONS):
        raise SystemExit("RL-02 Repair01 prewrite changed surface exceeds authorization")

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
            "RL-02 Repair01 changed-path mismatch: "
            f"missing={sorted(set(CHANGED_PATH_CLASSIFICATIONS)-observed)!r} "
            f"extra={sorted(observed-set(CHANGED_PATH_CLASSIFICATIONS))!r}"
        )
    cumulative = diff_paths(root, ORIGINAL_RL02_BASE_COMMIT)
    if len(cumulative) != 42:
        raise SystemExit(f"RL-02 cumulative changed-path preservation mismatch: {len(cumulative)}")

    print(
        json.dumps(
            {
                "active_source_files": len(files),
                "candidate_label": CANDIDATE_LABEL,
                "cumulative_changed_paths": len(cumulative),
                "delta_changed_paths": len(observed),
                "license_expression": LICENSE_EXPRESSION,
                "rights_clear": 0,
                "rights_hold": 158,
                "rights_rows": len(rights),
                "status": "PASS",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
