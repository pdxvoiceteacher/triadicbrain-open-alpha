"""Run the authenticated substantive totality task into a new external root.

The normal caller supplies only an output directory.  Repository location,
task identity, source identity, run identity, and logical time are derived from
this committed launcher and its exact-hash-pinned task profile.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any


PROFILE_RELATIVE = Path(
    "validation/triadic_brain_totality_repair_inputs_v1/PRODUCT_TASK_01_PROFILE.json"
)
COMPARATOR_RELATIVE = Path(
    "validation/triadic_brain_totality_repair_inputs_v1/"
    "PRODUCT_TASK_01_USABILITY_COMPARATOR_TEMPLATE.json"
)
PROFILE_SHA256 = "585049829dd6595a4bf46cabb050f0e31bf6282494eed81a81b92a880b57b6d9"
COMPARATOR_SHA256 = "352ae20b0c19f5c9aba27fed9e34d1e81b0ea607ee586cff317871e86f2f5bc4"
DELTA_SHA256 = "e00d009c9384bbbda3ca5f1f8a66edc8be13fce4c802dc92771ced67debe0efc"
TASK_STATUS = "AWAITING_THOMAS_HUMAN_REVIEW"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024


class SubstantiveTaskError(RuntimeError):
    """The fixed task could not be authenticated or completed safely."""


def _canonical(value: Any) -> bytes:
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


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _link_like(path: Path) -> bool:
    try:
        junction_probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(junction_probe and junction_probe())
    except OSError:
        return True


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in rows:
        if key in value:
            raise SubstantiveTaskError(f"JSON_DUPLICATE_MEMBER:{key}")
        value[key] = item
    return value


def _read_bytes(path: Path, label: str, maximum: int) -> bytes:
    if _link_like(path) or not path.is_file():
        raise SubstantiveTaskError(f"INPUT_UNSAFE_OR_MISSING:{label}")
    try:
        with path.open("rb") as stream:
            payload = stream.read(maximum + 1)
    except OSError as exc:
        raise SubstantiveTaskError(f"INPUT_READ_FAILED:{label}") from exc
    if len(payload) > maximum:
        raise SubstantiveTaskError(f"INPUT_SIZE_LIMIT_EXCEEDED:{label}")
    return payload


def _read_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(path, label, MAX_JSON_BYTES)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SubstantiveTaskError(f"JSON_BOM_PROHIBITED:{label}")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SubstantiveTaskError(f"JSON_NONFINITE_NUMBER:{label}:{token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SubstantiveTaskError(f"JSON_INVALID:{label}") from exc
    if not isinstance(value, dict):
        raise SubstantiveTaskError(f"JSON_OBJECT_REQUIRED:{label}")
    return value, raw


def _verify_sidecar(path: Path, digest: str) -> None:
    sidecar = path.with_name(path.name + ".sha256")
    raw = _read_bytes(sidecar, sidecar.name, 4096)
    expected = f"{digest}  {path.name}\n".encode("ascii")
    if raw != expected:
        raise SubstantiveTaskError(f"SIDECAR_IDENTITY_MISMATCH:{path.name}")


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "AGENTS.md").is_file() or not (root / "integration/tools").is_dir():
        raise SubstantiveTaskError("DERIVED_REPOSITORY_ROOT_INVALID")
    return root


def _source_member(repo: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise SubstantiveTaskError("PROFILE_SOURCE_PATH_INVALID")
    member = PurePosixPath(relative)
    if member.is_absolute() or not member.parts or any(part in {"", ".", ".."} for part in member.parts):
        raise SubstantiveTaskError("PROFILE_SOURCE_PATH_INVALID")
    candidate = repo.joinpath(*member.parts)
    try:
        candidate.resolve(strict=True).relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SubstantiveTaskError("PROFILE_SOURCE_PATH_ESCAPE") from exc
    return candidate


def load_authenticated_inputs(repo_root: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Authenticate the fixed profile, comparator template, and exact Delta."""

    repo = (repo_root or _repo_root()).resolve(strict=True)
    profile_path = repo / PROFILE_RELATIVE
    profile, profile_raw = _read_object(profile_path, profile_path.name)
    if _sha(profile_raw) != PROFILE_SHA256:
        raise SubstantiveTaskError("PROFILE_IDENTITY_MISMATCH")
    _verify_sidecar(profile_path, PROFILE_SHA256)

    template_path = repo / COMPARATOR_RELATIVE
    template, template_raw = _read_object(template_path, template_path.name)
    if _sha(template_raw) != COMPARATOR_SHA256:
        raise SubstantiveTaskError("COMPARATOR_TEMPLATE_IDENTITY_MISMATCH")
    _verify_sidecar(template_path, COMPARATOR_SHA256)

    expected_profile_keys = {
        "aha_mode",
        "authority_effect",
        "captured_adapter",
        "logical_time",
        "nonauthority",
        "privacy",
        "request_id",
        "run_id",
        "schema_id",
        "source",
        "task_id",
        "unsupported_claim_answer_key",
        "user_input",
    }
    if set(profile) != expected_profile_keys:
        raise SubstantiveTaskError("PROFILE_CONTRACT_INVALID")
    captured = profile.get("captured_adapter")
    privacy = profile.get("privacy")
    source = profile.get("source")
    key = profile.get("unsupported_claim_answer_key")
    if (
        profile.get("schema_id") != "uvlm.triadic.totality.substantive_task_profile.v1"
        or profile.get("task_id") != "PRODUCT_TASK_01"
        or profile.get("aha_mode") != "structural"
        or profile.get("authority_effect") != "NONE"
        or not isinstance(captured, dict)
        or set(captured)
        != {
            "claim_evidence_references",
            "claims",
            "provider_invoked",
            "uncertainty",
        }
        or captured.get("provider_invoked") is not False
        or not isinstance(captured.get("claims"), list)
        or len(captured["claims"]) < 8
        or not all(isinstance(claim, str) and claim.strip() for claim in captured["claims"])
        or not isinstance(captured.get("claim_evidence_references"), list)
        or len(captured["claim_evidence_references"]) != len(captured["claims"])
        or any(
            not isinstance(references, list)
            or any(not isinstance(reference, dict) for reference in references)
            for references in captured["claim_evidence_references"]
        )
        or not isinstance(privacy, dict)
        or privacy.get("task_consent") is not True
        or privacy.get("policy_satisfied") is not True
        or not isinstance(source, dict)
        or source.get("sha256") != DELTA_SHA256
        or not isinstance(key, dict)
        or key.get("human_adjudication_required_for_final_rating") is not True
        or key.get("adjudication_is_human_decision") is not False
    ):
        raise SubstantiveTaskError("PROFILE_CONTRACT_INVALID")
    answer_rows = key.get("claims")
    if not isinstance(answer_rows, list) or [row.get("claim_id") for row in answer_rows if isinstance(row, dict)] != [
        f"CLM-{index:04d}" for index in range(1, len(captured["claims"]) + 1)
    ]:
        raise SubstantiveTaskError("ANSWER_KEY_CLAIM_BINDING_INVALID")
    if not any(
        isinstance(row, dict) and row.get("expected_support") == "UNSUPPORTED_AND_CONTRADICTED"
        for row in answer_rows
    ):
        raise SubstantiveTaskError("ANSWER_KEY_REQUIRES_UNSUPPORTED_CONTROL")

    source_path = _source_member(repo, source.get("relative_path"))
    source_raw = _read_bytes(source_path, source_path.name, MAX_SOURCE_BYTES)
    if _sha(source_raw) != DELTA_SHA256:
        raise SubstantiveTaskError("DELTA_IDENTITY_MISMATCH")
    return profile, template, source_path


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _new_external_root(repo: Path, requested: Path) -> Path:
    candidate = requested.resolve(strict=False)
    if candidate.exists() or _link_like(candidate):
        raise SubstantiveTaskError("OUTPUT_ROOT_ALREADY_EXISTS_OR_UNSAFE")
    parent = candidate.parent
    if _link_like(parent) or not parent.is_dir():
        raise SubstantiveTaskError("OUTPUT_PARENT_UNSAFE_OR_MISSING")
    if _contains(repo, candidate):
        raise SubstantiveTaskError("OUTPUT_ROOT_MUST_BE_EXTERNAL_TO_REPOSITORY")
    try:
        candidate.mkdir()
    except OSError as exc:
        raise SubstantiveTaskError("OUTPUT_ROOT_CREATE_FAILED") from exc
    return candidate


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except OSError as exc:
        raise SubstantiveTaskError(f"OUTPUT_WRITE_FAILED:{path.name}") from exc


