# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations


def make_two_node_events(*, with_entangle: bool = False) -> list[dict]:
    """Return a minimal valid event list: Alice and Bob with one quantum channel.

    Timeline when *with_entangle* is False:  [0, 10]
    Timeline when *with_entangle* is True:   [0, 10, 100, 125, 150]
    (the entangle gate starts at t=100 and commits at t=150)
    """
    events: list[dict] = [
        {"type": "createNode", "t_ns": 0, "label": "Alice", "x": 25.0, "y": 50.0},
        {"type": "createNode", "t_ns": 0, "label": "Bob", "x": 75.0, "y": 50.0},
        {"type": "createChannel", "t_ns": 0, "from": "Alice", "to": "Bob", "kind": "quantum"},
        {"type": "createQubit", "t_ns": 10, "label": "q0", "node": "Alice"},
        {"type": "createQubit", "t_ns": 10, "label": "q1", "node": "Bob"},
    ]
    if with_entangle:
        events.append({"type": "entangle", "t_ns": 150, "duration_ns": 50, "bits": ["q0", "q1"]})
    return events


def make_stress_events(n_pairs: int = 80) -> list[dict]:
    """Larger synthetic trace exercising the incremental replay engine.

    Interleaves Bell-pair generation, transfers, measurements, removals,
    entangle toggles, overlapping gate windows sharing a qubit, and a
    graph-state chain with X/Y graph measurements.  With the default size
    the action count exceeds the checkpoint interval several times over.
    """
    events: list[dict] = [
        {"type": "createNode", "t_ns": 0, "label": "Alice", "x": 25.0, "y": 50.0},
        {"type": "createNode", "t_ns": 0, "label": "Bob", "x": 75.0, "y": 50.0},
        {"type": "createChannel", "t_ns": 0, "from": "Alice", "to": "Bob", "kind": "quantum"},
    ]
    t = 100
    for i in range(n_pairs):
        a, b = f"a{i}", f"b{i}"
        remove: dict = {"type": "removeQubit", "t_ns": t + 95, "bit": a}
        if i % 3 == 0:
            remove["reason"] = "discarded"
        elif i % 3 == 1:
            remove["reason"] = "lost"
        events += [
            {"type": "createQubit", "t_ns": t, "label": a, "node": "Alice"},
            {"type": "createQubit", "t_ns": t, "label": b, "node": "Alice"},
            {"type": "entangle", "t_ns": t + 50, "duration_ns": 20, "bits": [a, b]},
            {"type": "sendQubit", "t0_ns": t + 40, "t1_ns": t + 90, "bit": b, "from": "Alice", "to": "Bob"},
            {"type": "measure", "t_ns": t + 105, "duration_ns": 10, "bit": a, "base": "Z"},
            remove,
        ]
        t += 50  # overlaps the previous pair's transit window
    # Overlapping gate windows sharing qubit y: [t+980, t+1080) and [t+1000, t+1100)
    events += [
        {"type": "createQubit", "t_ns": t, "label": "x", "node": "Alice"},
        {"type": "createQubit", "t_ns": t, "label": "y", "node": "Alice"},
        {"type": "createQubit", "t_ns": t, "label": "z", "node": "Alice"},
        {"type": "entangle", "t_ns": t + 1080, "duration_ns": 100, "bits": ["y", "z"]},
        {"type": "entangle", "t_ns": t + 1100, "duration_ns": 100, "bits": ["x", "y"]},
        {"type": "entangle", "t_ns": t + 1100, "bits": ["x", "y"]},  # toggle off
        {"type": "entangle", "t_ns": t + 1200, "bits": ["x", "y"]},  # toggle back on
    ]
    t += 1300
    # Graph-state chain g0-g1-g2-g3 with X and Y graph measurements
    events += [{"type": "createQubit", "t_ns": t, "label": f"g{k}", "node": "Bob"} for k in range(4)]
    events += [
        {"type": "entangle", "t_ns": t + 10, "bits": ["g0", "g1"]},
        {"type": "entangle", "t_ns": t + 10, "bits": ["g1", "g2"]},
        {"type": "entangle", "t_ns": t + 10, "bits": ["g2", "g3"]},
        {"type": "graphMeasure", "t_ns": t + 70, "duration_ns": 20, "bit": "g1", "base": "X", "supportNode": "g0"},
        {"type": "graphMeasure", "t_ns": t + 100, "duration_ns": 20, "bit": "g2", "base": "Y"},
        {"type": "removeQubit", "t_ns": t + 90, "bit": "g1"},
    ]
    return events


def make_linear_graph_state_events() -> list[dict]:
    """Three-qubit linear graph state: q0--q1--q2 (edges added at t=100).

    Useful for testing graph-state measurement operations where removing or
    measuring the central qubit q1 changes the topology for q0 and q2.
    """
    return [
        {"type": "createNode", "t_ns": 0, "label": "Alice", "x": 25.0, "y": 50.0},
        {"type": "createNode", "t_ns": 0, "label": "Bob", "x": 75.0, "y": 50.0},
        {"type": "createChannel", "t_ns": 0, "from": "Alice", "to": "Bob", "kind": "quantum"},
        {"type": "createQubit", "t_ns": 10, "label": "q0", "node": "Alice"},
        {"type": "createQubit", "t_ns": 10, "label": "q1", "node": "Alice"},
        {"type": "createQubit", "t_ns": 10, "label": "q2", "node": "Bob"},
        {"type": "entangle", "t_ns": 100, "bits": ["q0", "q1"]},
        {"type": "entangle", "t_ns": 100, "bits": ["q1", "q2"]},
    ]
