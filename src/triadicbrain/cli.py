"""Console entry point for the private alpha."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .contracts import ContractError, canonical_json
from .demo import run_demo
from .doctor import doctor_report
from .serve import serve_review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triadicbrain")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="print a read-only local readiness report")
    demo = commands.add_parser("demo", help="run the deterministic offline fixture")
    demo.add_argument("--output", required=True, type=Path)
    serve = commands.add_parser("serve", help="serve a completed demo for local review")
    serve.add_argument("--run-root", required=True, type=Path)
    serve.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor_report()
            sys.stdout.buffer.write(canonical_json(result))
            return 0 if result["python"]["compatible"] else 3
        if args.command == "demo":
            result = run_demo(args.output.resolve(strict=False))
            sys.stdout.buffer.write(canonical_json(result))
            return 0
        serve_review(args.run_root.resolve(strict=True), args.host, args.port)
        return 0
    except (ContractError, FileNotFoundError, OSError) as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 3

