"""Loopback-only, raw-first human usability comparison capture.

This companion surface records a comparison observation.  It does not submit
an Atlas final decision or authorize any memory, publication, deployment, or
release effect.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import ipaddress
import json
import os
import secrets
import socket
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
import uvicorn


SCHEMA_ID = "uvlm.triadic.totality.usability_comparator.v2"
OUTPUT_SCHEMA_ID = "uvlm.triadic.totality.usability_comparator_submission.v2"
DECISIONS = ("APPROVE", "HOLD", "REJECT", "REPAIR")
LANE_KEYS = {
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
BINDING_PATHS = {
    "answer_key_sha256": "unsupported_claim_answer_key.json",
    "governed_claim_map_sha256": "sealed_run/claim_evidence_map.json",
    "governed_review_html_sha256": "sealed_run/final_review.html",
    "raw_candidate_html_sha256": "raw_lane/raw_candidate.html",
    "raw_candidate_sha256": "raw_lane/captured_semantic.json",
    "raw_lane_manifest_sha256": "raw_lane/raw_candidate_manifest.json",
    "replay_receipt_sha256": "exact_replay_receipt.json",
    "route_receipt_sha256": "route_receipt.json",
    "sealed_run_manifest_sha256": "sealed_run/run_manifest.json",
}
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_FORM_BYTES = 32 * 1024
MAX_REVIEWER = 200
MAX_NOTES = 4000
HEX = frozenset("0123456789abcdef")
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
ARTIFACT_HEADERS = {
    **HEADERS,
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; "
        "base-uri 'none'; frame-ancestors 'self'"
    ),
}
NO_EFFECTS = {
    "atlas_final_decision": False,
    "canonization": False,
    "deployment": False,
    "external_network": False,
    "memory_write": False,
    "merge": False,
    "model_invocation": False,
    "pmr_write": False,
    "publication": False,
    "release": False,
    "training": False,
    "truth_certification": False,
}
NONAUTHORITY = (
    "This is a human usability comparison observation, not an Atlas final "
    "decision. It grants no truth, memory, PMR, training, canonization, merge, "
    "publication, deployment, or release authority."
)


class ComparatorUIError(ValueError):
    """The comparison input, observation, or output boundary is invalid."""


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


def _hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in HEX for character in value)
    )


def _link_like(path: Path) -> bool:
    try:
        probe = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(probe and probe())
    except OSError:
        return True


def _directory_identity(path: Path, label: str) -> tuple[int, int]:
    """Return the physical identity of one owned, ordinary directory."""

    try:
        if _link_like(path) or not path.is_dir():
            raise OSError
        details = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ComparatorUIError(f"{label}_IDENTITY_INVALID") from exc
    return details.st_dev, details.st_ino


def _root(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or _link_like(path) or path == Path(path.anchor):
        raise ComparatorUIError(f"{label}_UNSAFE")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ComparatorUIError(f"{label}_UNSAFE") from exc
    if _link_like(resolved) or not resolved.is_dir():
        raise ComparatorUIError(f"{label}_UNSAFE")
    return resolved


def _contains(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _output_path(value: str | Path, task_root: Path, review_root: Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or os.path.lexists(path) or _link_like(path):
        raise ComparatorUIError("OUTPUT_ROOT_UNSAFE_OR_EXISTS")
    resolved = path.resolve(strict=False)
    # Human submissions are durable only at TASK_ROOT/human_comparisons.  A
    # raw-free review run may itself be a temporary reconstruction, but it
    # must never redirect the human receipt into that temporary scope.
    if (
        resolved.name != "human_comparisons"
        or resolved.parent != task_root
        or _contains(review_root, resolved)
    ):
        raise ComparatorUIError("OUTPUT_ROOT_SCOPE_INVALID")
    if _link_like(resolved.parent) or not resolved.parent.is_dir():
        raise ComparatorUIError("OUTPUT_PARENT_UNSAFE")
    return resolved


def _member(root: Path, relative: str, maximum: int = MAX_MEMBER_BYTES) -> bytes:
    candidate = root.joinpath(*relative.split("/"))
    try:
        candidate.resolve(strict=True).relative_to(root)
        if _link_like(candidate) or not candidate.is_file():
            raise ValueError
        size = candidate.stat().st_size
        if size > maximum:
            raise ValueError
        with candidate.open("rb") as stream:
            payload = stream.read(maximum + 1)
        if len(payload) != size:
            raise ValueError
    except (OSError, ValueError) as exc:
        raise ComparatorUIError(f"TASK_MEMBER_INVALID:{relative}") from exc
    return payload


def _object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ComparatorUIError(f"JSON_INVALID:{label}") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise ComparatorUIError(f"JSON_NOT_CANONICAL_OBJECT:{label}")
    return value


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in rows:
        if key in value:
            raise ValueError(key)
        value[key] = item
    return value


def _load_evidence(task_root: Path, review_root: Path) -> dict[str, Any]:
    relative_bytes = {
        relative: _member(task_root, relative)
        for relative in {
            "exact_replay_receipt.json",
            "raw_lane/captured_semantic.json",
            "raw_lane/raw_candidate.html",
            "raw_lane/raw_candidate_manifest.json",
            "route_receipt.json",
            "unsupported_claim_answer_key.json",
            "usability_comparator.json",
        }
    }
    review_bytes = {
        relative: _member(review_root, relative)
        for relative in {
            "claim_evidence_map.json",
            "final_review.html",
            "run_manifest.json",
        }
    }
    template_raw = relative_bytes["usability_comparator.json"]
    template = _object(template_raw, "usability_comparator.json")
    bindings = template.get("machine_bindings")
    if (
        template.get("schema_id") != SCHEMA_ID
        or template.get("submitted_by_human") is not False
        or template.get("human_fields_complete") is not False
        or template.get("human_review_status") != "NOT_STARTED"
        or template.get("reviewer_display_name") is not None
        or template.get("machine_scoring") is not None
        or template.get("submitted_receipt") is not None
        or template.get("human_comparison_is_not_atlas_final_decision") is not True
        or any(
            not isinstance(template.get(lane), dict)
            or set(template[lane]) != LANE_KEYS
            or any(value is not None for value in template[lane].values())
            for lane in ("raw_lane", "governed_lane")
        )
        or not isinstance(template.get("comparison"), dict)
        or any(value is not None for value in template["comparison"].values())
        or not isinstance(bindings, dict)
        or bindings.get("task_id") != "PRODUCT_TASK_01"
        or not _hex(bindings.get("profile_sha256"))
        or not _hex(bindings.get("comparator_template_sha256"))
    ):
        raise ComparatorUIError("UNSUBMITTED_COMPARATOR_CONTRACT_INVALID")
    actual = {
        "answer_key_sha256": _sha(
            relative_bytes["unsupported_claim_answer_key.json"]
        ),
        "governed_claim_map_sha256": _sha(review_bytes["claim_evidence_map.json"]),
        "governed_review_html_sha256": _sha(review_bytes["final_review.html"]),
        "raw_candidate_html_sha256": _sha(
            relative_bytes["raw_lane/raw_candidate.html"]
        ),
        "raw_candidate_sha256": _sha(
            relative_bytes["raw_lane/captured_semantic.json"]
        ),
        "raw_lane_manifest_sha256": _sha(
            relative_bytes["raw_lane/raw_candidate_manifest.json"]
        ),
        "replay_receipt_sha256": _sha(
            relative_bytes["exact_replay_receipt.json"]
        ),
        "route_receipt_sha256": _sha(relative_bytes["route_receipt.json"]),
        "sealed_run_manifest_sha256": _sha(review_bytes["run_manifest.json"]),
    }
    if any(bindings.get(key) != value for key, value in actual.items()):
        raise ComparatorUIError("COMPARATOR_MACHINE_BINDING_MISMATCH")
    answer_key = _object(
        relative_bytes["unsupported_claim_answer_key.json"],
        "unsupported_claim_answer_key.json",
    )
    rows = answer_key.get("claims")
    if (
        answer_key.get("human_adjudication_required_for_final_rating") is not True
        or answer_key.get("adjudication_is_human_decision") is not False
        or not isinstance(rows, list)
        or not rows
        or any(
            not isinstance(row, dict)
            or set(row) != {"claim_id", "expected_support"}
            or not isinstance(row["claim_id"], str)
            for row in rows
        )
    ):
        raise ComparatorUIError("ANSWER_KEY_CONTRACT_INVALID")
    claim_ids = [row["claim_id"] for row in rows]
    if claim_ids != sorted(set(claim_ids)):
        raise ComparatorUIError("ANSWER_KEY_CLAIM_IDS_INVALID")
    return {
        "task_root": task_root,
        "review_root": review_root,
        "relative_bytes": relative_bytes,
        "review_bytes": review_bytes,
        "template": template,
        "template_raw": template_raw,
        "template_sha256": _sha(template_raw),
        "bindings": copy.deepcopy(bindings),
        "answer_key": answer_key,
        "claim_ids": claim_ids,
    }


def _verify_unchanged(evidence: dict[str, Any]) -> None:
    for relative, expected in evidence["relative_bytes"].items():
        if _member(evidence["task_root"], relative) != expected:
            raise ComparatorUIError(f"TASK_INPUT_CHANGED:{relative}")
    for relative, expected in evidence["review_bytes"].items():
        if _member(evidence["review_root"], relative) != expected:
            raise ComparatorUIError(f"REVIEW_INPUT_CHANGED:{relative}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _claim_controls(claim_ids: list[str], name: str) -> str:
    return "".join(
        f'<label class="claim"><input type="checkbox" name="{name}" '
        f'value="{_esc(claim_id)}"> {_esc(claim_id)}</label>'
        for claim_id in claim_ids
    )


def _rating(name: str, label: str) -> str:
    options = '<option value="">Choose 1–7</option>' + "".join(
        f'<option value="{value}">{value}</option>' for value in range(1, 8)
    )
    return f'<label>{_esc(label)}<select required name="{name}">{options}</select></label>'


def _decision_controls() -> str:
    return "".join(
        f'<label><input required type="radio" name="selected_decision" '
        f'value="{decision}"> {decision}</label>'
        for decision in DECISIONS
    )


def _page(title: str, body: str) -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>
body{{font:17px/1.5 system-ui;max-width:92rem;margin:0 auto;padding:1.5rem;color:#171717;background:#fafafa}}
main{{background:white;padding:1.5rem;border:1px solid #bbb;border-radius:.5rem}}
.notice{{border-left:.4rem solid #6b4f00;background:#fff8db;padding:.8rem 1rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1rem}}
.claim{{display:block;padding:.25rem}} fieldset{{margin:1rem 0;padding:1rem}} label{{display:block;margin:.55rem 0}}
select,input[type=text],textarea{{font:inherit;max-width:100%;padding:.35rem}} textarea{{width:100%;min-height:5rem}}
iframe{{width:100%;height:34rem;border:2px solid #555;background:white}} button{{font:inherit;padding:.7rem 1rem;font-weight:700}}
</style></head><body><main>{body}</main></body></html>"""
    return HTMLResponse(document, headers=HEADERS)


