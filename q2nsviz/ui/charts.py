# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

import bisect
import logging

from .theme import is_dark

try:
    import matplotlib

    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import FixedLocator

    from ..logic import SimulationStateManager as _SimulationStateManager

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logging.getLogger(__name__).warning("matplotlib not available -- chart tab will be disabled")


if MATPLOTLIB_AVAILABLE:

    def _expand_series(
        times: list[int], values: list[float], operation_windows: set[tuple[int, int]]
    ) -> tuple[list[int], list[float]]:
        """Convert keyframe arrays into a step-function suitable for plotting.

        Interior points that fall inside an operation window are left as-is so
        that the linear ramp inserted by ``_rebuild_series`` is preserved.
        All other value changes produce a duplicate x-point at the next
        timestamp (step function).

        @param times             Keyframe timestamps in nanoseconds.
        @param values            Series value at each keyframe.
        @param operation_windows Set of ``(t_start_ns, t_end_ns)`` operation duration
                                 windows (entangle / measure / graphMeasure).
        @returns                 Tuple of ``(xs, ys)`` lists ready for plotting.
        """
        xs: list[int] = []
        ys: list[float] = []
        for i in range(len(times)):
            xs.append(times[i])
            ys.append(values[i])
            if i < len(times) - 1:
                t_c, t_n = times[i], times[i + 1]
                v_c, v_n = values[i], values[i + 1]
                in_window = any(t0 <= t_c and t_n <= t1 for t0, t1 in operation_windows)
                if not in_window and v_c != v_n:
                    xs.append(t_n)
                    ys.append(v_c)
        return xs, ys

    def _live_qubit_series(events: list[dict], times: list[int]) -> list[float]:
        """Per-keyframe live-qubit counts from a single pass over the events.

        A qubit is live from its first ``createQubit`` to its first
        ``measure`` / ``graphMeasure`` / ``removeQubit`` event, matching
        ``Snapshot.live_qubit_labels`` without an O(all qubits) registry scan
        per keyframe.

        @param events  Full trace event list.
        @param times   Sorted keyframe timestamps to evaluate.
        @returns       Live-qubit count at each timestamp in *times*.
        """
        birth: dict[str, int] = {}
        death: dict[str, int] = {}
        for event in events:
            event_type = event.get("type")
            if event_type == "createQubit":
                label = event.get("label")
                if label:
                    t = event.get("t_ns", 0)
                    if label not in birth or t < birth[label]:
                        birth[label] = t
            elif event_type in {"measure", "graphMeasure", "removeQubit"}:
                label = event.get("bit")
                if label:
                    # Commit-anchored stamps: the transition lands at t_ns.
                    t = event.get("t_ns", 0)
                    if label not in death or t < death[label]:
                        death[label] = t
        births = sorted(birth.values())
        # A death before the qubit's creation takes effect at creation time.
        deaths = sorted(max(t, birth[label]) for label, t in death.items() if label in birth)
        return [float(bisect.bisect_right(births, t) - bisect.bisect_right(deaths, t)) for t in times]

    def _make_ticks(lo, hi, n_inner=2, integer=False):
        """Return a tick list that always contains lo and hi with ~n_inner interior ticks."""
        if lo == hi:
            return [lo]
        if integer:
            lo, hi = int(lo), int(hi)
            if hi - lo <= n_inner + 1:
                return list(range(lo, hi + 1))
            inner = sorted({round(lo + (hi - lo) * i / (n_inner + 1)) for i in range(1, n_inner + 1)} - {lo, hi})
            return [lo, *inner, hi]
        inner = [lo + (hi - lo) * i / (n_inner + 1) for i in range(1, n_inner + 1)]
        return [lo, *inner, hi]

    class ChartCanvas(FigureCanvasQTAgg):
        """Matplotlib canvas for time-series and summary charts.

        @ingroup q2nsviz_charts
        """

        def __init__(self):
            self.fig = Figure(figsize=(5.2, 10), facecolor="white")
            super().__init__(self.fig)
            self.setMinimumHeight(480)
            # Cached time series --- rebuilt only when a new file is loaded.
            # Cache key is the *identity* of state_manager.time_array (not
            # equality), so any new load() replaces the list object and
            # triggers a rebuild automatically.
            self._cached_time_array: list[int] | None = None
            self._cached_live: list[float] = []
            self._cached_entangled: list[float] = []
            self._cached_measurements: list[float] = []
            self._cached_operation_windows: set[tuple[int, int]] = set()

        def clear(self):
            """Clear the figure and redraw an empty canvas."""
            self.fig.clear()
            self.draw()

        def _rebuild_series(self, state_manager) -> None:
            """Pre-compute time-series arrays for all keyframes.

            Uses an isolated ``SimulationStateManager`` instance so that the
            shared state manager is never mutated during series computation.
            The shared instance is accessed read-only for its event list;
            the timeline sweep positions the private copy via ``seek()`` --
            the same reconstruction path as ``snapshot_at()``.

            @param state_manager  Shared ``SimulationStateManager`` from the window.
                                  Accessed read-only within this method.
            """
            _sm = _SimulationStateManager()
            _sm.load_events(state_manager.events)

            measurement_times = sorted(
                event.get("t_ns", 0)
                for event in _sm.events
                if event.get("type") in {"measure", "graphMeasure"} and event.get("t_ns") is not None
            )
            # Live-qubit counts come from a single event pass; only the
            # entanglement series needs the per-keyframe state sweep.
            live_qubits = _live_qubit_series(_sm.events, _sm.time_array)
            entangled_states: list[float] = []
            total_measurements: list[float] = []
            measurement_index = 0
            measurement_total = 0

            for t in _sm.time_array:
                # seek() shares snapshot_at()'s positioning path but skips the
                # per-step Snapshot packaging, keeping the sweep O(actions).
                _sm.seek(t)
                while measurement_index < len(measurement_times) and measurement_times[measurement_index] <= t:
                    measurement_total += 1
                    measurement_index += 1

                entangled_states.append(float(len(_sm.get_entangled_states())))
                total_measurements.append(float(measurement_total))

            # Operation-window linear interpolation: smooth the step changes across
            # operation durations so the series does not show a hard jump mid-operation.
            time_to_idx = {t: i for i, t in enumerate(_sm.time_array)}
            operation_windows: set[tuple[int, int]] = set()
            for ev in _sm.events:
                if ev.get("type") not in {"entangle", "measure", "graphMeasure"}:
                    continue
                dur = ev.get("duration_ns", 0)
                t_end = ev.get("t_ns")
                if not dur or t_end is None:
                    continue
                t_start = max(0, t_end - dur)
                operation_windows.add((t_start, t_end))
                i0 = time_to_idx.get(t_start)
                i1 = time_to_idx.get(t_end)
                if i0 is None or i1 is None or i0 >= i1:
                    continue
                live_start, live_end = live_qubits[i0], live_qubits[i1]
                entangled_start, entangled_end = entangled_states[i0], entangled_states[i1]
                meas_start, meas_end = total_measurements[i0], total_measurements[i1]
                for i in range(i0 + 1, i1):
                    frac = (_sm.time_array[i] - t_start) / (t_end - t_start)
                    live_qubits[i] = live_start + frac * (live_end - live_start)
                    entangled_states[i] = entangled_start + frac * (entangled_end - entangled_start)
                    total_measurements[i] = meas_start + frac * (meas_end - meas_start)

            self._cached_live = live_qubits
            self._cached_entangled = entangled_states
            self._cached_measurements = total_measurements
            self._cached_operation_windows = operation_windows
            self._cached_time_array = state_manager.time_array

        def update_charts(self, state_manager, snap):
            """Render all four chart panels for the given simulation time.

            Chart layout (top to bottom)
            ----------------------------
            1. Live qubit count over time (step function).
            2. Entangled states over time (step function).
            3. Total measurements over time (step function).
            4. Per-node qubit distribution at ``snap.t_ns`` (bar chart).

            Cached series are rebuilt only when a new trace is loaded, detected
            by an identity change on ``state_manager.time_array``.  The shared
            state manager is never queried here: the controller performs the
            per-frame ``snapshot_at()`` call and passes the resulting
            ``Snapshot``, which drives both the bar chart and the current-time
            marker.

            @param state_manager  Shared ``SimulationStateManager`` instance,
                                  read only for its event list and timeline.
            @param snap           ``Snapshot`` at the current simulation time.
            """
            current_time = snap.t_ns
            self.fig.clear()
            _dark = is_dark()
            _fig_bg = "#161b22" if _dark else "#ffffff"
            _ax_bg = "#1c2128" if _dark else "#ffffff"
            _spine_c = "#8d96a0" if _dark else "#24292f"
            _grid_c = "#30363d" if _dark else "#f0f2f5"
            _text_c = "#e6edf3" if _dark else "#24292f"
            _marker_c = "#8d96a0" if _dark else "#555555"
            self.fig.set_facecolor(_fig_bg)
            if not state_manager.time_array:
                return
            if self._cached_time_array is not state_manager.time_array:
                self._rebuild_series(state_manager)

            live_qubits = self._cached_live
            entangled_states = self._cached_entangled
            total_measurements = self._cached_measurements
            operation_windows = self._cached_operation_windows

            current_node_qubits: dict[str, int] = {
                node_name: sum(
                    1
                    for q in snap.qubits.values()
                    if q.node == node_name
                    and q.label in snap.live_qubit_labels
                    and q.label not in snap.inflight_qubits
                )
                for node_name in snap.nodes
            }
            current_inflight_count: int = len(snap.inflight_qubits)
            current_loss_count: int = len(snap.lost_qubits)
            rc_params = {
                "font.size": 9.5,
                "axes.linewidth": 0.95,
                "xtick.major.width": 0.95,
                "ytick.major.width": 0.95,
                "xtick.major.size": 0,
                "ytick.major.size": 0,
            }
            with matplotlib.rc_context(rc_params):
                ax1 = self.fig.add_subplot(4, 1, 1)
                ax2 = self.fig.add_subplot(4, 1, 2)
                ax3 = self.fig.add_subplot(4, 1, 3)
                ax4 = self.fig.add_subplot(4, 1, 4)
                times_us = [t / 1000 for t in state_manager.time_array]
                current_us = current_time / 1000

                colors = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E8"]
                line_width = 1.6
                spine_color = _spine_c
                grid_color = _grid_c
                text_color = _text_c
                current_line = {"color": _marker_c, "linestyle": "--", "linewidth": 1.2, "alpha": 0.6}

                def style_ax(ax, show_xlabels=True):
                    for spine in ax.spines.values():
                        spine.set_visible(True)
                        spine.set_color(spine_color)
                        spine.set_linewidth(0.95)
                    ax.tick_params(
                        axis="x",
                        which="major",
                        bottom=True,
                        labelbottom=show_xlabels,
                        length=0,
                        width=0,
                        color=spine_color,
                        labelcolor=text_color,
                        pad=4,
                    )
                    ax.tick_params(
                        axis="y", which="major", length=0, width=0, color=spine_color, labelcolor=text_color, pad=4
                    )
                    ax.yaxis.grid(True, linestyle="-", linewidth=0.6, alpha=1.0, color=grid_color)
                    ax.xaxis.grid(False)
                    ax.set_axisbelow(True)
                    ax.set_facecolor(_ax_bg)
                    ax.margins(x=0.01)
                    ax.title.set_color(text_color)
                    ax.xaxis.label.set_color(text_color)
                    ax.yaxis.label.set_color(text_color)

                _lx, _ly = _expand_series(state_manager.time_array, live_qubits, operation_windows)
                ax1.plot([t / 1000 for t in _lx], _ly, color=colors[0], linewidth=line_width)
                ax1.axvline(current_us, **current_line)
                ax1.set_ylabel("Num. Qubits", fontsize=8.5)
                ax1.set_title(
                    f"Live Qubits \u2014 t\u2009=\u2009{current_us:.3f}\u202f\u03bcs",
                    fontsize=9.5,
                    fontweight="normal",
                    pad=5,
                )
                ax1.yaxis.set_major_locator(
                    FixedLocator(_make_ticks(min(live_qubits), max(live_qubits), integer=True))
                )
                ax1.xaxis.set_major_locator(FixedLocator(_make_ticks(times_us[0], times_us[-1], n_inner=0)))
                style_ax(ax1, show_xlabels=True)

                _ex, _ey = _expand_series(state_manager.time_array, entangled_states, operation_windows)
                ax2.plot([t / 1000 for t in _ex], _ey, color=colors[1], linewidth=line_width)
                ax2.axvline(current_us, **current_line)
                ax2.set_ylabel("Num. States", fontsize=8.5)
                ax2.set_title(
                    f"Entangled States \u2014 t\u2009=\u2009{current_us:.3f}\u202f\u03bcs",
                    fontsize=9.5,
                    fontweight="normal",
                    pad=5,
                )
                ax2.yaxis.set_major_locator(
                    FixedLocator(_make_ticks(min(entangled_states), max(entangled_states), integer=True))
                )
                ax2.xaxis.set_major_locator(FixedLocator(_make_ticks(times_us[0], times_us[-1], n_inner=0)))
                style_ax(ax2, show_xlabels=True)

                _mx, _my = _expand_series(state_manager.time_array, total_measurements, operation_windows)
                ax3.plot([t / 1000 for t in _mx], _my, color=colors[2], linewidth=line_width)
                ax3.axvline(current_us, **current_line)
                ax3.set_ylabel("Num. Measurements", fontsize=8.5)
                ax3.set_xlabel("Time (\u03bcs)", fontsize=8.5)
                ax3.set_title(
                    f"Total Measurements \u2014 t\u2009=\u2009{current_us:.3f}\u202f\u03bcs",
                    fontsize=9.5,
                    fontweight="normal",
                    pad=5,
                )
                ax3.yaxis.set_major_locator(
                    FixedLocator(_make_ticks(min(total_measurements), max(total_measurements), integer=True))
                )
                ax3.xaxis.set_major_locator(FixedLocator(_make_ticks(times_us[0], times_us[-1], n_inner=0)))
                style_ax(ax3)

                node_names = list(state_manager.nodes.keys())
                bar_counts = [current_node_qubits.get(name, 0) for name in node_names]
                bar_colors = [colors[i % len(colors)] for i in range(len(node_names))]
                all_bar_names = [*node_names, "In-Flight", "Lost"]
                all_bar_counts = [*bar_counts, current_inflight_count, current_loss_count]
                all_bar_colors = [*bar_colors, "#999999", "#D55E00"]
                ax4.bar(
                    all_bar_names, all_bar_counts, color=all_bar_colors, width=0.52, edgecolor="none", linewidth=0
                )
                ax4.set_ylabel("Num. Qubits", fontsize=8.5)
                ax4.set_xlabel("Node", fontsize=8.5)
                ax4.set_title(
                    f"Live Qubits per Node \u2014 t\u2009=\u2009{current_us:.3f}\u202f\u03bcs",
                    fontsize=9.5,
                    fontweight="normal",
                    pad=5,
                )
                ax4.set_ylim(bottom=0)
                max_bar = max(all_bar_counts) if all_bar_counts else 0
                ax4.yaxis.set_major_locator(FixedLocator(_make_ticks(0, max_bar, integer=True)))
                style_ax(ax4, show_xlabels=True)
                if len(all_bar_names) > 5:
                    ax4.tick_params(axis="x", rotation=30)

                self.fig.set_layout_engine("constrained")
                self.draw()


else:
    ChartCanvas = None


__all__ = ["MATPLOTLIB_AVAILABLE", "ChartCanvas"]
