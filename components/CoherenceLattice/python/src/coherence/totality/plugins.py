"""Optional-plugin receipt validation with explicit zero-effect defaults."""

from __future__ import annotations

from typing import Any

from .canonical import require_exact_keys, require_identifier, require_sha256, reject_prohibited_surfaces, sha256_json
from .errors import ValidationError

PLUGIN_RECEIPT_SCHEMA = "uvlm.coherence.totality.plugin_receipt.v1"
OPTIONAL_PLUGIN_RECEIPTS_SCHEMA = "uvlm.coherence.totality.optional_plugin_receipts.v1"
OPTIONAL_PLUGIN_IDS = (
    "uvlm_432_humanities_atlas",
    "master_preserving_waveform_rosetta",
    "recursive_geometric_fiber_rosetta",
    "quantum_pattern_donors",
    "sacred_geometry_donors",
    "specialized_scientific_vocabularies",
    "discovery_navigation",
    "civilizational_topology",
)
# Exact disabled-plugin effect surface: the normalized union of the active
# AEGIS ceiling, the sealed-route ceiling, and dormant-route zero-effect
# postures.  Authority is also carried by the aggregate ``authority_effect``.
EFFECT_KEYS = (
    "network",
    "provider_invocation",
    "memory_read",
    "memory_write",
    "pmr_read",
    "pmr_write",
    "atlas_read",
    "atlas_write",
    "prior_influence",
    "federation",
    "training",
    "source_mutation",
    "candidate_mutation",
    "sophia_audit_manufactured",
    "candidate_authority",
    "truth_certification",
    "canonization",
    "publication",
    "deployment",
    "release",
    "external_action",
)


def disabled_plugin_receipt(plugin_id: str) -> dict[str, Any]:
    return {
        "schema_id": PLUGIN_RECEIPT_SCHEMA,
        "plugin_id": require_identifier(plugin_id, "$.plugin_id"),
        "status": "DISABLED_BY_DEFAULT",
        "output_schema": None,
        "output_sha256": None,
        "output": None,
        "declared_effects": dict.fromkeys(EFFECT_KEYS, False),
        "observed_effects": dict.fromkeys(EFFECT_KEYS, False),
        "authority_effect": "NONE",
    }


def disabled_plugin_catalog_receipt() -> dict[str, Any]:
    """Return complete deterministic absence evidence for the optional catalog."""

    return {
        "schema_id": OPTIONAL_PLUGIN_RECEIPTS_SCHEMA,
        "receipts": [disabled_plugin_receipt(plugin_id) for plugin_id in OPTIONAL_PLUGIN_IDS],
        "all_optional": True,
        "all_disabled_by_default": True,
        "authority_effect": "NONE",
    }


def validate_plugin_receipt(value: Any, *, execution_authorized: bool = False) -> dict[str, Any]:
    require_exact_keys(
        value,
        required={
            "schema_id", "plugin_id", "status", "output_schema", "output_sha256", "output",
            "declared_effects", "observed_effects", "authority_effect",
        },
    )
    if value["schema_id"] != PLUGIN_RECEIPT_SCHEMA or value["authority_effect"] != "NONE":
        raise ValidationError("PLUGIN_RECEIPT_SCHEMA_OR_AUTHORITY_INVALID")
    require_identifier(value["plugin_id"], "$.plugin_id")
    for name in ("declared_effects", "observed_effects"):
        require_exact_keys(value[name], required=EFFECT_KEYS, path=f"$.{name}")
        if any(item is not False for item in value[name].values()):
            raise ValidationError("PLUGIN_EFFECT_NOT_ALLOWED")
    if value["status"] == "DISABLED_BY_DEFAULT":
        if any(value[name] is not None for name in ("output_schema", "output_sha256", "output")):
            raise ValidationError("PLUGIN_DISABLED_OUTPUT_PROHIBITED")
    elif value["status"] == "EXECUTED":
        if not execution_authorized:
            raise ValidationError("PLUGIN_EXECUTION_NOT_AUTHORIZED")
        require_exact_keys(value["output"], required={"schema_id", "payload", "authority_effect"}, path="$.output")
        reject_prohibited_surfaces(value["output"]["payload"], "$.output.payload")
        if value["output"]["schema_id"] != value["output_schema"] or value["output"]["authority_effect"] != "NONE":
            raise ValidationError("PLUGIN_OUTPUT_SCHEMA_OR_AUTHORITY_INVALID")
        if require_sha256(value["output_sha256"], "$.output_sha256") != sha256_json(value["output"]):
            raise ValidationError("PLUGIN_OUTPUT_SHA256_MISMATCH")
    else:
        raise ValidationError("PLUGIN_STATUS_INVALID")
    return value


def validate_disabled_plugin_catalog(value: Any) -> dict[str, Any]:
    """Validate exact eight-entry, zero-effect, disabled-by-default coverage."""

    require_exact_keys(
        value,
        required={
            "schema_id",
            "receipts",
            "all_optional",
            "all_disabled_by_default",
            "authority_effect",
        },
    )
    if (
        value["schema_id"] != OPTIONAL_PLUGIN_RECEIPTS_SCHEMA
        or value["all_optional"] is not True
        or value["all_disabled_by_default"] is not True
        or value["authority_effect"] != "NONE"
        or not isinstance(value["receipts"], list)
    ):
        raise ValidationError("OPTIONAL_PLUGIN_CATALOG_POSTURE_INVALID")
    receipts = [validate_plugin_receipt(receipt) for receipt in value["receipts"]]
    if tuple(receipt["plugin_id"] for receipt in receipts) != OPTIONAL_PLUGIN_IDS:
        raise ValidationError("OPTIONAL_PLUGIN_CATALOG_COVERAGE_INVALID")
    return {**value, "receipts": receipts}