def _lane_page(
    evidence: dict[str, Any],
    lane: str,
    csrf: str,
    *,
    raw_locked: bool,
) -> HTMLResponse:
    is_raw = lane == "raw"
    label = "Lane A — raw captured candidate" if is_raw else "Lane B — governed review"
    artifact = "/artifact/raw" if is_raw else "/artifact/governed"
    action = "/compare/raw" if is_raw else "/compare/governed"
    progress = (
        "Lane A is open. Lane B and scoring remain locked."
        if is_raw
        else "Lane A is locked. Lane B is open; scoring occurs only after this submission."
    )
    reviewer = (
        '<label>Reviewer display name<input required maxlength="200" '
        'name="reviewer_display_name" type="text"></label>'
        if is_raw
        else ""
    )
    body = f"""
<h1 tabindex="-1">{_esc(label)}</h1>
<p class="notice"><strong>{_esc(progress)}</strong> This records a usability observation, not an Atlas final decision.</p>
<iframe title="{_esc(label)} artifact" src="{artifact}"></iframe>
<form method="post" action="{action}">
<input type="hidden" name="csrf" value="{_esc(csrf)}">
{reviewer}
<div class="grid"><fieldset><legend>Claims you identify as unsupported</legend>{_claim_controls(evidence['claim_ids'], 'detected_unsupported_claim_ids')}</fieldset>
<fieldset><legend>Claims you identify as limitations</legend>{_claim_controls(evidence['claim_ids'], 'detected_limitation_claim_ids')}</fieldset></div>
<div class="grid">{_rating('cognitive_load_1_to_7', 'Cognitive load (1 low, 7 high)')}{_rating('understandability_1_to_7', 'Understandability (1 low, 7 high)')}{_rating('usefulness_1_to_7', 'Usefulness (1 low, 7 high)')}</div>
<fieldset><legend>Decision you would select from this lane alone</legend>{_decision_controls()}</fieldset>
<label>Optional notes<textarea maxlength="4000" name="notes"></textarea></label>
<button type="submit">{'Lock Lane A and reveal Lane B' if is_raw else 'Lock Lane B and submit comparison'}</button>
</form><p>{_esc(NONAUTHORITY)}</p>"""
    if not is_raw and not raw_locked:
        raise ComparatorUIError("RAW_LANE_NOT_LOCKED")
    return _page(label, body)


