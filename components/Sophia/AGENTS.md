# Sophia repository instructions

Before work, read:

- `docs/architecture/UVLM_TCC_ADR_001_SOPHIA_ADOPTION.md`;
- canonical ADR `pdxvoiceteacher/CoherenceLattice:docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md` (UVLM-TCC-ADR-001); and
- `README.md`.

Repository rules:

- Sophia implementation belongs only in `pdxvoiceteacher/Sophia`.
- Do not implement CoherenceLattice or Atlas behavior in Sophia.
- Do not import sibling repositories' private packages. Consume only versioned bridge artifacts or invoke approved sibling CLIs.
- Do not call Ollama or another model from Sophia, consume raw Ollama output, or generate the candidate Sophia audits.
- Do not claim hashes or schemas establish truth, or emit private chain-of-thought.
- Do not authorize memory write, canonization, publication, deployment, or final human action.
- Do not claim the complete live route is green without a three-repository acceptance run.
- One active work unit at a time.

Active work unit: `TRIADIC-GOVERNED-COGNITION-VERTICAL-SLICE-01` — WORKSTREAM B OF 4, SOPHIA INDEPENDENT CANDIDATE AUDIT.

Next documentation tranche: `UVLM-PUBLICATIONS ADOPTION OF UVLM-TCC-ADR-001`.
