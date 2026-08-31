# Notice implementation and review plan

**Status:** RL-02 implementation candidate assembled for independent review

**Public release:** HOLD
**Runtime authority effect:** NONE

## Implemented candidate surface

1. The exact official MPL-2.0 text is present as `LICENSE`.
2. `LICENSE_SCOPE.md` identifies the MPL scope, Unicode exception, and
   AI-assisted-rights boundary without narrowing MPL rights.
3. `NOTICE` attributes Thomas Prislac and Ultra Verba, Lux Mentis contributors
   and does not adopt Aggregation Station as a current rightsholder.
4. `CONTRIBUTORS.md` reconciles the two Thomas Git emails, the UVLM project
   identity, and the OA-01 local staging identity.
5. The six existing MPL-2.0 SPDX headers are preserved.
6. `THIRD_PARTY_NOTICES.md` identifies Unicode UCD 17.0.0
   `Default_Ignorable_Code_Point` provenance, exact source hash, exact license
   hash, and the six affected paths.
7. The exact Unicode License V3 bytes are present at
   `licenses/Unicode-3.0.txt` and are packaged with the distribution.
8. `AI_ASSISTANCE_DISCLOSURE.md` records the bounded human and automated roles.
9. `DEPENDENCIES.md` separates root, component, CI, and packaged boundaries.

## Independent review still required

The review must confirm exact hashes, unchanged range values and SPDX headers,
notice accuracy, contributor identity treatment, package metadata and members,
rights/lineage topology, deterministic builds, offline-demo stability, action
pins, and the no-provider/no-remote-mutation boundary. Every rights row remains
HOLD and public-release-ineligible until separate authority says otherwise.

This plan does not claim legal compliance, production readiness, or truth
certification and does not authorize release or publication.