def _parse_form(raw: bytes) -> dict[str, list[str]]:
    if len(raw) > MAX_FORM_BYTES:
        raise ComparatorUIError("FORM_SIZE_LIMIT_EXCEEDED")
    try:
        parsed = parse_qs(
            raw.decode("utf-8", errors="strict"),
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=128,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ComparatorUIError("FORM_INVALID") from exc
    return parsed


def _one(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name)
    if not isinstance(values, list) or len(values) != 1:
        raise ComparatorUIError(f"FORM_FIELD_INVALID:{name}")
    return values[0]


def _lane_observation(
    form: dict[str, list[str]],
    evidence: dict[str, Any],
    *,
    started_at: str,
    started_monotonic: float,
) -> dict[str, Any]:
    known = set(evidence["claim_ids"])

    def selected(name: str) -> list[str]:
        values = form.get(name, [])
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(value not in known for value in values)
        ):
            raise ComparatorUIError(f"FORM_FIELD_INVALID:{name}")
        return sorted(values)

    def rating(name: str) -> int:
        value = _one(form, name)
        if value not in {str(number) for number in range(1, 8)}:
            raise ComparatorUIError(f"FORM_FIELD_INVALID:{name}")
        return int(value)

    decision = _one(form, "selected_decision")
    notes = _one(form, "notes")
    if decision not in DECISIONS or len(notes) > MAX_NOTES:
        raise ComparatorUIError("FORM_DECISION_OR_NOTES_INVALID")
    ended = _utc_now()
    duration = round(max(0.001, time.monotonic() - started_monotonic), 3)
    return {
        "cognitive_load_1_to_7": rating("cognitive_load_1_to_7"),
        "completion_seconds": duration,
        "detected_limitation_claim_ids": selected(
            "detected_limitation_claim_ids"
        ),
        "detected_unsupported_claim_ids": selected(
            "detected_unsupported_claim_ids"
        ),
        "ended_at": ended,
        "notes": notes or None,
        "selected_decision": decision,
        "started_at": started_at,
        "understandability_1_to_7": rating("understandability_1_to_7"),
        "usefulness_1_to_7": rating("usefulness_1_to_7"),
    }


