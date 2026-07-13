# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import random

from helpers import make_linear_graph_state_events, make_stress_events, make_two_node_events

from q2nsviz import SimulationStateManager, Snapshot, UnionFind


class TestLifecycle:
    def test_initial_state_empty(self, sm):
        """Test that a fresh SimulationStateManager has empty state."""
        assert sm.nodes == {}
        assert sm.channels == []
        assert sm.qubits == {}
        assert sm.cbits == {}
        assert sm.t_max == 0
        assert sm.time_array == []

    def test_reset_clears_all_state(self, sm):
        """Test that reset() clears the loaded state and the replay structures."""
        sm.load_events(make_two_node_events(with_entangle=True))
        sm.snapshot_at(100)
        sm.reset()
        assert sm.nodes == {}
        assert sm.channels == []
        assert sm.qubits == {}
        assert sm.cbits == {}
        assert sm.events == []
        assert sm.measured_qubits == set()
        assert sm.removed_qubits == set()
        assert sm.t_max == 0
        assert sm.time_array == []
        assert sm._actions == []
        assert sm._checkpoints == []
        assert sm._cursor is None

    def test_load_events_builds_topology(self, sm):
        """Test that load_events() populates nodes and channels."""
        sm.load_events(make_two_node_events())
        assert "Alice" in sm.nodes
        assert "Bob" in sm.nodes
        assert len(sm.channels) == 1
        assert sm.channels[0].from_node == "Alice"
        assert sm.channels[0].to_node == "Bob"

    def test_channel_dedup(self, sm):
        """Test that a {pair, kind} collapses to one channel in any direction; distinct kinds stay separate."""
        events = [
            {"type": "createNode", "t_ns": 0, "label": "A"},
            {"type": "createNode", "t_ns": 0, "label": "B"},
            {"type": "createChannel", "t_ns": 0, "from": "A", "to": "B", "kind": "quantum"},
            {"type": "createChannel", "t_ns": 0, "from": "B", "to": "A", "kind": "quantum"},  # reverse
            {"type": "createChannel", "t_ns": 0, "from": "A", "to": "B", "kind": "quantum"},  # exact repeat
            {"type": "createChannel", "t_ns": 0, "from": "A", "to": "B", "kind": "classical"},  # distinct kind
        ]
        sm.load_events(events)
        assert len(sm.channels) == 2
        assert {c.kind for c in sm.channels} == {"quantum", "classical"}

    def test_timeline_construction(self, sm):
        """Test that the timeline is sorted and deduplicated, includes operation-window
        and transit-interpolation keyframes, and that t_max follows the latest t1_ns.
        """
        events = make_two_node_events(with_entangle=True)
        events.append({"type": "sendQubit", "t0_ns": 110, "t1_ns": 510, "bit": "q0", "from": "Alice", "to": "Bob"})
        sm.load_events(events)
        ta = sm.time_array
        assert ta == sorted(ta), "time_array must be sorted"
        assert len(ta) == len(set(ta)), "time_array must not contain duplicates"
        assert sm.t_max == 510  # latest t1_ns wins over the latest gate commit
        assert {0, 10, 100} <= set(ta)  # event timestamps
        assert {125, 150} <= set(ta)  # entangle-window midpoint and completion
        assert {210, 310, 410} <= set(ta)  # 3 interpolation frames for the [110, 510] transit

    def test_load_events_resets_before_loading(self, sm):
        """Test that load_events() implicitly resets; only the second load's state persists."""
        sm.load_events(make_two_node_events(with_entangle=True))
        sm.load_events([{"type": "createNode", "t_ns": 0, "label": "Charlie"}])
        assert "Alice" not in sm.nodes
        assert "Bob" not in sm.nodes
        assert "Charlie" in sm.nodes
        assert sm._actions == []  # a node-only trace compiles no actions


