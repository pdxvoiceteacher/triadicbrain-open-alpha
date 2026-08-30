# Sophia adoption of UVLM Triadic Cognition Core v1

**Local document ID:** UVLM-TCC-ADR-001-SOPHIA-ADOPTION-00
**Status:** accepted_architecture_adoption; implementation_in_progress
**Canonical document ID:** UVLM-TCC-ADR-001
**Canonical repository:** pdxvoiceteacher/CoherenceLattice
**Canonical path:** `docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md`
**Canonical source commit:** `d09ac8667ce648ac8492055e752f257611fabbe0` (CoherenceLattice `master`, retrieved from GitHub raw source)
**Canonical document SHA-256:** `4d564f76107db0d0ff436736334c72b9a7a6a42b429634d6342354d61745b061`
**Date of adoption:** 2026-07-17
**Sophia repository:** pdxvoiceteacher/Sophia
**Sophia adoption commit:** pending_until_commit
**Authority effect:** none.

Sophia is the independent governance and claim-boundary layer of the UVLM Triadic Cognition Core.

Sophia does not generate the model candidate it audits.

Sophia does not consume raw Ollama output.

Sophia consumes provenance-bound candidate and evidence artifacts produced through the Sonya and CoherenceLattice boundaries.

## Scope and architecture lock

This is a repository adoption document, not a runtime authorization. It adopts the accepted canonical architecture while preserving Sophia's independent role. It grants no live-model, network, CoherenceLattice runtime, Atlas runtime, PMR-write, publication, deployment, or release authority.

The canonical model-result order is:

```text
approved local model backend → Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human → PMR only when separately authorized
```

The invocation boundary is distinct from the result flow:

```text
Sonya → model backend → Sonya
```

Sonya calls the model. Sophia does not call the model or another model, and no downstream component consumes raw Ollama output.

## Separate lanes; no ambiguous ordering

### Forward candidate-governance lane

The forward candidate lane is:

```text
CoherenceLattice → Sophia → Atlas
```

Within the full model-result flow above, Sophia may receive a canonical request identity, grounding-bundle identity, Sonya candidate packet, CoherenceLattice claim/evidence map, CoherenceLattice formal measurements, repository identity, parent packet hashes, logical run ID, and authority ceiling.

Sophia owns independent governance: source-grounding challenge, claim-support and counterevidence review, overclaim detection, uncertainty and proportionality review, authority-ceiling enforcement, stable reason codes, bounded disposition, escalation posture, and human-review routing. It independently reopens or verifies evidence references; verifies parent hashes, run identity, and repository-role identity; challenges unsupported claims and evidence mismatch; detects candidate self-approval; applies selected UCC governance controls; and emits bounded dispositions and reason codes. It requires human review where applicable.

Sophia must not generate the candidate it audits, call Ollama, invoke another model, consume raw Ollama output, rewrite source evidence, silently alter CoherenceLattice measurements, self-approve the candidate, write Atlas memory, publish, canonize, or certify truth.

### Memory / prior-admissibility feedback lane

This is not the same as the forward candidate lane. A separately authorized future or existing bounded process may provide an Atlas or PMR prior candidate to Sophia for admissibility review:

```text
Atlas/PMR candidate → Sophia review
```

Sophia may review provenance; check revocation, expiry, context compatibility, and evidence class; and recommend admit, hold, quarantine, reject, or human review. Its existing memory-disposition handling is bounded review-queue routing, not a memory operation.

This lane must not be described as Atlas automatically preceding Sophia in every cognition run. It does not authorize memory write, canonization, silent prior injection, model training, publication, or truth certification. These lanes must not be collapsed into one ambiguous order.

## Ownership and non-ownership

Sophia does **not** own local model inference, Ollama adapter behavior, Sonya request construction, candidate generation, source ingestion, canonical grounding-bundle generation, CoherenceLattice metric computation, Atlas posture, PMR retention, publication execution, deployment, or the final human decision.

Hashes, schemas, and provenance support integrity checking but do not establish truth. Sophia's disposition is governance guidance and routing posture: it does not issue legal verdicts, determine guilt, authorize adverse action, authorize memory promotion, authorize publication, or authorize deployment. Human final authority remains binding.

## UCC, TEL, and telemetry boundaries

UCC is cross-cutting. Sophia applies the governance portions of selected UCC controls: claim-boundary rules, evidence sufficiency, proportionality, authority limits, escalation, and human-review requirements. Sophia does not own the entire UCC catalog or SaaS.

Sophia telemetry may record packet receipt, schema result, parent-hash result, evidence-verification result, control identifiers, reason codes, bounded disposition, escalation, and output artifact identity. Structured decision evidence is allowed.

Sophia telemetry and TEL must not contain private chain-of-thought, hidden reasoning, scratchpad, unredacted internal deliberation, or unsupported psychographic inference. Private reasoning capture is not allowed.

## Conservative implementation-status matrix

| Surface | Status | Boundary / evidence note |
| --- | --- | --- |
| Local audit runtime | implemented | Local deterministic audit artifacts and bounded decisions exist; this is not live model authority. |
| Sophia API server | implemented | API source and import smoke tests exist; API availability is not deployment authorization. |
| Existing governance packet handling | implemented_in_parts | Existing bridge-oriented governance packets are handled; this is not the UVLM candidate-audit contract. |
| Existing memory-disposition admissibility | implemented_in_parts | Review-queue admissibility is bounded and does not authorize memory write or canonization. |
| UCC routing | implemented_in_parts | Selected governance-control routing is present; Sophia does not own the complete UCC catalog or SaaS. |
| Candidate-audit contract for UVLM-TCC-ADR-001 | implemented_in_parts | Sophia provides a deterministic, file-only audit of hash-bound candidate artifacts; this does not authorize a live cross-repository route. |
| Real separate-process three-repository route | not_authorized | No three-repository acceptance run establishes a live route. |
| Deterministic replay from captured Sonya candidate | source_present_not_live_accepted | Canonical architecture describes it; Sophia has no acceptance evidence for a real cross-repository replay. |
| Live Ollama use | not_authorized | Sophia neither calls nor consumes raw model output. |
| Atlas write | not_authorized | Sophia cannot authorize or perform memory write. |
| PMR write | not_authorized | PMR requires separate authorization and human final authority. |
| Publication | not_authorized | Sophia cannot publish or authorize publication. |
| Full cognition-engine completion | not_authorized | The complete route is not green or accepted. |

## Implementation guardrails

No runtime behavior, schema, network behavior, model behavior, publication behavior, deployment behavior, registry phase entry, manifest, closure receipt, or release is created by this adoption. Any future implementation must remain in the owning repository and must use versioned bridge artifacts or approved sibling CLIs rather than private sibling-package imports.
