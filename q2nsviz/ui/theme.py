# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

from PyQt6.QtGui import QColor

SANS_FONT = "Arial,Liberation Sans,DejaVu Sans,Helvetica,sans-serif"


def ui_font_family() -> str:
    """Native UI font family matching the application font, for QPainter text."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    return app.font().family() if app is not None else SANS_FONT


# ---------------------------------------------------------------------------
# Palette definitions
# ---------------------------------------------------------------------------

_LIGHT: dict[str, QColor] = {
    "BG_DARK": QColor("#f5f7fa"),  # canvas background
    "BG_MEDIUM": QColor("#ffffff"),  # node background, tooltip
    "BG_LIGHT": QColor("#fafbfc"),  # sidebar, legend, tooltip hover
    "BG_TOPBAR": QColor("#ffffff"),  # top bar background
    "PRIMARY": QColor("#334261"),  # buttons, highlights (Qnattynet navy)
    "PRIMARY_HOVER": QColor("#3d4f76"),  # button hover state (lighter navy)
    "PRIMARY_DARK": QColor("#27324b"),  # button active/pressed state (darker navy)
    "QUANTUM_CHANNEL": QColor("#8250df"),  # quantum channel
    "CLASSICAL_CHANNEL": QColor("#d9b112"),  # classical channel
    "ENTANGLEMENT": QColor("#9527a3"),  # entanglement
    "TEXT_PRIMARY": QColor("#334261"),  # primary text
    "TEXT_SECONDARY": QColor("#57606a"),  # secondary text
    "TEXT_MUTED": QColor("#6e7781"),  # muted text
    "NODE_TEXT": QColor("#334261"),  # node labels
    "BORDER": QColor("#d0d7de"),  # borders and dividers
    "QUBIT_PRODUCT": QColor("#0969da"),  # isolated qubit
    "QUBIT_ENTANGLED": QColor("#9527a3"),  # qubit in an entanglement cluster
    "QUBIT_MEASURED": QColor("#8c959f"),  # measured and removed qubit marker
    "QUBIT_LOST": QColor("#da3633"),  # lost marker
    "HALO_GATE": QColor("#475569"),  # quantum-gate processing ring (dashed)
    "HALO_MEASURE": QColor("#0e7c86"),  # measure operation ring (solid)
    "HALO_GRAPH_MEASURE": QColor("#cf9a27"),  # graphMeasure operation ring (double)
    "PACKET_CLASSICAL": QColor("#d9b112"),  # unknown / generic classical
    "PACKET_TCP": QColor("#1a7f37"),  # TCP classical packet
    "PACKET_UDP": QColor("#bc4c00"),  # UDP classical packet
    "CBIT": QColor("#cc6600"),  # classical bit square marker
}

_DARK: dict[str, QColor] = {
    "BG_DARK": QColor("#0d1117"),  # canvas background
    "BG_MEDIUM": QColor("#21262d"),  # node background, tooltip
    "BG_LIGHT": QColor("#2d333b"),  # sidebar, legend, tooltip hover
    "BG_TOPBAR": QColor("#161b22"),  # top bar background (dark surface, matches canvas family)
    "PRIMARY": QColor("#334261"),  # buttons, highlights (Qnattynet navy, lighter for dark bg)
    "PRIMARY_HOVER": QColor("#3d4f76"),  # button hover state (lighter navy)
    "PRIMARY_DARK": QColor("#27324b"),  # button active/pressed state (darker navy)
    "QUANTUM_CHANNEL": QColor("#a371f7"),  # quantum channel
    "CLASSICAL_CHANNEL": QColor("#e3b341"),  # classical channel
    "ENTANGLEMENT": QColor("#d2a8ff"),  # entanglement
    "TEXT_PRIMARY": QColor("#e6edf3"),  # primary text
    "TEXT_SECONDARY": QColor("#8d96a0"),  # secondary text
    "TEXT_MUTED": QColor("#6e7681"),  # muted text
    "NODE_TEXT": QColor("#e6edf3"),  # node labels
    "BORDER": QColor("#30363d"),  # borders and dividers
    "QUBIT_PRODUCT": QColor("#388bfd"),  # isolated qubit
    "QUBIT_ENTANGLED": QColor("#d2a8ff"),  # qubit in an entanglement cluster
    "QUBIT_MEASURED": QColor("#6e7681"),  # measured and removed qubit marker
    "QUBIT_LOST": QColor("#f85149"),  # lost marker
    "HALO_GATE": QColor("#94a3b8"),  # quantum-gate processing ring (dashed)
    "HALO_MEASURE": QColor("#39c5bb"),  # measure operation ring (solid)
    "HALO_GRAPH_MEASURE": QColor("#e3b341"),  # graphMeasure operation ring (double)
    "PACKET_CLASSICAL": QColor("#e3b341"),  # unknown / generic classical
    "PACKET_TCP": QColor("#3fb950"),  # TCP classical packet
    "PACKET_UDP": QColor("#f0883e"),  # UDP classical packet
    "CBIT": QColor("#ffa657"),  # classical bit square marker
}

_active_palette: dict[str, QColor] = _LIGHT


def toggle_dark() -> bool:
    """Switch the active palette between light and dark.

    @returns  ``True`` if the palette is now dark; ``False`` if light.
    """
    global _active_palette
    _active_palette = _DARK if _active_palette is _LIGHT else _LIGHT
    return _active_palette is _DARK


def is_dark() -> bool:
    """Return ``True`` when the dark palette is active."""
    return _active_palette is _DARK


# ---------------------------------------------------------------------------
# Theme proxy --- exposes palette entries as class-level attributes.
# All consumer code accesses colors via ``Theme.X``
# ---------------------------------------------------------------------------


class _ThemeMeta(type):
    """Metaclass that forwards attribute access to the active palette dict."""

    def __getattr__(cls, name: str) -> QColor:
        try:
            return _active_palette[name]
        except KeyError:
            raise AttributeError(f"Theme has no color attribute '{name}'") from None


class Theme(metaclass=_ThemeMeta):
    """Semantic color palette for Q2NSViz.

    Access colors as class attributes (e.g. ``Theme.BG_DARK``).  The active
    palette (light or dark) is selected by calling ``toggle_dark()``.

    **Qubit semantic states**

    | Constant | Semantic |
    |---|---|
    | ``QUBIT_PRODUCT`` | Isolated qubit (no entanglement) |
    | ``QUBIT_ENTANGLED`` | Qubit in an entanglement cluster |
    | ``QUBIT_MEASURED`` | Measured and removed qubit marker |
    | ``QUBIT_LOST`` | Lost qubit (removed without measurement) marker |

    **Operation halos** (transient rings marking processing time during a
    duration_ns window; entanglement itself is shown by qubit color, not a ring)

    | Constant | Semantic | Symbol |
    |---|---|---|
    | ``HALO_GATE`` | quantum-gate processing (``entangle`` event) | dashed single |
    | ``HALO_MEASURE`` | ``measure`` operation ring | solid single |
    | ``HALO_GRAPH_MEASURE`` | ``graphMeasure`` operation ring | solid double |

    **Classical packet types**

    | Constant | Semantic |
    |---|---|
    | ``PACKET_CLASSICAL`` | Unknown or generic classical packet |
    | ``PACKET_TCP`` | TCP classical packet |
    | ``PACKET_UDP`` | UDP classical packet |
    """


__all__ = ["SANS_FONT", "Theme", "is_dark", "toggle_dark", "ui_font_family"]
