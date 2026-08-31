"""Provider-free OA-01 source, documentation, and boundary checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath


ALLOWED_CLAIM_STATUSES = {"IMPLEMENTED", "TESTED", "PROPOSED", "RESEARCH", "DEFERRED"}
SKIP_DIRS = {".git", ".venv", "build", "dist", "__pycache__", ".pytest_cache"}
GENERATED_METADATA_SUFFIXES = (".egg-info", ".dist-info")
TEXT_SUFFIXES = {
    ".cmd", ".csv", ".html", ".ini", ".json", ".md", ".ps1", ".py",
    ".toml", ".txt", ".yml", ".yaml",
}
REPOSITORY_MODES = {"local-source-candidate", "private-github"}
RECORD_STATUSES = {"ACTIVE", "RETIRED"}
EXPECTED_PRIVATE_ORIGIN = "pdxvoiceteacher/triadicbrain-open-alpha"
EXPECTED_SUCCESSOR_BRANCH = "rights-license/mpl-unicode-notices-01"
EXPECTED_CANDIDATE_LABEL = "v0.1.0-alpha.0-private.3-rc1"
EXPECTED_BASELINE_TAG = "v0.1.0-alpha.0-private.1"
EXPECTED_BASELINE = {
    "commit": "b278378f5add312aa8fb81a6cc1e0dc5fccc49aa",
    "tree": "aefe9503e8f0ede0d7d5ab3de9f93a8e25a3668e",
}
EXPECTED_ACTIVE_WORKFLOWS = [".github/workflows/private-alpha-ci.yml"]
EXPECTED_RETIRED_WORKFLOWS = [".github/workflows/triadicgate-ci.yml"]
EXPECTED_SUPERSEDED_WORKFLOWS = [
    ".github/workflows/oa01-linux-python312.yml",
    ".github/workflows/oa01-windows-python312.yml",
]
EXPECTED_MANIFEST_COUNTS = {
    "active_source_file_count": 156,
    "retired_source_file_count": 2,
    "lineage_active_count": 107,
    "lineage_retired_count": 2,
    "excluded_active_count": 8418,
    "excluded_retired_count": 2,
    "excluded_source_count": 8420,
    "rights_active_count": 156,
    "rights_retired_count": 2,
    "rights_hold_count": 158,
    "rights_clear_count": 0,
}
PRIVACY_METADATA_SOURCES = {
    "GITHUB_ACTIONS_EVENT_CONTEXT",
    "GITHUB_API_AUTHENTICATED",
}
RETIRED_WORKFLOW_REASON = "RETIRED_INAPPLICABLE_UPSTREAM_INTEGRATION_WORKFLOW"
RETIRED_LICENSE_REASON = "RETIRED_RL02_OBSOLETE_LICENSE_PLACEHOLDER"
EXPECTED_RETIRED_PATHS = [
    ".github/workflows/triadicgate-ci.yml",
    "LICENSE_NOT_YET_SELECTED.md",
]
MPL_LICENSE_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
UNICODE_SOURCE_SHA256 = "24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08"
REDISTRIBUTION_AUTHORITY = "HUMAN_APPROVED_RL02_CANDIDATE_PENDING_INDEPENDENT_REVIEW"
ACTION_PINS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
UNICODE_PATHS = {
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/tests/product/test_r3_actual_runtime_boundaries.py",
    "components/Sophia/python/src/sophia/triadic/totality_audit.py",
    "components/Sophia/tests/test_totality_audit.py",
    "components/uvlm-publications/python/src/atlas/triadic/totality_posture.py",
    "components/uvlm-publications/tests/test_atlas_totality_posture.py",
}
EXPECTED_UNICODE_RANGE_ROWS = (
    "(0x00AD, 0x00AD),", "(0x034F, 0x034F),", "(0x061C, 0x061C),",
    "(0x115F, 0x1160),", "(0x17B4, 0x17B5),", "(0x180B, 0x180F),",
    "(0x200B, 0x200F),", "(0x202A, 0x202E),", "(0x2060, 0x206F),",
    "(0x3164, 0x3164),", "(0xFE00, 0xFE0F),", "(0xFEFF, 0xFEFF),",
    "(0xFFA0, 0xFFA0),", "(0xFFF0, 0xFFF8),", "(0x1BCA0, 0x1BCA3),",
    "(0x1D173, 0x1D17A),", "(0xE0000, 0xE0FFF),",
)
MPL_MARKED_PATHS = {
    "components/CoherenceLattice/python/src/coherence/totality/atlas_contract.py",
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/src/coherence/totality/grounding.py",
    "components/CoherenceLattice/python/src/coherence/totality/seal.py",
    "components/CoherenceLattice/python/src/coherence/totality/ucm.py",
    "components/CoherenceLattice/python/src/coherence/totality/waveform.py",
}
CHANGED_PATH_CLASSIFICATIONS = {
    "LICENSE": "LICENSE_TEXT",
    "licenses/Unicode-3.0.txt": "LICENSE_TEXT",
    "NOTICE": "THIRD_PARTY_NOTICE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICE",
    **{path: "THIRD_PARTY_NOTICE" for path in UNICODE_PATHS},
    "AI_ASSISTANCE_DISCLOSURE.md": "DISCLOSURE",
    "CONTRIBUTORS.md": "DISCLOSURE",
    "DEPENDENCIES.md": "DISCLOSURE",
    "components/CoherenceLattice/README.md": "AMBIGUOUS_NOTICE_REPLACEMENT",
    "LICENSE_NOT_YET_SELECTED.md": "AMBIGUOUS_NOTICE_REPLACEMENT",
    "pyproject.toml": "PACKAGE_METADATA",
    "_triadicbrain_build_backend.py": "DETERMINISTIC_PACKAGING",
    ".github/workflows/private-alpha-ci.yml": "ACTION_PIN",
    "tools/oa01_validate.py": "VALIDATOR_OR_TEST",
    "tools/run_private_alpha_ci.py": "VALIDATOR_OR_TEST",
    "tests/test_root_package.py": "VALIDATOR_OR_TEST",
    "tools/write_projection_records.py": "RIGHTS_OR_LINEAGE_RECORD",
    "PROJECTION_LINEAGE.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "EXCLUDED_PATHS.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "REPLACED_PATHS.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "RIGHTS_EVIDENCE_MATRIX.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "PUBLIC_PROJECTION_MANIFEST.json": "RIGHTS_OR_LINEAGE_RECORD",
    "THIRD_PARTY_SNIPPET_AND_LICENSE_FINDINGS.csv": "RIGHTS_OR_LINEAGE_RECORD",
    "LICENSE_SCOPE.md": "VERSION_OR_STATUS_DOCUMENT",
    "README.md": "VERSION_OR_STATUS_DOCUMENT",
    "CONTRIBUTING.md": "VERSION_OR_STATUS_DOCUMENT",
    "LICENSE_DECISION_MEMO.md": "VERSION_OR_STATUS_DOCUMENT",
    "HUMAN_RIGHTS_ATTESTATION_REQUIRED.md": "VERSION_OR_STATUS_DOCUMENT",
    "NOTICE_REPAIR_PLAN.md": "VERSION_OR_STATUS_DOCUMENT",
    "docs/getting-started.md": "VERSION_OR_STATUS_DOCUMENT",
    "src/triadicbrain/__init__.py": "VERSION_OR_STATUS_DOCUMENT",
}
if len(CHANGED_PATH_CLASSIFICATIONS) != 36:
    raise RuntimeError("RL-02 changed-path classification count mismatch")
WINDOWS_REPARSE_ATTRIBUTE = 0x400


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & WINDOWS_REPARSE_ATTRIBUTE
    )


def files_under(root: Path) -> list[Path]:
    rows: list[Path] = []
    for base, dirs, files in os.walk(root):
        retained_dirs: list[str] = []
        for name in sorted(dirs):
            if name in SKIP_DIRS or name.endswith(GENERATED_METADATA_SUFFIXES):
                continue
            path = Path(base) / name
            if is_link_like(path) or not path.is_dir():
                raise ValueError(f"non-ordinary source directory: {relative(path, root)}")
            retained_dirs.append(name)
        dirs[:] = retained_dirs
        for name in sorted(files):
            path = Path(base) / name
            if is_link_like(path) or not path.is_file():
                raise ValueError(f"non-ordinary source member: {relative(path, root)}")
            rows.append(path)
    return rows


def relative(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    parsed = PurePosixPath(value)
    if value != "/".join(parsed.parts) or value.startswith("/") or ".." in parsed.parts:
        raise ValueError(f"unsafe path: {value}")
    return value


def record_target(root: Path, value: str) -> Path:
    parsed = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or value != "/".join(parsed.parts)
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("unsafe or empty record path")
    target = root.joinpath(*parsed.parts)
    current = root
    if is_link_like(current):
        raise ValueError("record root is link-like")
    for part in parsed.parts:
        current = current / part
        if is_link_like(current):
            raise ValueError("record path has a link-like component")
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise ValueError("record path resolves outside the source root") from None
    return target


def normalize_expected_origin(value: str) -> str:
    if value != value.strip() or value.count("/") != 1:
        raise ValueError("expected origin must be an owner/repository identity")
    owner, repository = value.split("/", 1)
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", owner):
        raise ValueError("expected origin owner is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repository):
        raise ValueError("expected origin repository is invalid")
    return f"{owner.casefold()}/{repository.casefold()}"


def normalize_github_origin(value: str) -> str:
    if value != value.strip() or any(character.isspace() for character in value):
        raise ValueError("remote URL has surrounding or embedded whitespace")
    patterns = (
        re.compile(
            r"https://(?:[^/@]+@)?github\.com/"
            r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/"
            r"(?P<repository>[A-Za-z0-9._-]+?)(?:\.git)?/?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"git@github\.com:"
            r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/"
            r"(?P<repository>[A-Za-z0-9._-]+?)(?:\.git)?$",
            re.IGNORECASE,
        ),
        re.compile(
            r"ssh://git@github\.com(?::22)?/"
            r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/"
            r"(?P<repository>[A-Za-z0-9._-]+?)(?:\.git)?/?$",
            re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.fullmatch(value)
        if match:
            return f"{match.group('owner').casefold()}/{match.group('repository').casefold()}"
    raise ValueError("unsupported or malformed GitHub remote URL")


def remote_url_form(value: str) -> str:
    lowered = value.casefold()
    if lowered.startswith("https://"):
        return "HTTPS"
    if lowered.startswith("git@github.com:"):
        return "SSH_SCP"
    if lowered.startswith("ssh://"):
        return "SSH_URL"
    return "INVALID"


def git_lines(root: Path, *arguments: str) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"Git command failed without exposing its output: {arguments[0]}")
    return completed.stdout.splitlines()


def describe_remote_urls(values: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    descriptions: list[dict[str, str]] = []
    normalized: list[str] = []
    for value in values:
        try:
            repository = normalize_github_origin(value)
        except ValueError:
            descriptions.append({"form": remote_url_form(value), "normalized_repository": "INVALID"})
        else:
            normalized.append(repository)
            descriptions.append({"form": remote_url_form(value), "normalized_repository": repository})
    return descriptions, normalized


def check_privacy_metadata(path: Path | None, expected_origin: str | None) -> dict[str, object]:
    if path is None:
        return {
            "status": "NOT_PROVIDED",
            "verified_private": False,
            "repository": expected_origin,
            "source": "NOT_PROVIDED",
            "authority_effect": "NONE",
            "errors": [],
        }
    errors: list[str] = []
    if path.is_symlink() or not path.is_file():
        return {
            "status": "FAIL",
            "verified_private": False,
            "repository": expected_origin,
            "source": "INVALID",
            "authority_effect": "NONE",
            "errors": ["privacy metadata is not an ordinary file"],
        }
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return {
            "status": "FAIL",
            "verified_private": False,
            "repository": expected_origin,
            "source": "INVALID",
            "authority_effect": "NONE",
            "errors": ["privacy metadata could not be read as JSON"],
        }
    if not isinstance(value, dict):
        return {
            "status": "FAIL",
            "verified_private": False,
            "repository": expected_origin,
            "source": "INVALID",
            "authority_effect": "NONE",
            "errors": ["privacy metadata is not an object"],
        }
    repository = value.get("repository")
    try:
        normalized_repository = normalize_expected_origin(repository) if isinstance(repository, str) else None
    except ValueError:
        normalized_repository = None
    required_keys = {"schema", "repository", "private", "source", "authority_effect"}
    if set(value) != required_keys:
        errors.append("privacy metadata keys mismatch")
    if value.get("schema") != "uvlm.gh01.authenticated_repository_metadata.v1":
        errors.append("privacy metadata schema mismatch")
    if normalized_repository != expected_origin:
        errors.append("privacy metadata repository mismatch")
    if value.get("private") is not True:
        errors.append("privacy metadata does not verify a private repository")
    metadata_source = value.get("source")
    if metadata_source not in PRIVACY_METADATA_SOURCES:
        errors.append("privacy metadata source is not authenticated")
    if value.get("authority_effect") != "NONE":
        errors.append("privacy metadata authority effect mismatch")
    return {
        "status": "PASS" if not errors else "FAIL",
        "verified_private": not errors,
        "repository": normalized_repository,
        "source": metadata_source if metadata_source in PRIVACY_METADATA_SOURCES else "INVALID",
        "authority_effect": "NONE",
        "errors": errors,
    }


def check_repository(
    root: Path,
    repository_mode: str,
    expected_origin: str | None,
    privacy_metadata: Path | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    if repository_mode not in REPOSITORY_MODES:
        errors.append("unsupported repository mode")
    normalized_expected: str | None = None
    if expected_origin is not None:
        try:
            normalized_expected = normalize_expected_origin(expected_origin)
        except ValueError as error:
            errors.append(str(error))
    try:
        remote_names = sorted(git_lines(root, "remote"))
    except ValueError as error:
        remote_names = []
        errors.append(str(error))
    observed: list[dict[str, object]] = []
    normalized_origin: str | None = None
    normalized_by_name: dict[str, tuple[list[str], list[str], int, int]] = {}
    for name in remote_names:
        try:
            fetch_values = git_lines(root, "remote", "get-url", "--all", name)
            push_values = git_lines(root, "remote", "get-url", "--push", "--all", name)
        except ValueError as error:
            fetch_values = []
            push_values = []
            errors.append(str(error))
        fetch_descriptions, fetch_normalized = describe_remote_urls(fetch_values)
        push_descriptions, push_normalized = describe_remote_urls(push_values)
        normalized_by_name[name] = (
            fetch_normalized,
            push_normalized,
            len(fetch_values),
            len(push_values),
        )
        observed_name = "origin" if name == "origin" else "UNEXPECTED_REMOTE"
        observed.append({
            "name": observed_name,
            "name_sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            "fetch_url_count": len(fetch_values),
            "push_url_count": len(push_values),
            "fetch_urls": fetch_descriptions,
            "push_urls": push_descriptions,
        })
    privacy = check_privacy_metadata(privacy_metadata, normalized_expected)
    if repository_mode == "local-source-candidate":
        if expected_origin is not None:
            errors.append("expected origin is not allowed in local-source-candidate mode")
        if privacy_metadata is not None:
            errors.append("privacy metadata is not allowed in local-source-candidate mode")
        if remote_names:
            errors.append("local-source-candidate mode requires no Git remotes")
    elif repository_mode == "private-github":
        if normalized_expected is None:
            errors.append("private-github mode requires a valid expected origin")
        elif normalized_expected != EXPECTED_PRIVATE_ORIGIN:
            errors.append("expected origin does not match the commissioned repository")
        if remote_names != ["origin"]:
            errors.append("private-github mode requires exactly one remote named origin")
        if remote_names == ["origin"]:
            fetch_normalized, push_normalized, fetch_count, push_count = normalized_by_name.get(
                "origin", ([], [], 0, 0)
            )
            observed_origin = (
                fetch_normalized[0]
                if fetch_count == 1 and len(fetch_normalized) == 1
                else None
            )
            observed_push = (
                push_normalized[0]
                if push_count == 1 and len(push_normalized) == 1
                else None
            )
            if observed_origin is None or observed_push is None:
                errors.append("origin must have one accepted fetch URL and one accepted push URL")
            elif observed_origin != observed_push:
                errors.append("origin fetch and push repository identities differ")
            else:
                normalized_origin = observed_origin
                if normalized_origin != normalized_expected:
                    errors.append("normalized origin does not match expected origin")
        if privacy["status"] == "FAIL":
            errors.append("authenticated privacy metadata failed validation")
    return {
        "status": "PASS" if not errors else "FAIL",
        "repository_mode": repository_mode,
        "expected_origin": normalized_expected,
        "observed_remotes": observed,
        "normalized_origin": normalized_origin,
        "privacy_verification": privacy,
        "authority_effect": "NONE",
        "errors": errors,
    }


def scan_casefold(root: Path, files: list[Path]) -> dict[str, object]:
    seen: dict[str, str] = {}
    collisions: list[list[str]] = []
    for path in files:
        rel = relative(path, root)
        key = unicodedata.normalize("NFC", rel).casefold()
        prior = seen.get(key)
        if prior is not None and prior != rel:
            collisions.append([prior, rel])
        seen[key] = rel
    return {"status": "PASS" if not collisions else "FAIL", "path_count": len(files), "collisions": collisions}


def scan_private_content(root: Path, files: list[Path]) -> dict[str, object]:
    slash = bytes((92,))
    private_prefixes = [
        b"C:" + slash + b"Users" + slash,
        b"/" + b"home" + b"/",
        b"/" + b"Users" + b"/",
        b"BEGIN " + b"PRIVATE KEY",
        b"AKIA" + b"IOSFODNN7EXAMPLE",
        b"gh" + b"p_",
        b"sk" + b"-proj-",
    ]
    findings: list[dict[str, str]] = []
    for path in files:
        rel = relative(path, root)
        data = path.read_bytes()
        for marker in private_prefixes:
            if marker.lower() in data.lower():
                findings.append({"path": rel, "category": "PRIVATE_OR_SECRET_LITERAL"})
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                findings.append({"path": rel, "category": "NON_UTF8_TEXT"})
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}


def check_docs(root: Path) -> dict[str, object]:
    required = [
        "README.md", "docs/index.md", "docs/getting-started.md", "docs/first-review.md",
        "docs/output-guide.md", "docs/safety-and-boundaries.md", "docs/roadmap.md",
        "docs/whitepaper/index.md", "docs/technical/index.md", "docs/research/index.md",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    bad_links: list[dict[str, str]] = []
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for name in required:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for raw in link_re.findall(text):
            target = raw.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                bad_links.append({"source": name, "target": raw})
                continue
            if not resolved.exists():
                bad_links.append({"source": name, "target": raw})
    return {"status": "PASS" if not missing and not bad_links else "FAIL", "missing": missing, "bad_links": bad_links}


def check_claims(root: Path) -> dict[str, object]:
    path = root / "PUBLIC_CLAIM_LEDGER.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing PUBLIC_CLAIM_LEDGER.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    invalid = [row for row in rows if row.get("status") not in ALLOWED_CLAIM_STATUSES]
    return {"status": "PASS" if rows and not invalid else "FAIL", "row_count": len(rows), "invalid_rows": invalid}



def check_lineage(root: Path, files: list[Path]) -> dict[str, object]:
    path = root / "PROJECTION_LINEAGE.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing PROJECTION_LINEAGE.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    errors: list[dict[str, str]] = []
    required_columns = {
        "source_path", "source_sha256", "projected_path", "projected_size_bytes",
        "projected_sha256", "classification", "byte_identity", "public_status",
        "public_release_eligible", "record_status",
    }
    missing_columns = sorted(required_columns - set(reader.fieldnames or []))
    if missing_columns:
        errors.append({"path": "PROJECTION_LINEAGE.csv", "error": f"missing columns: {','.join(missing_columns)}"})
    seen: set[str] = set()
    seen_source: set[str] = set()
    active_paths: list[str] = []
    retired_paths: list[str] = []
    for row in rows:
        projected = row.get("projected_path", "")
        source = row.get("source_path", "")
        if not projected or projected in seen:
            errors.append({"path": projected, "error": "missing or duplicate projected path"})
            continue
        seen.add(projected)
        if not source or source in seen_source:
            errors.append({"path": source, "error": "missing or duplicate source path"})
        else:
            seen_source.add(source)
            try:
                record_target(root, source)
            except ValueError as error:
                errors.append({"path": source, "error": str(error)})
        try:
            target = record_target(root, projected)
        except ValueError as error:
            errors.append({"path": projected, "error": str(error)})
            continue
        record_status = row.get("record_status")
        if record_status not in RECORD_STATUSES:
            errors.append({"path": projected, "error": "invalid record status"})
            continue
        for field in ("source_sha256", "projected_sha256"):
            field_value = row.get(field)
            if not isinstance(field_value, str) or not re.fullmatch(r"[0-9a-f]{64}", field_value):
                errors.append({"path": projected, "error": f"invalid {field}"})
        for field in ("source_size_bytes", "projected_size_bytes"):
            field_value = row.get(field)
            if not isinstance(field_value, str) or not re.fullmatch(r"0|[1-9][0-9]*", field_value):
                errors.append({"path": projected, "error": f"invalid {field}"})
        if row.get("public_status") != "HOLD" or row.get("public_release_eligible") != "false":
            errors.append({"path": projected, "error": "invalid rights posture"})
        if record_status == "RETIRED":
            retired_paths.append(projected)
            if target.exists() or target.is_symlink():
                errors.append({"path": projected, "error": "retired projected path is present"})
            expected_retired = {
                ".github/workflows/triadicgate-ci.yml": (
                    RETIRED_WORKFLOW_REASON, "TRUE_RETIRED_BASELINE"
                ),
                "LICENSE_NOT_YET_SELECTED.md": (
                    RETIRED_LICENSE_REASON, "TRUE_RETIRED_RL02_BASE"
                ),
            }.get(projected)
            if expected_retired is None or row.get("classification") != expected_retired[0]:
                errors.append({"path": projected, "error": "retired classification mismatch"})
            if expected_retired is None or row.get("byte_identity") != expected_retired[1]:
                errors.append({"path": projected, "error": "retired byte identity mismatch"})
            if source != projected:
                errors.append({"path": projected, "error": "retired source/projected path mismatch"})
            if row.get("source_sha256") != row.get("projected_sha256"):
                errors.append({"path": projected, "error": "retired baseline SHA-256 mismatch"})
            if row.get("source_size_bytes") != row.get("projected_size_bytes"):
                errors.append({"path": projected, "error": "retired baseline size mismatch"})
            continue
        active_paths.append(projected)
        if not target.is_file() or target.is_symlink():
            errors.append({"path": projected, "error": "active projected file missing or link-like"})
            continue
        payload = target.read_bytes()
        size = str(len(payload))
        digest = hashlib.sha256(payload).hexdigest()
        if row.get("projected_size_bytes") != size:
            errors.append({"path": projected, "error": "projected size mismatch"})
        if row.get("projected_sha256") != digest:
            errors.append({"path": projected, "error": "projected SHA-256 mismatch"})
        byte_identity = row.get("byte_identity")
        if byte_identity == "TRUE":
            if row.get("classification") not in {
                "INHERITED_HOLD_NUCLEUS",
                "ADDITIONAL_INHERITED_ROUTE_DEPENDENCY",
            }:
                errors.append({"path": projected, "error": "byte-identical classification mismatch"})
            if row.get("source_sha256") != digest or row.get("source_size_bytes") != size:
                errors.append({"path": projected, "error": "declared byte identity mismatch"})
        elif byte_identity in {
            "FALSE_REPLACED", "FALSE_GH01_SUCCESSOR_MODIFIED",
            "FALSE_RL02_PROVENANCE_COMMENT_ONLY", "FALSE_RL02_REPLACED",
        }:
            expected_classification = {
                "FALSE_REPLACED": "REPLACED_BY_OA01",
                "FALSE_GH01_SUCCESSOR_MODIFIED": "GH01_SUCCESSOR_MODIFIED",
                "FALSE_RL02_PROVENANCE_COMMENT_ONLY": "RL02_UNICODE_PROVENANCE_COMMENT_ONLY",
                "FALSE_RL02_REPLACED": "REPLACED_BY_RL02_BOUNDED_NOTICE_DOCUMENTATION",
            }[byte_identity]
            if row.get("classification") != expected_classification:
                errors.append({"path": projected, "error": "replacement classification mismatch"})
            if row.get("source_sha256") == digest:
                errors.append({"path": projected, "error": "replacement is not byte-distinct"})
        else:
            errors.append({"path": projected, "error": "invalid active byte identity"})
    if sorted(retired_paths) != EXPECTED_RETIRED_PATHS:
        errors.append({"path": "PROJECTION_LINEAGE.csv", "error": "retired path set mismatch"})
    actual_paths = {relative(path, root) for path in files}
    active_outside_source = sorted(set(active_paths) - actual_paths)
    if active_outside_source:
        errors.append({"path": "PROJECTION_LINEAGE.csv", "error": "active lineage path is outside source inventory"})
    return {
        "status": "PASS" if rows and not errors else "FAIL",
        "row_count": len(rows),
        "active_count": len(active_paths),
        "retired_count": len(retired_paths),
        "active_paths": sorted(active_paths),
        "retired_paths": sorted(retired_paths),
        "active_outside_source": active_outside_source,
        "errors": errors,
    }


def check_exclusions(root: Path) -> dict[str, object]:
    path = root / "EXCLUDED_PATHS.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing EXCLUDED_PATHS.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    errors: list[dict[str, str]] = []
    required_columns = {"source_path", "reason", "copied", "record_status"}
    missing_columns = sorted(required_columns - set(reader.fieldnames or []))
    if missing_columns:
        errors.append({"path": "EXCLUDED_PATHS.csv", "error": f"missing columns: {','.join(missing_columns)}"})
    seen: set[str] = set()
    active_count = 0
    retired_count = 0
    for row in rows:
        source = row.get("source_path", "")
        if not source or source in seen:
            errors.append({"path": source, "error": "missing or duplicate source path"})
            continue
        seen.add(source)
        try:
            target = record_target(root, source)
        except ValueError as error:
            errors.append({"path": source, "error": str(error)})
            continue
        record_status = row.get("record_status")
        if record_status not in RECORD_STATUSES:
            errors.append({"path": source, "error": "invalid record status"})
            continue
        if record_status == "ACTIVE":
            active_count += 1
        else:
            retired_count += 1
            expected_reason = {
                ".github/workflows/triadicgate-ci.yml": RETIRED_WORKFLOW_REASON,
                "LICENSE_NOT_YET_SELECTED.md": RETIRED_LICENSE_REASON,
            }.get(source)
            if expected_reason is None or row.get("reason") != expected_reason:
                errors.append({"path": source, "error": "retired reason mismatch"})
        if row.get("copied") != "false":
            errors.append({"path": source, "error": "excluded row is not marked copied=false"})
        if target.exists() or target.is_symlink():
            errors.append({"path": source, "error": "excluded source path is present"})
    retired_paths = sorted(
        row.get("source_path", "") for row in rows if row.get("record_status") == "RETIRED"
    )
    if retired_paths != EXPECTED_RETIRED_PATHS:
        errors.append({"path": "EXCLUDED_PATHS.csv", "error": "retired path set mismatch"})
    return {
        "status": "PASS" if rows and not errors else "FAIL",
        "row_count": len(rows),
        "active_count": active_count,
        "retired_count": retired_count,
        "errors": errors,
    }


def check_rights_coverage(root: Path, files: list[Path]) -> dict[str, object]:
    path = root / "RIGHTS_EVIDENCE_MATRIX.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing RIGHTS_EVIDENCE_MATRIX.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    required_columns = {
        "path", "modification_status", "public_status", "public_release_eligible",
        "outbound_license", "authority_effect", "record_status",
    }
    missing_columns = sorted(required_columns - set(reader.fieldnames or []))
    matrix_paths = [row.get("path", "") for row in rows]
    actual_paths = sorted(relative(path, root) for path in files)
    duplicates = sorted({value for value in matrix_paths if matrix_paths.count(value) > 1})
    active_rows = [row for row in rows if row.get("record_status") == "ACTIVE"]
    retired_rows = [row for row in rows if row.get("record_status") == "RETIRED"]
    invalid_status = sorted(
        row.get("path", "") for row in rows if row.get("record_status") not in RECORD_STATUSES
    )
    active_paths = [row.get("path", "") for row in active_rows]
    retired_paths = [row.get("path", "") for row in retired_rows]
    missing = sorted(set(actual_paths) - set(active_paths))
    extra = sorted(set(active_paths) - set(actual_paths))
    retired_present: list[str] = []
    unsafe_paths: list[str] = []
    for value in matrix_paths:
        try:
            target = record_target(root, value)
        except ValueError:
            unsafe_paths.append(value)
            continue
        if value in retired_paths and (target.exists() or target.is_symlink()):
            retired_present.append(value)
    invalid_posture = []
    for row in rows:
        is_active = row.get("record_status") == "ACTIVE"
        allowed_license = (
            row.get("outbound_license") in {
                "MPL-2.0", "MPL-2.0_WITH_UNICODE_LICENSE_V3_EXCEPTION"
            } if is_active else row.get("outbound_license") == "NOT_APPLICABLE_RETIRED"
        )
        if (
            row.get("authority_effect") != "NONE"
            or row.get("public_release_eligible") != "false"
            or row.get("public_status") != "HOLD"
            or not allowed_license
            or row.get("redistribution_authority") != REDISTRIBUTION_AUTHORITY
        ):
            invalid_posture.append(row.get("path", ""))
    invalid_retired = [
        row.get("path", "") for row in retired_rows
        if row.get("modification_status") not in {
            "RETIRED_IN_GH01_SUCCESSOR", "RETIRED_IN_RL02_SUCCESSOR"
        }
    ]
    invalid_active = [
        row.get("path", "") for row in active_rows
        if row.get("modification_status", "").startswith("RETIRED_IN_")
    ]
    hold_count = sum(row.get("public_status") == "HOLD" for row in rows)
    clear_count = sum(row.get("public_status") == "CLEAR" for row in rows)
    retired_path_set_mismatch = sorted(retired_paths) != EXPECTED_RETIRED_PATHS
    status = "PASS" if (
        rows
        and not missing_columns
        and not duplicates
        and not missing
        and not extra
        and not retired_present
        and not unsafe_paths
        and not invalid_status
        and not invalid_posture
        and not invalid_retired
        and not invalid_active
        and not retired_path_set_mismatch
    ) else "FAIL"
    return {
        "status": status,
        "row_count": len(rows),
        "active_count": len(active_rows),
        "retired_count": len(retired_rows),
        "hold_count": hold_count,
        "clear_count": clear_count,
        "active_paths": sorted(active_paths),
        "retired_paths": sorted(retired_paths),
        "missing_columns": missing_columns,
        "duplicates": duplicates,
        "missing_paths": missing,
        "extra_paths": extra,
        "retired_present": sorted(retired_present),
        "unsafe_paths": sorted(unsafe_paths),
        "invalid_status": invalid_status,
        "invalid_posture": invalid_posture,
        "invalid_retired": invalid_retired,
        "invalid_active": invalid_active,
        "retired_path_set_mismatch": retired_path_set_mismatch,
    }


def check_manifest(
    root: Path,
    files: list[Path],
    lineage: dict[str, object],
    exclusions: dict[str, object],
    rights: dict[str, object],
) -> dict[str, object]:
    path = root / "PUBLIC_PROJECTION_MANIFEST.json"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing PUBLIC_PROJECTION_MANIFEST.json"}
    errors: list[str] = []
    try:
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("manifest is not an object")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"status": "FAIL", "errors": [str(error)]}
    expected: dict[str, object] = {
        "schema": "uvlm.rl02.public_projection_manifest.v1",
        "candidate_label": EXPECTED_CANDIDATE_LABEL,
        "successor_branch": EXPECTED_SUCCESSOR_BRANCH,
        "reviewed_base": EXPECTED_BASELINE,
        "reviewed_baseline_tag": EXPECTED_BASELINE_TAG,
        "record_status_values": ["ACTIVE", "RETIRED"],
        "active_workflows": EXPECTED_ACTIVE_WORKFLOWS,
        "retired_workflows": EXPECTED_RETIRED_WORKFLOWS,
        "superseded_workflows": EXPECTED_SUPERSEDED_WORKFLOWS,
        "triadicgate_workflow_retirement_reason": RETIRED_WORKFLOW_REASON,
        "retired_license_placeholder_reason": RETIRED_LICENSE_REASON,
        "repository_visibility": "PRIVATE",
        "github_actions": "RESTRICTED_GITHUB_OWNED_ACTIONS_FULL_SHA_PINS_SOURCE_DEFINED",
        "remote_push": False,
        "rights_status": "HUMAN_APPROVED_IMPLEMENTATION_CANDIDATE_PENDING_INDEPENDENT_REVIEW",
        "authority_effect": "NONE",
        "runtime_authority_effect": "NONE",
        "human_authority_effect": "RIGHTS_AND_LICENSE_IMPLEMENTATION_CANDIDATE_ONLY",
        "public_release": False,
        "public_release_eligible": False,
        "outbound_license": "MPL-2.0 with Unicode License V3 exception",
        "python_distribution_version": "0.1.0a0.dev2",
        "mpl_license_sha256": MPL_LICENSE_SHA256,
        "unicode_license_sha256": UNICODE_LICENSE_SHA256,
        "unicode_ucd_source_sha256": UNICODE_SOURCE_SHA256,
        "unicode_affected_paths": sorted(UNICODE_PATHS),
        "action_pins": ACTION_PINS,
        **EXPECTED_MANIFEST_COUNTS,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"manifest {key} mismatch")
    derived = {
        "active_source_file_count": len(files),
        "retired_source_file_count": rights.get("retired_count"),
        "lineage_active_count": lineage.get("active_count"),
        "lineage_retired_count": lineage.get("retired_count"),
        "excluded_active_count": exclusions.get("active_count"),
        "excluded_retired_count": exclusions.get("retired_count"),
        "excluded_source_count": exclusions.get("row_count"),
        "rights_active_count": rights.get("active_count"),
        "rights_retired_count": rights.get("retired_count"),
        "rights_hold_count": rights.get("hold_count"),
        "rights_clear_count": rights.get("clear_count"),
    }
    for key, derived_value in derived.items():
        if value.get(key) != derived_value:
            errors.append(f"manifest {key} does not match source records")
    actual_workflows = sorted(
        relative(source, root)
        for source in files
        if relative(source, root).startswith(".github/workflows/")
    )
    if actual_workflows != EXPECTED_ACTIVE_WORKFLOWS:
        errors.append("source workflow inventory mismatch")
    for workflow in EXPECTED_ACTIVE_WORKFLOWS:
        target = record_target(root, workflow)
        if not target.is_file() or target.is_symlink():
            errors.append(f"active workflow missing: {workflow}")
    for workflow in EXPECTED_RETIRED_WORKFLOWS + EXPECTED_SUPERSEDED_WORKFLOWS:
        target = record_target(root, workflow)
        if target.exists() or target.is_symlink():
            errors.append(f"retired or superseded workflow present: {workflow}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "schema": value.get("schema"),
        "derived_counts": derived,
        "actual_workflows": actual_workflows,
        "errors": errors,
    }


def git_show_bytes(root: Path, revision: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"Git object unavailable: {revision}:{path}")
    return completed.stdout


def unicode_range_block(payload: bytes, test_path: bool) -> tuple[str, ...]:
    text = payload.decode("utf-8")
    marker = (
        "EXPECTED_DEFAULT_IGNORABLE_CODE_POINT_RANGES = ("
        if test_path else "DEFAULT_IGNORABLE_CODE_POINT_RANGES = ("
    )
    start = text.find(marker)
    if start < 0:
        raise ValueError("Unicode range marker missing")
    end = text.find("\n)", start)
    if end < 0:
        raise ValueError("Unicode range block is unterminated")
    rows = tuple(
        line.strip() for line in text[start:end].splitlines()[1:]
        if re.fullmatch(r"\(0x[0-9A-F]+, 0x[0-9A-F]+\),", line.strip())
    )
    if len(rows) != 17:
        raise ValueError("Unicode range cardinality mismatch")
    return rows


def check_rl02_surface(root: Path) -> dict[str, object]:
    errors: list[str] = []
    hashes: dict[str, str] = {}
    for relative_name, expected in (
        ("LICENSE", MPL_LICENSE_SHA256),
        ("licenses/Unicode-3.0.txt", UNICODE_LICENSE_SHA256),
    ):
        target = record_target(root, relative_name)
        if not target.is_file() or target.is_symlink():
            errors.append(f"missing exact license input: {relative_name}")
            continue
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        hashes[relative_name] = digest
        if digest != expected:
            errors.append(f"license hash mismatch: {relative_name}")

    required_documents = {
        "LICENSE_SCOPE.md", "NOTICE", "THIRD_PARTY_NOTICES.md",
        "AI_ASSISTANCE_DISCLOSURE.md", "CONTRIBUTORS.md", "DEPENDENCIES.md",
    }
    for relative_name in sorted(required_documents):
        target = record_target(root, relative_name)
        if not target.is_file() or target.is_symlink() or not target.read_bytes():
            errors.append(f"missing or empty RL-02 document: {relative_name}")
    placeholder = root / "LICENSE_NOT_YET_SELECTED.md"
    if placeholder.exists() or placeholder.is_symlink():
        errors.append("retired license placeholder remains present")

    expected_comment_parts = (
        "Unicode provenance: UCD 17.0.0 DerivedCoreProperties.txt",
        "Default_Ignorable_Code_Point; source SHA-256",
        UNICODE_SOURCE_SHA256,
        "License: Unicode License V3",
    )
    range_results: dict[str, object] = {}
    for path in sorted(UNICODE_PATHS):
        target = record_target(root, path)
        if not target.is_file() or target.is_symlink():
            errors.append(f"Unicode path missing: {path}")
            continue
        current = target.read_bytes()
        text = current.decode("utf-8")
        if any(part not in text for part in expected_comment_parts):
            errors.append(f"Unicode provenance comment mismatch: {path}")
        try:
            current_ranges = unicode_range_block(current, "/tests/" in path)
            range_results[path] = {
                "range_count": len(current_ranges),
                "unchanged": current_ranges == EXPECTED_UNICODE_RANGE_ROWS,
            }
            if current_ranges != EXPECTED_UNICODE_RANGE_ROWS:
                errors.append(f"Unicode range drift: {path}")
        except (UnicodeDecodeError, ValueError) as error:
            errors.append(f"Unicode range validation failed for {path}: {error}")

    exact_mpl_header = (
        "# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors\n"
        "# SPDX-License-Identifier: MPL-2.0\n"
    ).encode("utf-8")
    for path in sorted(MPL_MARKED_PATHS):
        target = record_target(root, path)
        if not target.is_file() or not target.read_bytes().startswith(exact_mpl_header):
            errors.append(f"MPL SPDX header mismatch: {path}")

    workflow = (root / ".github" / "workflows" / "private-alpha-ci.yml")
    uses_rows: dict[str, str] = {}
    if workflow.is_file() and not workflow.is_symlink():
        workflow_text = workflow.read_text(encoding="utf-8")
        uses_matches = re.findall(
            r"(?m)^\s*uses:\s*([^@\s]+)@([0-9a-f]{40})(?:\s+#.*)?$", workflow_text
        )
        uses_rows = dict(uses_matches)
        if len(uses_matches) != 3 or uses_rows != ACTION_PINS:
            errors.append("GitHub Actions full-SHA allowlist mismatch")
        if len(re.findall(r"(?m)^\s*uses:\s*", workflow_text)) != 3:
            errors.append("unreviewed GitHub Action use found")
    else:
        errors.append("private-alpha workflow missing")

    scope_text = (root / "LICENSE_SCOPE.md").read_text(encoding="utf-8")
    for token in (
        "MPL-2.0", "Unicode License V3", "AI-assisted material",
        "do not narrow", "public-release HOLD",
    ):
        if token not in scope_text:
            errors.append(f"license scope token missing: {token}")
    third_party_text = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for token in ("UCD 17.0.0", "Default_Ignorable_Code_Point", UNICODE_SOURCE_SHA256, UNICODE_LICENSE_SHA256):
        if token not in third_party_text:
            errors.append(f"third-party notice token missing: {token}")
    for path in UNICODE_PATHS:
        if f"`{path}`" not in third_party_text:
            errors.append(f"third-party notice path missing: {path}")

    contributor_text = (root / "CONTRIBUTORS.md").read_text(encoding="utf-8")
    for token in (
        "thomas@thomasprislac.com", "YOUR_EMAIL@example.com",
        "pdxvoiceteacher@gmail.com", "oa01@local.invalid",
        "not legal contributors",
    ):
        if token not in contributor_text:
            errors.append(f"contributor identity token missing: {token}")
    disclosure_text = (root / "AI_ASSISTANCE_DISCLOSURE.md").read_text(encoding="utf-8")
    for token in (
        "human commissioning", "selection", "integration", "testing",
        "rejection and revision", "exact-byte approval", "does not claim",
    ):
        if token not in disclosure_text:
            errors.append(f"AI disclosure token missing: {token}")

    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    for token in (
        'version = "0.1.0a0.dev2"', "dependencies = []", 'license = "MPL-2.0"',
        'license-files = ["LICENSE", "licenses/Unicode-3.0.txt"]',
    ):
        if token not in pyproject_text:
            errors.append(f"project metadata token missing: {token}")
    component_readme = (root / "components" / "CoherenceLattice" / "README.md").read_text(encoding="utf-8")
    if "and collaborators" in component_readme.casefold() or len(component_readme.encode("utf-8")) > 6000:
        errors.append("bounded CoherenceLattice README contract mismatch")

    base_probe = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{EXPECTED_BASELINE['commit']}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    changed: set[str] | None = None
    if base_probe.returncode == 0:
        try:
            changed = set(git_lines(root, "diff", "--name-only", EXPECTED_BASELINE["commit"], "--"))
            changed.update(git_lines(root, "ls-files", "--others", "--exclude-standard"))
            changed = {path.replace("\\", "/") for path in changed}
        except (OSError, subprocess.SubprocessError):
            errors.append("RL-02 changed surface unavailable")
        if changed is not None and changed != set(CHANGED_PATH_CLASSIFICATIONS):
            errors.append("RL-02 changed path ceiling or classification mismatch")

    return {
        "status": "PASS" if not errors else "FAIL",
        "license_sha256": hashes,
        "unicode_ranges": range_results,
        "action_pins": uses_rows,
        "changed_path_count": len(changed) if changed is not None else 36,
        "changed_surface_basis": "BASE_COMMIT_DIFF" if changed is not None else "CANONICAL_COMMITTED_FIXTURE",
        "changed_path_classifications": {
            path: CHANGED_PATH_CLASSIFICATIONS[path] for path in sorted(CHANGED_PATH_CLASSIFICATIONS)
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--repository-mode",
        choices=sorted(REPOSITORY_MODES),
        default="local-source-candidate",
    )
    parser.add_argument("--expected-origin")
    parser.add_argument("--privacy-metadata", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    files = files_under(root)
    repository = check_repository(
        root,
        args.repository_mode,
        args.expected_origin,
        args.privacy_metadata,
    )
    lineage = check_lineage(root, files)
    exclusions = check_exclusions(root)
    rights = check_rights_coverage(root, files)
    manifest = check_manifest(root, files, lineage, exclusions, rights)
    rl02 = check_rl02_surface(root)
    result = {
        "schema": "uvlm.rl02.source_validation.v1",
        "authority_effect": "NONE",
        "repository_mode": repository["repository_mode"],
        "expected_origin": repository["expected_origin"],
        "observed_remotes": repository["observed_remotes"],
        "normalized_origin": repository["normalized_origin"],
        "privacy_verification": repository["privacy_verification"],
        "casefold": scan_casefold(root, files),
        "privacy": scan_private_content(root, files),
        "documentation": check_docs(root),
        "claims": check_claims(root),
        "lineage": lineage,
        "exclusions": exclusions,
        "rights": rights,
        "manifest": manifest,
        "rl02_license_notice": rl02,
        "git_remote": repository,
        "source_file_count": len(files),
        "source_sha256": hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest() for p in files)).hexdigest(),
    }
    result["status"] = "PASS" if all(
        result[key]["status"] == "PASS"
        for key in (
            "casefold", "privacy", "documentation", "claims",
            "lineage", "exclusions", "rights", "manifest", "rl02_license_notice", "git_remote",
        )
    ) else "FAIL"
    data = canonical_json(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
    sys.stdout.buffer.write(data)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
