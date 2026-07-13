# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

import bisect
import logging
import os
import sys

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QFontDatabase, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ..logic import EventFileParser, SimulationStateManager
from . import theme as _theme
from .canvas import NetworkCanvas
from .panels import ControlPanel, InfoPanel
from .theme import Theme

logger = logging.getLogger(__name__)


def _example_traces_dir() -> str:
    """Locate the bundled example traces.

    Prefers the repository copy (when running from a clone); falls back to
    the installed copy under ``<prefix>/share/q2nsviz/example_traces``.
    Returns an empty string when neither exists.
    """
    # <repo>/q2nsviz/ui/window.py -> <repo>/example_traces
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    repo_dir = os.path.join(repo_root, "example_traces")
    if os.path.isdir(repo_dir):
        return repo_dir
    installed_dir = os.path.join(sys.prefix, "share", "q2nsviz", "example_traces")
    if os.path.isdir(installed_dir):
        return installed_dir
    return ""


def _primary_modifier_label() -> str:
    """Name of the primary shortcut modifier as it appears on this platform's keyboard.

    Qt maps the ``Ctrl`` of a ``QKeySequence`` onto the Command key on macOS, so the
    key the user actually presses differs from the sequence's spelling.  Shortcut
    hints are labelled from this helper rather than hard-coding either form.
    """
    return "\u2318" if sys.platform == "darwin" else "Ctrl"


def _tinted_pixmap(src: QPixmap, color: QColor) -> QPixmap:
    """Return a copy of *src* recolored to *color*, preserving its alpha silhouette."""
    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, src)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), color)
    painter.end()
    return out


