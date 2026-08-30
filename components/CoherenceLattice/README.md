We are building the Triadic Brain, a local-first AI governance system for people and organizations that want powerful AI without giving up control of their data.

The idea is that users can host their own models locally, keep their own data private or encrypted, and still participate in a federated network of shared provenance, review schemas, and bounded prior packets.

In this architecture, models connect through governed Sonya Nodes. A Sonya Node does not make a model “truthful”; it makes the model’s work inspectable. Each output becomes a typed, hash-linked candidate packet with model identity, source references, provenance, and explicit boundaries. Evidence enters separately through grounded source bundles, so the system can distinguish source material from model interpretation.

Users and organizations can optionally share best-practice schemas through the Universal Control Codex, along with provenance receipts, benchmark results, and carefully bounded priors. The goal is collective improvement without forcing private data into a central black box.

The system is being designed to help answer questions like:

Which source supported this claim?
Which model produced this candidate?
What prior memory was used?
Was that prior compatible with the current source?
Where did uncertainty remain?
Did the output pass governance review?
Is this ready for reuse, or should it be quarantined for human review?

The long-term goal is a federated AI ecosystem where local models can cooperate through auditable evidence, governed memory, and transparent review — improving reliability while preserving data sovereignty.

Data stays local. Provenance becomes shareable. AI cognition becomes auditable.

#TriadicBrain #LocalAI #FederatedAI #AIAlignment #Provenance #AIgovernance #OpenSourceAI
 

---


## Architecture quick lock

The canonical architecture is [UVLM-TCC-ADR-001](docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md). Model-result flow: **Ollama → Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human**. Invocation clarification: **Sonya → Ollama → Sonya**. UCC is cross-cutting, telemetry is first-class, retrosynthesis is the governed feedback metabolism, and PMR is governed provenance—not truth. The complete live three-repository route is not yet accepted.

## Provenance apprentice curriculum

The canonical training package, including the preserved v1.0.0 base curriculum
and adopted compatible v1.1.0 refinement overlay, is available at
[docs/provenance/pedagogy/README.md](docs/provenance/pedagogy/README.md).

## Local AHA Pattern Donation review

The local Sonya shell includes a deterministic, model-free AHA candidate-review
workflow. Start `sonya-desktop`, open `http://127.0.0.1:4180/aha`, upload one
target and two to five donor `.txt` or `.md` sources, complete the guided
structural mapping, then read the review and open its artifacts. The review is
not truth, approval, memory, publication, deployment, or release authority.

## Governed document review

Start `sonya-desktop`, open `/cognition`, upload a supported local text source,
state a task, choose the approved local adapter and model, then follow the
bounded status page. The initial intake records external-only session evidence
and preserves Sonya's model membrane; it is not a decision, memory,
publication, deployment, or release action.

## Canonical Formal Drift Artifact

CoherenceLattice produces the canonical formal-drift measurement artifact used by the triadic architecture. That artifact is bounded evidence and posture, not truth certification.
Downstream repositories (for example Sophia/Atlas integrations) should consume:

- `bridge/coherence_drift_map.json` (canonical per-concept drift, regime centroid reference, psi coherence, drift band)
- `bridge/coherence_drift_summary.json` (concept count, mean/max drift, high-drift concepts)

Do **not** independently recompute canonical drift in downstream repos; local UI drift heuristics may exist, but the bounded formal-drift measurement comes from CoherenceLattice bridge artifacts.

### Triadic phaselock order and semantics

Integration order is fixed:

- `CoherenceLattice -> Sophia -> Publisher`

Semantic responsibilities:

- **formal drift** = canonical CoherenceLattice measurement evidence (not truth authority)
- **attention update** = Sophia executive interpretation
- **overlay rendering** = Publisher visualization/memory presentation

If Publisher maintains a local view-layer mismatch heuristic, prefer a non-canonical name such as `activityMismatchScore` to avoid ambiguity with canonical lattice drift.

See `docs/BRIDGE_INTEGRATION_PHASELOCK.md` for the cross-repo contract details.

### Canonical ingestion gate for new Sonya inputs

