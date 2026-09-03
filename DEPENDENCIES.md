# Dependency and packaging boundary

## Root distribution

The root `triadicbrain` project keeps `dependencies = []`. Its wheel metadata
contains no `Requires-Dist` field, and the dependency-free build backend uses
only the Python standard library. The wheel packages selected UVLM source plus
license metadata; it does not vendor the CI environment.

## Component declarations

The projected component `pyproject.toml` files retain their own declarations,
including FastAPI, Uvicorn, Pydantic, jsonschema, requests, NumPy,
python-multipart, pytest, Hypothesis, HTTPX, pandas, scikit-learn, and networkx
where applicable. Those declarations describe component development or runtime
contexts; they are not copied into root `Requires-Dist` and are not a statement
that every component route is accepted or active.

## Public-development CI tooling

`.github/requirements-private-alpha-ci.txt` retains its historical filename and
pins the public-development acceptance tools. They are installed only into the
CI/test environment and are not bundled in the root wheel. The workflow uses
only GitHub-owned actions, pinned to reviewed 40-hex commits:

```text
actions/checkout      11d5960a326750d5838078e36cf38b85af677262
actions/setup-python  a26af69be951a213d495a4c3e4e4022e16d87065
actions/upload-artifact ea165f8d65b6e75b540449e92b4886f43607fa02
```

Dependency names, availability, and test use do not transfer ownership or
license terms. Unicode-derived UCD data has a separate notice and license; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
