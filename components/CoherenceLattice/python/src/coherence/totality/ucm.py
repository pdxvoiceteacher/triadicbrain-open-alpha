# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Typed UCM state and CE-compatible full-posterior projection."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping

from .canonical import require_exact_keys, require_identifier, require_sha256, sha256_json
from .errors import ValidationError

UCM_SCHEMA = "uvlm.coherence.totality.ucm_state.v1"
PROJECTOR_SCHEMA = "uvlm.coherence.totality.projector_receipt.v1"
RESIDUAL_SCHEMA = "uvlm.coherence.totality.residual_refusal.v1"
AXES = ("E_cpl", "T_tr", "E_s", "phase_stability_lambda", "mutual_containment_mu")
PATTERN_POSTURES = {"IN_DISTRIBUTION", "AMBIGUOUS", "OOD", "NEW_PATTERN"}
CONTEXT_FIELDS = {
    "request_sha256", "candidate_sha256", "grounding_manifest_sha256", "source_sha256", "claim_map_sha256"
}


def _unit(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"UCM_UNIT_NUMBER_REQUIRED:{path}")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValidationError(f"UCM_UNIT_INTERVAL_REQUIRED:{path}")
    return number


def _context(value: Any) -> dict[str, str]:
    require_exact_keys(value, required=CONTEXT_FIELDS, path="$.expected_context")
    return {name: require_sha256(value[name], f"$.expected_context.{name}") for name in sorted(CONTEXT_FIELDS)}


