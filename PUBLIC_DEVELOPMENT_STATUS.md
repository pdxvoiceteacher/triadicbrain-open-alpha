
# Public development status

**Observed:** September 3, 2026
**Repository:** `pdxvoiceteacher/triadicbrain-open-alpha`
**Status:** public development alpha; no formal release
**Authority effect:** NONE

## Exact current source

```text
main commit:
82f819f4f5491f5daffb510c0c6ab6a7328dd6e6

main tree:
a612d2f58a8e8f2a53e06ec3a61ae1675068870c

merge parents:
b278378f5add312aa8fb81a6cc1e0dc5fccc49aa
ef9d70bf0ca2af8a0b0ec344047a33e0d50c601d

merged pull request:
#2

pre-merge pull-request workflow:
33419890871 — SUCCESS

post-merge push workflow:
33423783473 — SUCCESS
```

The repository is publicly visible and cloneable. No GitHub Release exists,
no Python package has been published, and GitHub Pages is not configured.

## What is implemented and tested

- Deterministic offline root demo with nine checksum-closed artifacts.
- Separate request, source/grounding, candidate, audit, posture, human-review,
  manifest, and checksum roles.
- Foreground loopback-only review server.
- Host, Origin, and CSRF refusal checks.
- Deterministic wheel and source-distribution builds.
- Clean offline wheel installation.
- Windows and Linux Python 3.12 GitHub CI.
- MPL-2.0 plus Unicode-3.0 distribution metadata and notices.
- A deeper fixed substantive task in the source checkout.

Exact post-merge identities:

```text
wheel:
3da8614355e40462f710b63078988bcb7c2f452b669014b22e2982e9501eee5a

sdist:
7acca7b5ce47ffcaed56e27d4bf2f97ee7190d5bb894bed22a70f7e346f777db

offline demo:
ed2ab14592d7c62a6e82658207680b56246f8c4126bbc0a8f94b3ae83d61202f

source inventory:
90a2412714ad6be065afd14157cd3c41b81eee6bccd6f710916ed29c53b9310d
```

## What the default demo does not do

- It does not invoke a model or provider.
- It does not invoke the inherited Sophia or Atlas runtime; it uses fixed
  role-labeled fixture artifacts.
- It does not accept an arbitrary user document through the installed root
  command.
- It does not submit a human decision.
- It does not write PMR memory.
- It does not publish, deploy, or act for the reviewer.
- It does not certify truth, safety, or legal compliance.

## Rights and release language

The repository's public visibility means source availability is already public.
The phrase “no formal release” means:

```text
GitHub Release:
none

published package:
none

Pages / hosted application:
none

release-readiness authorization:
not completed
```

The internal rights matrix remains a fail-closed provenance and formal-release
readiness record. It must not be described as withdrawing the MPL-2.0 or
Unicode-3.0 terms attached to public files.

## Next product milestone

The next ordinary-user capability is:

```text
user-selected local text or Markdown
+ user-defined task
+ pasted/captured candidate
→ grounding
→ claim/evidence review
→ Sophia audit
→ Atlas posture
→ human decision
→ verifiable export
```

Live-provider integration and persistent memory remain later, separately
authorized gates.
