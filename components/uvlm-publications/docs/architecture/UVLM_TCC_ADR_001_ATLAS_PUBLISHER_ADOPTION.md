# UVLM-TCC-ADR-001 Atlas/Publisher adoption

**Status:** `accepted_architecture_adoption` / `implementation_in_progress`

```yaml
canonical_reference:
  document_id: UVLM-TCC-ADR-001
  owner_repository: pdxvoiceteacher/CoherenceLattice
  canonical_path: docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md
  source_commit: null
  document_sha256: null
  verification_status: deferred_to_three_repository_consistency_gate
  adoption_basis: human_authorized_architecture_capsule
  authority_effect: none
```

Atlas/Publisher is the bounded prior, retention-posture, publication-posture, lifecycle, and human-presentation layer of the UVLM Triadic Cognition Core.

Atlas posture does not itself perform a memory write. Atlas posture does not canonize. Atlas posture does not publish. Atlas posture does not mutate DOI, Crossref, publication, catalog, or knowledge-graph state.

The reference is human-authorized for this local adoption. External commit/hash verification is deliberately deferred to `THREE-REPOSITORY-ARCHITECTURE-CONSISTENCY-VALIDATION-00`; the null values above are not verification claims and have no authority effect.

## Normative architecture capsule

Model-result flow:

```text
approved local model → Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human → PMR only when separately authorized
```

Model invocation: `Sonya → approved local model backend → Sonya`.

Sonya calls the model and raw output returns to Sonya; Atlas does not consume raw model output. UCC is a cross-cutting control plane. Telemetry is first-class and need not pass through an LLM. Hashes establish artifact identity, not truth; schemas establish structural conformance, not truth or authority. Human final authority remains binding.

## Authority lanes

### Atlas triadic posture lane

Forward order: `Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human`.

Atlas may verify parent artifacts, run identity, and repository identity; it requires a valid Sophia disposition and fails closed on missing or altered Sophia evidence. It may compare eligible bounded priors, classify retention, publication, expiry, and revocation posture, render static human-facing review output, and preserve provenance and nonclaims.

Permitted posture labels include `session_only`, `retain_for_human_review`, `quarantine`, `rejected`, `do_not_publish`, `publication_blocked_pending_human_review`, and `retention_intent_only`. These labels are not side effects.

### Publication and DOI execution lane

This repository separately owns publication packages, metadata validation, catalog and knowledge-graph generation, Crossref XML, DOI state, and deposit logs. Publication execution requires separate explicit human authorization.

Atlas posture and publication execution are separate namespaces and separate authority grants.

A favorable Atlas posture is not permission to write memory, canonize, publish, mint a DOI, deposit Crossref metadata, mutate a registry, deploy, or release. A `do_not_publish` or `publication_blocked` posture is a binding block.

## PMR, UCC, telemetry, and retrosynthesis

Atlas assigns memory posture. PMR performs governed provenance retention only when separately authorized; Atlas posture is not PMR execution. UCC is cross-cutting. Atlas consumes applicable retention, expiry, revocation, publication-block, human-review, and provenance-display controls.

Atlas telemetry may record structured packet-receipt, parent-hash and Sophia disposition verification, posture, reason-code, expiry/revocation, rendering, and publication-block events. It must not contain private chain-of-thought, hidden user profiling, unsupported identity inference, or unreviewed memory promotion.

Retrosynthetic feedback may return only as a bounded prior candidate with provenance, uncertainty, expiry, revocation, context scope, and authority limits. No silent learning, automatic memory promotion, automatic canonization, or automatic publication is authorized. Retained or displayed material does not become truth.

## Measurement language

Canonical formal drift measurement is the CoherenceLattice-owned formal measurement artifact. Repository ownership of a measurement implementation does not grant truth certification. Atlas/Publisher provides memory posture and presentation, not automatic storage authority.

## Implementation status matrix

| Capability | Status | Boundary |
| --- | --- | --- |
| Memory-disposition intake | implemented_in_parts | Deterministic posture intake exists; no memory write is authorized. |
| Atlas API server | source_present_not_live_accepted | Source presence is not live-route acceptance. |
| Persistence path | not_authorized | Not invoked or changed by this patch. |
| Publication registry | implemented | Separately governed publication tooling. |
| Crossref dry-run | implemented_in_parts | Separate publication operation; not run by this patch. |
| Live Crossref deposit | not_authorized | Requires separate human authorization. |
| Knowledge graph | implemented | Publication-registry artifact, not cognition truth. |
| Human rendering | implemented_in_parts | Static rendering is distinct from a final decision. |
| ADR posture integration | implemented | Documentation adoption only. |
| Real three-process route | source_present_not_live_accepted | The complete live route is not accepted or green. |
| PMR retention | not_authorized | Separate governed retention authority is required. |
| Automatic canonization | not_authorized | Never granted by posture. |
| Automatic publication | not_authorized | Never granted by posture. |
| Retrosynthetic prior return | planned | Bounded candidates require a future authorized lane. |
| UCC SaaS | planned | UCC control use does not require a SaaS catalog. |
| Complete cognition engine | not_authorized | This adoption grants no runtime authority. |