All new/external Sonya inputs must be formally projected through CoherenceLattice before Sophia evaluates admission decisions:

`raw Sonya input -> CoherenceLattice projection -> Sophia audit -> Atlas/Publisher memory posture and presentation`

Authoritative projection artifacts:

- `bridge/sonya_lattice_projection.json`
- `bridge/sonya_projection_summary.json`

CoherenceLattice performs formal projection/characterization only; executive admission decisions remain Sophia responsibilities.

### Canonical reasoning-thread formalization

`bridge/reasoning_thread_map.json` is the canonical formal representation of admitted-memory thread structure produced by CoherenceLattice.

It provides deterministic thread construction and coherence characterization, but it is **not** a final judgment of significance or executive admission/ranking.

### Canonical longitudinal reasoning monitor

CoherenceLattice owns the canonical formal longitudinal view of reasoning-thread stability via:

- `bridge/reasoning_thread_history.json`
- `bridge/coherence_monitor_report.json`
- `bridge/coherence_monitor_summary.json`

This monitoring layer is descriptive/formal and **not** an escalation-significance decision layer.

CoherenceLattice formalizes social-entropy and civic-cohesion signals only; it does not authorize suppression of dissent or coercive normalization.

CoherenceLattice formalizes federated stewardship and capture-risk signals only; it does not assign sovereignty to any node or authorize central control.

CoherenceLattice formalizes commons participation and cognitive-legibility signals only; it does not rank persons, assign civic worth, or authorize exclusion.

CoherenceLattice formalizes emergent-domain and field-birth signals only; it does not declare a new science as socially accepted truth by itself.

CoherenceLattice formalizes commons sovereignty signals only; it does not assign control authority or override human governance.

CoherenceLattice formalizes civilizational memory and stewardship signals only; it does not autonomously rewrite canon, suppress historical branches, or determine final cultural authority.

CoherenceLattice formalizes epistemic attractors, basins, dead zones, and paradigm-shift signals only; it does not declare final truth, close scientific competition, or assign canonical scientific sovereignty.

CoherenceLattice formalizes operational maturity and deployment-boundary signals only; it does not authorize deployment, policy enactment, or infrastructure control.

CoherenceLattice formalizes discovery vectors, bridge stability, entropy-reduction corridors, and navigation priorities only; it does not autonomously pursue, deploy, or certify discoveries, and it prioritizes coherent care, legibility, and commons review over novelty alone.

CoherenceLattice formalizes knowledge rivers, corridor braiding, tributary support, and river capture-risk signals only; it does not declare final truth, close scientific competition, or authorize deployment or canon formation.

CoherenceLattice formalizes delta seeds, paradigm convergence, epistemic reorganization, and civilizational delta forecasts only; it does not declare epochal truth, canonize paradigms, or authorize governance or deployment transitions.

CoherenceLattice formalizes epochal terraces, stability plateaus, institutional sedimentation, and terrace erosion signals only; it does not declare final epochs, canonize civilizations, or authorize institutional control.

CoherenceLattice formalizes terrace erosion, orthodoxy pressure, renewal corridors, and epochal-transition forecasts only; it does not declare epoch collapse, authorize institutional overthrow, or canonize successor orders.
CoherenceLattice formalizes renewal braids, successor delta seeds, plurality recovery, and transition coupling only; it does not declare successor epochs, authorize institutional replacement, or canonize emergent orders.
CoherenceLattice formalizes successor maturation, false-future risk, plurality retention, and maturation gates only; it does not declare new epochs, authorize successor governance, or canonize emergent futures.
CoherenceLattice formalizes successor crossing, false-future decay, delta-crossing gates, and future viability only; it does not declare new epochs, authorize successor governance, or canonize emergent futures.
CoherenceLattice formalizes new-delta stabilization, fragmented-renewal reversion, crossing resilience, and post-crossing governance gates only; it does not declare new epochs, authorize successor governance, or canonize emergent futures.
CoherenceLattice formalizes terrace seeds, experimental repluralization, sedimentation readiness, and terrace-seed gates only; it does not declare new epochs, authorize successor governance, or canonize emergent orders.
CoherenceLattice formalizes epochal surfaces, habitable plateaus, reopened experimentation, and surface-emergence gates only; it does not declare new epochs, authorize successor governance, or canonize emergent orders.
CoherenceLattice formalizes living terraces, commons habitability, plural habitation, and terrace consolidation gates only; it does not declare new epochs, authorize settlement authority, or canonize emergent orders.