class TestReduceToQubits:
    def test_qubit_creation_visibility(self, sm):
        """Test that a qubit appears in the state only from its createQubit timestamp on."""
        sm.load_events(make_two_node_events())
        sm.snapshot_at(5)  # createQubit is at t_ns=10
        assert "q0" not in sm.qubits
        sm.snapshot_at(10)
        assert sm.qubits["q0"].node == "Alice"
        assert sm.qubits["q1"].node == "Bob"

    def test_sendqubit_transit_lifecycle(self, sm):
        """Test a qubit through sendQubit: at the source before t0_ns, in flight inside
        [t0_ns, t1_ns), and arrived at the destination at t1_ns.
        """
        events = make_two_node_events()
        events.append({"type": "sendQubit", "t0_ns": 20, "t1_ns": 80, "bit": "q0", "from": "Alice", "to": "Bob"})
        sm.load_events(events)
        assert "q0" not in sm.snapshot_at(10).inflight_qubits
        assert sm.qubits["q0"].node == "Alice"
        assert "q0" in sm.snapshot_at(50).inflight_qubits
        assert "q0" not in sm.snapshot_at(80).inflight_qubits
        assert sm.qubits["q0"].node == "Bob"

    def test_removequbit_appears_in_removed_set(self, sm):
        """Test that a qubit removed by removeQubit appears in the removed_qubits set."""
        events = make_two_node_events()
        events.append({"type": "removeQubit", "t_ns": 50, "bit": "q0"})
        sm.load_events(events)
        assert "q0" in sm.snapshot_at(50).removed_qubits

    def test_removequbit_reason_classifies_lost_vs_discarded(self, sm):
        """Test that reason="discarded" excludes a removal from lost_qubits, while
        reason="lost" and a missing reason both classify the removal as lost.
        """
        events = make_two_node_events()
        events += [
            {"type": "createQubit", "t_ns": 10, "label": "q2", "node": "Alice"},
            {"type": "removeQubit", "t_ns": 50, "bit": "q0", "reason": "lost"},
            {"type": "removeQubit", "t_ns": 50, "bit": "q1", "reason": "discarded"},
            {"type": "removeQubit", "t_ns": 50, "bit": "q2"},
        ]
        sm.load_events(events)
        snap = sm.snapshot_at(50)
        assert snap.removed_qubits == {"q0", "q1", "q2"}
        assert snap.discarded_qubits == {"q1"}
        assert snap.lost_qubits == {"q0", "q2"}
        assert snap.live_qubit_labels == frozenset()

    def test_measured_then_discarded_qubit_is_neither_lost_nor_live(self, sm):
        """Test that a measured qubit removed with reason="discarded" (the BSM
        pattern emitted by Q2NS) stays out of both lost_qubits and the live set.
        """
        events = make_two_node_events()
        events += [
            {"type": "measure", "t_ns": 40, "bit": "q0", "base": "Bell"},
            {"type": "removeQubit", "t_ns": 40, "bit": "q0", "reason": "discarded"},
        ]
        sm.load_events(events)
        snap = sm.snapshot_at(40)
        assert "q0" in snap.measured_qubits
        assert "q0" in snap.discarded_qubits
        assert snap.lost_qubits == frozenset()
        assert "q0" not in snap.live_qubit_labels

    def test_cbit_lifecycle(self, sm):
        """Test a classical bit through creation, transit, arrival, and removal."""
        events = make_two_node_events()
        events += [
            {"type": "createCbit", "t_ns": 10, "label": "c0", "node": "Alice"},
            {"type": "sendCbit", "t0_ns": 20, "t1_ns": 80, "bit": "c0", "from": "Alice", "to": "Bob"},
            {"type": "removeCbit", "t_ns": 100, "bit": "c0"},
        ]
        sm.load_events(events)
        sm.snapshot_at(10)
        assert sm.cbits["c0"].node == "Alice"
        assert "c0" in sm.snapshot_at(50).inflight_cbits
        sm.snapshot_at(80)
        assert sm.cbits["c0"].node == "Bob"
        assert "c0" in sm.snapshot_at(100).removed_cbits


