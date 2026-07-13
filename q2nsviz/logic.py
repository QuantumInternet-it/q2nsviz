# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

import bisect
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """A network node with a canvas-relative position.

    @param label   Unique identifier used in events and displayed on the canvas.
    @param x_pct   Horizontal position as a percentage [0, 100] of the layout area.
    @param y_pct   Vertical position as a percentage [0, 100] of the layout area.
    @param has_explicit_position:   True when (x, y) were set by a createNode event;
                                    False triggers the automatic circular layout.
    @ingroup q2nsviz_engine
    """

    label: str
    x_pct: float
    y_pct: float
    has_explicit_position: bool = False


@dataclass
class Channel:
    """A directed communication link between two network nodes.

    @param from_node    Label of the source node.
    @param to_node      Label of the destination node.
    @param kind         Channel type: ``"quantum"`` or ``"classical"``.
                        Unknown kinds are stored but not rendered by the canvas.
    @ingroup q2nsviz_engine
    """

    from_node: str
    to_node: str
    kind: str  # "quantum" or "classical"


@dataclass
class Qubit:
    """A qubit residing at a network node, tracked by label.

    @param label    Unique identifier matching the Q2NS ``createQubit`` label field.
    @param node     Current host node label.  Updated by ``sendQubit`` events.
                    ``None`` while the qubit is in transit.
    @ingroup q2nsviz_engine
    """

    label: str
    node: str | None = None


@dataclass
class ClassicalBit:
    """A classical bit residing at a network node, tracked by label.

    @param label    Unique identifier matching the Q2NS ``createCbit`` label field.
    @param node     Current host node label.  Updated by ``sendCbit`` events.
                    ``None`` while the bit is in transit.
    @ingroup q2nsviz_engine
    """

    label: str
    node: str | None = None


# ---------------------------------------------------------------------------
# Replay checkpoint (used by the incremental replay engine)
# ---------------------------------------------------------------------------


@dataclass
class _StateSnapshot:
    """Full replay state captured at one checkpoint of the action stream.

    Produced by ``_build_checkpoints()`` and consumed by ``snapshot_at()``,
    which restores the nearest checkpoint at or before the requested time
    and replays the remaining actions.  Containers are stored as copies so
    a restore cannot corrupt the stored snapshot.  Operation-window sets
    (inflight, gate, measuring) are stored as reference counters so that
    overlapping windows on the same label survive a restore-and-continue.
    @ingroup q2nsviz_engine
    """

    qubits: dict[str, Qubit]
    cbits: dict[str, ClassicalBit]
    ent_graph: dict[str, frozenset[str]]
    measured_qubits: frozenset[str]
    removed_qubits: frozenset[str]
    discarded_qubits: frozenset[str]
    removed_cbits: frozenset[str]
    inflight_qubits: dict[str, int]
    inflight_cbits: dict[str, int]
    gate_qubits: dict[str, int]
    measuring_qubits: dict[str, int]
    graph_measuring_qubits: dict[str, int]


# ---------------------------------------------------------------------------
# Union-Find (for entanglement groups)
# ---------------------------------------------------------------------------


class UnionFind:
    """Disjoint-set data structure with path compression and union by rank.

    Used by ``SimulationStateManager`` to compute the connected components of
    the entanglement graph.
    @ingroup q2nsviz_engine
    """

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        """Find the root representative of the set containing *x*.

        Inserts *x* into the structure on first access.  Uses iterative
        two-pass path compression so the call stack never grows with set size.

        @param x  Element label to look up.
        @returns  Root representative of the component containing *x*.
        """
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        root = x
        while self.parent[root] != root:
            if self.parent[root] not in self.parent:
                self.parent[self.parent[root]] = self.parent[root]
                self.rank[self.parent[root]] = 0
            root = self.parent[root]
        node = x
        while node != root:
            nxt = self.parent[node]
            self.parent[node] = root
            node = nxt
        return root

    def union(self, a: str, b: str):
        """Merge the sets containing *a* and *b* using union by rank.

        @param a  First element label.
        @param b  Second element label.
        """
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1

    def groups(self) -> dict[str, list[str]]:
        """Return all components as ``{root: [members]}``.

        @returns  Dictionary mapping each component root to its member list.
                  Every element appears in exactly one list.
        """
        result: dict[str, list[str]] = defaultdict(list)
        for x in list(self.parent.keys()):
            result[self.find(x)].append(x)
        return dict(result)


