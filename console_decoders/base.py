from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SerialConfig:
    baud: int = 9600
    bytesize: int = 8
    parity: str = 'E'
    stopbits: int = 1


class ConsoleDecoder(ABC):
    """Abstract base for timing-console serial decoders.

    Implementors receive raw byte packets and return structured update dicts
    whose keys match the scoreboard's update_scoreboard event payload.
    No web-framework, transport, or app-layer dependencies belong here.
    """

    @property
    @abstractmethod
    def serial_config(self) -> SerialConfig:
        """Serial port parameters required by this console."""
        ...

    @abstractmethod
    def is_packet_start(self, byte: int, buffer: list[int]) -> bool:
        """Return True if byte begins a new packet, flushing any buffered data first.

        Called by the worker for every incoming byte before it is appended to
        the buffer.  Implementations should inspect the byte (and optionally the
        current buffer contents) to detect packet boundaries.

        Examples:
          - CTS Gen6: return bool(byte & 0x80)   — high bit marks new packet
          - Omnisport 2000: return byte == 0x16  — SYN byte starts a frame
        """
        ...

    @property
    def post_open_bytes(self) -> bytes:
        """Bytes to write immediately after the serial port is opened.

        Override in decoders that must send an initialization sequence to the
        console before it starts streaming data (e.g. CTS Gen7).
        Default: empty (no initialization required).
        """
        return b''

    @property
    def max_packet_bytes(self) -> int:
        """Maximum number of bytes in one packet before forcing a flush.

        Override in subclasses when the protocol has a known fixed or maximum
        packet length.  The worker flushes the buffer when this limit is reached
        even if no packet-start byte was seen.  Defaults to 256.
        """
        return 256

    @abstractmethod
    def feed(self, packet: list[int]) -> dict:
        """Decode one assembled packet.

        Returns an update dict (subset of keys from the update_scoreboard
        payload).  Special keys consumed by the app layer before emitting:
          - 'event_changed': (event_num, heat_num) — new event/heat detected;
            app should load names, seed times, heat_time, etc. then call
            set_seed_times().
          - 'dismiss_overlay': True — a lane just started running; app should
            dismiss any active overlay.

        For consoles that transmit split times natively, include
        'lane_splits{n}' in the returned dict with the cumulative split count.

        Returns {} when the packet produces nothing of interest.
        """
        ...

    @abstractmethod
    def reset_lanes(self) -> dict:
        """Reset per-race lane state.

        Returns the update dict for those resets so the app can emit them.
        Called by the app layer when a race restarts unexpectedly.
        """
        ...

    @abstractmethod
    def race_finished(self) -> bool:
        """True when every lane with a time has a final place and is stopped."""
        ...

    @abstractmethod
    def set_seed_times(self, times: dict) -> None:
        """Supply seed times for the current heat.

        times: {lane_idx: time_str} — called by the app layer after an
        event_changed signal, once it has looked up the Lenex/HyTek data.
        """
        ...

    @abstractmethod
    def configure(self, cfg: dict) -> None:
        """Update runtime configuration (num_lanes, split thresholds, etc.)."""
        ...

    @abstractmethod
    def get_lane_time(self, lane_idx: int) -> str:
        """Return the formatted finish/split time for lane_idx (1-based)."""
        ...

    @abstractmethod
    def get_lane_place(self, lane_idx: int) -> str:
        """Return the place string (' ' if not yet placed) for lane_idx (1-based)."""
        ...
