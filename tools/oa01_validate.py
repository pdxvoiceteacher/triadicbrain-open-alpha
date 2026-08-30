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


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def files_under(root: Path) -> list[Path]:
    rows: list[Path] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(GENERATED_METADATA_SUFFIXES)
        )
        for name in sorted(files):
            path = Path(base) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"non-ordinary source member: {path}")
            rows.append(path)
    return rows


def relative(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    parsed = PurePosixPath(value)
    if value != "/".join(parsed.parts) or value.startswith("/") or ".." in parsed.parts:
        raise ValueError(f"unsafe path: {value}")
    return value


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



def check_lineage(root: Path) -> dict[str, object]:
    path = root / "PROJECTION_LINEAGE.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing PROJECTION_LINEAGE.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        projected = row.get("projected_path", "")
        if not projected or projected in seen:
            errors.append({"path": projected, "error": "missing or duplicate projected path"})
            continue
        seen.add(projected)
        target = root.joinpath(*PurePosixPath(projected).parts)
        if not target.is_file() or target.is_symlink():
            errors.append({"path": projected, "error": "projected file missing or link-like"})
            continue
        payload = target.read_bytes()
        size = str(len(payload))
        digest = hashlib.sha256(payload).hexdigest()
        if row.get("projected_size_bytes") != size:
            errors.append({"path": projected, "error": "projected size mismatch"})
        if row.get("projected_sha256") != digest:
            errors.append({"path": projected, "error": "projected SHA-256 mismatch"})
        if row.get("byte_identity") == "TRUE" and row.get("source_sha256") != digest:
            errors.append({"path": projected, "error": "declared byte identity mismatch"})
    return {"status": "PASS" if rows and not errors else "FAIL", "row_count": len(rows), "errors": errors}


def check_rights_coverage(root: Path, files: list[Path]) -> dict[str, object]:
    path = root / "RIGHTS_EVIDENCE_MATRIX.csv"
    if not path.is_file():
        return {"status": "FAIL", "error": "missing RIGHTS_EVIDENCE_MATRIX.csv"}
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    matrix_paths = [row.get("path", "") for row in rows]
    actual_paths = sorted(relative(path, root) for path in files)
    duplicates = sorted({value for value in matrix_paths if matrix_paths.count(value) > 1})
    missing = sorted(set(actual_paths) - set(matrix_paths))
    extra = sorted(set(matrix_paths) - set(actual_paths))
    invalid_posture = [
        row.get("path", "") for row in rows
        if row.get("authority_effect") != "NONE"
        or row.get("public_release_eligible") != "false"
        or row.get("public_status") != "HOLD"
    ]
    status = "PASS" if rows and not duplicates and not missing and not extra and not invalid_posture else "FAIL"
    return {
        "status": status,
        "row_count": len(rows),
        "duplicates": duplicates,
        "missing_paths": missing,
        "extra_paths": extra,
        "invalid_posture": invalid_posture,
    }

def check_git(root: Path) -> dict[str, object]:
    remotes = subprocess.check_output(["git", "-C", str(root), "remote"], text=True).splitlines()
    return {"status": "PASS" if not remotes else "FAIL", "remotes": remotes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    files = files_under(root)
    result = {
        "schema": "uvlm.oa01.source_validation.v1",
        "authority_effect": "NONE",
        "casefold": scan_casefold(root, files),
        "privacy": scan_private_content(root, files),
        "documentation": check_docs(root),
        "claims": check_claims(root),
        "lineage": check_lineage(root),
        "rights": check_rights_coverage(root, files),
        "git_remote": check_git(root),
        "source_file_count": len(files),
        "source_sha256": hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest() for p in files)).hexdigest(),
    }
    result["status"] = "PASS" if all(
        result[key]["status"] == "PASS"
        for key in (
            "casefold", "privacy", "documentation", "claims",
            "lineage", "rights", "git_remote",
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
