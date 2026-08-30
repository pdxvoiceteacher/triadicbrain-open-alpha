"""Build a small deterministic, dependency-free documentation site."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


DOCS = [
    "README.md", "docs/index.md", "docs/getting-started.md", "docs/first-review.md",
    "docs/output-guide.md", "docs/safety-and-boundaries.md", "docs/roadmap.md",
    "docs/whitepaper/index.md", "docs/technical/index.md", "docs/research/index.md",
]


def render_markdown(text: str) -> str:
    output: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            output.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            output.append(html.escape(line) + "\n")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            output.append(f"<h{level}>{html.escape(heading.group(2))}</h{level}>")
        elif line.startswith("- "):
            output.append(f"<p>• {html.escape(line[2:])}</p>")
        elif line.strip():
            output.append(f"<p>{html.escape(line)}</p>")
    return "<!doctype html>\n<meta charset=\"utf-8\">\n" + "\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    inventory = []
    for name in DOCS:
        source = root / name
        if not source.is_file():
            raise SystemExit(f"missing documentation source: {name}")
        destination = args.output / ("index.html" if name == "README.md" else name.removesuffix(".md") + ".html")
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = render_markdown(source.read_text(encoding="utf-8")).encode("utf-8")
        destination.write_bytes(data)
        inventory.append({"source": name, "output": destination.relative_to(args.output).as_posix(), "bytes": len(data)})
    manifest = {"schema": "uvlm.oa01.documentation_build.v1", "status": "PASS", "files": inventory}
    (args.output / "documentation_build.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
