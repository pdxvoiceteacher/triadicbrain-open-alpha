from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import csv
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "b278378f5add312aa8fb81a6cc1e0dc5fccc49aa"
MPL_SHA256 = "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
UNICODE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"
UCD_SHA256 = "24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08"
DEMO_SHA256 = "ed2ab14592d7c62a6e82658207680b56246f8c4126bbc0a8f94b3ae83d61202f"
LICENSE_EXPRESSION = "MPL-2.0 AND Unicode-3.0"
EXPECTED_RIGHTS_POSTURE = {
    "candidate_review_status": "PENDING_INDEPENDENT_REVIEW",
    "outbound_license_selected": True,
    "primary_license": "MPL-2.0",
    "public_release_eligible": False,
    "status": "HOLD",
    "third_party_licenses": ["Unicode-3.0"],
}
EXPECTED_DISTRIBUTION_POSTURE = {
    "distribution_status": "PUBLIC_DEVELOPMENT_NO_FORMAL_RELEASE",
    "formal_release_created": False,
    "package_published": False,
    "pages_enabled": False,
    "repository_visibility": "PUBLIC",
    "source_publicly_available": True,
}
EXPECTED_DEMO_STATUS = {
    "authority_effect": "NONE",
    "formal_release_created": False,
    "human_decision_submission": False,
    "inherited_atlas_invoked": False,
    "inherited_sophia_invoked": False,
    "live_model_invoked": False,
    "mode": "DETERMINISTIC_OFFLINE_FIXTURE",
    "package_published": False,
    "public_release_eligible": False,
    "repository_visibility": "PUBLIC",
    "schema_id": "uvlm.triadicbrain.demo_status.v2",
    "source_publicly_available": True,
}
PUBLIC_DEVELOPMENT_DOCUMENTS = (
    "PUBLIC_DEVELOPMENT_STATUS.md",
    "docs/evidence/rl02-repair01-main-closure.md",
    "docs/investor-demo-checklist.md",
    "docs/investor-demo.md",
    "docs/investor-one-page.md",
    "docs/operator-runbook.md",
    "docs/status-matrix.md",
    "docs/website-front-matter.md",
)
REVIEW_SECTIONS = (
    "What you are seeing",
    "What this proves",
    "What this does not prove",
    "Request and source",
    "Candidate and claims",
    "Sophia role",
    "Atlas role",
    "Human decision boundary",
    "Artifacts and checksums",
    "Next product milestone",
)
ACTION_PINS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
UNICODE_PATHS = (
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/tests/product/test_r3_actual_runtime_boundaries.py",
    "components/Sophia/python/src/sophia/triadic/totality_audit.py",
    "components/Sophia/tests/test_totality_audit.py",
    "components/uvlm-publications/python/src/atlas/triadic/totality_posture.py",
    "components/uvlm-publications/tests/test_atlas_totality_posture.py",
)
MPL_PATHS = (
    "components/CoherenceLattice/python/src/coherence/totality/atlas_contract.py",
    "components/CoherenceLattice/python/src/coherence/totality/canonical.py",
    "components/CoherenceLattice/python/src/coherence/totality/grounding.py",
    "components/CoherenceLattice/python/src/coherence/totality/seal.py",
    "components/CoherenceLattice/python/src/coherence/totality/ucm.py",
    "components/CoherenceLattice/python/src/coherence/totality/waveform.py",
)
sys.path.insert(0, str(ROOT / "src"))

from triadicbrain.cli import INVESTOR_STATUS_BLOCK, _investor_port, main as cli_main  # noqa: E402
from triadicbrain.contracts import ContractError, canonical_json, parse_canonical_object  # noqa: E402
from triadicbrain.demo import run_demo  # noqa: E402
from triadicbrain.doctor import doctor_report  # noqa: E402
from triadicbrain.serve import (  # noqa: E402
    DEMO_STATUS,
    DEMO_STATUS_BYTES,
    load_review,
    render_review,
    serve_review,
    validate_request_policy,
)


