# UVLM Triadic Cognition Core v1
**Document ID:** UVLM-TCC-ADR-001  
**Status:** accepted_architecture; implementation_in_progress

The UVLM Triadic Cognition Core is a local-first, evidence-bound, governed cognition architecture. Its model-result path is: **Ollama or another approved local model → Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human → PMR only when separately authorized.** The architecture is a governed loop, not a single linear pipeline.

## Request and model-invocation flow
```text
Human/operator → Sonya consent, identity, privacy, and adapter boundary
→ CoherenceLattice canonical ingress, grounding, context, and UCC plan
→ Sonya model request → Ollama adapter → local model → raw output returns to Sonya
```
Sonya calls Ollama. Ollama output flows into Sonya. **No downstream component consumes raw Ollama output.** An approved model backend is an inference engine only: it has no governance, direct downstream integration, or truth authority.

## Candidate-artifact flow
```text
Sonya candidate packet → CoherenceLattice claim/evidence mapping, GUFT metrics, TEL,
telemetry, and UCC processing → Sophia independent governance disposition
→ Atlas/Publisher retention/publication posture and human-facing rendering
→ Human final decision → PMR only after separate authorization
```
Sonya owns consent, privacy, adapter permission, model identity, raw-output quarantine, and a non-authoritative candidate packet. It must not approve its candidate, decide memory, publish, call Sophia on its own authority, or bypass CoherenceLattice evidence processing.

## Telemetry flow
```text
sensor/application/AI node/tool → typed adapter or governed telemetry gateway
→ CoherenceLattice telemetry/TEL → deterministic UCC controls
→ Sophia escalation when required → operator action or Atlas historical posture
```
Telemetry does not need to pass through an LLM. Ollama is optional for interpretation, explanation, or synthesis. Raw telemetry remains the evidence substrate.

## Retrosynthetic feedback flow
```text
human correction / telemetry anomaly / model failure / novel success / scientific perturbation
→ Coherence Retrosynthesis → branch reconstruction and counter-hypotheses
→ candidate invariant extraction → GUFT metrics and UCC → Sophia audit → Atlas posture
→ human review → governed PMR retention → bounded future prior
```
No silent learning. No automatic model retraining. No automatic memory promotion. No automatic self-modification.

## Component ownership and limits
**CoherenceLattice** owns canonical ingress, grounding bundles, evidence topology, claim/evidence linkage, GUFT/ΔSyn measurements, TEL, telemetry, UCC runtime coordination, retrosynthesis, orchestration, and replay verification. It must not call measurements final truth, manufacture Sophia dispositions or Atlas postures, authorize publication/PMR writes, or self-approve.

**Sophia** independently challenges evidence sufficiency, counterevidence, proportionality, authority ceilings, reason codes, and bounded escalation/disposition. It must not generate the candidate it audits, write Atlas memory, publish, or certify truth.

**Atlas/Publisher** owns prior comparison, retention/publication/expiry/revocation posture, memory-facing metadata, and static human-facing rendering. It must not write memory automatically, canonize, alter Sophia’s disposition, trigger DOI/publication workflows, or certify truth.

**PMR** is governed provenance retention, replayable lineage, correction, revocation, and consent-bounded future prior. PMR is not truth, canon, ordinary chat history, automatic training data, or a silent user profile. **Human final authority** approves memory writes, publication, deployment, correction, and revocation.

## UCC architecture
UCC is a **cross-cutting control plane**. **UCC Core** is local, offline-capable typed control modules, reasoning steps, evidence requirements, validation rules, escalation, telemetry, and receipts. **UCC Catalog/SaaS** is a future optional lifecycle service for versioning, official-source provenance, licensing, jurisdiction, supersession, organization overlays, and distribution. The local cognition engine must not require SaaS availability.

PRISMA 2020 is a planned free public UCC reporting profile: reporting guidance, not certification, not proof of systematic-review quality, and not publication authority; attribution and license requirements apply. Industry standards require copyright, licensing, jurisdiction, and scope review before module use.

## Implementation status matrix
| Surface | Status | Boundary |
|---|---|---|
| Sonya request builder; candidate builder; grounding bundles; TEL | implemented_in_parts | no live authority implied |
| Sonya Ollama adapter; telemetry; UCC runtime; deterministic replay from captured candidate | implemented_in_parts | activation remains separately governed |
| Sophia independent repository process; Atlas posture intake; Coherence Retrosynthesis | planned | separate repository/adoption evidence required |
| Full real-model three-repository route; PMR retention; UCC SaaS catalog; PRISMA module | not_authorized | no complete cycle is green |

This ADR does not claim the complete live three-repository cognition route is accepted.
