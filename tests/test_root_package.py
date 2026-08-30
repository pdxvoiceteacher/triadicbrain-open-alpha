from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from triadicbrain.contracts import ContractError, parse_canonical_object  # noqa: E402
from triadicbrain.demo import run_demo  # noqa: E402
from triadicbrain.doctor import doctor_report  # noqa: E402
from triadicbrain.serve import load_review, render_review, validate_request_policy  # noqa: E402


def _backend():
    spec = importlib.util.spec_from_file_location(
        "triadicbrain_test_backend", ROOT / "_triadicbrain_build_backend.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RootPackageTests(unittest.TestCase):
    def test_doctor_is_read_only_and_conservative(self) -> None:
        report = doctor_report()
        self.assertEqual(report["schema_id"], "uvlm.triadicbrain.doctor_report.v1")
        self.assertTrue(report["python"]["compatible"])
        self.assertFalse(report["rights_posture"]["public_release_eligible"])
        self.assertFalse(report["optional_ollama"]["provider_contacted"])
        self.assertTrue(all(value is False for value in report["side_effects"].values()))

    def test_demo_is_byte_identical_and_human_controlling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "first", root / "second"
            result_a = run_demo(first)
            result_b = run_demo(second)
            self.assertEqual(result_a, result_b)
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
            self.assertIn(b"Human decision", render_review(values, "fixed-test-token"))

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
                record = archive.read(f"{backend.DIST_INFO}/RECORD").decode("utf-8")
                self.assertEqual(len(record.splitlines()), len(names))
            with tarfile.open(sa, "r:gz") as archive:
                names = archive.getnames()
                self.assertEqual(names, sorted(names))
                self.assertIn(f"{backend.SDIST_ROOT}/pyproject.toml", names)
                self.assertIn(f"{backend.SDIST_ROOT}/tests/test_root_package.py", names)
                self.assertIn(
                    f"{backend.SDIST_ROOT}/components/Sophia/python/src/sophia/triadic/totality_audit.py",
                    names,
                )
            self.assertEqual(hashlib.sha256(wa.read_bytes()).hexdigest(), hashlib.sha256(wb.read_bytes()).hexdigest())

    def test_pyproject_has_no_build_or_runtime_dependencies(self) -> None:
        import tomllib

        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["build-system"]["requires"], [])
        self.assertEqual(project["project"]["dependencies"], [])
        self.assertEqual(project["project"]["scripts"]["triadicbrain"], "triadicbrain.cli:main")


if __name__ == "__main__":
    unittest.main()
