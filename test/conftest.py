# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

import pathlib

import pytest
from helpers import make_two_node_events

from q2nsviz import EventFileParser, SimulationStateManager

_EXAMPLE_DIR = pathlib.Path(__file__).parent.parent / "q2nsviz" / "example_traces"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sm() -> SimulationStateManager:
    """Fresh, empty SimulationStateManager (function-scoped)."""
    return SimulationStateManager()


@pytest.fixture()
def loaded_sm() -> SimulationStateManager:
    """SimulationStateManager pre-loaded with a minimal two-node Bell-pair trace."""
    m = SimulationStateManager()
    m.load_events(make_two_node_events(with_entangle=True))
    return m


@pytest.fixture(scope="session")
def teleportation_events() -> list[dict]:
    """Events from the bundled teleportation example trace, loaded once per session."""
    events, _ = EventFileParser.load_from_file(str(_EXAMPLE_DIR / "q2nsviz-teleportation-example.json"))
    return events