def _category_score(detected: list[str], expected: list[str]) -> dict[str, Any]:
    detected_set, expected_set = set(detected), set(expected)
    true_positive = len(detected_set & expected_set)
    false_positive = len(detected_set - expected_set)
    false_negative = len(expected_set - detected_set)
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0 if not expected_set else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    return {
        "exact_match": detected_set == expected_set,
        "false_negative_count": false_negative,
        "false_positive_count": false_positive,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "true_positive_count": true_positive,
    }


def _score(evidence: dict[str, Any], raw: dict[str, Any], governed: dict[str, Any]) -> dict[str, Any]:
    rows = evidence["answer_key"]["claims"]
    unsupported = sorted(
        row["claim_id"]
        for row in rows
        if row["expected_support"] == "UNSUPPORTED_AND_CONTRADICTED"
    )
    limitations = sorted(
        row["claim_id"]
        for row in rows
        if row["expected_support"] == "SOURCE_SUPPORTED_WITH_LIMITATION"
    )

    def lane(value: dict[str, Any]) -> dict[str, Any]:
        unsupported_score = _category_score(
            value["detected_unsupported_claim_ids"], unsupported
        )
        limitation_score = _category_score(
            value["detected_limitation_claim_ids"], limitations
        )
        return {
            "deliberately_unsupported_claim_exactly_identified": unsupported_score[
                "exact_match"
            ],
            "identification_error_count": sum(
                score["false_positive_count"] + score["false_negative_count"]
                for score in (unsupported_score, limitation_score)
            ),
            "limitation_detection": limitation_score,
            "unsupported_detection": unsupported_score,
        }

    return {
        "answer_key_revealed_or_scored_before_raw_lane_lock": False,
        "answer_key_sha256": evidence["bindings"]["answer_key_sha256"],
        "evaluated_after_both_human_lanes_locked": True,
        "expected_limitation_claim_ids": limitations,
        "expected_unsupported_claim_ids": unsupported,
        "governed_lane": lane(governed),
        "raw_lane": lane(raw),
        "scoring_is_not_truth_or_final_human_adjudication": True,
    }