def _load_tool(repo: Path, stem: str):
    path = repo / "integration" / "tools" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_totality_{stem}", path)
    if spec is None or spec.loader is None:
        raise SubstantiveTaskError(f"TOOL_IMPORT_FAILED:{stem}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_lane(profile: dict[str, Any], prepared: Path, output: Path) -> dict[str, Any]:
    """Preserve Lane A only from the prepared capture, never from quarantine."""

    capture_path = prepared / "captured_semantic.json"
    capture, capture_raw = _read_object(capture_path, "prepared/captured_semantic.json")
    expected_answer = "\n".join(profile["captured_adapter"]["claims"])
    if capture.get("answer") != expected_answer:
        raise SubstantiveTaskError("RAW_CAPTURE_PROFILE_MISMATCH")
    raw_root = output / "raw_lane"
    raw_root.mkdir()
    _write_new(raw_root / "captured_semantic.json", capture_raw)
    claim_rows = "".join(
        "<article class=\"claim\">"
        f"<h3>CLM-{index:04d}</h3><p>{html.escape(claim)}</p></article>"
        for index, claim in enumerate(profile["captured_adapter"]["claims"], start=1)
    )
    page = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        "<title>Raw captured candidate</title><style>body{font:18px/1.55 system-ui;max-width:76ch;margin:3rem auto;padding:0 1rem;color:#171717}"
        "header{border-bottom:2px solid #222;margin-bottom:2rem}.question{padding:1rem;background:#f4f4f4}"
        ".claim{border-top:1px solid #ddd;padding:.75rem 0}.claim h3{font:600 .9rem/1.2 ui-monospace,monospace;margin:0}p{margin:1em 0}</style></head>"
        "<body><header><h1>Raw captured candidate</h1><p>Lane A — candidate text without governance annotations.</p></header>"
        f"<section aria-labelledby=\"question\"><h2 id=\"question\">Task</h2><p class=\"question\">{html.escape(profile['user_input'])}</p></section>"
        f"<section aria-labelledby=\"answer\"><h2 id=\"answer\">Candidate</h2>{claim_rows}</section></body></html>\n"
    ).encode("utf-8")
    _write_new(raw_root / "raw_candidate.html", page)
    manifest = {
        "authority_effect": "NONE",
        "capture_origin": "prepared/captured_semantic.json",
        "capture_sha256": _sha(capture_raw),
        "governance_annotations_present": False,
        "quarantine_read_performed": False,
        "raw_candidate_html_sha256": _sha(page),
        "schema_id": "uvlm.triadic.totality.raw_candidate_lane.v1",
        "task_id": profile["task_id"],
    }
    _write_new(raw_root / "raw_candidate_manifest.json", _canonical(manifest))
    return manifest


