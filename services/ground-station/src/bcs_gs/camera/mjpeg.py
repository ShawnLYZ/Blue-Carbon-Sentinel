"""Incremental parser for the camera's ``multipart/x-mixed-replace`` stream (addendum L3)."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_HEADER_BYTES = 8192
MAX_BODY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Part:
    headers: dict[str, str] = field(default_factory=dict)  # keys lower-cased
    body: bytes = b""


class MjpegParser:
    """Feed arbitrary chunks, get complete parts. The body is taken by ``Content-Length`` when the
    part has one, so JPEG bytes that happen to contain the boundary are never split. Without a
    length the body ends at the next boundary line."""

    def __init__(self, boundary: bytes) -> None:
        self._delim = b"--" + boundary.lstrip(b"-")
        self._buf = bytearray()
        self._state = "seek"
        self._headers: dict[str, str] = {}
        self._length: int | None = None

    def _resync(self) -> None:
        self._state = "seek"
        self._headers = {}
        self._length = None

    def feed(self, chunk: bytes) -> list[Part]:
        buf = self._buf
        buf += chunk
        out: list[Part] = []
        while True:
            if self._state == "seek":
                i = buf.find(self._delim)
                if i < 0:
                    keep = len(self._delim) - 1
                    if len(buf) > keep:
                        del buf[: len(buf) - keep]
                    break
                del buf[: i + len(self._delim)]
                self._state = "headers"
            elif self._state == "headers":
                if buf[:2] == b"--":  # closing delimiter
                    del buf[:2]
                    self._state = "seek"
                    continue
                if len(buf) < 2 and buf[:1] == b"-":
                    break
                end = buf.find(b"\r\n\r\n")
                if end < 0:
                    if len(buf) > MAX_HEADER_BYTES:
                        buf.clear()
                        self._resync()
                    break
                block = bytes(buf[:end]).decode("latin-1")
                del buf[: end + 4]
                headers: dict[str, str] = {}
                for line in block.split("\r\n"):
                    key, sep, value = line.partition(":")
                    if sep:
                        headers[key.strip().lower()] = value.strip()
                self._headers = headers
                try:
                    length: int | None = int(headers["content-length"])
                except (KeyError, ValueError):
                    length = None
                if length is not None and not 0 <= length <= MAX_BODY_BYTES:
                    self._resync()
                    continue
                self._length = length
                self._state = "body"
            else:  # body
                if self._length is not None:
                    if len(buf) < self._length:
                        break
                    body = bytes(buf[: self._length])
                    del buf[: self._length]
                else:
                    j = buf.find(self._delim)
                    if j < 0:
                        if len(buf) > MAX_BODY_BYTES:
                            buf.clear()
                            self._resync()
                        break
                    body = bytes(buf[:j])
                    del buf[:j]
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                out.append(Part(self._headers, body))
                self._resync()
        return out