def _comparison(raw: dict[str, Any], governed: dict[str, Any], scoring: dict[str, Any]) -> dict[str, bool]:
    raw_errors = scoring["raw_lane"]["identification_error_count"]
    governed_errors = scoring["governed_lane"]["identification_error_count"]
    reduced = (
        governed["cognitive_load_1_to_7"] < raw["cognitive_load_1_to_7"]
        and governed["completion_seconds"] <= raw["completion_seconds"]
        and governed_errors <= raw_errors
        and governed["understandability_1_to_7"]
        >= raw["understandability_1_to_7"]
        and governed["usefulness_1_to_7"] >= raw["usefulness_1_to_7"]
    )
    return {
        "governance_reduced_burden": reduced,
        "governed_faster": governed["completion_seconds"] < raw["completion_seconds"],
        "governed_less_burdensome": governed["cognitive_load_1_to_7"]
        < raw["cognitive_load_1_to_7"],
        "governed_more_accurate": governed_errors < raw_errors,
        "governed_more_understandable": governed["understandability_1_to_7"]
        > raw["understandability_1_to_7"],
        "governed_more_useful": governed["usefulness_1_to_7"]
        > raw["usefulness_1_to_7"],
        "negative_result_preserved": not reduced,
    }


def _publish(
    evidence: dict[str, Any],
    output_root: Path,
    raw: dict[str, Any],
    governed: dict[str, Any],
    reviewer: str,
) -> Path:
    _verify_unchanged(evidence)
    scoring = _score(evidence, raw, governed)
    comparison = _comparison(raw, governed, scoring)
    comparison_id = "COMPARISON-" + evidence["template_sha256"][:24]
    submitted_at = _utc_now()
    document = copy.deepcopy(evidence["template"])
    document.update(
        {
            "comparison": comparison,
            "governed_lane": governed,
            "human_fields_complete": True,
            "human_review_status": "COMPARISON_SUBMITTED",
            "machine_scoring": scoring,
            "raw_lane": raw,
            "reviewer_display_name": reviewer,
            "schema_id": OUTPUT_SCHEMA_ID,
            "submitted_by_human": True,
            "submitted_receipt": {
                "comparison_id": comparison_id,
                "governed_lane_locked": True,
                "raw_lane_locked_before_governed_reveal": True,
                "submitted_at": submitted_at,
                "unsubmitted_comparator_sha256": evidence["template_sha256"],
            },
        }
    )
    document["nonauthority"] = NONAUTHORITY
    document["side_effects"] = NO_EFFECTS
    payload = _canonical(document)
    digest = _sha(payload)
    summary = (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>Usability comparison receipt</title><body>"
        "<h1>Usability comparison recorded</h1>"
        f"<p>Comparison ID: {_esc(comparison_id)}</p>"
        f"<p>Governance reduced burden: {_esc(comparison['governance_reduced_burden'])}; "
        f"negative result preserved: {_esc(comparison['negative_result_preserved'])}.</p>"
        f"<p>{_esc(NONAUTHORITY)}</p></body></html>"
    ).encode("utf-8")
    claimed_identity: tuple[int, int] | None = None
    try:
        try:
            output_root.mkdir()
        except FileExistsError as exc:
            raise ComparatorUIError("COMPARISON_ALREADY_SUBMITTED") from exc
        except OSError as exc:
            raise ComparatorUIError("COMPARISON_PUBLICATION_FAILED") from exc
        claimed_identity = _directory_identity(output_root, "COMPARISON_OUTPUT")
        comparison_root = output_root / comparison_id
        comparison_root.mkdir()
        receipt = comparison_root / "usability_comparator_submitted.json"
        with receipt.open("xb") as stream:
            stream.write(payload)
        with (comparison_root / "usability_comparator_submitted.json.sha256").open(
            "xb"
        ) as stream:
            stream.write(
                f"{digest}  usability_comparator_submitted.json\n".encode("ascii")
            )
        with (comparison_root / "usability_comparison_receipt.html").open(
            "xb"
        ) as stream:
            stream.write(summary)
        if _directory_identity(output_root, "COMPARISON_OUTPUT") != claimed_identity:
            raise ComparatorUIError("COMPARISON_OUTPUT_IDENTITY_CHANGED")
        _verify_unchanged(evidence)
    except BaseException:
        # Once the public destination has been exclusively claimed, never
        # mutate it again by pathname during failure cleanup.  A same-user
        # actor can replace a pathname between any identity check and a later
        # rename/delete.  Leaving the partial owned directory as a fail-closed
        # tombstone makes retries reject without risking mutation of a raced
        # or swapped-in foreign target.
        raise
    return output_root / comparison_id / "usability_comparator_submitted.json"


