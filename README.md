# Triadic Brain

> [!IMPORTANT]
> **Public development alpha — no formal release.**
>
> This repository is publicly visible and cloneable. It is not a GitHub Release,
> published package, hosted service, production deployment, or truth/compliance
> certification. The installed default demonstration is a deterministic offline
> fixture and does not invoke a live model or the inherited Sophia/Atlas runtime.
>
> UVLM-controlled and otherwise licensable material is offered under MPL-2.0.
> Embedded Unicode UCD-derived data remains under Unicode-3.0. The internal
> rights ledger remains on HOLD for formal-release readiness and provenance
> review; that internal status does not revoke the license terms attached to
> files already made public.

Triadic Brain is a local-first governed AI review workbench. It keeps source
evidence, a candidate response, independent audit, bounded review posture, and
the human decision separate so fluent output cannot silently become authority.

| Current fact | Status |
| --- | --- |
| Repository source | Publicly available |
| Formal GitHub Release | None |
| Published Python package | None |
| GitHub Pages / hosted service | None |
| Default demo | Deterministic offline fixture |
| Live model/provider in default path | No |
| Persistent PMR memory | No |
| Human decision submission in root demo | Not yet |
| Formal public-release readiness | HOLD |

Start with [Public development status](PUBLIC_DEVELOPMENT_STATUS.md), then follow
the [operator runbook](docs/operator-runbook.md) or the
[investor demonstration](docs/investor-demo.md).

## What this public development alpha does

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
call a model provider, download a model, write memory, publish a package, deploy
a hosted service, create a formal release, or act for the reviewer. A receipt
records identity or process; it does not prove that a claim is true. Formal
release readiness remains on HOLD, and live-provider acceptance is absent.

## Install and try the offline route

Use Python 3.12 and an independently reviewed local wheel:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index --no-deps .\triadicbrain-0.1.0a0.dev4-py3-none-any.whl
.venv\Scripts\triadicbrain doctor
.venv\Scripts\triadicbrain investor-demo --output .\review-run --open-browser
```

The guided command creates the deterministic fixture, prints its status, and
starts the foreground loopback server. Browser opening is opt-in. Open only
`http://127.0.0.1:8765/review` (or the explicit loopback host and port you
selected), inspect `/status`, and stop with `Ctrl+C`. Installation and use do
not create formal-release, deployment, or package-publication authority.

## License, notices, and disclosure

- [MPL-2.0 text](LICENSE)
- [License scope and Unicode exception](LICENSE_SCOPE.md)
- [Project notice](NOTICE)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [AI-assistance disclosure](AI_ASSISTANCE_DISCLOSURE.md)
- [Contributor identities](CONTRIBUTORS.md)
- [Dependency and packaging boundary](DEPENDENCIES.md)

## Product documentation

- [Public development status](PUBLIC_DEVELOPMENT_STATUS.md)
- [Investor demonstration](docs/investor-demo.md)
- [Investor one-page](docs/investor-one-page.md)
- [Operator runbook](docs/operator-runbook.md)
- [Capability and claim-status matrix](docs/status-matrix.md)
- [Getting started](docs/getting-started.md)
- [Your first review](docs/first-review.md)
- [Output guide](docs/output-guide.md)
- [Safety and boundaries](docs/safety-and-boundaries.md)
- [Technical index](docs/technical/index.md)
- [Research index](docs/research/index.md)
