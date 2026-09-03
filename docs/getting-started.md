# Getting started

**[IMPLEMENTED] Public-development, offline fixture path**
**Formal release: NONE · Rights: HOLD · Authority effect: NONE**

This guide uses the public development candidate and its deterministic contract
fixture. The demo does not invoke the inherited Coherence/Sophia/Atlas route or
a model provider. Public source availability is not a formal GitHub Release,
published package, hosted service, or production deployment.

## Prerequisites

- Python 3.12.
- A clean directory you control.
- An independently reviewed local `triadicbrain-0.1.0a0.dev4-py3-none-any.whl`.
- No Ollama installation, model download, network service, or developer checkout
  is required for the fixture demo.

## Install the wheel

On PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --no-index --no-deps .\triadicbrain-0.1.0a0.dev4-py3-none-any.whl
```

On a POSIX shell:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./triadicbrain-0.1.0a0.dev4-py3-none-any.whl
```

`--no-index` keeps this installation offline. The wheel includes the bounded
inherited package closure but declares no dependency download; the root fixture
facade itself uses the Python standard library. This does not authorize broader
component services. If installation differs, stop and use the independently
reviewed candidate instructions; do not silently download a replacement
dependency as evidence for this exact candidate.

## Run the read-only doctor

```powershell
.venv\Scripts\triadicbrain doctor
```

Doctor reports Python and package compatibility, packaged-resource integrity,
loopback readiness, optional local Ollama discovery, and the rights/network
posture. It must not start a daemon, contact a non-loopback host, download a
model, edit PATH or the registry, or change the machine.

Optional Ollama discovery is a local observation only. It is not a provider
test, and this public-development route does not authorize invoking Ollama.

## Run the deterministic demo

```powershell
.venv\Scripts\triadicbrain demo --output .\review-run
```

Choose a new or empty output directory. The demo uses packaged fixture bytes,
makes no provider or network call, and writes the contract-demonstration
artifacts described in the [output guide](output-guide.md). Repeat the command
with a second empty directory to compare deterministic output bytes. Passing
that comparison is not evidence that the inherited product route was invoked.

## Run the guided investor demonstration

```powershell
.venv\Scripts\triadicbrain investor-demo --output .\review-run-investor --open-browser
```

Use a new output path. The command runs the same read-only doctor checks,
creates the deterministic fixture, prints a concise status block, and starts
the foreground loopback server. Browser opening occurs only when
`--open-browser` is present. See the [investor demonstration](investor-demo.md)
and [operator runbook](operator-runbook.md).

## Start the local review surface manually

```powershell
.venv\Scripts\triadicbrain serve --run-root .\review-run
```

The server runs in the foreground and binds only to a loopback address by
default. Open `http://127.0.0.1:8765/review`, inspect the canonical read-only
`/status` endpoint, review the fixture, and press `Ctrl+C` to stop. Requests
with non-loopback Host or Origin conditions are refused.

The root interface is read-only: it does not submit a human decision, publish a
package, deploy, write memory, or make the decision for you. Continue with
[Your first review](first-review.md).