def _loopback_host(value: str) -> bool:
    try:
        addresses = socket.getaddrinfo(value, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(item[4][0]).is_loopback for item in addresses
        )
    except (OSError, ValueError):
        return False


def _request_is_loopback(request: Request) -> bool:
    client = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(client).is_loopback:
            return False
    except ValueError:
        return False
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1", "testserver"}


def create_app(
    task_root: str | Path,
    review_run_root: str | Path,
    output_root: str | Path,
) -> FastAPI:
    task = _root(task_root, "TASK_ROOT")
    review = _root(review_run_root, "REVIEW_RUN_ROOT")
    output = _output_path(output_root, task, review)
    evidence = _load_evidence(task, review)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    state: dict[str, Any] = {
        "raw": None,
        "raw_started_at": None,
        "raw_started_monotonic": None,
        "governed": None,
        "governed_started_at": None,
        "governed_started_monotonic": None,
        "reviewer": None,
        "raw_csrf": secrets.token_urlsafe(32),
        "governed_csrf": secrets.token_urlsafe(32),
        "published": False,
    }

    def reject(reason: str, status: int) -> HTMLResponse:
        return _page("Request rejected", f"<h1>Request rejected</h1><p>{_esc(reason)}</p>")

    @app.middleware("http")
    async def bounded_request(request: Request, call_next):
        if not _request_is_loopback(request):
            response = reject("REQUEST_NOT_LOOPBACK", 403)
            response.status_code = 403
            return response
        if request.method == "POST" and request.headers.get(
            "sec-fetch-site", "same-origin"
        ) == "cross-site":
            response = reject("REQUEST_FETCH_SITE_CROSS_SITE", 403)
            response.status_code = 403
            return response
        return await call_next(request)

    @app.get("/compare", response_class=HTMLResponse)
    async def compare():
        if state["published"] or os.path.lexists(output):
            response = reject("COMPARISON_ALREADY_SUBMITTED", 409)
            response.status_code = 409
            return response
        if state["raw"] is None:
            if state["raw_started_at"] is None:
                state["raw_started_at"] = _utc_now()
                state["raw_started_monotonic"] = time.monotonic()
            return _lane_page(
                evidence, "raw", state["raw_csrf"], raw_locked=False
            )
        if state["governed_started_at"] is None:
            state["governed_started_at"] = _utc_now()
            state["governed_started_monotonic"] = time.monotonic()
        return _lane_page(
            evidence, "governed", state["governed_csrf"], raw_locked=True
        )

    @app.get("/artifact/raw")
    async def raw_artifact():
        return Response(
            evidence["relative_bytes"]["raw_lane/raw_candidate.html"],
            media_type="text/html",
            headers=ARTIFACT_HEADERS,
        )

    @app.get("/artifact/governed")
    async def governed_artifact():
        if state["raw"] is None:
            response = reject("RAW_LANE_NOT_LOCKED", 409)
            response.status_code = 409
            return response
        return Response(
            evidence["review_bytes"]["final_review.html"],
            media_type="text/html",
            headers=ARTIFACT_HEADERS,
        )

    @app.post("/compare/raw", response_class=HTMLResponse)
    async def submit_raw(request: Request):
        if state["raw"] is not None or state["published"]:
            response = reject("RAW_LANE_ALREADY_LOCKED", 409)
            response.status_code = 409
            return response
        try:
            form = _parse_form(await request.body())
            if not secrets.compare_digest(_one(form, "csrf"), state["raw_csrf"]):
                raise ComparatorUIError("CSRF_INVALID")
            reviewer = _one(form, "reviewer_display_name").strip()
            if not reviewer or len(reviewer) > MAX_REVIEWER:
                raise ComparatorUIError("REVIEWER_INVALID")
            if state["raw_started_at"] is None:
                raise ComparatorUIError("RAW_LANE_NOT_STARTED")
            observation = _lane_observation(
                form,
                evidence,
                started_at=state["raw_started_at"],
                started_monotonic=state["raw_started_monotonic"],
            )
        except ComparatorUIError as exc:
            response = reject(str(exc), 400)
            response.status_code = 400
            return response
        state["raw"], state["reviewer"] = observation, reviewer
        state["governed_started_at"] = _utc_now()
        state["governed_started_monotonic"] = time.monotonic()
        return _lane_page(
            evidence, "governed", state["governed_csrf"], raw_locked=True
        )

    @app.post("/compare/governed", response_class=HTMLResponse)
    async def submit_governed(request: Request):
        if state["raw"] is None:
            response = reject("RAW_LANE_NOT_LOCKED", 409)
            response.status_code = 409
            return response
        if state["governed"] is not None or state["published"]:
            response = reject("COMPARISON_ALREADY_SUBMITTED", 409)
            response.status_code = 409
            return response
        try:
            form = _parse_form(await request.body())
            if not secrets.compare_digest(
                _one(form, "csrf"), state["governed_csrf"]
            ):
                raise ComparatorUIError("CSRF_INVALID")
            observation = _lane_observation(
                form,
                evidence,
                started_at=state["governed_started_at"],
                started_monotonic=state["governed_started_monotonic"],
            )
            receipt = _publish(
                evidence, output, state["raw"], observation, state["reviewer"]
            )
        except ComparatorUIError as exc:
            response = reject(str(exc), 409)
            response.status_code = 409
            return response
        state["governed"], state["published"] = observation, True
        return _page(
            "Comparison recorded",
            "<h1 tabindex=\"-1\">Comparison recorded</h1>"
            f"<p>The immutable comparator was written outside the sealed run root as {_esc(receipt.name)}.</p>"
            f"<p>{_esc(NONAUTHORITY)}</p>",
        )

    app.state.comparator_evidence = evidence
    app.state.comparator_state = state
    return app


