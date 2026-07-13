# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

import logging
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QToolTip, QWidget

from ..logic import SimulationStateManager, Snapshot
from .theme import Theme, ui_font_family

logger = logging.getLogger(__name__)


def _diamond_path(x: float, y: float, size: float) -> QPainterPath:
    """Return the diamond marker used for classical packets and in-flight cbits."""
    path = QPainterPath()
    path.moveTo(x, y - size)
    path.lineTo(x + size, y)
    path.lineTo(x, y + size)
    path.lineTo(x - size, y)
    path.closeSubpath()
    return path


class NetworkCanvas(QWidget):
    """Custom widget that renders the network topology and quantum state.

    Paint order (back to front)
    ---------------------------
    1. Background fill
    2. Channel lines
    3. Node boxes (each with its resident qubits and classical bits)
    4. Lost-qubit crosses
    5. Measured-qubit markers
    6. In-flight qubits (colored circles on the channel lane)
    7. In-flight classical packets (``sendPacket``)
    8. In-flight classical bits (``sendCbit``)
    9. Entanglement links (colored lines between qubit circles)
    10. Legend overlay (optional)
    11. Current-time ``traceText`` overlay

    A qubit inside an operation window wears a ring whose style names the
    operation: dashed single for ``entangle``, solid single for ``measure``,
    solid double for ``graphMeasure``.

    The widget owns no state of its own beyond the ``Snapshot`` pushed by
    the ``QuantumVisualizerWindow`` controller via ``set_snapshot()`` and
    the qubit sets derived from it.  The shared ``state_manager`` is read
    only for the static topology and the raw event list (in-flight
    animation geometry and ``traceText`` overlays).  The widget is **not**
    thread-safe; call only from the Qt main thread.
    @ingroup q2nsviz_canvas
    """

    # --- Layout constants (pixels) ------------------------------------------
    NODE_WIDTH: int = 120  # pixel width of each node box
    NODE_HEIGHT: int = 70  # pixel height of each node box
    QUBIT_RADIUS: int = 8  # radius of qubit circles
    CHANNEL_WIDTH: int = 6  # stroke width for channel lines
    LAYOUT_MARGIN_X: int = 100  # left/right canvas margin for the node layout area
    LAYOUT_MARGIN_Y: int = 75  # top/bottom canvas margin for the node layout area
    LEGEND_RESERVE: int = 210  # left gutter reserved for the legend panel so it never overlaps nodes

    def __init__(self, state_manager: SimulationStateManager):
        super().__init__()
        self.state_manager = state_manager
        self._snap: Snapshot | None = None
        self.current_time = 0
        self.inflight_qubits: set[str] = set()
        self.removed_qubits: set[str] = set()
        self.gate_qubits: set[str] = set()
        self.measuring_qubits: set[str] = set()
        self.graph_measuring_qubits: set[str] = set()
        self.lost_qubits: set[str] = set()
        self.entangled_qubits: set[str] = set()
        self.inflight_cbits: set[str] = set()
        self.removed_cbits: set[str] = set()
        self._legend_visible: bool = True
        self._show_node_labels: bool = True
        self.setMinimumSize(600, 400)
        self.setMouseTracking(True)
        self._qubit_positions_cache: dict[str, QPointF] = {}
        self._node_positions_cache: dict[str, QPointF] = {}

    def _events_of(self, event_type: str) -> list[dict]:
        """Return the loaded events of one type, from the manager's load-time index."""
        return self.state_manager.events_by_type.get(event_type, [])

    def set_snapshot(self, snap: Snapshot):
        """Display the state carried by *snap* and repaint.

        Called by the ``QuantumVisualizerWindow`` controller, which performs
        the per-frame ``snapshot_at()`` query and pushes the resulting
        ``Snapshot`` here.  Unpacks the inflight, removed, and
        in-progress-operation qubit sets, then triggers a full repaint.
        Must be called from the Qt main thread.

        @param snap  ``Snapshot`` of the network state to render.
        """
        self._snap = snap
        self.current_time = snap.t_ns
        self.inflight_qubits = set(snap.inflight_qubits)
        self.removed_qubits = set(snap.removed_qubits)
        self.gate_qubits = set(snap.gate_qubits)
        self.measuring_qubits = set(snap.measuring_qubits)
        self.graph_measuring_qubits = set(snap.graph_measuring_qubits)
        self.inflight_cbits = set(snap.inflight_cbits)
        self.removed_cbits = set(snap.removed_cbits)
        self.lost_qubits = set(snap.lost_qubits)
        self.entangled_qubits = set().union(*snap.entangled_states.values())
        self.update()

    def reset(self):
        """Clear all transient qubit sets and repaint an empty canvas.

        Called when the user loads a new file or the application starts.
        """
        self._snap = None
        self.current_time = 0
        self.inflight_qubits.clear()
        self.removed_qubits.clear()
        self.gate_qubits.clear()
        self.measuring_qubits.clear()
        self.graph_measuring_qubits.clear()
        self.lost_qubits.clear()
        self.entangled_qubits.clear()
        self.inflight_cbits.clear()
        self.removed_cbits.clear()
        # An empty canvas short-circuits paintEvent before the hit-test caches are
        # rebuilt, so clear them here or hover would still report the old topology.
        self._qubit_positions_cache.clear()
        self._node_positions_cache.clear()
        self.update()

    def mouseMoveEvent(self, event):
        """Hit-test nodes and in-flight qubits on hover and update the tooltip.

        Tests each node bounding box first; on a miss, scans in-flight qubits.
        Updates the Qt tooltip text so the OS displays it near the cursor.

        @param event  Qt mouse-move event providing the current cursor position.
        """
        pos = event.position()
        snap_qubits = self._snap.qubits if self._snap else {}
        snap_cbits = self._snap.cbits if self._snap else {}
        for node_label, npos in self._node_positions_cache.items():
            if abs(pos.x() - npos.x()) <= self.NODE_WIDTH / 2 and abs(pos.y() - npos.y()) <= self.NODE_HEIGHT / 2:
                qubit_count = sum(
                    1 for q in snap_qubits.values() if q.node == node_label and q.label not in self.removed_qubits
                )
                cbit_count = sum(
                    1 for c in snap_cbits.values() if c.node == node_label and c.label not in self.removed_cbits
                )
                tip = f"{node_label}  |  qubits: {qubit_count}  cbits: {cbit_count}"
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                return
        hit_radius = self.QUBIT_RADIUS + 4
        for label, qpos in self._qubit_positions_cache.items():
            dx = pos.x() - qpos.x()
            dy = pos.y() - qpos.y()
            if math.sqrt(dx * dx + dy * dy) <= hit_radius:
                QToolTip.showText(event.globalPosition().toPoint(), label, self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        """Render one frame of the network visualization.

        Computes node and qubit screen positions once, then executes the
        layered draw passes listed in the class docstring.  Caches qubit
        positions in ``_qubit_positions_cache`` for use by the tooltip
        hit-test in ``mouseMoveEvent``.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Theme.BG_DARK)
        if not self.state_manager.nodes:
            self._draw_empty_state(painter)
            return
        node_positions = self._calculate_positions()
        qubit_positions = self._get_qubit_positions(node_positions)
        self._draw_channels(painter, node_positions)
        self._draw_nodes(painter, node_positions)
        self._draw_lost_qubits(painter, node_positions)
        self._draw_measured_qubits(painter, node_positions)
        self._draw_inflight_qubits(painter, qubit_positions)
        self._draw_inflight_packets(painter, node_positions)
        self._draw_inflight_cbits(painter, node_positions)
        self._draw_entanglement(painter, qubit_positions)
        if self._legend_visible:
            self._draw_legend(painter)
        self._draw_event_overlay(painter)
        self._qubit_positions_cache = qubit_positions
        self._node_positions_cache = node_positions

    def _draw_empty_state(self, painter: QPainter):
        painter.setPen(QPen(Theme.TEXT_MUTED))
        painter.setFont(QFont(ui_font_family(), 14))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Load a simulation file to begin")

    def _calculate_positions(self) -> dict[str, QPointF]:
        """Compute screen centre coordinates for each node.

        Nodes with explicit (x, y) percentages from ``createNode`` events
        are placed using those percentages relative to the layout area.
        All other nodes are arranged on a circle centred on the widget.

        When the legend is visible, the layout area is inset from the left by
        ``LEGEND_RESERVE`` so that nodes never render underneath the legend panel.

        @returns  ``{node_label: QPointF}`` for every node in
                  ``state_manager.nodes``.
        """
        positions: dict[str, QPointF] = {}
        nodes = list(self.state_manager.nodes.items())
        if not nodes:
            return positions
        left_reserve = self.LEGEND_RESERVE if self._legend_visible else 0
        width = self.width() - 2 * self.LAYOUT_MARGIN_X - left_reserve
        height = self.height() - 2 * self.LAYOUT_MARGIN_Y
        num_nodes = len(nodes)
        for idx, (label, node) in enumerate(nodes):
            if node.has_explicit_position:
                x = self.LAYOUT_MARGIN_X + left_reserve + width * (node.x_pct / 100)
                y = self.LAYOUT_MARGIN_Y + height * (node.y_pct / 100)
            else:
                angle = (2 * math.pi * idx / num_nodes) - math.pi / 2
                x = self.width() / 2 + left_reserve / 2 + (width / 2.5) * math.cos(angle)
                y = self.height() / 2 + (height / 2.5) * math.sin(angle)
            positions[label] = QPointF(x, y)
        return positions

    def _draw_channels(self, painter: QPainter, positions: dict[str, QPointF]):
        """Render quantum and classical channel lines with perpendicular lane offset.

        Node pairs that share both a quantum and a classical channel receive
        parallel lanes offset perpendicularly so neither line obscures the other.
        Duplicate channel definitions are de-duplicated at load time, so any that
        slip through here are silently discarded.

        @param painter    Active ``QPainter`` for the canvas widget.
        @param positions  Mapping of node label to widget-space centre point.
        """
        channel_pairs: dict[tuple, dict] = {}
        for channel in self.state_manager.channels:
            if channel.from_node not in positions or channel.to_node not in positions:
                continue
            pair = tuple(sorted([channel.from_node, channel.to_node]))
            if pair not in channel_pairs:
                channel_pairs[pair] = {"quantum": None, "classical": None}
            if channel_pairs[pair].get(channel.kind) is not None:
                continue  # already de-duplicated at load time
            channel_pairs[pair][channel.kind] = channel

        for (node1, node2), channels in channel_pairs.items():
            start = positions[node1]
            end = positions[node2]
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.sqrt(dx * dx + dy * dy) or 1
            perp_x = -dy / length
            perp_y = dx / length

            if channels["quantum"]:
                q_start = QPointF(
                    start.x() + perp_x * self.CHANNEL_WIDTH / 2, start.y() + perp_y * self.CHANNEL_WIDTH / 2
                )
                q_end = QPointF(
                    end.x() + perp_x * self.CHANNEL_WIDTH / 2, end.y() + perp_y * self.CHANNEL_WIDTH / 2
                )
                pen = QPen(Theme.QUANTUM_CHANNEL, self.CHANNEL_WIDTH)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawLine(q_start, q_end)

            if channels["classical"]:
                c_start = QPointF(
                    start.x() - perp_x * self.CHANNEL_WIDTH / 2, start.y() - perp_y * self.CHANNEL_WIDTH / 2
                )
                c_end = QPointF(
                    end.x() - perp_x * self.CHANNEL_WIDTH / 2, end.y() - perp_y * self.CHANNEL_WIDTH / 2
                )
                pen = QPen(Theme.CLASSICAL_CHANNEL, self.CHANNEL_WIDTH)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawLine(c_start, c_end)

    def _draw_entanglement(self, painter: QPainter, qubit_positions: dict[str, QPointF]):
        """Draw entanglement edges between qubit circles.

        Each edge of the snapshot's ``ent_graph`` that connects two qubits
        with known screen positions is rendered as a colored line.  Qubits
        in ``removed_qubits`` are excluded to avoid artifacts from stale
        edges that have not yet been cleaned up by a ``removeQubit`` event.

        @param painter         Active ``QPainter`` in the correct state.
        @param qubit_positions Screen positions returned by
                               ``_get_qubit_positions()``.
        """
        pen = QPen(Theme.ENTANGLEMENT, 2.5)
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setOpacity(0.85)

        drawn = set()
        ent_graph = self._snap.ent_graph if self._snap else {}
        for qubit1, neighbors in ent_graph.items():
            if qubit1 in self.removed_qubits or qubit1 not in qubit_positions:
                continue

            for qubit2 in neighbors:
                if qubit2 in self.removed_qubits or qubit2 not in qubit_positions:
                    continue

                pair = tuple(sorted([qubit1, qubit2]))
                if pair in drawn:
                    continue
                drawn.add(pair)
                painter.drawLine(qubit_positions[qubit1], qubit_positions[qubit2])
        painter.setOpacity(1.0)

    def _draw_lost_qubits(self, painter: QPainter, positions: dict[str, QPointF]):
        if not self.lost_qubits:
            return
        loss_by_node: dict[str, list[str]] = {}
        snap_qubits = self._snap.qubits if self._snap else {}
        for label in self.lost_qubits:
            qubit = snap_qubits.get(label)
            if qubit and qubit.node and qubit.node in positions:
                loss_by_node.setdefault(qubit.node, []).append(label)

        fill = QColor(Theme.QUBIT_LOST)
        fill.setAlpha(200)
        cross_pen = QPen(QColor(Theme.QUBIT_LOST).darker(140), 1.5)
        r = self.QUBIT_RADIUS - 2

        for node_label, lost_labels in loss_by_node.items():
            center = positions[node_label]
            num = len(lost_labels)
            spacing = min(18, (self.NODE_WIDTH - 30) / max(num, 1))
            start_x = center.x() - (num - 1) * spacing / 2
            y = center.y() + self.NODE_HEIGHT / 2 + r + 6
            for i in range(num):
                pos = QPointF(start_x + i * spacing, y)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(fill))
                painter.drawEllipse(pos, r, r)
                d = r * 0.55
                painter.setPen(cross_pen)
                painter.drawLine(QPointF(pos.x() - d, pos.y() - d), QPointF(pos.x() + d, pos.y() + d))
                painter.drawLine(QPointF(pos.x() + d, pos.y() - d), QPointF(pos.x() - d, pos.y() + d))

    def _draw_measured_qubits(self, painter: QPainter, positions: dict[str, QPointF]):
        """Render all measured qubits as gray circles below their node.

        Drawn whether or not a ``removeQubit`` event also fired, so a measurement
        always leaves a marker distinct from the lost-qubit cross.

        @param painter    Active ``QPainter``.
        @param positions  Node screen positions from ``_calculate_positions()``.
        """
        measured = set(self._snap.measured_qubits) if self._snap else set()
        if not measured:
            return
        by_node: dict[str, list[str]] = {}
        for label in measured:
            qubit = self._snap.qubits.get(label)
            if qubit and qubit.node and qubit.node in positions:
                by_node.setdefault(qubit.node, []).append(label)

        fill = QColor(Theme.QUBIT_MEASURED)
        fill.setAlpha(200)
        tick_pen = QPen(QColor(Theme.QUBIT_MEASURED).darker(120), 1.5)
        r = self.QUBIT_RADIUS - 2

        for node_label, labels in by_node.items():
            center = positions[node_label]
            num = len(labels)
            spacing = min(18, (self.NODE_WIDTH - 30) / max(num, 1))
            # Measured qubits appear one row below lost qubits
            start_x = center.x() - (num - 1) * spacing / 2
            y = center.y() + self.NODE_HEIGHT / 2 + r + 6 + (r * 2 + 4)
            for i in range(num):
                pos = QPointF(start_x + i * spacing, y)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(fill))
                painter.drawEllipse(pos, r, r)
                painter.setPen(tick_pen)
                painter.drawLine(
                    QPointF(pos.x() - r * 0.45, pos.y()), QPointF(pos.x() - r * 0.1, pos.y() + r * 0.45)
                )
                painter.drawLine(
                    QPointF(pos.x() - r * 0.1, pos.y() + r * 0.45), QPointF(pos.x() + r * 0.5, pos.y() - r * 0.4)
                )

    @staticmethod
    def _draw_soft_shadow(painter: QPainter, rect: QRectF, radius: float):
        """Draw a soft drop shadow beneath a rounded-rect card."""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        layers = 8
        for i in range(layers):
            frac = (i + 1) / layers
            spread = 7.0 * (1.0 - frac)
            painter.setBrush(QColor(15, 23, 42, int(9 * frac)))
            shadow = QRectF(
                rect.left() - spread,
                rect.top() - spread + 2.5,
                rect.width() + 2 * spread,
                rect.height() + 2 * spread,
            )
            painter.drawRoundedRect(shadow, radius + spread, radius + spread)
        painter.restore()

    def _draw_nodes(self, painter: QPainter, positions: dict[str, QPointF]):
        """Render each network node as a rounded card.

        Draws qubits and classical bits stacked beneath the node box via
        ``_draw_node_qubits`` and ``_draw_node_cbits``.  Node labels are
        elided to fit the node width when ``_show_node_labels`` is set.

        @param painter    Active ``QPainter`` for the canvas widget.
        @param positions  Mapping of node label to widget-space centre point.
        """
        radius = 12
        for label, pos in positions.items():
            rect = QRectF(
                pos.x() - self.NODE_WIDTH / 2, pos.y() - self.NODE_HEIGHT / 2, self.NODE_WIDTH, self.NODE_HEIGHT
            )
            self._draw_soft_shadow(painter, rect, radius)
            painter.setPen(QPen(Theme.BORDER, 1.0))
            painter.setBrush(QBrush(Theme.BG_MEDIUM))
            painter.drawRoundedRect(rect, radius, radius)
            if self._show_node_labels:
                painter.setPen(QPen(QColor(Theme.NODE_TEXT)))
                painter.setFont(QFont(ui_font_family(), 11, QFont.Weight.Medium))
                fm = QFontMetrics(painter.font())
                elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(self.NODE_WIDTH - 12))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
            self._draw_node_qubits(painter, label, pos)
            self._draw_node_cbits(painter, label, pos)

    def _get_live_qubit_label_set(self) -> set[str]:
        """Return the set of qubit labels that are alive (neither measured nor removed).

        @returns  Live qubit labels from the current snapshot.
        """
        return set(self._snap.live_qubit_labels) if self._snap else set()

    def _get_live_cbit_label_set(self) -> set[str]:
        """Return the set of classical bit labels that are not yet removed."""
        if self._snap is None:
            return set()
        return {label for label in self._snap.cbits if label not in self.removed_cbits}

    def _get_node_qubit_positions(
        self, node_label: str, center: QPointF, live_labels: set[str]
    ) -> dict[str, QPointF]:
        snap_qubits = self._snap.qubits if self._snap else {}
        qubits = [
            label
            for label, qubit in snap_qubits.items()
            if qubit.node == node_label and label in live_labels and label not in self.inflight_qubits
        ]
        if not qubits:
            return {}
        num_qubits = len(qubits)
        spacing = min(18, (self.NODE_WIDTH - 30) / max(num_qubits, 1))
        start_x = center.x() - (num_qubits - 1) * spacing / 2
        y = center.y() + self.NODE_HEIGHT / 2 - 16
        return {qubit_label: QPointF(start_x + index * spacing, y) for index, qubit_label in enumerate(qubits)}

    def _get_node_cbit_positions(
        self, node_label: str, center: QPointF, live_labels: set[str]
    ) -> dict[str, QPointF]:
        """Return screen positions for classical bits stored at *node_label*."""
        snap_cbits = self._snap.cbits if self._snap else {}
        cbits = [
            label
            for label, cbit in snap_cbits.items()
            if cbit.node == node_label and label in live_labels and label not in self.inflight_cbits
        ]
        if not cbits:
            return {}
        num_cbits = len(cbits)
        spacing = min(16, (self.NODE_WIDTH - 30) / max(num_cbits, 1))
        start_x = center.x() - (num_cbits - 1) * spacing / 2
        # Classical bits appear one row below the qubit row
        y = center.y() + self.NODE_HEIGHT / 2 - 4
        return {cbit_label: QPointF(start_x + index * spacing, y) for index, cbit_label in enumerate(cbits)}

    def _draw_node_cbits(self, painter: QPainter, node_label: str, center: QPointF):
        """Render classical bits stored at *node_label* as small squares."""
        cbit_positions = self._get_node_cbit_positions(node_label, center, self._get_live_cbit_label_set())
        if not cbit_positions:
            return
        half = 5  # half-side of the classical-bit square
        for _cbit_label, pos in cbit_positions.items():
            color = QColor(Theme.CBIT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 23, 42, 40))
            painter.drawRoundedRect(QRectF(pos.x() - half, pos.y() - half + 1.0, half * 2, half * 2), 2, 2)
            painter.setPen(QPen(color.darker(118), 1.0))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(pos.x() - half, pos.y() - half, half * 2, half * 2), 2, 2)

    def _draw_node_qubits(self, painter: QPainter, node_label: str, center: QPointF):
        """Render qubits stored at *node_label* as small circles."""
        qubit_positions = self._get_node_qubit_positions(node_label, center, self._get_live_qubit_label_set())
        if not qubit_positions:
            return
        for qubit_label, pos in qubit_positions.items():
            color = Theme.QUBIT_ENTANGLED if qubit_label in self.entangled_qubits else Theme.QUBIT_PRODUCT
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 23, 42, 45))
            painter.drawEllipse(QPointF(pos.x(), pos.y() + 1.0), self.QUBIT_RADIUS, self.QUBIT_RADIUS)
            painter.setPen(QPen(QColor(color).darker(115), 1.0))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(pos, self.QUBIT_RADIUS, self.QUBIT_RADIUS)
            if qubit_label in self.gate_qubits:
                gate_pen = QPen(QColor(Theme.HALO_GATE), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(gate_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pos, self.QUBIT_RADIUS + 4, self.QUBIT_RADIUS + 4)
            elif qubit_label in self.measuring_qubits:
                painter.setPen(QPen(QColor(Theme.HALO_MEASURE), 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pos, self.QUBIT_RADIUS + 4, self.QUBIT_RADIUS + 4)
            elif qubit_label in self.graph_measuring_qubits:
                gm_color = QColor(Theme.HALO_GRAPH_MEASURE)
                painter.setPen(QPen(gm_color, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pos, self.QUBIT_RADIUS + 4, self.QUBIT_RADIUS + 4)
                painter.drawEllipse(pos, self.QUBIT_RADIUS + 8, self.QUBIT_RADIUS + 8)

    def _draw_inflight_cbits(self, painter: QPainter, positions: dict[str, QPointF]):
        """Animate in-flight cbits as classical packet diamonds."""
        for event in self._events_of("sendCbit"):
            t0 = event.get("t0_ns", 0)
            t1 = event.get("t1_ns", 0)
            if not (t0 <= self.current_time < t1):
                continue
            from_node = event.get("from")
            to_node = event.get("to")
            if from_node not in positions or to_node not in positions:
                continue
            progress = (self.current_time - t0) / (t1 - t0) if t1 > t0 else 0
            start = positions[from_node]
            end = positions[to_node]
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.sqrt(dx * dx + dy * dy) or 1
            perp_x = -dy / length
            perp_y = dx / length
            # Travel on the classical channel lane (same side as sendPacket)
            if sorted([from_node, to_node])[0] == from_node:
                lane_x, lane_y = -perp_x * 3, -perp_y * 3
            else:
                lane_x, lane_y = perp_x * 3, perp_y * 3
            x = start.x() + dx * progress + lane_x
            y = start.y() + dy * progress + lane_y
            painter.setPen(QPen(QColor(Theme.BG_MEDIUM), 1.5))
            painter.setBrush(QBrush(QColor(Theme.PACKET_CLASSICAL)))
            painter.drawPath(_diamond_path(x, y, 7))

    def _get_qubit_positions(self, positions: dict[str, QPointF]) -> dict[str, QPointF]:
        """Return screen positions for all qubits, including in-flight ones."""
        qubit_positions = {}
        live_labels = self._get_live_qubit_label_set()
        for node_label, center in positions.items():
            qubit_positions.update(self._get_node_qubit_positions(node_label, center, live_labels))

        for event in self._events_of("sendQubit"):
            t0 = event.get("t0_ns", 0)
            t1 = event.get("t1_ns", 0)
            if not (t0 <= self.current_time < t1):
                continue
            qubit_label = event.get("bit")
            from_node = event.get("from")
            to_node = event.get("to")
            if from_node not in positions or to_node not in positions:
                continue
            progress = (self.current_time - t0) / (t1 - t0) if t1 > t0 else 0
            start = positions[from_node]
            end = positions[to_node]
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.sqrt(dx * dx + dy * dy) or 1
            perp_x = -dy / length
            perp_y = dx / length
            # Alphabetical node order determines which lane (side of the channel
            # line) the qubit occupies, ensuring stable positioning each frame.
            if sorted([from_node, to_node])[0] == from_node:
                lane_x, lane_y = perp_x * 3, perp_y * 3
            else:
                lane_x, lane_y = -perp_x * 3, -perp_y * 3
            qubit_positions[qubit_label] = QPointF(
                start.x() + dx * progress + lane_x, start.y() + dy * progress + lane_y
            )
        return qubit_positions

    def _draw_inflight_qubits(self, painter: QPainter, qubit_positions: dict[str, QPointF]):
        """Render in-flight qubits as filled circles on the channel lane.

        Only qubits currently in ``inflight_qubits`` are drawn.  Their
        color is determined by the qubit's semantic state (product vs.
        entangled) as defined by the active color palette.

        @param painter         Active ``QPainter``.
        @param qubit_positions Screen positions returned by
                               ``_get_qubit_positions()``, which places every
                               in-flight qubit on its channel lane.
        """
        for qubit_label in self.inflight_qubits:
            pos = qubit_positions.get(qubit_label)
            if pos is None:
                continue
            color = Theme.QUBIT_ENTANGLED if qubit_label in self.entangled_qubits else Theme.QUBIT_PRODUCT
            painter.setPen(QPen(QColor(Theme.BG_MEDIUM), 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(pos, self.QUBIT_RADIUS, self.QUBIT_RADIUS)

    def _draw_inflight_packets(self, painter: QPainter, positions: dict[str, QPointF]):
        """Render classical network packets in flight between nodes.

        Iterates ``sendPacket`` events and draws a diamond marker at the
        proportional position along the source-to-destination vector for any
        packet whose transit window ``[t0_ns, t1_ns)`` contains the current
        simulation time.

        @param painter    Active ``QPainter`` for the canvas widget.
        @param positions  Mapping of node label to widget-space centre point.
        """
        for event in self._events_of("sendPacket"):
            t0 = event.get("t0_ns", 0)
            t1 = event.get("t1_ns", 0)
            if not (t0 <= self.current_time < t1):
                continue
            from_node = event.get("from")
            to_node = event.get("to")
            label = event.get("label", "")
            if from_node not in positions or to_node not in positions:
                continue
            progress = (self.current_time - t0) / (t1 - t0) if t1 > t0 else 0
            start = positions[from_node]
            end = positions[to_node]
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.sqrt(dx * dx + dy * dy) or 1
            perp_x = -dy / length
            perp_y = dx / length
            # Packets travel on the opposite lane from qubits (classical
            # channel side). Alphabetical node order determines which side.
            if sorted([from_node, to_node])[0] == from_node:
                lane_x, lane_y = -perp_x * 3, -perp_y * 3
            else:
                lane_x, lane_y = perp_x * 3, perp_y * 3
            x = start.x() + dx * progress + lane_x
            y = start.y() + dy * progress + lane_y
            color = {"tcp": Theme.PACKET_TCP, "udp": Theme.PACKET_UDP}.get(
                event.get("protocol", "").lower(), Theme.PACKET_CLASSICAL
            )
            size = 7
            painter.setPen(QPen(QColor(Theme.BG_MEDIUM), 1.5))
            painter.setBrush(QBrush(color))
            painter.drawPath(_diamond_path(x, y, size))
            if label:
                short_label = label[:18] + ("…" if len(label) > 18 else "")
                painter.setPen(QPen(Theme.TEXT_SECONDARY))
                painter.setFont(QFont(ui_font_family(), 8))
                painter.drawText(QPointF(x + size + 4, y + 4), short_label)

    def toggle_legend(self) -> bool:
        """Toggle legend visibility and repaint.  Returns the new visible state."""
        self._legend_visible = not self._legend_visible
        self.update()
        return self._legend_visible

    def toggle_node_labels(self) -> bool:
        """Toggle node label visibility and repaint.  Returns the new visible state."""
        self._show_node_labels = not self._show_node_labels
        self.update()
        return self._show_node_labels

    def _draw_legend(self, painter: QPainter):
        """Render a grouped color-legend card in the bottom-left corner.

        Entries are organised into categories separated by hairline spacing.
        Each row pairs a graphical icon with a text label; the icon style
        matches what is rendered on the canvas so the legend stays consistent.
        """
        ROW_H = 22
        GROUP_GAP = 9
        ICON_R = 6.5
        HALO_R = 10.0
        ICON_CX = 17
        TEXT_X = ICON_CX + HALO_R + 9
        FONT_SIZE = 10

        groups = [
            [
                ("channel", Theme.QUANTUM_CHANNEL, self.CHANNEL_WIDTH, "Quantum channel"),
                ("channel", Theme.CLASSICAL_CHANNEL, self.CHANNEL_WIDTH, "Classical channel"),
                ("link", Theme.ENTANGLEMENT, 2.5, "Entanglement link"),
            ],
            [
                ("qubit", Theme.QUBIT_PRODUCT, 0, "Qubit (product state)"),
                ("qubit", Theme.QUBIT_ENTANGLED, 0, "Qubit (entangled)"),
                ("cbit", Theme.CBIT, 0, "Classical bit"),
                ("lost", Theme.QUBIT_LOST, 0, "Lost qubit"),
                ("measured", Theme.QUBIT_MEASURED, 0, "Measured qubit"),
            ],
            [
                ("halo_gate", Theme.HALO_GATE, 0, "Gate (processing)"),
                ("halo_measure", Theme.HALO_MEASURE, 0, "Measuring"),
                ("halo_graph", Theme.HALO_GRAPH_MEASURE, 0, "Graph-measuring"),
            ],
            [
                ("packet", Theme.PACKET_CLASSICAL, 0, "Classical packet"),
                ("packet", Theme.PACKET_TCP, 0, "TCP packet"),
                ("packet", Theme.PACKET_UDP, 0, "UDP packet"),
            ],
        ]
        entries = [entry for group in groups for entry in group]

        HEADER_H = 30
        pad = 10
        _fm = QFontMetrics(QFont(ui_font_family(), FONT_SIZE))
        hdr_font = QFont(ui_font_family(), FONT_SIZE - 1)
        hdr_font.setWeight(QFont.Weight.DemiBold)
        hdr_font.setCapitalization(QFont.Capitalization.AllUppercase)
        hdr_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        _fm_hdr = QFontMetrics(hdr_font)
        panel_w = max(
            TEXT_X + max(_fm.horizontalAdvance(text) for *_, text in entries) + 16,
            _fm_hdr.horizontalAdvance("LEGEND") + pad * 2 + 4,
        )
        panel_h = HEADER_H + len(entries) * ROW_H + (len(groups) - 1) * GROUP_GAP + pad
        if panel_h + 18 > self.height() or panel_w + 18 > self.width():
            return
        panel_x = 10
        panel_y = self.height() - panel_h - 10
        card = QRectF(panel_x, panel_y, panel_w, panel_h)
        self._draw_soft_shadow(painter, card, 12)
        bg = QColor(Theme.BG_MEDIUM)
        bg.setAlpha(245)
        painter.setPen(QPen(QColor(Theme.BORDER), 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(card, 12, 12)

        painter.setFont(hdr_font)
        painter.setPen(QPen(QColor(Theme.TEXT_MUTED)))
        hdr_y = panel_y + (HEADER_H - _fm_hdr.height()) / 2 + _fm_hdr.ascent()
        painter.drawText(QPointF(panel_x + pad + 2, hdr_y), "Legend")

        painter.setFont(QFont(ui_font_family(), FONT_SIZE))
        cy = panel_y + HEADER_H + ROW_H * 0.5
        for gi, group in enumerate(groups):
            if gi > 0:
                cy += GROUP_GAP
            for kind, color, line_w, text in group:
                c = QColor(color)
                cx_ = panel_x + ICON_CX
                if kind in ("channel", "link"):
                    pen = QPen(c, min(line_w, 3.0))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawLine(QPointF(panel_x + 6, cy), QPointF(panel_x + TEXT_X - 9, cy))
                elif kind == "qubit":
                    painter.setPen(QPen(QColor(c).darker(115), 1.0))
                    painter.setBrush(QBrush(c))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                elif kind == "cbit":
                    half = ICON_R * 0.85
                    painter.setPen(QPen(QColor(c).darker(118), 1.0))
                    painter.setBrush(QBrush(c))
                    painter.drawRoundedRect(QRectF(cx_ - half, cy - half, half * 2, half * 2), 2, 2)
                elif kind == "lost":
                    fill = QColor(c)
                    fill.setAlpha(200)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(fill))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                    d = ICON_R * 0.55
                    painter.setPen(QPen(QColor(c).darker(140), 2.0))
                    painter.drawLine(QPointF(cx_ - d, cy - d), QPointF(cx_ + d, cy + d))
                    painter.drawLine(QPointF(cx_ + d, cy - d), QPointF(cx_ - d, cy + d))
                elif kind == "measured":
                    fill = QColor(c)
                    fill.setAlpha(200)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(fill))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                    r = ICON_R
                    painter.setPen(QPen(QColor(c).darker(120), 2.0))
                    painter.drawLine(QPointF(cx_ - r * 0.45, cy), QPointF(cx_ - r * 0.1, cy + r * 0.45))
                    painter.drawLine(QPointF(cx_ - r * 0.1, cy + r * 0.45), QPointF(cx_ + r * 0.5, cy - r * 0.4))
                elif kind == "halo_gate":
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(Theme.QUBIT_PRODUCT)))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                    painter.setPen(QPen(QColor(c), 1.5, Qt.PenStyle.DashLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(cx_, cy), HALO_R, HALO_R)
                elif kind == "halo_measure":
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(Theme.QUBIT_PRODUCT)))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                    painter.setPen(QPen(QColor(c), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(cx_, cy), HALO_R, HALO_R)
                elif kind == "halo_graph":
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(QColor(Theme.QUBIT_PRODUCT)))
                    painter.drawEllipse(QPointF(cx_, cy), ICON_R, ICON_R)
                    painter.setPen(QPen(QColor(c), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(cx_, cy), HALO_R - 2, HALO_R - 2)
                    painter.drawEllipse(QPointF(cx_, cy), HALO_R + 1, HALO_R + 1)
                elif kind == "packet":
                    s = ICON_R
                    diamond = QPainterPath()
                    diamond.moveTo(cx_, cy - s)
                    diamond.lineTo(cx_ + s, cy)
                    diamond.lineTo(cx_, cy + s)
                    diamond.lineTo(cx_ - s, cy)
                    diamond.closeSubpath()
                    painter.setPen(QPen(QColor(c).darker(118), 1.0))
                    painter.setBrush(QBrush(c))
                    painter.drawPath(diamond)
                painter.setPen(QPen(Theme.TEXT_SECONDARY))
                painter.drawText(
                    QRectF(panel_x + TEXT_X, cy - ROW_H / 2, panel_w - TEXT_X - 6, ROW_H),
                    Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
                cy += ROW_H

    def _draw_event_overlay(self, painter: QPainter):
        """Draw traceText events for the current timestamp in the bottom-right corner.

        Renders a semi-transparent panel listing every ``traceText`` event
        whose timestamp exactly matches the current slider position.  At most
        five events are shown; a "… +N more" line is appended when there are
        additional events.
        """
        log = self.state_manager.log_events
        hi = self.state_manager.log_count_at(self.current_time)
        lo = self.state_manager.log_count_at(self.current_time - 1)
        current_events = log[lo:hi]
        if not current_events:
            return

        MAX_BODY = 5
        font_hdr = QFont(ui_font_family(), 11)
        font_hdr.setWeight(QFont.Weight.Bold)
        font_body = QFont("Courier New", 11)
        fm_h = QFontMetrics(font_hdr)
        fm_b = QFontMetrics(font_body)
        line_h = fm_b.height() + 3

        t_us = self.current_time / 1000
        header = f"@ {t_us:.3f} \u03bcs"

        body_lines: list[str] = []
        for ev in current_events[:MAX_BODY]:
            node = ev.get("node", "")
            text = ev.get("text", "")
            body_lines.append(f"[{node}] {text}" if node else text)
        extra = len(current_events) - MAX_BODY
        if extra > 0:
            body_lines.append(f"\u2026 +{extra} more")

        PAD_X, PAD_Y = 12, 8
        all_widths = [fm_h.horizontalAdvance(header)] + [fm_b.horizontalAdvance(ln) for ln in body_lines]
        panel_w = max(all_widths) + PAD_X * 2
        panel_h = PAD_Y + fm_h.height() + len(body_lines) * line_h + PAD_Y

        margin = 12
        px = self.width() - panel_w - margin
        py = self.height() - panel_h - margin

        painter.save()
        bg = QColor(Theme.BG_MEDIUM)
        bg.setAlpha(220)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(Theme.BORDER), 1))
        painter.drawRoundedRect(px, py, panel_w, panel_h, 6, 6)

        painter.setFont(font_hdr)
        painter.setPen(QPen(QColor(Theme.PRIMARY)))
        painter.drawText(px + PAD_X, py + PAD_Y + fm_h.ascent(), header)

        painter.setFont(font_body)
        painter.setPen(QPen(QColor(Theme.TEXT_PRIMARY)))
        y0 = py + PAD_Y + fm_h.height() + 2
        for i, line in enumerate(body_lines):
            painter.drawText(px + PAD_X, y0 + i * line_h + fm_b.ascent(), line)

        painter.restore()

    def apply_theme(self):
        """Repaint the canvas with the currently active color palette.

        Call after ``toggle_dark()`` to reflect palette changes.
        """
        self.update()


__all__ = ["NetworkCanvas"]