def _backend():
    spec = importlib.util.spec_from_file_location(
        "triadicbrain_test_backend", ROOT / "_triadicbrain_build_backend.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _docs_builder():
    spec = importlib.util.spec_from_file_location(
        "triadicbrain_test_docs_builder", ROOT / "tools" / "build_docs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _range_rows(payload: bytes, test_path: bool) -> tuple[str, ...]:
    text = payload.decode("utf-8")
    marker = (
        "EXPECTED_DEFAULT_IGNORABLE_CODE_POINT_RANGES = ("
        if test_path else "DEFAULT_IGNORABLE_CODE_POINT_RANGES = ("
    )
    start = text.index(marker)
    end = text.index("\n)", start)
    return tuple(
        line.strip() for line in text[start:end].splitlines()[1:]
        if re.fullmatch(r"\(0x[0-9A-F]+, 0x[0-9A-F]+\),", line.strip())
    )


class RootPackageTests(unittest.TestCase):
    def test_doctor_is_read_only_and_conservative(self) -> None:
        report = doctor_report()
        self.assertEqual(report["schema_id"], "uvlm.triadicbrain.doctor_report.v2")
        self.assertTrue(report["python"]["compatible"])
        self.assertEqual(report["distribution_posture"], EXPECTED_DISTRIBUTION_POSTURE)
        self.assertEqual(report["rights_posture"], EXPECTED_RIGHTS_POSTURE)
        self.assertFalse(report["optional_ollama"]["provider_contacted"])
        self.assertTrue(all(value is False for value in report["side_effects"].values()))

    def test_demo_is_byte_identical_and_human_controlling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "first", root / "second"
            result_a = run_demo(first)
            result_b = run_demo(second)
            self.assertEqual(result_a, result_b)
            self.assertEqual(result_a["artifact_set_sha256"], DEMO_SHA256)
            self.assertFalse(result_a["provider_invoked"])
            names_a = sorted(path.name for path in first.iterdir())
            names_b = sorted(path.name for path in second.iterdir())
            self.assertEqual(names_a, names_b)
            for name in names_a:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
            values = load_review(first.resolve())
            candidate = values["candidate_packet.json"]
            sophia = values["sophia_audit.json"]
            atlas = values["atlas_posture.json"]
            human = values["human_review.json"]
            self.assertTrue(candidate["candidate_is_not_final_answer"])
            self.assertFalse(sophia["candidate_rewritten"])
            self.assertFalse(atlas["canonization_performed"])
            self.assertEqual(human["decision"], "PENDING")
            self.assertFalse(human["decision_overwritten_by_automation"])
            page = render_review(values, "fixed-test-token")
            self.assertIn(b"Human decision boundary", page)

    def test_review_page_is_truthful_accessible_and_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root = Path(temporary) / "run"
            run_demo(run_root)
            page = render_review(load_review(run_root.resolve()), "fixed-test-token").decode("utf-8")
        status_tokens = (
            "MODE:</dt><dd>DETERMINISTIC OFFLINE FIXTURE",
            "LIVE MODEL INVOKED:</dt><dd>NO",
            "INHERITED SOPHIA INVOKED:</dt><dd>NO",
            "INHERITED ATLAS INVOKED:</dt><dd>NO",
            "HUMAN DECISION SUBMISSION:</dt><dd>NOT AVAILABLE IN THIS ROOT MODE",
            "REPOSITORY SOURCE:</dt><dd>PUBLIC DEVELOPMENT",
            "FORMAL RELEASE:</dt><dd>NONE",
        )
        offsets = [page.index(token) for token in status_tokens]
        self.assertEqual(offsets, sorted(offsets))
        section_offsets = [page.index(f">{title}</h2>") for title in REVIEW_SECTIONS]
        self.assertEqual(section_offsets, sorted(section_offsets))
        self.assertGreater(section_offsets[0], offsets[-1])
        self.assertIn("system-ui", page)
        self.assertIn("color:CanvasText", page)
        self.assertIn("frozen fixture identifiers", page)
        self.assertNotIn("<script", page.casefold())
        self.assertIsNone(re.search(r"(?:href|src)=[\"']https?://", page, re.IGNORECASE))

    def test_status_contract_is_exact_canonical_public_development_json(self) -> None:
        self.assertEqual(DEMO_STATUS, EXPECTED_DEMO_STATUS)
        self.assertEqual(DEMO_STATUS_BYTES, canonical_json(EXPECTED_DEMO_STATUS))
        self.assertEqual(parse_canonical_object(DEMO_STATUS_BYTES, "demo status"), EXPECTED_DEMO_STATUS)

    def test_investor_demo_runs_doctor_fixture_and_foreground_serve_contract(self) -> None:
        for include_browser in (False, True):
            with self.subTest(open_browser=include_browser), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "investor-run"
                argv = ["investor-demo", "--output", str(output), "--host", "127.0.0.1", "--port", "8765"]
                if include_browser:
                    argv.append("--open-browser")
                stream = io.StringIO()
                with mock.patch("triadicbrain.cli.doctor_report", wraps=doctor_report) as doctor, mock.patch(
                    "triadicbrain.cli.serve_review"
                ) as serve, redirect_stdout(stream):
                    self.assertEqual(cli_main(argv), 0)
                doctor.assert_called_once_with()
                serve.assert_called_once_with(
                    output.resolve(strict=True),
                    "127.0.0.1",
                    8765,
                    open_browser=include_browser,
                )
                self.assertEqual(
                    hashlib.sha256(canonical_json([
                        {
                            "bytes": path.stat().st_size,
                            "path": path.name,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for path in sorted(output.iterdir(), key=lambda item: item.name)
                    ])).hexdigest(),
                    DEMO_SHA256,
                )
                printed = stream.getvalue()
                self.assertTrue(printed.startswith(INVESTOR_STATUS_BLOCK))
                self.assertIn(DEMO_SHA256, printed)
                self.assertIn("http://127.0.0.1:8765/review", printed)

    def test_investor_demo_port_contract_is_bounded(self) -> None:
        self.assertEqual(_investor_port("1"), 1)
        self.assertEqual(_investor_port("65535"), 65535)
        for value in ("0", "65536", "not-a-port"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                _investor_port(value)

    def test_browser_opening_is_strictly_opt_in_after_server_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_root = Path(temporary) / "run"
            run_demo(run_root)
            with mock.patch("triadicbrain.serve._ReviewServer.serve_forever"), mock.patch(
                "triadicbrain.serve.webbrowser.open"
            ) as browser:
                serve_review(run_root.resolve(), "127.0.0.1", 0, open_browser=False)
                browser.assert_not_called()
                serve_review(run_root.resolve(), "127.0.0.1", 0, open_browser=True)
                browser.assert_called_once()
                opened_url = browser.call_args.args[0]
                self.assertRegex(opened_url, r"^http://127\.0\.0\.1:[1-9][0-9]*/review$")

    def test_demo_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ContractError):
                run_demo(Path(temporary).resolve())

    def test_http_policy_rejects_host_origin_and_csrf(self) -> None:
        valid = dict(
            method="GET",
            host_header="127.0.0.1:8765",
            origin=None,
            fetch_site="same-origin",
            client_host="127.0.0.1",
            csrf_token=None,
            expected_csrf_token="expected",
        )
        validate_request_policy(**valid)
        for changed in (
            {"host_header": "example.test"},
            {"origin": "http://example.test"},
            {"client_host": "192.0.2.10"},
            {"fetch_site": "cross-site"},
        ):
            hostile = dict(valid)
            hostile.update(changed)
            with self.assertRaises(ContractError):
                validate_request_policy(**hostile)
        post = dict(valid, method="POST", csrf_token="wrong")
        with self.assertRaises(ContractError):
            validate_request_policy(**post)
        validate_request_policy(**dict(valid, method="POST", csrf_token="expected"))

    def test_rl02_license_notice_rights_and_identity_posture(self) -> None:
        self.assertEqual(hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest(), MPL_SHA256)
        self.assertEqual(
            hashlib.sha256((ROOT / "licenses" / "Unicode-3.0.txt").read_bytes()).hexdigest(),
            UNICODE_SHA256,
        )
        self.assertFalse((ROOT / "LICENSE_NOT_YET_SELECTED.md").exists())
        scope = (ROOT / "LICENSE_SCOPE.md").read_text(encoding="utf-8")
        third_party = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("MPL-2.0", scope)
        self.assertIn("Unicode License V3", scope)
        self.assertIn(UCD_SHA256, third_party)
        self.assertIn(UNICODE_SHA256, third_party)
        self.assertLess(len((ROOT / "components" / "CoherenceLattice" / "README.md").read_bytes()), 6000)
        with (ROOT / "RIGHTS_EVIDENCE_MATRIX.csv").open(encoding="utf-8", newline="") as handle:
            rights = list(csv.DictReader(handle))
        self.assertEqual(len(rights), 166)
        self.assertEqual(sum(row["record_status"] == "ACTIVE" for row in rights), 164)
        self.assertEqual(sum(row["record_status"] == "RETIRED" for row in rights), 2)
        self.assertTrue(all(row["public_status"] == "HOLD" for row in rights))
        self.assertTrue(all(row["public_release_eligible"] == "false" for row in rights))
        self.assertFalse(any(row["public_status"] == "CLEAR" for row in rights))

    def test_rl02_unicode_ranges_and_mpl_headers_are_preserved(self) -> None:
        provenance_tokens = (
            "Unicode provenance: UCD 17.0.0 DerivedCoreProperties.txt",
            UCD_SHA256,
            "Unicode License V3",
        )
        for relative in UNICODE_PATHS:
            current = (ROOT / relative).read_bytes()
            baseline = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{relative}"]
            )
            self.assertTrue(all(token in current.decode("utf-8") for token in provenance_tokens))
            self.assertEqual(_range_rows(current, "/tests/" in relative), _range_rows(baseline, "/tests/" in relative))
            self.assertEqual(len(_range_rows(current, "/tests/" in relative)), 17)
        header = (
            b"# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors\n"
            b"# SPDX-License-Identifier: MPL-2.0\n"
        )
        for relative in MPL_PATHS:
            self.assertTrue((ROOT / relative).read_bytes().startswith(header), relative)

    def test_rl02_action_pins_and_disclosures_are_bounded(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "private-alpha-ci.yml").read_text(encoding="utf-8")
        matches = re.findall(r"(?m)^\s*uses:\s*([^@\s]+)@([0-9a-f]{40})(?:\s+#.*)?$", workflow)
        self.assertEqual(dict(matches), ACTION_PINS)
        self.assertEqual(len(matches), 3)
        disclosure = (ROOT / "AI_ASSISTANCE_DISCLOSURE.md").read_text(encoding="utf-8")
        contributors = (ROOT / "CONTRIBUTORS.md").read_text(encoding="utf-8")
        self.assertIn("does not claim", disclosure)
        self.assertIn("not legal contributors", contributors)
        self.assertIn("oa01@local.invalid", contributors)

    def test_rl02_repair01_active_license_posture_is_consistent(self) -> None:
        active_posture_paths = (
            "AGENTS.md",
            "README.md",
            "LICENSE_SCOPE.md",
            "NOTICE",
            "THIRD_PARTY_NOTICES.md",
            "DEPENDENCIES.md",
            "AI_ASSISTANCE_DISCLOSURE.md",
            "CONTRIBUTORS.md",
            "docs/getting-started.md",
            "docs/roadmap.md",
            "docs/safety-and-boundaries.md",
            "docs/whitepaper/index.md",
            "PUBLIC_CLAIM_LEDGER.csv",
            "PUBLIC_PROJECTION_MANIFEST.json",
            "pyproject.toml",
            "_triadicbrain_build_backend.py",
            "src/triadicbrain/doctor.py",
            "tools/run_private_alpha_ci.py",
        )
        forbidden = (
            "LICENSE_NOT_YET_SELECTED.md",
            "select an outbound license",
            "Selection of an outbound license",
            "outbound-license selection",
            "0.1.0a0.dev2",
            "v0.1.0-alpha.0-private.3-rc1",
            "License :: OSI Approved :: Mozilla Public License 2.0",
        )
        for relative in active_posture_paths:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for fragment in forbidden:
                if (
                    relative == "tools/run_private_alpha_ci.py"
                    and fragment == "License :: OSI Approved :: Mozilla Public License 2.0"
                ):
                    continue
                self.assertNotIn(fragment, text, f"{relative}: {fragment}")

        manifest = json.loads((ROOT / "PUBLIC_PROJECTION_MANIFEST.json").read_bytes())
        self.assertEqual(manifest["candidate_label"], "v0.1.0-alpha.0-public-dev.1-rc1")
        self.assertEqual(manifest["python_distribution_version"], "0.1.0a0.dev4")
        self.assertEqual(manifest["outbound_license"], LICENSE_EXPRESSION)
        self.assertEqual(manifest["primary_license"], "MPL-2.0")
        self.assertEqual(manifest["third_party_licenses"], ["Unicode-3.0"])
        self.assertTrue(manifest["outbound_license_selected"])
        self.assertEqual(manifest["repository_visibility"], "PUBLIC")
        self.assertTrue(manifest["source_publicly_available"])
        self.assertFalse(manifest["formal_release_created"])
        self.assertFalse(manifest["package_published"])
        self.assertFalse(manifest["pages_enabled"])
        self.assertEqual(manifest["distribution_status"], "PUBLIC_DEVELOPMENT_NO_FORMAL_RELEASE")
        self.assertTrue(manifest["remote_push"])
        self.assertEqual(manifest["main_commit_at_phase_start"], "82f819f4f5491f5daffb510c0c6ab6a7328dd6e6")
        self.assertEqual(manifest["main_tree_at_phase_start"], "a612d2f58a8e8f2a53e06ec3a61ae1675068870c")
        self.assertEqual(manifest["post_merge_ci_run"], 33423783473)
        self.assertFalse(manifest["public_release_eligible"])
        self.assertEqual(manifest["rights_active_count"], 164)
        self.assertEqual(manifest["rights_hold_count"], 166)
        self.assertEqual(manifest["rights_clear_count"], 0)

        with (ROOT / "PUBLIC_CLAIM_LEDGER.csv").open(encoding="utf-8", newline="") as handle:
            claims = {row["claim_id"]: row for row in csv.DictReader(handle)}
        release_claim = claims["CLM-015"]
        self.assertEqual(release_claim["status"], "DEFERRED")
        self.assertEqual(release_claim["public_status"], "HOLD")
        self.assertNotIn("LICENSE_NOT_YET_SELECTED.md", release_claim["evidence_reference"])
        self.assertIn("166 rights rows remain HOLD", release_claim["limitation"])
        self.assertIn("formal", release_claim["limitation"].casefold())
        self.assertIn("public", release_claim["limitation"].casefold())
        for token in ("RIGHTS_EVIDENCE_MATRIX.csv", "LICENSE", "LICENSE_SCOPE.md", "THIRD_PARTY_NOTICES.md"):
            self.assertIn(token, release_claim["evidence_reference"])

        for name, path_field in (
            ("EXCLUDED_PATHS.csv", "source_path"),
            ("PROJECTION_LINEAGE.csv", "projected_path"),
            ("RIGHTS_EVIDENCE_MATRIX.csv", "path"),
        ):
            with (ROOT / name).open(encoding="utf-8", newline="") as handle:
                matches = [
                    row for row in csv.DictReader(handle)
                    if row[path_field] == "LICENSE_NOT_YET_SELECTED.md"
                ]
            self.assertEqual(len(matches), 1, name)
            self.assertEqual(matches[0]["record_status"], "RETIRED", name)

    def test_canonical_parser_rejects_duplicates_and_noncanonical_json(self) -> None:
        with self.assertRaises(ContractError):
            parse_canonical_object(b'{"a":1,"a":2}\n', "duplicate")
        with self.assertRaises(ContractError):
            parse_canonical_object(b'{"b":2, "a":1}\n', "noncanonical")


class BuildBackendTests(unittest.TestCase):
    def test_wheel_and_sdist_double_builds_are_identical(self) -> None:
        backend = _backend()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel_a, wheel_b = root / "wheel-a", root / "wheel-b"
            sdist_a, sdist_b = root / "sdist-a", root / "sdist-b"
            wa = wheel_a / backend.build_wheel(wheel_a)
            wb = wheel_b / backend.build_wheel(wheel_b)
            sa = sdist_a / backend.build_sdist(sdist_a)
            sb = sdist_b / backend.build_sdist(sdist_b)
            self.assertEqual(wa.read_bytes(), wb.read_bytes())
            self.assertEqual(sa.read_bytes(), sb.read_bytes())
            with zipfile.ZipFile(wa) as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                roots = {name.split("/", 1)[0] for name in names if ".dist-info/" not in name}
                self.assertEqual(roots, {"atlas", "coherence", "sophia", "triadicbrain"})
                self.assertIn("coherence/totality/cli.py", names)
                self.assertIn("sophia/triadic/totality_audit.py", names)
                self.assertIn("atlas/triadic/totality_posture.py", names)
                self.assertFalse(any(name.startswith(("components/", "integration/", "tests/")) for name in names))
                self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist()))
                metadata = archive.read(f"{backend.DIST_INFO}/METADATA")
                self.assertNotIn(b"Requires-Dist:", metadata)
                self.assertIn(b"Metadata-Version: 2.4\n", metadata)
                self.assertIn(b"Version: 0.1.0a0.dev4\n", metadata)
                self.assertIn(b"Summary: Public development alpha", metadata)
                self.assertIn(f"License-Expression: {LICENSE_EXPRESSION}\n".encode(), metadata)
                self.assertNotIn(b"Classifier: License :: OSI Approved :: Mozilla Public License 2.0", metadata)
                self.assertIn(b"License-File: LICENSE\n", metadata)
                self.assertIn(b"License-File: licenses/Unicode-3.0.txt\n", metadata)
                mpl_member = f"{backend.DIST_INFO}/licenses/LICENSE"
                unicode_member = f"{backend.DIST_INFO}/licenses/licenses/Unicode-3.0.txt"
                self.assertIn(mpl_member, names)
                self.assertIn(unicode_member, names)
                self.assertEqual(hashlib.sha256(archive.read(mpl_member)).hexdigest(), MPL_SHA256)
                self.assertEqual(hashlib.sha256(archive.read(unicode_member)).hexdigest(), UNICODE_SHA256)
                record = archive.read(f"{backend.DIST_INFO}/RECORD").decode("utf-8")
                self.assertEqual(len(record.splitlines()), len(names))
            with tarfile.open(sa, "r:gz") as archive:
                names = archive.getnames()
                self.assertEqual(names, sorted(names))
                self.assertIn(f"{backend.SDIST_ROOT}/pyproject.toml", names)
                self.assertIn(f"{backend.SDIST_ROOT}/tests/test_root_package.py", names)
                for relative in (
                    "LICENSE", "licenses/Unicode-3.0.txt", "LICENSE_SCOPE.md", "NOTICE",
                    "THIRD_PARTY_NOTICES.md", "AI_ASSISTANCE_DISCLOSURE.md", "CONTRIBUTORS.md",
                    "DEPENDENCIES.md",
                    *PUBLIC_DEVELOPMENT_DOCUMENTS,
                ):
                    self.assertIn(f"{backend.SDIST_ROOT}/{relative}", names)
                    if relative in PUBLIC_DEVELOPMENT_DOCUMENTS:
                        archived = archive.extractfile(f"{backend.SDIST_ROOT}/{relative}")
                        self.assertIsNotNone(archived)
                        self.assertEqual(archived.read(), (ROOT / relative).read_bytes())
                self.assertIn(
                    f"{backend.SDIST_ROOT}/components/Sophia/python/src/sophia/triadic/totality_audit.py",
                    names,
                )
                pkg_info = archive.extractfile(f"{backend.SDIST_ROOT}/PKG-INFO")
                self.assertIsNotNone(pkg_info)
                metadata = pkg_info.read()
                self.assertIn(b"Metadata-Version: 2.4\n", metadata)
                self.assertIn(b"Version: 0.1.0a0.dev4\n", metadata)
                self.assertIn(f"License-Expression: {LICENSE_EXPRESSION}\n".encode(), metadata)
                self.assertNotIn(b"Classifier: License :: OSI Approved :: Mozilla Public License 2.0", metadata)
            self.assertEqual(hashlib.sha256(wa.read_bytes()).hexdigest(), hashlib.sha256(wb.read_bytes()).hexdigest())

    def test_pyproject_has_no_build_or_runtime_dependencies(self) -> None:
        import tomllib

        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["build-system"]["requires"], [])
        self.assertEqual(project["project"]["dependencies"], [])
        self.assertEqual(project["project"]["version"], "0.1.0a0.dev4")
        self.assertIn("Public development alpha", project["project"]["description"])
        self.assertEqual(project["project"]["license"], LICENSE_EXPRESSION)
        self.assertEqual(project["project"]["license-files"], ["LICENSE", "licenses/Unicode-3.0.txt"])
        self.assertNotIn(
            "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            project["project"]["classifiers"],
        )
        self.assertEqual(project["project"]["scripts"]["triadicbrain"], "triadicbrain.cli:main")
        self.assertEqual(
            project["tool"]["triadicbrain"]["distribution-status"],
            "PUBLIC_DEVELOPMENT_NO_FORMAL_RELEASE",
        )
        self.assertEqual(project["tool"]["triadicbrain"]["repository-visibility"], "PUBLIC")
        self.assertTrue(project["tool"]["triadicbrain"]["source-publicly-available"])
        self.assertFalse(project["tool"]["triadicbrain"]["formal-release-created"])
        self.assertFalse(project["tool"]["triadicbrain"]["package-published"])
        self.assertFalse(project["tool"]["triadicbrain"]["pages-enabled"])

    def test_documentation_build_inventory_is_exact_and_links_are_local(self) -> None:
        builder = _docs_builder()
        self.assertEqual(len(builder.DOCS), 18)
        self.assertEqual(len(builder.DOCS), len(set(builder.DOCS)))
        self.assertEqual(set(PUBLIC_DEVELOPMENT_DOCUMENTS).issubset(builder.DOCS), True)
        self.assertEqual(builder.internal_link_errors(ROOT), [])


if __name__ == "__main__":
    unittest.main()
