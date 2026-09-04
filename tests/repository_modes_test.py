"""Repository-mode regression tests using local temporary Git repositories."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "oa01_validate.py"
EXPECTED_ORIGIN = "pdxvoiceteacher/triadicbrain-open-alpha"


def load_validator():
    spec = importlib.util.spec_from_file_location("oa01_validate_repository_modes", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=True,
    )
    return completed.stdout


def make_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "--quiet", str(repository)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    (repository / "governed.txt").write_bytes(b"governed source bytes\n")
    return repository


def add_origin(repository: Path, url: str) -> None:
    git(repository, "remote", "add", "origin", url)


def validate(
    repository: Path,
    mode: str,
    expected_origin: str | None = None,
    privacy_metadata: Path | None = None,
) -> dict[str, object]:
    return VALIDATOR.check_repository(repository, mode, expected_origin, privacy_metadata)


def test_local_source_candidate_passes_without_remote(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    result = validate(repository, "local-source-candidate")
    assert result["status"] == "PASS"
    assert result["observed_remotes"] == []
    assert result["normalized_origin"] is None


def test_local_source_candidate_rejects_origin(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    assert validate(repository, "local-source-candidate")["status"] == "FAIL"


def test_local_source_candidate_rejects_expected_origin_argument(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    assert validate(repository, "local-source-candidate", EXPECTED_ORIGIN)["status"] == "FAIL"


@pytest.mark.parametrize(
    "url,form",
    [
        (f"https://github.com/{EXPECTED_ORIGIN}.git", "HTTPS"),
        (f"git@github.com:{EXPECTED_ORIGIN}.git", "SSH_SCP"),
        (f"ssh://git@github.com/{EXPECTED_ORIGIN}.git", "SSH_URL"),
    ],
)
def test_private_github_accepts_exact_origin_forms(tmp_path: Path, url: str, form: str) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, url)
    result = validate(repository, "private-github", EXPECTED_ORIGIN)
    assert result["status"] == "PASS"
    assert result["normalized_origin"] == EXPECTED_ORIGIN
    observed = result["observed_remotes"]
    assert isinstance(observed, list)
    assert observed[0]["fetch_urls"] == [
        {"form": form, "normalized_repository": EXPECTED_ORIGIN}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/not-the-owner/triadicbrain-open-alpha.git",
        "https://github.com/pdxvoiceteacher/not-the-repository.git",
    ],
)
def test_private_github_rejects_wrong_identity(tmp_path: Path, url: str) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, url)
    assert validate(repository, "private-github", EXPECTED_ORIGIN)["status"] == "FAIL"


def test_private_github_rejects_extra_remote(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    unexpected_name = "PRIVATE_REMOTE_SECRET"
    git(repository, "remote", "add", unexpected_name, f"git@github.com:{EXPECTED_ORIGIN}.git")
    result = validate(repository, "private-github", EXPECTED_ORIGIN)
    assert result["status"] == "FAIL"
    assert unexpected_name not in json.dumps(result, sort_keys=True)


def test_private_github_rejects_missing_origin(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    assert validate(repository, "private-github", EXPECTED_ORIGIN)["status"] == "FAIL"


def test_private_github_requires_expected_origin_argument(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    assert validate(repository, "private-github")["status"] == "FAIL"


@pytest.mark.parametrize(
    "url,form",
    [
        (f"https://github.com/{EXPECTED_ORIGIN}.git", "HTTPS"),
        (f"git@github.com:{EXPECTED_ORIGIN}.git", "SSH_SCP"),
        (f"ssh://git@github.com/{EXPECTED_ORIGIN}.git", "SSH_URL"),
    ],
)
def test_public_github_unreleased_accepts_exact_origin_forms(
    tmp_path: Path, url: str, form: str
) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, url)
    result = validate(repository, "public-github-unreleased", EXPECTED_ORIGIN)
    assert result["status"] == "PASS"
    assert result["normalized_origin"] == EXPECTED_ORIGIN
    assert result["observed_remotes"][0]["fetch_urls"] == [
        {"form": form, "normalized_repository": EXPECTED_ORIGIN}
    ]


def test_public_github_unreleased_requires_expected_origin(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    assert validate(repository, "public-github-unreleased")["status"] == "FAIL"


def test_public_github_unreleased_rejects_wrong_identity(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, "https://github.com/not-the-owner/not-the-repository.git")
    assert validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN
    )["status"] == "FAIL"


def test_private_github_rejects_matching_uncommissioned_origin(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    uncommissioned = "not-the-owner/not-the-repository"
    add_origin(repository, f"https://github.com/{uncommissioned}.git")
    assert validate(repository, "private-github", uncommissioned)["status"] == "FAIL"


def test_private_github_rejects_mismatched_push_identity(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    git(
        repository,
        "remote",
        "set-url",
        "--push",
        "origin",
        "git@github.com:pdxvoiceteacher/not-the-repository.git",
    )
    assert validate(repository, "private-github", EXPECTED_ORIGIN)["status"] == "FAIL"


def test_private_github_rejects_extra_malformed_origin_url(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    exact = f"https://github.com/{EXPECTED_ORIGIN}.git"
    add_origin(repository, exact)
    extra_secret = "EXTRA_REMOTE_URL_SECRET"
    git(
        repository,
        "config",
        "--add",
        "remote.origin.url",
        f"https://visible-user:{extra_secret}@example.invalid/not/accepted.git",
    )
    git(repository, "remote", "set-url", "--push", "origin", exact)
    result = validate(repository, "private-github", EXPECTED_ORIGIN)
    assert result["status"] == "FAIL"
    assert result["observed_remotes"][0]["fetch_url_count"] == 2
    assert extra_secret not in json.dumps(result, sort_keys=True)


def test_credential_bearing_https_output_is_redacted(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    secret = "TOP_SECRET_REMOTE_TOKEN"
    add_origin(
        repository,
        f"https://visible-user:{secret}@github.com/{EXPECTED_ORIGIN}.git",
    )
    result = validate(repository, "private-github", EXPECTED_ORIGIN)
    serialized = json.dumps(result, sort_keys=True)
    assert result["status"] == "PASS"
    assert secret not in serialized
    assert "visible-user" not in serialized
    assert result["normalized_origin"] == EXPECTED_ORIGIN


def test_authenticated_privacy_metadata_is_optional_and_validated(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    absent = validate(repository, "private-github", EXPECTED_ORIGIN)
    assert absent["status"] == "PASS"
    assert absent["privacy_verification"]["status"] == "NOT_PROVIDED"
    assert absent["privacy_verification"]["verified_private"] is False

    metadata = tmp_path / "authenticated-repository-metadata.json"
    metadata.write_text(
        json.dumps({
            "schema": "uvlm.gh01.authenticated_repository_metadata.v1",
            "repository": EXPECTED_ORIGIN,
            "private": True,
            "source": "GITHUB_ACTIONS_EVENT_CONTEXT",
            "authority_effect": "NONE",
        }),
        encoding="utf-8",
    )
    present = validate(repository, "private-github", EXPECTED_ORIGIN, metadata)
    assert present["status"] == "PASS"
    assert present["privacy_verification"]["status"] == "PASS"
    assert present["privacy_verification"]["verified_private"] is True

    metadata.write_text(
        json.dumps({
            "schema": "uvlm.gh01.authenticated_repository_metadata.v1",
            "repository": EXPECTED_ORIGIN,
            "private": True,
            "source": "GITHUB_API_AUTHENTICATED",
            "authority_effect": "NONE",
        }),
        encoding="utf-8",
    )
    assert validate(repository, "private-github", EXPECTED_ORIGIN, metadata)["status"] == "PASS"

    metadata_secret = "PRIVATE_METADATA_SECRET"
    metadata.write_text(
        json.dumps({
            "schema": "uvlm.gh01.authenticated_repository_metadata.v1",
            "repository": EXPECTED_ORIGIN,
            "private": True,
            "source": "GITHUB_API_AUTHENTICATED",
            "authority_effect": "NONE",
            "unexpected": metadata_secret,
        }),
        encoding="utf-8",
    )
    extra_key_result = validate(repository, "private-github", EXPECTED_ORIGIN, metadata)
    assert extra_key_result["status"] == "FAIL"
    assert metadata_secret not in json.dumps(extra_key_result, sort_keys=True)

    metadata.write_text(
        json.dumps({
            "schema": "uvlm.gh01.authenticated_repository_metadata.v1",
            "repository": EXPECTED_ORIGIN,
            "private": False,
            "source": "GITHUB_ACTIONS_EVENT_CONTEXT",
            "authority_effect": "NONE",
        }),
        encoding="utf-8",
    )
    assert validate(repository, "private-github", EXPECTED_ORIGIN, metadata)["status"] == "FAIL"


def test_authenticated_public_repository_metadata_v2_is_exact(tmp_path: Path) -> None:
    repository = make_repository(tmp_path)
    add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    metadata = tmp_path / "authenticated-public-repository-metadata.json"
    exact = {
        "authority_effect": "NONE",
        "private": False,
        "repository": EXPECTED_ORIGIN,
        "schema": "uvlm.github.authenticated_repository_metadata.v2",
        "source": "GITHUB_ACTIONS_EVENT_CONTEXT",
        "visibility": "PUBLIC",
    }
    metadata.write_text(json.dumps(exact), encoding="utf-8")
    result = validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN, metadata
    )
    assert result["status"] == "PASS"
    assert result["privacy_verification"] == {
        "authority_effect": "NONE",
        "errors": [],
        "repository": EXPECTED_ORIGIN,
        "source": "GITHUB_ACTIONS_EVENT_CONTEXT",
        "status": "PASS",
        "verified_private": False,
        "verified_public": True,
        "visibility": "PUBLIC",
    }

    wrong_private = dict(exact, private=True)
    metadata.write_text(json.dumps(wrong_private), encoding="utf-8")
    assert validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN, metadata
    )["status"] == "FAIL"

    wrong_visibility = dict(exact, visibility="PRIVATE")
    metadata.write_text(json.dumps(wrong_visibility), encoding="utf-8")
    assert validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN, metadata
    )["status"] == "FAIL"

    wrong_schema = dict(exact, schema="uvlm.gh01.authenticated_repository_metadata.v1")
    metadata.write_text(json.dumps(wrong_schema), encoding="utf-8")
    assert validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN, metadata
    )["status"] == "FAIL"

    unexpected = dict(exact, unexpected="MUST_NOT_BE_REFLECTED")
    metadata.write_text(json.dumps(unexpected), encoding="utf-8")
    rejected = validate(
        repository, "public-github-unreleased", EXPECTED_ORIGIN, metadata
    )
    assert rejected["status"] == "FAIL"
    assert "MUST_NOT_BE_REFLECTED" not in json.dumps(rejected, sort_keys=True)


@pytest.mark.parametrize(
    "mode,with_remote,expected_origin",
    [
        ("local-source-candidate", False, None),
        ("private-github", True, EXPECTED_ORIGIN),
        ("public-github-unreleased", True, EXPECTED_ORIGIN),
    ],
)
def test_repository_mode_validation_does_not_change_git_or_worktree(
    tmp_path: Path,
    mode: str,
    with_remote: bool,
    expected_origin: str | None,
) -> None:
    repository = make_repository(tmp_path)
    if with_remote:
        add_origin(repository, f"https://github.com/{EXPECTED_ORIGIN}.git")
    config = repository / ".git" / "config"
    before_config = config.read_bytes()
    before_source = (repository / "governed.txt").read_bytes()
    before_status = git(repository, "status", "--porcelain=v1", "--untracked-files=all")

    result = validate(repository, mode, expected_origin)

    assert result["status"] == "PASS"
    assert config.read_bytes() == before_config
    assert (repository / "governed.txt").read_bytes() == before_source
    assert git(repository, "status", "--porcelain=v1", "--untracked-files=all") == before_status
