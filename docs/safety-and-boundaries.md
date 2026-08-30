# Safety and boundaries

**[IMPLEMENTED] Enforced product boundaries · [DEFERRED] Provider and public-release acceptance**

## Authority

Every OA-01 command and artifact ends with `authority_effect=none`. Capability is
not authorization. A candidate, audit, posture, receipt, manifest, checksum,
test result, or private review decision cannot independently authorize memory,
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
conditions are rejected. OA-01 does not authorize Ollama or another provider,
model download, daemon startup, federation, or a remote connection.

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

This repository is a private staging projection. Inherited and OA-01-generated
files remain `public_status=HOLD` until exact-hash human rights attestation,
third-party/notice closure, and an outbound-license decision are complete.
`LICENSE_NOT_YET_SELECTED.md` grants no rights. No GitHub remote, push,
publication, public release, private release, or deployment is authorized by
OA-01.
