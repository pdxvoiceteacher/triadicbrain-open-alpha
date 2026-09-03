"""Console entry point for the public development alpha."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .contracts import ContractError, canonical_json
from .demo import run_demo
from .doctor import doctor_report
from .serve import serve_review


INVESTOR_STATUS_BLOCK = """MODE:
DETERMINISTIC OFFLINE FIXTURE

LIVE MODEL INVOKED:
NO

INHERITED SOPHIA INVOKED:
NO

INHERITED ATLAS INVOKED:
NO

HUMAN DECISION SUBMISSION:
NOT AVAILABLE IN THIS ROOT MODE

REPOSITORY SOURCE:
PUBLIC DEVELOPMENT

FORMAL RELEASE:
NONE"""


def _investor_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 1 through 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be from 1 through 65535")
    return port


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
    investor = commands.add_parser(
        "investor-demo",
        help="run and serve the truthful deterministic investor fixture",
    )
    investor.add_argument("--output", required=True, type=Path)
    investor.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    investor.add_argument("--port", type=_investor_port, default=8765)
    investor.add_argument("--open-browser", action="store_true")
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
        if args.command == "investor-demo":
            doctor = doctor_report()
            if not doctor["python"]["compatible"]:
                raise ContractError("Python runtime is outside the supported doctor range")
            output = args.output.resolve(strict=False)
            result = run_demo(output)
            display_host = f"[{args.host}]" if args.host == "::1" else args.host
            status = (
                f"{INVESTOR_STATUS_BLOCK}\n\n"
                f"OUTPUT DIRECTORY:\n{output}\n\n"
                f"ARTIFACT SET SHA-256:\n{result['artifact_set_sha256']}\n\n"
                f"REVIEW URL:\nhttp://{display_host}:{args.port}/review\n"
            )
            sys.stdout.write(status)
            sys.stdout.flush()
            serve_review(
                output.resolve(strict=True),
                args.host,
                args.port,
                open_browser=args.open_browser,
            )
            return 0
        serve_review(args.run_root.resolve(strict=True), args.host, args.port)
        return 0
    except (ContractError, FileNotFoundError, OSError) as exc:
        print(f"HOLD: {exc}", file=sys.stderr)
        return 3
