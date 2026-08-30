# Repository instructions

## Required reading

- `README.md`
- `docs/architecture/UVLM_TCC_ADR_001_ATLAS_PUBLISHER_ADOPTION.md`
- Canonical reference: `pdxvoiceteacher/CoherenceLattice`, `docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md`; external binding is deferred to the three-repository consistency gate.

## Authority boundaries

- Atlas/Publisher behavior belongs only in `pdxvoiceteacher/uvlm-publications`.
- Do not implement CoherenceLattice or Sophia behavior here, and do not import sibling private packages.
- Do not call a model or accept raw model output.
- A favorable posture requires a valid Sophia disposition; missing or altered Sophia evidence fails closed.
- Do not write memory automatically or invoke persistence during documentation validation.
- Do not mutate publication, DOI, catalog, graph, or Crossref state without separate human authorization.
- Do not treat hashes or schemas as truth; do not emit private chain-of-thought.
- Do not claim the live route is green without a three-repository run.
- One active work unit at a time.

## Active work unit

`UVLM-TCC-ADR-001-ATLAS-PUBLISHER-ADOPTION-00`

## Next gate

`THREE-REPOSITORY-ARCHITECTURE-CONSISTENCY-VALIDATION-00`
