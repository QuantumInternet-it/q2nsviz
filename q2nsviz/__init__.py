# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

"""Q2NSViz -- desktop trace visualizer for Q2NS quantum network simulations.

Importing this package pulls in the replay engine only, and never Qt: a script
can reconstruct network state without a GUI, or even a display.  The PyQt6
interface lives in the ``q2nsviz.ui`` subpackage and is imported on demand.

    from q2nsviz import SimulationStateManager

    sm = SimulationStateManager()
    sm.load_events("example_traces/q2nsviz-repeater-swap-example.json")
    snap = sm.snapshot_at(4000)
"""

from .logic import Channel, ClassicalBit, EventFileParser, Node, Qubit, SimulationStateManager, Snapshot, UnionFind

__all__ = [
    "Channel",
    "ClassicalBit",
    "EventFileParser",
    "Node",
    "Qubit",
    "SimulationStateManager",
    "Snapshot",
    "UnionFind",
]
