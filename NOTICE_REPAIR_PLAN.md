# Notice repair plan

**Status: OPEN · Public release: HOLD · Authority effect: NONE**

This plan records notice work without changing inherited source notices or
selecting a license.

## Findings to reconcile

1. The authenticated source root README contains an all-rights-reserved notice
   naming Thomas Prislac and Aggregation Station.
2. Six inherited `coherence.totality` source files contain MPL-2.0 SPDX
   identifiers and a Thomas Prislac / UVLM contributors copyright line.
3. The inherited CoherenceLattice README describes original work by
   UVLM/Prislac and collaborators and mentions Mathlib and standard toolchains,
   but the private projection does not yet have a complete contributor,
   dependency, permission, or notice inventory.
4. OA-01 generated files are AI-assisted and require an approved disclosure and
   human confirmation of the rights posture.
5. No project-wide outbound license has been selected.

These observations may coexist for private evidence review, but they are not a
resolved public licensing posture.

## Required repair sequence

1. Freeze the exact candidate commit, tree, source ZIP, sdist, and wheel hashes.
2. Review every row in `RIGHTS_EVIDENCE_MATRIX.csv` against projection lineage.
3. Confirm the correct rights holder and contributor for each inherited file;
   reclassify Group A rows to B or C where evidence requires it.
4. Identify copied excerpts, vendored material, schema-derived text, assets, and
   all runtime/build/test dependencies; collect their license and notice texts
   where inclusion or distribution requires them.
5. Resolve the six file-level MPL-2.0 SPDX notices without deleting or weakening
   them. Determine whether they are authorized, whether source-form obligations
   apply, and how they interact with the broader candidate.
6. Approve exact AI-assistance disclosure language for Group D files.
7. Select an outbound license only through a separately signed human decision.
8. Generate `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES` only after steps 1–7,
   and validate their wheel/sdist inclusion and hash identity.
9. Obtain exact-hash public-alpha authorization separately from any private push.

## Current non-action

Do not add a generic license text, remove inherited SPDX lines, infer permission
from Git history, or treat dependency availability as redistribution authority.
`LICENSE_NOT_YET_SELECTED.md` remains the only root license-status file in this
private candidate and grants no rights.