class TestReduceToEntanglement:
    def test_entangle_edge_semantics(self, sm):
        """Test that entangle creates symmetric pairwise edges among all listed bits and
        that a second entangle on the same pair toggles that edge off, leaving the rest.
        """
        events = make_two_node_events()
        events.append({"type": "createQubit", "t_ns": 10, "label": "q2", "node": "Alice"})
        events.append({"type": "entangle", "t_ns": 100, "bits": ["q0", "q1", "q2"]})
        events.append({"type": "entangle", "t_ns": 200, "bits": ["q0", "q1"]})
        sm.load_events(events)
        sm.snapshot_at(100)
        assert "q1" in sm.ent_graph["q0"]
        assert "q0" in sm.ent_graph["q1"]  # symmetric
        assert "q2" in sm.ent_graph["q0"]
        assert "q2" in sm.ent_graph["q1"]
        sm.snapshot_at(200)
        assert "q1" not in sm.ent_graph.get("q0", set())
        assert "q0" not in sm.ent_graph.get("q1", set())
        assert "q2" in sm.ent_graph["q0"]  # untouched pairs keep their edges

    def test_entangle_with_measured_qubit_is_ignored(self, sm):
        """Test that _ent_graph_add_edge returns early when one qubit is already measured;
        no edge is created between q0 (measured) and q1.
        """
        events = make_two_node_events()
        events += [
            {"type": "measure", "t_ns": 50, "duration_ns": 0, "bit": "q0", "base": "Z"},
            {"type": "entangle", "t_ns": 100, "bits": ["q0", "q1"]},
        ]
        sm.load_events(events)
        sm.snapshot_at(100)
        assert "q1" not in sm.ent_graph.get("q0", set())
        assert "q0" not in sm.ent_graph.get("q1", set())

    def test_measure_clears_ent_graph_edges(self, sm):
        """Test that measuring q0 removes all edges to q0 in the entanglement graph."""
        events = make_two_node_events(with_entangle=True)
        events.append({"type": "measure", "t_ns": 200, "duration_ns": 0, "bit": "q0", "base": "Z"})
        sm.load_events(events)
        sm.snapshot_at(200)
        assert "q0" not in sm.ent_graph.get("q1", set())


class TestReduceToOperationWindows:
    def test_entangle_window_lifecycle(self, loaded_sm):
        """Test the gate window [100, 150): no marker before the gate starts, both
        qubits gate-processing (never measuring) with the edge uncommitted inside
        it, and the marker cleared with the edge committed at t=150.
        """
        gate = loaded_sm.snapshot_at(99).gate_qubits
        assert "q0" not in gate
        assert "q1" not in gate
        snap = loaded_sm.snapshot_at(125)
        assert "q0" in snap.gate_qubits
        assert "q1" in snap.gate_qubits
        assert "q0" not in snap.measuring_qubits  # a gate must never be reported as a measurement
        assert "q1" not in snap.measuring_qubits
        assert "q1" not in loaded_sm.ent_graph.get("q0", set())
        gate = loaded_sm.snapshot_at(150).gate_qubits
        assert "q0" not in gate
        assert "q1" not in gate
        assert "q1" in loaded_sm.ent_graph["q0"]

    def test_measure_window_lifecycle(self, sm):
        """Test the measure window [100, 140): the qubit is in the measuring set (not
        the gate set) inside the window and enters measured_qubits only at commit.
        """
        events = make_two_node_events()
        events.append({"type": "measure", "t_ns": 140, "duration_ns": 40, "bit": "q0", "base": "Z"})
        sm.load_events(events)
        snap = sm.snapshot_at(120)
        assert "q0" in snap.measuring_qubits
        assert "q0" not in snap.gate_qubits
        assert "q0" not in sm.measured_qubits
        sm.snapshot_at(140)
        assert "q0" in sm.measured_qubits

    def test_graph_measure_window_lifecycle(self, sm):
        """Test the graphMeasure window [100, 140): graph-measuring inside, committed after."""
        events = make_two_node_events()
        events.append({"type": "graphMeasure", "t_ns": 140, "duration_ns": 40, "bit": "q0", "base": "Z"})
        sm.load_events(events)
        assert "q0" in sm.snapshot_at(120).graph_measuring_qubits
        assert "q0" not in sm.measured_qubits  # not yet committed
        sm.snapshot_at(140)
        assert "q0" in sm.measured_qubits


