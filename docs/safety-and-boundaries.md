# Safety and boundaries

**[IMPLEMENTED] Enforced product boundaries · [DEFERRED] Provider and formal-release acceptance**

## Authority

Every root public-development command and artifact ends with
`authority_effect=none`. Capability is not authorization. A candidate, audit,
posture, receipt, manifest, checksum,
test result, or review decision cannot independently authorize memory,
publication, deployment, release, or action.

## Role separation

- Sonya/Coherence accepts bounded inputs, binds evidence, quarantines captured
  output, and emits a candidate packet.
- Sophia audits the immutable candidate. It cannot generate or rewrite it.
- Atlas orients a reviewer. It cannot canonize, publish, deploy, write memory, or
  decide for the person.
- The human decision is controlling for the stated review scope.

## Network and provider boundary

The deterministic demo makes no network or provider call. The review server is
foreground-only and loopback-only by default; non-loopback Host and Origin
conditions are rejected. The public-development candidate does not authorize
Ollama or another provider, model download, daemon startup, federation, or a
remote connection.

```text
LIVE LOCAL PROVIDER:
NOT_TESTED_REQUIRES_SEPARATE_HUMAN_PROVIDER_AUTHORIZATION
```

Doctor may make a read-only local observation about optional Ollama availability.
Discovery is not invocation and is not acceptance evidence.

## Data and memory boundary

The fixture is synthetic. Do not introduce credentials, personal records,
private source documents, model caches, or unapproved third-party material.
The root demo does not write memory or emit a PMR retention artifact. The
broader inherited route contains a PMR no-write contract; PMR retention remains
separately authorized, consented, and revocable work.

## Product and evidence boundary

- Candidate is not answer.
- Receipt or checksum is identity/process evidence, not truth.
- Structural metrics are not proof of cognition, safety, or correctness.
- Missing evidence never grants permission.
- A skipped required test is not green.
- A Windows workflow definition is not Windows product acceptance.

## Rights and release boundary

This repository is publicly visible and cloneable development source. MPL-2.0
applies to UVLM-controlled and otherwise licensable material, and Unicode-3.0
applies to the embedded Unicode data. Public visibility does not clear the 166
rights rows: all remain `public_status=HOLD` for provenance and formal-release
review. No formal GitHub Release, package publication, Pages site, hosted
service, production deployment, or provider acceptance has been created. The
internal HOLD does not revoke or narrow license terms attached to public files.
