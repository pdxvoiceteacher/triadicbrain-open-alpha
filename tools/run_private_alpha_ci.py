"""Run the bounded, provider-free RL-02 Repair01 private-alpha CI contract.

All durable output is written beneath a fresh evidence root outside the source
checkout.  Build/install scratch state is also external and is removed before
the final evidence inventory is sealed.  The initial source snapshot and Git
status are treated as the baseline, so this driver can truthfully run against
an intentionally dirty pre-commit worktree as well as a clean CI checkout.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import http.client
import importlib.metadata
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit


EXPECTED_ORIGIN = "pdxvoiceteacher/triadicbrain-open-alpha"
EXPECTED_WHEEL_NAME = "triadicbrain-0.1.0a0.dev3-py3-none-any.whl"
EXPECTED_WHEEL_SHA256 = "3da8614355e40462f710b63078988bcb7c2f452b669014b22e2982e9501eee5a"
EXPECTED_SDIST_NAME = "triadicbrain-0.1.0a0.dev3.tar.gz"
EXPECTED_SDIST_SHA256 = "7acca7b5ce47ffcaed56e27d4bf2f97ee7190d5bb894bed22a70f7e346f777db"
EXPECTED_DEMO_SHA256 = "ed2ab14592d7c62a6e82658207680b56246f8c4126bbc0a8f94b3ae83d61202f"
MPL_LICENSE_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
EXPECTED_TOOL_VERSIONS = {
    "build": "1.5.0",
    "fastapi": "0.141.1",
    "httpx": "0.28.1",
    "jsonschema": "4.26.0",
    "pytest": "9.1.1",
    "setuptools": "84.0.0",
    "uvicorn": "0.52.3",
    "wheel": "0.48.0",
}
SKIP_SOURCE_DIRS = {".git", ".venv", "build", "dist", "__pycache__", ".pytest_cache"}
GENERATED_METADATA_SUFFIXES = (".egg-info", ".dist-info")
COMMAND_TIMEOUT_SECONDS = 600
GATES = (
    "python_3_12",
    "git_and_repository_context",
    "toolchain_inventory_and_pip_check",
    "root_unittest",
    "complete_pytest",
    "rl02_private_repository_validation",
    "documentation_and_links",
    "deterministic_wheel_build",
    "deterministic_sdist_build",
    "wheel_boundary_inspection",
    "clean_offline_wheel_install",
    "installed_doctor",
    "deterministic_offline_demo",
    "real_loopback_http_contract",
    "post_generation_validation",
    "source_snapshot_stability",
    "canonical_result_and_checksum_inventory",
)


class GateFailure(RuntimeError):
    """A fail-fast contract failure with a bounded public reason."""


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def remove_readonly_for_rmtree(function: Callable[[str], object], path: str, error: BaseException) -> None:
    """Retry one scratch-tree removal after clearing a Windows read-only bit."""
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    function(path)


def write_json(path: Path, value: object) -> None:
    write_new(path, canonical_json(value))


def parse_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise GateFailure(f"duplicate JSON member in {label}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict) or canonical_json(value) != payload:
        raise GateFailure(f"non-canonical JSON object in {label}")
    return value


def read_canonical_object(path: Path) -> dict[str, Any]:
    return parse_canonical_object(path.read_bytes(), path.name)


def bounded_detail(exc: BaseException) -> str:
    if isinstance(exc, GateFailure):
        text = str(exc)
    else:
        text = f"{type(exc).__name__}: unexpected gate failure"
    token_pattern = r"(?i)(?:gh" + r"[opusr]_[A-Za-z0-9_]+|github" + r"_pat_[A-Za-z0-9_]+)"
    text = re.sub(token_pattern, "<redacted>", text)
    text = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1<redacted>@", text)
    return text[:500]


def outside(child: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath([os.path.normcase(str(child)), os.path.normcase(str(parent))])
    except ValueError:
        return True
    return common != os.path.normcase(str(parent))


def safe_relative(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    parsed = PurePosixPath(value)
    if not value or value.startswith("/") or value != "/".join(parsed.parts) or ".." in parsed.parts:
        raise GateFailure("unsafe source-relative path")
    return value


def source_files(root: Path) -> list[Path]:
    rows: list[Path] = []
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        kept: list[str] = []
        for name in sorted(dirs):
            path = base_path / name
            if name in SKIP_SOURCE_DIRS or name.endswith(GENERATED_METADATA_SUFFIXES):
                continue
            if path.is_symlink() or not path.is_dir():
                raise GateFailure(f"non-ordinary source directory: {safe_relative(path, root)}")
            kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            path = base_path / name
            if path.is_symlink() or not path.is_file():
                raise GateFailure(f"non-ordinary source file: {safe_relative(path, root)}")
            rows.append(path)
    rows.sort(key=lambda path: safe_relative(path, root))
    return rows


def source_snapshot(root: Path) -> dict[str, Any]:
    files = source_files(root)
    seen: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for path in files:
        relative = safe_relative(path, root)
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in seen:
            raise GateFailure(f"source path normalization collision: {seen[key]} / {relative}")
        seen[key] = relative
        payload = path.read_bytes()
        rows.append({"bytes": len(payload), "path": relative, "sha256": sha256_bytes(payload)})
    digest = sha256_bytes(canonical_json(rows))
    return {"file_count": len(rows), "files": rows, "inventory_sha256": digest}


def tree_snapshot(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise GateFailure("artifact tree is unavailable or link-like")
    rows: list[dict[str, Any]] = []
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        for name in dirs:
            path = base_path / name
            if path.is_symlink() or not path.is_dir():
                raise GateFailure("artifact tree contains a non-ordinary directory")
        for name in files:
            path = base_path / name
            if path.is_symlink() or not path.is_file():
                raise GateFailure("artifact tree contains a non-ordinary file")
            payload = path.read_bytes()
            rows.append(
                {
                    "bytes": len(payload),
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_bytes(payload),
                }
            )
    rows.sort(key=lambda row: row["path"])
    return {
        "file_count": len(rows),
        "files": rows,
        "inventory_sha256": sha256_bytes(canonical_json(rows)),
    }


def describe_remote(raw: str) -> dict[str, Any]:
    """Return useful remote identity without retaining credentials or query data."""
    raw = raw.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        return {
            "host": (parsed.hostname or "").lower(),
            "kind": "URL",
            "path": parsed.path.rstrip("/"),
            "query_present": bool(parsed.query),
            "scheme": parsed.scheme.lower(),
            "userinfo_present": parsed.username is not None or parsed.password is not None,
        }
    match = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", raw)
    if match:
        return {"host": match.group(1).lower(), "kind": "SCP_LIKE", "path": "/" + match.group(2).rstrip("/")}
    return {"kind": "LOCAL_OR_OTHER", "terminal_name": Path(raw).name}


def source_environment(base: dict[str, str], root: Path) -> dict[str, str]:
    """Prepend the governed source roots while preserving the caller environment."""
    value = base.copy()
    source_roots = [
        root / "src",
        root / "components" / "CoherenceLattice" / "python" / "src",
        root / "components" / "Sophia" / "python" / "src",
        root / "components" / "uvlm-publications" / "python" / "src",
    ]
    inherited = value.get("PYTHONPATH")
    entries = [str(path) for path in source_roots]
    if inherited:
        entries.append(inherited)
    value["PYTHONPATH"] = os.pathsep.join(entries)
    return value


class Runner:
    def __init__(self, root: Path, evidence: Path, scratch: Path, mode: str, expected_origin: str) -> None:
        self.root = root
        self.evidence = evidence
        self.scratch = scratch
        self.mode = mode
        self.expected_origin = expected_origin
        self.initial_snapshot: dict[str, Any] | None = None
        self.initial_status = b""
        self.initial_head = ""
        self.initial_tree = ""
        self.initial_remotes: list[dict[str, Any]] = []
        self.privacy_metadata: Path | None = None
        self.initial_validation: dict[str, Any] | None = None
        self.wheel_a: Path | None = None
        self.sdist_a: Path | None = None
        self.venv_python: Path | None = None
        self.demo_a: Path | None = None
        self.gates = [
            {"gate": index, "name": name, "status": "PENDING"}
            for index, name in enumerate(GATES, start=1)
        ]
        self.env = os.environ.copy()
        self.env.update(
            {
                "NO_PROXY": "127.0.0.1,localhost,::1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_CACHE_DIR": "1",
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            }
        )
        self.env.pop("PYTHONHOME", None)
        self.source_env = source_environment(self.env, self.root)

    def command(
        self,
        command_id: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout: int = COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[bytes]:
        if not re.fullmatch(r"[a-z0-9_]+", command_id):
            raise GateFailure("invalid command identifier")
        command_dir = self.evidence / "commands"
        command_dir.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd or self.root,
                env=env or self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            write_new(command_dir / f"{command_id}.stdout.bin", stdout)
            write_new(command_dir / f"{command_id}.stderr.bin", stderr)
            write_json(
                command_dir / f"{command_id}.json",
                {"argv": argv, "command_id": command_id, "returncode": None, "status": "TIMEOUT"},
            )
            raise GateFailure(f"command timeout: {command_id}") from exc
        write_new(command_dir / f"{command_id}.stdout.bin", completed.stdout)
        write_new(command_dir / f"{command_id}.stderr.bin", completed.stderr)
        write_json(
            command_dir / f"{command_id}.json",
            {
                "argv": argv,
                "command_id": command_id,
                "returncode": completed.returncode,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
            },
        )
        if check and completed.returncode != 0:
            raise GateFailure(f"command failed: {command_id} (exit {completed.returncode})")
        return completed

    def git(self, command_id: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return self.command(command_id, ["git", "-C", str(self.root), *args], check=check)

    def run_gate(self, number: int, callback: Callable[[], dict[str, Any]]) -> None:
        row = self.gates[number - 1]
        try:
            details = callback()
        except BaseException as exc:
            row["status"] = "FAIL"
            row["detail"] = bounded_detail(exc)
            raise
        row["status"] = "PASS"
        row["evidence"] = details

    def gate_01(self) -> dict[str, Any]:
        if sys.version_info[:2] != (3, 12):
            raise GateFailure("Python 3.12 is required")
        value = {
            "implementation": sys.implementation.name,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
        }
        write_json(self.evidence / "python_runtime.json", value)
        return value

    def _private_context(self) -> dict[str, Any] | None:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return None
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        event_path_raw = os.environ.get("GITHUB_EVENT_PATH", "")
        if repository.casefold() != self.expected_origin.casefold() or not event_path_raw:
            raise GateFailure("GitHub repository context does not match the expected private origin")
        event_path = Path(event_path_raw)
        payload = event_path.read_bytes()
        if len(payload) > 4 * 1024 * 1024:
            raise GateFailure("GitHub event context exceeds the bounded metadata limit")
        try:
            event = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateFailure("GitHub event context is invalid JSON") from exc
        repository_object = event.get("repository") if isinstance(event, dict) else None
        if not isinstance(repository_object, dict) or repository_object.get("private") is not True:
            raise GateFailure("GitHub event context does not attest a private repository")
        full_name = repository_object.get("full_name", repository)
        if not isinstance(full_name, str) or full_name.casefold() != self.expected_origin.casefold():
            raise GateFailure("GitHub event repository identity mismatch")
        metadata = {
            "authority_effect": "NONE",
            "private": True,
            "repository": self.expected_origin,
            "schema": "uvlm.gh01.authenticated_repository_metadata.v1",
            "source": "GITHUB_ACTIONS_EVENT_CONTEXT",
        }
        path = self.evidence / "github_private_repository_metadata.json"
        write_json(path, metadata)
        self.privacy_metadata = path
        return {"event_name": event_name, "metadata_path": path.name, **metadata}

    def _remote_rows(self, command_id: str) -> list[dict[str, Any]]:
        remote_names_raw = self.git(command_id, "remote").stdout.decode("utf-8", errors="strict")
        remote_rows: list[dict[str, Any]] = []
        for name in sorted(filter(None, remote_names_raw.splitlines())):
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise GateFailure("unsafe Git remote name")
            descriptions: dict[str, list[dict[str, Any]]] = {}
            for role, role_arguments in (("fetch", []), ("push", ["--push"])):
                completed = subprocess.run(
                    ["git", "-C", str(self.root), "remote", "get-url", *role_arguments, "--all", name],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=self.env,
                    check=False,
                    timeout=30,
                )
                if completed.returncode != 0:
                    raise GateFailure("unable to read configured Git remote")
                urls = completed.stdout.decode("utf-8", errors="strict").splitlines()
                descriptions[f"{role}_locations"] = [describe_remote(value) for value in urls]
            remote_rows.append({"name": name, **descriptions})
        return remote_rows

    def gate_02(self) -> dict[str, Any]:
        self.initial_snapshot = source_snapshot(self.root)
        write_json(self.evidence / "initial_source_snapshot.json", self.initial_snapshot)
        self.initial_head = self.git("git_head", "rev-parse", "HEAD").stdout.decode("ascii").strip()
        self.initial_tree = self.git("git_tree", "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
        status = self.git("git_status_initial", "status", "--porcelain=v1", "-z").stdout
        self.initial_status = status
        remote_rows = self._remote_rows("git_remote_names")
        self.initial_remotes = remote_rows
        private_context = self._private_context()
        value = {
            "commit": self.initial_head,
            "initial_status_sha256": sha256_bytes(status),
            "initial_status_rows": status.count(b"\0"),
            "private_repository_context": private_context or {
                "authority_effect": "NONE",
                "source": "NOT_SUPPLIED_OUTSIDE_GITHUB_ACTIONS",
                "status": "NOT_VERIFIED_BY_DRIVER",
            },
            "remotes": remote_rows,
            "tree": self.initial_tree,
        }
        write_json(self.evidence / "repository_context.json", value)
        return value

    def gate_03(self) -> dict[str, Any]:
        actual: dict[str, str] = {}
        for name, expected in EXPECTED_TOOL_VERSIONS.items():
            try:
                actual[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError as exc:
                raise GateFailure(f"required CI tool is absent: {name}") from exc
            if actual[name] != expected:
                raise GateFailure(f"CI tool version mismatch: {name}")
        self.command("pip_list", [sys.executable, "-m", "pip", "list", "--format=json"])
        self.command("pip_check", [sys.executable, "-m", "pip", "check"])
        value = {"status": "PASS", "versions": actual}
        write_json(self.evidence / "toolchain_inventory.json", value)
        return value

    def gate_04(self) -> dict[str, Any]:
        self.command(
            "root_unittest",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            env=self.source_env,
        )
        return {"command": "root_unittest"}

    def gate_05(self) -> dict[str, Any]:
        self.command(
            "complete_pytest",
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            env=self.source_env,
        )
        return {"command": "complete_pytest", "plugin_autoload": False}

    def _validator_argv(self, output: Path, mode: str, root: Path | None = None) -> list[str]:
        script = (root or self.root) / "tools" / "oa01_validate.py"
        argv = [
            sys.executable,
            str(script),
            "--root",
            str(root or self.root),
            "--repository-mode",
            mode,
        ]
        if mode == "private-github":
            argv.extend(["--expected-origin", self.expected_origin])
            if self.privacy_metadata is not None:
                argv.extend(["--privacy-metadata", str(self.privacy_metadata)])
        argv.extend(["--output", str(output)])
        return argv

    def _require_validation_pass(self, path: Path) -> dict[str, Any]:
        value = read_canonical_object(path)
        if value.get("status") != "PASS" or value.get("authority_effect") != "NONE":
            raise GateFailure(f"source validation did not pass: {path.name}")
        return value

    def _local_validator_test(self) -> dict[str, Any]:
        if self.initial_snapshot is None:
            raise GateFailure("initial source snapshot unavailable")
        checkout = self.scratch / "local-no-remote-checkout"
        checkout.mkdir()
        for row in self.initial_snapshot["files"]:
            relative = row["path"]
            source = self.root.joinpath(*PurePosixPath(relative).parts)
            payload = source.read_bytes()
            if len(payload) != row["bytes"] or sha256_bytes(payload) != row["sha256"]:
                raise GateFailure("source changed while creating local validator fixture")
            target = checkout.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, payload)
        self.command("local_git_init", ["git", "init", "--quiet", "--initial-branch=main"], cwd=checkout)
        fixture_env = source_environment(self.env, checkout)
        fixture_email = "gh01-validator" + chr(64) + "invalid.example"
        fixture_env.update(
            {
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                "GIT_AUTHOR_EMAIL": fixture_email,
                "GIT_AUTHOR_NAME": "GH-01 Validator Fixture",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
                "GIT_COMMITTER_EMAIL": fixture_email,
                "GIT_COMMITTER_NAME": "GH-01 Validator Fixture",
            }
        )
        self.command(
            "local_git_add",
            ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "add", "--all"],
            cwd=checkout,
            env=fixture_env,
        )
        self.command(
            "local_git_commit",
            ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "--no-verify", "-m", "GH-01 local validator fixture"],
            cwd=checkout,
            env=fixture_env,
        )
        remotes = self.command("local_git_remotes", ["git", "remote"], cwd=checkout).stdout
        if remotes != b"":
            raise GateFailure("local validator fixture unexpectedly has a remote")
        status = self.command(
            "local_git_status", ["git", "status", "--porcelain=v1", "-z"], cwd=checkout
        ).stdout
        if status != b"":
            raise GateFailure("local validator fixture is not a clean worktree")
        output = self.evidence / "local_source_candidate_validation.json"
        completed = self.command(
            "local_source_validation",
            self._validator_argv(output, "local-source-candidate", checkout),
            cwd=checkout,
            env=fixture_env,
        )
        if completed.stdout != output.read_bytes():
            raise GateFailure("local validator stdout/output identity mismatch")
        value = self._require_validation_pass(output)
        return {"mode": "local-source-candidate", "remote_count": 0, "source_file_count": value.get("source_file_count")}

    def gate_06(self) -> dict[str, Any]:
        output = self.evidence / "private_repository_validation_initial.json"
        completed = self.command(
            "private_validation_initial",
            self._validator_argv(output, self.mode),
            env=self.source_env,
        )
        if completed.stdout != output.read_bytes():
            raise GateFailure("initial validator stdout/output identity mismatch")
        value = self._require_validation_pass(output)
        self.initial_validation = value
        local = self._local_validator_test()
        return {
            "local_no_remote_test": local,
            "mode": self.mode,
            "privacy_verification": value.get("privacy_verification", "NOT_REPORTED"),
        }

    def gate_07(self) -> dict[str, Any]:
        if self.initial_validation is None or self.initial_validation.get("documentation", {}).get("status") != "PASS":
            raise GateFailure("documentation/link validation was not PASS")
        output = self.evidence / "documentation"
        completed = self.command(
            "documentation_build",
            [sys.executable, str(self.root / "tools" / "build_docs.py"), "--root", str(self.root), "--output", str(output)],
        )
        manifest_bytes = (output / "documentation_build.json").read_bytes()
        if not manifest_bytes.endswith(b"\n") or b"\r" in manifest_bytes:
            raise GateFailure("documentation build manifest is not canonical LF JSON")
        expected_stdout = manifest_bytes[:-1] + (b"\r\n" if os.name == "nt" else b"\n")
        if completed.stdout != expected_stdout:
            raise GateFailure("documentation builder stdout/manifest identity mismatch")
        manifest = read_canonical_object(output / "documentation_build.json")
        files = manifest.get("files")
        if manifest.get("status") != "PASS" or not isinstance(files, list) or len(files) != 10:
            raise GateFailure("documentation build manifest is incomplete")
        for row in files:
            if not isinstance(row, dict) or not isinstance(row.get("output"), str):
                raise GateFailure("documentation build row is invalid")
            target = output.joinpath(*PurePosixPath(row["output"]).parts)
            if not target.is_file() or target.is_symlink() or target.stat().st_size != row.get("bytes"):
                raise GateFailure("documentation build output identity mismatch")
        return {"file_count": len(files), "manifest": "documentation/documentation_build.json"}

    def _only_file(self, directory: Path, expected_name: str) -> Path:
        rows = list(directory.iterdir())
        if len(rows) != 1 or rows[0].name != expected_name or rows[0].is_symlink() or not rows[0].is_file():
            raise GateFailure(f"unexpected build output topology: {directory.name}")
        return rows[0]

    def gate_08(self) -> dict[str, Any]:
        first = self.evidence / "build" / "wheel-a"
        second = self.evidence / "build" / "wheel-b"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        for command_id, target in (("wheel_build_a", first), ("wheel_build_b", second)):
            self.command(
                command_id,
                [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(target), str(self.root)],
                cwd=self.scratch,
            )
        wheel_a = self._only_file(first, EXPECTED_WHEEL_NAME)
        wheel_b = self._only_file(second, EXPECTED_WHEEL_NAME)
        payload = wheel_a.read_bytes()
        if payload != wheel_b.read_bytes() or sha256_bytes(payload) != EXPECTED_WHEEL_SHA256:
            raise GateFailure("wheel reproducibility or expected identity mismatch")
        self.wheel_a = wheel_a
        return {"bytes": len(payload), "name": wheel_a.name, "sha256": sha256_bytes(payload)}

    def gate_09(self) -> dict[str, Any]:
        first = self.evidence / "build" / "sdist-a"
        second = self.evidence / "build" / "sdist-b"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        for command_id, target in (("sdist_build_a", first), ("sdist_build_b", second)):
            self.command(
                command_id,
                [sys.executable, "-m", "build", "--no-isolation", "--sdist", "--outdir", str(target), str(self.root)],
                cwd=self.scratch,
            )
        sdist_a = self._only_file(first, EXPECTED_SDIST_NAME)
        sdist_b = self._only_file(second, EXPECTED_SDIST_NAME)
        payload = sdist_a.read_bytes()
        if payload != sdist_b.read_bytes() or sha256_bytes(payload) != EXPECTED_SDIST_SHA256:
            raise GateFailure("sdist reproducibility or expected identity mismatch")
        with tarfile.open(sdist_a, "r:gz") as archive:
            names = archive.getnames()
            if names != sorted(names) or len(names) != len(set(names)):
                raise GateFailure("sdist member order or uniqueness mismatch")
            root = "triadicbrain-0.1.0a0.dev3"
            required = {
                f"{root}/LICENSE": MPL_LICENSE_SHA256,
                f"{root}/licenses/Unicode-3.0.txt": UNICODE_LICENSE_SHA256,
            }
            required_documents = {
                "AI_ASSISTANCE_DISCLOSURE.md", "CONTRIBUTORS.md", "DEPENDENCIES.md",
                "LICENSE", "LICENSE_SCOPE.md", "NOTICE", "THIRD_PARTY_NOTICES.md",
                "licenses/Unicode-3.0.txt",
            }
            for relative in required_documents:
                if f"{root}/{relative}" not in names:
                    raise GateFailure(f"sdist required document missing: {relative}")
            for name, expected in required.items():
                extracted = archive.extractfile(name)
                if extracted is None or sha256_bytes(extracted.read()) != expected:
                    raise GateFailure(f"sdist license identity mismatch: {name}")
            pkg_info = archive.extractfile(f"{root}/PKG-INFO")
            if pkg_info is None:
                raise GateFailure("sdist PKG-INFO missing")
            metadata = pkg_info.read().decode("utf-8", errors="strict")
            if (
                "\nRequires-Dist:" in "\n" + metadata
                or metadata.count("License-Expression: MPL-2.0 AND Unicode-3.0\n") != 1
                or "Classifier: License :: OSI Approved :: Mozilla Public License 2.0" in metadata
            ):
                raise GateFailure("sdist dependency or license metadata mismatch")
        self.sdist_a = sdist_a
        return {
            "bytes": len(payload), "member_count": len(names),
            "name": sdist_a.name, "sha256": sha256_bytes(payload),
        }

    def gate_10(self) -> dict[str, Any]:
        if self.wheel_a is None:
            raise GateFailure("wheel artifact unavailable")
        with zipfile.ZipFile(self.wheel_a, "r") as archive:
            if archive.comment or archive.testzip() is not None:
                raise GateFailure("wheel CRC or archive-comment check failed")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if names != sorted(names) or len(names) != len(set(names)):
                raise GateFailure("wheel members are not uniquely sorted")
            normalized: set[str] = set()
            for info in infos:
                parsed = PurePosixPath(info.filename)
                key = unicodedata.normalize("NFC", info.filename).casefold()
                if (
                    info.is_dir()
                    or info.filename.startswith("/")
                    or info.filename != "/".join(parsed.parts)
                    or ".." in parsed.parts
                    or key in normalized
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.extra
                    or info.comment
                    or info.flag_bits & 1
                ):
                    raise GateFailure("wheel member safety or determinism check failed")
                normalized.add(key)
                mode = info.external_attr >> 16
                if info.create_system != 3 or stat.S_IFMT(mode) != stat.S_IFREG or stat.S_IMODE(mode) != 0o644:
                    raise GateFailure("wheel member metadata check failed")
            roots = {name.split("/", 1)[0] for name in names}
            dist_info = "triadicbrain-0.1.0a0.dev3.dist-info"
            if roots != {"atlas", "coherence", "sophia", "triadicbrain", dist_info}:
                raise GateFailure("wheel package boundary mismatch")
            if any(
                part in {"components", "integration", "tests", "__pycache__"} or part.endswith((".pyc", ".pyo"))
                for name in names
                for part in PurePosixPath(name).parts
            ):
                raise GateFailure("wheel contains excluded source or cache content")
            metadata = archive.read(f"{dist_info}/METADATA").decode("utf-8", errors="strict")
            if (
                "\nRequires-Dist:" in "\n" + metadata
                or "Metadata-Version: 2.4\n" not in metadata
                or "Name: triadicbrain\n" not in metadata
                or "Version: 0.1.0a0.dev3\n" not in metadata
                or metadata.count("License-Expression: MPL-2.0 AND Unicode-3.0\n") != 1
                or "License-File: LICENSE\n" not in metadata
                or "License-File: licenses/Unicode-3.0.txt\n" not in metadata
                or "Classifier: License :: OSI Approved :: Mozilla Public License 2.0" in metadata
            ):
                raise GateFailure("wheel dependency or identity metadata mismatch")
            license_members = {
                f"{dist_info}/licenses/LICENSE": MPL_LICENSE_SHA256,
                f"{dist_info}/licenses/licenses/Unicode-3.0.txt": UNICODE_LICENSE_SHA256,
            }
            for name, expected in license_members.items():
                if name not in names or sha256_bytes(archive.read(name)) != expected:
                    raise GateFailure(f"wheel license identity mismatch: {name}")
            record_name = f"{dist_info}/RECORD"
            record_rows = list(csv.reader(archive.read(record_name).decode("utf-8", errors="strict").splitlines()))
            if len(record_rows) != len(names) or any(len(row) != 3 for row in record_rows):
                raise GateFailure("wheel RECORD shape mismatch")
            records = {row[0]: row[1:] for row in record_rows}
            if set(records) != set(names) or records.get(record_name) != ["", ""]:
                raise GateFailure("wheel RECORD coverage mismatch")
            for name in names:
                if name == record_name:
                    continue
                payload = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode("ascii")
                if records[name] != [f"sha256={encoded}", str(len(payload))]:
                    raise GateFailure("wheel RECORD identity mismatch")
        value = {"member_count": len(names), "record_count": len(record_rows), "status": "PASS"}
        write_json(self.evidence / "wheel_inspection.json", value)
        return value

    def _isolated_env(self) -> dict[str, str]:
        value = self.env.copy()
        value.pop("PYTHONPATH", None)
        value["PYTHONNOUSERSITE"] = "1"
        return value

    def gate_11(self) -> dict[str, Any]:
        if self.wheel_a is None:
            raise GateFailure("wheel artifact unavailable")
        venv_root = self.scratch / "wheel-install-venv"
        self.command(
            "create_install_venv",
            [sys.executable, "-m", "venv", str(venv_root)],
            cwd=self.scratch,
            env=self._isolated_env(),
        )
        venv_python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not venv_python.is_file():
            raise GateFailure("fresh virtual environment Python is unavailable")
        isolated = self._isolated_env()
        self.command(
            "offline_wheel_install",
            [str(venv_python), "-m", "pip", "install", "--no-index", "--no-deps", str(self.wheel_a)],
            cwd=self.scratch,
            env=isolated,
        )
        probe = (
            "import importlib, json, pathlib; "
            "names=('triadicbrain','coherence','sophia','atlas'); "
            "rows={n:str(pathlib.Path(importlib.import_module(n).__file__).resolve()) for n in names}; "
            "print(json.dumps(rows,sort_keys=True,separators=(',',':')))"
        )
        completed = self.command(
            "installed_import_probe",
            [str(venv_python), "-I", "-B", "-c", probe],
            cwd=self.scratch,
            env=isolated,
        )
        try:
            modules = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateFailure("installed import probe output is invalid") from exc
        venv_resolved = venv_root.resolve()
        if set(modules) != {"triadicbrain", "coherence", "sophia", "atlas"}:
            raise GateFailure("installed import set mismatch")
        for module_path in modules.values():
            try:
                Path(module_path).resolve().relative_to(venv_resolved)
            except ValueError as exc:
                raise GateFailure("installed module resolved outside the fresh environment") from exc
        self.venv_python = venv_python
        return {"dependency_install": "--no-index --no-deps", "imported_packages": sorted(modules)}

    def gate_12(self) -> dict[str, Any]:
        if self.venv_python is None:
            raise GateFailure("installed Python unavailable")
        completed = self.command(
            "installed_doctor",
            [str(self.venv_python), "-I", "-B", "-m", "triadicbrain", "doctor"],
            cwd=self.scratch,
            env=self._isolated_env(),
        )
        value = parse_canonical_object(completed.stdout, "doctor stdout")
        expected_rights_posture = {
            "candidate_review_status": "PENDING_INDEPENDENT_REVIEW",
            "outbound_license_selected": True,
            "primary_license": "MPL-2.0",
            "public_release_eligible": False,
            "status": "HOLD",
            "third_party_licenses": ["Unicode-3.0"],
        }
        if (
            value.get("authority_effect") != "NONE"
            or value.get("optional_ollama", {}).get("provider_contacted") is not False
            or value.get("rights_posture") != expected_rights_posture
            or value.get("side_effects", {}).get("network_used") is not False
        ):
            raise GateFailure("doctor authority, provider, rights, or network posture mismatch")
        write_json(self.evidence / "doctor_verified.json", value)
        return {
            "license_expression": "MPL-2.0 AND Unicode-3.0",
            "provider_contacted": False,
            "public_release_eligible": False,
            "rights_posture": expected_rights_posture,
        }

    def gate_13(self) -> dict[str, Any]:
        if self.venv_python is None:
            raise GateFailure("installed Python unavailable")
        first = self.evidence / "demo-a"
        second = self.evidence / "demo-b"
        results: list[dict[str, Any]] = []
        for command_id, target in (("offline_demo_a", first), ("offline_demo_b", second)):
            completed = self.command(
                command_id,
                [str(self.venv_python), "-I", "-B", "-m", "triadicbrain", "demo", "--output", str(target)],
                cwd=self.scratch,
                env=self._isolated_env(),
            )
            value = parse_canonical_object(completed.stdout, f"{command_id} stdout")
            if (
                value.get("artifact_set_sha256") != EXPECTED_DEMO_SHA256
                or value.get("provider_invoked") is not False
                or value.get("authority_effect") != "NONE"
                or value.get("artifact_count") != 9
            ):
                raise GateFailure("demo identity or authority contract mismatch")
            results.append(value)
        snapshot_a = tree_snapshot(first)
        snapshot_b = tree_snapshot(second)
        if snapshot_a != snapshot_b or snapshot_a["file_count"] != 9 or results[0] != results[1]:
            raise GateFailure("demo runs are not byte-identical")
        self.demo_a = first
        value = {
            "artifact_count": 9,
            "artifact_set_sha256": EXPECTED_DEMO_SHA256,
            "tree_inventory_sha256": snapshot_a["inventory_sha256"],
        }
        write_json(self.evidence / "demo_reproducibility.json", value)
        return value

    @staticmethod
    def _http_request(port: int, method: str, path: str, host: str, origin: str | None = None) -> dict[str, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host)
            if origin is not None:
                connection.putheader("Origin", origin)
            connection.putheader("Connection", "close")
            connection.endheaders()
            response = connection.getresponse()
            body = response.read()
            headers = {key.lower(): value for key, value in response.getheaders()}
            return {
                "body_bytes": len(body),
                "body_sha256": sha256_bytes(body),
                "headers": {
                    key: headers.get(key)
                    for key in (
                        "cache-control",
                        "content-security-policy",
                        "cross-origin-resource-policy",
                        "referrer-policy",
                        "x-content-type-options",
                        "x-frame-options",
                    )
                },
                "status": response.status,
            }
        finally:
            connection.close()

    def gate_14(self) -> dict[str, Any]:
        if self.venv_python is None or self.demo_a is None:
            raise GateFailure("installed server inputs unavailable")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        argv = [
            str(self.venv_python),
            "-I",
            "-B",
            "-m",
            "triadicbrain",
            "serve",
            "--run-root",
            str(self.demo_a),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        process = subprocess.Popen(
            argv,
            cwd=self.scratch,
            env=self._isolated_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        responses: dict[str, dict[str, Any]] = {}
        returncode: int | None = None
        stdout = b""
        stderr = b""
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise GateFailure("loopback server exited before readiness")
                try:
                    responses["health"] = self._http_request(port, "GET", "/health", f"127.0.0.1:{port}")
                    break
                except (ConnectionRefusedError, ConnectionResetError, OSError, http.client.HTTPException):
                    time.sleep(0.05)
            else:
                raise GateFailure("loopback server readiness timeout")
            responses["review"] = self._http_request(port, "GET", "/review", f"127.0.0.1:{port}")
            responses["hostile_host"] = self._http_request(port, "GET", "/health", "example.test")
            responses["hostile_origin"] = self._http_request(
                port, "GET", "/health", f"127.0.0.1:{port}", "http://example.test"
            )
            responses["post_without_csrf"] = self._http_request(port, "POST", "/review", f"127.0.0.1:{port}")
            expected = {
                "health": 200,
                "hostile_host": 403,
                "hostile_origin": 403,
                "post_without_csrf": 403,
                "review": 200,
            }
            if {name: row["status"] for name, row in responses.items()} != expected:
                raise GateFailure("loopback HTTP status contract mismatch")
            if responses["health"]["body_sha256"] != sha256_bytes(
                b'{"authority_effect":"NONE","status":"ok"}\n'
            ) or responses["review"]["body_bytes"] == 0:
                raise GateFailure("loopback HTTP response-body contract mismatch")
            required_headers = {
                "cache-control": "no-store",
                "cross-origin-resource-policy": "same-origin",
                "referrer-policy": "no-referrer",
                "x-content-type-options": "nosniff",
                "x-frame-options": "DENY",
            }
            for row in responses.values():
                if any(row["headers"].get(key) != value for key, value in required_headers.items()):
                    raise GateFailure("loopback HTTP security-header contract mismatch")
                if not row["headers"].get("content-security-policy"):
                    raise GateFailure("loopback HTTP content-security-policy is absent")
            if process.poll() is not None:
                raise GateFailure("loopback server exited during the probe sequence")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
            returncode = process.returncode
            command_dir = self.evidence / "commands"
            command_dir.mkdir(parents=True, exist_ok=True)
            write_new(command_dir / "loopback_server.stdout.bin", stdout)
            write_new(command_dir / "loopback_server.stderr.bin", stderr)
            write_json(
                command_dir / "loopback_server.json",
                {
                    "argv": argv,
                    "command_id": "loopback_server",
                    "controlled_termination": True,
                    "probe_sequence_completed": len(responses) == 5,
                    "returncode_after_controlled_stop": returncode,
                    "status": "CONTROLLED_STOP",
                },
            )
        value = {"binding": "127.0.0.1", "external_network_used": False, "responses": responses}
        write_json(self.evidence / "loopback_probe.json", value)
        return {"probe_count": len(responses), "statuses": {name: row["status"] for name, row in responses.items()}}

    def gate_15(self) -> dict[str, Any]:
        output = self.evidence / "private_repository_validation_final.json"
        completed = self.command(
            "private_validation_final",
            self._validator_argv(output, self.mode),
            env=self.source_env,
        )
        if completed.stdout != output.read_bytes():
            raise GateFailure("final validator stdout/output identity mismatch")
        value = self._require_validation_pass(output)
        return {"mode": self.mode, "source_file_count": value.get("source_file_count")}

    def gate_16(self) -> dict[str, Any]:
        if self.initial_snapshot is None:
            raise GateFailure("initial source snapshot unavailable")
        final_snapshot = source_snapshot(self.root)
        write_json(self.evidence / "final_source_snapshot.json", final_snapshot)
        final_status = self.git("git_status_final", "status", "--porcelain=v1", "-z").stdout
        final_head = self.git("git_head_final", "rev-parse", "HEAD").stdout.decode("ascii").strip()
        final_tree = self.git("git_tree_final", "rev-parse", "HEAD^{tree}").stdout.decode("ascii").strip()
        final_remotes = self._remote_rows("git_remote_names_final")
        if (
            final_snapshot != self.initial_snapshot
            or final_status != self.initial_status
            or final_head != self.initial_head
            or final_tree != self.initial_tree
            or final_remotes != self.initial_remotes
        ):
            raise GateFailure("source, Git identity, remote state, or intentional dirty-state baseline changed during CI")
        value = {
            "commit": final_head,
            "initial_dirty_state_accepted_as_baseline": bool(final_status),
            "source_file_count": final_snapshot["file_count"],
            "source_inventory_sha256": final_snapshot["inventory_sha256"],
            "status_sha256": sha256_bytes(final_status),
            "tree": final_tree,
        }
        write_json(self.evidence / "source_stability.json", value)
        return value

    def gate_17(self) -> dict[str, Any]:
        if any(row["status"] != "PASS" for row in self.gates[:16]):
            raise GateFailure("a prior gate is not PASS")
        if self.scratch.exists():
            shutil.rmtree(self.scratch, onexc=remove_readonly_for_rmtree)
        if self.scratch.exists():
            raise GateFailure("external scratch root cleanup failed")
        return {
            "checksum_inventory": "SHA256SUMS.txt",
            "result": "ci_result.json",
            "scratch_preserved": False,
        }

    def execute(self) -> None:
        callbacks = (
            self.gate_01,
            self.gate_02,
            self.gate_03,
            self.gate_04,
            self.gate_05,
            self.gate_06,
            self.gate_07,
            self.gate_08,
            self.gate_09,
            self.gate_10,
            self.gate_11,
            self.gate_12,
            self.gate_13,
            self.gate_14,
            self.gate_15,
            self.gate_16,
            self.gate_17,
        )
        for number, callback in enumerate(callbacks, start=1):
            self.run_gate(number, callback)

    def finalize(self, error: BaseException | None) -> None:
        for row in self.gates:
            if row["status"] == "PENDING":
                row["status"] = "NOT_RUN_DUE_TO_FAIL_FAST"
        passed = error is None and all(row["status"] == "PASS" for row in self.gates)
        first_failed = next((row for row in self.gates if row["status"] == "FAIL"), None)
        result = {
            "authority_effect": "NONE",
            "external_network_used_by_driver": False,
            "first_failed_gate": first_failed["gate"] if first_failed else None,
            "gates": self.gates,
            "model_provider_invoked": False,
            "outbound_license": "MPL-2.0 AND Unicode-3.0",
            "outbound_license_candidate_only": True,
            "public_release_eligible": False,
            "repository_mode": self.mode,
            "schema": "uvlm.rl02.private_alpha_ci_result.v1",
            "status": "PASS" if passed else "HOLD",
        }
        if error is not None and first_failed is None:
            result["unexpected_failure"] = bounded_detail(error)
        result_path = self.evidence / "ci_result.json"
        if result_path.exists():
            raise GateFailure("CI result path unexpectedly exists")
        write_json(result_path, result)
        if read_canonical_object(result_path) != result:
            raise GateFailure("CI result canonical verification failed")
        checksum_path = self.evidence / "SHA256SUMS.txt"
        files = []
        for path in self.evidence.rglob("*"):
            if path == checksum_path:
                continue
            if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
                raise GateFailure("evidence contains a non-ordinary member")
            if path.is_file():
                files.append(path)
        files.sort(key=lambda path: path.relative_to(self.evidence).as_posix())
        lines = "".join(
            f"{sha256_bytes(path.read_bytes())}  {path.relative_to(self.evidence).as_posix()}\n"
            for path in files
        ).encode("ascii")
        write_new(checksum_path, lines)
        if checksum_path.read_bytes() != lines:
            raise GateFailure("checksum inventory verification failed")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument(
        "--repository-mode",
        choices=("local-source-candidate", "private-github"),
        required=True,
    )
    parser.add_argument("--expected-origin", default=EXPECTED_ORIGIN)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve(strict=True)
    evidence = args.evidence_root.resolve(strict=False)
    if not root.is_dir() or root.is_symlink():
        print("HOLD: source root must be an ordinary directory", file=sys.stderr)
        return 2
    if not outside(evidence, root) or evidence == Path(evidence.anchor) or os.path.lexists(evidence):
        print("HOLD: evidence root must be fresh, bounded, and outside the source root", file=sys.stderr)
        return 2
    if args.repository_mode == "private-github" and args.expected_origin.casefold() != EXPECTED_ORIGIN.casefold():
        print("HOLD: private GitHub mode requires the commissioned origin", file=sys.stderr)
        return 2
    evidence.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix="triadicbrain-gh01-scratch-", dir=evidence.parent)).resolve()
    runner = Runner(root, evidence, scratch, args.repository_mode, args.expected_origin)
    error: BaseException | None = None
    try:
        runner.execute()
    except BaseException as exc:
        error = exc
    finally:
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
    try:
        runner.finalize(error)
    except BaseException as finalize_error:
        print(f"HOLD: {bounded_detail(finalize_error)}", file=sys.stderr)
        return 1
    if error is not None:
        print(f"HOLD: {bounded_detail(error)}", file=sys.stderr)
        return 1
    print(canonical_json({"evidence_root": str(evidence), "status": "PASS"}).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
