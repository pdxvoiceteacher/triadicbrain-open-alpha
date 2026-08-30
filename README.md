# Triadic Brain

> **Private alpha-staging candidate. Public distribution is on HOLD.** No
> outbound license has been selected, no provider acceptance is claimed, and
> every command in this candidate has `authority_effect=none`.

Triadic Brain helps a person inspect a source-grounded AI candidate before
deciding whether to trust or use it. It keeps evidence binding, candidate
generation, independent audit, orientation, and the human decision in separate
artifacts so that no component quietly turns a candidate into an answer.

## What this private alpha does

**[IMPLEMENTED]** The root `triadicbrain` package exposes one bounded
deterministic contract-fixture demonstration:

```text
task + request envelope + grounding bundle + candidate packet
     + Sophia audit + Atlas posture + human decision
     + checksum-closed export
```

`triadicbrain demo` runs the included deterministic fixture offline. It binds
fixture evidence and emits fixed candidate, Sophia-labeled audit, Atlas-labeled
posture, and pending human-review artifacts. It demonstrates the public artifact
contract; it does **not** invoke the inherited Coherence, Sophia, or Atlas
implementation route and is not live-component or provider acceptance.
`triadicbrain doctor` performs read-only local checks.
`triadicbrain serve --run-root <demo-directory>` starts a foreground,
loopback-only review surface.

## What it does not do

It does not certify truth, call Ollama or any other model provider, download a
model, write memory, publish, deploy, release, or act for the reviewer. A receipt
records identity or process; it does not prove that a claim is true. Live local
provider acceptance, Windows product acceptance, and public-release rights are
not established by this staging candidate.

## Install and try the offline route

Use Python 3.12 and the supplied private wheel in a clean virtual environment:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index .\triadicbrain-0.1.0a0.dev1-py3-none-any.whl
.venv\Scripts\triadicbrain doctor
.venv\Scripts\triadicbrain demo --output .\review-run
.venv\Scripts\triadicbrain serve --run-root .\review-run
```

Open only `http://127.0.0.1:8765/review` (or the explicit loopback host and port
you selected). Stop the foreground process with `Ctrl+C`. Installation and use
do not grant redistribution rights.

## Read next

- [Getting started](docs/getting-started.md)
- [Your first review](docs/first-review.md)
- [Output guide](docs/output-guide.md)
- [Safety and boundaries](docs/safety-and-boundaries.md)
- [Triadic Brain: Local AI You Can Inspect Before You Trust](docs/whitepaper/index.md)
- [Technical index](docs/technical/index.md)
- [Research index](docs/research/index.md)
- [Rights and license status](LICENSE_NOT_YET_SELECTED.md)
