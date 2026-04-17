from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass, field

try:
    import serial
except Exception:
    serial = None

from .protocol import ImageChunkPacket, TelemetryPacket, parse_application_payload


TELEMETRY_FIELDS = [
    "time",
    "alt_ms5611",
    "alt_bme280",
    "pressure",
    "temperature",
    "velocity_z",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_z",
    "voltage",
    "current",
    "packets_received",
]


@dataclass
class ImageAssemblyState:
    total_chunks: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    last_update_s: float = field(default_factory=time.monotonic)


class ImageAssembler:
    def __init__(self, ttl_s: float = 30.0) -> None:
        self.ttl_s = ttl_s
        self._images: dict[int, ImageAssemblyState] = {}

    def add_chunk(self, packet: ImageChunkPacket) -> bytes | None:
        state = self._images.get(packet.image_id)
        if state is None:
            state = ImageAssemblyState(total_chunks=packet.total_chunks)
            self._images[packet.image_id] = state

        state.total_chunks = packet.total_chunks
        state.chunks[packet.chunk_index] = packet.data
        state.last_update_s = time.monotonic()

        if len(state.chunks) >= state.total_chunks:
            image_data = b"".join(state.chunks[i] for i in range(state.total_chunks) if i in state.chunks)
            self._images.pop(packet.image_id, None)
            return image_data

        self.cleanup()
        return None

    def cleanup(self) -> None:
        now = time.monotonic()
        stale_ids = [image_id for image_id, state in self._images.items() if now - state.last_update_s > self.ttl_s]
        for image_id in stale_ids:
            self._images.pop(image_id, None)


class XBeeReceiverWorker:
    def __init__(
        self,
        serial_port: str,
        baudrate: int,
        timeout_s: float,
        enable_image_transmission: bool,
        telemetry_callback,
        image_callback,
        logger,
    ) -> None:
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.enable_image_transmission = enable_image_transmission
        self.telemetry_callback = telemetry_callback
        self.image_callback = image_callback
        self.logger = logger

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

        self._assembler = ImageAssembler(ttl_s=30.0)
        self._packets_received = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    @staticmethod
    def _read_api_frame(ser: serial.Serial) -> bytes | None:
        while True:
            start = ser.read(1)
            if not start:
                return None
            if start[0] == 0x7E:
                break

        length_bytes = ser.read(2)
        if len(length_bytes) < 2:
            return None

        length = struct.unpack(">H", length_bytes)[0]
        payload = ser.read(length + 1)
        if len(payload) < length + 1:
            return None

        return b"\x7E" + length_bytes + payload

    @staticmethod
    def _parse_rx_data(raw: bytes) -> bytes | None:
        if len(raw) < 9 or raw[0] != 0x7E:
            return None

        frame_type = raw[3]
        if frame_type == 0x80:
            if len(raw) < 15:
                return None
            data = raw[14:-1]
        elif frame_type == 0x81:
            if len(raw) < 9:
                return None
            data = raw[8:-1]
        else:
            return None

        body = raw[3:-1]
        checksum = raw[-1]
        if (sum(body) + checksum) & 0xFF != 0xFF:
            return None

        return data

    def _normalize_telemetry(self, telemetry: dict[str, float | int]) -> dict[str, float | int]:
        normalized: dict[str, float | int] = {}

        try:
            normalized["time"] = int(telemetry.get("time", int(time.time() * 1000)))
        except Exception:
            normalized["time"] = int(time.time() * 1000)

        for key in TELEMETRY_FIELDS:
            if key in {"time", "packets_received"}:
                continue
            value = telemetry.get(key, 0)
            try:
                normalized[key] = float(value)
            except Exception:
                normalized[key] = 0.0

        normalized["packets_received"] = int(self._packets_received)
        return normalized

    def _handle_payload(self, payload: bytes) -> None:
        packet = parse_application_payload(payload)
        if packet is None:
            return

        self._packets_received += 1

        if isinstance(packet, TelemetryPacket):
            telemetry = self._normalize_telemetry(packet.telemetry)
            self.telemetry_callback(telemetry)
            return

        if isinstance(packet, ImageChunkPacket):
            if not self.enable_image_transmission:
                return
            image_data = self._assembler.add_chunk(packet)
            if image_data is not None:
                self.image_callback(packet.image_id, image_data)

    def _run(self) -> None:
        self.logger.info("XBee receiver worker iniciado")

        if serial is None:
            self.logger.warning("pyserial no instalado en receptor, worker serial deshabilitado")
            return

        while not self._stop_event.is_set():
            try:
                with serial.Serial(self.serial_port, self.baudrate, timeout=self.timeout_s) as ser:
                    self.logger.info("Puerto serial abierto %s @ %s", self.serial_port, self.baudrate)
                    ser.reset_input_buffer()

                    while not self._stop_event.is_set():
                        t0 = time.perf_counter()
                        raw = self._read_api_frame(ser)
                        if raw is None:
                            continue
                        payload = self._parse_rx_data(raw)
                        if payload is None:
                            continue
                        self._handle_payload(payload)
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        self.logger.info("rx_step_ms=%.2f payload_bytes=%s", elapsed_ms, len(payload))
            except Exception as exc:
                self.logger.warning("Error receptor XBee (%s). Reintentando en 2s", exc)
                self._stop_event.wait(2.0)

        self.logger.info("XBee receiver worker detenido")
