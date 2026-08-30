# Sophia — Independent Governance for the UVLM Triadic Cognition Core

Sophia is the independent governance and claim-boundary layer of the UVLM Triadic Cognition Core. It audits provenance-bound candidate and evidence artifacts; it does not generate candidates or determine truth.

## Architecture quick lock

- **Canonical architecture:** `UVLM-TCC-ADR-001`
- **Canonical repository:** `pdxvoiceteacher/CoherenceLattice`
- **Local adoption document:** [`docs/architecture/UVLM_TCC_ADR_001_SOPHIA_ADOPTION.md`](docs/architecture/UVLM_TCC_ADR_001_SOPHIA_ADOPTION.md)
- **Provenance audit apprentice profile:** [`docs/provenance/README.md`](docs/provenance/README.md)
- **Deterministic audit explanation:** [`docs/TRIADIC_PRODUCT_USABILITY_VERTICAL_SLICE_02_C_SOPHIA_EXPLANATION_01.md`](docs/TRIADIC_PRODUCT_USABILITY_VERTICAL_SLICE_02_C_SOPHIA_EXPLANATION_01.md)
- **Provider candidate v2 compatibility:** [`docs/TRIADIC_PRODUCT_USABILITY_02_C_PROVIDER_CANDIDATE_V2.md`](docs/TRIADIC_PRODUCT_USABILITY_02_C_PROVIDER_CANDIDATE_V2.md)

**Model-result flow**

```text
Ollama or approved local model → Sonya → CoherenceLattice → Sophia → Atlas/Publisher → Human
```

**Invocation clarification**

```text
Sonya → model backend → Sonya
```

Sophia does not call the model. It does not consume raw Ollama output.

## Sophia's role

Sophia provides independent governance: source-grounding challenge, claim-support and counterevidence review, overclaim and evidence-mismatch detection, uncertainty and proportionality review, authority-ceiling enforcement, stable reason codes, bounded dispositions, escalation posture, and human-review routing.

Accepted inputs are versioned, provenance-bound bridge artifacts, including canonical request and grounding-bundle identities, Sonya candidate packets, CoherenceLattice claim/evidence maps and formal measurements, repository identity, parent packet hashes, logical run IDs, authority ceilings, and separately submitted Atlas/PMR prior candidates. Hashes and schemas support integrity checking; they do not establish truth.

Bounded outputs are governance dispositions, reason codes, escalation posture, structured decision evidence, and human-review routing. They are not legal verdicts, guilt determinations, or final decisions.

## Two separately governed lanes

### Forward candidate-governance lane

The forward candidate lane is `CoherenceLattice → Sophia → Atlas`. In the complete result flow, Sonya supplies a candidate through CoherenceLattice's evidence-processing boundary before Sophia audits it. Sophia may verify references, hashes, run identity, and repository role, then challenge unsupported claims and route bounded governance guidance.

### Prior-admissibility feedback lane

The bounded prior-admissibility feedback lane may involve `Atlas/PMR candidate → Sophia review`. It is a separately authorized review of prior provenance, revocation, expiry, context compatibility, and evidence class. Sophia may recommend admit, hold, quarantine, reject, or human review.

This does **not** mean Atlas automatically precedes Sophia in every cognition run. Neither lane authorizes memory write, canonization, silent prior injection, model training, publication, or truth certification.

## Authority boundaries and human final authority

Sophia cannot call Ollama or another model, generate the candidate it audits, rewrite source evidence, silently alter CoherenceLattice measurements, self-approve a candidate, write Atlas memory, canonize, publish, certify truth, deploy, or authorize final human action.

Sophia's disposition is governance guidance and routing posture. Human final authority remains binding for memory, publication, deployment, correction, revocation, and final action.

## Current runtime entry points

Install the Python package and development dependencies from the repository root:

```bash
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

Run the deterministic local-audit adapter against a bridge-artifact directory:

```bash
python -m sophia.local_audit.local_review_runtime_v0 --bridge-root <bridge-dir> --out <output-dir>
```

Audit a private totality run from canonical, file-only bridge artifacts:

```bash
python -m sophia.triadic.totality_audit --run-root <absolute-run-dir>
```

Use `--output <absolute-path>/sophia_audit_packet.json` when the input run is
already sealed and the audit packet must be written outside it. The route emits
a deterministic PASS, HOLD, or REJECT packet even when an upstream contract is
invalid. It never invokes a model or rewrites the request, source, candidate, or
CoherenceLattice artifacts.

The totality route audits the immutable `tel_audit_prefix.jsonl`, not the
post-audit `tel_events.jsonl` that a route finalizer may extend. Raw model output
is never a Sophia input. Quarantine is checked through the canonical Sonya
receipt and Coherence's separately bound, raw-free verification receipt. The
optional `pmr_consent.json` parent is represented with null digests when absent;
`pmr_receipt.json` is always required and is accepted only as a no-network,
no-training reference-lifecycle receipt with a persistent byte count of zero.

The FastAPI application is `sophia.api.server:app`; bridge resolution requires `TRIADIC_BRIDGE_ROOT`, `COHERENCE_LATTICE_ROOT`, or an available sibling bridge path.

## Tests and checks

```bash
PYTHONPATH=python/src python -m pytest tests/test_uvlm_tcc_adr_001_sophia_adoption.py
PYTHONPATH=python/src python -m pytest tests/test_local_review_audit_adapter.py
TRIADIC_BRIDGE_ROOT="$PWD/bridge" PYTHONPATH=python/src python -m pytest python/tests/test_sophia_api_server_import_smoke.py python/tests/test_sophia_api_init_import_smoke.py
PYTHONPATH=python/src python -m pytest tests/test_totality_audit.py
python -m compileall -q python tools sophia sophia-core
```

## Implementation status

| Surface | Status |
| --- | --- |
| Local audit runtime and Sophia API server | implemented |
| Governance packet handling, memory-disposition admissibility, and UCC routing | implemented_in_parts |
| UVLM-TCC-ADR-001 candidate-audit contract | implemented_in_parts |
| Captured-Sonya-candidate replay | source_present_not_live_accepted |
| Separate-process three-repository route, live Ollama use, Atlas/PMR write, publication, and full cognition-engine completion | not_authorized |

The complete live triadic route is not green. See the [Sophia adoption document](docs/architecture/UVLM_TCC_ADR_001_SOPHIA_ADOPTION.md) for ownership, telemetry/TEL boundaries, and the complete conservative status matrix.
