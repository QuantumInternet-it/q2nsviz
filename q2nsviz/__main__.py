# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

"""Entry point for ``python -m q2nsviz``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
