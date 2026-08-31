# Triadic Brain

> **Private RL-02 implementation candidate. Public distribution remains on
> HOLD.** The operative human decision selects MPL-2.0 for UVLM-controlled and
> otherwise licensable material, with Unicode-derived UCD data retained under
> Unicode License V3. Independent review is still required.

Triadic Brain helps a person inspect a source-grounded AI candidate before
deciding whether to trust or use it. Evidence binding, candidate generation,
independent audit, orientation, and the human decision remain separate so no
component quietly turns a candidate into an answer.

## What this private alpha does

**[IMPLEMENTED]** The root `triadicbrain` package exposes one bounded,
deterministic contract-fixture demonstration:

```text
task + request envelope + grounding bundle + candidate packet
     + Sophia audit + Atlas posture + human decision
     + checksum-closed export
```

`triadicbrain demo` runs the included deterministic fixture offline. It emits
fixed evidence, candidate, audit, posture, pending-human-review, and export
artifacts. It demonstrates an artifact contract; it does not invoke the
inherited live component route or a model provider. `triadicbrain doctor`
performs read-only local checks. `triadicbrain serve --run-root
<demo-directory>` starts a foreground, loopback-only review surface.

## What it does not do

It does not certify truth or legal compliance, claim production readiness,
call a model provider, download a model, write memory, publish, deploy, release,
or act for the reviewer. A receipt records identity or process; it does not
prove that a claim is true. Public release, package publication, and live
provider acceptance are not authorized by this candidate.

## Install and try the offline route

Use Python 3.12 and an independently reviewed local wheel:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index .\triadicbrain-0.1.0a0.dev3-py3-none-any.whl
.venv\Scripts\triadicbrain doctor
.venv\Scripts\triadicbrain demo --output .\review-run
.venv\Scripts\triadicbrain serve --run-root .\review-run
```

Open only `http://127.0.0.1:8765/review` (or the explicit loopback host and port
you selected). Stop the foreground process with `Ctrl+C`. Installation and use
do not grant release, deployment, or publication authority.

## License, notices, and disclosure

- [MPL-2.0 text](LICENSE)
- [License scope and Unicode exception](LICENSE_SCOPE.md)
- [Project notice](NOTICE)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [AI-assistance disclosure](AI_ASSISTANCE_DISCLOSURE.md)
- [Contributor identities](CONTRIBUTORS.md)
- [Dependency and packaging boundary](DEPENDENCIES.md)

## Product documentation

- [Getting started](docs/getting-started.md)
- [Your first review](docs/first-review.md)
- [Output guide](docs/output-guide.md)
- [Safety and boundaries](docs/safety-and-boundaries.md)
- [Technical index](docs/technical/index.md)
- [Research index](docs/research/index.md)