Derivatives that remove provenance or alter safety boundaries without disclosure lose canonical trust status, and downstream overlays should visibly mark canonical divergence.

### Canonical multimodal projection and reinforcement assessment

CoherenceLattice owns canonical formal multimodal projection and initial cross-modal reinforcement assessment via:

- `bridge/multimodal_lattice_projection.json`
- `bridge/multimodal_projection_summary.json`
- `bridge/cross_modal_reinforcement_report.json`
- `bridge/cross_modal_reinforcement_summary.json`

This layer is formal/descriptive and does **not** decide admission or significance; executive audit remains downstream (Sophia).

### Canonical promotion-candidate characterization

CoherenceLattice owns canonical formal characterization of promotion-worthiness signals via:

- `bridge/promotion_candidate_map.json`
- `bridge/promotion_candidate_summary.json`

These artifacts prepare structured human-review candidates, but do **not** perform executive/editorial promotion decisions.

### Constitutional constraints and continuity protocol

CoherenceLattice formalizes constitutional constraints and continuity-mode conditions as canonical bridge artifacts:

- `bridge/constitutional_principles.json`
- `bridge/constitutional_formalization.json`
- `bridge/constitutional_health_report.json`
- `bridge/continuity_mode_assessment.json`

These artifacts support bounded governance stress assessment (watch/freeze/preservation signaling) and anti-capture monitoring, but CoherenceLattice does **not** authorize unilateral governance changes or autonomous constitutional rewriting.


### Constitutional deliberation docket and amendment queue formalization

CoherenceLattice also formalizes deliberation-state and amendment-worthiness signals as review artifacts:

- `bridge/deliberation_state_map.json`
- `bridge/deliberation_state_summary.json`
- `bridge/amendment_candidate_map.json`
- `bridge/amendment_candidate_summary.json`

These artifacts are procedural review objects only (deliberation docket/amendment queue) and do **not** authorize constitutional change, ratification, or enactment.


### Succession and quorum resilience formalization

CoherenceLattice formalizes governance survivability, reviewer redundancy, quorum fragility, and continuity roster signals via:

- `bridge/succession_state_map.json`
- `bridge/succession_state_summary.json`
- `bridge/quorum_resilience_report.json`
- `bridge/continuity_roster_candidates.json`

These artifacts characterize succession and resilience conditions only; CoherenceLattice does **not** appoint successors, transfer authority, or auto-install governance roles.


### Evidence escrow and recovery formalization

CoherenceLattice formalizes preservation criticality, escrow indexing, integrity watchlists, and recovery-worthiness signals via:

- `bridge/preservation_state_map.json`
- `bridge/preservation_state_summary.json`
- `bridge/artifact_escrow_plan.json`
- `bridge/recovery_candidate_map.json`

These artifacts are formal review materials only; CoherenceLattice does **not** execute replication, silent persistence, or automatic recovery.


### Federated witness and external attestation formalization

CoherenceLattice formalizes attestation-worthiness and witness-readiness signals via:

- `bridge/attestation_state_map.json`
- `bridge/attestation_state_summary.json`
- `bridge/witness_roster_candidates.json`
- `bridge/attestation_candidate_map.json`

These outputs describe federated witnessability and integrity-check readiness only; CoherenceLattice does **not** attest, sign, ratify, or authorize state transitions.


### Normative memory and precedent formalization

CoherenceLattice formalizes precedent-memory, case analogy candidates, and divergence watch signals via:

- `bridge/precedent_state_map.json`
- `bridge/precedent_state_summary.json`
- `bridge/case_analogy_candidates.json`
- `bridge/precedent_divergence_report.json`

