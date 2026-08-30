from __future__ import annotations

from typing import Literal, TypedDict

AegisDecision = Literal[
    "admit",
    "admit_with_controls",
    "hold_for_human_review",
    "reject_fail_closed",
    "alarm_requires_elevated_review",
]


class ScenarioPolicy(TypedDict):
    decision: AegisDecision
    reason_codes: list[str]
    source_scope_status: str
    consent_status: str
    grounding_status: str
    security_screen_status: str
    canonicalization_status: str
    content_type: str
    request_envelope_ref: str | None
    failure_receipt_ref: str | None
    human_review_required: bool
