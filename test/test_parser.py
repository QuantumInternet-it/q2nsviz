# -----------------------------------------------------------------------------
# Q2NSViz - Quantum Network Trace Visualizer
# Copyright (c) 2026 QuantumInternet.it
#
# This program is released under the MIT License - see LICENSE for details.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path

import pytest

from q2nsviz import EventFileParser

_NODE_EVENT: dict = {"type": "createNode", "t_ns": 0, "label": "A", "x": 0.0, "y": 0.0}


class TestParse:
    def test_json_array(self):
        """Test that a JSON array parses correctly and that invalid array syntax reports errors."""
        events, errors = EventFileParser.parse(json.dumps([_NODE_EVENT]))
        assert events == [_NODE_EVENT]
        assert errors == []
        events, errors = EventFileParser.parse("[not valid json]")
        assert events == []
        assert len(errors) >= 1

    def test_ndjson(self):
        """Test NDJSON parsing: one object per line, blank lines skipped, and invalid
        lines reported as errors without discarding the valid ones.
        """
        valid = json.dumps(_NODE_EVENT)
        events, errors = EventFileParser.parse(f"\n{valid}\n\n{valid}\n{valid}\n")
        assert len(events) == 3
        assert errors == []
        events, errors = EventFileParser.parse(f"{valid}\n{{broken\n{valid}")
        assert len(events) == 2
        assert len(errors) == 1

    def test_empty_and_invalid_input(self):
        """Test that empty input yields no events and no errors, while non-JSON
        content yields no events and at least one error.
        """
        assert EventFileParser.parse("") == ([], [])
        events, errors = EventFileParser.parse("not json at all")
        assert events == []
        assert len(errors) >= 1


class TestLoadFromFile:
    def test_load_from_file_roundtrip(self, tmp_path: Path):
        """Test that a trace written to disk loads back with all events and no errors."""
        payload = [_NODE_EVENT, _NODE_EVENT]
        trace_file = tmp_path / "trace.json"
        trace_file.write_text(json.dumps(payload), encoding="utf-8")
        events, errors = EventFileParser.load_from_file(str(trace_file))
        assert len(events) == 2
        assert errors == []

    def test_load_from_file_missing_raises(self, tmp_path: Path):
        """Test that loading from a missing file raises an OSError."""
        missing = tmp_path / "does_not_exist.json"
        with pytest.raises(OSError):
            EventFileParser.load_from_file(str(missing))
