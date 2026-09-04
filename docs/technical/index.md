# Technical index

**Public development technical material · No formal release · Rights HOLD · Authority effect NONE**

This index describes the bounded public-development contract and source
projection. It does not endorse every historical component document present for
lineage or package support.

## Canonical contract

**[IMPLEMENTED]** The public contract is:

```text
task
+ request envelope
+ grounding bundle
+ candidate packet
+ Sophia audit
+ Atlas posture
+ human decision
+ checksum-closed export
```

The grounding bundle is the evidence substrate. Compatibility aliases, where
retained, remain behind this boundary and are not an alternative public API.

The root demo emits a deterministic fixture representation of this contract. It
does not import or invoke the inherited Coherence, Sophia, or Atlas route. Keep
fixture reproducibility evidence separate from inherited-route integration
evidence.

## Ownership and invariants

| Stage | Owner | Required invariant |
| --- | --- | --- |
| Intake, admission, evidence, candidate, seal | Sonya/Coherence | Candidate remains a proposal bound to declared evidence |
| Audit | Sophia | Reads immutable candidate artifacts; never generates or rewrites |
| Orientation and human-review presentation | Atlas | Never canonizes, publishes, deploys, writes memory, or increases authority |
| Decision | Human reviewer | Remains controlling and is not overwritten by replay |

Every stage preserves `authority_effect=none`. The root fixture path performs no
PMR write and makes no provider call. The broader inherited route retains
quarantine and PMR no-write contracts, but those implementations and extra
artifacts are not silently represented as root-demo output.

## Schemas and packaged resources

**[IMPLEMENTED]** Versioned request-envelope, grounding-bundle, candidate-packet,
audit, TEL, adapter, quarantine, and PMR consent schemas are present in the
projection. The root package must include the schemas it uses and verify
source/package resource parity. The final wheel-member inventory and parity log
in the candidate handoff are the build-specific evidence.

## Validation surfaces

**[PROPOSED]** A final public-development candidate is expected to preserve raw
logs for:

- two source-package and two wheel builds;
- clean source and wheel installs;
- developer-checkout import exclusion;
- doctor, demo, contract, nonauthority, and role-separation tests;
- human-decision non-overwrite and loopback Host/Origin/CSRF tests;
- casefold, wheel-member, package-resource, privacy, secret, and path checks;
- documentation rendering and internal-link validation.

No required skip is green. The final review handoff and remote CI evidence, not
a configuration file or this index, state which checks actually ran.

## Inherited architecture references

The following exact-source files provide focused architectural context and
remain rights-held:

- `components/CoherenceLattice/docs/architecture/UVLM_TRIADIC_COGNITION_CORE_V1.md`
- `components/Sophia/docs/architecture/UVLM_TCC_ADR_001_SOPHIA_ADOPTION.md`
- `components/uvlm-publications/docs/architecture/UVLM_TCC_ADR_001_ATLAS_PUBLISHER_ADOPTION.md`

Broader component READMEs may mention surfaces excluded from the root route.
Treat those mentions as historical context, not current root-package claims.