def smoke_render(
    task_root: str | Path,
    review_run_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    app = create_app(task_root, review_run_root, output_root)
    evidence = app.state.comparator_evidence
    raw = _lane_page(evidence, "raw", "smoke", raw_locked=False).body
    governed = _lane_page(
        evidence, "governed", "smoke", raw_locked=True
    ).body
    output = Path(output_root)
    if os.path.lexists(output):
        raise ComparatorUIError("SMOKE_TEST_CREATED_OUTPUT")
    return {
        "authority_effect": "NONE",
        "governed_lane_rendered": b"Lane B" in governed,
        "host": "127.0.0.1",
        "human_observations_synthesized": False,
        "output_created": False,
        "raw_lane_rendered": b"Lane A" in raw,
        "schema_id": "uvlm.atlas.totality.usability_comparator_smoke.v1",
        "side_effects": NO_EFFECTS,
        "valid": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", required=True, type=Path)
    parser.add_argument("--review-run-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    arguments = parser.parse_args()
    if not _loopback_host(arguments.host):
        raise SystemExit("host must resolve only to loopback")
    if arguments.smoke_test:
        result = smoke_render(
            arguments.task_root,
            arguments.review_run_root,
            arguments.output_root,
        )
        print(_canonical(result).decode("utf-8"), end="")
        return 0
    app = create_app(
        arguments.task_root,
        arguments.review_run_root,
        arguments.output_root,
    )
    if not arguments.no_browser:
        webbrowser.open(f"http://{arguments.host}:{arguments.port}/compare")
    uvicorn.run(app, host=arguments.host, port=arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
