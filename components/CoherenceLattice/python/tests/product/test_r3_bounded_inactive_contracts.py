from __future__ import annotations

import ast
import copy
import inspect
from pathlib import Path

import pytest

from coherence.totality import cli
from coherence.totality.errors import ValidationError
from coherence.totality.inactive_routes import (
    inactive_route_receipt,
    validate_inactive_route_receipt,
)
from coherence.totality.plugins import (
    EFFECT_KEYS,
    OPTIONAL_PLUGIN_IDS,
    disabled_plugin_catalog_receipt,
    validate_disabled_plugin_catalog,
)
from coherence.totality.pmr import PMRReferenceStore


COMPONENT_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = COMPONENT_ROOT.parents[1]
ACTIVE_ROUTE_FILES = (
    COMPONENT_ROOT / "python/src/coherence/totality/cli.py",
    REPOSITORY_ROOT / "integration/tools/run_totality_product_route.py",
    REPOSITORY_ROOT / "components/Sophia/python/src/sophia/triadic/totality_audit.py",
    REPOSITORY_ROOT
    / "components/uvlm-publications/python/src/atlas/triadic/totality_posture.py",
)
EXPECTED_PLUGIN_EFFECT_KEYS = (
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


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_exact_optional_plugin_catalog_is_disabled_and_zero_effect() -> None:
    assert EFFECT_KEYS == EXPECTED_PLUGIN_EFFECT_KEYS
    assert OPTIONAL_PLUGIN_IDS == (
        "uvlm_432_humanities_atlas",
        "master_preserving_waveform_rosetta",
        "recursive_geometric_fiber_rosetta",
        "quantum_pattern_donors",
        "sacred_geometry_donors",
        "specialized_scientific_vocabularies",
        "discovery_navigation",
        "civilizational_topology",
    )
    catalog = disabled_plugin_catalog_receipt()
    assert validate_disabled_plugin_catalog(catalog) == catalog
    assert tuple(row["plugin_id"] for row in catalog["receipts"]) == OPTIONAL_PLUGIN_IDS
    assert all(row["status"] == "DISABLED_BY_DEFAULT" for row in catalog["receipts"])
    assert all(row["output"] is row["output_schema"] is row["output_sha256"] is None for row in catalog["receipts"])
    assert all(
        tuple(row[effect_map]) == EXPECTED_PLUGIN_EFFECT_KEYS
        for row in catalog["receipts"]
        for effect_map in ("declared_effects", "observed_effects")
    )
    assert all(
        not any(row[effect_map].values())
        for row in catalog["receipts"]
        for effect_map in ("declared_effects", "observed_effects")
    )
    assert "disabled_plugin_catalog_receipt()" in inspect.getsource(
        cli._build_core_success_from_inputs
    )
    assert "validate_disabled_plugin_catalog" in inspect.getsource(
        cli._build_core_success_from_inputs
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "unknown",
        "effect",
        "missing_declared_effect",
        "missing_observed_effect",
        "extra_declared_effect",
        "extra_observed_effect",
        "non_boolean_zero",
    ],
)
def test_optional_plugin_catalog_mutations_fail_closed(mutation: str) -> None:
    catalog = disabled_plugin_catalog_receipt()
    if mutation == "missing":
        catalog["receipts"].pop()
    elif mutation == "duplicate":
        catalog["receipts"][-1] = copy.deepcopy(catalog["receipts"][0])
    elif mutation == "unknown":
        catalog["receipts"][-1]["plugin_id"] = "unregistered_plugin"
    elif mutation == "effect":
        catalog["receipts"][0]["observed_effects"]["network"] = True
    elif mutation == "missing_declared_effect":
        del catalog["receipts"][0]["declared_effects"]["publication"]
    elif mutation == "missing_observed_effect":
        del catalog["receipts"][0]["observed_effects"]["publication"]
    elif mutation == "extra_declared_effect":
        catalog["receipts"][0]["declared_effects"]["authority"] = False
    elif mutation == "extra_observed_effect":
        catalog["receipts"][0]["observed_effects"]["undeclared_effect"] = False
    else:
        catalog["receipts"][0]["declared_effects"]["training"] = 0
    with pytest.raises(ValidationError):
        validate_disabled_plugin_catalog(catalog)