# ---------------------------------------------------------------------------
# Public snapshot (returned by SimulationStateManager.snapshot_at)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """Immutable view of the reconstructed network state at one instant.

    Returned by ``SimulationStateManager.snapshot_at()``.  This is the unit
    of state that the ``QuantumVisualizerWindow`` controller dispatches to
    the views, and the object a script inspects after reconstructing a
    chosen simulation time.  Dynamic containers are copies or immutable
    views; advancing the manager afterwards never mutates an
    already-returned ``Snapshot``.

    @param t_ns              Simulation timestamp this snapshot reflects.
    @param nodes             Node topology (label -> ``Node``), built once at load time.
    @param channels          Channel list, built once at load time.
    @param qubits            Every qubit created up to ``t_ns`` (label -> ``Qubit``, with its current host node).
    @param cbits             Every classical bit created up to ``t_ns`` (label -> ``ClassicalBit``).
    @param ent_graph         Entanglement-graph adjacency (label -> neighbor labels);
                             vertices with no edges are omitted.
    @param entangled_states  Entangled components of two or more qubits, keyed by the
                             lexicographically smallest member (root -> sorted member tuple).
    @param measured_qubits   Qubits measured at or before ``t_ns``.
    @param removed_qubits    Qubits explicitly removed from the simulation.
    @param discarded_qubits  Qubits removed with ``reason == "discarded"``.
    @param lost_qubits       ``removed_qubits - measured_qubits - discarded_qubits``.
    @param live_qubit_labels Qubits neither measured nor removed.
    @param inflight_qubits   Qubits in transit inside a ``sendQubit`` window.
    @param inflight_cbits    Classical bits in transit inside a ``sendCbit`` window.
    @param gate_qubits       Qubits inside an ``entangle`` processing window
                             (``[t_ns - duration_ns, t_ns)``; the edges commit at ``t_ns``).
    @param measuring_qubits  Qubits inside a ``measure`` ``duration_ns`` window.
    @param graph_measuring_qubits  Qubits inside a ``graphMeasure`` ``duration_ns`` window.
    @param removed_cbits     Classical bits removed by ``removeCbit``.
    @ingroup q2nsviz_engine
    """

    t_ns: int
    nodes: dict[str, Node]
    channels: list[Channel]
    qubits: dict[str, Qubit]
    cbits: dict[str, ClassicalBit]
    ent_graph: dict[str, frozenset[str]]
    entangled_states: dict[str, tuple[str, ...]]
    measured_qubits: frozenset[str]
    removed_qubits: frozenset[str]
    discarded_qubits: frozenset[str]
    lost_qubits: frozenset[str]
    live_qubit_labels: frozenset[str]
    inflight_qubits: frozenset[str]
    inflight_cbits: frozenset[str]
    gate_qubits: frozenset[str]
    measuring_qubits: frozenset[str]
    graph_measuring_qubits: frozenset[str]
    removed_cbits: frozenset[str]


# ---------------------------------------------------------------------------
# Simulation State Manager
# ---------------------------------------------------------------------------


class SimulationStateManager:
    """Replays a Q2NS simulation event stream and exposes the quantum state.

    Usage pattern::

        sm = SimulationStateManager()
        sm.load_events(parsed_events)
        snap = sm.snapshot_at(t_ns)
        groups = snap.entangled_states

    Key invariants
    ---------------
    - ``snapshot_at(t_ns)`` returns an immutable ``Snapshot`` carrying all
      per-instant state; prefer its fields over the query helpers.  The
      helpers reflect the state positioned by the most recent
      ``snapshot_at()`` call; calling them on a fresh instance returns
      empty results silently.
    - ``ent_graph`` is restored or advanced to the requested time on every
      ``snapshot_at()`` call.  Do not cache pointers to its contents.
    - The class is **not** thread-safe; all calls must originate from the
      Qt main thread.

    JSON event types handled
    -------------------------
    ``createNode``, ``createChannel``,
    ``createQubit``, ``sendQubit``, ``removeQubit``,
    ``createCbit``, ``sendCbit``, ``removeCbit``,
    ``entangle``, ``measure``, ``graphMeasure``,
    ``sendPacket``, ``traceText``.
    @ingroup q2nsviz_engine
    """

    # Actions replayed between stored checkpoints, bounds both the memory used
    # by the checkpoint list and the replay cost of a backward jump.
    _CHECKPOINT_INTERVAL = 256

    def __init__(self):
        """Initialize all tracking collections to empty state.

        Call ``reset()`` to return to this state after loading events,
        or ``load_events()`` to populate from a parsed trace file.
        """
        self.nodes: dict[str, Node] = {}
        self.channels: list[Channel] = []
        self.qubits: dict[str, Qubit] = {}
        self.cbits: dict[str, ClassicalBit] = {}
        self.ent_graph: dict[str, set[str]] = defaultdict(set)
        self.measured_qubits: set[str] = set()
        self.removed_qubits: set[str] = set()
        self.discarded_qubits: set[str] = set()
        self.removed_cbits: set[str] = set()
        self.events: list[dict[str, Any]] = []
        self.events_by_type: dict[str, list[dict[str, Any]]] = {}
        self.log_events: list[dict[str, Any]] = []
        self._log_times: list[int] = []
        self.t_max: int = 0
        self.time_array: list[int] = []
        # Replay engine: (t_ns, event_idx, phase, kind, event) actions,
        # sparse checkpoints, and the (t_ns, next_action_idx) live cursor.
        self._actions: list[tuple[int, int, int, str, dict[str, Any]]] = []
        self._checkpoints: list[tuple[int, _StateSnapshot]] = []
        self._checkpoint_times: list[int] = []
        self._cursor: tuple[int, int] | None = None
        self._win_inflight_qubits: dict[str, int] = {}
        self._win_inflight_cbits: dict[str, int] = {}
        self._win_gate: dict[str, int] = {}
        self._win_measuring: dict[str, int] = {}
        self._win_graph_measuring: dict[str, int] = {}

    def reset(self):
        """Clear all loaded state."""
        self.nodes.clear()
        self.channels.clear()
        self.events.clear()
        self.events_by_type.clear()
        self.log_events = []
        self._log_times = []
        self.t_max = 0
        self.time_array.clear()
        self._actions.clear()
        self._checkpoints.clear()
        self._checkpoint_times.clear()
        self._cursor = None
        self._clear_replay_state()

    # -- Event loading ------------------------------------------------------

    def load_events(self, source: str | Path | list[dict[str, Any]]):
        """Ingest a trace and build the simulation timeline.

        Accepts either an already-parsed event list or a path to a trace
        file; a path is parsed with ``EventFileParser`` first, with any
        parse errors logged as warnings.  Processes ``createNode`` and
        ``createChannel`` events immediately; all other event types are
        deferred to ``snapshot_at()``.  Runs ``_validate_events()`` and logs
        any detected issues as warnings.

        @param source  List of raw event dictionaries from
                       ``EventFileParser``, or the path of a JSON/NDJSON
                       trace file to load.

        Calls ``reset()`` before loading, so any previously loaded state is
        discarded.  Each call to ``load_events()`` always starts from a clean
        slate.
        """
        if isinstance(source, str | Path):
            events, errors = EventFileParser.load_from_file(str(source))
            for error in errors:
                logger.warning("Trace parse: %s", error)
        else:
            events = source
        self.reset()
        self.events = events

        issues = self._validate_events(events)
        for issue in issues:
            logger.warning("Trace validation: %s", issue)

        seen_channels: set[tuple] = set()
        for event in events:
            event_type = event.get("type")

            if event_type == "createNode":
                label = event.get("label")
                if not label:
                    logger.warning("createNode event missing 'label': %s", event)
                    continue
                node = Node(
                    label=label,
                    x_pct=event.get("x", 0.0),
                    y_pct=event.get("y", 0.0),
                    has_explicit_position=("x" in event and "y" in event),
                )
                self.nodes[label] = node

            elif event_type == "createChannel":
                from_node = event.get("from")
                to_node = event.get("to")
                if not from_node or not to_node:
                    logger.warning("createChannel missing 'from'/'to': %s", event)
                    continue
                kind = event.get("kind", "quantum")
                # One undirected line is drawn per {pair, kind}; a link declared in
                # both directions collapses to a single channel.
                key = (*sorted((from_node, to_node)), kind)
                if key in seen_channels:
                    continue
                seen_channels.add(key)
                self.channels.append(Channel(from_node=from_node, to_node=to_node, kind=kind))

        self._build_index()
        self._build_timeline()
        self._build_actions()
        self._build_checkpoints()

    def _build_index(self):
        """Group the events by type, and collect the ``traceText`` events in time order.

        Both indexes are built once per load so that the per-frame consumers --
        the canvas animation passes and ``get_log_events()`` -- never rescan the
        full event list.
        """
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events:
            by_type[event.get("type", "")].append(event)
        self.events_by_type = dict(by_type)
        self.log_events = sorted(self.events_by_type.get("traceText", []), key=lambda e: e.get("t_ns", 0))
        self._log_times = [e.get("t_ns", 0) for e in self.log_events]

    # -- Timeline -----------------------------------------------------------

    def _build_timeline(self):
        """Build a sorted array of keyframe times from the event list."""
        self.t_max = 0
        for event in self.events:
            if "t_ns" in event and event["t_ns"] is not None:
                self.t_max = max(self.t_max, event["t_ns"])
            if "t1_ns" in event and event["t1_ns"] is not None:
                self.t_max = max(self.t_max, event["t1_ns"])

        time_set: set[int] = set()
        for event in self.events:
            if "t_ns" in event and event["t_ns"] is not None:
                time_set.add(event["t_ns"])
            if "t0_ns" in event and "t1_ns" in event and event["t0_ns"] is not None and event["t1_ns"] is not None:
                t0, t1 = event["t0_ns"], event["t1_ns"]
                time_set.add(t0)
                time_set.add(t1)
                # Interpolation frames for smooth animation
                k_frames = 3
                for k in range(1, k_frames + 1):
                    time_set.add(int(t0 + (k / (k_frames + 1)) * (t1 - t0)))
            if "duration_ns" in event and event.get("t_ns") is not None:
                duration = event["duration_ns"]
                if duration and duration > 0:
                    t_end = event["t_ns"]
                    t_start = max(0, t_end - duration)
                    time_set.add(t_start)
                    # Midpoint keyframe, so stepping cannot skip over the operation ring
                    time_set.add((t_start + t_end) // 2)

        self.time_array = sorted(time_set)

    # -- Validation ---------------------------------------------------------

    def _validate_events(self, events: list[dict[str, Any]]) -> list[str]:
        """Validate the event stream and return a list of issue descriptions.

        Checks performed:
        - Timestamps are non-negative and non-decreasing.
        - t0_ns <= t1_ns for movement events (sendQubit, sendCbit, sendPacket).
        - Qubit and node labels referenced before createQubit / createNode.
        - duration_ns windows (``[t_ns - duration_ns, t_ns)``) that reach back
          before t=0 or before the referenced qubit existed.
        """
        issues: list[str] = []
        known_bits: dict[str, int] = {}
        known_nodes: set[str] = set()
        last_t: int = -1

        for idx, ev in enumerate(events):
            ev_type = ev.get("type", "")
            t = ev.get("t_ns")

            if t is not None:
                if t < 0:
                    issues.append(f"Event #{idx} ({ev_type}): negative t_ns={t}")
                if t < last_t:
                    issues.append(
                        f"Event #{idx} ({ev_type}): t_ns={t} is before previous "
                        f"t_ns={last_t} \u2014 events are out of chronological order"
                    )
                last_t = max(last_t, t)

            if ev_type in {"sendQubit", "sendCbit", "sendPacket"}:
                t0, t1 = ev.get("t0_ns"), ev.get("t1_ns")
                if t0 is not None and t1 is not None and t0 > t1:
                    issues.append(f"Event #{idx} ({ev_type}): t0_ns={t0} > t1_ns={t1}")

            if ev_type == "createNode":
                label = ev.get("label")
                if label:
                    known_nodes.add(label)

            elif ev_type == "createChannel":
                for field in ("from", "to"):
                    ref = ev.get(field)
                    if ref and ref not in known_nodes:
                        issues.append(f"Event #{idx} (createChannel): '{field}' references unknown node '{ref}'")

            elif ev_type == "createQubit":
                label = ev.get("label")
                if not label:
                    issues.append(f"Event #{idx} (createQubit): missing 'label' field")
                else:
                    known_bits[label] = t if t is not None else 0

            elif ev_type == "createCbit":
                label = ev.get("label")
                if not label:
                    issues.append(f"Event #{idx} (createCbit): missing 'label' field")
                else:
                    known_bits[label] = t if t is not None else 0

            elif ev_type in {"measure", "graphMeasure", "removeQubit"}:
                qubit_label = ev.get("bit")
                if qubit_label and qubit_label not in known_bits:
                    issues.append(f"Event #{idx} ({ev_type}): qubit '{qubit_label}' referenced before createQubit")
                if ev_type != "removeQubit" and qubit_label:
                    issues.extend(
                        self._window_issues(idx, ev_type, t, ev.get("duration_ns"), [qubit_label], known_bits)
                    )

            elif ev_type in {"removeCbit"}:
                cbit_label = ev.get("bit")
                if cbit_label and cbit_label not in known_bits:
                    issues.append(f"Event #{idx} ({ev_type}): cbit '{cbit_label}' referenced before createCbit")

            elif ev_type == "sendQubit":
                qubit_label = ev.get("bit")
                if qubit_label and qubit_label not in known_bits:
                    issues.append(f"Event #{idx} (sendQubit): qubit '{qubit_label}' referenced before createQubit")
                for field in ("from", "to"):
                    ref = ev.get(field)
                    if ref and ref not in known_nodes:
                        issues.append(f"Event #{idx} (sendQubit): '{field}' references unknown node '{ref}'")

            elif ev_type == "sendCbit":
                cbit_label = ev.get("bit")
                if cbit_label and cbit_label not in known_bits:
                    issues.append(f"Event #{idx} (sendCbit): cbit '{cbit_label}' referenced before createCbit")
                for field in ("from", "to"):
                    ref = ev.get(field)
                    if ref and ref not in known_nodes:
                        issues.append(f"Event #{idx} (sendCbit): '{field}' references unknown node '{ref}'")

            elif ev_type == "sendPacket":
                for field in ("from", "to"):
                    ref = ev.get(field)
                    if ref and ref not in known_nodes:
                        issues.append(f"Event #{idx} (sendPacket): '{field}' references unknown node '{ref}'")

            elif ev_type == "entangle":
                for qubit_label in ev.get("bits", []):
                    if qubit_label not in known_bits:
                        issues.append(
                            f"Event #{idx} (entangle): qubit '{qubit_label}' referenced before createQubit"
                        )
                issues.extend(
                    self._window_issues(idx, ev_type, t, ev.get("duration_ns"), ev.get("bits", []), known_bits)
                )

        return issues

    @staticmethod
    def _window_issues(
        idx: int, ev_type: str, t: int | None, duration: int | None, bits: list[str], known_bits: dict[str, int]
    ) -> list[str]:
        """Check one durationed event's back-window ``[t - duration, t)`` for acausality."""
        issues: list[str] = []
        if t is None or not duration or duration <= 0:
            return issues
        t_start = t - duration
        if t_start < 0:
            issues.append(
                f"Event #{idx} ({ev_type}): duration_ns={duration} exceeds t_ns={t} "
                f"— processing window clipped at t=0"
            )
        for bit in bits:
            created = known_bits.get(bit)
            if created is not None and t_start < created:
                issues.append(
                    f"Event #{idx} ({ev_type}): window [{t_start}, {t}) starts before "
                    f"createQubit of '{bit}' at t_ns={created} — acausal duration_ns"
                )
        return issues

    # -- Replay engine ------------------------------------------------------

    def _build_actions(self) -> None:
        """Compile ``self.events`` into a time-sorted list of atomic state actions.

        Each action is ``(t_ns, event_idx, phase, kind, event)``.  Sorting by
        ``(t_ns, event_idx, phase)`` preserves the file order of same-time
        events, so order-sensitive semantics (``entangle`` toggling, measured
        guards) replay exactly as in ``_snapshot_at_uncached()`` for
        chronologically consistent traces.  Events with a ``duration_ns``
        window expand into start/end actions that maintain the operation-ring
        sets; transfers expand into departure/arrival actions.  Malformed
        events are warned about once here and skipped.
        @ingroup q2nsviz_engine
        """
        actions: list[tuple[int, int, int, str, dict[str, Any]]] = []
        for idx, event in enumerate(self.events):
            event_type = event.get("type")
            t = event.get("t_ns", 0)

            if event_type == "createQubit":
                if not event.get("label"):
                    logger.warning("createQubit event missing 'label': %s", event)
                    continue
                actions.append((t, idx, 0, "createQubit", event))

            elif event_type == "createCbit":
                if not event.get("label"):
                    logger.warning("createCbit event missing 'label': %s", event)
                    continue
                actions.append((t, idx, 0, "createCbit", event))

            elif event_type == "sendQubit":
                if not event.get("bit"):
                    logger.warning("sendQubit event missing 'bit': %s", event)
                    continue
                actions.append((event.get("t0_ns", 0), idx, 0, "transitStartQubit", event))
                t1 = event.get("t1_ns")
                if t1 is not None:
                    actions.append((t1, idx, 1, "arriveEndQubit", event))
                else:
                    # Missing t1_ns: the reference replay sets the node from
                    # t=0 on and never closes the transit window.
                    actions.append((0, idx, 1, "arriveQubit", event))

            elif event_type == "sendCbit":
                if not event.get("bit"):
                    logger.warning("sendCbit event missing 'bit': %s", event)
                    continue
                actions.append((event.get("t0_ns", 0), idx, 0, "transitStartCbit", event))
                t1 = event.get("t1_ns")
                if t1 is not None:
                    actions.append((t1, idx, 1, "arriveEndCbit", event))
                else:
                    actions.append((0, idx, 1, "arriveCbit", event))

            elif event_type == "entangle":
                duration = event.get("duration_ns", 0) or 0
                if duration > 0:
                    actions.append((max(0, t - duration), idx, 0, "gateStart", event))
                    actions.append((t, idx, 1, "gateEnd", event))
                actions.append((t, idx, 2, "entangleCommit", event))

            elif event_type == "measure":
                duration = event.get("duration_ns", 0) or 0
                if duration > 0:
                    actions.append((max(0, t - duration), idx, 0, "measureStart", event))
                    actions.append((t, idx, 1, "measureEnd", event))
                actions.append((t, idx, 2, "measureCommit", event))

            elif event_type == "graphMeasure":
                duration = event.get("duration_ns", 0) or 0
                if duration > 0:
                    actions.append((max(0, t - duration), idx, 0, "graphMeasureStart", event))
                    actions.append((t, idx, 1, "graphMeasureEnd", event))
                actions.append((t, idx, 2, "graphMeasureCommit", event))

            elif event_type == "removeQubit":
                if not event.get("bit"):
                    logger.warning("removeQubit event missing 'bit': %s", event)
                    continue
                actions.append((t, idx, 0, "removeQubit", event))

            elif event_type == "removeCbit":
                if not event.get("bit"):
                    logger.warning("removeCbit event missing 'bit': %s", event)
                    continue
                actions.append((t, idx, 0, "removeCbit", event))

        actions.sort(key=lambda a: (a[0], a[1], a[2]))
        self._actions = actions

    @staticmethod
    def _counter_inc(counter: dict[str, int], key: str) -> None:
        counter[key] = counter.get(key, 0) + 1

    @staticmethod
    def _counter_dec(counter: dict[str, int], key: str) -> None:
        n = counter.get(key, 0)
        if n <= 1:
            counter.pop(key, None)
        else:
            counter[key] = n - 1

    def _apply_action(self, kind: str, event: dict[str, Any]) -> None:
        """Apply one atomic action to the live replay state."""
        if kind == "createQubit":
            label = event["label"]
            self.qubits[label] = Qubit(label=label, node=event.get("node"))
        elif kind == "createCbit":
            label = event["label"]
            self.cbits[label] = ClassicalBit(label=label, node=event.get("node"))
        elif kind == "transitStartQubit":
            self._counter_inc(self._win_inflight_qubits, event["bit"])
        elif kind == "arriveEndQubit":
            bit = event["bit"]
            if bit in self.qubits:
                self.qubits[bit].node = event.get("to")
            self._counter_dec(self._win_inflight_qubits, bit)
        elif kind == "arriveQubit":
            bit = event["bit"]
            if bit in self.qubits:
                self.qubits[bit].node = event.get("to")
        elif kind == "transitStartCbit":
            self._counter_inc(self._win_inflight_cbits, event["bit"])
        elif kind == "arriveEndCbit":
            bit = event["bit"]
            if bit in self.cbits:
                self.cbits[bit].node = event.get("to")
            self._counter_dec(self._win_inflight_cbits, bit)
        elif kind == "arriveCbit":
            bit = event["bit"]
            if bit in self.cbits:
                self.cbits[bit].node = event.get("to")
        elif kind == "gateStart":
            for label in event.get("bits", []):
                self._counter_inc(self._win_gate, label)
        elif kind == "gateEnd":
            for label in event.get("bits", []):
                self._counter_dec(self._win_gate, label)
        elif kind == "entangleCommit":
            labels = event.get("bits", [])
            for i in range(len(labels)):
                for j in range(i + 1, len(labels)):
                    self._ent_graph_add_edge(labels[i], labels[j])
        elif kind == "measureStart":
            bit = event.get("bit")
            if bit:
                self._counter_inc(self._win_measuring, bit)
        elif kind == "measureEnd":
            bit = event.get("bit")
            if bit:
                self._counter_dec(self._win_measuring, bit)
        elif kind == "measureCommit":
            bit = event.get("bit")
            if bit:
                self.measured_qubits.add(bit)
            self._ent_graph_remove_vertex(bit)
        elif kind == "graphMeasureStart":
            bit = event.get("bit")
            if bit:
                self._counter_inc(self._win_graph_measuring, bit)
        elif kind == "graphMeasureEnd":
            bit = event.get("bit")
            if bit:
                self._counter_dec(self._win_graph_measuring, bit)
        elif kind == "graphMeasureCommit":
            target = event.get("bit")
            if target:
                self.measured_qubits.add(target)
            self._perform_graph_measurement(target, event.get("base", "Z"), event.get("supportNode"))
        elif kind == "removeQubit":
            bit = event["bit"]
            self.removed_qubits.add(bit)
            if event.get("reason") == "discarded":
                self.discarded_qubits.add(bit)
            self._ent_graph_remove_vertex(bit)
        elif kind == "removeCbit":
            self.removed_cbits.add(event["bit"])

    def _clear_replay_state(self) -> None:
        """Reset the live replay state to the pre-simulation (t < 0) state."""
        self.qubits.clear()
        self.cbits.clear()
        self.ent_graph.clear()
        self.measured_qubits.clear()
        self.removed_qubits.clear()
        self.discarded_qubits.clear()
        self.removed_cbits.clear()
        self._win_inflight_qubits.clear()
        self._win_inflight_cbits.clear()
        self._win_gate.clear()
        self._win_measuring.clear()
        self._win_graph_measuring.clear()

    def _capture_snapshot(self) -> _StateSnapshot:
        """Copy the live replay state into an immutable checkpoint."""
        return _StateSnapshot(
            qubits={k: Qubit(label=v.label, node=v.node) for k, v in self.qubits.items()},
            cbits={k: ClassicalBit(label=v.label, node=v.node) for k, v in self.cbits.items()},
            ent_graph={k: frozenset(v) for k, v in self.ent_graph.items()},
            measured_qubits=frozenset(self.measured_qubits),
            removed_qubits=frozenset(self.removed_qubits),
            discarded_qubits=frozenset(self.discarded_qubits),
            removed_cbits=frozenset(self.removed_cbits),
            inflight_qubits=dict(self._win_inflight_qubits),
            inflight_cbits=dict(self._win_inflight_cbits),
            gate_qubits=dict(self._win_gate),
            measuring_qubits=dict(self._win_measuring),
            graph_measuring_qubits=dict(self._win_graph_measuring),
        )

    def _restore_snapshot(self, snap: _StateSnapshot) -> None:
        """Replace the live replay state with fresh mutable copies of *snap*."""
        self.qubits = {k: Qubit(label=v.label, node=v.node) for k, v in snap.qubits.items()}
        self.cbits = {k: ClassicalBit(label=v.label, node=v.node) for k, v in snap.cbits.items()}
        self.ent_graph = defaultdict(set, {k: set(v) for k, v in snap.ent_graph.items()})
        self.measured_qubits = set(snap.measured_qubits)
        self.removed_qubits = set(snap.removed_qubits)
        self.discarded_qubits = set(snap.discarded_qubits)
        self.removed_cbits = set(snap.removed_cbits)
        self._win_inflight_qubits = dict(snap.inflight_qubits)
        self._win_inflight_cbits = dict(snap.inflight_cbits)
        self._win_gate = dict(snap.gate_qubits)
        self._win_measuring = dict(snap.measuring_qubits)
        self._win_graph_measuring = dict(snap.graph_measuring_qubits)

    def _build_checkpoints(self) -> None:
        """Replay the action stream once, storing sparse checkpoints.

        A checkpoint is stored after roughly every ``_CHECKPOINT_INTERVAL``
        applied actions, always on a boundary between distinct timestamps so
        that a restored checkpoint reflects every action at its time.  Memory
        is O(actions / interval) snapshots; traces shorter than the interval
        store none and replay from the empty state on demand.

        Called automatically at the end of ``load_events()``.  Leaves the
        live state cleared; ``snapshot_at()`` positions it on first use.
        @ingroup q2nsviz_engine
        """
        self._checkpoints.clear()
        self._checkpoint_times.clear()
        self._clear_replay_state()
        actions = self._actions
        n = len(actions)
        i = 0
        since_checkpoint = 0
        while i < n:
            t_block = actions[i][0]
            while i < n and actions[i][0] == t_block:
                self._apply_action(actions[i][3], actions[i][4])
                i += 1
                since_checkpoint += 1
            if since_checkpoint >= self._CHECKPOINT_INTERVAL and i < n:
                self._checkpoint_times.append(t_block)
                self._checkpoints.append((i, self._capture_snapshot()))
                since_checkpoint = 0
        self._clear_replay_state()
        self._cursor = None

    # -- State reduction ----------------------------------------------------

    def _make_snapshot(
        self,
        t_ns: int,
        *,
        inflight_qubits: Iterable[str],
        gate_qubits: Iterable[str],
        measuring_qubits: Iterable[str],
        graph_measuring_qubits: Iterable[str],
        inflight_cbits: Iterable[str],
    ) -> Snapshot:
        """Package the current live replay state as an immutable ``Snapshot``.

        A pure function of the live state: both the incremental engine
        (``snapshot_at()``) and the from-scratch reference
        (``_snapshot_at_uncached()``) position the state independently and
        then delegate here, so shared packaging cannot mask a divergence
        between the two replay paths.  The operation-window sets are computed
        by each caller and passed in.  Empty adjacency entries are dropped
        from ``ent_graph`` and entangled components are keyed by their
        smallest member, so snapshots from the two paths compare equal
        whenever the underlying state matches.
        @ingroup q2nsviz_engine
        """
        measured = frozenset(self.measured_qubits)
        removed = frozenset(self.removed_qubits)
        discarded = frozenset(self.discarded_qubits)
        groups = self.get_entangled_states()
        return Snapshot(
            t_ns=t_ns,
            nodes=self.nodes,
            channels=self.channels,
            qubits={k: Qubit(label=v.label, node=v.node) for k, v in self.qubits.items()},
            cbits={k: ClassicalBit(label=v.label, node=v.node) for k, v in self.cbits.items()},
            ent_graph={q: frozenset(nbrs) for q, nbrs in self.ent_graph.items() if nbrs},
            entangled_states={min(members): tuple(sorted(members)) for members in groups.values()},
            measured_qubits=measured,
            removed_qubits=removed,
            discarded_qubits=discarded,
            lost_qubits=removed - measured - discarded,
            live_qubit_labels=frozenset(q for q in self.qubits if q not in removed and q not in measured),
            inflight_qubits=frozenset(inflight_qubits),
            inflight_cbits=frozenset(inflight_cbits),
            gate_qubits=frozenset(gate_qubits),
            measuring_qubits=frozenset(measuring_qubits),
            graph_measuring_qubits=frozenset(graph_measuring_qubits),
            removed_cbits=frozenset(self.removed_cbits),
        )

    def seek(self, t_ns: int) -> None:
        """Position the replay state at *t_ns* without packaging a ``Snapshot``.

        Moving forward in time continues incrementally from the last queried
        position; moving backward restores the nearest checkpoint at or before
        *t_ns* and replays the gap (at most ``_CHECKPOINT_INTERVAL`` actions
        after a restore).  Valid for arbitrary timestamps, not only keyframes
        in ``time_array``.

        This is the O(advanced-actions) positioning primitive shared by
        ``snapshot_at()``.  Use it directly for bulk timeline scans where the
        O(#qubits) packaging cost of a full ``Snapshot`` per step would
        dominate, then read the query helpers (``get_entangled_states()``
        and friends) on the positioned state.

        @param t_ns  Simulation timestamp in nanoseconds.
        @ingroup q2nsviz_engine
        """
        actions = self._actions
        if self._cursor is not None and t_ns >= self._cursor[0]:
            i = self._cursor[1]
        else:
            pos = bisect.bisect_right(self._checkpoint_times, t_ns) - 1
            if pos >= 0:
                i, snap = self._checkpoints[pos]
                self._restore_snapshot(snap)
            else:
                self._clear_replay_state()
                i = 0
        n = len(actions)
        while i < n and actions[i][0] <= t_ns:
            self._apply_action(actions[i][3], actions[i][4])
            i += 1
        self._cursor = (t_ns, i)

    def snapshot_at(self, t_ns: int) -> Snapshot:
        """Advance or restore the replay state to *t_ns* and return a ``Snapshot``.

        Positions the state via ``seek()`` and packages it as an immutable
        ``Snapshot``.  This is the per-instant entry point used by the
        ``QuantumVisualizerWindow`` controller and by scripts.

        ``_snapshot_at_uncached()`` is retained as the from-scratch reference
        implementation and produces identical results for chronologically
        consistent traces.

        @param t_ns  Simulation timestamp in nanoseconds.
        @returns     ``Snapshot`` of the reconstructed state at *t_ns*.
        @ingroup q2nsviz_engine
        """
        self.seek(t_ns)
        return self._make_snapshot(
            t_ns,
            inflight_qubits=self._win_inflight_qubits,
            gate_qubits=self._win_gate,
            measuring_qubits=self._win_measuring,
            graph_measuring_qubits=self._win_graph_measuring,
            inflight_cbits=self._win_inflight_cbits,
        )

    def _snapshot_at_uncached(self, t_ns: int) -> Snapshot:
        """Replay all events up to *t_ns* from scratch and return a ``Snapshot``.

        The from-scratch reference implementation used to verify the incremental
        replay engine; normal playback uses ``snapshot_at()``.  Durationed events
        (``entangle``, ``measure``, ``graphMeasure``) are stamped at operation
        completion: the state transition commits at ``t_ns``, with the operation
        ring shown during ``[t_ns - duration_ns, t_ns)``.  O(N) in the number of
        events.

        @param t_ns  Simulation timestamp in nanoseconds.
        @returns     ``Snapshot`` of the reconstructed state at *t_ns*.
        """
        # From-scratch replay leaves the incremental cursor stale; invalidate it
        # so a later snapshot_at() restores from a checkpoint instead.
        self._cursor = None
        self.qubits.clear()
        self.cbits.clear()
        self.ent_graph.clear()
        self.measured_qubits.clear()
        self.removed_qubits.clear()
        self.discarded_qubits.clear()
        self.removed_cbits.clear()
        inflight_qubits: set[str] = set()
        inflight_cbits: set[str] = set()
        gate_qubits: set[str] = set()
        measuring_qubits: set[str] = set()
        graph_measuring_qubits: set[str] = set()

        for event in self.events:
            event_type = event.get("type")
            event_t = event.get("t_ns", 0)

            if event_type == "createQubit" and event_t <= t_ns:
                label = event.get("label")
                if not label:
                    logger.warning("createQubit event missing 'label': %s", event)
                    continue
                qubit = Qubit(label=label, node=event.get("node"))
                self.qubits[label] = qubit

            elif event_type == "sendQubit":
                qubit_label = event.get("bit")
                if not qubit_label:
                    logger.warning("sendQubit event missing 'bit': %s", event)
                    continue
                if event.get("t1_ns", 0) <= t_ns and qubit_label in self.qubits:
                    self.qubits[qubit_label].node = event.get("to")
                if event.get("t0_ns", 0) <= t_ns < event.get("t1_ns", float("inf")):
                    inflight_qubits.add(qubit_label)

            elif event_type == "createCbit" and event_t <= t_ns:
                label = event.get("label")
                if not label:
                    logger.warning("createCbit event missing 'label': %s", event)
                    continue
                cbit = ClassicalBit(label=label, node=event.get("node"))
                self.cbits[label] = cbit

            elif event_type == "sendCbit":
                cbit_label = event.get("bit")
                if not cbit_label:
                    logger.warning("sendCbit event missing 'bit': %s", event)
                    continue
                if event.get("t1_ns", 0) <= t_ns and cbit_label in self.cbits:
                    self.cbits[cbit_label].node = event.get("to")
                if event.get("t0_ns", 0) <= t_ns < event.get("t1_ns", float("inf")):
                    inflight_cbits.add(cbit_label)

            elif event_type == "entangle":
                duration_ns = event.get("duration_ns", 0) or 0
                t_start = max(0, event_t - duration_ns)
                # The duration window marks the gate's processing time (the halo);
                # the entanglement edges themselves commit at event_t below.
                if t_start <= t_ns < event_t:
                    for qubit_label in event.get("bits", []):
                        gate_qubits.add(qubit_label)
                if event_t <= t_ns:
                    qubit_labels = event.get("bits", [])
                    for i in range(len(qubit_labels)):
                        for j in range(i + 1, len(qubit_labels)):
                            self._ent_graph_add_edge(qubit_labels[i], qubit_labels[j])

            elif event_type == "measure":
                duration_ns = event.get("duration_ns", 0) or 0
                t_start = max(0, event_t - duration_ns)
                if t_start <= t_ns < event_t:
                    qubit_label = event.get("bit")
                    if qubit_label:
                        measuring_qubits.add(qubit_label)
                if event_t <= t_ns:
                    qubit_label = event.get("bit")
                    if qubit_label:
                        self.measured_qubits.add(qubit_label)
                    self._ent_graph_remove_vertex(qubit_label)

            elif event_type == "graphMeasure":
                duration_ns = event.get("duration_ns", 0) or 0
                t_start = max(0, event_t - duration_ns)
                if t_start <= t_ns < event_t:
                    target = event.get("bit")
                    if target:
                        graph_measuring_qubits.add(target)
                if event_t <= t_ns:
                    target = event.get("bit")
                    if target:
                        self.measured_qubits.add(target)
                    self._perform_graph_measurement(target, event.get("base", "Z"), event.get("supportNode"))

            elif event_type == "removeQubit" and event_t <= t_ns:
                qubit_label = event.get("bit")
                if not qubit_label:
                    logger.warning("removeQubit event missing 'bit': %s", event)
                    continue
                self.removed_qubits.add(qubit_label)
                if event.get("reason") == "discarded":
                    self.discarded_qubits.add(qubit_label)
                self._ent_graph_remove_vertex(qubit_label)

            elif event_type == "removeCbit" and event_t <= t_ns:
                cbit_label = event.get("bit")
                if not cbit_label:
                    logger.warning("removeCbit event missing 'bit': %s", event)
                    continue
                self.removed_cbits.add(cbit_label)

        return self._make_snapshot(
            t_ns,
            inflight_qubits=inflight_qubits,
            gate_qubits=gate_qubits,
            measuring_qubits=measuring_qubits,
            graph_measuring_qubits=graph_measuring_qubits,
            inflight_cbits=inflight_cbits,
        )

    # --- Entanglement graph helpers -----------------------------------------

    def _ent_graph_add_edge(self, qubit1: str, qubit2: str):
        """Toggle the entanglement edge between *qubit1* and *qubit2*.

        Models a generic entangling operation: applying it twice is the
        identity, so a second ``entangle`` event on the same pair
        dis-entangles them.
        """
        if qubit1 in self.measured_qubits or qubit2 in self.measured_qubits:
            logger.warning("Ignoring entangle event: %s or %s is already measured", qubit1, qubit2)
            return
        if qubit1 in self.removed_qubits or qubit2 in self.removed_qubits:
            logger.warning("Ignoring entangle event: %s or %s is already removed/lost", qubit1, qubit2)
            return
        if qubit2 in self.ent_graph.get(qubit1, set()):
            self.ent_graph[qubit1].discard(qubit2)
            self.ent_graph[qubit2].discard(qubit1)
        else:
            self.ent_graph[qubit1].add(qubit2)
            self.ent_graph[qubit2].add(qubit1)

    def _ent_graph_remove_vertex(self, qubit: str):
        """Remove *qubit* from the entanglement graph and clean up its edges."""
        if qubit in self.ent_graph:
            for connected in self.ent_graph[qubit]:
                if connected in self.ent_graph:
                    self.ent_graph[connected].discard(qubit)
            del self.ent_graph[qubit]

    def _ent_graph_local_complement(self, target: str):
        """Toggle all edges between neighbors of *target* (graph-state LC op)."""
        if target not in self.ent_graph:
            logger.warning("Qubit %s not found in entanglement graph", target)
            return

        neighbors = list(self.ent_graph[target])
        logger.debug("Local complementation on %s, neighbors: %s", target, neighbors)

        for i in range(len(neighbors)):
            for j in range(i + 1, len(neighbors)):
                n1, n2 = neighbors[i], neighbors[j]
                if n2 in self.ent_graph.get(n1, set()):
                    self.ent_graph[n1].discard(n2)
                    self.ent_graph[n2].discard(n1)
                    logger.debug("  Removed edge: [%s, %s]", n1, n2)
                else:
                    self.ent_graph[n1].add(n2)
                    self.ent_graph[n2].add(n1)
                    logger.debug("  Added edge: [%s, %s]", n1, n2)

    def _perform_graph_measurement(self, target: str, basis: str, support_node: str | None = None):
        """Execute a graph-state measurement in the given Pauli basis."""
        basis = basis.upper()

        if basis == "Z":
            logger.info("Graph-state Z measurement on %s", target)
            self._ent_graph_remove_vertex(target)

        elif basis == "Y":
            logger.info("Graph-state Y measurement on %s", target)
            self._ent_graph_local_complement(target)
            self._ent_graph_remove_vertex(target)

        elif basis == "X":
            logger.info("Graph-state X measurement on %s", target)
            if target not in self.ent_graph:
                logger.warning("Qubit %s not found in entanglement graph", target)
                return
            neighbors = sorted(self.ent_graph[target])
            if neighbors:
                if support_node is None or support_node not in neighbors:
                    logger.warning(
                        "graphMeasure on '%s' (X-basis): no valid supportNode in trace "
                        "(got %r, neighbors: %s). Falling back to alphabetical ('%s'). "
                        "Displayed topology may differ from the simulator's "
                        "internal representation.",
                        target,
                        support_node,
                        neighbors,
                        neighbors[0],
                    )
                    support_node = neighbors[0]
                logger.debug("Adjacent: %s, support node: %s", neighbors, support_node)
                self._ent_graph_local_complement(support_node)
                self._ent_graph_local_complement(target)
                self._ent_graph_remove_vertex(target)
                self._ent_graph_local_complement(support_node)
            else:
                self._ent_graph_remove_vertex(target)
                logger.debug("Qubit %s had no neighbors; removed", target)

        else:
            logger.warning("Unknown basis '%s', defaulting to Z measurement", basis)
            self._ent_graph_remove_vertex(target)

    # --- Query helpers ------------------------------------------------------

    def get_entanglement_groups(self) -> dict[str, list[str]]:
        """Return all entanglement components as ``{root: [members]}``.

        Must be called *after* ``snapshot_at(t_ns)`` so that ``ent_graph``
        and ``qubits`` reflect the desired simulation time.

        Computes connected components of ``ent_graph`` via
        ``UnionFind``, excluding measured and removed qubits.  The result
        therefore correctly reflects graph-state measurements (X/Y/Z) and
        any bridge qubits whose removal splits the graph.

        @returns  Dictionary mapping each component root label to the
                  sorted list of qubit labels in that component.
        """
        gone = self.removed_qubits | self.measured_qubits
        uf = UnionFind()
        for q in self.qubits:
            if q not in gone:
                uf.find(q)
        for q, neighbors in self.ent_graph.items():
            if q in gone:
                continue
            for nbr in neighbors:
                if nbr not in gone:
                    uf.union(q, nbr)
        return dict(uf.groups())

    def get_entangled_states(self) -> dict[str, list[str]]:
        """Return entanglement components with two or more qubits.

        Traverses only the entanglement graph, so the cost scales with the
        number of live entanglement edges rather than with every qubit
        created so far (``get_entanglement_groups()`` also enrolls singleton
        components and therefore scans the full qubit registry).

        @returns  ``{root: members}`` for every component with two or more
                  qubits; equal, as member sets, to filtering
                  ``get_entanglement_groups()`` by ``len(members) >= 2``.
        """
        # Excluding "measured or lost" qubits reduces to "measured or removed";
        # plain membership tests avoid an O(all qubits) set subtraction per call.
        uf = UnionFind()
        for q, neighbors in self.ent_graph.items():
            if q in self.measured_qubits or q in self.removed_qubits:
                continue
            for nbr in neighbors:
                if nbr not in self.measured_qubits and nbr not in self.removed_qubits:
                    uf.union(q, nbr)
        return {root: members for root, members in uf.groups().items() if len(members) > 1}

    def log_count_at(self, t_ns: int) -> int:
        """Return how many ``traceText`` events have a timestamp <= *t_ns*.

        The log grows monotonically with time, so the GUI uses this count to
        append only the new lines instead of rebuilding the whole log view.

        @param t_ns  Cut-off time in nanoseconds.
        @returns     Index into ``log_events`` one past the last visible entry.
        """
        return bisect.bisect_right(self._log_times, t_ns)

    def get_log_events(self, t_ns: int) -> list[dict[str, Any]]:
        """Return all ``traceText`` events with timestamp <= *t_ns*, in time order.

        @param t_ns  Cut-off time in nanoseconds.
        @returns     List of event dicts with ``type == "traceText"``.
        """
        return self.log_events[: self.log_count_at(t_ns)]


