"""Every example in the protocol document validates (valid) or is rejected (invalid)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from bcs_protocol.validate import ProtocolError, parse_message

DOC = Path(__file__).resolve().parents[4] / "docs" / "protocol" / "sentinel-protocol-v1.md"
CHANNELS = {"telemetry", "status", "event", "cmd", "ack", "config"}
PATTERN = re.compile(
    r"<!--\s*example:(?P<channel>\w+):(?P<kind>valid|invalid)\s*-->\s*```json\r?\n(?P<body>.*?)```", re.DOTALL
)


@dataclass(frozen=True)
class Example:
    channel: str
    valid: bool
    json: str


def extract_examples(text: str) -> list[Example]:
    return [Example(m["channel"], m["kind"] == "valid", m["body"]) for m in PATTERN.finditer(text)]


def _examples() -> list[Example]:
    return extract_examples(DOC.read_text(encoding="utf-8"))


def test_every_channel_has_a_valid_and_an_invalid_example():
    blocks = _examples()
    assert {b.channel for b in blocks if b.valid} >= CHANNELS
    assert {b.channel for b in blocks if not b.valid} >= CHANNELS


def test_every_example_tag_is_followed_by_a_json_block():
    text = DOC.read_text(encoding="utf-8")
    assert text.count("<!-- example:") == len(extract_examples(text))


def test_protocol_doc_examples_validate():
    blocks = _examples()
    assert blocks
    for b in blocks:
        if b.valid:
            parse_message(b.channel, b.json.encode())
        else:
            with pytest.raises(ProtocolError):
                parse_message(b.channel, b.json.encode())