class PlaybackController:
    """Owns the simulation clock, playback timer, and all time-navigation logic.

    Decoupled from ``QuantumVisualizerWindow`` so that playback concerns are
    separated from widget construction.  The controller reads
    ``state_manager.time_array`` and ``state_manager.t_max`` and drives the
    ``on_update`` callback after every time advance.

    Call ``connect_signals()`` once after construction to wire ``ControlPanel``
    signals, and ``setup_for_file()`` each time a new trace is loaded.

    @param state_manager  Shared ``SimulationStateManager`` instance.
    @param control_panel  ``ControlPanel`` providing slider, speed, and loop widgets.
    @param on_update      Callback invoked (with no arguments) after every time step.
    @ingroup q2nsviz_app
    """

    def __init__(self, state_manager: SimulationStateManager, control_panel: ControlPanel, on_update):
        self.state_manager = state_manager
        self.control_panel = control_panel
        self._on_update = on_update
        self.current_sim_time_ns: int = 0
        self.is_playing: bool = False
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def connect_signals(self):
        """Wire all ``ControlPanel`` signals to the appropriate playback methods."""
        cp = self.control_panel
        cp.play_clicked.connect(self.start)
        cp.pause_clicked.connect(self.pause)
        cp.step_forward.connect(self.step_forward)
        cp.step_backward.connect(self.step_backward)
        cp.time_changed.connect(self._on_time_changed)
        cp.speed_changed.connect(self._on_speed_changed)

    def setup_for_file(self):
        """Reset to time zero and configure the slider for a newly loaded file.

        Called immediately after ``SimulationStateManager.load_events()``.  Does not
        invoke the update callback; the caller is responsible for triggering a
        visualization refresh.
        """
        self.current_sim_time_ns = 0
        self.is_playing = False
        self._timer.stop()
        self.control_panel.set_playing(False)
        if self.state_manager.time_array:
            self.control_panel.time_slider.setMaximum(len(self.state_manager.time_array) - 1)
            self.control_panel.time_slider.blockSignals(True)
            self.control_panel.time_slider.setValue(0)
            self.control_panel.time_slider.blockSignals(False)

    def reset(self):
        """Stop playback, return to t = 0, and restore the slider to its default range."""
        self.is_playing = False
        self._timer.stop()
        self.control_panel.set_playing(False)
        self.current_sim_time_ns = 0
        slider = self.control_panel.time_slider
        slider.blockSignals(True)
        slider.setValue(0)
        slider.setMaximum(100)
        slider.blockSignals(False)
        self.control_panel.update_time_label(0.0, 0, 0)

    def start(self):
        """Begin timer-driven playback."""
        self.is_playing = True
        self._timer.start()

    def pause(self):
        """Suspend timer-driven playback."""
        self.is_playing = False
        self._timer.stop()

    def step_forward(self):
        """Advance to the next keyframe and invoke the update callback."""
        if not self.state_manager.time_array:
            return
        ta = self.state_manager.time_array
        idx = bisect.bisect_right(ta, self.current_sim_time_ns)
        if idx < len(ta):
            self.current_sim_time_ns = ta[idx]
        self._sync_slider()
        self._on_update()

    def step_backward(self):
        """Retreat to the previous keyframe and invoke the update callback."""
        if not self.state_manager.time_array:
            return
        ta = self.state_manager.time_array
        idx = bisect.bisect_left(ta, self.current_sim_time_ns) - 1
        self.current_sim_time_ns = ta[idx] if idx >= 0 else 0
        self._sync_slider()
        self._on_update()

    def jump_to_start(self):
        """Jump to t = 0 and invoke the update callback."""
        if not self.state_manager.time_array:
            return
        self.current_sim_time_ns = 0
        self._sync_slider()
        self._on_update()

    def jump_to_end(self):
        """Jump to the last event timestamp and invoke the update callback."""
        if not self.state_manager.time_array:
            return
        self.current_sim_time_ns = self.state_manager.t_max
        self._sync_slider()
        self._on_update()

    def _on_time_changed(self, value: int):
        """Handle time-scrubber drag: snap to the keyframe at the given slider index."""
        if self.state_manager.time_array:
            value = max(0, min(value, len(self.state_manager.time_array) - 1))
            self.current_sim_time_ns = self.state_manager.time_array[value]
        self._on_update()

    def _on_speed_changed(self, value: int):
        """Recompute and display the speed label from the slider position.

        The mapping is logarithmic: slider range [1, 100] maps to playback
        multipliers [1x, ~600x] via ``mult = 10 ** (2.778 * (value - 1) / 99)``.
        At value = 1 the exponent is 0 (1x); at value = 100 it is 2.778 (~600x).
        """
        exp = 2.778 * (value - 1) / 99
        mult = 10**exp
        if mult >= 10:
            label = f"{mult:.0f}\u00d7"
        elif mult >= 2:
            label = f"{mult:.1f}\u00d7"
        else:
            label = f"{mult:.2f}\u00d7"
        self.control_panel.update_speed_label(label)

    def _sync_slider(self):
        """Set the time-scrubber position to reflect ``current_sim_time_ns``.

        Blocks slider signals during the update so that ``time_changed`` is
        not re-emitted and does not cause a recursive update.
        """
        if not self.state_manager.time_array:
            return
        idx = bisect.bisect_right(self.state_manager.time_array, self.current_sim_time_ns) - 1
        idx = max(0, min(idx, len(self.state_manager.time_array) - 1))
        slider = self.control_panel.time_slider
        slider.blockSignals(True)
        slider.setValue(idx)
        slider.blockSignals(False)

    def _tick(self):
        """Advance playback by one wall-clock frame and invoke the update callback.

        Each 16 ms tick advances ``current_sim_time_ns`` by an amount proportional
        to the speed-slider multiplier (same log scale as ``_on_speed_changed``).
        Stops or loops at the final event timestamp depending on the loop-button state.
        """
        if not self.is_playing or not self.state_manager.time_array:
            return
        speed = self.control_panel.speed_slider.value()
        exp = 2.778 * (speed - 1) / 99
        target_ticks = 3600 / (10**exp)
        advance_ns = max(1, int(self.state_manager.t_max / target_ticks))
        self.current_sim_time_ns = min(self.current_sim_time_ns + advance_ns, self.state_manager.t_max)
        if self.current_sim_time_ns >= self.state_manager.t_max:
            if self.control_panel.loop_btn.isChecked():
                self.current_sim_time_ns = 0
            else:
                self.pause()
                self.control_panel.set_playing(False)
        self._sync_slider()
        self._on_update()


