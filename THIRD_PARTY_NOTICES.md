# Third-party notices

## Unicode Character Database material

Six source and test files contain a frozen range table derived from the Unicode
UCD 17.0.0 `DerivedCoreProperties.txt` property
`Default_Ignorable_Code_Point`:

- `components/CoherenceLattice/python/src/coherence/totality/canonical.py`
- `components/CoherenceLattice/python/tests/product/test_r3_actual_runtime_boundaries.py`
- `components/Sophia/python/src/sophia/triadic/totality_audit.py`
- `components/Sophia/tests/test_totality_audit.py`
- `components/uvlm-publications/python/src/atlas/triadic/totality_posture.py`
- `components/uvlm-publications/tests/test_atlas_totality_posture.py`

Official source identity:

```text
Unicode UCD version: 17.0.0
Source: DerivedCoreProperties.txt / Default_Ignorable_Code_Point
Source SHA-256: 24c7fed1195c482faaefd5c1e7eb821c5ee1fb6de07ecdbaa64b56a99da22c08
License: Unicode License V3
License SHA-256: e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96
Local license path: licenses/Unicode-3.0.txt
```

The Unicode-derived ranges are not relicensed under MPL-2.0. The range values
are unchanged by RL-02; only a provenance comment is added to each named file.

## Build, test, and component dependency boundary

The root `triadicbrain` distribution declares no runtime dependencies and its
wheel does not bundle installed CI packages. Component dependency declarations
and the pinned CI toolchain are inventoried in [DEPENDENCIES.md](DEPENDENCIES.md).
Those packages and GitHub-owned actions retain their own terms. Availability or
use during testing is not a project ownership claim.

This inventory is evidence for independent review, not a claim of exhaustive
legal compliance or public-release readiness.
