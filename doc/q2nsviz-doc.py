"""
@mainpage Q2NSViz

<div class="q2nsviz-badges">
<a href="https://opensource.org/licenses/MIT"><img
src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square"
alt="License: MIT"></a>
<a href="https://github.com/QuantumInternet-it/q2nsviz"><img
src="https://img.shields.io/badge/GitHub-repo-123463?logo=github"
alt="GitHub repo"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-brightgreen?style=flat-square"
alt="Python 3.12+">
<img src="https://img.shields.io/badge/PyQt-6.6+-brightgreen?style=flat-square"
alt="PyQt 6.6+">
</div>

Q2NSViz is a desktop companion for [Q2NS](https://github.com/QuantumInternet-it/q2ns)
that replays JSON trace files and renders an interactive, time-stepped view of quantum
network protocols and simulations.

It jointly renders physical- and entanglement-connectivity graphs and supports
entangled-state manipulations, facilitating an intuitive inspection of entanglement
dynamics and protocol behavior.  Trace files are produced by the Q2NS simulator and
follow an NDJSON or JSON-array format where each event object carries a nanosecond
timestamp and a typed payload.

@tableofcontents

@section q2nsviz_main_groups Topics

The Q2NSViz codebase is navigated by topic:
- @ref q2nsviz_engine
- @ref q2nsviz_canvas
- @ref q2nsviz_charts
- @ref q2nsviz_panels
- @ref q2nsviz_app

@section q2nsviz_architecture Architecture

Q2NSViz is organized around a small set of focused roles.

- **EventFileParser** reads NDJSON and JSON-array trace files from disk.
- **SimulationStateManager** ingests a trace (file path or parsed event list),
  builds a sorted timeline, and exposes the network state at arbitrary
  nanosecond timestamps as immutable `Snapshot` objects via `snapshot_at(t_ns)`;
  `seek(t_ns)` is the packaging-free positioning primitive for bulk scans.
- **NetworkCanvas** is a QPainter widget that renders the network topology,
  in-flight qubits, entanglement graph, and lost qubits in a fixed sequence of
  layered paint passes.
- **ChartCanvas** wraps a Matplotlib figure and plots three time-series
  (live qubits, entangled states, total measurements) plus a per-node bar chart.
- **ControlPanel** provides transport controls (play/pause/step), a time scrubber,
  and a speed slider.  Signals drive the `QuantumVisualizerWindow` playback loop.
- **InfoPanel** is a tabbed widget containing the event log, statistics table,
  entanglement-states table, and the ChartCanvas.
- **QuantumVisualizerWindow** owns all the above and acts as the controller:
  a `PlaybackController` `QTimer` tick advances `current_sim_time_ns` and calls
  `_update_visualization()`, which queries `snapshot_at(t)` once per frame and
  dispatches the resulting `Snapshot` to the canvas and panels.

@section q2nsviz_workflow Typical Workflow

1. Launch `python -m q2nsviz` (optionally passing a trace file path).
2. Use the **Load Simulation** button (Ctrl+O) to load a `.json` / `.ndjson` trace.
3. Press **Play** or use the time scrubber to step through the simulation.
4. Inspect the canvas for qubit positions, channel activity, and entanglement links.
5. Switch to the **Charts** tab to see time-series trends.
6. Read the **Event Log** tab for `traceText` protocol messages.

@section q2nsviz_json_format Trace File Format

Q2NSViz reads the JSON wire format produced by Q2NS.  Event type strings and field
keys are part of the Q2NS public API and are **never** renamed inside Q2NSViz:

| Event type | Key fields |
|---|---|
| `createNode` | `t_ns`, `label`, `x`, `y` |
| `createChannel` | `t_ns`, `from`, `to`, `kind` |
| `createQubit` | `t_ns`, `label`, `node` |
| `createCbit` | `t_ns`, `label`, `node` |
| `entangle` | `t_ns`, `bits` |
| `sendQubit` | `t0_ns`, `t1_ns`, `bit`, `from`, `to` |
| `sendCbit` | `t0_ns`, `t1_ns`, `bit`, `from`, `to` |
| `sendPacket` | `t0_ns`, `t1_ns`, `from`, `to`, `label`, `protocol` (optional) |
| `measure` | `t_ns`, `bit`, `base` |
| `graphMeasure` | `t_ns`, `bit`, `base`, `supportNode` (optional) |
| `removeQubit` | `t_ns`, `bit`, `reason` (optional) |
| `removeCbit` | `t_ns`, `bit` |
| `traceText` | `t_ns`, `text`, `node` (optional) |

The `entangle`, `measure`, and `graphMeasure` events accept an optional `duration_ns`
field giving the operation's processing time. Events are emitted at operation completion;
`t_ns` is the commit instant, and the visualizer draws a ring during the preceding window
`[t_ns - duration_ns, t_ns)`. The ring is distinct per event type: dashed for a
quantum gate, solid for `measure`, solid double for `graphMeasure`, and marks processing
time only; entanglement is shown by qubit color and the entanglement links.
The `base` field of `measure` is informational and does not affect the state update.
The `reason` field of `removeQubit` selects how the removal is displayed: a qubit removed
with `reason: "discarded"` leaves the canvas silently (counted under *Discarded* in the
Statistics tab), while any other or missing reason on an unmeasured qubit marks it as
lost (red cross marker, *Lost* statistics and chart bar). The removal itself is identical
in both cases.

@section q2nsviz_publications Related Publications

<a href="https://ieeexplore.ieee.org/document/11322738">[1]</a>
<em>Quantum Internet Architecture: Unlocking Quantum-Native Routing via Quantum Addressing (invited paper)</em>.
Marcello Caleffi and Angela Sara Cacciapuoti —
IEEE Transactions on Communications, vol. 74, pp. 3577-3599, 2026.

<a href="https://doi.org/10.1016/j.comnet.2026.112292">[2]</a>
<em>An Extensible Quantum Network Simulator Built on ns-3: Q2NS Design and Evaluation</em>.
Adam Pearson, Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti —
Computer Networks (Elsevier) 2026.

<a href="https://doi.org/10.5281/zenodo.18980972">[3]</a>
<em>Q2NS: A Modular Framework for Quantum Network Simulation in ns-3 (invited paper)</em>.
Adam Pearson, Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti —
Proc. QCNC 2026.

<a href="https://doi.org/10.48550/arXiv.2604.02112">[4]</a>
<em>Q2NS Demo: a Quantum Network Simulator based on ns-3</em>.
Francesco Mazza, Adam Pearson, Marcello Caleffi, Angela Sara Cacciapuoti — 2026.

[5]
<em>Q2NSViz: An Open-source Standalone Visualizer for Quantum Network Simulations</em>.
Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti — 2026 (submitted).

@section q2nsviz_acknowledgement Acknowledgement

This work has been funded by the <b>European Union</b> under Horizon Europe ERC-CoG
grant <b>QNattyNet</b>, n. 101169850.  Views and opinions expressed are those of the
author(s) only and do not necessarily reflect those of the European Union or the
European Research Council Executive Agency.  Neither the European Union nor the
granting authority can be held responsible for them.


@defgroup q2nsviz_engine Core State Engine
@brief Quantum network state engine: data types, replay logic, and trace parser.

Covers all symbols defined in `q2nsviz/logic.py`:
- @ref q2nsviz::logic::Node, @ref q2nsviz::logic::Channel, @ref q2nsviz::logic::Qubit,
  @ref q2nsviz::logic::ClassicalBit — lightweight dataclasses that mirror Q2NS network
  topology, qubit, and classical-bit state.
- @ref q2nsviz::logic::UnionFind — disjoint-set structure used for computing entanglement components.
- @ref q2nsviz::logic::Snapshot — immutable per-instant view of the reconstructed network state,
  returned by `snapshot_at(t_ns)` and dispatched by the controller to the views.
- @ref q2nsviz::logic::SimulationStateManager — the central replay engine; ingests a trace (file path
  or parsed event list) and exposes the state via `snapshot_at(t_ns)` / `seek(t_ns)`.
- @ref q2nsviz::logic::EventFileParser — reads NDJSON and JSON-array trace files from disk.


@defgroup q2nsviz_canvas Network Canvas
@brief QPainter widget that renders the network topology and quantum state.

Covers all symbols defined in `q2nsviz/ui/canvas.py`:
- @ref q2nsviz::ui::canvas::NetworkCanvas — the main rendering widget.  Executes a fixed sequence of
  layered paint passes each frame (background, channels, nodes, lost qubits,
  measured qubits, in-flight qubits, classical packets, in-flight cbits,
  entanglement links, legend, and the current-time traceText overlay).


@defgroup q2nsviz_charts Chart Panel
@brief Matplotlib-based time-series and bar-chart visualisation.

Covers all symbols defined in `q2nsviz/ui/charts.py`:
- @ref q2nsviz::ui::charts::ChartCanvas — wraps a Matplotlib figure; plots live qubits, entangled states,
  and total measurements as step-function time series, plus a per-node bar chart
  snapshot at the current simulation time.
- `_expand_series` — module-level helper that converts keyframe arrays into step
  functions suitable for plotting.
- `_make_ticks` — tick-list generator that always includes the axis endpoints.


@defgroup q2nsviz_panels Side Panels
@brief Transport controls and tabbed information panel.

Covers all symbols defined in `q2nsviz/ui/panels.py`:
- @ref q2nsviz::ui::panels::ControlPanel — play/pause/step buttons, time scrubber, and speed slider.
  Emits `play_clicked` and `pause_clicked` signals consumed by the main window.
- @ref q2nsviz::ui::panels::InfoPanel — tabbed widget containing the event log, statistics table,
  entanglement-states table, and the optional ChartCanvas.


@defgroup q2nsviz_app Application Window
@brief Top-level application window, playback controller, and entry point.

Covers all symbols defined in `q2nsviz/ui/window.py` and `q2nsviz/cli.py`:
- @ref q2nsviz::ui::window::QuantumVisualizerWindow — owns the state manager, canvas, and panels;
  delegates all time-navigation to `PlaybackController` and propagates
  updates to all child widgets through `_update_visualization()`.
- @ref q2nsviz::ui::window::PlaybackController — owns the `QTimer`, current simulation time, and all
  time-navigation methods (play, pause, step, scrub, jump).
- `main()` — creates the `QApplication`, shows the window, and optionally loads a trace
  passed by the caller.  Command-line arguments are parsed in `q2nsviz/cli.py`, which
  backs both the `q2nsviz` console script and `python -m q2nsviz`.
"""
