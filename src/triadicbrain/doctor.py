"""Read-only local readiness report for the private alpha."""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import sys
from typing import Any

from . import __version__
from .contracts import SIDE_EFFECT_DENIALS, fixture_bytes, sha256_bytes


def doctor_report() -> dict[str, Any]:
    try:
        installed_version = importlib.metadata.version("triadicbrain")
        source = "installed_distribution_metadata"
    except importlib.metadata.PackageNotFoundError:
        installed_version = __version__
        source = "source_tree_fallback"
    compatible = sys.version_info >= (3, 12) and sys.version_info < (4, 0)
    return {
        "authority_effect": "NONE",
        "installed_package": {
            "name": "triadicbrain",
            "version": installed_version,
            "version_source": source,
        },
        "loopback_binding": {
            "default_hosts": ["127.0.0.1", "::1"],
            "readiness": "SUPPORTED_NOT_BOUND_BY_DOCTOR",
        },
        "network_posture": "DENY_EXCEPT_EXPLICIT_FOREGROUND_LOOPBACK_SERVE",
        "optional_ollama": {
            "executable_name_visible_on_path": shutil.which("ollama") is not None,
            "installed_model_discovery": "NOT_PERFORMED_REQUIRES_SEPARATE_HUMAN_PROVIDER_AUTHORIZATION",
            "provider_contacted": False,
        },
        "package_resource_integrity": {
            "fixture_bytes": len(fixture_bytes()),
            "fixture_sha256": sha256_bytes(fixture_bytes()),
            "status": "PASS_CANONICAL_RESOURCE_READABLE",
        },
        "python": {
            "compatible": compatible,
            "implementation": platform.python_implementation(),
            "required": ">=3.12,<4",
            "version": platform.python_version(),
        },
        "rights_posture": {
            "outbound_license_selected": False,
            "public_release_eligible": False,
            "status": "HOLD",
        },
        "schema_id": "uvlm.triadicbrain.doctor_report.v1",
        "side_effects": dict(SIDE_EFFECT_DENIALS),
    }

