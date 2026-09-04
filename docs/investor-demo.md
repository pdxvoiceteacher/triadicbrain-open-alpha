
# Investor demonstration

## The one-sentence explanation

> Triadic Brain is a local-first governed AI review workbench that keeps the
> model proposal, source evidence, independent audit, review posture, and human
> decision separate so fluent output cannot silently become authority.

## What this demonstration is

The default demonstration is a deterministic offline fixture. It is designed to
show the artifact contract and human-authority boundary reliably.

It does not contact a model, run a hosted service, write memory, or certify that
the candidate is true.

## Before the meeting

Use Windows 11 and CPython 3.12.

For the strongest reproducibility, use an exact wheel produced from the reviewed
source. The RL-02 Repair01 wheel identity was:

```text
3da8614355e40462f710b63078988bcb7c2f452b669014b22e2982e9501eee5a
```

The current UX-01 candidate will produce a new wheel identity after review.

Use only the supplied synthetic fixture. Do not substitute tax records, health
records, customer data, credentials, or private source material.

## Eight-minute guided route

From an installed reviewed wheel:

```powershell
triadicbrain investor-demo `
  --output .\review-run-investor `
  --host 127.0.0.1 `
  --port 8765 `
  --open-browser
```

Without browser opening:

```powershell
triadicbrain investor-demo `
  --output .\review-run-investor
```

The browser option must be explicit. The server stays in the foreground and
stops with `Ctrl+C`.

## Manual route

```powershell
triadicbrain doctor
triadicbrain demo --output .\review-run-investor
triadicbrain serve --run-root .\review-run-investor
```

Open:

```text
http://127.0.0.1:8765/review
```

## What to point out

### Mode banner

The first block must say:

```text
MODE:
DETERMINISTIC OFFLINE FIXTURE

LIVE MODEL INVOKED:
NO

INHERITED SOPHIA INVOKED:
NO

INHERITED ATLAS INVOKED:
NO

HUMAN DECISION SUBMISSION:
NOT AVAILABLE IN THIS ROOT MODE
```

### Candidate

> This is a proposal. It is not a final answer and cannot authorize itself.

### Evidence

> The source and grounding artifacts show what material the candidate says it
> relies on. A hash proves byte identity, not truth.

### Sophia role

> Sophia is the independent audit role. In this root fixture, the artifact is a
> fixed contract demonstration. The deeper source route executes the inherited
> deterministic Sophia audit.

### Atlas role

> Atlas helps orient the reviewer but cannot canonize, publish, deploy, write
> memory, or decide for the person. The root demo uses a fixed Atlas role
> fixture.

### Human boundary

> The root page leaves the decision pending. That is a visible product gap. The
> next product patch brings bounded approve, hold, reject, and repair receipts
> into the ordinary path.

## Ninety-second talk track

AI systems can produce persuasive text without preserving a dependable chain
from source to claim, policy, audit, and human decision. Triadic Brain separates
those responsibilities.

Sonya is the model and tool boundary. CoherenceLattice binds the request,
source, candidate, and evidence. Sophia audits without rewriting the candidate.
Atlas presents a bounded posture. The human remains the decision authority.
Telemetry and receipts preserve observable process without pretending to reveal
hidden chain-of-thought.

This demonstration is the deterministic offline alpha contract. It proves that
the evidence and authority boundaries can be packaged, reproduced, inspected,
and tested across Windows and Linux. It does not call a live model or certify
truth. The next milestone is an ordinary-user route for a real local document,
task, captured candidate, bounded human decision, and verifiable export.

## Claims you may make

- The repository contains a working provider-free fixture route.
- The role and authority boundaries are explicit.
- The reviewed source passed Linux and Windows Python 3.12 CI.
- The wheel and sdist were reproducible in the reviewed build.
- The local review server enforces loopback Host, Origin, and CSRF boundaries.
- The architecture includes a deeper fixed substantive task.
- The project publishes explicit license, third-party, contributor, and
  AI-assistance disclosures.

## Claims you must not make

- The system certifies truth or compliance.
- The default demo invokes a live model, Sophia, or Atlas.
- PMR is already an active persistent memory.
- Every provider is already compatible.
- The project is production-secure or deployment-ready.
- The coherence-compression hypothesis is proven.
- The public repository is a formal release.
- The current alpha accepts arbitrary investor documents through the root UI.

## Technical-diligence route

The source checkout contains:

```powershell
integration\tools\RUN_PRODUCT_TASK_01.cmd `
  C:\UVLM_Demos\TB_PRODUCT_TASK_01

integration\tools\START_THOMAS_REVIEW.cmd `
  C:\UVLM_Demos\TB_PRODUCT_TASK_01
```

This uses one authenticated source and one captured candidate to exercise a
deeper governed route. Present it as fixed and reproducible—not as a general
live-model product.

## Closing line

> The current alpha proves the governed receipt architecture. The next
> investment milestone is the ordinary-user document-review vertical slice and
> a measured study of whether it helps people identify unsupported claims more
> accurately and with less cognitive burden.
