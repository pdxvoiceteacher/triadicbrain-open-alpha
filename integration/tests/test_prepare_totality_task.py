from __future__ import annotations

import importlib.util
import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "prepare_totality_task",
    ROOT / "integration" / "tools" / "prepare_totality_task.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareTotalityTaskTests(unittest.TestCase):
    def test_prepares_canonical_host_path_free_structural_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source.write_text("Candidate stage.\n\nIndependent review stage.\n", encoding="utf-8")
            output = root / "prepared"
            manifest = MODULE.prepare(
                source_path=source,
                output_dir=output,
                request_id="REQ-TEST-001",
                run_id="RUN-TEST-001",
                logical_time="2026-08-22T00:00:00Z",
                user_input="State the ordered stages.",
                claims=["Candidate stage.", "Independent review stage."],
                uncertainty=0.2,
                source_label="source.md",
                aha_mode="structural",
                task_consent=True,
                privacy_policy_satisfied=True,
                privacy_basis="operator_attests_local_source_no_external_egress",
            )
            self.assertEqual(manifest["aha_mode"], "STRUCTURAL")
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"source.bin", "request.json", "captured_semantic.json", "aha_case.json", "input_manifest.json"},
            )
            for path in output.glob("*.json"):
                raw = path.read_bytes()
                self.assertTrue(raw.endswith(b"\n"))
                self.assertEqual(
                    raw,
                    (json.dumps(json.loads(raw), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                )
                self.assertNotIn(str(root).encode(), raw)
            request = json.loads((output / "request.json").read_bytes())
            self.assertEqual(request["grounding"][0]["bundle_manifest_path"], "grounding/manifest.json")
            self.assertEqual(request["grounding"][0]["source_kind"], "grounding_bundle")
            capture = json.loads((output / "captured_semantic.json").read_bytes())
            for claim in capture["claims"]:
                self.assertEqual(
                    capture["answer"][claim["answer_start"] : claim["answer_end"]],
                    claim["text"],
                )
                self.assertEqual(claim["candidate_evidence_references"], [])
            aha = json.loads((output / "aha_case.json").read_bytes())
            self.assertEqual(len(aha["donors"]), 2)
            self.assertTrue(all(mapping["disanalogies"] for mapping in aha["mappings"]))

    def test_existing_output_and_default_ignorable_source_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source.write_text("safe source", encoding="utf-8")
            output = root / "already"
            output.mkdir()
            with self.assertRaisesRegex(MODULE.PreparationError, "OUTPUT_DIRECTORY_ALREADY_EXISTS"):
                MODULE.prepare(
                    source_path=source,
                    output_dir=output,
                    request_id="REQ-TEST-002",
                    run_id="RUN-TEST-002",
                    logical_time="T0",
                    user_input="task",
                    claims=["safe source"],
                    uncertainty=0.1,
                    source_label="source.md",
                    aha_mode="unavailable",
                    task_consent=True,
                    privacy_policy_satisfied=True,
                    privacy_basis="operator_attests_local_source_no_external_egress",
                )
            unsafe = root / "unsafe.md"
            unsafe.write_text("unsafe\u200bsource", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.PreparationError, "INVALID_UNICODE_TEXT"):
                MODULE.prepare(
                    source_path=unsafe,
                    output_dir=root / "new",
                    request_id="REQ-TEST-003",
                    run_id="RUN-TEST-003",
                    logical_time="T0",
                    user_input="task",
                    claims=["unsafe source"],
                    uncertainty=0.1,
                    source_label="unsafe.md",
                    aha_mode="unavailable",
                    task_consent=True,
                    privacy_policy_satisfied=True,
                    privacy_basis="operator_attests_local_source_no_external_egress",
                )

    def test_consent_and_privacy_are_explicit_and_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source.write_text("Exact local source.", encoding="utf-8")
            output = root / "prepared"
            MODULE.prepare(
                source_path=source,
                output_dir=output,
                request_id="REQ-TEST-004",
                run_id="RUN-TEST-004",
                logical_time="T0",
                user_input="State the source.",
                claims=["Exact local source."],
                uncertainty=0.1,
                source_label="source.md",
                aha_mode="unavailable",
                task_consent=False,
                privacy_policy_satisfied=False,
                privacy_basis="operator_did_not_attest_privacy_clearance",
            )
            request = json.loads((output / "request.json").read_bytes())
            manifest = json.loads((output / "input_manifest.json").read_bytes())
            self.assertIs(request["task_consent"], False)
            self.assertIs(request["meta"]["privacy_policy_satisfied"], False)
            self.assertEqual(
                request["grounding"][0]["bundle_manifest_sha256"],
                manifest["grounding_manifest_sha256"],
            )

            with self.assertRaisesRegex(
                MODULE.PreparationError,
                "CONSENT_AND_PRIVACY_ASSERTIONS_MUST_BE_EXPLICIT_BOOLEANS",
            ):
                MODULE.prepare(
                    source_path=source,
                    output_dir=root / "invalid",
                    request_id="REQ-TEST-005",
                    run_id="RUN-TEST-005",
                    logical_time="T0",
                    user_input="State the source.",
                    claims=["Exact local source."],
                    uncertainty=0.1,
                    source_label="source.md",
                    aha_mode="unavailable",
                    task_consent="yes",  # type: ignore[arg-type]
                    privacy_policy_satisfied=True,
                    privacy_basis="operator_attests_local_source_no_external_egress",
                )

    def test_producer_rejects_consumer_limit_violations_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source.write_text("Exact local source.", encoding="utf-8")
            base = {
                "source_path": source,
                "request_id": "REQ-LIMITS",
                "run_id": "RUN-LIMITS",
                "logical_time": "T0",
                "user_input": "State the source.",
                "claims": ["Exact local source."],
                "uncertainty": 0.1,
                "source_label": "source.md",
                "aha_mode": "unavailable",
                "task_consent": True,
                "privacy_policy_satisfied": True,
                "privacy_basis": "local_attestation",
            }
            cases = (
                ("logical_time", "T" * (MODULE.MAX_LOGICAL_TIME_CHARS + 1)),
                ("user_input", "u" * (MODULE.MAX_USER_INPUT_CHARS + 1)),
                ("user_input", "   "),
                ("source_label", "s" * (MODULE.MAX_SOURCE_LABEL_CHARS + 1)),
                ("privacy_basis", "p" * (MODULE.MAX_PRIVACY_BASIS_CHARS + 1)),
                ("claims", ["c"] * (MODULE.MAX_CAPTURE_CLAIMS + 1)),
                ("claims", [" "]),
                ("claims", ["c" * (MODULE.MAX_ANSWER_CHARS + 1)]),
            )
            for ordinal, (field, value) in enumerate(cases):
                output = root / f"rejected-{ordinal}"
                arguments = {**base, field: value, "output_dir": output}
                with self.subTest(field=field, ordinal=ordinal):
                    with self.assertRaises(MODULE.PreparationError):
                        MODULE.prepare(**arguments)
                    self.assertFalse(output.exists())

            oversized = root / "oversized.md"
            oversized.write_bytes(b"x" * (MODULE.MAX_SOURCE_BYTES + 1))
            output = root / "rejected-source"
            with self.assertRaisesRegex(MODULE.PreparationError, "SOURCE_SIZE_LIMIT_EXCEEDED"):
                MODULE.prepare(**{**base, "source_path": oversized, "output_dir": output})
            self.assertFalse(output.exists())

            growing = root / "growing.md"
            growing.write_bytes(b"small")
            growing_output = root / "rejected-growing-source"
            original_open = Path.open
            growth_applied = False

            def grow_before_read(path: Path, *args: object, **kwargs: object):
                nonlocal growth_applied
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == growing and mode == "rb" and not growth_applied:
                    growth_applied = True
                    with builtins.open(growing, "ab") as stream:
                        stream.write(b"x" * (MODULE.MAX_SOURCE_BYTES + 1))
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", grow_before_read):
                with self.assertRaisesRegex(MODULE.PreparationError, "SOURCE_SIZE_LIMIT_EXCEEDED"):
                    MODULE.prepare(
                        **{**base, "source_path": growing, "output_dir": growing_output}
                    )
            self.assertFalse(growing_output.exists())

    def test_exact_candidate_evidence_references_are_aligned_and_claim_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.md"
            source_raw = "Exact local source.\n".encode("utf-8")
            source.write_bytes(source_raw)
            claim = "Exact local source."
            reference = {
                "source_sha256": MODULE._sha(source_raw),
                "segment_id": "SEG-0001",
                "segment_sha256": MODULE._sha(claim.encode("utf-8")),
                "source_span": {
                    "byte_start": 0,
                    "byte_end": len(claim.encode("utf-8")),
                    "char_start": 0,
                    "char_end": len(claim),
                },
                "exact_excerpt_sha256": MODULE._sha(claim.encode("utf-8")),
                "claim_text_sha256": MODULE._sha(claim.encode("utf-8")),
                "candidate_relation": "SUPPORTS",
            }
            output = root / "prepared"
            MODULE.prepare(
                source_path=source,
                output_dir=output,
                request_id="REQ-EVIDENCE-001",
                run_id="RUN-EVIDENCE-001",
                logical_time="T0",
                user_input="State the source.",
                claims=[claim],
                uncertainty=0.1,
                source_label="source.md",
                aha_mode="unavailable",
                task_consent=True,
                privacy_policy_satisfied=True,
                privacy_basis="local_attestation",
                claim_evidence_references=[[reference]],
            )
            capture = json.loads((output / "captured_semantic.json").read_bytes())
            self.assertEqual(
                capture["claims"][0]["candidate_evidence_references"], [reference]
            )

            with self.assertRaisesRegex(
                MODULE.PreparationError,
                "CLAIM_EVIDENCE_REFERENCE_ALIGNMENT_INVALID",
            ):
                MODULE.prepare(
                    source_path=source,
                    output_dir=root / "misaligned",
                    request_id="REQ-EVIDENCE-002",
                    run_id="RUN-EVIDENCE-002",
                    logical_time="T0",
                    user_input="State the source.",
                    claims=[claim],
                    uncertainty=0.1,
                    source_label="source.md",
                    aha_mode="unavailable",
                    task_consent=True,
                    privacy_policy_satisfied=True,
                    privacy_basis="local_attestation",
                    claim_evidence_references=[],
                )
            copied = dict(reference)
            copied["claim_text_sha256"] = "0" * 64
            with self.assertRaisesRegex(
                MODULE.PreparationError,
                "EVIDENCE_CLAIM_TEXT_BINDING_MISMATCH",
            ):
                MODULE.prepare(
                    source_path=source,
                    output_dir=root / "copied",
                    request_id="REQ-EVIDENCE-003",
                    run_id="RUN-EVIDENCE-003",
                    logical_time="T0",
                    user_input="State the source.",
                    claims=[claim],
                    uncertainty=0.1,
                    source_label="source.md",
                    aha_mode="unavailable",
                    task_consent=True,
                    privacy_policy_satisfied=True,
                    privacy_basis="local_attestation",
                    claim_evidence_references=[[copied]],
                )


if __name__ == "__main__":
    unittest.main()