class TestEntanglementQueries:
    def test_get_entanglement_groups_components(self, sm):
        """Test that chained entangle events merge into one component while a disjoint
        pair stays a separate component.
        """
        events = [
            {"type": "createNode", "t_ns": 0, "label": "A"},
            {"type": "createQubit", "t_ns": 0, "label": "q0", "node": "A"},
            {"type": "createQubit", "t_ns": 0, "label": "q1", "node": "A"},
            {"type": "createQubit", "t_ns": 0, "label": "q2", "node": "A"},
            {"type": "createQubit", "t_ns": 0, "label": "q3", "node": "A"},
            {"type": "createQubit", "t_ns": 0, "label": "q4", "node": "A"},
            {"type": "entangle", "t_ns": 100, "bits": ["q0", "q1"]},
            {"type": "entangle", "t_ns": 100, "bits": ["q1", "q2"]},
            {"type": "entangle", "t_ns": 100, "bits": ["q3", "q4"]},
        ]
        sm.load_events(events)
        sm.snapshot_at(100)
        groups = sm.get_entanglement_groups()
        chain = next((ms for ms in groups.values() if "q0" in ms), None)
        assert chain is not None, "q0 not found in any entanglement group"
        assert {"q1", "q2"} <= set(chain)
        pair = next((ms for ms in groups.values() if "q3" in ms), None)
        assert pair is not None, "q3 not found in any entanglement group"
        assert "q4" in pair
        assert set(chain).isdisjoint(pair)

    def test_get_entangled_states_filters_singletons_and_removed(self, sm):
        """Test that isolated qubits never appear as entangled states and that removing a
        chain endpoint strips it while the surviving pair remains an entangled state.
        """
        events = make_linear_graph_state_events()
        events.append({"type": "createQubit", "t_ns": 10, "label": "lone", "node": "Alice"})
        events.append({"type": "removeQubit", "t_ns": 200, "bit": "q0"})
        sm.load_events(events)
        sm.snapshot_at(100)
        states = sm.get_entangled_states()
        assert not any("lone" in ms for ms in states.values())
        assert any("q0" in ms for ms in states.values())
        sm.snapshot_at(200)
        states = sm.get_entangled_states()
        assert not any("q0" in ms for ms in states.values())
        # q1-q2 edge survives q0's removal --- they must still form an entangled pair
        assert any("q1" in ms and "q2" in ms for ms in states.values())


class TestLiveQubitQueries:
    def test_live_set_excludes_measured_and_removed(self, sm):
        """Test that the snapshot's live set excludes removed and measured qubits."""
        events = make_two_node_events()
        events.append({"type": "removeQubit", "t_ns": 50, "bit": "q0"})
        events.append({"type": "measure", "t_ns": 60, "duration_ns": 0, "bit": "q1", "base": "Z"})
        sm.load_events(events)
        assert sm.snapshot_at(10).live_qubit_labels == {"q0", "q1"}
        assert sm.snapshot_at(50).live_qubit_labels == {"q1"}
        snap = sm.snapshot_at(60)
        assert snap.live_qubit_labels == frozenset()
        assert snap.measured_qubits == {"q1"}


class TestLogEvents:
    def test_log_events_filtered_by_time(self, sm):
        """Test that traceText events are returned filtered by time, that the count
        agrees with the slice, and that traces without traceText yield an empty log.
        """
        sm.load_events(make_two_node_events())
        assert sm.get_log_events(9999) == []
        events = make_two_node_events()
        events += [
            {"type": "traceText", "t_ns": 50, "text": "early"},
            {"type": "traceText", "t_ns": 150, "text": "late"},
        ]
        sm.load_events(events)
        logs = sm.get_log_events(100)
        assert len(logs) == 1
        assert logs[0]["text"] == "early"
        assert sm.log_count_at(100) == 1
        assert sm.log_count_at(49) == 0
        assert sm.log_count_at(150) == 2


class TestValidation:
    def test_malformed_trace_flags_all_issues(self, sm, caplog):
        """Test that validation flags negative timestamps, out-of-order events, inverted
        transit windows, unknown nodes, and undeclared qubits in one load.
        """
        events = [
            {"type": "createNode", "t_ns": -1, "label": "A"},
            {"type": "createNode", "t_ns": 100, "label": "B"},
            {"type": "createQubit", "t_ns": 50, "label": "q"},  # 50 < 100 -> out of order
            {"type": "sendQubit", "t0_ns": 100, "t1_ns": 50, "bit": "q", "from": "A", "to": "Nowhere"},
            {"type": "entangle", "t_ns": 200, "bits": ["q", "ghost"]},
        ]
        with caplog.at_level(logging.WARNING):
            sm.load_events(events)
        assert "negative t_ns" in caplog.text
        assert "out of chronological order" in caplog.text
        assert "t0_ns=100 > t1_ns=50" in caplog.text
        assert "Nowhere" in caplog.text
        assert "ghost" in caplog.text

    def test_acausal_duration_windows_flagged(self, sm, caplog):
        """Test that a duration window reaching back before t=0 or before the
        qubit's createQubit is flagged; a window starting exactly at creation is not.
        """
        events = make_two_node_events()
        events += [
            {"type": "entangle", "t_ns": 30, "duration_ns": 50, "bits": ["q0", "q1"]},  # window < 0
            {"type": "measure", "t_ns": 40, "duration_ns": 35, "bit": "q0", "base": "Z"},  # starts before create
            {"type": "graphMeasure", "t_ns": 60, "duration_ns": 50, "bit": "q1", "base": "X"},  # starts at create
        ]
        with caplog.at_level(logging.WARNING):
            sm.load_events(events)
        assert "duration_ns=50 exceeds t_ns=30" in caplog.text
        assert "window [5, 40) starts before createQubit of 'q0'" in caplog.text
        assert "window [10, 60)" not in caplog.text

    def test_unknown_event_type_does_not_raise(self, sm):
        """Test that loading an event with an unknown type does not raise an exception and is ignored."""
        events = make_two_node_events()
        events.append({"type": "unknownFutureEventType", "t_ns": 50, "data": 42})
        sm.load_events(events)  # must not raise
        assert sm.t_max == 50


