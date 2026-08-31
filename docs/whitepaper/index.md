# Triadic Brain: Local AI You Can Inspect Before You Trust

**Private alpha-staging whitepaper**  
**Public rights: HOLD · Authority effect: NONE**

MPL-2.0 is selected as the primary private-candidate license, while Unicode-3.0
applies to embedded Unicode data. This selection does not clear any of the 158
rights HOLD rows or authorize public release.

## The user problem

**[IMPLEMENTED]** A person reviewing AI output often receives one fluent block
of text without a durable boundary between the source, the generated proposal,
the checks performed on it, and the decision to use it. Triadic Brain addresses
that review problem by producing separate, checksum-bound artifacts. It does not
solve truth in general and does not turn fluency into evidence.

## Three roles, one human decision

**[IMPLEMENTED]** Sonya/Coherence binds a task to source evidence, quarantines
captured output, and creates a candidate packet. Sophia audits that immutable
candidate without generating or rewriting it. Atlas presents a bounded posture
without canonizing, publishing, deploying, or writing memory. The person remains
the decision-maker.

This separation matters because each role can fail visibly. If source scope is
wrong, the route can stop before candidate handling. If evidence links are
missing, the candidate remains held. If audit or posture artifacts disagree with
their inputs, their checksums expose the mismatch. No later component receives
permission merely because an earlier component produced a receipt.

## One deterministic fixture run

**[IMPLEMENTED]** The private alpha includes a synthetic contract fixture that
emits the roles in this public contract:

```text
task
  -> request envelope
  -> grounding bundle
  -> fixed fixture candidate packet
  -> Sophia-labeled fixture audit
  -> Atlas-labeled fixture posture
  -> pending human-review contract
  -> checksum-closed export
```

**[PROPOSED]** Each final candidate build must demonstrate the demo twice from
clean output directories and preserve the byte comparison in its review
handoff. The claim becomes build-specific `TESTED` only when those logs and
digests are present; this document alone is not that evidence. The root demo
does not invoke the inherited Coherence, Sophia, or Atlas implementations, so a
passing fixture replay is not full inherited-route integration evidence.

## Why the roles stay separate

**[IMPLEMENTED]** Sophia is forbidden to repair a candidate during audit,
because an unrecorded repair would erase what was actually evaluated. Atlas is
forbidden to canonize or act, because orientation is not authority. The human
decision is a separate artifact so a replay cannot silently overwrite it.

Failure receipts are part of the design. A clean stop at a failed boundary is
more informative than an apparently complete result assembled from missing or
incompatible evidence.

## What this bounded alpha implements

**[IMPLEMENTED]** The staged source contains inherited bounded task, grounding,
candidate, audit, posture, human-review, and sealing implementations plus a root
package facade. The root demo is a separately generated contract fixture: local,
deterministic, and non-authoritative, but not an invocation of those inherited
implementations. Doctor is read-only. Serve is foreground and loopback-only by
default.

**[DEFERRED]** It does not include model-provider invocation, model download,
PMR retention, federation, training, automatic publication, deployment, or
autonomous action.

## Evaluation evidence

**[PROPOSED]** OA-01 requires reproducible source and wheel builds, clean
installs, developer-checkout import exclusion, deterministic fixture replay,
contract and nonauthority tests, loopback security tests, casefold and wheel
boundary checks, resource parity, privacy scans, and documentation validation.
The exact review handoff records what ran, where it ran, and the first failed
gate if any.

**[DEFERRED]** A Windows CI definition is not Windows product acceptance. Live
local Ollama is not tested and requires separate human provider authorization.
Human usability and accessibility evidence are not created by fixture tests.

## Limits and nonclaims

**[IMPLEMENTED]** Candidate is not answer. Receipt is not truth. Audit is not a
rights grant. Posture is not canon. A checksum proves byte identity under a
declared algorithm, not correctness. No artifact produced here has authority to
write memory, publish, deploy, release, or act.

**[RESEARCH]** Advanced mathematics, GUFT, 432/Atlas, sacred-geometry,
telemetry-history, totality-assurance, and cognition-improvement hypotheses may
be studied separately. They are not ordinary-workflow capabilities or evidence
of scientific validity in this alpha.

## Roadmap and governance of change

**[PROPOSED]** The next meaningful steps are independent exact-hash review,
human rights attestation, verification of the selected license and notice
posture, clean Windows acceptance, and separately authorized
local-provider/usability studies.

**[IMPLEMENTED]** Candidate governance is identity-specific: source commit and
tree, projected paths and blobs, schemas, tests, build hashes, and human
decisions are recorded separately. A later change creates new evidence needs;
it does not inherit acceptance automatically.