def build_ucm_state(
    *,
    run_id: str,
    candidate_id: str,
    expected_context: Mapping[str, str],
    axes: Mapping[str, float],
    uncertainty: float,
    source_ref_count: int,
    unsupported_claim_ids: list[str],
    hypotheses: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    context = _context(dict(expected_context))
    if set(axes) != set(AXES):
        raise ValidationError("UCM_AXES_EXACT_SET_REQUIRED")
    normalized_axes = {name: _unit(axes[name], f"$.axes.{name}") for name in AXES}
    uncertainty_value = _unit(uncertainty, "$.uncertainty")
    if isinstance(source_ref_count, bool) or not isinstance(source_ref_count, int) or source_ref_count < 0:
        raise ValidationError("UCM_SOURCE_REF_COUNT_INVALID")
    if len(set(unsupported_claim_ids)) != len(unsupported_claim_ids):
        raise ValidationError("UCM_UNSUPPORTED_CLAIM_ID_DUPLICATE")
    unsupported = sorted(require_identifier(item, "$.unsupported_claim_ids[]") for item in unsupported_claim_ids)
    raw_hypotheses = hypotheses or [
        {
            "hypothesis_id": candidate_id,
            "score": 1.0 - uncertainty_value,
            "equivalence_group": candidate_id,
            "pattern_posture": "IN_DISTRIBUTION",
        }
    ]
    if not 1 <= len(raw_hypotheses) <= 10_000:
        raise ValidationError("UCM_HYPOTHESIS_COUNT_INVALID")
    normalized_hypotheses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_hypotheses):
        require_exact_keys(
            item,
            required={"hypothesis_id", "score", "equivalence_group", "pattern_posture"},
            path=f"$.hypotheses[{index}]",
        )
        hid = require_identifier(item["hypothesis_id"], f"$.hypotheses[{index}].hypothesis_id")
        if hid in seen:
            raise ValidationError(f"UCM_HYPOTHESIS_ID_DUPLICATE:{hid}")
        seen.add(hid)
        score = item["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise ValidationError(f"UCM_HYPOTHESIS_SCORE_INVALID:{hid}")
        posture = item["pattern_posture"]
        if posture not in PATTERN_POSTURES:
            raise ValidationError(f"UCM_PATTERN_POSTURE_INVALID:{hid}")
        normalized_hypotheses.append(
            {
                "hypothesis_id": hid,
                "score": float(score),
                "equivalence_group": require_identifier(
                    item["equivalence_group"], f"$.hypotheses[{index}].equivalence_group"
                ),
                "pattern_posture": posture,
            }
        )
    normalized_hypotheses.sort(key=lambda row: row["hypothesis_id"])
    return {
        "schema_id": UCM_SCHEMA,
        "run_id": require_identifier(run_id, "$.run_id"),
        "candidate_id": require_identifier(candidate_id, "$.candidate_id"),
        "expected_context": context,
        "axes": normalized_axes,
        "uncertainty": uncertainty_value,
        "source_ref_count": source_ref_count,
        "unsupported_claim_ids": unsupported,
        "hypotheses": normalized_hypotheses,
        "authority_effect": "NONE",
    }


def validate_ucm_state(value: Any, *, expected_context: Mapping[str, str] | None = None) -> dict[str, Any]:
    require_exact_keys(
        value,
        required={
            "schema_id", "run_id", "candidate_id", "expected_context", "axes", "uncertainty",
            "source_ref_count", "unsupported_claim_ids", "hypotheses", "authority_effect",
        },
    )
    if value["schema_id"] != UCM_SCHEMA or value["authority_effect"] != "NONE":
        raise ValidationError("UCM_SCHEMA_OR_AUTHORITY_INVALID")
    rebuilt = build_ucm_state(
        run_id=value["run_id"],
        candidate_id=value["candidate_id"],
        expected_context=value["expected_context"],
        axes=value["axes"],
        uncertainty=value["uncertainty"],
        source_ref_count=value["source_ref_count"],
        unsupported_claim_ids=value["unsupported_claim_ids"],
        hypotheses=value["hypotheses"],
    )
    if rebuilt != value:
        raise ValidationError("UCM_CANONICAL_STATE_MISMATCH")
    if expected_context is not None and rebuilt["expected_context"] != _context(dict(expected_context)):
        raise ValidationError("UCM_EXPECTED_CONTEXT_MISMATCH")
    return rebuilt


def _softmax(scores: list[float]) -> list[float]:
    maximum = max(scores)
    exponentials = [math.exp(value - maximum) for value in scores]
    denominator = math.fsum(exponentials)
    return [value / denominator for value in exponentials]


def _disposition(state: dict[str, Any], full_margin: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    axes = state["axes"]
    psi_cl = axes["E_cpl"] * axes["T_tr"]
    if state["source_ref_count"] == 0:
        reasons.append("NO_AUTHENTICATED_SOURCE_REFERENCE")
    if axes["T_tr"] < 0.20:
        reasons.append("TRANSPARENCY_BELOW_REFUSAL_FLOOR")
    if state["uncertainty"] >= 0.85:
        reasons.append("UNCERTAINTY_ABOVE_REFUSAL_CEILING")
    if state["unsupported_claim_ids"]:
        reasons.append("INSUFFICIENT_EVIDENCE_FOR_CLAIMS")
    if any(row["pattern_posture"] == "OOD" for row in state["hypotheses"]):
        reasons.append("OOD_PATTERN_DETECTED")
    if reasons:
        return "REFUSE", sorted(reasons)
    if psi_cl < 0.45:
        reasons.append("COHERENCE_BELOW_SCREEN_THRESHOLD")
    if axes["E_s"] < 0.50:
        reasons.append("ETHICAL_SYMMETRY_REQUIRES_REVIEW")
    if state["uncertainty"] > 0.40:
        reasons.append("UNCERTAINTY_REQUIRES_REVIEW")
    if full_margin < 0.10:
        reasons.append("FULL_POSTERIOR_MARGIN_AMBIGUOUS")
    if any(row["pattern_posture"] == "NEW_PATTERN" for row in state["hypotheses"]):
        reasons.append("NEW_PATTERN_REQUIRES_REVIEW")
    if any(row["pattern_posture"] == "AMBIGUOUS" for row in state["hypotheses"]):
        reasons.append("PATTERN_AMBIGUITY_REQUIRES_REVIEW")
    if reasons:
        return "HOLD", sorted(reasons)
    return "PASS_SCREEN", ["BOUNDED_SCREEN_CRITERIA_MET"]


def project_ucm(value: Any, *, top_k: int = 8) -> dict[str, dict[str, Any]]:
    state = validate_ucm_state(value)
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise ValidationError("PROJECTOR_TOP_K_INTEGER_REQUIRED")
    probabilities = _softmax([row["score"] for row in state["hypotheses"]])
    candidates: list[dict[str, Any]] = []
    group_mass: dict[str, float] = defaultdict(float)
    for row, probability in zip(state["hypotheses"], probabilities, strict=True):
        candidate = {**row, "probability": probability}
        candidates.append(candidate)
        group_mass[row["equivalence_group"]] += probability
    groups = sorted(
        ({"equivalence_group": group, "probability": probability} for group, probability in group_mass.items()),
        key=lambda row: (-row["probability"], row["equivalence_group"]),
    )
    margin = groups[0]["probability"] - (groups[1]["probability"] if len(groups) > 1 else 0.0)
    disposition, reasons = _disposition(state, margin)
    safe_top_k = max(1, min(top_k, len(candidates)))
    presentation_rows = sorted(candidates, key=lambda row: (-row["probability"], row["hypothesis_id"]))[:safe_top_k]
    retained = math.fsum(row["probability"] for row in presentation_rows)
    projector = {
        "schema_id": PROJECTOR_SCHEMA,
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "ucm_state_sha256": sha256_json(state),
        "expected_context": state["expected_context"],
        "psi_cl": state["axes"]["E_cpl"] * state["axes"]["T_tr"],
        "full_candidate_posterior": sorted(candidates, key=lambda row: row["hypothesis_id"]),
        "full_equivalence_posterior": groups,
        "full_posterior_margin": margin,
        "disposition": disposition,
        "reasons": reasons,
        "presentation": {
            "top_k": safe_top_k,
            "candidates": presentation_rows,
            "retained_mass": retained,
            "omitted_mass": max(0.0, 1.0 - retained),
            "disposition_invariant_to_top_k": True,
        },
        "authority_effect": "NONE",
        "human_review_required": True,
    }
    residual = {
        # Residual is computed from the full posterior.  Presentation-only
        # top_k omission remains exclusively in projector.presentation.
        "omitted_probability_mass": 0.0,
        "unsupported_claim_ids": state["unsupported_claim_ids"],
        "ambiguity": margin < 0.10 or any(row["pattern_posture"] == "AMBIGUOUS" for row in state["hypotheses"]),
        "ood_hypothesis_ids": sorted(row["hypothesis_id"] for row in state["hypotheses"] if row["pattern_posture"] == "OOD"),
        "new_pattern_hypothesis_ids": sorted(row["hypothesis_id"] for row in state["hypotheses"] if row["pattern_posture"] == "NEW_PATTERN"),
    }
    residual_refusal = {
        "schema_id": RESIDUAL_SCHEMA,
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "projector_invariant_sha256": sha256_json({
            key: projector[key]
            for key in (
                "ucm_state_sha256", "expected_context", "psi_cl", "full_candidate_posterior",
                "full_equivalence_posterior", "full_posterior_margin", "disposition", "reasons",
            )
        }),
        "residual": residual,
        "refusal": {"triggered": disposition == "REFUSE", "reason_codes": reasons if disposition == "REFUSE" else []},
        "disposition": disposition,
        "reasons": reasons,
        "authority_effect": "NONE",
    }
    return {"projector": projector, "residual_refusal": residual_refusal}