class QuantumVisualizerWindow(QMainWindow):
    """Top-level application window.

    Owns the ``SimulationStateManager``, the ``NetworkCanvas``, the
    ``ControlPanel``, and the ``InfoPanel``.  Coordinates playback via a
    ``PlaybackController`` and propagates time-step changes to all child
    widgets through ``_update_visualization()``.

    The single source of truth for the current simulation time is
    ``playback.current_sim_time_ns``; all other widgets derive their
    displayed state from that value on each ``_update_visualization()`` call.
    @ingroup q2nsviz_app
    """

    def __init__(self):
        super().__init__()
        self.state_manager = SimulationStateManager()
        self._last_filename: str | None = None

        self.setWindowTitle("Q2NSViz - Quantum Network Trace Visualizer")
        self.resize(1600, 900)
        self._center_on_screen()
        self._setup_ui()
        # PlaybackController is created after _setup_ui so that control_panel exists.
        self.playback = PlaybackController(self.state_manager, self.control_panel, self._update_visualization)
        self.playback.connect_signals()
        self.playback._on_speed_changed(self.control_panel.speed_slider.value())
        self.setStyleSheet(f"background-color: {Theme.BG_DARK.name()};")
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background-color: {Theme.BG_MEDIUM.name()};
                color: {Theme.TEXT_SECONDARY.name()};
                border-top: 1px solid {Theme.BORDER.name()};
                padding: 4px 8px;
                font-size: 12px;
            }}
        """)
        self.statusBar().showMessage("Ready \u2014 Load a simulation file to begin")
        self._setup_shortcuts()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = (geo.width() - self.width()) // 2
        y = (geo.height() - self.height()) // 2
        self.move(geo.left() + x, geo.top() + y)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        top_bar = self._create_top_bar()
        self._top_bar = top_bar
        main_layout.addWidget(top_bar)

        content = QHBoxLayout()
        content.setSpacing(10)
        self.canvas = NetworkCanvas(self.state_manager)
        content.addWidget(self.canvas, 2)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)
        self.info_panel = InfoPanel()
        right_panel.addWidget(self.info_panel, 1)
        content.addLayout(right_panel, 1)
        main_layout.addLayout(content, 1)

        self.control_panel = ControlPanel()
        main_layout.addWidget(self.control_panel)

    def _build_topbar_stylesheet(self) -> str:
        return f"""
            QFrame {{
                background-color: {Theme.BG_TOPBAR.name()};
                border-radius: 12px;
                padding: 12px;
            }}
            QPushButton {{
                background-color: {Theme.PRIMARY.name()};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {Theme.PRIMARY_HOVER.name()};
            }}
            QPushButton:pressed {{
                background-color: {Theme.PRIMARY_DARK.name()};
            }}
            QPushButton#secondary {{
                background-color: transparent;
                color: {Theme.TEXT_PRIMARY.name()};
                border: 1px solid {Theme.BORDER.name()};
            }}
            QPushButton#secondary:hover {{
                background-color: {Theme.BG_LIGHT.name()};
                border-color: {Theme.PRIMARY_HOVER.name()};
            }}
            QPushButton#secondary:checked {{
                background-color: {Theme.PRIMARY.name()};
                border-color: {Theme.PRIMARY.name()};
                color: white;
            }}
            QLabel {{
                color: {Theme.TEXT_PRIMARY.name()};
                font-size: 18px;
                font-weight: 600;
            }}
        """

    def _create_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(self._build_topbar_stylesheet())
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)

        # --- Left side: logo + title ---
        _assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        logo_path = os.path.join(_assets_dir, "logo-qnattynet.png")
        self._logo_label = QLabel()
        self._logo_label.setStyleSheet("background: transparent; padding: 3px 6px;")
        pix = QPixmap(logo_path)
        self._logo_pixmap = (
            pix.scaled(
                QSize(500, 36),
                aspectRatioMode=Qt.AspectRatioMode.KeepAspectRatio,
                transformMode=Qt.TransformationMode.SmoothTransformation,
            )
            if not pix.isNull()
            else QPixmap()
        )
        self._apply_logo()
        layout.addWidget(self._logo_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(12)

        self._title_label = QLabel("Q2NSViz \u2014 Quantum Network Trace Visualizer")
        self._title_label.setStyleSheet(
            f"color: {Theme.TEXT_PRIMARY.name()}; font-size: 16px; font-weight: 600; background: transparent;"
        )
        layout.addWidget(self._title_label)
        layout.addSpacing(16)

        layout.addStretch()

        # --- Right side ---
        self._dark_btn = QPushButton("Dark")
        self._dark_btn.setObjectName("secondary")
        self._dark_btn.setToolTip("Switch to dark / light mode")
        self._dark_btn.clicked.connect(self._toggle_dark)
        layout.addWidget(self._dark_btn)

        self._legend_btn = QPushButton("Legend")
        self._legend_btn.setObjectName("secondary")
        self._legend_btn.setToolTip("Toggle legend (L)")
        self._legend_btn.setCheckable(True)
        self._legend_btn.setChecked(True)
        self._legend_btn.clicked.connect(self._toggle_legend)
        layout.addWidget(self._legend_btn)

        help_btn = QPushButton("Shortcuts")
        help_btn.setObjectName("secondary")
        help_btn.setToolTip("Keyboard shortcuts")
        help_btn.clicked.connect(self._show_shortcuts)
        layout.addWidget(help_btn)

        layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

        reload_btn = QPushButton("\u21ba\u00a0Reload")
        reload_btn.setObjectName("secondary")
        reload_btn.setToolTip("Reload the last opened trace file")
        reload_btn.clicked.connect(self._reload_file)
        layout.addWidget(reload_btn)

        reset_btn = QPushButton("\u2715\u00a0Reset")
        reset_btn.setObjectName("secondary")
        reset_btn.setToolTip("Reset simulation to the start")
        reset_btn.clicked.connect(self._reset_simulation)
        layout.addWidget(reset_btn)

        export_btn = QPushButton("Export\u2026")
        export_btn.setObjectName("secondary")
        export_btn.setToolTip("Save the current canvas as an image")
        export_btn.clicked.connect(self._export_canvas)
        layout.addWidget(export_btn)

        layout.addItem(QSpacerItem(20, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))

        load_btn = QPushButton("Load Simulation")
        load_btn.setToolTip(f"Open a trace file ({_primary_modifier_label()}+O)")
        load_btn.clicked.connect(self._load_file)
        layout.addWidget(load_btn)

        return bar

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self).activated.connect(self.control_panel.play_btn.click)
        QShortcut(QKeySequence("Right"), self).activated.connect(self.playback.step_forward)
        QShortcut(QKeySequence("Left"), self).activated.connect(self.playback.step_backward)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._load_file)
        QShortcut(QKeySequence("Home"), self).activated.connect(self.playback.jump_to_start)
        QShortcut(QKeySequence("End"), self).activated.connect(self.playback.jump_to_end)
        QShortcut(QKeySequence("L"), self).activated.connect(self._toggle_legend)
        QShortcut(QKeySequence("N"), self).activated.connect(self._toggle_node_labels)

    def _load_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open Simulation File", _example_traces_dir(), "JSON Files (*.json *.ndjson);;All Files (*)"
        )
        if filename:
            self.load_file(filename)

    def load_file(self, filename: str):
        """Load a Q2NS simulation trace from *filename* and initialize playback.

        Calls ``EventFileParser.load_from_file()``, resets the state manager,
        and repaints all child widgets at simulation time zero.  Any parse errors are
        counted and displayed in the status bar without aborting the load.

        @param filename  Absolute path to the trace file.
        @warning         Displays a ``QMessageBox.critical`` dialog on
                         ``OSError`` or any unexpected exception.
        """
        self._last_filename = filename
        try:
            events, parse_errors = EventFileParser.load_from_file(filename)
            self.state_manager.load_events(events)
            self.playback.setup_for_file()
            self.canvas.reset()
            self._update_visualization()
            status = f"Loaded: {os.path.basename(filename)} — {len(events)} events"
            if parse_errors:
                status += f" | {len(parse_errors)} line(s) skipped (parse errors)"
                logger.warning("Parse errors in %s: %s", filename, parse_errors)
            self.statusBar().showMessage(status)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load file:\n{exc}")
            logger.exception("Failed to load file: %s", filename)

    def _reset_simulation(self):
        """Stop playback, clear all loaded state, and return the UI to its initial state."""
        self.playback.reset()
        self.state_manager.reset()
        self.canvas.reset()
        if self.info_panel.chart_canvas:
            self.info_panel.chart_canvas.clear()
        self.info_panel.update_log([], 0)
        self.info_panel.entangle_table.setRowCount(0)
        self.info_panel.stats_table.setRowCount(0)
        self.statusBar().showMessage("Ready \u2014 Load a simulation file to begin")

    def _update_visualization(self):
        """Query the replay engine once and dispatch the state to all child widgets.

        Called after any change to ``current_sim_time_ns``.  Performs the
        single per-frame ``snapshot_at()`` query and pushes the resulting
        ``Snapshot`` to the network canvas and the information panel; derives
        the display step index via binary search for the status bar readout.

        Safe to call on an empty trace: every widget then renders its empty state.
        """
        t_ns = self.playback.current_sim_time_ns
        snap = self.state_manager.snapshot_at(t_ns)
        self.canvas.set_snapshot(snap)
        t_us = t_ns / 1000
        ta = self.state_manager.time_array
        display_step = bisect.bisect_right(ta, t_ns)
        total_steps = len(ta)
        self.control_panel.update_time_label(t_us, display_step, total_steps)
        self.info_panel.update_log(self.state_manager.log_events, self.state_manager.log_count_at(t_ns))
        self.info_panel.update_entanglement(snap.entangled_states)
        live_qubits = len(snap.live_qubit_labels)
        self.info_panel.update_stats(
            len(snap.nodes),
            len(self.state_manager.events),
            self.state_manager.t_max / 1000 if self.state_manager.t_max else 0,
            qubits=live_qubits,
            entangled=len(snap.entangled_states),
            measured=len(snap.measured_qubits),
            lost=len(snap.lost_qubits),
            discarded=len(snap.discarded_qubits),
        )
        self.info_panel.update_charts(self.state_manager, snap)

        self.statusBar().showMessage(
            f"Time: {t_us:.3f}\u202f\u03bcs | Step: {display_step}/{total_steps} | "
            f"Qubits: {live_qubits} | Entangled States: {len(snap.entangled_states)}"
        )

    def _toggle_dark(self):
        """Switch between light and dark color palettes for this session."""
        is_now_dark = _theme.toggle_dark()
        self._dark_btn.setText("Light" if is_now_dark else "Dark")
        self.apply_theme()
        if self.info_panel.chart_canvas and self.state_manager.time_array:
            snap = self.state_manager.snapshot_at(self.playback.current_sim_time_ns)
            self.info_panel.update_charts(self.state_manager, snap)

    def _toggle_legend(self):
        """Show or hide the canvas legend; syncs the toolbar button state."""
        visible = self.canvas.toggle_legend()
        self._legend_btn.setChecked(visible)

    def _toggle_node_labels(self):
        """Show or hide node labels on the canvas."""
        self.canvas.toggle_node_labels()

    def _export_canvas(self):
        """Save the current canvas view as an image file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Canvas", "canvas.png", "PNG Image (*.png);;JPEG Image (*.jpg);;All Files (*)"
        )
        if path:
            self.canvas.grab().save(path)

    def _reload_file(self):
        """Reload the last opened trace file."""
        if self._last_filename:
            self.load_file(self._last_filename)

    def _show_shortcuts(self):
        """Display a summary of keyboard shortcuts with styled key badges."""
        _kb = (
            "background:#e8eaed; border:1px solid #c0c3c8;"
            " border-bottom:2px solid #a0a3a8; border-radius:4px;"
            " padding:2px 8px; font-family:monospace; font-size:11px;"
        )
        html = (
            f"<table cellpadding='5' cellspacing='0' style='font-size:13px;'>"
            f"<tr><td colspan='2' style='padding-top:0;padding-bottom:4px;'><b>Playback</b></td></tr>"
            f"<tr><td align='right'><span style='{_kb}'>Space</span></td>"
            f"    <td style='padding-left:14px;'>Play / Pause</td></tr>"
            f"<tr><td align='right'>"
            f"    <span style='{_kb}'>&#8592;</span>&nbsp;"
            f"    <span style='{_kb}'>&#8594;</span></td>"
            f"    <td style='padding-left:14px;'>Step backward / forward</td></tr>"
            f"<tr><td align='right'>"
            f"    <span style='{_kb}'>Home</span>&nbsp;"
            f"    <span style='{_kb}'>End</span></td>"
            f"    <td style='padding-left:14px;'>Jump to start / end</td></tr>"
            f"<tr><td colspan='2' style='padding-top:10px;padding-bottom:4px;'><b>File</b></td></tr>"
            f"<tr><td align='right'>"
            f"    <span style='{_kb}'>{_primary_modifier_label()}</span>&nbsp;+&nbsp;"
            f"    <span style='{_kb}'>O</span></td>"
            f"    <td style='padding-left:14px;'>Open trace file</td></tr>"
            f"<tr><td colspan='2' style='padding-top:10px;padding-bottom:4px;'><b>Display</b></td></tr>"
            f"<tr><td align='right'><span style='{_kb}'>L</span></td>"
            f"    <td style='padding-left:14px;'>Toggle legend</td></tr>"
            f"<tr><td align='right'><span style='{_kb}'>N</span></td>"
            f"    <td style='padding-left:14px;'>Toggle node labels</td></tr>"
            f"</table>"
        )
        QMessageBox.information(self, "Keyboard Shortcuts", html)

    def _apply_logo(self):
        """Set the top-bar logo, tinted to a light tone in dark mode for legibility."""
        if self._logo_pixmap.isNull():
            return
        if _theme.is_dark():
            self._logo_label.setPixmap(_tinted_pixmap(self._logo_pixmap, QColor(Theme.TEXT_PRIMARY)))
        else:
            self._logo_label.setPixmap(self._logo_pixmap)

    def apply_theme(self):
        """Re-apply the active color palette to the window and all child widgets.

        Call after ``toggle_dark()`` to propagate palette changes throughout
        the application.  Updates stylesheets and triggers a canvas repaint.
        """
        self.setStyleSheet(f"background-color: {Theme.BG_DARK.name()};")
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background-color: {Theme.BG_MEDIUM.name()};
                color: {Theme.TEXT_SECONDARY.name()};
                border-top: 1px solid {Theme.BORDER.name()};
                padding: 4px 8px;
                font-size: 12px;
            }}
        """)
        if hasattr(self, "_top_bar"):
            self._top_bar.setStyleSheet(self._build_topbar_stylesheet())
            for _btn in self._top_bar.findChildren(QPushButton):
                self._top_bar.style().unpolish(_btn)
                self._top_bar.style().polish(_btn)
                _btn.update()
        if hasattr(self, "_title_label"):
            self._title_label.setStyleSheet(
                f"color: {Theme.TEXT_PRIMARY.name()}; font-size: 16px; font-weight: 600; background: transparent;"
            )
        if hasattr(self, "_logo_label"):
            self._apply_logo()
        self.control_panel.apply_theme()
        self.info_panel.apply_theme()
        self.canvas.apply_theme()


def main(initial_file: str | None = None):
    """Launch the Quantum Network Visualizer application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Q2NSViz")
    app.setApplicationDisplayName("Q2NSViz \u2014 Quantum Network Trace Visualizer")
    app.setStyle("Fusion")
    app.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))

    _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo-qnattynet.png")
    if os.path.isfile(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    window = QuantumVisualizerWindow()
    window.show()

    if initial_file:
        window.load_file(initial_file)

    return app.exec()


__all__ = ["PlaybackController", "QuantumVisualizerWindow", "main"]
