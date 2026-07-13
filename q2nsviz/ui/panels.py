# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .charts import MATPLOTLIB_AVAILABLE, ChartCanvas
from .theme import Theme


class ControlPanel(QFrame):
    """Transport controls, time scrubber, and speed slider.

    @ingroup q2nsviz_panels
    """

    play_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    step_forward = pyqtSignal()
    step_backward = pyqtSignal()
    time_changed = pyqtSignal(int)
    speed_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("ControlPanel")
        self.is_playing = False
        self._setup_ui()

    def _apply_stylesheet(self):
        self.setStyleSheet(f"""
            QFrame#ControlPanel {{
                background-color: {Theme.BG_MEDIUM.name()};
                border-radius: 10px;
                border: none;
            }}
            QPushButton {{
                background-color: {Theme.PRIMARY.name()};
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: 500;
                font-size: 13px;
                min-width: 90px;
            }}
            QPushButton:hover {{
                background-color: {Theme.PRIMARY_HOVER.name()};
            }}
            QPushButton:pressed {{
                background-color: {Theme.PRIMARY_DARK.name()};
            }}
            QPushButton#secondary {{
                background-color: {Theme.BG_MEDIUM.name()};
                color: {Theme.TEXT_PRIMARY.name()};
                border: 1px solid {Theme.BORDER.name()};
            }}
            QPushButton#secondary:hover {{
                background-color: {Theme.BG_LIGHT.name()};
                border-color: {Theme.PRIMARY.name()};
            }}
            QPushButton#secondary:checked {{
                background-color: {Theme.BG_LIGHT.name()};
                border-color: {Theme.PRIMARY.name()};
                color: {Theme.PRIMARY.name()};
            }}
            QLabel {{
                background-color: transparent;
                color: {Theme.TEXT_SECONDARY.name()};
                font-size: 12px;
            }}
            QSlider::groove:horizontal {{
                background: {Theme.BG_DARK.name()};
                height: 6px;
                border-radius: 3px;
                border: 1px solid {Theme.BORDER.name()};
            }}
            QSlider::handle:horizontal {{
                background: {Theme.PRIMARY.name()};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                border: 2px solid {Theme.BG_MEDIUM.name()};
            }}
            QSlider::handle:horizontal:hover {{
                background: {Theme.PRIMARY_HOVER.name()};
            }}
            QSlider::sub-page:horizontal {{
                background: {Theme.PRIMARY.name()};
                border-radius: 3px;
            }}
        """)

    def _setup_ui(self):
        self._apply_stylesheet()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(20)

        controls_box = QVBoxLayout()
        controls_box.setSpacing(8)
        self.prev_btn = QPushButton("Previous")
        self.prev_btn.setObjectName("secondary")
        self.prev_btn.setToolTip("Step backward (←)")
        self.prev_btn.clicked.connect(self.step_backward.emit)
        self.play_btn = QPushButton("Play")
        self.play_btn.setToolTip("Play / Pause (Space)")
        self.play_btn.clicked.connect(self._toggle_play)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("secondary")
        self.next_btn.setToolTip("Step forward (→)")
        self.next_btn.clicked.connect(self.step_forward.emit)
        controls_box.addWidget(self.play_btn)
        controls_box.addWidget(self.prev_btn)
        controls_box.addWidget(self.next_btn)
        self.loop_btn = QPushButton("Loop")
        self.loop_btn.setObjectName("secondary")
        self.loop_btn.setToolTip("Loop playback when reaching the end")
        self.loop_btn.setCheckable(True)
        controls_box.addWidget(self.loop_btn)
        layout.addLayout(controls_box)

        sliders_box = QVBoxLayout()
        sliders_box.setSpacing(12)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Time:"))
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(100)
        self.time_slider.valueChanged.connect(self.time_changed.emit)
        time_row.addWidget(self.time_slider, 1)
        self.time_label = QLabel("0.000 μs")
        self.time_label.setMinimumWidth(100)
        time_row.addWidget(self.time_label)
        sliders_box.addLayout(time_row)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(100)
        self.speed_slider.setValue(10)
        self.speed_slider.valueChanged.connect(self.speed_changed.emit)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_label = QLabel("")
        self.speed_label.setMinimumWidth(60)
        speed_row.addWidget(self.speed_label)
        sliders_box.addLayout(speed_row)

        layout.addLayout(sliders_box, 1)

    def _toggle_play(self):
        """Toggle the play/pause button state and emit the corresponding signal."""
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setText("Pause")
            self.play_clicked.emit()
        else:
            self.play_btn.setText("Play")
            self.pause_clicked.emit()

    def set_playing(self, playing: bool):
        self.is_playing = playing
        self.play_btn.setText("Pause" if playing else "Play")

    def update_time_label(self, time_us: float, step: int, total: int):
        self.time_label.setText(f"{time_us:.3f} μs ({step}/{total})")

    def update_speed_label(self, label: str):
        self.speed_label.setText(label)

    def apply_theme(self):
        """Re-apply the active color palette to all styled elements.

        Call after ``toggle_dark()`` to update the control panel's appearance.
        """
        self._apply_stylesheet()


