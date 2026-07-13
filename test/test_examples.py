# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from q2nsviz import EventFileParser, SimulationStateManager

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_EXAMPLE_DIR = _REPO_ROOT / "q2nsviz" / "example_traces"
_EXAMPLE_FILES = sorted(_EXAMPLE_DIR.glob("*.json"))


def test_engine_import_pulls_in_no_qt():
    """Test that importing the package exposes the replay engine without loading Qt,
    so a script can reconstruct network state headlessly (run in a fresh interpreter,
    since the GUI tests import Qt into this one).
    """
    code = "import q2nsviz, sys; print([m for m in sys.modules if 'PyQt' in m])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=_REPO_ROOT)
    assert out.stdout.strip() == "[]", f"importing q2nsviz loaded Qt: {out.stdout}"


@pytest.mark.parametrize("path", _EXAMPLE_FILES, ids=lambda p: p.stem)
def test_bundled_example_parses_validates_and_replays(path):
    """Test that every bundled example parses with zero errors, validates with zero
    issues, and replays identically to the from-scratch reference at every keyframe.
    """
    events, errors = EventFileParser.load_from_file(str(path))
    assert errors == []
    assert events
    sm = SimulationStateManager()
    assert sm._validate_events(events) == []
    sm.load_events(events)
    assert sm.time_array
    ref = SimulationStateManager()
    ref.load_events(events)
    for t in sm.time_array:
        assert sm.snapshot_at(t) == ref._snapshot_at_uncached(t), f"Mismatch at t={t}"


def test_load_events_accepts_a_trace_path():
    """Test that load_events() accepts a str or Path trace-file source and yields
    the same timeline and final state as loading the pre-parsed event list.
    """
    path = _EXAMPLE_DIR / "q2nsviz-repeater-swap-example.json"
    from_list = SimulationStateManager()
    from_list.load_events(EventFileParser.load_from_file(str(path))[0])
    for source in (str(path), path):
        sm = SimulationStateManager()
        sm.load_events(source)
        assert sm.time_array == from_list.time_array
        assert sm.snapshot_at(sm.t_max) == from_list.snapshot_at(from_list.t_max)


def test_channel_loss_example_separates_lost_from_discarded():
    """Test that the channel-loss example reports only the three dropped photons
    as lost; the three deliberately discarded memory qubits are classified apart.
    """
    sm = SimulationStateManager()
    sm.load_events(str(_EXAMPLE_DIR / "q2nsviz-channel-loss-example.json"))
    snap = sm.snapshot_at(sm.t_max)
    assert snap.lost_qubits == {"fly_1", "fly_2", "fly_3"}
    assert snap.discarded_qubits == {"mem_1", "mem_2", "mem_3"}
    assert snap.live_qubit_labels == {"fly_4", "mem_4"}


def test_teleportation_example_final_state(teleportation_events):
    """Test that the teleportation example ends with all three qubits measured
    and no residual entanglement.
    """
    sm = SimulationStateManager()
    sm.load_events(teleportation_events)
    sm.snapshot_at(sm.t_max)
    assert sm.measured_qubits == {"psi", "alice_epr", "bob_epr"}
    assert sm.get_entangled_states() == {}
