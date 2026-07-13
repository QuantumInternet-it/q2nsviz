#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

import argparse
import logging
import sys

from .ui.window import main as launch_gui


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="q2nsviz", description="Launch the Quantum Network Visualizer desktop viewer."
    )
    parser.add_argument(
        "trace_file", nargs="?", help="Optional path to a .json or .ndjson trace file to load on startup."
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python log verbosity for the viewer process.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s [%(name)s] %(message)s")
    return launch_gui(args.trace_file)


if __name__ == "__main__":
    sys.exit(main())