def _assert_null_human_fields(template: dict[str, Any]) -> None:
    lane_keys = {
        "cognitive_load_1_to_7",
        "completion_seconds",
        "detected_limitation_claim_ids",
        "detected_unsupported_claim_ids",
        "ended_at",
        "notes",
        "selected_decision",
        "started_at",
        "understandability_1_to_7",
        "usefulness_1_to_7",
    }
    for lane_name in ("raw_lane", "governed_lane"):
        lane = template.get(lane_name)
        if not isinstance(lane, dict) or set(lane) != lane_keys or any(value is not None for value in lane.values()):
            raise SubstantiveTaskError("COMPARATOR_HUMAN_FIELDS_MUST_BE_NULL")
    comparison = template.get("comparison")
    if not isinstance(comparison, dict) or any(value is not None for value in comparison.values()):
        raise SubstantiveTaskError("COMPARATOR_HUMAN_FIELDS_MUST_BE_NULL")
    if (
        template.get("submitted_by_human") is not False
        or template.get("submitted_receipt") is not None
        or template.get("human_fields_complete") is not False
        or template.get("human_review_status") != "NOT_STARTED"
        or template.get("reviewer_display_name") is not None
        or template.get("machine_scoring") is not None
        or template.get("human_comparison_is_not_atlas_final_decision") is not True
        or template.get("schema_id")
        != "uvlm.triadic.totality.usability_comparator.v2"
    ):
        raise SubstantiveTaskError("COMPARATOR_MUST_BE_UNSUBMITTED")