class TestUnionFind:
    def test_union_find_connectivity(self):
        """Test find on singletons, union transitivity, and path-compressed roots."""
        uf = UnionFind()
        assert uf.find("a") == "a"
        uf.union("a", "b")
        uf.union("b", "c")
        uf.union("c", "d")
        root = uf.find("a")
        assert uf.find("b") == root
        assert uf.find("c") == root
        assert uf.find("d") == root

    def test_groups_separates_disjoint_sets(self):
        """Test that groups() separates disjoint sets correctly."""
        uf = UnionFind()
        uf.union("x", "y")
        uf.find("z")  # enroll z as a singleton
        groups = uf.groups()
        group_xy = next((ms for ms in groups.values() if "x" in ms), None)
        assert group_xy is not None, "x not found in any group"
        assert "y" in group_xy
        assert "z" not in group_xy


class TestGraphMeasure:
    def _setup_chain_then_measure(self, sm, basis: str, support_node: str | None = None) -> None:
        """Test helper to set up a linear chain q0-q1-q2;
        then apply a graphMeasure on q1 in the specified basis.
        """
        events = make_linear_graph_state_events()
        event = {"type": "graphMeasure", "t_ns": 200, "duration_ns": 0, "bit": "q1", "base": basis}
        if support_node is not None:
            event["supportNode"] = support_node
        events.append(event)
        sm.load_events(events)
        sm.snapshot_at(200)

    def test_graph_measure_z_removes_vertex(self, sm):
        """Test that a Z measurement marks the qubit measured and removes it without
        connecting its former neighbours.
        """
        self._setup_chain_then_measure(sm, "Z")
        assert "q1" in sm.measured_qubits
        assert "q2" not in sm.ent_graph.get("q0", set())
        assert "q0" not in sm.ent_graph.get("q2", set())
        assert "q1" not in sm.ent_graph  # vertex removed entirely

    def test_graph_measure_y_connects_endpoints(self, sm):
        """Test that a Y measurement on the centre removes it and connects q0 and q2 via
        local complementation; the LC-created edge must also be reported by
        get_entangled_states, identically to the filtered reference query.
        """
        self._setup_chain_then_measure(sm, "Y")
        assert "q2" in sm.ent_graph.get("q0", set())
        assert "q0" in sm.ent_graph.get("q2", set())
        assert "q1" not in sm.ent_graph
        fast = {frozenset(ms) for ms in sm.get_entangled_states().values()}
        assert fast == {frozenset({"q0", "q2"})}
        assert fast == {frozenset(ms) for ms in sm.get_entanglement_groups().values() if len(ms) > 1}

    def test_graph_measure_x_connects_endpoints_via_support(self, sm):
        """Test that an X measurement with a valid supportNode connects the non-measured endpoints."""
        self._setup_chain_then_measure(sm, "X", support_node="q0")
        assert "q2" in sm.ent_graph.get("q0", set())
        assert "q0" in sm.ent_graph.get("q2", set())
        assert "q1" not in sm.ent_graph

    def test_graph_measure_isolated_qubit_no_error(self, sm):
        """Test that Z and X measurements on qubits with no entanglement neighbours
        degrade to plain vertex removal without error.
        """
        events = make_two_node_events()
        events.append({"type": "graphMeasure", "t_ns": 50, "duration_ns": 0, "bit": "q0", "base": "Z"})
        events.append({"type": "graphMeasure", "t_ns": 60, "duration_ns": 0, "bit": "q1", "base": "X"})
        sm.load_events(events)
        sm.snapshot_at(60)
        assert {"q0", "q1"} <= sm.measured_qubits
        assert "q0" not in sm.ent_graph
        assert "q1" not in sm.ent_graph


