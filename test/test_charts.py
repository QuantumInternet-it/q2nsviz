# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from helpers import make_stress_events, make_two_node_events

from q2nsviz import SimulationStateManager
from q2nsviz.ui.charts import MATPLOTLIB_AVAILABLE, _live_qubit_series

pytestmark = pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib unavailable")


@pytest.mark.parametrize(
    "events_factory", [list, make_two_node_events, make_stress_events], ids=["empty", "two-node", "stress"]
)
def test_live_series_matches_engine_at_every_keyframe(events_factory):
    """Test that the one-pass live-qubit series equals the replay engine's live set
    at every keyframe, including for an empty trace.
    """
    events = events_factory()
    sm = SimulationStateManager()
    sm.load_events(events)
    series = _live_qubit_series(sm.events, sm.time_array)
    assert len(series) == len(sm.time_array)
    for t, value in zip(sm.time_array, series, strict=True):
        assert value == float(len(sm.snapshot_at(t).live_qubit_labels)), f"Mismatch at t={t}"
