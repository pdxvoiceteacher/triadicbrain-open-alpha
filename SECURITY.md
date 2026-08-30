# Security policy for private alpha staging

## Supported status

This is a private, unreleased, pre-1.0 staging candidate. There is no public
support or security-update commitment, no authorized deployment, and no
provider acceptance. Public distribution remains on hold.

## Reporting a security concern

Report concerns privately to the repository owner through the already approved
private review channel. Do not open a public issue, upload sensitive artifacts,
or create a remote solely to report an OA-01 finding. Include:

- the exact candidate commit/tree and artifact SHA-256;
- affected command, path, and minimal reproduction;
- expected and observed boundary;
- whether credentials, personal records, or private source may be present;
- a redacted log where possible.

Do not include plaintext secrets, personal records, model caches, or unapproved
private documents. Preserve original evidence securely and share it only after
the owner approves the exact channel and recipients.

## Security boundaries

- `triadicbrain demo` is offline and uses a synthetic deterministic fixture.
- `triadicbrain serve` is foreground and loopback-only by default and must reject
  non-loopback Host/Origin conditions.
- OA-01 does not authorize provider calls, model downloads, remote binding,
  daemon installation, PATH or registry changes, memory writes, publication,
  deployment, or release.
- `triadicbrain doctor` is observational and must not mutate the machine.
- A successful test, receipt, or checksum does not establish safety or truth.

If a boundary appears violated, stop use, preserve the exact evidence, and hold
the candidate for human review. Authority effect remains none.