class TestReplayEngine:
    @staticmethod
    def _assert_states_match(sm, ref, t):
        """Compare the incremental engine against the from-scratch reference at *t*,
        including the fast entangled-states query against the filtered full query.
        """
        incremental = sm.snapshot_at(t)
        reference = ref._snapshot_at_uncached(t)
        assert incremental == reference, f"Snapshot mismatch at t={t}"
        assert {k: v.node for k, v in sm.qubits.items()} == {k: v.node for k, v in ref.qubits.items()}
        assert {k: v.node for k, v in sm.cbits.items()} == {k: v.node for k, v in ref.cbits.items()}
        assert {k: set(v) for k, v in sm.ent_graph.items() if v} == {
            k: set(v) for k, v in ref.ent_graph.items() if v
        }
        assert sm.measured_qubits == ref.measured_qubits
        fast = {frozenset(ms) for ms in sm.get_entangled_states().values()}
        full = {frozenset(ms) for ms in sm.get_entanglement_groups().values() if len(ms) > 1}
        assert fast == full, f"Entangled-states query mismatch at t={t}"

    def _make_sm(self, events):
        """Build a SimulationStateManager with the given events loaded."""
        sm = SimulationStateManager()
        sm.load_events(events)
        return sm

    def test_matches_reference_at_and_between_keyframes(self):
        """Test equivalence with the from-scratch reference at every keyframe, between
        keyframes, before the first event, and past the end of the trace; the compiled
        action list must be time-sorted.
        """
        sm = self._make_sm(make_two_node_events(with_entangle=True))
        ref = self._make_sm(make_two_node_events(with_entangle=True))
        times = [action[0] for action in sm._actions]
        assert times == sorted(times)
        ts = sorted(set(sm.time_array) | {t + 1 for t in sm.time_array} | {-1, sm.t_max + 50})
        for t in ts:
            self._assert_states_match(sm, ref, t)

    def test_seek_interleaves_safely_with_snapshot_at(self):
        """Test that positioning via seek() — forward, backward, and between
        keyframes — leaves the incremental cursor consistent, so subsequent
        snapshot_at() calls still match the from-scratch reference.
        """
        sm = self._make_sm(make_two_node_events(with_entangle=True))
        ref = self._make_sm(make_two_node_events(with_entangle=True))
        ts = sm.time_array
        for t_seek, t_query in [(ts[-1], ts[0]), (ts[0], ts[-1]), (ts[-1] + 1, ts[1] + 1), (-1, ts[0])]:
            sm.seek(t_seek)
            self._assert_states_match(sm, ref, t_query)

    def test_time_travel_restores_state(self):
        """Test that backward jumps restore earlier keyframe state and that querying
        before the first event yields the all-empty state.
        """
        sm = self._make_sm(make_two_node_events(with_entangle=True))
        sm.snapshot_at(sm.time_array[0])
        qubits_at_start = set(sm.qubits)
        sm.snapshot_at(sm.time_array[-1])
        sm.snapshot_at(sm.time_array[0])
        assert set(sm.qubits) == qubits_at_start
        snap = sm.snapshot_at(-1)
        assert isinstance(snap, Snapshot)
        assert snap.qubits == {} and snap.cbits == {}
        assert snap.ent_graph == {} and snap.entangled_states == {}
        assert snap.inflight_qubits == frozenset() and snap.inflight_cbits == frozenset()
        assert snap.removed_qubits == frozenset() and snap.removed_cbits == frozenset()
        assert snap.measured_qubits == frozenset() and snap.lost_qubits == frozenset()
        assert snap.gate_qubits == frozenset() and snap.measuring_qubits == frozenset()
        assert snap.graph_measuring_qubits == frozenset() and snap.live_qubit_labels == frozenset()
        assert sm.qubits == {}

    def test_stress_trace_checkpoints_and_random_access(self):
        """Test that a trace larger than the checkpoint interval stores sparse, sorted
        checkpoints and replays identically to the reference under shuffled access.
        """
        events = make_stress_events()
        sm = self._make_sm(events)
        ref = self._make_sm(events)
        assert sm._checkpoints
        assert len(sm._checkpoints) < len(sm.time_array)
        assert sm._checkpoint_times == sorted(sm._checkpoint_times)
        ts = list(sm.time_array)
        ts += [t + 1 for t in ts[::7]] + [-5, sm.t_max + 100]
        random.Random(42).shuffle(ts)
        for t in ts[:400]:
            self._assert_states_match(sm, ref, t)