def test_every_declared_plugin_effect_fails_closed_when_positive() -> None:
    for effect_map in ("declared_effects", "observed_effects"):
        for effect_key in EXPECTED_PLUGIN_EFFECT_KEYS:
            catalog = disabled_plugin_catalog_receipt()
            catalog["receipts"][0][effect_map][effect_key] = True
            with pytest.raises(ValidationError, match="PLUGIN_EFFECT_NOT_ALLOWED"):
                validate_disabled_plugin_catalog(catalog)


@pytest.mark.parametrize("route_id", ["OMEGA", "RETROSYNTHESIS"])
def test_inactive_route_receipts_are_exact_and_nonauthoritative(route_id: str) -> None:
    receipt = inactive_route_receipt(route_id)
    assert validate_inactive_route_receipt(receipt) == receipt
    assert receipt["normal_route_reference_observed"] is False
    assert receipt["active_route_reachable"] is False
    assert receipt["output_reentry_performed"] is False
    assert receipt["authority_effect"] == "NONE"
    assert not any(receipt["effects"].values())


def test_omega_is_not_referenced_by_the_active_totality_route() -> None:
    assert all(
        "omega" not in path.read_text(encoding="utf-8").casefold()
        for path in ACTIVE_ROUTE_FILES
    )
    assert all(
        "omega" not in module.casefold()
        for path in ACTIVE_ROUTE_FILES
        for module in _imports(path)
    )
    receipt = inactive_route_receipt("OMEGA")
    assert receipt["status"] == "NOT_APPLICABLE_NORMAL_ROUTE_NO_REFERENCE"
    assert receipt["stop_reason_packet_required"] is False


def test_retrosynthesis_active_route_is_unreachable() -> None:
    assert all(
        "retrosynthesis" not in path.read_text(encoding="utf-8").casefold()
        for path in ACTIVE_ROUTE_FILES
    )
    assert all(
        "retrosynthesis" not in module.casefold()
        for path in ACTIVE_ROUTE_FILES
        for module in _imports(path)
    )
    receipt = inactive_route_receipt("RETROSYNTHESIS")
    assert receipt["status"] == "CONTRACTED_AND_DORMANT"
    assert receipt["effects"]["canonization_performed"] is False
    assert receipt["effects"]["sophia_audit_manufactured"] is False


def test_coherencelattice_cannot_manufacture_a_sophia_audit() -> None:
    totality_sources = tuple(
        (COMPONENT_ROOT / "python/src/coherence/totality").glob("*.py")
    )
    assert all(
        not module.casefold().startswith("sophia")
        for path in totality_sources
        for module in _imports(path)
    )
    cli_tree = ast.parse(
        (COMPONENT_ROOT / "python/src/coherence/totality/cli.py").read_text(
            encoding="utf-8"
        )
    )
    write_calls = [
        node
        for node in ast.walk(cli_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_write_artifact"
    ]
    assert all(
        len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
        for node in write_calls
    )
    written_paths = {
        node.args[1].value
        for node in write_calls
    }
    assert "sophia_audit_packet.json" not in written_paths


def test_pmr_cannot_promote_itself_into_atlas() -> None:
    pmr_path = COMPONENT_ROOT / "python/src/coherence/totality/pmr.py"
    assert all("atlas" not in module.casefold() for module in _imports(pmr_path))
    public_methods = {
        name
        for name, member in inspect.getmembers(PMRReferenceStore, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {
        "apply_consent",
        "correct",
        "delete",
        "receipt",
        "retain_reference",
        "retrieve",
        "revoke",
    }
    assert not {"promote", "admit_to_atlas", "inject_prior"} & public_methods