# ---------------------------------------------------------------------------
# Event file parser
# ---------------------------------------------------------------------------


class EventFileParser:
    """Reads Q2NS simulation trace files in NDJSON or JSON-array format.

    Both formats are auto-detected by inspecting the first non-whitespace
    character of the content string:

    - JSON array: content begins with ``[``; the entire file is parsed as
      a single ``json.loads`` call.
    - NDJSON: each non-empty line is an independent JSON object.
    @ingroup q2nsviz_engine
    """

    @staticmethod
    def parse(content: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse a string containing a Q2NS trace in NDJSON or JSON-array format.

        @param content  Raw file content as a Unicode string.
        @returns        ``(events, errors)`` where *events* is the list of
                        successfully parsed event dicts and *errors* lists any
                        human-readable parse failures (empty on success).
        """
        content = content.strip()
        if not content:
            return [], []

        if content.startswith("["):
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    return data, []
            except json.JSONDecodeError as exc:
                logger.error("Failed to parse JSON array: %s", exc)
                return [], [f"JSON array parse error: {exc}"]

        events: list[dict[str, Any]] = []
        errors: list[str] = []
        for line_no, line in enumerate(content.split("\n"), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                msg = f"Line {line_no}: {exc}"
                logger.error("NDJSON parse error: %s", msg)
                errors.append(msg)
        return events, errors

    @staticmethod
    def load_from_file(filepath: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Read a simulation trace file from disk and delegate to ``parse()``.

        @param filepath  Absolute or relative path to the trace file.
                         Must be UTF-8 encoded.
        @returns         Same ``(events, errors)`` tuple as ``parse()``.
        @warning         Raises ``OSError`` if the file cannot be opened.
        """
        with open(filepath, encoding="utf-8") as fh:
            return EventFileParser.parse(fh.read())
