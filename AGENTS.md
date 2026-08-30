# TriadicGate repository instructions

TriadicGate becomes the canonical cognition-engine integration repository only after
this PR is human-reviewed and merged. Nested component instructions remain binding,
and a task may modify only components explicitly named in scope.

## Source precedence

Apply, in descending order: current root and nested `AGENTS.md`; current executable
contracts and tests; current authoritative acceptance ledger; current cross-component
contract documentation; accepted phase overlays and handoffs; historical reports and
narrative summaries. A conflict produces **HOLD**. Never select the source that sounds
most confident.

## Boundaries

- Sonya / ingress surfaces: `protect_and_route`.
- CoherenceLattice: `canonicalize_and_bind_evidence`.
- Sophia: `audit`; Sophia cannot generate or rewrite candidates.
- Atlas: `orient`; Atlas cannot write memory, canonize, publish, deploy, or release.
- PMR, only after separate authorization: `retain_governed_provenance`; retention is
  separately consented and revocable.
- Candidate is not answer. Receipt/hash is identity or process evidence, not truth.
- Capability is not authorization. Raw provider output cannot bypass Sonya.
- No skipped test is green. Missing evidence never grants permission.
- E05 remains red and controlled by the imported authoritative ledger.
- CivicProof remains separate from the cognition-engine core.
