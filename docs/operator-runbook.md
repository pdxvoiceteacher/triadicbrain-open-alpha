
# Alpha operator runbook

**Supported posture:** public development alpha; no formal release
**Python:** CPython 3.12
**Default mode:** deterministic offline fixture
**Provider invocation:** none
**Authority effect:** NONE

## Install from a reviewed local wheel

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index --no-deps `
  .\triadicbrain-0.1.0a0.dev4-py3-none-any.whl
```

The UX-01 wheel hash is established only after the candidate is built and
reviewed.

## Install from the public source checkout

```powershell
git clone https://github.com/pdxvoiceteacher/triadicbrain-open-alpha.git
cd triadicbrain-open-alpha
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index --no-deps `
  --no-build-isolation .
```

A source checkout is development material, not a formal package release.

## Read-only readiness report

```powershell
.venv\Scripts\triadicbrain doctor
```

A healthy report must state:

```text
provider contacted:
false

network used:
false

repository/source posture:
public development

formal release:
false

package publication:
false

rights:
HOLD

public release eligible:
false
```

## Guided investor demonstration

```powershell
.venv\Scripts\triadicbrain investor-demo `
  --output .\review-run-investor `
  --open-browser
```

Use a new output path. Browser opening is opt-in.

## Manual demonstration

```powershell
.venv\Scripts\triadicbrain demo --output .\review-run-001
.venv\Scripts\triadicbrain serve --run-root .\review-run-001
```

Open only:

```text
http://127.0.0.1:8765/review
```

Stop with `Ctrl+C`.

## Read-only status endpoint

While the server is running:

```text
http://127.0.0.1:8765/status
```

It must return canonical JSON declaring the fixture mode and every unavailable
authority/capability boundary.

## Fixture artifact set

```text
source.txt
request_envelope.json
grounding_bundle.json
candidate_packet.json
sophia_audit.json
atlas_posture.json
human_review.json
run_manifest.json
SHA256SUMS.txt
```

The existing fixture artifact-set identity must remain:

```text
ed2ab14592d7c62a6e82658207680b56246f8c4126bbc0a8f94b3ae83d61202f
```

The fixture retains historical private-alpha identifiers inside its sealed
bytes. The review page must explain that those identifiers describe the frozen
fixture lineage, not the repository's current visibility.

## Manual verification

```powershell
Get-FileHash .\review-run-001\* -Algorithm SHA256
```

Compare the results with `run_manifest.json` and `SHA256SUMS.txt`.

Do not edit a sealed run and continue presenting it as the reviewed original.

## Common holds

### Output path exists

Choose a new directory. Do not silently overwrite prior evidence.

### Artifact identity mismatch

Preserve the directory for diagnosis and create a separate run.

### Non-loopback request refused

Use `127.0.0.1` or `::1`. Do not expose the server on a LAN or public
interface.

### Incompatible Python

Use CPython 3.12 for the reviewed route.

## Privacy

The default fixture is synthetic. The current root route is not authority to
process secrets, tax data, health data, client records, or private evidence.

## Current ceiling

Implemented:

- deterministic provider-free fixture;
- role separation;
- loopback review;
- reproducible packaging;
- public source and documentation;
- deeper fixed source task.

Not yet implemented in the ordinary root flow:

- arbitrary source/task intake;
- captured-candidate intake;
- decision submission;
- bounded repair;
- live provider;
- persistent memory;
- one-click installer;
- production deployment.