def run_task(
    output_dir: Path,
    *,
    repo_root: Path | None = None,
    allow_dirty_for_test: bool = False,
) -> dict[str, Any]:
    """Build, seal, exactly replay, and stop before any human submission."""

    repo = (repo_root or _repo_root()).resolve(strict=True)
    profile, comparator, source_path = load_authenticated_inputs(repo)
    _assert_null_human_fields(comparator)
    output = _new_external_root(repo, output_dir)
    prepare_tool = _load_tool(repo, "prepare_totality_task")
    route_tool = _load_tool(repo, "run_totality_product_route")

    prepared = output / "prepared"
    prepare_tool.prepare(
        source_path=source_path,
        output_dir=prepared,
        request_id=profile["request_id"],
        run_id=profile["run_id"],
        logical_time=profile["logical_time"],
        user_input=profile["user_input"],
        claims=profile["captured_adapter"]["claims"],
        claim_evidence_references=profile["captured_adapter"][
            "claim_evidence_references"
        ],
        uncertainty=profile["captured_adapter"]["uncertainty"],
        source_label=profile["source"]["source_label"],
        aha_mode=profile["aha_mode"],
        task_consent=profile["privacy"]["task_consent"],
        privacy_policy_satisfied=profile["privacy"]["policy_satisfied"],
        privacy_basis=profile["privacy"]["basis"],
    )
    raw_manifest = _raw_lane(profile, prepared, output)
    answer_key_bytes = _canonical(profile["unsupported_claim_answer_key"])
    _write_new(output / "unsupported_claim_answer_key.json", answer_key_bytes)

    sealed_run = output / "sealed_run"
    sealed_zip = output / "sealed_run.zip"
    route_receipt = route_tool.build_product_route(
        repo,
        prepared,
        sealed_run,
        top_k=8,
        export_zip=sealed_zip,
        allow_dirty=allow_dirty_for_test,
    )
    route_bytes = _canonical(route_receipt)
    _write_new(output / "route_receipt.json", route_bytes)
    replay_receipt = route_tool.replay_product_route(
        repo,
        sealed_run,
        output / "exact_replay",
        allow_dirty=allow_dirty_for_test,
    )
    replay_bytes = _canonical(replay_receipt)
    _write_new(output / "exact_replay_receipt.json", replay_bytes)
    export_receipt = route_receipt.get("export_zip")
    if (
        route_receipt.get("schema_id")
        != "uvlm.triadicgate.totality_product_route_receipt.v2"
        or route_receipt.get("receipt_path_contract")
        != "STABLE_ARTIFACT_NAMES_ONLY"
        or route_receipt.get("sealed") is not True
        or route_receipt.get("human_decision") != "PENDING"
        or route_receipt.get("external_human_continuation_required") is not True
        or not isinstance(export_receipt, dict)
        or export_receipt.get("zip_path") != "sealed_run.zip"
        or export_receipt.get("zip_sidecar_path") != "sealed_run.zip.sha256"
        or replay_receipt.get("valid") is not True
        or replay_receipt.get("exact_tree_equality") is not True
    ):
        raise SubstantiveTaskError("ROUTE_OR_REPLAY_NOT_READY_FOR_HUMAN_REVIEW")
    pmr, pmr_raw = _read_object(sealed_run / "pmr_receipt.json", "sealed_run/pmr_receipt.json")
    if (
        pmr.get("mode") != "NO_WRITE_REFERENCE_IMPLEMENTATION"
        or pmr.get("retained") is not False
        or pmr.get("persistent_bytes_written") != 0
    ):
        raise SubstantiveTaskError("PMR_NO_ACTION_RECEIPT_REQUIRED")

    bindings = comparator.get("machine_bindings")
    if not isinstance(bindings, dict):
        raise SubstantiveTaskError("COMPARATOR_MACHINE_BINDINGS_INVALID")
    bindings.update(
        {
            "answer_key_sha256": _sha(answer_key_bytes),
            "comparator_template_sha256": COMPARATOR_SHA256,
            "governed_claim_map_sha256": _sha(
                _read_bytes(
                    sealed_run / "claim_evidence_map.json",
                    "claim_evidence_map.json",
                    MAX_JSON_BYTES,
                )
            ),
            "governed_review_html_sha256": _sha(
                _read_bytes(sealed_run / "final_review.html", "final_review.html", MAX_JSON_BYTES)
            ),
            "profile_sha256": PROFILE_SHA256,
            "raw_candidate_html_sha256": raw_manifest["raw_candidate_html_sha256"],
            "raw_candidate_sha256": raw_manifest["capture_sha256"],
            "raw_lane_manifest_sha256": _sha(_canonical(raw_manifest)),
            "replay_receipt_sha256": _sha(replay_bytes),
            "route_receipt_sha256": _sha(route_bytes),
            "sealed_run_manifest_sha256": _sha(
                _read_bytes(sealed_run / "run_manifest.json", "run_manifest.json", MAX_JSON_BYTES)
            ),
        }
    )
    _assert_null_human_fields(comparator)
    comparator_bytes = _canonical(comparator)
    _write_new(output / "usability_comparator.json", comparator_bytes)
    status = {
        "authority_effect": "NONE",
        "human_comparator_submitted": False,
        "human_decision_submitted": False,
        "nonauthority": profile["nonauthority"],
        "pmr_no_action_receipt_sha256": _sha(pmr_raw),
        "profile_sha256": PROFILE_SHA256,
        "raw_lane_manifest_sha256": _sha(_canonical(raw_manifest)),
        "replay_exact_tree_equality": True,
        "replay_receipt_sha256": _sha(replay_bytes),
        "route_receipt_sha256": _sha(route_bytes),
        "schema_id": "uvlm.triadic.totality.product_task_status.v1",
        "sealed_run_root": "sealed_run",
        "status": TASK_STATUS,
        "task_id": profile["task_id"],
        "usability_comparator_sha256": _sha(comparator_bytes),
    }
    _write_new(output / "task_status.json", _canonical(status))
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New external directory for PRODUCT_TASK_01 evidence.",
    )
    arguments = parser.parse_args()
    try:
        result = run_task(arguments.output_dir)
    except (OSError, SubstantiveTaskError) as exc:
        sys.stderr.buffer.write(
            _canonical({"valid": False, "error": type(exc).__name__, "reason": str(exc)})
        )
        return 2
    sys.stdout.buffer.write(_canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