Precedent in this layer is persuasive, not absolute: divergence from precedent should remain explicit/reviewable; constitutional principles outrank precedent; and anti-capture risk overrides convenience in precedent reuse. These artifacts do **not** bind future decisions or authorize automatic rule hardening.


### Scenario simulation and adversarial stress formalization

CoherenceLattice formalizes bounded stress rehearsal artifacts via:

- `bridge/scenario_catalog.json`
- `bridge/scenario_state_map.json`
- `bridge/scenario_outcome_projection.json`
- `bridge/scenario_stress_summary.json`

These outputs are preparedness simulations only. They inform review and rehearsal, but do **not** trigger live governance actions, emergency overrides, or automatic crisis execution.

## Product usability status

The bounded live three-repository route and Workstream 02-A Atlas human-decision UI completed local Windows acceptance. This is **not** deployment or release readiness.

`sonya-desktop --repo-root <absolute CoherenceLattice root> --no-browser` launches the bounded foreground loopback Sonya shell. DELTA-00 is the supervisor foundation for a later thin tray adapter; it does not perform task intake, model calls, review, memory, publication, deployment, or release.

## Build status

<!-- Replace <OWNER>/<REPO> and workflow filenames if needed -->
**Lean proofs:**  
[![Lean proofs](https://github.com/pdxvoiceteacher/CoherenceLattice/actions/workflows/lean_proofs_ci.yml/badge.svg?branch=master)](https://github.com/pdxvoiceteacher/CoherenceLattice/actions/workflows/lean_proofs_ci.yml?query=branch%3Amaster)


## CoherenceLattice — GUFT / Coherence / Sacred Geometry / Generative Engines (Lean + Python)

This repository is a working lab for cross-domain coherence modeling and formal verification (Lean 4 + Mathlib) alongside Python engines (UCC + coherence/music utilities). The goal is a unified, testable interface for reasoning about coherence, coarse-graining, safety transitions, and generative mappings (including sacred geometry and musical ratio systems), with paper-facing “gloss” layers and reproducible artifacts.

**Status: ✅ Everything referenced below is building green under Lean 4.27.0-rc1.**

## Repo Structure (high level)

CoherenceLattice/Coherence/
Lean modules for coherence lattice, ΔSyn dynamics guardrails, paper-facing wrappers, sacred geometry formalizations, and eval-only diagnostics.

CoherenceLattice/Quantum/
Lean quantum anchor demonstrations (Pauli matrices, simple finite constructions).

ucc/
Universal Control Codex (Python) — governance & safety tooling + CI-style checks and demos.

python/
Python coherence simulations / music experiments / supporting utilities.

paper/
Manuscript support files and exported CSV artifacts (paper/out/*.csv).

Lean: Core Coherence Lattice (formal)
Coherence state + invariants

State: points (E,T) in the unit square [0,1]×[0,1]

Coherence: psi = E*T

# Proofs include:

psi_nonneg and psi_le_one → 0 ≤ psi ≤ 1

monotonicity lemmas and Lipschitz-style bounds in the unit square

Regimes + safe transitions (“no teleport”)

classify : State -> Regime maps a state to discrete bands using thresholds tau0..tau3

validTransition enforces adjacency-only regime steps

No-teleport theorem: if |Δpsi| < tau0 then the induced regime transition is valid

This is used to prove that capped ΔSyn-driven updates cannot “jump regimes” unexpectedly.

ΔSyn dynamics guardrails (formal)

Two safe update styles are formalized:

ψ-centric step (stepPsi) — update psi directly, then clamp back into [0,1]

E/T-centric step (stepET) — update E and T independently, clamp each into [0,1]

**Key theorems:**

validTransition_stepPsi / validTransition_stepET
Each step respects the regime graph.

abs_psi_stepET_sub_le
Per-step bounded drift: |Δpsi| ≤ tau0/2

interpretation lemma variants linking ΔS sign to monotone drift (paper-friendly wrapper names live in PaperGloss).

Paper-facing wrapper layer

A “gloss” layer provides stable lemma names and narrative-friendly constructors so a manuscript can cite Lean without exposing internal file structure.


**This includes:**

stable lemma wrappers

sunflower packing bundle constructors

successor-specialized corollaries


**Lean: Sacred Geometry Formalizations (formal + scaffolds)**
Flower of Life / centered hex counts (formal)

A Flower-of-Life / hex-lattice point count model using centered hex numbers:

recursive flowerPoints and proof that:

flowerPoints n = centeredHex n

Sacred circles + crop-circle scaffolding (formal + validation)


**Algebraic circle primitives:**

circle structure with radius nonneg proof

circumference + area

scaling laws: circumference scales linearly, area scales quadratically (k ≥ 0)

**Crop-circle pattern scaffolding:**

rosette circle generation via List.range k

count lemmas (rosette length; rosette+center count = k+1)

signature structure (order,count) + validation lemma


**Lean: Tree of Life → Coherence Lattice mapping (synced)**

We model the Tree of Life (Sephirot) as a mapping into the coherence lattice state space:

EFrac / TFrac provide a single source of truth as unit fractions (Nat/Nat with proofs).

sephiraState derives the lattice state (E,T) from these fractions.

sephiraPsi is coherence psi on the sephiraState.

proof:

sephiraPsi_bounds : 0 ≤ sephiraPsi s ∧ sephiraPsi s ≤ 1

A lightweight adjacency graph over Sephirot is included (TreeOfLifeGraphAddons) with psiPath + bounds over paths.


**Lean: Music — ratios + scale scaffolds (synced profiles)**
Just ratios (formal, Lean-light)

canonical ratios: unison, minor third, major third, fourth, fifth, octave

ordering / chain lemmas usable in narrative

Music scale scaffold (profiles)

The repo now has synced consonance profiles stored in MusicScaleScaffoldAddons.lean:

Rat profiles (computable / eval tooling)

consonantSetRat_major

consonantSetRat_minor

chordOKRat_major, chordOKRat_minor

Real profiles (proof-facing scaffolds)

consonantSet_major

consonantSet_minor

chordOK_major, chordOK_minor

This ensures the eval artifacts and proof-facing scaffolds can’t drift out of sync.

Eval-only Artifacts (“bells & whistles”)

Eval-only files are non-proof diagnostics intended for:

quick sanity checks

generating CSV outputs for Python diffs

reproducible paper artifacts


**Crop circles: rotated centers + invariance checks**

CropCircleRotatedCentersEval.lean

outputs CSV rows for each rotation angle:

rotated centers

distance-from-origin invariance

per-angle summary row

global summary row

strict CSV column completion (okAngle column always present)

comment separators # ---- next angle ---- for readability


**Tree of Life: band table CSV**

TreeOfLifeBandCSV.lean

prints:

name, E, T, psi, band

band thresholds are configurable in the file

exportable to paper/out/tree_of_life_bands.csv


**Tree of Life: Real/Float spot checks**

TreeOfLifeRealFloatEval.lean

prints exact Rat psi and Float psi

uses #reduce on Real psi terms for structural sanity (no execution)


**Music: profile comparison CSVs**

MusicScaffoldEval.lean

prints scale + chord accept/reject tables under:

major consonance profile

minor-friendly consonance profile

includes per-profile __SUMMARY__ rows

Exporting CSV Artifacts to paper/out
One-shot export (Tree of Life, Crop circles, Music)


## Use the PowerShell export script shared in chat to generate:

paper/out/tree_of_life_bands.csv

paper/out/crop_circle_rotated_centers.csv

paper/out/music_scaffold_profiles.csv (combined sections)

Split music export

The “split by section markers” PowerShell script outputs:

paper/out/music_scale.csv

paper/out/music_chords_major.csv

paper/out/music_chords_minor.csv

Building / Running Lean
Build individual modules
lake build CoherenceLattice.Coherence.TreeOfLifeAddons
lake build CoherenceLattice.Coherence.TreeOfLifeGraphAddons
lake build CoherenceLattice.Coherence.CropCirclesAddons
lake build CoherenceLattice.Coherence.MusicScaleScaffoldAddons

Run eval-only tools
lake env lean CoherenceLattice/Coherence/CropCircleRotatedCentersEval.lean
lake env lean CoherenceLattice/Coherence/TreeOfLifeBandCSV.lean
lake env lean CoherenceLattice/Coherence/MusicScaffoldEval.lean

Building / Running Python (UCC + engines)

Python components live primarily under:

ucc/ (Universal Control Codex)

python/src/ (coherence sim + coherence music experiments)

# Typical workflow:

set up venv

run tests and example demos

compare outputs against exported Lean CSVs when relevant (e.g., music ratios / phyllotaxis / crop circles)

(If you want, we can add a dedicated python/tools/compare_csv.py to diff Lean-exported CSVs vs Python engine output.)

# Notes on Encoding + Windows

The project uses UTF-8 (no BOM) for Lean files generated via PowerShell.

ASCII-safe identifiers are used where Windows encoding pitfalls have previously caused “unexpected token” errors.

# Contributing / Workflow

Make a change in Lean or Python

lake build the relevant modules

Run eval artifacts when appropriate and export to paper/out

Commit Lean + exported CSV artifacts together when they substantively update the paper-facing story

## License / Attribution

This repo includes original work by UVLM/Prislac and collaborators, plus dependencies from Mathlib and standard toolchains.

---

## Quickstart (Windows + PowerShell)

This is the fastest “clone → build → run eval tools → export CSVs” path on Windows.

0) Prereqs

You’ll need:

Git

Lean toolchain via elan (recommended)

Lake (comes with Lean via elan)

A working C toolchain isn’t typically needed for Mathlib-only Lean builds, but keep your environment consistent with what you already use (you’re on Lean 4.27.0-rc1).

1) Clone + enter repo
git clone https://github.com/pdxvoiceteacher/CoherenceLattice.git
cd CoherenceLattice

2) Confirm Lean + Lake
lean --version
lake --version

3) Pull dependencies (Mathlib, etc.)
lake update

4) Build the core Lean project

Full build:

lake build


Or build key targets (faster, iterative):

lake build CoherenceLattice.Coherence.TreeOfLifeAddons
lake build CoherenceLattice.Coherence.TreeOfLifeGraphAddons
lake build CoherenceLattice.Coherence.CropCirclesAddons
lake build CoherenceLattice.Coherence.MusicScaleScaffoldAddons

5) Run eval-only tools (prints CSV/text to console)
lake env lean CoherenceLattice/Coherence/TreeOfLifeBandCSV.lean
lake env lean CoherenceLattice/Coherence/CropCircleRotatedCentersEval.lean
lake env lean CoherenceLattice/Coherence/MusicScaffoldEval.lean

6) Export eval outputs to paper/out/ (UTF-8 no BOM)

Create output directory:

New-Item -ItemType Directory -Force -Path paper\out | Out-Null


Export Tree of Life band table:

$enc = New-Object System.Text.UTF8Encoding($false)
$tol = (lake env lean CoherenceLattice/Coherence/TreeOfLifeBandCSV.lean) -join "`n"
$tol = ($tol -split "`n" | Where-Object { $_ -notmatch '^\s*#' -and $_ -ne "" }) -join "`n"
[System.IO.File]::WriteAllText("paper\out\tree_of_life_bands.csv", $tol, $enc)
"wrote paper\out\tree_of_life_bands.csv"


Export crop-circle rotated centers (filters # comment separators):

$crop = (lake env lean CoherenceLattice/Coherence/CropCircleRotatedCentersEval.lean) -join "`n"
$crop = ($crop -split "`n" | Where-Object { $_ -notmatch '^\s*#' -and $_ -ne "" }) -join "`n"
[System.IO.File]::WriteAllText("paper\out\crop_circle_rotated_centers.csv", $crop, $enc)
"wrote paper\out\crop_circle_rotated_centers.csv"


Export combined music scaffold output (keeps # section markers):

$music = (lake env lean CoherenceLattice/Coherence/MusicScaffoldEval.lean) -join "`n"
[System.IO.File]::WriteAllText("paper\out\music_scaffold_profiles.csv", $music, $enc)
"wrote paper\out\music_scaffold_profiles.csv"

7) Optional: Split music into three CSVs

If you’ve added the section-splitting PowerShell script from chat, run it to generate:

paper/out/music_scale.csv

paper/out/music_chords_major.csv

paper/out/music_chords_minor.csv

8) Commit + push
git status
git add CoherenceLattice/Coherence/*.lean paper/out/*.csv
git commit -m "Add Lean proofs + eval CSV artifacts (Tree-of-Life, crop circles, music profiles)"
git push


### Institutional state canonical producer contract (Phase P.1)

CoherenceLattice now publishes the **only canonical institutional artifacts** using these exact filenames:

- `bridge/institutional_state_map.json`
- `bridge/institutional_state_summary.json`
- `bridge/institutional_conflict_report.json`
- `bridge/institutional_health_projection.json`
- `bridge/phaselock_contract_report.json`

Alternative names such as `institutional_synthesis.json` are **deprecated** and must not be used by downstream consumers except as temporary compatibility aliases with explicit deprecation messaging.


### Queue pressure and anti-Goodhart formalization (Phase Q)

CoherenceLattice canonically formalizes operational queue pressure, review-load concentration, and metric-gaming risk via:

- `bridge/queue_pressure_map.json`
- `bridge/queue_pressure_summary.json`
- `bridge/review_load_distribution.json`
- `bridge/goodhart_risk_report.json`

This layer is formal-only: CoherenceLattice does **not** execute load shedding, reviewer reassignment, queue mutation, or automatic policy intervention.


### Priority and triage formalization (Phase R)

CoherenceLattice canonically formalizes priority and triage-worthiness signals via:

- `bridge/priority_state_map.json`
- `bridge/priority_state_summary.json`
- `bridge/triage_candidate_map.json`
- `bridge/triage_conflict_report.json`

This layer is descriptive-only: CoherenceLattice does **not** execute triage actions or reorder queues by itself.


### Closure and repair formalization (Phase S)

CoherenceLattice canonically formalizes closure state, repair-worthiness, and reopen signals via:

- `bridge/closure_state_map.json`
- `bridge/closure_state_summary.json`
- `bridge/repair_candidate_map.json`
- `bridge/reopen_signal_report.json`

CoherenceLattice formalizes closure and repair-worthiness only; it does **not** close or reopen cases by itself.


### Symbolic multi-axial field and early-warning formalization (Phase T)

CoherenceLattice canonically formalizes symbolic multi-axial field state and early-warning regime signals via:

- `bridge/symbolic_field_state.json`
- `bridge/symbolic_field_summary.json`
- `bridge/regime_transition_report.json`
- `bridge/early_warning_signal_map.json`

CoherenceLattice formalizes symbolic field state and warnings only; it does **not** execute intervention or memory mutation by itself.


### Claim typing, entity-resolution, and verification formalization (Phase U)

CoherenceLattice canonically formalizes claim type, entity ambiguity, and verification-worthiness via:

- `bridge/claim_type_map.json`
- `bridge/entity_resolution_map.json`
- `bridge/entity_resolution_summary.json`
- `bridge/verification_task_map.json`

CoherenceLattice formalizes claim/identity ambiguity and verification-worthiness only; it does **not** declare wrongdoing or resolve identity conclusively by itself.


### Public-record intake, entity-graph, and chain-of-custody formalization (Phase V)

CoherenceLattice canonically formalizes public-record intake structure, entity graph-worthiness, relationship edges, and evidence chain-of-custody via:

- `bridge/public_record_intake_map.json`
- `bridge/entity_graph_map.json`
- `bridge/relationship_edge_map.json`
- `bridge/chain_of_custody_report.json`

CoherenceLattice formalizes public-record structure and graph-worthiness only; it does **not** accuse, infer corruption, or resolve identity conclusively by itself.


### Environment-integrity and counter-hypothesis formalization (Phase W)

CoherenceLattice canonically formalizes environment-integrity anomaly structure, anomaly-domain rollups, evidence maturity, and counter-hypothesis coverage via:

- `bridge/environment_integrity_map.json`
- `bridge/anomaly_domain_map.json`
- `bridge/evidence_maturity_report.json`
- `bridge/counter_hypothesis_map.json`

This layer is formal-only and non-accusatory: CoherenceLattice does **not** conclude manipulation occurred, does not assign guilt, and does not execute intervention by itself.


### Observer cartography and onboarding formalization (Phase BC)

CoherenceLattice canonically formalizes observer cartography and onboarding readiness via:

- `bridge/observer_cartography_map.json`
- `bridge/visualization_access_profile.json`
- `bridge/polycentric_onboarding_registry.json`
- `bridge/participatory_standing_report.json`

Observer cartography and onboarding outputs widen legibility and participation without granting autonomous governance authority, sovereignty transfer, or coercive classification rights.

Build:

- `python -m coherence.bridge.build_observer_onboarding_state --repo-root .`

Validate:

- `python -m coherence.bridge.build_observer_onboarding_state --repo-root . --validate-only`

Observer classes include `sophia`, `human-steward`, `human-public`, `recognized-nonhuman`, `candidate-intelligence`, and `witness-only`; these are bounded interface classes and not sovereignty ranks.

Guided views prioritize translation support for low-legibility contexts, public views expose safe summaries without mutation pathways, and steward views provide expanded context while preserving anti-priesthood and anti-capture boundaries.

CoherenceLattice formalizes canonical authorship, disclosure completeness, and misattribution-risk signals only; it does not execute retaliation, sabotage, or coercive enforcement against derivatives.

## Legibility, Lineage, and Queryability Hardening

This refinement track improves operator usability without changing constitutional boundaries.

### Purpose

- make cross-phase lineage and vocabulary legible,
- compress complex bridge state into queryable operator views,
- preserve bounded/non-authoritative semantics while improving day-to-day stewardship.

### Operator value

- faster answerability for “where did this status come from?”
- clearer boundary notes that prevent governance over-claim drift
- compact memory traces for handoff and review continuity

### Agent Echo field-test relevance

These LRQ artifacts reduce founder-only context dependency so bounded stewards and Agent Echo operators can audit signal paths and unresolved tensions quickly.

### Query helper commands

- `PYTHONPATH=python/src python -m coherence.tools.query_bridge_artifact --phase-id BO`
- `PYTHONPATH=python/src python -m coherence.tools.query_bridge_artifact --status keep-open --json`
- `PYTHONPATH=python/src python -m coherence.tools.summarize_phase_status --format both`

### Boundary note

This hardening track improves legibility and navigation only; it does **not** transfer governance authority, declare final epochs, or close canon.

## Navigation kernel CLI (triadic brain)

Build `bridge/navigation_state.json` from low-level telemetry and validate output:

```bash
PYTHONPATH=python/src python -m coherence.bridge.build_navigation_state \
  --repo-root . \
  --out bridge/navigation_state.json \
  --validate
```

The navigation kernel reads `bridge/telemetry_field_state.json`, computes a weighted coherence potential per adjacent candidate, and selects deterministic next-state recommendations for each node.

### Agent Echo telemetry example

Example event file:

`telemetry/events/agent_echo.json`

```json
{
  "telemetryId": "agent_Echo_123",
  "agentId": "EchoAI",
  "novelty": 0.85,
  "transfer": 0.60,
  "contradiction": 0.10,
  "uncertainty": 0.15,
  "ethicalSymmetry": 0.92,
  "requiresExecutiveReview": false
}
```

Ingest with tools:

```bash
PYTHONPATH=python/src python -m coherence.tools.inject_agent_telemetry_event --repo-root . \
  --agent-id EchoAI --novelty 0.85 --transfer 0.6 --contradiction 0.1 --uncertainty 0.15 \
  --ethical-symmetry 0.92 --notes "Loop test"
```
# Provider-bound cognition (local alpha)

The Sonya `/cognition` intake is a local, evidence-bound review surface. Select
only an approved provider profile and a model permitted by that profile; a
non-loopback profile requires explicit egress consent. Provider secrets are
environment-resolved and are never entered into the form or evidence package.
Candidate output remains non-final and requires independent Sophia/Atlas and
human review. See `docs/TRIADIC_PRODUCT_USABILITY_02_C_LIVE_UNIVERSAL_COGNITION.md`.