class InfoPanel(QFrame):
    """Tabbed panel with event log, statistics, entangled states, and charts.

    @ingroup q2nsviz_panels
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("InfoPanel")
        self._save_btn: QPushButton | None = None
        # Event-log view state: formatted lines cached per loaded trace, plus how
        # many of them are currently rendered (see update_log).
        self._log_source: list[dict[str, Any]] | None = None
        self._log_lines: list[str] = []
        self._log_visible: int = 0
        self._setup_ui()

    def _apply_stylesheet(self):
        self.setStyleSheet(f"""
            QFrame#InfoPanel {{
                background-color: {Theme.BG_MEDIUM.name()};
                border-radius: 10px;
                padding: 12px;
                border: none;
            }}
            QLabel {{
                background-color: transparent;
                color: {Theme.TEXT_PRIMARY.name()};
                font-size: 12px;
            }}
            QTextEdit {{
                background-color: {Theme.BG_DARK.name()};
                color: {Theme.TEXT_PRIMARY.name()};
                border: 1px solid {Theme.BORDER.name()};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Courier New', monospace;
                font-size: 14px;
            }}
            QTableWidget {{
                background-color: {Theme.BG_DARK.name()};
                alternate-background-color: {Theme.BG_MEDIUM.name()};
                color: {Theme.TEXT_PRIMARY.name()};
                border: 1px solid {Theme.BORDER.name()};
                border-radius: 4px;
                gridline-color: {Theme.BORDER.name()};
            }}
            QTableWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {Theme.BORDER.name()};
            }}
            QTableWidget::item:selected {{
                background-color: {Theme.PRIMARY.name()};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {Theme.BG_DARK.name()};
                color: {Theme.TEXT_SECONDARY.name()};
                padding: 8px;
                border: none;
                font-weight: 600;
            }}
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background-color: {Theme.BG_LIGHT.name()};
                color: {Theme.TEXT_SECONDARY.name()};
                padding: 7px 12px;
                border: 1px solid {Theme.BORDER.name()};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {Theme.BG_DARK.name()};
                color: {Theme.TEXT_PRIMARY.name()};
                font-weight: 600;
            }}
            QTabBar::tab:hover {{
                background-color: {Theme.BG_MEDIUM.name()};
            }}
        """)
        if self._save_btn is not None:
            self._save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_DARK.name()};
                    color: {Theme.TEXT_PRIMARY.name()};
                    border: 1px solid {Theme.BORDER.name()};
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border-color: {Theme.PRIMARY.name()};
                }}
            """)

    def _setup_ui(self):
        self._apply_stylesheet()
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        self.tabs = QTabWidget()

        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        self.tabs.addTab(log_widget, "Event Log")

        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Property", "Value"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        stats_layout.addWidget(self.stats_table)
        self.tabs.addTab(stats_widget, "Statistics")

        entangle_widget = QWidget()
        entangle_layout = QVBoxLayout(entangle_widget)
        self.entangle_table = QTableWidget()
        self.entangle_table.setColumnCount(2)
        self.entangle_table.setHorizontalHeaderLabels(["State", "Qubits"])
        self.entangle_table.horizontalHeader().setStretchLastSection(True)
        self.entangle_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.entangle_table.verticalHeader().setVisible(False)
        self.entangle_table.setAlternatingRowColors(True)
        self.entangle_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        entangle_layout.addWidget(self.entangle_table)
        self.tabs.addTab(entangle_widget, "Entangled States")

        if MATPLOTLIB_AVAILABLE:
            charts_widget = QWidget()
            charts_layout = QVBoxLayout(charts_widget)
            self.chart_canvas = ChartCanvas()
            charts_layout.addWidget(self.chart_canvas)
            save_btn = QPushButton("Save chart as PNG/PDF\u2026")
            self._save_btn = save_btn
            save_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_DARK.name()};
                    color: {Theme.TEXT_PRIMARY.name()};
                    border: 1px solid {Theme.BORDER.name()};
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    border-color: {Theme.PRIMARY.name()};
                }}
            """)
            save_btn.clicked.connect(self._save_chart)
            charts_layout.addWidget(save_btn)
            self.tabs.addTab(charts_widget, "Charts")
        else:
            self.chart_canvas = None

        layout.addWidget(self.tabs)

        self._last_chart_state: tuple | None = None
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _save_chart(self):
        """Open a save-file dialog and export the chart figure to an image file."""
        if not self.chart_canvas:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chart",
            "chart.png",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg);;All Files (*)",
        )
        if path:
            self.chart_canvas.fig.savefig(path, dpi=300, bbox_inches="tight")

    def _on_tab_changed(self, _index: int):
        """Re-render the chart when the chart tab is brought into view.

        Lazy redraw: the chart is updated only when the tab becomes visible,
        avoiding unnecessary Matplotlib renders during log or entanglement updates.
        """
        if (
            self.chart_canvas
            and self.tabs.currentWidget() is self.chart_canvas.parent()
            and self._last_chart_state is not None
        ):
            self.chart_canvas.update_charts(*self._last_chart_state)

    @staticmethod
    def _format_log_line(event: dict[str, Any]) -> str:
        t_us = event.get("t_ns", 0) / 1000
        node = event.get("node", "")
        prefix = f"[{t_us:8.3f} μs]"
        return f"{prefix} [{node}] {event.get('text', '')}" if node else f"{prefix} {event.get('text', '')}"

    def update_log(self, log_events: list[dict[str, Any]], visible: int):
        """Show the first *visible* entries of the trace's ``traceText`` log.

        The log only grows as the clock advances, so stepping forward appends
        the new lines instead of re-rendering the whole document; the view is
        rebuilt only when the user scrubs backward or loads a new trace.

        @param log_events  ``SimulationStateManager.log_events`` -- every
                           ``traceText`` event of the trace, in time order.
        @param visible     Number of leading entries to display, from
                           ``SimulationStateManager.log_count_at()``.
        """
        if log_events is not self._log_source:
            self._log_source = log_events
            self._log_lines = [self._format_log_line(event) for event in log_events]
            self._log_visible = 0
            self.log_text.clear()
        if visible == self._log_visible:
            return

        scrollbar = self.log_text.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        cursor = self.log_text.textCursor()
        if visible > self._log_visible:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            head = "\n" if self._log_visible else ""
            cursor.insertText(head + "\n".join(self._log_lines[self._log_visible : visible]))
        elif visible == 0:
            self.log_text.clear()
        else:
            # Scrubbed backward: drop the trailing lines (and the newline that
            # precedes them) rather than re-rendering the whole document.
            first_dropped = self.log_text.document().findBlockByNumber(visible)
            cursor.setPosition(max(first_dropped.position() - 1, 0))
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
        self._log_visible = visible

        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def update_stats(
        self,
        nodes: int,
        events: int,
        max_time: float,
        qubits: int = 0,
        entangled: int = 0,
        measured: int = 0,
        lost: int = 0,
        discarded: int = 0,
    ):
        """Refresh the statistics table with the given snapshot values.

        @param nodes     Total number of network nodes in the simulation.
        @param events    Total number of events in the loaded trace.
        @param max_time  Simulation duration in microseconds.
        @param qubits    Number of live qubits at the current time.
        @param entangled Number of entangled multi-qubit states.
        @param measured  Number of measured qubits.
        @param lost      Number of lost qubits (removed, neither measured nor discarded).
        @param discarded Number of qubits removed with ``reason == "discarded"``.
        """
        stats = [
            ("Network Nodes", str(nodes)),
            ("Simulation Events", str(events)),
            ("Duration", f"{max_time:.3f} μs"),
            ("Live Qubits", str(qubits)),
            ("Measured Qubits", str(measured)),
            ("Lost Qubits", str(lost)),
            ("Discarded Qubits", str(discarded)),
            ("Entangled States (≥2)", str(entangled)),
        ]
        self.stats_table.setRowCount(len(stats))
        for i, (prop, value) in enumerate(stats):
            self.stats_table.setItem(i, 0, QTableWidgetItem(prop))
            self.stats_table.setItem(i, 1, QTableWidgetItem(value))

    def update_entanglement(self, states: dict[str, tuple[str, ...]]):
        """Refresh the entanglement-states tab.

        Rows are sorted by descending component size, then alphabetically,
        so the largest entangled states appear at the top.

        @param states  Multi-qubit entanglement groups from
                       ``Snapshot.entangled_states``.
        """
        ordered_states = sorted(
            (sorted(members) for members in states.values()), key=lambda members: (-len(members), members)
        )
        self.entangle_table.setHorizontalHeaderLabels(["State", "Qubits"])
        self.entangle_table.setRowCount(len(ordered_states))
        for i, members in enumerate(ordered_states):
            self.entangle_table.setItem(i, 0, QTableWidgetItem(f"State {i + 1}"))
            self.entangle_table.setItem(i, 1, QTableWidgetItem(", ".join(members)))

    def update_charts(self, state_manager, snap):
        """Forward chart data to ``ChartCanvas`` if the Charts tab is visible.

        Stores ``(state_manager, snap)`` so the charts can be redrawn
        lazily when the user switches to the Charts tab.

        @param state_manager  Shared ``SimulationStateManager`` instance.
        @param snap           ``Snapshot`` at the current simulation time,
                              queried by the controller.
        """
        self._last_chart_state = (state_manager, snap)
        if self.chart_canvas and self.tabs.currentWidget() is self.chart_canvas.parent():
            self.chart_canvas.update_charts(state_manager, snap)

    def apply_theme(self):
        """Re-apply the active color palette to all styled elements.

        Call after ``toggle_dark()`` to update the info panel's appearance.
        """
        self._apply_stylesheet()


__all__ = ["ControlPanel", "InfoPanel"]
