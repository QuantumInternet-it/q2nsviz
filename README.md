<p align="center">
  <a href="https://qnattynet.quantuminternet.it/"><img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/.doxygen/assets/logo-qnattynet.png" height="120px" alt="QNattyNet"></a>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square"></a>
  <a href="https://quantuminternet-it.github.io/q2nsviz/"><img src="https://img.shields.io/badge/documentation-blue?style=flat-square&logo=read%20the%20docs"></a>
  <a href="https://doi.org/10.5281/zenodo.21216676"><img src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.21216676-1682D4?style=flat-square"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-brightgreen?style=flat-square">
  <img src="https://img.shields.io/badge/PyQt-6.6+-brightgreen?style=flat-square">
</p>

# Q2NSViz — Quantum Network Trace Visualizer

**Q2NSViz** is a desktop companion for [Q2NS](https://github.com/QuantumInternet-it/q2ns) that replays JSON trace files into an interactive, time-stepped view of quantum network protocols: physical and entanglement-connectivity graphs rendered jointly, with support for entangled-state manipulations. More details can be found in our documentation and related works!

**Q2NS** and its companion tool **Q2NSViz** are developed within the [ERC-CoG QNattyNet](https://qnattynet.quantuminternet.it/) project (grant n. 101169850) at the [University of Naples Federico II](https://www.unina.it/), funded by the European Research Council.

## Key Features

- **Time-step replay** — scrub forward and backward through the simulation timeline with transport controls
- **Network canvas** — QPainter-rendered topology showing nodes, qubits (color-coded), in-flight transfers, and channel kinds
- **Entanglement graph** — live view of the entanglement graph including graph-state measurements and local complementations
- **Charts panel** — time-series plots of live qubits, entangled states, and cumulative measurements, plus a per-node qubit distribution, updated along the timeline
- **Event log** — list of `traceText` protocol messages emitted by the simulation

## Installation

The viewer is built with **PyQt6** for the GUI and **Matplotlib** for the charts. Clone the repository and install with pip:

```bash
git clone https://github.com/QuantumInternet-it/q2nsviz.git
cd q2nsviz
pip install .
```

This pulls in the dependencies and installs a `q2nsviz` launcher command. For development, use an editable install with the test extras instead:

```bash
pip install -e ".[test]"
```

> [!NOTE]
> Q2NSViz has been tested and is recommended for use with **Python 3.12**; other versions may require minor adjustments. Use an isolated environment (`venv` or `conda`) to avoid dependency conflicts.

## Getting Started

Once installed, launch the viewer with the `q2nsviz` command:

```bash
# Open the viewer (no trace loaded)
q2nsviz

# Load a trace file on startup
q2nsviz example_traces/q2nsviz-teleportation-example.json

# Set log verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL; default: WARNING)
q2nsviz --log-level DEBUG
```

> [!TIP]
> Running from a clone without installing? Use `python -m q2nsviz` in place of `q2nsviz` with the same arguments.

Use the **Load Simulation** button in the top bar to open a trace at any time. The file dialog opens in the bundled `example_traces/` folder by default — the repository copy when running from a clone, or the copy installed under `<prefix>/share/q2nsviz/example_traces` otherwise.

## Example Traces

The `example_traces/` directory contains ready-to-load traces:

| File | Protocol |
|------|----------|
| `q2nsviz-teleportation-example.json` | Quantum teleportation |
| `q2nsviz-graphstate-gen-example.json` | Graph-state generation and measurement |
| `q2nsviz-entanglement-distribution-example.json` | Entanglement distribution |
| `q2nsviz-repeater-swap-example.json` | Entanglement swapping (1 repeater) |
| `q2nsviz-channel-loss-example.json` | Lossy quantum channel |

The repeater-swap example replayed in the viewer — network canvas and event log:

<p align="center">
  <img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/doc/assets/q2nsviz-canvas.gif" alt="Network canvas replaying the bundled repeater-swap example" width="62%">
  <img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/doc/assets/q2nsviz-eventlog.gif" alt="Event log during the same replay" width="31%">
</p>

## Trace Format

Q2NSViz reads the JSON format emitted by Q2NS, in either **NDJSON** (one event object per line — the form used by the bundled examples) or **JSON-array** form; the format is auto-detected on load. A minimal NDJSON trace looks like this:

```json
{"type": "createNode", "t_ns": 0, "label": "Alice", "x": 25, "y": 50}
{"type": "createNode", "t_ns": 0, "label": "Bob", "x": 75, "y": 50}
{"type": "createChannel", "t_ns": 0, "from": "Alice", "to": "Bob", "kind": "quantum"}
{"type": "createQubit", "t_ns": 1000, "label": "q0", "node": "Alice"}
{"type": "createQubit", "t_ns": 1000, "label": "q1", "node": "Alice"}
{"type": "entangle", "t_ns": 1300, "duration_ns": 300, "bits": ["q0", "q1"]}
{"type": "sendQubit", "t0_ns": 1400, "t1_ns": 1500, "bit": "q1", "from": "Alice", "to": "Bob"}
{"type": "traceText", "t_ns": 1500, "node": "Bob", "text": "q1 arrived - Bell pair shared"}
{"type": "measure", "t_ns": 2100, "duration_ns": 100, "bit": "q0", "base": "Z"}
{"type": "removeQubit", "t_ns": 2100, "bit": "q0", "reason": "discarded"}
```

The supported event types are:

| Event type      | Required fields                                             | Description                                      |
|-----------------|-------------------------------------------------------------|--------------------------------------------------|
| `createNode`    | `t_ns`, `label`, `x`, `y`                                  | Define a network node; `x` and `y` are canvas percentages (0–100); always emitted with `t_ns = 0` |
| `createChannel` | `t_ns`, `from`, `to`, `kind` (`quantum`\|`classical`)      | Add a channel between two nodes                  |
| `createQubit`   | `t_ns`, `label`, `node`                                     | Instantiate a qubit on a node                    |
| `createCbit`    | `t_ns`, `label`, `node`                                     | Instantiate a classical bit on a node            |
| `entangle`      | `t_ns`, `bits` (array)                                      | Mark a set of qubits as entangled; a second `entangle` event on the same set cancels the edge (e.g. CZ² = I) |
| `sendQubit`     | `t0_ns`, `t1_ns`, `bit`, `from`, `to`                      | Transfer a qubit through a quantum channel       |
| `sendCbit`      | `t0_ns`, `t1_ns`, `bit`, `from`, `to`                      | Transfer a classical bit through a classical channel |
| `sendPacket`    | `t0_ns`, `t1_ns`, `from`, `to`, `label` [, `protocol`]      | Classical packet in flight; `protocol` is optional (`"tcp"` or `"udp"`) and controls the packet color in the visualizer |
| `measure`       | `t_ns`, `bit`, `base`                                       | Projective measurement; removes the qubit's entanglement edges. `base` is informational — use `graphMeasure` for basis-dependent updates |
| `graphMeasure`  | `t_ns`, `bit`, `base`, `supportNode` (optional)            | Graph-state measurement; `supportNode` is the neighbour of `bit` that drives the X-basis local-complementation sequence |
| `removeQubit`   | `t_ns`, `bit`, `reason` (optional)                          | Remove a qubit — silently when `reason` is `"discarded"`, as *lost* (red ✕) otherwise; removals co-occurring with a `measure` are never shown as lost |
| `removeCbit`    | `t_ns`, `bit`                                               | Remove a classical bit that is no longer needed  |
| `traceText`     | `t_ns`, `text`, `node` (optional)                           | Protocol log message                             |

`entangle`, `measure`, and `graphMeasure` accept an optional `duration_ns` giving the operation's processing time. Events are emitted at operation **completion**: the state transition commits at `t_ns`, and a processing ring is drawn during the preceding `[t_ns - duration_ns, t_ns)` — dashed for `entangle`, solid for `measure`, double for `graphMeasure`.

> [!TIP]
> Without `duration_ns` the transition is instantaneous at `t_ns`.

### Timing model: gate times and propagation

Every event line describes something that has already happened: `t_ns` is the instant its state change commits.

- **Gate times** — durationed events are emitted at completion; the ring covers the preceding `[t_ns - duration_ns, t_ns)`. Anything that uses the result is simply stamped at or after `t_ns`.
- **Propagation** — `sendQubit`/`sendCbit`/`sendPacket` carry explicit `t0_ns`/`t1_ns` and are emitted at departure. The carrier animates over the window and sits at its destination from `t1_ns` on.

In Q2NS this is one pattern — schedule the completion, log there. The Bell-state measurement in the bundled repeater-swap example:

```cpp
// We schedule something to happen after a processing time
Simulator::Schedule(kTwoQGate, [&]() {
  auto [m1, m2] = repeater->MeasureBell(memA, memB);
  // commit now, ring back-dated kTwoQGate
  TraceMeasure("rep_a", kTwoQGate, "Bell");
  TraceMeasure("rep_b", kTwoQGate, "Bell");
  // swapped pair, instantaneous commit
  TraceEntangle({"q_a", "q_b"});
  // ... send the corrections carrying m1, m2 ...
});
```

yields the trace:

```json
{"type": "measure", "t_ns": 4200, "duration_ns": 300, "bit": "rep_a", "base": "Bell"}
{"type": "measure", "t_ns": 4200, "duration_ns": 300, "bit": "rep_b", "base": "Bell"}
{"type": "entangle", "t_ns": 4200, "bits": ["q_a", "q_b"]}
```

The measurement rings run during `[3900, 4200)`; the swapped entanglement edge lands exactly when the BSM completes.

> **Note on BSM and entanglement swapping.** Measuring a qubit (via `measure`) removes all its entanglement edges — no new entanglement is inferred from measurement outcomes. For entanglement-swapping protocols (e.g., repeater chains), Q2NS should emit an explicit `entangle` event for the newly swapped pair after the BSM; the BSM alone does not update the entanglement graph.

## Programmatic API

The replay engine (`q2nsviz/logic.py`) is Qt-free and can be used directly from Python scripts, independently of the GUI — importing `q2nsviz` never loads Qt. `load_events()` accepts a trace-file path (or a pre-parsed event list), and `snapshot_at(t_ns)` reconstructs the network state at any simulation time as an immutable `Snapshot`:

```python
from q2nsviz import SimulationStateManager

sm = SimulationStateManager()
sm.load_events("example_traces/q2nsviz-repeater-swap-example.json")

snap = sm.snapshot_at(4000)            # state at t = 4 µs, mid-BSM
print(sorted(snap.live_qubit_labels))  # ['q_a', 'q_b', 'rep_a', 'rep_b']
print(snap.entangled_states)           # {'q_a': ('q_a', 'rep_a'), 'q_b': ('q_b', 'rep_b')}
print(sorted(snap.measuring_qubits))   # ['rep_a', 'rep_b']
```

> [!TIP]
> A `Snapshot` carries the node/channel topology, the qubit and classical-bit registries, the entanglement graph and its connected components, the measured/removed/lost sets, and the in-flight and operation-window sets — see the `Snapshot` docstring for the full field list.

## Development

### Install dev tools

Pre-commit runs **ruff** for linting, import sorting, and formatting on every commit.

```bash
pip install ruff pre-commit
pre-commit install
```

Run the hooks manually with `pre-commit run --all-files`, or invoke ruff directly with `ruff check --fix .` and `ruff format .`.

### Run the tests

The test suite covers the trace parser, the quantum-state replay engine, and the bundled example traces.

```bash
pip install pytest pytest-qt
pytest
```

### Build the documentation

The API reference is generated with [Doxygen](https://www.doxygen.nl/) (with [Graphviz](https://graphviz.org/) for the class and call diagrams). On macOS: `brew install doxygen graphviz`. Then run:

```bash
doxygen .doxygen/Doxyfile
```

The HTML site is written to `.doxygen-build/html/`; open `.doxygen-build/html/index.html` in a browser. Generated output is not committed to the repository.

The same build is published to GitHub Pages by [`.github/workflows/docs.yml`](.github/workflows/docs.yml) on every push to `main` (once the repository is public, with Pages set to build from GitHub Actions).

## Repository Layout

```
q2nsviz/
  __init__.py             # Public API — the Qt-free replay engine
  __main__.py             # `python -m q2nsviz` entry point
  cli.py                  # Argument parsing; backs the `q2nsviz` console script
  logic.py                # Trace parser and quantum state replay engine
  ui/
    window.py             # QMainWindow, playback controller, and main() launcher
    canvas.py             # Network topology renderer (QPainter)
    charts.py             # Matplotlib time-series charts
    panels.py             # Control panel and info tabs
    theme.py              # Shared colors and fonts
test/                     # Pytest suite: parser, state engine, charts, examples
doc/                      # Doxygen mainpage, API-doc sources, README assets
example_traces/           # Sample JSON traces
pyproject.toml            # Project metadata, ruff and pytest configuration
requirements.txt          # Runtime dependencies
MANIFEST.in               # Source-distribution packaging rules
CITATION.cff              # Citation metadata
LICENSE                   # MIT license
.pre-commit-config.yaml   # Pre-commit hook definitions
.doxygen/                 # Doxyfile, HTML theme, and documentation assets
.github/workflows/        # CI: builds and publishes docs to GitHub Pages
```

## Contributors & Supporters

Q2NSViz, like Q2NS, is developed by our [Quantum Internet Research Group](https://qnattynet.quantuminternet.it/) team, under the [ERC-CoG QNattyNet](https://www.quantuminternet.it/qnattynet/) project.

Thank you to all the researchers who have helped develop Q2NS and Q2NSViz!

<!-- Add new contributors below following the same pattern -->
<table align="center" border="0" cellspacing="12" cellpadding="0"><tr>
  <td align="center" style="border:none;">
    <a href="https://github.com/pearsona">
      <img src="https://wsrv.nl/?url=github.com/pearsona.png&w=60&h=60&mask=circle" width="60" height="60" alt="Adam Pearson" title="Adam Pearson" />
    </a>
  </td>
  <td align="center" style="border:none;">
    <a href="https://github.com/framazzaa">
      <img src="https://wsrv.nl/?url=github.com/framazzaa.png&w=60&h=60&mask=circle" width="60" height="60" alt="Francesco Mazza" title="Francesco Mazza" />
    </a>
  </td>
  <td align="center" style="border:none;">
    <a href="https://github.com/AngelaSara">
      <img src="https://wsrv.nl/?url=github.com/AngelaSara.png&w=60&h=60&mask=circle" width="60" height="60" alt="Angela Sara Cacciapuoti" title="Angela Sara Cacciapuoti" />
    </a>
  </td>
</tr></table>

Q2NSViz is and will remain free, open-source software.
We are committed to keeping it open and actively maintained for the quantum networking research community.

To support this endeavor, please consider:

- Starring and sharing the repository: https://github.com/QuantumInternet-it/q2nsviz
- Contributing code, documentation, tests, or examples via issues and pull requests
- Citing Q2NS and Q2NSViz in your publications (see [Cite This](#cite-this))
- Sharing feedback and use cases with the team

## Cite This

If you use Q2NSViz in your research, please cite our reference paper:
_Q2NSViz: An Open-source Standalone Visualizer for Quantum Network Simulations_ (submitted)

You can use the GitHub **"Cite this repository"** button (top-right of this page) for a ready-to-use citation in multiple formats, or use the BibTeX entry below:

```bibtex
@article{q2nsviz-2026,
  title  = {{Q2NSViz: An Open-source Standalone Visualizer for Quantum Network Simulations}},
  author = {Mazza, Francesco and Caleffi, Marcello and Cacciapuoti, Angela Sara},
  year   = {2026},
  note   = {Submitted for publication}
}
```

You may additionally cite the software itself. It is archived on Zenodo under a DOI that always resolves to the latest release ([10.5281/zenodo.21216676](https://doi.org/10.5281/zenodo.21216676)):

```bibtex
@software{q2nsviz-software,
  title     = {{Q2NSViz: Quantum Network Trace Visualizer}},
  author    = {Mazza, Francesco and Caleffi, Marcello and Cacciapuoti, Angela Sara},
  year      = {2026},
  version   = {0.1.0},
  doi       = {10.5281/zenodo.21216676},
  publisher = {Zenodo},
  url       = {https://doi.org/10.5281/zenodo.21216676}
}
```

## License

Q2NSViz is released under the [MIT License](LICENSE).

## Related Publications

The following papers present the Q2NS and Q2NSViz tools, or motivate the research behind them. If your work belongs here, please open an issue or pull request.

[[1]](https://ieeexplore.ieee.org/document/11322738) _Quantum Internet Architecture: Unlocking Quantum-Native Routing via Quantum Addressing (invited paper)_. Marcello Caleffi and Angela Sara Cacciapuoti — IEEE Transactions on Communications, vol. 74, pp. 3577–3599, 2026.

[[2]](https://doi.org/10.1016/j.comnet.2026.112292) _An Extensible Quantum Network Simulator Built on ns-3: Q2NS Design and Evaluation_. Adam Pearson, Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti — Computer Networks (Elsevier), 2026.

[[3]](https://doi.org/10.5281/zenodo.18980972) _Q2NS: A Modular Framework for Quantum Network Simulation in ns-3 (invited paper)_. Adam Pearson, Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti — Proc. of QCNC 2026.

[[4]](https://doi.org/10.48550/arXiv.2604.02112) _Q2NS Demo: a Quantum Network Simulator based on ns-3_. Francesco Mazza, Adam Pearson, Marcello Caleffi, Angela Sara Cacciapuoti — 2026.

[5] _Q2NSViz: An Open-source Standalone Visualizer for Quantum Network Simulations_. Francesco Mazza, Marcello Caleffi, Angela Sara Cacciapuoti — 2026 (submitted).

## Acknowledgements

This work has been funded by the **European Union** under Horizon Europe ERC-CoG grant **QNattyNet**, n.101169850. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union or the European Research Council Executive Agency. Neither the European Union nor the granting authority can be held responsible for them.

<p align="center">
  <a href="https://qnattynet.quantuminternet.it/">
    <img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/.doxygen/assets/logo-full.png" height="80px" alt="QNattyNet">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/.doxygen/assets/logo-erc.png" height="70px" alt="European Research Council">
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/QuantumInternet-it/q2nsviz/main/.doxygen/assets/logo-unina.png" height="70px" alt="Università Federico II">
</p>
